"""Private per-account drafts with atomic writes and delayed disk work."""
import asyncio
import json
from pathlib import Path
import os
import shutil
import tempfile
import threading
import uuid

from telethon import errors as _tl_errors

from .preferences import write_json

# Per-chat refusals that retrying cannot fix. Anything else (offline, timeouts,
# FLOOD_WAIT, server errors) keeps the original stop-and-retry-later behaviour.
PERMANENT_DRAFT_ERRORS = tuple(getattr(_tl_errors, name) for name in (
    'ChatAdminRequiredError', 'ChatWriteForbiddenError', 'ChannelPrivateError', 'PeerIdInvalidError',
    'UserBannedInChannelError', 'ChatRestrictedError', 'ChannelInvalidError', 'ChatIdInvalidError',
    'InputUserDeactivatedError', 'ChatGuestSendForbiddenError', 'ChatSendPlainForbiddenError')
    if hasattr(_tl_errors, name))


def valid_record(record):
    if not isinstance(record, dict) or not isinstance(record.get('text', ''), str):
        return None
    text = record.get('text', '')
    result = {'text': text, 'files': [], 'custom': [], 'formats': [], 'reply': None,
              'pending': record.get('pending') is True, 'unsupported': record.get('unsupported') is True}
    if 'photo_quality' in record and record['photo_quality'] in (None, 'sd', 'hd', 'original'):
        result['photo_quality'] = record['photo_quality']
    files = record.get('files', [])
    if isinstance(files, list):
        result['files'] = [p for p in files if isinstance(p, str) and len(p)<=4096 and '\0' not in p]
    for kind in ('custom', 'formats'):
        spans = record.get(kind, [])
        if not isinstance(spans, list):
            continue
        for span in spans:
            if not isinstance(span, (list, tuple)) or len(span)!=4:
                continue
            start, end, value, extra = span
            if type(start) is not int or type(end) is not int or not 0<=start<end<=len(text) or not isinstance(extra, str):
                continue
            if kind=='custom' and (type(value) is not int or value<=0 or text[start:end]!=extra):
                continue
            if kind=='formats' and value not in ('bold', 'italic', 'underline', 'strike', 'code', 'spoiler', 'link', 'quote', 'collapsed_quote'):
                continue
            result[kind].append((start, end, value, extra))
    if type(record.get('reply')) is int and record['reply']>0:
        result['reply'] = record['reply']
    return result


def copy_record(record):
    """Validated spans contain immutable scalars; only their lists need copies."""
    if record is None:
        return None
    return {**record, 'files': list(record['files']), 'custom': list(record['custom']),
            'formats': list(record['formats'])}


def copy_records(records):
    return {account: {peer: copy_record(record) for peer, record in chats.items()}
            for account, chats in records.items()}


class DraftStore:
    def __init__(self, root, demo=False):
        self.path = Path(root)/'drafts.json'
        self.demo = demo
        self._lock = threading.RLock()
        self._flush_lock = threading.Lock()
        self._assets = {}
        self._ready_assets = set()
        self._managed_assets = set()
        self._active_assets = set()
        self._pending_keys = set()
        self._revision = self._persisted_revision = 0
        self._gc_dirty = False
        self.records = {}
        self.load_error = None
        self.recovery_path = None
        self._recovery_pending = False
        source = {} if demo else self._read_records()
        for account, chats in source.items():
            if not isinstance(account, str) or not isinstance(chats, dict):
                self._damaged(ValueError('Invalid account draft data'))
                continue
            valid = {}
            for peer, record in chats.items():
                try:
                    key = str(int(peer))
                except (ValueError, TypeError):
                    self._damaged(ValueError('Invalid draft peer'))
                    continue
                checked = valid_record(record)
                if checked is not None:
                    valid[key] = checked
                    normalized = {**checked, 'custom': [list(span) for span in checked['custom']],
                                  'formats': [list(span) for span in checked['formats']]}
                    if any(field not in normalized or value != normalized[field] for field, value in record.items()):
                        self._damaged(ValueError('Damaged draft fields were preserved for recovery'))
                else:
                    self._damaged(ValueError('Invalid draft record'))
            self.records[account] = valid
            self._pending_keys.update((account, peer) for peer, record in valid.items() if record['pending'])
        self._managed_assets.update(path for path in self._record_files(self.records) if self._owned_asset(path))
        # A malformed recovery document may refer to attachments we cannot
        # decode. Keep its assets until the user has recovered/removed the copy.
        self._protect_recovery_assets = self.load_error is not None or (not demo and any(
            self.path.parent.glob('drafts-recovery-*.json')))
        self._persisted = copy_records(self.records)

    def _read_records(self):
        # Drafts are user data, not bounded application settings. Applying the
        # settings reader's 2 MiB ceiling silently discards valid large stores.
        try:
            with self.path.open('r', encoding='utf-8') as stream:
                source = json.load(stream)
            if not isinstance(source, dict):
                raise ValueError('Invalid draft document')
            return source
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, RecursionError) as error:
            self._damaged(error)
            return {}

    def _damaged(self, error):
        if self.load_error is None:
            self.load_error = error
            self.recovery_path = self.path.with_name('drafts-recovery-' + uuid.uuid4().hex + '.json')
        self._recovery_pending = True

    @staticmethod
    def _record_files(records):
        return {path for chats in records.values() for record in chats.values() for path in record['files']}

    def _owned_asset(self, path):
        path = Path(path)
        return path.parent == self.path.parent/'draft-assets' and len(path.stem) == 32 and all(
            character in '0123456789abcdef' for character in path.stem)

    def set_active_assets(self, paths):
        """Keep attachments held by visible composers, including duplicate windows."""
        with self._lock:
            active = {str(path) for path in paths}
            if active != self._active_assets:
                self._active_assets = active
                self._gc_dirty = True

    def get(self, account, peer):
        with self._lock:
            return copy_record(self.records.get(account, {}).get(str(peer)))

    def pending_records(self, account=None):
        """Snapshot just dirty cloud drafts without walking every saved chat."""
        with self._lock:
            result = {}
            for owner, peer in self._pending_keys:
                if account is None or owner == account:
                    result.setdefault(owner, {})[peer] = copy_record(self.records[owner][peer])
            return result

    def mark_synced(self, account, peer, expected):
        with self._lock:
            current = self.records.get(account, {}).get(str(peer))
            if current and current['pending'] and draft_content(current) == draft_content(expected):
                current['pending'] = False
                self._pending_keys.discard((account, str(peer)))
                self._revision += 1

    def put(self, account, peer, record, pending=None):
        checked = valid_record(record)
        if checked is None:
            raise ValueError('Invalid draft')
        with self._lock:
            peer = str(peer)
            old = self.records.get(account, {}).get(peer)
            if pending is not None:
                checked['pending'] = pending
            elif old and draft_content(old)==draft_content(checked):
                checked['pending'] = old['pending']
            elif old is None and not checked['text'] and not checked['reply']:
                checked['pending'] = False
            else:
                checked['pending'] = True
            if checked['text'] or checked['files'] or checked['reply'] or checked['pending'] or checked['unsupported']:
                if old != checked:
                    self.records.setdefault(account, {})[peer] = checked
                    self._revision += 1
                    self._gc_dirty = True
                if checked['pending']:
                    self._pending_keys.add((account, peer))
                else:
                    self._pending_keys.discard((account, peer))
            else:
                if self.records.get(account, {}).pop(peer, None) is not None:
                    self._revision += 1
                    self._gc_dirty = True
                self._pending_keys.discard((account, peer))

    def remove(self, account, peer=None):
        with self._lock:
            if peer is None:
                removed = self.records.pop(account, None)
                if removed is not None:
                    self._pending_keys.difference_update((account, key) for key in removed)
            else:
                removed = self.records.get(account, {}).pop(str(peer), None)
                self._pending_keys.discard((account, str(peer)))
            if removed is not None:
                self._revision += 1
                self._gc_dirty = True

    def remove_account(self, account):
        """Purge an explicitly logged-out identity and its private window slots."""
        linked = 'linked:' + account
        with self._lock:
            for owner in tuple(self.records):
                suffix = owner[len(linked) + 1:] if owner.startswith(linked + ':') else ''
                if owner in (account, linked) or (suffix.isascii() and suffix.isdecimal() and suffix.strip('0')):
                    self.remove(owner)

    def flush(self):
        if self.demo:
            return
        # Only writers wait for disk work. The UI can continue taking snapshots
        # and editing text while a large attachment is copied in this thread.
        with self._flush_lock:
            with self._lock:
                unchanged = self._revision == self._persisted_revision and not self._recovery_pending
            if unchanged:
                if self._gc_dirty:
                    self._collect_assets()
                return
            while True:
                with self._lock:
                    files = self._record_files(self.records)
                    pending = [(source, self._assets[source]) for source in files
                               if source in self._assets and source not in self._ready_assets]
                    if not pending:
                        # A snapshot may have reused a source while its first copy
                        # was finishing. Publish only paths with a complete copy.
                        for chats in self.records.values():
                            for record in chats.values():
                                record['files'] = [str(self._assets[p]) if p in self._ready_assets else p for p in record['files']]
                        snapshot = copy_records(self.records)
                        snapshot_revision = self._revision
                        break
                for source, target in pending:
                    self._copy_asset(Path(source), target)
                    with self._lock:
                        self._ready_assets.add(source)
                        self._managed_assets.add(str(target))
                        self._gc_dirty = True
            if self._recovery_pending:
                # Keep the exact original bytes, including malformed records,
                # before replacing anything. Failed backups leave it untouched.
                self._copy_asset(self.path, self.recovery_path)
            if snapshot != self._persisted or self._recovery_pending:
                write_json(self.path, snapshot)
                self._persisted = snapshot
                self._recovery_pending = False
            self._persisted_revision = snapshot_revision
            if self._gc_dirty:
                self._collect_assets()

    def _collect_assets(self):
        # Only assets known to this store are eligible. Unknown files and assets
        # belonging to a damaged/recovery document are deliberately untouched.
        with self._lock:
            self._gc_dirty = False
            if self._protect_recovery_assets or not self._managed_assets:
                return
            referenced = self._record_files(self.records) | self._record_files(self._persisted) | self._active_assets
            referenced.update(str(self._assets[source]) for source in tuple(referenced) if source in self._assets)
            for target in self._managed_assets - referenced:
                try:
                    Path(target).unlink(missing_ok=True)
                except OSError:
                    self._gc_dirty = True
                    continue  # Windows may still hold an upload handle; retry later.
                self._managed_assets.discard(target)
                for source in [source for source, path in self._assets.items() if str(path) == target]:
                    self._assets.pop(source)
                    self._ready_assets.discard(source)

    def register_asset(self, source):
        """Record an app-owned temporary file without touching its contents."""
        source = str(source)
        with self._lock:
            target = self._assets.get(source)
            if target is None:
                target = self._assets[source] = self.path.parent/'draft-assets'/(uuid.uuid4().hex+Path(source).suffix)
            return str(target) if source in self._ready_assets else source

    @staticmethod
    def _copy_asset(source, target):
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(prefix='draft-', suffix='.part', dir=target.parent)
        os.close(descriptor)
        temporary = Path(temporary)
        try:
            shutil.copyfile(source, temporary)
            with temporary.open('rb+') as stream:
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)


def draft_content(record):
    return tuple(record.get(k) for k in ('text', 'custom', 'formats', 'reply'))


class DraftManager:
    def __init__(self, app, store=None):
        self.app = app
        self.store = store if store is not None else DraftStore(app.preferences.path.parent, demo=app.demo)
        self.job = None
        self.loaded = set()
        self.sync_lock = None
        self._remote_applying = False
        self._remote_versions = {}
        self.close_pending = False
        self.close_error = None
        self._load_warning_shown = False
        self._persist_running = False
        self._persist_requested = False

    def restore_account(self):
        app = self.app
        for peer, record in self.store.records.get(app.ui_account, {}).items():
            ident = int(peer)
            files = [Path(p) for p in record['files'] if Path(p).is_file()]
            app.drafts[ident] = (record['text'], files[0] if len(files)==1 else tuple(files) if files else None)
            app.rich_drafts[(app.ui_account, ident)] = record['custom']
            app.format_drafts[(app.ui_account, ident)] = record['formats']
            if record['reply']:
                if not hasattr(app, 'reply_drafts'):
                    app.reply_drafts = {}
                app.reply_drafts[(app.ui_account, ident)] = record['reply']

    def bind(self):
        self.app.editor.bind('<<Modified>>', self.changed, add='+')
        if self.store.load_error is not None and not self._load_warning_shown:
            self._load_warning_shown = True
            from .interface_layout import caption
            warning = ValueError(caption('Damaged local drafts. The original file is preserved; recovery copy: ',
                'Borradores locales dañados. Se conserva el original; copia de recuperación: ') + str(self.store.recovery_path))
            self.app.root.after_idle(lambda: self.failed(warning))

    def changed(self, event=None):
        if self.app.closed or self.app.closing or self._remote_applying:
            return
        if event is not None and event.widget.winfo_exists():
            if not event.widget.edit_modified():
                return
            event.widget.edit_modified(False)
        if self.job is not None:
            self.app.root.after_cancel(self.job)
        self.job = self.app.root.after(600, self.persist_async)

    def snapshot(self):
        app = self.app
        from .attachments import paths_in
        logging_out = getattr(app, '_logging_out_accounts', ())
        active_files = [] if app.ui_account in logging_out else list(paths_in(getattr(app, 'attachment', None)))
        for window in getattr(app, '_chat_windows', ()):
            if not window.closed and window.account not in logging_out:
                active_files.extend(paths_in(window.attachment))
        self.store.set_active_assets(active_files)
        if app.ui_account in logging_out:
            return
        if app.active is None or getattr(app, 'stage', None)!='ready' or not hasattr(app, 'editor') or not app.editor.winfo_exists():
            return
        files = []
        roots = [Path(d.name).resolve() for d in app.media_temps]
        for source in paths_in(app.attachment):
            source = Path(source).resolve()
            if not app.demo and any(source.is_relative_to(root) for root in roots):
                files.append(self.store.register_asset(source))
            else:
                files.append(str(source))
        old = self.store.get(app.ui_account, app.active)
        record = {'text': app.editor.get('1.0', 'end-1c'),
            'files': files, 'custom': app.snapshot_custom(), 'formats': app.snapshot_formats(),
            'reply': getattr(app, 'reply_drafts', {}).get((app.ui_account, app.active)),
            'unsupported': bool(old and old['unsupported'])}
        if files:
            from .attachments import photo_quality_for
            record['photo_quality']=photo_quality_for(app)
        self.store.put(app.ui_account, app.active, record)
        if hasattr(app, 'drafts'):
            app.drafts[app.active] = (record['text'], getattr(app, 'attachment', None))
        state = getattr(app, 'account_states', {}).get(app.ui_account)
        if state is not None and isinstance(state.get('drafts'), dict):
            state['drafts'][app.active] = (record['text'], getattr(app, 'attachment', None))

    def persist_async(self):
        self.job = None
        try:
            self.snapshot()
        except (OSError, ValueError) as exc:
            self.failed(exc)
            return
        if self._persist_running:
            self._persist_requested = True
            return
        self._persist_running = True
        self._persist_requested = False
        persisted = False
        async def flush():
            nonlocal persisted
            await asyncio.to_thread(self.store.flush)
            persisted = True
            await self.sync_pending()
        def finished(error=None):
            self._persist_running = False
            if error is not None:
                self.failed(error, local=not persisted)
            if self._persist_requested and not self.app.closed and not self.app.closing:
                self.persist_async()
        self.app.worker.submit(flush(), lambda _: finished(), finished)

    def failed(self, exc, *, local=False):
        from .interface_layout import caption
        from .pending_actions import transport_failure
        if not local and transport_failure(exc):
            # 1.5.3: offline. The draft is already saved on this device and is
            # synchronised with Telegram when the connection returns.
            self.app.status.set(caption('Draft saved on this device; it syncs when the connection returns.',
                                        'Borrador guardado en este dispositivo; se sincroniza al volver la conexión.'))
            return
        self.app.status.set(caption('Draft could not be saved: ', 'No se pudo guardar el borrador: ')+str(exc))

    def flush(self):
        if self.job is not None:
            self.app.root.after_cancel(self.job)
            self.job = None
        self.snapshot()
        self.store.flush()

    def capture_close(self):
        """Called on Tk: capture widgets, then let flush_close do disk work."""
        if self.job is not None:
            self.app.root.after_cancel(self.job)
            self.job = None
        self.snapshot()
        self.close_error = None
        self.close_pending = True

    async def flush_close(self):
        task = asyncio.create_task(asyncio.to_thread(self.store.flush))
        try:
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                # Cancelling asyncio.to_thread does not stop its copy. Wait for
                # its durable result before allowing temporary files to vanish.
                await task
                raise
        except BaseException as exc:
            self.close_error = exc
            raise
        finally:
            self.close_pending = False

    async def sync_pending(self, account=None, *, allow_logout=False):
        if self.app.demo:
            return
        if self.sync_lock is None:
            self.sync_lock = asyncio.Lock()
        async with self.sync_lock:
            failures = []
            records = self.store.pending_records(account)
            for owner, chats in records.items():
                if account is not None and owner != account:
                    continue
                if owner not in self.app.service.entries or (not allow_logout and owner in getattr(self.app, '_logging_out_accounts', ())):
                    continue
                service = self.app.service.services.get(owner)
                backend = getattr(service, 'backend', None)
                if backend is None:
                    continue
                rejected = self._rejected_drafts()
                for peer, record in chats.items():
                    if not record['pending'] or record['unsupported']:
                        continue
                    content = draft_content(record)
                    if rejected.get((owner, str(peer))) == content:
                        # Telegram already refused exactly this draft for this
                        # chat (no permission, chat gone). Keep it locally and do
                        # not resend it on every keystroke elsewhere; editing it
                        # (different content) tries again.
                        continue
                    try:
                        await backend.save_draft(int(peer), record['text'], record['formats'], record['custom'], record['reply'])
                    except PERMANENT_DRAFT_ERRORS as exc:
                        # Before 1.3.2 this broke the loop: one channel without
                        # write permission blocked every other chat's draft of
                        # the account, and was retried forever.
                        rejected[(owner, str(peer))] = content
                        if allow_logout:
                            failures.append(exc)
                        continue
                    except Exception as exc:
                        failures.append(exc)
                        break  # One offline/rate-limited account must not block other accounts.
                    rejected.pop((owner, str(peer)), None)
                    self.store.mark_synced(owner, peer, record)
            await asyncio.to_thread(self.store.flush)
            if failures:
                raise failures[0]
            if allow_logout and account is not None:
                with self.store._lock:
                    unsaved = any(record['pending'] for record in self.store.records.get(account, {}).values())
                if unsaved:
                    from .interface_layout import caption
                    raise ValueError(caption(
                        'Some pending drafts could not be synchronized safely. Logout was cancelled; your local drafts are preserved.',
                        'No se pudieron sincronizar de forma segura todos los borradores pendientes. Se canceló el cierre de sesión y se conservan los borradores locales.'))

    def _rejected_drafts(self):
        rejected = getattr(self, '_permanent_rejections', None)
        if rejected is None:
            rejected = self._permanent_rejections = {}
        while len(rejected) > 512:
            rejected.pop(next(iter(rejected)))
        return rejected

    def pull(self, force=False):
        app = self.app
        if app.demo or getattr(app, 'stage', None)!='ready':
            return
        account, backend = app.ui_account, app.service.backend
        key = (account, id(backend))
        if key in self.loaded and not force:
            return
        self.loaded.add(key)
        versions = {peer: version for (owner, peer), version in self._remote_versions.items() if owner == account}
        def loaded(records):
            # GetAllDrafts is a full snapshot. Missing clean drafts were cleared
            # on another client while this app was offline. Keep pending edits.
            with self.store._lock:
                previous = {int(peer) for peer in self.store.records.get(account, {})}
            for peer in previous | {int(peer) for peer in records}:
                if self._remote_versions.get((account, peer), 0) != versions.get(peer, 0):
                    continue  # A newer push update won while this snapshot was in flight.
                if peer not in records:
                    old = self.store.get(account, peer)
                    if old and old.get('files'):
                        continue  # Local attachments must not be deleted by cloud snapshot
                self.remote(account, peer, records.get(peer, {'text': ''}), from_snapshot=True)
            async def flush_store():
                await asyncio.to_thread(self.store.flush)
            self.app.worker.submit(flush_store(), lambda _: None, self.failed)
        def failed(exc):
            self.loaded.discard(key)
            self.failed(exc)
        app.worker.submit(backend.fetch_drafts(), loaded, failed)

    def remote(self, account, peer, remote, *, from_snapshot=False):
        app = self.app
        if account not in app.service.entries or account in getattr(app, '_logging_out_accounts', ()):
            return  # Late updates must not resurrect a logged-out account's data.
        if not from_snapshot:
            key = (account, peer)
            self._remote_versions[key] = self._remote_versions.get(key, 0) + 1
        # Capture unsaved keystrokes only if user actively modified editor text locally.
        visible = (account, peer)==(app.ui_account, app.active) and getattr(app, 'stage', None)=='ready'
        has_unsaved = visible and (self.job is not None or (hasattr(app, 'editor') and app.editor.winfo_exists() and app.editor.edit_modified()))
        if has_unsaved:
            self.snapshot()
        old = self.store.get(account, peer)
        checked = valid_record(remote)
        if checked is None:
            return
        if old and old['pending'] and draft_content(old)!=draft_content(checked):
            return  # A newer local edit is still waiting to be sent.
        if old:
            checked['files'] = old['files']
            if 'photo_quality' in old:checked['photo_quality']=old['photo_quality']
        self.store.put(account, peer, checked, pending=False)
        files = [Path(p) for p in checked['files'] if Path(p).is_file()]
        draft = (checked['text'], files[0] if len(files)==1 else tuple(files) if files else None)
        state = getattr(app, 'account_states', {}).get(account)
        if state is not None:
            state.setdefault('drafts', {})[peer] = draft
        app.rich_drafts[(account, peer)] = checked['custom']
        app.format_drafts[(account, peer)] = checked['formats']
        if not hasattr(app, 'reply_drafts'):
            app.reply_drafts = {}
        if checked['reply']:
            app.reply_drafts[(account, peer)] = checked['reply']
        else:
            app.reply_drafts.pop((account, peer), None)
        if account==app.ui_account:
            app.drafts[peer] = draft
            if visible and (old is None or draft_content(old)!=draft_content(checked)):
                self._remote_applying = True
                try:
                    app.restore_draft()
                finally:
                    self._remote_applying = False
            if hasattr(app, 'chat_list') and app.chat_list.winfo_exists():
                app.render_chats()
            if checked['unsupported'] and visible:
                from .interface_layout import caption
                app.status.set(caption('This Telegram draft includes fields this editor cannot change; it is preserved on the server.',
                    'Este borrador contiene campos que este editor no puede cambiar; se conserva en Telegram.'))

    def sent(self, account, peer):
        # Successful sends clear the cloud draft explicitly. A failed send never
        # reaches here, so its text remains available locally and in Telegram.
        self.store.put(account, peer, {'text': ''}, pending=True)
        self.changed()
