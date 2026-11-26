"""Viewer-owned media: no reusable plaintext file for protected/expiring messages."""
import asyncio
from pathlib import Path
import shutil
import tempfile
import time
import tkinter as tk

from .i18n import tr
from .media_cache import has_expiry, media_identity


def owner_of(app):
    return getattr(app, '_linked_owner', None) or getattr(app, 'app', None) or app


def restricted(message, app=None, peer=None):
    from .secret_chats import is_secret_peer
    chat = next((chat for chat in getattr(app, 'chats', ()) if chat.id == peer), None)
    return bool(has_expiry(message) or getattr(message, 'protected', False)
                or getattr(message, 'noforwards', False)
                or getattr(getattr(chat, 'entity', None), 'noforwards', False)
                or (isinstance(peer, int) and is_secret_peer(peer)))


def secret_record(backend, peer, ident):
    manager = getattr(backend, 'secret_chats', None)
    if manager is None:return None
    try:session = manager.session_for_peer(peer)
    except (KeyError,ValueError):return None
    return next((row for row in session.messages if row['id'] == ident), None)


def export_blocked(message, app=None, peer=None):
    from .secret_chats import is_secret_peer
    if isinstance(peer,int) and is_secret_peer(peer):
        # Secret Message.protected means "cannot forward to cloud", not "cannot
        # save locally". Its local TTL record decides the export restriction.
        backend = getattr(getattr(app,'service',None),'backend',None)
        ident = getattr(message,'id',None) or getattr(message,'msg_id',None)
        row = secret_record(backend,peer,ident)
        return has_expiry(message) or row is None or bool(row.get('ttl',0) or row.get('expires_at'))
    return restricted(message,app,peer)


async def source_message(backend, peer, ident):
    from .secret_chats import is_secret_peer
    if not is_secret_peer(peer):return await backend.media_message(peer,ident)
    manager = backend.secret_chats
    manager._prune_expired_sync()
    row = secret_record(backend,peer,ident)
    if row is None:raise PermissionError(tr('El archivo ya no esta disponible.'))
    message = manager._record_to_message(manager.session_for_peer(peer),row)
    message.expires_at = row.get('expires_at')
    return message


def deadline(message):
    expires = getattr(message,'expires_at',None)
    if isinstance(expires,(int,float)) and expires>0:return expires
    period = getattr(message, 'ttl_period', None)
    date = getattr(message, 'date', None)
    if hasattr(date, 'timestamp'):date = date.timestamp()
    if isinstance(period, (int, float)) and period > 0 and isinstance(date, (int, float)):
        return date + period
    return None


async def mark_contents(backend, peer, ident):
    """Viewing an expiring attachment reads its contents, not the whole chat."""
    from telethon import functions, types, utils
    async def send():
        if utils.resolve_id(peer)[1] is types.PeerChannel:
            entity = await backend.client.get_input_entity(peer)
            await backend.client(functions.channels.ReadMessageContentsRequest(entity, [ident]))
        else:
            await backend.client(functions.messages.ReadMessageContentsRequest([ident]))
    await asyncio.wait_for(send(),30)


def purge_known(app, account, peer, ident, message, backend=None):
    """Target known old copies only; retain unrelated ordinary offline media."""
    directory = getattr(app, 'preview_dir', None)
    identity = media_identity(message)
    if directory is not None:
        prefixes = [f'{account}-{peer}-{ident}']
        if identity:prefixes.append(f'{account}-{peer}-{identity[0]}-{identity[1]}-gallery-')
        for prefix in prefixes:
            for path in Path(directory).glob(prefix + '*'):
                suffix = path.name[len(prefix):]
                if suffix and suffix[0] not in '.-' and not prefix.endswith('-'):continue
                if path.is_file():
                    try:path.unlink(missing_ok=True)
                    except OSError:pass
    cache = backend if backend is not None else getattr(getattr(app, 'service', None), 'backend', None)
    cache = getattr(cache, 'media_cache_dir', None)
    if identity and cache is not None:
        for path in (Path(cache) / 'previews').glob(f'{identity[0]}{identity[1]}-*'):
            try:path.unlink(missing_ok=True)
            except OSError:pass


def revoke(app, account=None, peer=None, identifiers=None):
    for lease in tuple(getattr(owner_of(app), '_private_media_leases', ())):
        if account is not None and lease.account != account:continue
        if peer is not None and lease.peer != peer:continue
        if identifiers is not None and lease.ident not in identifiers:continue
        if identifiers is not None and peer is None:
            from telethon import types, utils
            if isinstance(lease.peer,int) and utils.resolve_id(lease.peer)[1] is types.PeerChannel:continue
        lease.expire()


def private_preview(app, message, peer):
    """Expiring/protected bytes require an explicit, owned viewer, never preload."""
    if not restricted(message, app, peer):return False
    from .secret_chats import is_secret_peer
    if is_secret_peer(peer) and not export_blocked(message,app,peer):return False
    key = (app.ui_account, peer, message.id)
    getattr(app, 'preview_cache', {}).pop(key, None)
    purged = getattr(app, '_private_preview_purged', None)
    if purged is None:purged = app._private_preview_purged = set()
    if key not in purged:
        if len(purged) >= 512:purged.clear()
        purged.add(key)
        app.worker.submit(asyncio.to_thread(purge_known, app, app.ui_account, peer, message.id,
                                           message, app.service.backend), lambda _:None, lambda _:None)
    return True


class ViewerMedia:
    """One temporary directory per visible item, destroyed with its consumer.

    Tk owns the timer and callbacks. The worker may only update plain metadata;
    its finalizer repeats cleanup after cancellation to cover a late downloader.
    """
    def __init__(self, app, window, account, backend, peer, ident, message, on_expire):
        self.app, self.window, self.account, self.backend = app, window, account, backend
        self.peer, self.ident, self.message, self.on_expire = peer, ident, message, on_expire
        self.directory = None
        self.copies = 0
        self.closed = False
        self.restricted = restricted(message, app, peer)
        self.export_blocked = export_blocked(message,app,peer)
        self.deadline = deadline(message)
        self.task = self.loop = None
        self.timer = None
        owner = owner_of(app)
        self.view_key = (account, peer, ident)
        previous = getattr(owner, '_private_media_deadlines', {}).get(self.view_key)
        if previous is not None:self.deadline = min(self.deadline or previous, previous)
        leases = getattr(owner, '_private_media_leases', None)
        if leases is None:leases = owner._private_media_leases = set()
        leases.add(self)
        self.destroy_binding = None
        self.attach(window)

    def attach(self, window):
        if self.destroy_binding is not None:
            try:self.window.unbind('<Destroy>', self.destroy_binding)
            except tk.TclError:pass
        if self.timer is not None:
            try:self.window.after_cancel(self.timer)
            except tk.TclError:pass
        self.window = window
        self.destroy_binding = window.bind('<Destroy>', self.destroyed, add='+')
        self.timer = window.after(250, self.tick)

    def destroyed(self, event):
        if event.widget is self.window:self.close()

    def check(self):
        owner = owner_of(self.app)
        if (self.closed or self.account != self.app.ui_account
                or self.backend is not self.app.service.backend
                or getattr(owner, '_app_locked', False)
                or getattr(self.app, 'closed', False) or getattr(self.app, 'closing', False)
                or (self.deadline is not None and time.time() >= self.deadline)):
            raise PermissionError(tr('El archivo ya no esta disponible.'))

    def update(self, message):
        self.message = message
        self.restricted = self.restricted or restricted(message, self.app, self.peer)
        self.export_blocked = self.export_blocked or export_blocked(message,self.app,self.peer)
        expires = deadline(message)
        if expires is not None:self.deadline = min(self.deadline or expires, expires)
        self.check()

    def active(self):
        try:self.check();return True
        except PermissionError:return False

    def viewed(self):
        """A local view-once fallback never outlives its advertised viewing TTL."""
        media = getattr(self.message, 'media', None) or self.message
        seconds = getattr(media, 'ttl_seconds', None)
        if isinstance(seconds, (int, float)) and seconds > 0:
            owner = owner_of(self.app)
            deadlines = getattr(owner, '_private_media_deadlines', None)
            if deadlines is None:deadlines = owner._private_media_deadlines = {}
            first = self.view_key not in deadlines
            expires = deadlines.get(self.view_key, time.time() + min(seconds, 86400))
            deadlines[self.view_key] = expires
            while len(deadlines) > 1024:deadlines.pop(next(iter(deadlines)))
            self.deadline = min(self.deadline or expires, expires)
            # Telegram's view-once sentinel is closed locally with its viewer.
            self.once = seconds >= 2147483647
            if first and hasattr(self.backend, 'client') and hasattr(self.app, 'worker'):
                from .secret_chats import is_secret_peer
                if not is_secret_peer(self.peer):
                    self.app.worker.submit(mark_contents(self.backend,self.peer,self.ident),lambda _:None,lambda _:None)

    def tick(self):
        self.timer = None
        try:self.check()
        except PermissionError:self.expire();return
        if self.window.winfo_exists():self.timer = self.window.after(250, self.tick)
        else:self.close()

    def expire(self):
        if self.closed:return
        self.close()
        try:self.on_expire()
        except tk.TclError:pass

    def retain_copy(self):
        self.check()
        if self.export_blocked:raise PermissionError(tr('Protected content'))
        self.copies += 1

    def release_copy(self, *, close=False):
        """Called back on Tk once the native opener has consumed its source."""
        self.copies = max(0,self.copies-1)
        if close and not self.closed:self.close()
        elif self.closed:self.cleanup()

    def close(self):
        if self.closed:return
        self.closed = True
        if getattr(self,'once',False):
            getattr(owner_of(self.app),'_private_media_deadlines',{})[self.view_key] = time.time()
        try:self.window.unbind('<Destroy>', self.destroy_binding)
        except tk.TclError:pass
        if self.timer is not None:
            try:self.window.after_cancel(self.timer)
            except tk.TclError:pass
            self.timer = None
        getattr(owner_of(self.app), '_private_media_leases', set()).discard(self)
        if self.task is not None and self.loop is not None and not self.task.done():
            self.loop.call_soon_threadsafe(self.task.cancel)
        self.cleanup()

    def cleanup(self):
        if self.copies:return
        if self.directory is not None:
            shutil.rmtree(self.directory, ignore_errors=True)
            if self.directory.exists() and self.loop is not None and not self.loop.is_closed():
                # Windows can retain an open decoder handle briefly after abort.
                directory = self.directory
                async def cleanup():
                    for _ in range(20):
                        await asyncio.sleep(.1)
                        await asyncio.to_thread(shutil.rmtree,directory,ignore_errors=True)
                        if not directory.exists():break
                self.loop.call_soon_threadsafe(lambda:self.loop.create_task(cleanup()))

    async def download(self, media, *, thumbnail=False, quality='original'):
        self.check()
        self.loop = asyncio.get_running_loop()
        self.task = asyncio.current_task()
        try:
            from .secret_chats import is_secret_peer
            if is_secret_peer(self.peer):
                message = await source_message(self.backend,self.peer,self.ident)
                self.update(message)
                media = message.media
            if self.restricted:
                await asyncio.to_thread(purge_known, self.app, self.account, self.peer, self.ident, self.message, self.backend)
            self.check()
            if self.directory is None:
                self.directory = Path(tempfile.mkdtemp(prefix='tg-private-', dir=self.app.preview_dir))
            # Extensionless destination skips the shared persistent preview cache.
            path = await self.backend.download_media(media, self.directory / 'media',
                                                     thumbnail=thumbnail, quality=quality)
            self.check()
            return path
        finally:
            self.task = None
            if self.closed:self.cleanup()
