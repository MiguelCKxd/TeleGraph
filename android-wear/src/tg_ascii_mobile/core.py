"""Bridge between the shared TG-ASCII core (``tg_ascii``) and the mobile UI.

Everything that talks to Telegram runs on one worker thread with its own
asyncio loop, exactly like the desktop app: the UI thread only hosts the
WebView. The desktop service layer is reused unchanged: ``Accounts`` /
``DesktopService`` (sessions, sign-in, offline start, Recovery),
``pending_actions`` (offline action queue), ``outbox`` (send queue with
exactly-once delivery), ``offline_store`` (local copy) and ``i18n``.
"""
import asyncio
from collections import OrderedDict
from contextlib import contextmanager
from functools import partial
from inspect import isawaitable
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
import types
from weakref import WeakValueDictionary
from tg_ascii.media_cache import has_expiry

from .siri_vocabulary import SiriVocabulary, suspend_vocabulary
from .gallery import ProfileGallery
from .stories import MobileStories
from .wallpapers import ChatWallpapers
from .native_logos import NAMES, NATIVE_LOGOS

SAVE_DELAY = 3.0
VISUAL_KINDS = ('image', 'sticker', 'video')
MEDIA_FOLDER = 'mobile-media'
MOBILE_CACHE_FOLDERS = (MEDIA_FOLDER, 'mobile-stickers', 'mobile-avatars')
STAGING_FOLDER = 'mobile-outgoing'
STAGING_DAYS = 14
PREVIEW_LIMIT = 160
ACTION_TIMEOUT = 90


def _install_window_shim(core):
    """``outbox`` reports delivered messages through ``interface_windows``,
    a Tk module on the desktop. On mobile the same call reaches the core."""
    shim = types.ModuleType('tg_ascii.interface_windows')

    def publish_local_message(app, account, peer, message):
        core.local_message(account, peer, message)

    shim.publish_local_message = publish_local_message
    sys.modules['tg_ascii.interface_windows'] = shim


class _Timers:
    def __init__(self, loop):
        self.loop = loop

    def after(self, milliseconds, callback):
        return self.loop.call_later(milliseconds / 1000, callback)

    def after_cancel(self, handle):
        handle.cancel()


class _Worker:
    """The subset of the desktop worker that ``Outbox`` uses."""

    def __init__(self, core):
        self.core = core
        self.events = self
        self.tasks = set()

    def put(self, event):
        callback, value = event
        self.core.loop.call_soon(callback, value)

    def submit(self, coroutine, done, failed):
        task = self.core.loop.create_task(coroutine)
        self.tasks.add(task)

        def finished(task):
            self.tasks.discard(task)
            if task.cancelled():
                return
            error = task.exception()
            if error is not None:
                failed(error)
            else:
                done(task.result())
        task.add_done_callback(finished)
        return task

    async def close(self):
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


class _Status:
    def __init__(self, core):
        self.core = core

    def set(self, text):
        self.core.emit('status', {'text': str(text)})


class _OutboxHost:
    demo = False
    closed = False

    def __init__(self, core):
        self.core = core
        self.root = _Timers(core.loop)
        self.worker = _Worker(core)
        self.status = _Status(core)

    @property
    def service(self):
        return self.core.accounts

    def refresh_open_history(self, account, peer):
        if account == self.core.account:
            self.core.loop.create_task(self.core.reload_history(peer))


def _timestamp(value):
    try:
        return value.timestamp() if value is not None else None
    except (AttributeError, OSError, ValueError):
        return None


def _plus(phone):
    """Telegram gives contacts' numbers without '+'; the core wants it."""
    phone = str(phone or '').strip()
    return '+' + phone if phone and phone[0].isdigit() else phone


def _safe_mimetypes():
    """Python reads the system's mime.types files; inside the macOS sandbox
    (the iOS app running on a Mac) that read is refused and the import of
    Telethon failed. Use the built-in table when they cannot be read."""
    import mimetypes
    try:
        mimetypes.init()
    except OSError:
        mimetypes.knownfiles[:] = []
        mimetypes.init()


from .forums import MobileForums


class Core(MobileStories, ChatWallpapers, ProfileGallery, MobileForums):
    def __init__(self, data_dir, system, locale=''):
        self.root = Path(data_dir)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.environ['TG_ASCII_DATA_DIR'] = str(self.root)
        self.siri_vocabulary = SiriVocabulary(self.root)
        self.system = system
        self.locale = locale
        # A plain selector loop for the worker thread. On iOS Toga installs an
        # event loop policy whose loops run on the main NSRunLoop; using it
        # here would block start-up.
        self.loop = asyncio.SelectorEventLoop()
        self.thread = threading.Thread(target=self._run, name='tg-ascii-core', daemon=True)
        self.token = secrets.token_urlsafe(32)
        self.subscribers = set()
        self.stage, self.error = 'loading', ''
        self.connection = 'connecting'
        self.accounts = self.prefs = self.outbox = None
        self.chats, self.previews, self.histories = [], {}, {}
        self.history_requests = {}
        self._sticker_locks = WeakValueDictionary()
        self._sticker_downloads = asyncio.Semaphore(4)
        self.open_peer = None
        self.open_revision = 0
        self.open_discussion = None
        self.discussion_messages = {}
        self.qr_task = None
        self._save_handle = None
        self._refreshing = {}
        self._history_refreshing = {}
        self._snapshot_write_lock = threading.Lock()
        self._snapshot_sequence = 0
        self._snapshot_written = {}
        self._prune_handle = None
        self.port = None
        self.native_picker = None  # set by the Android shell
        self.native_open = None    # set by the mobile shell: open a file or URL outside
        self.native_icon = None    # set by the mobile shell: switch the launcher icon
        self.native_wear_appearance = None
        self._push_ready = asyncio.Event()
        self._startup_account_gate = asyncio.Lock()
        self._push_gate = asyncio.Lock()
        self._push_registered = {}
        self._push_registered_at = {}
        self._push_privacy = {}
        self._push_logging_out = set()
        self._push_check = None
        self._push_retry_delay = 5
        self._push_retry_native = False
        self._push_stopped = False
        self._push_generation = 0
        self._push_status = {'state': 'waiting', 'provider': None, 'error': None}
        self._push_permission = 'unknown'
        self.native_push_retry = None
        self.native_incoming_call = None
        self.native_telecom = None
        self.native_telecom_outgoing = None
        self.native_callkit_update = None
        self.native_callkit_answer = None
        self._incoming_call_notice = None
        self.native_call_manager = None
        self.native_call_engine = None
        self.call_pip = None
        self.native_call_available = None
        self.native_call_permission = None
        self.native_call_media_start = None
        self.native_call_media_end = None
        self.native_call_media_camera = None
        self.native_group_call_manager = None  # set by the Android shell (android_group_calls)
        self.native_window = None  # (peer, name, account, done) -> bool: a chat in its own system window
        self.window_peers = set()
        self.floating_peers = set()
        self.window_revisions = {}
        self.window_discussions = {}
        self.call_manager = None
        self.group_call_manager = None
        self._channel_calls = None
        self.call_manager_lock = asyncio.Lock()
        self.native_quit = None    # set by the Android shell: close the app completely
        self.native_scan = None    # (done(text or None)) - camera QR scanner
        self.native_notify = None  # (account, peer, title, body, count, sound) - system notification
        self.native_notify_clear = None       # (account, peer)
        self.native_notify_disable = None
        self.native_notify_permission = None  # () - ask once to show notifications
        self.native_notify_refresh = None    # () - recheck OS permission without asking
        self.native_keep_alive = None         # (on, title, text) - stay connected in the background
        self.native_battery_exemption = None  # () - Android: do not pause the network
        self.in_background = False
        self.notify_counts = {}
        self.recent_incoming_messages = OrderedDict()
        self.native_voice = None  # {'start', 'stop', 'level', 'cancel'} - microphone (voice_native)
        self.voice_recording = None
        self.voice_gate = asyncio.Lock()
        self.native_qr_image = None  # (path) -> text or None - QR in a picture
        self.native_biometric = None            # (reason, done(ok)) - device authentication
        self.native_biometric_available = None  # () -> bool
        self.hidden_at = None
        self.external_until = 0.0  # a picker/system screen of ours is in front until then
        from tg_ascii.drafts import DraftStore
        self.draft_store = DraftStore(self.root / 'mobile')
        self.draft_jobs = {}
        self.draft_pull_jobs = {}
        self.draft_sync_locks = {}
        self.loaded_draft_accounts = set()
        self.folder_records = []
        self.locked = False
        self.pin_verifying = False
        self.preview = False
        self._avatar_slots = None

    # -- thread and loop ----------------------------------------------------
    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def start(self):
        _safe_mimetypes()
        self.thread.start()
        return asyncio.run_coroutine_threadsafe(self._start(), self.loop).result(timeout=20)

    async def _start(self):
        from .server import Server
        self.locked = self.lock_record() is not None
        self.server = Server(self)
        self.port = await self.server.start()
        self.loop.create_task(self.boot())
        return self.port

    # -- events to the UI -----------------------------------------------------
    def emit(self, kind, payload=None):
        if kind in ('stage', 'lock', 'chats'):
            self.siri_vocabulary.sync(self)
        if self.locked and kind not in ('stage', 'connection', 'lock'):
            return  # Nothing about chats reaches the page while it is locked.
        if not self.subscribers:
            return
        data = json.dumps({'type': kind, 'data': payload, 'account': None if self.locked else self.account},
                          ensure_ascii=False, default=str)
        inactive_event = None
        for queue in tuple(self.subscribers):
            event = data
            account = getattr(queue, 'window_account', None)
            if kind == 'message_notice' and account is not None:
                continue
            inactive = account is not None and account != self.account
            if inactive:
                if kind not in ('stage', 'lock'):
                    continue
                if inactive_event is None:
                    public = self.state_snapshot(window_account=account) if kind == 'stage' else payload
                    inactive_event = json.dumps({'type': kind, 'data': public, 'account': None}, ensure_ascii=False)
                event = inactive_event
            budget = getattr(queue, 'would_overflow', None)
            overflow = budget(event) if budget is not None else queue.qsize() >= 500
            if overflow or (kind == 'lock' and self.locked) or (inactive and kind == 'stage'):
                while not queue.empty():
                    queue.get_nowait()
            if overflow:
                self.subscribers.discard(queue)
                queue.put_nowait(None)
            else:
                queue.put_nowait(event)

    def set_stage(self, stage, error=''):
        if stage != 'ready':
            self.disconnect_tv()
        self.stage, self.error = stage, error
        if stage == 'loading':
            self._push_ready.clear()
        else:
            self._push_ready.set()
        self.emit('stage', self.state_snapshot())

    # -- start-up -------------------------------------------------------------
    @property
    def account(self):
        return self.accounts.current if self.accounts else 'account'

    @property
    def backend(self):
        service = self.accounts.services.get(self.account) if self.accounts else None
        return getattr(service, 'backend', None)

    def client_factory(self, session, api_id, api_hash, **options):
        from telethon import TelegramClient
        from . import __version__
        options['device_model'] = f'TeleGraph {self.system}'  # shown in Telegram's device list
        options['system_version'] = self.system
        options['app_version'] = __version__
        return TelegramClient(session, api_id, api_hash, **options)

    async def boot(self):
        try:
            await self._boot()
        except Exception as exc:  # Show the problem instead of loading forever.
            import traceback
            traceback.print_exc()
            self.set_stage('error', f'{type(exc).__name__}: {exc}')

    async def _boot(self):
        _safe_mimetypes()
        from tg_ascii.preferences import Preferences
        from tg_ascii.i18n import LANGUAGES, set_language
        from . import strings
        strings.install()
        first_run = not (self.root / 'preferences.json').exists()
        from tg_ascii.local_state import LocalPins
        self.local_pins = LocalPins(self.root)
        self.prefs = Preferences(self.root)
        if getattr(self, 'native_display_name', None):
            self.native_display_name(self.prefs.values.get('app_display_name'))
        if first_run:
            language = self.guess_language(LANGUAGES)
            if language:
                self.prefs.save({'language': language})
        set_language(self.prefs.values['language'])
        self.apply_keep_loaded()
        self.locked = self.lock_record() is not None
        self.make_accounts()
        _install_window_shim(self)
        from tg_ascii.outbox import Outbox
        self.outbox = Outbox(_OutboxHost(self))
        self.outbox.subscribe(self.outbox_changed)
        # Sent attachments do not stay on the phone (an hour covers files
        # chosen but not sent yet).
        self.outbox.subscribe(self.schedule_prune_sent)
        self.load_snapshot()
        self.purge_secret_previews()
        try:
            self.prune_staging()
        except OSError:
            pass
        if self.should_choose_account():
            # Desktop behaviour: with several saved accounts, ask which one to
            # open before connecting any (Settings can turn this off).
            self.set_stage('choose_account')
            return
        await self.connect()

    def should_choose_account(self):
        return (len(self.accounts.entries) > 1 and bool(self.prefs.values.get('ask_account_startup', True))
                and any(self.accounts.labels.get(key) for key in self.accounts.entries))

    async def api_choose_account(self, key, ask=True):
        async with self._startup_account_gate:
            if self.stage != 'choose_account':
                raise ValueError('not choosing')
            if key not in self.accounts.entries:
                raise ValueError('account')
            self.prefs.save({'ask_account_startup': bool(ask)})
            self.accounts.current = key
            try:
                self.accounts.persist()
            except Exception:
                pass
            self.load_snapshot()
            self.set_stage('loading')
            self.loop.create_task(self.connect())
            return True

    def make_accounts(self):
        from tg_ascii.accounts import Accounts
        from tg_ascii.desktop_service import DesktopService
        self.accounts = Accounts(root=self.root, factory=partial(DesktopService, client_factory=self.client_factory))
        self.accounts.on_message = self.on_message
        self.accounts.on_change = self.on_change
        self.accounts.on_registry = lambda: self.emit('accounts', self.account_list())

    # -- connection and app lifetime (desktop: Reconnect / Restart / Quit) ---------------
    async def api_reconnect(self):
        """Reconnect to Telegram now instead of waiting for the next retry."""
        service = self.accounts.services.get(self.account) if self.accounts else None
        if self.stage != 'ready' or service is None or service.backend is None:
            await self.connect()
            return self.connection
        account, backend = self.account, service.backend
        self.connection = 'reconnecting'
        self.emit('connection', 'reconnecting')
        try:
            await asyncio.wait_for(service.recovery.ensure(force=True), 60)
            connection = getattr(service.recovery, 'state', 'online') or 'online'
        except Exception:
            connection = 'offline'
        if self.account != account or self.backend is not backend or self.stage != 'ready':
            return self.connection
        self.connection = connection
        self.emit('connection', self.connection)
        if self.connection == 'online':
            self.schedule_draft_sync(pull=True)
            self.outbox.kick()
            self.loop.create_task(self.refresh_chats())
        return self.connection

    async def shutdown(self):
        """Save the local copy and close the Telegram sessions (never log out)."""
        self.stage = 'loading'
        self._push_stopped = True
        self._push_generation = getattr(self, '_push_generation', 0) + 1
        if getattr(self, '_push_check', None) is not None:
            self._push_check.cancel()
            self._push_check = None
        await self.close_media_requests()
        if self.outbox is not None:
            self.outbox.app.closed = True
            if self.outbox.timer is not None:
                self.outbox.timer.cancel()
                self.outbox.timer = None
            await self.outbox.app.worker.close()
            for item in self.outbox.inflight.values():
                item.state, item.progress, item.retry_at = 'waiting', -1, 0.0
            self.outbox.inflight.clear()
            self.outbox.save()
        refreshing = (list(self._refreshing.values()) + list(self._history_refreshing.values())
                      + list(self.draft_jobs.values()) + list(self.draft_pull_jobs.values()))
        if self.qr_task is not None:
            refreshing.append(self.qr_task)
            self.qr_task = None
        for task in refreshing:
            task.cancel()
        if refreshing:
            await asyncio.gather(*refreshing, return_exceptions=True)
        self.draft_jobs.clear()
        self.draft_pull_jobs.clear()
        if self._prune_handle is not None:
            self._prune_handle.cancel()
            self._prune_handle = None
        self.siri_vocabulary.sync(self)
        self._push_ready.clear()
        await self.cancel_current_voice()
        try:
            await asyncio.wait_for(self.save_snapshot(), 10)
        except Exception:
            pass
        await self.close_call_manager()
        if self.accounts is not None:
            try:
                await asyncio.wait_for(self.accounts.close(), 15)
            except Exception:
                pass

    async def api_restart(self):
        """Start the app again: sessions, chats and interface (the page reloads)."""
        await self.shutdown()
        self.open_peer, self.preview = None, False
        self.open_revision += 1
        self.open_discussion = None
        self.discussion_messages.clear()
        self.window_discussions.clear()
        self.window_revisions.clear()
        self.window_peers.clear()
        self.floating_peers.clear()
        self.make_accounts()
        self.load_snapshot()
        self.loop.create_task(self.connect())
        return True

    async def api_quit(self):
        """Android: close the app completely (iOS does not allow apps to quit)."""
        if self.native_quit is None:
            raise LookupError('quit')
        if self.native_keep_alive is not None:
            self.native_keep_alive(False)
        await self.shutdown()
        self.native_quit()
        return True

    def guess_language(self, languages):
        code = (self.locale or '').replace('_', '-')
        if not code:
            return None
        lowered = code.lower()
        if lowered.startswith('es-') and lowered not in ('es-es',):
            return 'es-419' if 'es-419' in languages else 'es'
        for candidate in (code, code.split('-')[0]):
            if candidate in languages:
                return candidate
        return None

    async def connect(self):
        from tg_ascii.auth import error_message
        self._push_stopped = False
        if self.outbox is not None:
            self.outbox.app.closed = False
        self.set_stage('loading')
        try:
            state = await self.accounts.connect()
        except Exception as exc:
            self.set_stage('error', error_message(exc))
            return
        self.after_login(state)

    def after_login(self, state):
        if state == 'ready':
            service = self.accounts.services.get(self.account)
            recovery = getattr(service, 'recovery', None)
            # Recovery only reports changes; read where it starts from.
            if getattr(service, 'offline_start', False) or self.accounts.failures.get(self.account):
                self.connection = 'offline'
            else:
                self.connection = getattr(recovery, 'state', None) or 'online'
            self.load_drafts()
            if getattr(self.accounts, 'identities', {}).get(self.account):
                self.loop.create_task(self.cache_account_portrait(self.account, self.backend))
            self.set_stage('ready')
            self.schedule_draft_sync(pull=True)
            if getattr(self, '_push_token', None):
                self.loop.create_task(self.sync_push_registration())
            self.loop.create_task(self._sync_background())
            self.apply_notification_permission()
            self.keep_connected()
            self.publish_wear_appearance()
            self.loop.create_task(self.enable_call_manager())
            # The local copy first (works offline), then Telegram's list.
            self.emit('chats', [self.chat_json(chat) for chat in self.visible_chats()])
            self.outbox.kick()
            self.loop.create_task(self.refresh_chats())
        else:
            self.set_stage(state)

    # -- local copy (offline_store, 1.5.3) -----------------------------------
    def previews_path(self):
        return self.root / 'mobile' / f'previews-{self.account}.json'

    def load_snapshot(self):
        from tg_ascii import offline_store
        self.forget_fresh_histories()
        self.forget_details()
        self.chats, self.histories, self.previews, self.folder_records = [], {}, {}, []
        snapshot = offline_store.read(self.root, self.account)
        if snapshot is not None:
            self.chats, folders, self.histories = snapshot
            self.folder_records = folders or []
        self.trim_histories()
        try:
            self.previews = {int(k): v for k, v in json.loads(self.previews_path().read_text('utf-8')).items()}
        except (OSError, ValueError, AttributeError):
            self.previews = {}

    def trim_histories(self, peer=None):
        """Keep recently used chats within the existing offline-copy budget.

        Open views and active requests retain their full scrolling context.
        Eviction affects only the in-memory copy, never server messages.
        """
        from tg_ascii import offline_store
        if peer in self.histories:
            self.histories[peer] = self.histories.pop(peer)
        protected = self.floating_peers | self.window_peers | {self.open_peer, peer}
        protected.update(p for account, p, _ in self.history_requests.values() if account == self.account)
        protected.update(key[2] for key in self._history_refreshing if key[0] == self.account)
        limit = offline_store.chat_limit()
        for ident in tuple(self.histories):
            if ident in protected:
                continue
            del self.histories[ident][:-400]
            if len(self.histories) > limit:
                self.histories.pop(ident, None)
                self.__dict__.get('history_fresh', {}).pop(ident, None)

    def schedule_save(self):
        if not self.prefs or not self.prefs.values.get('offline_copy', True):
            return
        if self._save_handle is not None:
            self._save_handle.cancel()
        self._save_handle = self.loop.call_later(SAVE_DELAY, lambda: self.loop.create_task(self.save_snapshot()))

    async def save_snapshot(self):
        from tg_ascii import offline_store
        from tg_ascii.secret_chats import is_secret_peer
        if self._save_handle is not None:
            self._save_handle.cancel()
            self._save_handle = None
        self.trim_histories()
        self._snapshot_sequence += 1
        sequence = self._snapshot_sequence
        account, chats, folders = self.account, list(self.chats), list(self.folder_records)
        histories = {peer: list(messages) for peer, messages in self.histories.items()}
        previews = {peer: value for peer, value in self.previews.items() if not is_secret_peer(peer)}
        path = self.previews_path()

        def write():
            # A cancelled coroutine does not stop its worker thread. Serialize
            # the complete snapshot + previews transaction in the threads, and
            # skip an older snapshot if the executor started it out of order.
            with self._snapshot_write_lock:
                if sequence <= self._snapshot_written.get(account, 0):
                    return
                offline_store.write(self.root, account, chats, folders, histories)
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                temporary = path.with_suffix('.tmp')
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                    json.dump(previews, stream, ensure_ascii=False)
                os.replace(temporary, path)
                self._snapshot_written[account] = sequence
        try:
            await asyncio.to_thread(write)
        except Exception as exc:
            from tg_ascii.recovery import record_failure
            record_failure(self.root, 'mobile_snapshot', exc)

    # -- serialisation --------------------------------------------------------
    def text(self, value):
        if self.prefs and self.prefs.values.get('ascii_text'):
            from tg_ascii.backend import display
            return display(value)
        return value

    def chat_status(self, chat, preview):
        """Ticks of the last message in the list: ◷ waiting, ✓ sent, ✓✓ read (desktop/official)."""
        waiting = self.outbox.pending(self.account, chat.id) if self.outbox else []
        if waiting:
            return 'failed' if any(item.state == 'failed' for item in waiting) else 'pending', waiting[-1]
        if not preview.get('out'):
            return None, None
        if chat.id == getattr(getattr(self.backend, 'client', None), '_self_id', None):
            return 'read', None
        read_max = getattr(self.backend, 'read_max', {}).get(chat.id, 0) if self.backend else 0
        return ('read' if preview.get('id') and read_max >= preview['id'] else 'sent'), None

    def chat_json(self, chat):
        preview = self.previews.get(chat.id) or {}
        status, waiting = self.chat_status(chat, preview)
        if waiting is not None:
            preview = {**preview, 'text': self.text(waiting.preview(PREVIEW_LIMIT)), 'out': True,
                       'date': waiting.created}
        from tg_ascii.secret_chats import is_secret_peer
        draft_record = (self.secret_draft(chat.id) if is_secret_peer(chat.id)
                        else self.draft_store.get(self.account, chat.id)) or {}
        return {'status': status,'id': chat.id, 'name': self.text(chat.name), 'unread': chat.unread, 'pinned': self.is_pinned(chat),
                'kind': chat.kind, 'muted': chat.muted, 'archived': chat.archived,
                'forum': bool(getattr(chat, 'forum', False) or getattr(chat.entity, 'forum', False)),
                'has_link': bool(getattr(chat, 'has_link', False) or getattr(chat.entity, 'has_link', False)),
                'color': getattr(getattr(chat.entity, 'color', None), 'color', None),
                'protected': bool(getattr(chat.entity, 'noforwards', False)),
                'username': getattr(chat.entity, 'username', None),
                'emoji_status': emoji_status_id(chat.entity),
                'photo': str(self.photo_id(chat.id) or '') or None,
                'online': type(getattr(chat.entity, 'status', None)).__name__ == 'UserStatusOnline',
                'unread_mark': chat.unread_mark, 'preview': self.text(preview.get('text', '')),
                'out': preview.get('out', False), 'date': preview.get('date'),
                'emojis': preview.get('emojis') or [],
                'self': chat.id == getattr(getattr(self.backend, 'client', None), '_self_id', None),  # Saved Messages
                'draft': ' '.join(draft_record.get('text', '').split())[:120]}

    def message_json(self, message):
        from tg_ascii.backend import Message
        if not isinstance(message, Message):
            return None
        seconds = self.prefs.values.get('show_seconds') if self.prefs else False
        stamp = _timestamp(message.date)
        clock = message.time
        if seconds and message.date is not None:
            clock = message.date.astimezone().strftime('%H:%M:%S')
        visual = message.media_kind in VISUAL_KINDS and message.media is not None
        width, height = media_dimensions(message.media) if visual else (0, 0)
        audio = audio_json(message)
        # A voice message shows its player, not "[File] voice.ogg (size)".
        text = message.raw_text or '' if audio.get('voice') else message.text
        return {'id': message.id, 'sender': self.text(message.sender), 'text': self.text(text),
                'caption': self.text(message.raw_text or '') if visual else None, 'visual': visual,
                'w': width, 'h': height, 'album': str(message.grouped_id) if message.grouped_id is not None else None,
                'time': clock, 'date': stamp, 'out': message.outgoing, 'kind': message.media_kind,
                'filename': message.filename, 'size': message.size, 'reply_to': message.reply_to_id,
                'thread_root': message.thread_id, 'topic_id': getattr(message, 'topic_id', None),
                'read': message.read, 'sender_id': message.sender_id, 'color': message.sender_color,
                'service': message.service, 'forwarded': message.forwarded,
                'edited_at': _timestamp(message.edited_at), 'edited': message.edited_at is not None, 'protected': bool(message.protected or has_expiry(message)),
                'reactions': [[str(value), count, chosen] for value, count, chosen in message.reactions],
                'poll': poll_json(message.media), 'keyboard': keyboard_json(message.reply_markup),
                'custom_emojis': [[str(ident), alt] for ident, alt in (message.custom_emojis or ())][:200],
                'sticker_id': self.sticker_id(message), **audio,
                # Channel posts with a discussion group: number of comments.
                'comments': getattr(message, 'comments_count', None),
                'formats': formats_json(message, text, visual),
                'webpage': self.webpage_json(getattr(message, 'webpage', None)),
                'translatable': bool((message.raw_text or (text if message.media is None else '')).strip())}

    def webpage_json(self, page):
        """A link preview (types.WebPage): what the card shows."""
        url = getattr(page, 'url', None)
        if not url:
            return None
        clip = lambda value, size: self.text(str(value or '')[:size])
        return {'url': str(url), 'site': clip(getattr(page, 'site_name', ''), 80),
                'title': clip(getattr(page, 'title', ''), 200),
                'description': clip(getattr(page, 'description', ''), 600),
                'photo': getattr(page, 'photo', None) is not None}

    def sticker_id(self, message):
        """A sticker message's document (View pack from the message menu)."""
        if message.media_kind != 'sticker':
            return None
        document = getattr(message.media, 'document', None)
        if document is None or not hasattr(document, 'id'):
            return None
        self.remember_documents([document])
        return str(document.id)

    def outbox_changed(self, account, peer):
        self.emit('outbox', self.outbox_items(account, peer))
        if account == self.account:  # the list's ◷ / ✓ for that chat
            self.patch_chat(peer)

    def patch_chat(self, peer):
        """One row of the list changed in place: send that row, not the whole list."""
        chat = next((item for item in self.chats if item.id == peer), None)
        if chat is not None and not chat.archived:
            self.emit('chat_patch', self.chat_json(chat))

    def outbox_items(self, account, peer):
        items = self.outbox.pending(account, peer) if self.outbox else []
        return {'account': account, 'peer': peer,
                'items': [{'key': item.key, 'text': self.text(item.preview(400)), 'state': item.state, 'files': bool(item.paths), 'full': item.text,
                           'error': item.error, 'reply_to': item.reply_to, 'created': item.created, 'thread_root': item.thread_root, 'topic_id': getattr(item, 'topic_id', None),
                           'photo_quality': getattr(item, 'photo_quality', None)}
                          for item in items]}

    def account_portrait(self, key):
        # The startup chooser reads only the portrait of a registered account.
        entry = (self.accounts.entries if self.accounts else {}).get(key)
        if not entry or type(entry.get('user_id')) is not int:
            return None
        peer = entry['user_id']
        folder = self.root / 'mobile-avatars' / key
        return folder / f'{peer}.jpg'

    async def cache_account_portrait(self, account, backend):
        path = self.account_portrait(account)
        if not path or not getattr(backend, 'client', None):
            return
        try:
            me = await asyncio.wait_for(backend.client.get_me(), 10)
            if me is None or self.account != account or self.backend is not backend:
                return
            version = path.with_suffix('.id')
            photo = getattr(me, 'photo', None)
            revision = getattr(photo, 'photo_id', None)
            if not revision:
                path.unlink(missing_ok=True)
                version.unlink(missing_ok=True)
                return
            if path.is_file() and version.is_file() and version.read_text() == str(revision):
                return
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if self._avatar_slots is None:
                self._avatar_slots = asyncio.Semaphore(4)
            downloaded = await self._download_avatar(backend, me, path, path.with_suffix('.none'), False)
            if downloaded and self.account == account and self.account_portrait(account) == path:
                version.write_text(str(revision))
        except (OSError, ValueError, TimeoutError):
            return
        except Exception:
            # A failed or offline portrait request must leave login usable.
            return

    def account_list(self):
        if not self.accounts:
            return []
        aliases = (self.prefs.values.get('account_aliases') or {}) if self.prefs else {}
        return [{'key': key, 'label': self.accounts.labels.get(key, ''), 'alias': aliases.get(key, ''),
                 'user_id': entry.get('user_id'), 'current': key == self.account, 'failure': self.accounts.failures.get(key, ''),
                 'premium': bool(entry.get('premium'))}
                for key, entry in self.accounts.entries.items()]

    def state_snapshot(self, window_account=None):
        from tg_ascii.i18n import get_language, is_rtl
        from . import __version__
        info = self.lock_info()
        snapshot = {'stage': self.stage, 'connection': self.connection, 'language': get_language(),
                    'rtl': is_rtl(), 'version': __version__, 'system': self.system,
                    'locked': self.locked, 'lock_enabled': info['enabled'], 'lock': info}
        if self.locked or (window_account is not None and window_account != self.account):
            theme = self.prefs.values.get('theme') if self.prefs else None
            return {**snapshot, 'error': '', 'account': None, 'accounts': [], 'settings': {'theme': theme}, 'appearance': {}}
        return {**snapshot, 'error': self.error, 'account': self.account, 'accounts': self.account_list(),
                'settings': self.settings_snapshot(), 'appearance': self.appearance() if self.prefs else {}}

    def settings_snapshot(self):
        if not self.prefs:
            return {}
        keys = ('language', 'theme', 'font_size', 'enter_send', 'offline_copy', 'ascii_text',
                'show_seconds', 'notifications', 'notify_preview', 'bubbles', 'compact',
                'ask_account_startup', 'animated_emoji', 'reduce_animations', 'notify_sound', 'notify_active', 'inline_media',
                'local_pins', 'app_display_name', 'bubble_in_color', 'bubble_out_color', 'accent_color', 'text_color', 'background_color', 'bubble_radius', 'button_radius', 'menu_radius')
        snapshot = {key: self.prefs.values.get(key) for key in keys}
        from tg_ascii.preferences import FONT_SIZE_RANGE, RADIUS_RANGE
        snapshot.update(font_min=FONT_SIZE_RANGE[0], font_max=FONT_SIZE_RANGE[1], radius_max=RADIUS_RANGE[1],
                        photo_previews=self.prefs.values.get('photo_previews', True))
        snapshot['advanced_features'] = mobile_features(self.prefs.values)
        snapshot['quick_reaction'] = self.default_reaction(self.account)
        return snapshot

    # -- Telegram events (worker loop) ---------------------------------------
    def on_message(self, key, peer, message):
        if not message.outgoing:
            identity = (key, peer, message.id)
            if identity in self.recent_incoming_messages:
                return self.recent_incoming_messages[identity]
        delivery = self.loop.create_task(self.notify(key, peer, message))
        if not message.outgoing:
            self.recent_incoming_messages[identity] = delivery
            def finished(task):
                if self.recent_incoming_messages.get(identity) is task:
                    self.recent_incoming_messages[identity] = None
                if not task.cancelled():
                    task.exception()  # Socket deliveries are fire-and-forget.
            delivery.add_done_callback(finished)
            if len(self.recent_incoming_messages) > 4096:
                self.recent_incoming_messages.popitem(last=False)
        if key != self.account:
            self.emit('other_account', {'account': key})
            return delivery
        self.record_history_change(peer, 'message', message)
        history = self.histories.get(peer)
        if history is not None and not any(item.id == message.id for item in history):
            history.append(message)
            del history[:-400]
        self.remember_preview(peer, message)
        chat = next((item for item in self.chats if item.id == peer), None)
        if chat is not None:
            if not message.outgoing and not self.reading_message(key, peer, message):
                chat.unread += 1
            if not self.is_pinned(chat):
                self.chats.remove(chat)
                self.chats.insert(0, chat)
            self.emit('chat', self.chat_json(chat))
        else:
            self.loop.create_task(self.refresh_chats())
        in_thread = False
        _, root = self.message_scope(peer, message)
        for context, messages in self.active_discussions():
            if root is not None and context == (key, peer, root):
                messages[message.id] = message
                in_thread = True
        self.emit('message', {'peer': peer, 'message': self.message_json(message)})
        if in_thread and not self.in_background and not self.locked and not message.outgoing:
            self.loop.create_task(self._read_comments(self.backend, peer, root, [message]))
        self.schedule_save()
        return delivery

    async def notify(self, key, peer, message):
        """Apply the account's notification policy before choosing the presentation."""
        from tg_ascii.i18n import tr
        if message.outgoing or message.service or not self.prefs:
            return
        values = self.prefs.values
        # As on desktop: with the app in front, other chats notify; the chat being
        # read only with "Notify for the open chat" (notify_active).
        def reading_here():
            if key != self.account or self.in_background or self.prefs.values.get('notify_active', False):
                return False
            return self.reading_message(key, peer, message)

        if not values.get('notifications', True) or reading_here():
            return
        if getattr(message, 'read', False):
            return
        title = message.sender or ''
        conversation = ''
        if key == self.account:
            chat = next((item for item in self.chats if item.id == peer), None)
            if chat is not None:
                if chat.muted:
                    return
                conversation = self.text(chat.name) if peer < 0 else ''
                title = title or self.text(chat.name)
        if len(self.accounts.entries if self.accounts else ()) > 1:
            label = next((item.get('alias') or item.get('label') for item in self.account_list() if item['key'] == key), '')
            if label:
                conversation = f'{conversation} · {label}' if conversation else label
        service = self.accounts.services.get(key) if self.accounts else None
        backend = getattr(service, 'backend', None)
        if backend is None:
            return
        try:
            policy = await backend.notification_policy(peer, platform=self.system)
        except Exception:
            policy = {'enabled': True, 'preview': False, 'sound': False}
        sender_id = getattr(message, 'sender_id', None) or (peer if peer > 0 else None)
        def allowed():
            return (policy['enabled'] and self.prefs.values.get('notifications', True)
                    and not reading_here() and key not in self._push_logging_out and self.accounts
                    and self.accounts.services.get(key) is service and service.backend is backend)

        def banner_visible():
            return (not self.in_background and not self.locked and
                    any(getattr(q, 'window_account', None) is None for q in self.subscribers))

        if not allowed() or (not banner_visible() and self.native_notify is None):
            return
        receipt = (key, peer, getattr(message, 'id', None))
        track = self.system == 'Android' and isinstance(receipt[2], int)
        if track and not self.claim_android_notification(receipt):
            return
        delivered = False
        try:
            picture = None
            if (self.in_background and sender_id and policy['preview'] and self.lock_record() is None
                    and self.prefs.values.get('notify_preview', True)):
                # An avatar must belong to the same Telegram account as the message.
                path = self.root / 'mobile-avatars' / key / f'{int(sender_id)}.jpg'
                try:
                    if path.is_file() and time.time() - path.stat().st_mtime < 3 * 86400:
                        picture = await asyncio.to_thread(path.read_bytes)
                    else:
                        picture = await asyncio.wait_for(backend.client.download_profile_photo(
                            int(sender_id), file=bytes, download_big=False), 2)
                except Exception:
                    pass  # Missing photos and slow connections still deliver the message.
            # Account, visibility and preview settings can change while the photo loads.
            banner = banner_visible()
            if not allowed() or (not banner and self.native_notify is None):
                return
            values = self.prefs.values
            protected = self.lock_record() is not None
            if protected:
                title = 'TeleGraph'
            private = protected or not values.get('notify_preview', True) or not policy['preview']
            cache = getattr(self, 'ios_notice_cache', None)
            if cache and picture and not private:
                try:
                    cache.thumbnail(self.accounts.identities.get(key), sender_id, picture)
                except OSError:
                    pass
            body = tr('New message') if private else (self.text(preview_text(message)) or tr('New message'))
            count = self.notify_counts.get((key, peer), 0) + 1
            if banner:
                self.emit('message_notice', {'account': key, 'peer': peer, 'title': title or 'TeleGraph',
                                             'body': body[:400], 'sender': None if private else sender_id,
                                             'conversation': '' if private else conversation})
            else:
                details = {} if private or not sender_id else {'sender': str(sender_id), 'picture': picture,
                                                               'conversation': conversation}
                if self.system == 'iOS' and details and type(receipt[2]) is int:
                    details['message_id'] = receipt[2]
                result = self.native_notify(key, peer, title or 'TeleGraph', body[:400], count,
                                            policy['sound'] and values.get('notify_sound', True) is not False,
                                            **details)
                if isawaitable(result):
                    await result
            delivered = True
        finally:
            if track and not delivered:
                with self.android_receipts() as db:
                    db.execute('DELETE FROM receipts WHERE account=? AND peer=? AND msg=?', receipt)
        self.notify_counts[(key, peer)] = count
        return True

    @contextmanager
    def android_receipts(self):
        import sqlite3
        from contextlib import closing
        folder = self.root / 'mobile'
        folder.mkdir(exist_ok=True, parents=True)
        with closing(sqlite3.connect(folder / 'notification-receipts.sqlite3')) as db, db:
            yield db

    def claim_android_notification(self, receipt):
        with self.android_receipts() as db:
            db.execute('CREATE TABLE IF NOT EXISTS receipts (account TEXT, peer INTEGER, msg INTEGER, '
                       'created INTEGER NOT NULL, PRIMARY KEY (account, peer, msg))')
            now = int(time.time())
            if getattr(self, '_pruned_notification_day', None) != now // 86400:
                db.execute('DELETE FROM receipts WHERE created < ?', (now - 28 * 86400,))
                self._pruned_notification_day = now // 86400
            return db.execute('INSERT OR IGNORE INTO receipts VALUES (?, ?, ?, ?)',
                              (*receipt, now)).rowcount == 1

    def clear_notifications(self, peer, key=None):
        key = key or self.account
        count = self.notify_counts.pop((key, peer), None)
        if self.native_notify_clear is not None and (count or self.system == 'Android'):
            # A notification may outlive the process that posted it.
            self.native_notify_clear(key, peer)

    def keep_connected(self):
        """Settings › Notifications › Keep connected in the background."""
        from tg_ascii.i18n import tr
        if self.native_keep_alive is not None and self.prefs:
            on = bool(self.appearance().get('keep_connected')) and bool(self.prefs.values.get('notifications', True))
            if self.system == 'iOS':
                on = on and self.in_background
            self.native_keep_alive(on, 'TeleGraph', tr('Connected'))

    def local_message(self, account, peer, message):
        """A send confirmed by Telegram (outbox) - same routing as updates."""
        if message is not None:
            self.on_message(account, peer, message)

    def remember_preview(self, peer, message):
        text = ' '.join(preview_text(message).split())[:PREVIEW_LIMIT]
        self.previews[peer] = {'text': (('' if message.outgoing else '') + text), 'out': message.outgoing, 'id': message.id,
                               'emojis': [[str(ident), alt] for ident, alt in (message.custom_emojis or ())][:30],
                               'date': _timestamp(message.date) or time.time()}

    def on_change(self, key, kind, payload):
        if kind == 'connection':
            if payload == 'online':
                self.loop.create_task(self.sync_push_registration())
            if key == self.account:
                if payload != 'online':
                    self.forget_fresh_histories()
                self.connection = payload
                self.emit('connection', payload)
                if payload == 'online':
                    self.schedule_draft_sync(pull=True)
                    self.outbox.online(key)
                    self.loop.create_task(self.refresh_chats())
            return
        if kind == 'delete':
            from .chat_translations import ChatTranslations
            store = self.translations() if key == self.account else ChatTranslations(self.root / 'mobile', key)
            store.discard(*payload)
            from .media_lifetime import purge_cached
            deleted_peer, deleted_ids = payload
            temporary = self.__dict__.get('_transient_media')
            if temporary is not None:
                temporary.revoke(key, deleted_peer, deleted_ids)
            streams = getattr(getattr(self, 'server', None), 'video_ranges', None)
            if streams is not None:
                streams.revoke(key, deleted_peer, deleted_ids)
            if deleted_peer is not None:
                for ident in deleted_ids:
                    purge_cached(self, key, deleted_peer, ident)
        if key != self.account:
            return
        if kind == 'forum_topics':
            self.emit('forum_topics', {'peer': payload[0], 'topic_id': payload[1]})
            return
        if kind == 'edit':
            peer, message = payload
            from .media_lifetime import transient, purge_cached
            chat = next((chat for chat in self.chats if chat.id == peer), None)
            if transient(message, chat):
                purge_cached(self, key, peer, message.id)
                temporary = self.__dict__.get('_transient_media')
                if temporary is not None:
                    temporary.revoke(key, peer, [message.id])
                streams = getattr(getattr(self, 'server', None), 'video_ranges', None)
                if streams is not None:
                    streams.revoke(key, peer, [message.id])
            self.record_history_change(peer, 'edit', message)
            history = self.histories.get(peer) or []
            for index, item in enumerate(history):
                if item.id == message.id:
                    history[index] = message
            for context, messages in self.active_discussions():
                if context and context[:2] == (key, peer) and message.id in messages:
                    messages[message.id] = message
            self.emit('edit', {'peer': peer, 'message': self.message_json(message)})
            self.schedule_save()
        elif kind == 'delete':
            peer, identifiers = payload
            removed = set(identifiers)
            targets = {peer}
            if peer is None:
                from telethon.tl.types import PeerChannel
                from telethon.utils import resolve_id

                candidates = set(self.histories) | self.floating_peers | self.window_peers | {self.open_peer}
                candidates.update(p for account, p, _ in self.history_requests.values() if account == key)
                candidates.update(context[1] for context, _ in self.active_discussions() if context)
                targets = {p for p in candidates if p is not None and resolve_id(p)[1] is not PeerChannel}
            for target in targets:
                for ident in removed:
                    purge_cached(self, key, target, ident)
                self.record_history_change(target, 'delete', removed)
                history = self.histories.get(target)
                if history is not None:
                    history[:] = [item for item in history if item.id not in removed]
                self.emit('delete', {'peer': target, 'ids': list(identifiers)})
            for context, messages in self.active_discussions():
                if context and context[1] in targets:
                    for ident in removed:
                        messages.pop(ident, None)
            self.schedule_save()
        elif kind == 'read':
            peer, maximum = payload
            self.record_history_change(peer, 'read', maximum)
            for item in self.histories.get(peer) or []:
                if item.outgoing and item.id <= maximum:
                    item.read = True
            self.emit('read', {'peer': peer, 'max_id': maximum})
            backend = self.backend
            if backend is not None and key == self.account:
                marks = backend.__dict__.setdefault('read_max', {})
                if maximum > marks.get(peer, 0):
                    marks[peer] = maximum
                    self.patch_chat(peer)
        elif kind == 'emoji_status':
            peer, status = payload
            chat = next((item for item in self.chats if item.id == peer), None)
            if chat is not None and chat.entity is not None and hasattr(chat.entity, 'emoji_status'):
                chat.entity.emoji_status = status
            self.emit('emoji_status', {'peer': peer, 'status': emoji_status_id(types.SimpleNamespace(emoji_status=status))})
        elif kind == 'reaction':
            peer, ident = payload
            self.loop.create_task(self.refresh_message(peer, ident))
        elif kind == 'activity':
            peer, status = payload
            if status is None:
                if peer == self.open_peer:
                    self.loop.create_task(self.refresh_header(peer))
            else:
                self.emit('typing', {'peer': peer, 'status': status})
        elif kind == 'draft':
            peer, draft = payload
            self.receive_draft(peer, draft)
        elif kind == 'dialogs':
            self.loop.create_task(self.refresh_chats())

    async def refresh_message(self, peer, ident):
        backend = self.backend
        if backend is None:
            return
        try:
            raw = await backend.client.get_messages(peer, ids=ident)
        except Exception:
            return
        if raw is not None and self.backend is backend:
            self.on_change(self.account, 'edit', (peer, backend.message(raw)))

    # -- chats and history ------------------------------------------------------
    async def refresh_chats(self):
        backend = self.backend
        key = (self.account, id(backend))
        task = self._refreshing.get(key)
        if task is None or task.done():
            task = asyncio.create_task(self._refresh_chats(backend))
            self._refreshing[key] = task

            def finished(result):
                if self._refreshing.get(key) is result:
                    self._refreshing.pop(key, None)
                if not result.cancelled():
                    result.exception()
            task.add_done_callback(finished)
        # HTTP cancellation must not abort the refresh shared by other views.
        return await asyncio.shield(task)

    async def _refresh_chats(self, backend=None):
        backend = backend if backend is not None else self.backend
        if backend is None or getattr(backend, 'demo', False):
            return
        client = backend.client
        original = client.iter_dialogs
        captured = {}

        async def tap(*args, **kwargs):
            async for dialog in original(*args, **kwargs):
                message = dialog.message
                if type(getattr(message, 'action', None)).__name__ == 'MessageActionHistoryClear':
                    # Telegram shows nothing for "history cleared".
                    captured[dialog.id] = {'text': '', 'out': False, 'date': _timestamp(getattr(message, 'date', None))}
                elif message is not None:
                    emojis = []
                    try:
                        # The desktop's own summary: captions, files, service
                        # actions, polls, articles... exactly as in a chat.
                        converted = backend.message(message)
                        text = preview_text(converted)
                        emojis = [[str(ident), alt] for ident, alt in (converted.custom_emojis or ())][:30]
                    except Exception:
                        text = getattr(message, 'message', '') or ''
                    captured[dialog.id] = {'text': ' '.join((text or '').split())[:PREVIEW_LIMIT],
                                           'out': bool(getattr(message, 'out', False)), 'id': getattr(message, 'id', 0), 'emojis': emojis,
                                           'date': _timestamp(getattr(message, 'date', None))}
                yield dialog
        client.iter_dialogs = tap
        try:
            chats = await backend.chats()
        except Exception as exc:
            import errno
            import socket
            # Recovery already publishes the connectivity badge. Only this automatic
            # dialog refresh is silent for a transport failure; permission errors and
            # failures of explicit operations still reach their own error handlers.
            if backend is not self.backend or isinstance(exc, (ConnectionError, TimeoutError, socket.gaierror)):
                return
            if isinstance(exc, OSError) and exc.errno in (errno.ENETDOWN, errno.ENETUNREACH, errno.EHOSTUNREACH,
                                                         errno.EHOSTDOWN, errno.ENETRESET, errno.ENOTCONN, errno.ETIMEDOUT):
                return
            from tg_ascii.auth import error_message
            self.emit('toast', {'text': error_message(exc), 'kind': 'error'})
            return
        finally:
            try:
                del client.iter_dialogs
            except AttributeError:
                pass
        if backend is not self.backend:
            return
        self.chats = chats
        known_forums = self.__dict__.get('forum_peers', {})
        for chat in chats:
            forum = bool(getattr(chat, 'forum', False) or getattr(getattr(chat, 'entity', None), 'forum', False))
            if forum:
                self.floating_peers.discard(chat.id)
            if (self.account, chat.id) in known_forums:
                known_forums[(self.account, chat.id)] = forum
        if self.prefs and self.prefs.values.get('local_pins') and self.account not in self.local_pins.values:
            self.local_pins.save_order(self.account, [c.id for c in chats if c.pinned])
        from tg_ascii.secret_chats import is_secret_peer
        secret_mgr = getattr(backend, 'secret_chats', None)
        if secret_mgr is not None:
            for chat in chats:
                if is_secret_peer(chat.id) and chat.id not in captured:
                    hist = secret_mgr.history(chat.id)
                    if hist:
                        last = hist[-1]
                        text = preview_text(last)
                        captured[chat.id] = {
                            'text': ' '.join((text or '').split())[:PREVIEW_LIMIT],
                            'out': bool(last.outgoing),
                            'id': int(last.id),
                            'emojis': [[str(ident), alt] for ident, alt in (last.custom_emojis or ())][:30],
                            'date': _timestamp(last.date),
                        }
        self.previews.update(captured)
        self.emit('chats', [self.chat_json(chat) for chat in self.visible_chats()])
        self.schedule_save()
        if self.feature('preload_startup'):
            self.loop.create_task(self.preload())

    def local_order(self):
        if getattr(self, 'prefs', None) and self.prefs.values.get('local_pins'):
            return self.local_pins.values.get(self.account)
        return None

    def is_pinned(self, chat):
        order = self.local_order()
        return chat.pinned if order is None else chat.id in order

    def visible_chats(self, archived=False):
        chats = [chat for chat in self.chats if bool(chat.archived) == archived]
        order = self.local_order()
        if order is None:
            return sorted(chats, key=lambda chat: not chat.pinned)
        ranks = {peer: index for index, peer in enumerate(order)}
        return sorted(chats, key=lambda chat: ranks.get(chat.id, len(ranks)))

    def record_history_change(self, peer, kind, value):
        for account, target, updates in self.history_requests.values():
            if account == self.account and target == peer:
                updates.append((kind, value))

    async def history_page(self, peer, request, include_new=False):
        # Each network read can overlap a different set of live updates.
        token, updates = object(), []
        self.history_requests[token] = (self.account, peer, updates)
        try:
            messages = await request
        finally:
            del self.history_requests[token]
        if not updates:
            return messages
        page = {message.id: message for message in messages}
        read_max = None
        for kind, value in updates:
            if kind == 'delete':
                for ident in value:
                    page.pop(ident, None)
            elif kind == 'older':
                if include_new:
                    page = {**{m.id: m for m in value}, **page}
            elif kind == 'read':
                read_max = value if read_max is None else max(value, read_max)
            elif value.id in page or (kind == 'message' and include_new):
                page[value.id] = value
        if read_max is not None:
            for message in page.values():
                if message.outgoing and message.id <= read_max:
                    message.read = True
        return list(page.values())

    async def reload_history(self, peer):
        backend = self.backend
        if backend is None:
            return
        previous = self.histories.setdefault(peer, [])
        key = (self.account, id(backend), peer, id(previous))
        task = self._history_refreshing.get(key)
        if task is None or task.done():
            task = asyncio.create_task(self._reload_history(peer, backend, previous))
            self._history_refreshing[key] = task

            def finished(result):
                if self._history_refreshing.get(key) is result:
                    self._history_refreshing.pop(key, None)
                if not result.cancelled():
                    result.exception()
            task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def _reload_history(self, peer, backend, previous):
        try:
            messages = await self.history_page(peer, backend.history(peer), include_new=True)
        except Exception:
            return
        if backend is not self.backend or self.histories.get(peer) is not previous:
            return
        self.__dict__.setdefault('history_fresh', {})[peer] = time.monotonic()
        self.histories[peer] = messages
        self.trim_histories(peer)
        self.emit('history', {'peer': peer, 'messages': [self.message_json(m) for m in messages],
                              **self.translation_state(peer, messages)})
        self.schedule_save()

    async def api_system_window(self, peer, account):
        """Open a chat in its own system window (iPadOS scene, Android task) when
        the device supports it; otherwise the page uses its in-app window."""
        if account != self.account:
            raise ValueError('The active account changed.')
        if self.native_window is None:
            return {'opened': False}
        chat = next((item for item in self.chats if item.id == int(peer)), None)
        name = self.text(chat.name) if chat else str(peer)
        future = self.loop.create_future()
        self.native_window(int(peer), name, self.account, lambda ok: self.loop.call_soon_threadsafe(
            lambda: future.done() or future.set_result(bool(ok))))
        return {'opened': await asyncio.wait_for(future, 10)}

    async def floating_forum(self, peer, account):
        """Resolve a restored window before reading or sending to a group without a topic."""
        from telethon import types, utils
        from tg_ascii.secret_chats import is_secret_peer
        if account != self.account:
            raise ValueError('The active account changed.')
        if self.locked:
            raise PermissionError('locked')
        chat = next((item for item in self.chats if item.id == peer), None)
        if not self.is_forum_chat(peer):
            if (is_secret_peer(peer) or utils.resolve_id(peer)[1] is not types.PeerChannel
                    or (chat is not None and chat.kind == 'channel')):
                return None
            backend = self.backend
            if backend is None:
                raise ConnectionError('offline')
            entity = await asyncio.wait_for(backend.client.get_entity(peer), 15)
            if account != self.account or backend is not self.backend or self.locked:
                raise ValueError('The active account changed.')
            if not isinstance(entity, types.Channel) or utils.get_peer_id(entity) != peer:
                raise ValueError('The group is unavailable.')
            if not (entity.megagroup and entity.forum):
                return None
            self.__dict__.setdefault('forum_peers', {})[(account, peer)] = True
            if chat is None:
                from tg_ascii.backend import Chat
                chat = Chat(peer, entity.title, kind='group', entity=entity, forum=True)
            else:
                chat.forum, chat.entity = True, entity
        self.floating_peers.discard(peer)
        descriptor = self.chat_json(chat) if chat else {'id': peer, 'name': str(peer), 'kind': 'group'}
        return {'forum': True, 'chat': {**descriptor, 'forum': True}}

    async def api_window_open(self, peer, account, read=True):
        """Open a floating chat without changing the main window's reading position."""
        peer = int(peer)
        forum = await self.floating_forum(peer, account)
        if forum:
            return forum
        self.floating_peers.add(peer)
        self.trim_histories(peer)
        cached = self.histories.get(peer) or []
        if self.backend is not None:
            self.loop.create_task(self.reload_and_read(peer) if read else self.refresh_history(peer))
        chat = next((item for item in self.chats if item.id == peer), None)
        return {'messages': [self.message_json(m) for m in cached], 'chat': self.chat_json(chat) if chat else None,
                'draft': self.draft_record(peer), **self.translation_state(peer, cached)}

    async def api_window_send(self, peer, account, text='', keys=(), reply_to=None, spans=(), custom=(), photo_quality=None):
        peer = int(peer)
        forum = await self.floating_forum(peer, account)
        if forum:
            return forum
        params = dict(reply_to=reply_to, spans=spans, custom=custom, account=account)
        if keys:
            return await self.api_send_files(peer, keys, caption=text, photo_quality=photo_quality, **params)
        return await self.api_send(peer, text, **params)

    async def api_window_close(self, peer, account):
        if account != self.account:
            raise ValueError('The active account changed.')
        self.floating_peers.discard(int(peer))
        self.trim_histories()
        return True

    # -- Apple Watch companion (app.install_watch_bridge) --------------------------------
    def watch_message(self, message):
        text = (message.get('caption') if message.get('visual') else message.get('text')) or ''
        if message.get('visual'):
            from tg_ascii.i18n import tr
            kind = {'photo': tr('Foto'), 'image': tr('Foto'), 'video': tr('Vídeo')}.get(message.get('kind'), message.get('kind') or '')
            text = f'[{kind}] {text}'.strip()
        from tg_ascii.i18n import tr
        return {'id': int(message['id']), 'sender': tr('Tu') if message.get('out') else (message.get('sender') or ''),
                'text': text, 'time': message.get('time') or '', 'out': bool(message.get('out')),
                'translatable': bool(message.get('translatable')), 'sender_id': message.get('sender_id'),
                'date': message.get('date'), 'edited_at': message.get('edited_at'), 'read': message.get('read'),
                'color': message.get('color')}

    def client_for(self, key=None):
        service = self.accounts.services.get(key or self.account) if self.accounts else None
        backend = getattr(service, 'backend', None)
        if backend is None:
            raise ConnectionError('offline')
        return backend.client

    async def api_approve_login(self, url, key=None):
        """Sign another device (a watch, a computer) in with one of this phone's
        accounts: accept the login token its QR shows (tg://login?token=...), as
        Telegram does when a QR code is scanned. That device gets its own session;
        this phone's session is never copied."""
        from telethon import errors
        from tg_ascii.devices import accept_login
        try:
            item = await asyncio.wait_for(accept_login(self.client_for(key), url), 30)
        except errors.AuthTokenAlreadyAcceptedError:
            return {'ok': True, 'device': ''}  # A second scan of the same code.
        return {'ok': True, 'device': item.get('device', '')}

    # Settings › Accounts › Devices: the sessions of the account open here.
    async def api_devices(self):
        from tg_ascii.devices import list_sessions
        return await asyncio.wait_for(list_sessions(self.client_for()), 30)

    async def api_device_end(self, hash):
        from tg_ascii.devices import end_session
        return await end_session(self.client_for(), hash)

    async def api_devices_end_others(self):
        from tg_ascii.devices import end_other_sessions
        return await end_other_sessions(self.client_for())

    async def api_devices_ttl(self, days):
        from tg_ascii.devices import set_session_ttl
        return await set_session_ttl(self.client_for(), days)

    async def api_device_flags(self, hash, calls=None, secret_chats=None):
        from tg_ascii.devices import set_session_flags
        return await set_session_flags(self.client_for(), hash, calls, secret_chats)

    async def api_scan_qr(self, window_peer=None, window_account=None):
        """Read a QR code with the device camera (native scanner). Returns its text,
        and whether it is a Telegram login code."""
        from tg_ascii.devices import login_token
        if self.native_scan is None:
            raise RuntimeError('unavailable')
        future = self.loop.create_future()
        self.expect_external(180)
        def received(text):
            self.loop.call_soon_threadsafe(lambda: future.done() or future.set_result(text))
        cancel = (self.native_scan(received, window_peer, window_account) if window_peer is not None and self.system == 'iOS'
                  else self.native_scan(received))
        try:
            text = await asyncio.wait_for(future, timeout=180)
        finally:
            if future.cancelled() and callable(cancel):
                cancel()
        from .qr_native import CAMERA_DENIED
        if text == CAMERA_DENIED:
            from tg_ascii.i18n import tr
            raise RuntimeError(tr('Camera permission denied.'))
        return {'text': text or '', 'login': bool(text and login_token(text) is not None)}

    async def api_scan_qr_photo(self, key):
        """Read a QR code from a picture chosen in the gallery (staged file)."""
        from tg_ascii.devices import login_token
        path = self.staged(key)
        if self.native_qr_image is None:
            raise RuntimeError('unavailable')
        text = await asyncio.to_thread(self.native_qr_image, str(path))
        path.unlink(missing_ok=True)
        return {'text': text or '', 'login': bool(text and login_token(text) is not None)}

    def watch_appearance(self):
        """The phone's look for the watch: theme colours, text size and effects."""
        dark = {'bg': '#08100c', 'panel': '#0e1b13', 'text': '#8cf5a6', 'muted': '#80a98c', 'strong': '#bdffcd'}
        light = {'bg': '#f4f8f3', 'panel': '#ffffff', 'text': '#14532d', 'muted': '#4a6854', 'strong': '#0b4521'}
        values = self.prefs.values if self.prefs else {}
        theme = values.get('theme', 'dark')
        if theme == 'system':
            theme = getattr(self, 'system_theme', 'dark')
        result = dict(light if theme == 'light' else dark)
        text, background = values.get('text_color') or '', values.get('background_color') or ''
        if text:
            result['text'] = result['strong'] = text
        if background:
            result['bg'] = background
        if text or background:
            def blend(a, b, weight):
                a, b = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]
                return '#%02x%02x%02x' % tuple(round(x + (y - x) * weight) for x, y in zip(a, b))
            result['panel'] = blend(result['bg'], result['text'], .05)
            result['muted'] = blend(result['bg'], result['text'], .70)
        if values.get('accent_color'):
            result['strong'] = values['accent_color']
        appearance = self.appearance()
        effects = appearance['effects']
        result.update(name=values.get('app_display_name') or 'TeleGraph',
                      photo_previews=values.get('photo_previews', True),
                      brand_logo=appearance['brand_logo'], icon=appearance['icon'], scale=max(0.8, min(1.6, int(values.get('font_size') or 12) / 12)),
                      bold=bool(effects.get('text_bold')), italic=bool(effects.get('text_italic')),
                      font=appearance['font'], bubbles=bool(values.get('bubbles')),
                      reduce_animations=bool(values.get('reduce_animations')))
        return result

    def publish_wear_appearance(self):
        if self.native_wear_appearance is not None and self.prefs is not None:
            try:
                self.native_wear_appearance(self.watch_appearance())
            except Exception as error:
                print('wear appearance:', type(error).__name__)

    async def api_watch(self, request):
        return await self.watch_request(request)

    async def watch_forum(self, peer):
        from tg_ascii.secret_chats import is_secret_peer
        if self.is_forum_chat(peer):
            return True
        if peer > -1_000_000_000_000 or is_secret_peer(peer):
            return False
        # An existing watch may still hold the chat from before topics were enabled.
        entity = await self.client_for().get_entity(peer)
        return bool(getattr(entity, 'forum', False))

    async def watch_request(self, request):
        """Bind a companion request and its response to the originating account."""
        if request.get('op') in ('config', 'appearance') or self.locked or self.stage != 'ready':
            return await self._watch_request(request)
        self.check_active_account(request.get('account'))
        owner, backend = self.account, self.backend
        result = await self._watch_request(request)
        self.check_backend_context(owner, backend)
        return result

    async def _watch_request(self, request):
        """One request from the watch: chats, a chat's latest messages, or a reply."""
        from tg_ascii.i18n import tr
        if request.get('op') == 'config':
            return {'own': bool(self.appearance().get('watch_own'))}
        if request.get('op') == 'appearance':
            return self.watch_appearance()
        if self.locked:
            return {'error': tr('Unlock your messages')}
        if self.stage != 'ready':
            return {'error': tr('Conectando...')}
        op = request.get('op')
        if op == 'avatar':
            import base64
            owner = self.account
            path = await self.avatar_file(int(request['peer']))
            if self.locked or self.account != owner or not path or not path.is_file() or path.stat().st_size > 40000:
                return {}
            return {'image': base64.b64encode(path.read_bytes()).decode('ascii')}
        if op == 'message_dates':
            return await self.api_message_read_details(self.account, int(request['peer']), int(request['id']),
                                                       bool(request.get('group')))
        if op == 'move_pin':
            await self.api_move_pin(int(request['peer']), int(request['direction']), self.account)
            return {'ok': True}
        if op == 'chats':
            return [{'pinned': chat.get('pinned', False), 'id': chat['id'], 'name': chat['name'], 'unread': int(chat.get('unread') or 0),
                     'preview': chat.get('preview') or '', 'kind': chat.get('kind') or 'user',
                     'forum': bool(chat.get('forum')), 'has_link': bool(chat.get('has_link')), 'account': self.account} for chat in (await self.api_chats())[:60]]
        if op == 'linked_discussion':
            self.check_active_account(request.get('account'))
            owner = self.account
            link = await self.forum_call('linked_discussion', int(request['peer']), account=owner)
            return {'chat': None if not link else {'id': link['peer'], 'name': link['title'], 'kind': link['kind'],
                                                   'forum': link['forum'], 'unread': 0, 'preview': '', 'account': owner}}
        if op in ('topics', 'messages', 'send'):
            owner = self.account
            self.check_active_account(request.get('account'))
            peer = int(request['peer'])
            topic = request.get('topic_id')
            if op == 'topics':
                return await self.api_forum_topics(peer, cursor=request.get('cursor'), account=owner)
            if topic is not None:
                if type(topic) is not int or not 0 < topic <= 0x7fffffff:
                    raise ValueError(tr('Mensaje no válido.'))
                if op == 'send':
                    await self.forum_call('forum_send', peer, topic, str(request.get('text', ''))[:4096], account=owner)
                    return {'ok': True}
                page = await self.forum_call('forum_history', peer, topic, limit=25, account=owner)
                if page:
                    await self.forum_call('forum_mark_read', peer, topic, page[-1].id, account=owner)
                return [self.watch_message(self.message_json(m)) for m in page if not m.service]
            if await self.watch_forum(peer):
                raise ValueError(tr('Selecciona un tema.'))
            if self.locked or self.account != owner:
                raise ValueError(tr('Unlock your messages'))
        if op == 'messages':
            if self.backend is not None:
                await asyncio.wait_for(self.reload_and_read(peer), 25)
            if self.locked or self.account != owner:
                raise PermissionError(tr('Unlock your messages'))
            items = [self.message_json(m) for m in (self.histories.get(peer) or [])[-25:]]
            return [self.watch_message(item) for item in items if item and not item.get('service')]
        if op == 'translate':
            from tg_ascii.i18n import get_language
            from tg_ascii.message_translation import watch_language
            from tg_ascii.secret_chats import is_secret_peer
            language = watch_language(request.get('language') or get_language())
            peer = int(request['peer'])
            if is_secret_peer(peer):
                raise ValueError('Secret chat messages cannot be translated by Telegram.')
            ids = request.get('ids')
            if not isinstance(ids, list) or not 1 <= len(ids) <= 25 or any(type(item) is not int or item <= 0 for item in ids):
                raise ValueError('Invalid message selection.')
            values = await self.api_translate(peer, ids, language, chat=request.get('chat') is True)
            return {key: value['text'] for key, value in values.items() if value.get('text')}
        if op == 'accounts':
            return [{'key': item['key'], 'name': item.get('alias') or item.get('label') or ''} for item in self.account_list()]
        if op == 'approve_login':
            return await self.api_approve_login(request['url'], request.get('key'))
        if op == 'send':
            await self.api_send(peer, str(request.get('text', ''))[:4096], account=owner)
            return {'ok': True}
        if op == 'secret_info':
            return await self.api_secret_info(int(request['peer']))
        if op == 'secret_ttl':
            return await self.api_secret_ttl(int(request['peer']), int(request.get('seconds', 0)))
        if op == 'secret_start':
            return await self.api_secret_start(int(request['peer']))
        return {'error': 'op'}

    # -- media (phase 2) --------------------------------------------------------
    def media_folder(self):
        return self.root / MEDIA_FOLDER / self.account

    def purge_secret_previews(self):
        import shutil
        from tg_ascii.secret_chats import is_secret_peer

        shutil.rmtree(self.root / 'secret-previews', ignore_errors=True)
        shutil.rmtree(self.root / 'secret-exports', ignore_errors=True)
        # A process killed while serving a temporary attachment has no reader
        # left; never resurrect that response's private files on the next boot.
        shutil.rmtree(self.root / 'temporary-media', ignore_errors=True)
        # Remove copies left by versions that cached secret media like cloud media.
        for path in (self.root / MEDIA_FOLDER).glob('*/*'):
            prefix, separator, _ = path.name[1:].partition('-')
            if (separator and path.name.startswith('-') and prefix.isascii()
                    and prefix.isdecimal() and is_secret_peer(-int(prefix))):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    async def secret_preview_file(self, peer, ident, thumbnail, folder, *, original_name=False):
        import mimetypes
        import re
        from tg_ascii.secret_chats import SecretMedia

        account, backend = self.account, self.backend
        manager = getattr(backend, 'secret_chats', None)
        if manager is None:
            return None

        def attachment():
            try:
                messages = manager.message_context(peer, ident)
            except (LookupError, ValueError):
                return None
            return next((message.media for message in messages if message.id == ident), None)

        media = attachment()
        if not isinstance(media, SecretMedia):
            return None
        suffix = Path(media.file_name).suffix.lower()
        if thumbnail and media.thumb:
            suffix = '.jpg'
        elif not re.fullmatch(r'\.[a-z0-9]{1,12}', suffix):
            suffix = mimetypes.guess_extension(media.mime_type) or ''
        name = Path(media.file_name or '').name if original_name else ''
        if name in ('', '.', '..') or '\x00' in name:
            name = 'preview' + suffix
        path = await backend.download_media(media, folder / name, thumbnail=thumbnail)
        if self.locked or self.account != account or self.backend is not backend or attachment() is None:
            return None
        return Path(path) if path else None

    async def _media_index(self, folder):
        """Cached media of this account by name stem, read from disk once (not one
        directory scan per picture: the folder holds thousands of files)."""
        index = self.__dict__.setdefault('media_indexes', {})
        known = index.get(folder)
        if known is not None:
            return known

        def scan():
            found = {}
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        name = entry.name
                        if name.startswith('.') or name.endswith(('-play.caf', '-play-v2.caf')):
                            continue
                        found.setdefault(name.split('.', 1)[0], name)
            except OSError:
                pass
            return found
        scanned = await asyncio.to_thread(scan)
        known = index.get(folder)
        if known is None:
            known = index[folder] = scanned
        return known

    def forget_media_index(self):
        self.__dict__.pop('media_indexes', None)

    async def close_media_requests(self):
        streams = getattr(getattr(self, 'server', None), 'video_ranges', None)
        if streams is not None:
            streams.close()
        temporary = self.__dict__.get('_transient_media')
        if temporary is not None:
            await temporary.close()
        jobs = list(self.__dict__.get('media_jobs', {}).values())
        for job in jobs:
            job.cancel()
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)

    async def media_message(self, peer, ident, account, backend, *, fresh=False, article=False):
        """Classify before reading any disk cache, including legacy entries."""
        from .media_lifetime import transient, expiry_date, purge_cached, current_response
        response = current_response(self)
        cache_key = (account, id(backend), peer, ident)
        cached = response.messages.get(cache_key) if response is not None else None
        message = next((m for m in self.histories.get(peer) or [] if m.id == ident), None)
        chat = next((c for c in self.chats if c.id == peer), None)
        was_restricted = transient(message, chat)
        fetched = backend is not None and (fresh or message is None or was_restricted
                or getattr(message, 'media', None) is None
                or isinstance(getattr(message, 'media', None), (dict, list, str)))
        if cached is not None:
            message, was_restricted = cached
            fetched = False
        elif fetched:
            message = await self._fetch_message(backend, peer, ident)
        if self.account != account or self.backend is not backend or self.locked:
            raise PermissionError('The active account changed.')
        # An unclassified old cache file is not proof that a deleted or
        # self-destructed attachment is still available. Offline snapshots of
        # ordinary messages remain valid and do not need a network request.
        if message is None or (fetched and getattr(message, 'media', None) is None
                and not (article and getattr(message, 'rich_message', None) is not None)):
            if backend is not None:
                purge_cached(self, account, peer, ident)
                raise LookupError('no media')
            raise ConnectionError('offline')
        deadline = expiry_date(message)
        restricted = was_restricted or transient(message, chat)
        if restricted or (deadline is not None and time.time() >= deadline):
            purge_cached(self, account, peer, ident)
        if deadline is not None and time.time() >= deadline:
            raise PermissionError('The media expired.')
        if response is not None:
            response.messages[cache_key] = (message, restricted)
        return message, restricted

    def transient_media(self):
        from .media_lifetime import TransientMedia
        manager = self.__dict__.get('_transient_media')
        if manager is None:
            manager = self._transient_media = TransientMedia(self)
        return manager

    async def media_file(self, peer, ident, thumbnail=True, *, quality='original'):
        """Local path of a message's media (preview or full), downloading it once.
        Requests for the same file while it downloads share that download."""
        if quality not in ('original', 'display'):
            raise ValueError('quality')
        account, backend = self.account, self.backend
        message, restricted = await self.media_message(peer, ident, account, backend)
        if restricted:
            if backend is None or getattr(message, 'media', None) is None:
                raise PermissionError('The media is no longer available.')
            return await self.transient_media().file(account, backend, peer, ident, message, thumbnail, quality)
        folder = self.media_folder()
        stem = f'{int(peer)}-{int(ident)}' + ('-t' if thumbnail else '-d' if quality == 'display' else '')
        index = await self._media_index(folder)
        if self.account != account or self.backend is not backend or self.locked:
            raise PermissionError('The active account changed.')
        name = index.get(stem)
        if name is None and not thumbnail and quality == 'display':
            name = index.get(f'{int(peer)}-{int(ident)}')
        if name is not None:
            path = folder / name
            try:
                if path.stat().st_size:
                    return path
            except OSError:
                pass
            index.pop(stem, None)
        jobs = self.__dict__.setdefault('media_jobs', {})
        job = jobs.get((folder, stem))
        if job is None:
            job = jobs[(folder, stem)] = self.loop.create_task(
                self._download_media_file(folder, stem, peer, ident, thumbnail, quality, account, backend, message))
            def finished(done):
                if jobs.get((folder, stem)) is done:
                    jobs.pop((folder, stem), None)
                if not done.cancelled():
                    done.exception()  # the last HTTP reader may have gone away
            job.add_done_callback(finished)
        # A page that stops waiting (scrolled away) must not cancel the shared download.
        result = await asyncio.shield(job)
        if self.account != account or self.backend is not backend or self.locked:
            raise PermissionError('The active account changed.')
        return result

    async def _download_media_file(self, folder, stem, peer, ident, thumbnail, quality, account, backend, message):
        original = folder / stem
        if original.is_file() and original.stat().st_size:
            return original
        if backend is None:
            raise ConnectionError('offline')
        if self.account != account or self.backend is not backend or self.locked:
            raise PermissionError('The active account changed.')
        media = getattr(message, 'media', None)
        if media is None:
            raise LookupError('no media')
        if self.account != account or self.backend is not backend or self.locked:
            raise PermissionError('The active account changed.')
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = await backend.download_media(media, folder / stem, thumbnail=thumbnail, quality=quality)
        if not path:
            return None
        path = Path(path)
        if self.account != account or self.backend is not backend or self.locked:
            path.unlink(missing_ok=True)
            raise PermissionError('The active account changed.')
        known = self.__dict__.get('media_indexes', {}).get(folder)
        if known is not None:
            known[stem] = path.name
        return path

    async def _fetch_message(self, backend, peer, ident):
        """One Telegram message, asked together with the others requested in the
        same moment for that chat (a screen of previews is one request, not
        one per picture: faster and far from Telegram's flood limits)."""
        batches = self.__dict__.setdefault('message_batches', {})
        key = (id(backend), int(peer))
        batch = batches.get(key)
        if batch is None or len(batch['ids']) >= 100:
            batch = batches[key] = {'ids': {}, 'task': None}

            async def run(batch=batch):
                await asyncio.sleep(0.03)
                if batches.get(key) is batch:
                    batches.pop(key, None)
                ids = list(batch['ids'])
                try:
                    found = await backend.client.get_messages(int(peer), ids=ids)
                except Exception as exc:
                    for future in batch['ids'].values():
                        if not future.done():
                            future.set_exception(exc)
                    return
                found = found if isinstance(found, list) else [found]
                by_id = {getattr(item, 'id', None): item for item in found if item is not None}
                for number, future in batch['ids'].items():
                    if not future.done():
                        future.set_result(by_id.get(number))
            batch['task'] = self.loop.create_task(run())
        future = batch['ids'].get(int(ident))
        if future is None:
            future = batch['ids'][int(ident)] = self.loop.create_future()
        return await asyncio.shield(future)

    async def poll_attachment(self, peer, ident, part, thumbnail=True):
        from telethon.tl import types

        if part not in ('attached', 'solution'):
            raise ValueError('Unknown poll attachment')
        account, backend = self.account, self.backend
        if backend is None:
            raise ConnectionError('offline')
        raw, restricted = await self.media_message(peer, ident, account, backend, fresh=True)
        poll = getattr(raw, 'media', None)
        if not isinstance(poll, types.MessageMediaPoll):
            raise LookupError('no poll')
        media = poll.attached_media if part == 'attached' else poll.results.solution_media
        if not isinstance(media, (types.MessageMediaPhoto, types.MessageMediaDocument)):
            raise LookupError('no poll attachment')
        asset = media.photo if isinstance(media, types.MessageMediaPhoto) else media.document
        from .media_lifetime import transient, purge_cached
        if restricted or transient(media):
            purge_cached(self, account, peer, ident)
            return await self.transient_media().file(account, backend, peer, ident, raw, thumbnail, 'original',
                                                     media=media, variant=('poll', part, asset.id))
        folder = self.media_folder()
        if self.account != account or self.backend is not backend or self.locked:
            return None
        stem = f'{peer}-{ident}-poll-{part}-{asset.id}' + ('-t' if thumbnail else '')
        existing = next((p for p in folder.glob(stem + '.*') if p.is_file() and p.stat().st_size), None)
        if existing:
            return existing
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = await backend.download_media(media, folder / stem, thumbnail=thumbnail)
        if path and (self.account != account or self.backend is not backend or self.locked):
            Path(path).unlink(missing_ok=True)
            raise PermissionError('The active account changed.')
        return Path(path) if path else None

    # -- stickers and custom emoji (desktop: sticker_picker, telegram_extras) ----
    def remember_documents(self, documents):
        """Keep the documents the page can refer to by id (send, show, view pack)."""
        from tg_ascii.telegram_extras import sticker_alt
        store = self.__dict__.setdefault('sticker_store', {})
        items = []
        for document in documents or ():
            if document is None or not hasattr(document, 'id'):
                continue
            store.pop(document.id, None)
            store[document.id] = document
            mime = getattr(document, 'mime_type', '') or ''
            items.append({'id': str(document.id), 'emoji': sticker_alt(document),
                          'animated': mime == 'application/x-tgsticker', 'video': mime.startswith('video/')})
        while len(store) > 3000:
            store.pop(next(iter(store)))
        return items

    def pack_json(self, packs):
        store = self.__dict__.setdefault('pack_store', {})
        result = []
        for pack in packs or ():
            store[pack.id] = pack
            result.append({'id': str(pack.id), 'title': self.text(pack.title), 'count': int(getattr(pack, 'count', 0) or 0),
                           'emoji': bool(getattr(pack, 'emojis', False))})
        return result

    async def api_sticker_packs(self, custom=False):
        return self.pack_json(await asyncio.wait_for(self.backend.sticker_packs(bool(custom)), 30))

    async def api_sticker_documents(self, pack=None):
        """A pack's stickers / emoji, or the recent stickers (pack None)."""
        if pack == 'recent_emoji':
            # Like Telegram: its default emoji, reordered by use, with the custom ones used.
            from tg_ascii.emoji_usage import recent_items
            items = await asyncio.wait_for(recent_items(self.backend), 30)
            result = []
            for item in items:
                if isinstance(item, str):
                    result.append({'id': None, 'emoji': item, 'standard': True})
                else:
                    result.extend(self.remember_documents([item]))
            return result
        if pack == 'favourites':
            return self.remember_documents(await asyncio.wait_for(self.backend.sticker_documents(pack), 30))
        target = self.__dict__.get('pack_store', {}).get(int(pack)) if pack else None
        if pack and target is None:
            raise LookupError('pack')
        return self.remember_documents(await asyncio.wait_for(self.backend.sticker_documents(target), 30))

    async def api_sticker_search(self, query, custom=False, offset=0):
        from tg_ascii.i18n import get_language
        from tg_ascii.sticker_search import search
        result = await asyncio.wait_for(search(self.backend, str(query), bool(custom), get_language(), int(offset or 0)), 30)
        return {'documents': self.remember_documents(result['documents']), 'packs': self.pack_json(result['packs']),
                'next': result['next']}

    async def api_send_sticker(self, peer, id, reply_to=None, thread_root=None, account=None, topic_id=None):
        reply_to = self.send_reply(peer, reply_to, thread_root, account)
        if topic_id is not None:
            reply_to = await self.forum_call('forum_reply', int(peer), int(topic_id),
                                           reply_to if reply_to != thread_root else None, account=account)
        account = self.account
        document = self.__dict__.get('sticker_store', {}).get(int(id))
        if document is None:
            raise LookupError('sticker')
        message = await asyncio.wait_for(self.backend.send_sticker(int(peer), document, reply_to=reply_to), 60)
        self.local_message(account, int(peer), message)
        return True

    async def api_sticker_pack_of(self, id):
        """The pack a sticker / custom emoji belongs to (View pack)."""
        document = self.__dict__.get('sticker_store', {}).get(int(id))
        result = await asyncio.wait_for(self.backend.document_pack(document if document is not None else int(id)), 30)
        pack = result.set
        installed = bool(getattr(pack, 'installed_date', None))
        return {'pack': self.pack_json([pack])[0], 'installed': installed,
                'documents': self.remember_documents(result.documents)}

    async def api_install_pack(self, id):
        pack = self.__dict__.get('pack_store', {}).get(int(id))
        if pack is None:
            raise LookupError('pack')
        result = await asyncio.wait_for(self.backend.install_pack(pack), 30)
        return {'archived': type(result).__name__ == 'StickerSetInstallResultArchive'}

    async def sticker_file(self, ident):
        """Return the original WebP or the still thumbnail of a moving sticker."""
        return await self._sticker_asset(int(ident), animated=False)

    async def sticker_animation(self, ident):
        """Return Lottie JSON or WebM for moving stickers and custom emoji."""
        return await self._sticker_asset(int(ident), animated=True)

    async def _sticker_asset(self, ident, animated):
        import gzip
        folder = self.root / 'mobile-stickers'
        still = folder / f'{ident}.webp'
        lottie = folder / f'{ident}-anim.json'
        video = folder / f'{ident}-anim.webm'
        marker = folder / f'{ident}-anim.none'
        def cached():
            for candidate in ((lottie, video) if animated else (still,)):
                try:
                    if candidate.stat().st_size:
                        return candidate
                except FileNotFoundError:
                    pass
            return marker if animated and marker.exists() else None

        # Independent windows can request the same document at once. A cached
        # thumbnail should still be available while its animation downloads.
        path = cached()
        if path is not None:
            return None if path == marker else path
        lock = self._sticker_locks.get(ident)
        if lock is None:
            lock = self._sticker_locks[ident] = asyncio.Lock()
        async with lock:
            path = cached()
            if path is not None:
                return None if path == marker else path
            async with self._sticker_downloads:
                backend = self.backend
                if backend is None:
                    raise ConnectionError('offline')
                store = self.__dict__.setdefault('sticker_store', {})
                document = store.get(ident)
                if document is None:
                    self.remember_documents(await backend.custom_emoji_documents([ident]))
                    document = store.get(ident)
                if document is None:
                    raise LookupError('sticker')
                folder.mkdir(parents=True, exist_ok=True, mode=0o700)
                mime = getattr(document, 'mime_type', '') or ''
                if animated:
                    if mime not in ('video/webm', 'application/x-tgsticker') or getattr(document, 'size', 0) > 4 * 1024 * 1024:
                        marker.touch()
                        return None
                    path = video if mime == 'video/webm' else lottie
                else:
                    if mime != 'image/webp' and not getattr(document, 'thumbs', None):
                        return None
                    path = still
                with tempfile.NamedTemporaryFile(dir=folder, prefix='.sticker-', delete=False) as stream:
                    temp = Path(stream.name)
                    try:
                        if path == lottie:
                            data = await backend.client.download_media(document, file=bytes)
                            if data:
                                def unpack():
                                    import io
                                    limit = 4 * 1024 * 1024
                                    if len(data) > limit:
                                        raise ValueError('animation too large')
                                    with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
                                        expanded = compressed.read(limit + 1)
                                    if len(expanded) > limit:
                                        raise ValueError('animation too large')
                                    return expanded
                                stream.write(await asyncio.to_thread(unpack))
                        else:
                            thumb = -1 if path == still and mime != 'image/webp' else None
                            await backend.client.download_media(document, file=stream, thumb=thumb)
                        if not stream.tell():
                            return None
                        stream.flush()
                        temp.replace(path)
                        return path
                    finally:
                        temp.unlink(missing_ok=True)

    # -- attachments (phase 2) -------------------------------------------------
    def staging_path(self, name):
        """A new private file for an attachment; the name keeps its extension."""
        import re
        import uuid
        folder = self.root / STAGING_FOLDER
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        clean = re.sub(r'[^\w.\- ]+', '_', Path(str(name)).name).strip(' .')[:120] or 'file'
        return folder / f'{uuid.uuid4().hex[:12]}-{clean}'

    def staged(self, key):
        folder = (self.root / STAGING_FOLDER).resolve()
        path = (folder / str(key)).resolve()
        if path.parent != folder or not path.is_file():
            raise ValueError('unknown attachment')
        return path

    def prune_staging(self, age=STAGING_DAYS * 86400):
        """Attachments no longer waiting in the outbox, older than ``age`` s."""
        folder = (self.root / STAGING_FOLDER).resolve()
        if not folder.is_dir():
            return
        waiting = {str(path) for item in (self.outbox.items if self.outbox else ()) for path in item.paths}
        waiting.update(path for chats in self.draft_store.records.values()
                       for draft in chats.values() for path in draft['files'])
        waiting.update(path for draft in self.__dict__.get('_secret_drafts', {}).values()
                       for path in draft.get('files', ()))
        limit = time.time() - age
        for path in folder.iterdir():
            try:
                if str(path) not in waiting and path.stat().st_mtime < limit:
                    path.unlink()
            except OSError:
                pass

    def schedule_prune_sent(self, *args):
        if self._prune_handle is None:
            self._prune_handle = self.loop.call_later(5, self._prune_sent)

    def _prune_sent(self):
        self._prune_handle = None
        try:
            self.prune_staging(age=3600)
        except OSError:
            pass

    async def api_send_files(self, peer, keys, caption='', reply_to=None, silent=False, schedule=None,
                             account=None, thread_root=None, spans=(), custom=(), topic_id=None, photo_quality=None):
        from tg_ascii.outbox import Pending
        from tg_ascii.media_quality import validate_photo_quality
        photo_quality = validate_photo_quality(photo_quality)
        reply_to = self.send_reply(peer, reply_to, thread_root, account)
        if topic_id is not None:
            if int(topic_id) != thread_root:
                raise ValueError('The topic changed.')
            reply_to = None if reply_to == thread_root else reply_to
        caption = str(caption or '')
        formats, custom = self.outgoing_format(caption, spans, custom)
        paths = [str(self.staged(key)) for key in keys][:10]
        if not paths:
            raise ValueError('empty')
        item = Pending(account=self.account, peer=peer, text=caption, paths=paths,
                       reply_to=reply_to, silent=bool(silent), schedule=scheduled_at(schedule),
                       thread_root=thread_root, topic_id=topic_id, format_spans=formats, custom_spans=custom,
                       photo_quality=photo_quality)
        self.outbox.add(item, require_persistence=True)
        self.set_draft(int(peer), '', thread_root)
        return {'key': item.key}

    async def api_discard_files(self, keys):
        for key in keys:
            try:
                self.staged(key).unlink()
            except (ValueError, OSError):
                pass
        return True

    # -- voice messages (desktop: desktop_tools.record_audio) -----------------------
    async def api_voice_start(self, capture=None, account=None):
        from tg_ascii.i18n import tr
        if self.native_voice is None:
            raise ValueError(tr('Voice messages cannot be recorded on this device.'))
        async with self.voice_gate:
            self.check_active_account(account)
            if self.locked:
                raise PermissionError('locked')
            if self.voice_recording is not None:
                raise ValueError(tr('Could not start recording.'))
            base = str(self.staging_path('voice'))
            future = self.loop.create_future()
            recording = self.voice_recording = {'capture': capture, 'future': future}
            self.expect_external(90)  # the microphone permission dialog

            def done(result):
                self.loop.call_soon_threadsafe(lambda: future.done() or future.set_result(result))
            try:
                self.native_voice['start'](base, done)
            except Exception:
                self.voice_recording = None
                raise
        try:
            result = await asyncio.wait_for(future, 90)
            if self.voice_recording is not recording or self.locked:
                raise ValueError(tr('Could not start recording.'))
        except (Exception, asyncio.CancelledError):
            if self.voice_recording is recording:
                await self.api_voice_cancel(capture=capture)
            raise
        finally:
            if self.voice_recording is recording:
                self.external_until = time.monotonic() + 3
        if result.get('error') or not result.get('path'):
            await self.api_voice_cancel(capture=capture)
            if result.get('error') == 'permission':
                message = tr('TG-ASCII needs access to the microphone to record voice messages.')
                raise ValueError(message.replace('TG-ASCII', 'TeleGraph'))
            raise ValueError(tr('Could not start recording.'))
        recording.update(path=result['path'], started=time.monotonic())
        return {'recording': True}

    async def api_voice_level(self, capture=None):
        recording = self.voice_recording
        if not recording or 'started' not in recording or recording['capture'] != capture:
            return {'recording': False, 'level': 0, 'seconds': 0}
        level = await asyncio.to_thread(self.native_voice['level'])
        return {'recording': True, 'level': round(float(level), 3), 'seconds': round(time.monotonic() - recording['started'], 1)}

    async def api_voice_stop(self, capture=None):
        """Stop recording: the voice message waits (staged) to be listened to and sent."""
        from tg_ascii.i18n import tr
        from . import opus_mux
        async with self.voice_gate:
            recording = self.voice_recording
            if not recording or recording['capture'] != capture or 'started' not in recording:
                raise ValueError(tr('Nothing was recorded.'))
            self.voice_recording = None
            elapsed = time.monotonic() - recording['started']
            path = await asyncio.to_thread(self.native_voice['stop'])
        if not path or not Path(path).is_file() or Path(path).stat().st_size == 0:
            raise ValueError(tr('Nothing was recorded.'))
        path = Path(path)
        os.chmod(path, 0o600)
        preview = path
        if path.suffix == '.caf':
            target = path.with_suffix('.ogg')
            try:
                seconds = await asyncio.to_thread(opus_mux.caf_to_ogg, path, target)
                os.chmod(target, 0o600)
            except Exception:
                target.unlink(missing_ok=True)
                path.unlink(missing_ok=True)
                raise ValueError(tr('Could not save the recording.'))
            path = target
        elif path.suffix == '.ogg':
            seconds = await asyncio.to_thread(opus_mux.duration, path) or elapsed
        else:
            seconds = elapsed
        if seconds < 0.5:
            for item in {path, preview}:
                item.unlink(missing_ok=True)
            raise ValueError(tr('The recording is too short.'))
        return {'key': path.name, 'preview': preview.name, 'duration': round(seconds, 1),
                'voice': path.suffix == '.ogg'}

    async def cancel_current_voice(self):
        recording = self.voice_recording
        if recording is not None:
            await self.api_voice_cancel(capture=recording['capture'])

    async def api_voice_cancel(self, keys=(), capture=None):
        async with self.voice_gate:
            recording = self.voice_recording
            if recording and recording['capture'] == capture:
                self.voice_recording = None
                future = recording['future']
                if not future.done():
                    future.set_result({'error': 'cancelled'})
                self.external_until = time.monotonic()
                path = await asyncio.to_thread(self.native_voice['cancel'])
                for item in {path, recording.get('path')}:
                    if item:
                        Path(item).unlink(missing_ok=True)
        await self.api_discard_files([key for key in keys or () if key])
        return True

    async def api_send_voice(self, peer, key, duration, preview=None, reply_to=None, silent=False,
                             thread_root=None, account=None, topic_id=None):
        from tg_ascii.outbox import Pending
        reply_to = self.send_reply(peer, reply_to, thread_root, account)
        if topic_id is not None:
            if int(topic_id) != thread_root:
                raise ValueError('The topic changed.')
            reply_to = None if reply_to == thread_root else reply_to
        path = self.staged(key)
        voice = float(duration or 0) if path.suffix == '.ogg' else 0.0
        item = Pending(account=self.account, peer=peer, paths=[str(path)], reply_to=reply_to,
                       thread_root=thread_root, topic_id=topic_id, silent=bool(silent), voice=max(1.0, voice) if voice else 0.0)
        self.outbox.add(item, require_persistence=True)
        if preview and preview != key:
            await self.api_discard_files([preview])
        return {'key': item.key}

    async def api_pick_files(self, kind='any'):
        """Android: the system picker (the WebView cannot open one)."""
        if self.native_picker is None:
            raise LookupError('pick_files')
        future = self.loop.create_future()
        self.expect_external(300)

        def finished(result):
            self.external_until = time.monotonic() + 3
            self.loop.call_soon_threadsafe(lambda: future.done() or future.set_result(result))
        self.native_picker(kind, finished)
        return await future

    # -- API (called by the server on the worker loop) ----------------------------
    async def call(self, method, params):
        if self.locked and method not in UNLOCKED_METHODS:
            raise PermissionError('locked')
        handler = getattr(self, 'api_' + method.replace('.', '_'), None)
        if handler is None or not callable(handler):
            raise LookupError(method)
        if method not in ('profile', 'contacts', 'profile_tab') and any(word in method for word in CHANGES_DETAILS):
            self.forget_details()
        return await handler(**params)

    def forget_notification_chats(self, account=None, peer=None):
        forget = getattr(self, 'native_forget_notification_chats', None)
        if forget:
            try:
                forget(account, peer)
            except Exception as error:
                print('remove conversation shortcut:', type(error).__name__)

    async def api_take_notification_chat(self):
        take = getattr(self, 'native_take_notification_chat', None)
        if not take or self.locked or self.stage not in ('choose_account', 'ready'):
            return None
        route = take()
        if route and self.lock_record() is None and self.prefs.values.get('notify_preview', True):
            account, _, peer = str(route).rpartition(':')
            if account in self.accounts.identities and peer.removeprefix('-').isdigit():
                return {'account': account, 'peer': int(peer)}
        return None

    async def api_state(self, locale='', window_account=None):
        if locale and not self.locale:
            self.locale = locale
        return self.state_snapshot(window_account)

    async def api_launch_ready(self):
        ready = getattr(self, 'native_page_ready', None)
        if ready:
            self.native_page_ready = None
            ready()

    async def api_strings(self, keys=(), include_web=False):
        from tg_ascii.i18n import tr
        if include_web:
            from .strings import web_keys
            keys = dict.fromkeys((*web_keys(), *(key for key in keys if isinstance(key, str))))
        return {key: tr(key) for key in keys if isinstance(key, str)}

    async def api_languages(self):
        from tg_ascii.i18n import LANGUAGES
        return [[code, name] for code, name in LANGUAGES.items()]

    # sign-in
    async def api_login_phone(self, phone):
        state = await self.accounts.request_code(phone)
        self.set_stage(state)
        return state

    async def api_login_code(self, code):
        state = await self.accounts.verify_code(code)
        self.after_login(state)
        return state

    async def api_login_signup_help(self):
        if self.stage != 'phone':
            return False
        self.set_stage('signup')
        return True

    async def api_login_back(self):
        if self.stage != 'signup':
            return False
        self.set_stage('phone')
        return True

    async def api_login_password(self, password):
        state = await self.accounts.verify_password(password)
        self.after_login(state)
        return state

    async def api_login_qr(self):
        if self.qr_task is not None and not self.qr_task.done():
            return 'qr'

        async def run():
            from tg_ascii.auth import error_message
            try:
                state = await self.accounts.login_qr(lambda url: self.emit('qr', {'url': url, 'svg': qr_svg(url)}))
            except asyncio.CancelledError:
                return
            except Exception as exc:
                self.emit('toast', {'text': error_message(exc), 'kind': 'error'})
                return
            self.after_login(state)
        self.qr_task = self.loop.create_task(run())
        return 'qr'

    async def api_login_qr_cancel(self):
        if self.qr_task is not None:
            self.qr_task.cancel()
            self.qr_task = None
        return True

    async def api_retry(self):
        await self.connect()
        return self.stage

    # chats and messages
    async def api_tv_share(self, peer, account, topic_id=None):
        from .tv import share_chat
        return await share_chat(self, peer, account, topic_id)

    async def api_tv_disconnect(self):
        self.disconnect_tv()
        return True

    def disconnect_tv(self):
        if getattr(self, 'tv_link', None):
            self.tv_link.disconnect()

    async def api_chats(self):
        if self.stage == 'ready' and self.backend is not None:
            self.loop.create_task(self.refresh_chats())
        return [self.chat_json(chat) for chat in self.visible_chats()]

    async def api_archived(self):
        return [self.chat_json(chat) for chat in self.visible_chats(archived=True)]

    async def api_open(self, peer, read=True, window=False):
        """Open a chat. read=False is the preview: nothing is marked as read.
        window=True: in its own system window, leaving the main window's chat."""
        if window:
            self.window_peers.add(peer)
            self.window_revisions.pop(peer, None)
            self.window_discussions.pop(peer, None)
        else:
            self.open_revision += 1
            self.open_peer = peer
            self.open_discussion = None
            self.discussion_messages.clear()
            self.preview = not read
        chat = next((item for item in self.chats if item.id == peer), None)
        if chat is not None and self.chat_json(chat)['forum']:
            if not window:
                self.open_peer = None
            return {'peer': peer, 'forum': True, 'chat': self.chat_json(chat)}
        if read:
            self.clear_notifications(peer)
        self.trim_histories(peer)
        cached = self.histories.get(peer)
        chat = next((item for item in self.chats if item.id == peer), None)
        if read and chat is not None and (chat.unread or chat.unread_mark):
            chat.unread, chat.unread_mark = 0, False
            self.emit('chat', self.chat_json(chat))
        if self.backend is not None:
            self.loop.create_task(self.reload_and_read(peer) if read else self.refresh_history(peer))
            self.loop.create_task(self.refresh_header(peer))
        return {'peer': peer, 'messages': [self.message_json(m) for m in cached or []],
                'draft': self.draft_record(peer),
                'outbox': self.outbox_items(self.account, peer),
                **self.translation_state(peer, cached or ()),
                'chat': self.chat_json(chat) if chat is not None else None}

    async def reload_and_read(self, peer):
        backend = self.backend
        await self.refresh_history(peer)
        if backend is None or backend is not self.backend or self.locked or self.is_forum_chat(peer):
            return
        history = self.histories.get(peer) or []
        incoming = [m.id for m in history if not m.outgoing]
        if incoming:
            try:
                await backend.mark_read(peer, max(incoming))
            except Exception:
                pass

    async def api_close(self, peer=None, window=False):
        if window:
            self.window_peers.discard(peer)
            self.window_revisions.pop(peer, None)
            self.window_discussions.pop(peer, None)
            self.trim_histories()
            return True
        if self.locked:
            raise PermissionError('locked')
        closing_thread = self.open_discussion is not None and (peer is None or peer == self.open_discussion[1])
        if closing_thread or peer is None or peer == self.open_peer:
            self.open_revision += 1
        if closing_thread:
            self.open_discussion = None
            self.discussion_messages.clear()
        if self.open_peer == peer or peer is None:
            self.open_peer = None
            self.preview = False
        self.trim_histories()
        return True

    async def api_read(self, peer):
        """End a preview: mark the chat as read now."""
        if peer == self.open_peer:
            self.preview = False
        chat = next((item for item in self.chats if item.id == peer), None)
        if chat is not None and (chat.unread or chat.unread_mark):
            chat.unread, chat.unread_mark = 0, False
            self.emit('chat', self.chat_json(chat))
        history = self.histories.get(peer) or []
        incoming = [m.id for m in history if not m.outgoing]
        if incoming and self.backend is not None:
            from tg_ascii.pending_actions import Queued
            result = await asyncio.wait_for(self.backend.mark_read(peer, max(incoming)), ACTION_TIMEOUT)
            return {'queued': isinstance(result, Queued)}
        return True

    async def api_older(self, peer, before, account=None):
        self.check_active_account(account)
        account, backend = self.account, self.backend
        messages = await self.history_page(peer, backend.older_messages(peer, before))
        if self.account != account or self.backend is not backend:
            raise ValueError('The active account changed.')
        history = self.histories.setdefault(peer, [])
        known = {item.id for item in history}
        additions = [m for m in messages if m.id not in known]
        history[:0] = additions
        if additions:
            self.record_history_change(peer, 'older', additions)
        return {'messages': [self.message_json(m) for m in messages], **self.translation_state(peer, messages)}

    def check_active_account(self, account):
        if account is not None and account != self.account:
            raise ValueError('The active account changed.')

    def check_backend_context(self, account, backend):
        if self.locked or self.account != account or self.backend is not backend:
            raise ValueError('The active account changed.')

    def send_reply(self, peer, reply_to, thread_root, account):
        self.check_active_account(account)
        self.draft_location(peer, thread_root)
        return reply_to or thread_root

    @staticmethod
    def outgoing_format(text, spans, custom, emojis=()):
        from tg_ascii.message_tools import STYLES, formatted_entities

        formats = []
        for span in spans or ():
            start, end, style = int(span[0]), int(span[1]), str(span[2])
            argument = str(span[3]) if len(span) > 3 and span[3] else ''
            if style in STYLES and 0 <= start < end <= len(text):
                formats.append([start, end, style, argument])
        custom = [[int(start), int(end), int(ident), str(alt)] for start, end, ident, alt in custom]
        position = 0
        for ident, alt in emojis or ():
            at = text.find(str(alt), position)
            if at >= 0:
                custom.append([at, at + len(alt), int(ident), str(alt)])
                position = at + len(alt)
        if formats or custom:
            formatted_entities(text, [tuple(item) for item in formats], [tuple(item) for item in custom])  # rejects overlaps now
        return formats, custom

    async def api_send(self, peer, text, reply_to=None, silent=False, schedule=None, spans=(), emojis=(), custom=(), account=None, thread_root=None, topic_id=None):
        """spans: text formatting [[start, end, style, argument]] (bold, italic, underline,
        strike, spoiler, code, link, quote, collapsed_quote); emojis: custom emoji [[id, alt]]."""
        from tg_ascii.outbox import Pending
        reply_to = self.send_reply(peer, reply_to, thread_root, account)
        if topic_id is not None:
            if int(topic_id) != thread_root:
                raise ValueError('The topic changed.')
            reply_to = None if reply_to == thread_root else reply_to
        text = str(text)
        if not text.strip():
            raise ValueError('empty')
        formats, custom = self.outgoing_format(text, spans, custom, emojis)
        item = Pending(account=self.account, peer=peer, text=text, reply_to=reply_to, silent=bool(silent),
                       thread_root=thread_root, topic_id=topic_id, schedule=scheduled_at(schedule), format_spans=formats, custom_spans=custom)
        self.outbox.add(item, require_persistence=True)
        self.set_draft(int(peer), '', thread_root)
        return {'key': item.key}

    # -- conversation extras -------------------------------------------------------
    async def refresh_header(self, peer):
        """Only the newest header query for this account and chat can publish."""
        account, backend = self.account, self.backend
        if backend is None:
            return
        requests = self.__dict__.setdefault('_header_requests', {})
        key, token = (account, peer), object()
        requests[key] = token
        try:
            header = await backend.chat_header(peer)
            if (self.account != account or self.backend is not backend or self.locked
                    or requests.get(key) is not token):
                return
            seconds = bool(self.prefs and self.prefs.values.get('show_seconds'))
            status = header.get('status', '')
            try:
                from tg_ascii.telegram_actions import peer_activity
                status = peer_activity(header.get('activity_entity'), seconds) or status
            except Exception:
                pass
            self.emit('header', {'peer': peer, 'status': self.text(status or '')})
        except Exception:
            return
        finally:
            if requests.get(key) is token:
                requests.pop(key, None)

    async def api_draft(self, peer, account, text, formats=(), custom=(), reply=None, files=(), thread_root=None,
                        window_peer=None, photo_quality=None):
        from tg_ascii.message_tools import formatted_entities
        from tg_ascii.media_quality import validate_photo_quality
        photo_quality = validate_photo_quality(photo_quality)
        if account != self.account or self.stage != 'ready':
            raise ValueError('The active account changed.')
        peer = int(peer)
        if self.locked:
            # The native background callback may lock before the WebView's
            # final write arrives. Only its already-open composer may save.
            active = (self.discussion_view(window_peer)[0] == (account, peer, thread_root) if thread_root is not None
                      else peer == self.open_peer or peer in self.window_peers or peer in self.floating_peers)
            if not active:
                raise PermissionError('locked')
        text = str(text or '')
        if len(text) > 4096:
            raise ValueError('Draft exceeds 4096 characters.')
        formats = [tuple(span) for span in formats]
        custom = [(start, end, int(ident), alt) for start, end, ident, alt in custom]
        formatted_entities(text, formats, custom)
        paths = [str(self.staged(key)) for key in files[:10]]
        record = {'text': text, 'formats': formats, 'custom': custom, 'reply': reply, 'files': paths}
        if photo_quality is not None:
            record['photo_quality'] = photo_quality
        self.set_draft(peer, record, thread_root)
        return True

    def load_drafts(self):
        account = self.account
        if account in self.loaded_draft_accounts:
            return
        # Import the earlier mobile text-only format once, retaining its
        # original file so an interrupted migration can be retried.
        source = self.root / 'mobile' / f'drafts-{account}.json'
        if account not in self.draft_store.records:
            try:
                records = json.loads(source.read_text('utf-8'))
            except (OSError, ValueError):
                records = {}
            if isinstance(records, dict):
                for peer, record in records.items():
                    try:
                        peer = int(peer)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(record, dict) and isinstance(record.get('text'), str):
                        self.draft_store.put(account, peer, {'text': record['text']}, pending=True)
                self.draft_store.flush()
                if source.is_file():
                    source.replace(source.with_suffix('.migrated.json'))
        self.loaded_draft_accounts.add(account)

    def draft_location(self, peer, thread_root):
        if thread_root is None:
            return self.account, peer
        if type(thread_root) is not int or thread_root <= 0:
            raise ValueError('Invalid discussion thread.')
        return f'discussion:{self.account}:{peer}', thread_root

    def draft_record(self, peer, thread_root=None):
        from tg_ascii.secret_chats import is_secret_peer
        if is_secret_peer(peer):
            record = self.secret_draft(peer)
        else:
            record = self.draft_store.get(*self.draft_location(peer, thread_root)) or {}
        files = []
        for value in record.get('files', ()):
            try:
                path = self.staged(Path(value).name)
                files.append({'key': path.name, 'name': path.name.partition('-')[2] or path.name,
                              'size': path.stat().st_size})
            except (OSError, ValueError):
                continue
        return {'text': record.get('text', ''), 'formats': record.get('formats', []),
                'custom': [[start, end, str(ident), alt] for start, end, ident, alt in record.get('custom', ())],
                'reply': record.get('reply'), 'files': files,
                **({'photo_quality': record['photo_quality']} if record.get('photo_quality') else {})}

    def secret_draft(self, peer):
        from tg_ascii.secret_chats import secret_chat_id

        current = self.__dict__.get('_secret_drafts', {}).get((self.account, int(peer)), {})
        manager = getattr(self.backend, 'secret_chats', None)
        if manager is None:
            return current
        session = manager.sessions.get(secret_chat_id(peer))
        if session is None or session.state == 'discarded':
            return {}
        return current or manager.local_draft(peer)

    def emit_draft(self, peer, thread_root=None):
        if thread_root is not None:
            self.emit('draft', {'account': self.account, 'peer': peer, 'thread_root': thread_root,
                                'record': self.draft_record(peer, thread_root)})
            return
        self.emit('draft', {'account': self.account, 'peer': peer, 'record': self.draft_record(peer)})
        chat = next((item for item in self.chats if item.id == peer), None)
        if chat is not None:
            self.emit('chat', self.chat_json(chat))

    def set_draft(self, peer, record, thread_root=None):
        from tg_ascii.secret_chats import is_secret_peer
        if isinstance(record, str):
            record = {'text': record}
        if is_secret_peer(peer):
            store = self.__dict__.setdefault('_secret_drafts', {})
            key_pair = (self.account, int(peer))
            previous = self.secret_draft(peer)
            record = record or {}
            manager = getattr(self.backend, 'secret_chats', None)
            if manager is not None and record != previous:
                manager.save_local_draft(peer, record)
            if not (record.get('text') or record.get('files') or record.get('reply')):
                store.pop(key_pair, None)
            else:
                store[key_pair] = dict(record)
            if record != previous:
                self.emit_draft(peer)
            return
        owner, key = self.draft_location(peer, thread_root)
        previous = self.draft_store.get(owner, key)
        self.draft_store.put(owner, key, record, pending=False if thread_root is not None else None)
        # A failed disk write leaves the new record in memory. An identical
        # retry must finish persisting it before the composer can close.
        self.draft_store.flush()
        current = self.draft_store.get(owner, key)
        if current != previous or (current and current['pending']):
            self.emit_draft(peer, thread_root)
            if thread_root is None:
                self.schedule_draft_sync()

    def receive_draft(self, peer, remote):
        account = self.account
        current = self.draft_store.get(account, peer)
        if (current and current['pending']) or remote.get('unsupported'):
            return
        record = {**remote, 'files': current['files'] if current else []}
        if current and current.get('photo_quality'):
            record['photo_quality'] = current['photo_quality']
        self.draft_store.put(account, peer, record, pending=False)
        if self.draft_store.get(account, peer) != current:
            self.draft_store.flush()
            self.emit_draft(peer)

    def schedule_draft_sync(self, *, pull=False):
        account, backend = self.account, self.backend
        if backend is None:
            return
        if pull:
            key = (account, id(backend))
            task = self.draft_pull_jobs.get(key)
            if task is None or task.done():
                task = self.loop.create_task(self.sync_drafts(account, backend, pull=True))
                self.draft_pull_jobs[key] = task

                def finished(result):
                    if self.draft_pull_jobs.get(key) is result:
                        self.draft_pull_jobs.pop(key, None)
                    if not result.cancelled():
                        result.exception()
                task.add_done_callback(finished)
        elif account not in self.draft_jobs:
            async def delayed():
                await asyncio.sleep(0.6)
                self.draft_jobs.pop(account, None)
                await self.sync_drafts(account, backend)
            self.draft_jobs[account] = self.loop.create_task(delayed())

    async def sync_drafts(self, account, backend, *, pull=False):
        from tg_ascii.drafts import PERMANENT_DRAFT_ERRORS
        lock = self.draft_sync_locks.setdefault(account, asyncio.Lock())
        async with lock:
            if pull:
                versions = dict(getattr(backend, '_draft_versions', {}))
                try:
                    cloud = await backend.fetch_drafts()
                except Exception:
                    return
                if account == self.account and backend is self.backend:
                    peers = set(cloud) | {int(peer) for peer in self.draft_store.records.get(account, {})}
                    for peer in peers:
                        if versions.get(peer, 0) == getattr(backend, '_draft_versions', {}).get(peer, 0):
                            self.receive_draft(peer, cloud.get(peer, {}))
            for key in self.draft_store.pending_records(account).get(account, {}):
                service = self.accounts.services.get(account)
                if getattr(service, 'backend', None) is not backend:
                    break
                peer = int(key)
                if peer in getattr(backend, '_protected_drafts', ()):
                    continue
                record = self.draft_store.get(account, peer)
                if not record or not record['pending']:
                    continue
                try:
                    await backend.save_draft(peer, record['text'], record['formats'], record['custom'], record['reply'])
                except PERMANENT_DRAFT_ERRORS:
                    continue
                except Exception:
                    break
                self.draft_store.mark_synced(account, peer, record)
                self.draft_store.flush()

    async def api_typing(self, peer):
        backend = self.backend
        if backend is not None:
            try:
                await asyncio.wait_for(backend.typing(peer, True), 10)
            except Exception:
                pass
        return True

    # -- folders, search, contacts, profile -------------------------------------------
    async def api_folders(self, refresh=True, account=None):
        """Telegram chat folders and which chats each one shows (refresh asks
        Telegram again; otherwise the last folders are matched to the list)."""
        from telethon import utils
        from tg_ascii.telegram_features import compile_folder, in_chat_list
        self.check_active_account(account)
        owner, backend = self.account, self.backend
        if backend is not None and hasattr(backend, 'folders') and (refresh or not self.folder_records):
            try:
                records = await asyncio.wait_for(backend.folders(), 30)
            except Exception:
                records = None
            if self.account != owner or self.backend is not backend:
                raise ValueError('The active account changed.')
            if records is not None:
                self.folder_records = records
        result = []
        for folder in self.folder_records:
            compiled = compile_folder(folder)
            raw = getattr(folder, 'title', '')
            title = getattr(raw, 'text', raw) or ''
            ids = [chat.id for chat in self.chats if in_chat_list(chat, folder, compiled)]
            result.append({'id': folder.id, 'title': self.text(str(title)), 'chats': ids,
                           'pins': [utils.get_peer_id(p) for p in getattr(folder, 'pinned_peers', ())],
                           # Custom emoji in the folder name (Telegram's TextWithEntities).
                           'emojis': custom_emoji_spans(str(title), getattr(raw, 'entities', None)),
                           'still': bool(getattr(folder, 'title_noanimate', False))})
        return result

    async def api_recent_searches(self, account, scope, query=None, clear=False):
        from tg_ascii.recent_searches import RecentSearches
        from tg_ascii.secret_chats import is_secret_peer
        self.check_active_account(account)
        scope = str(scope)
        if not scope or len(scope) > 100:
            raise ValueError('Invalid search scope')
        if scope.startswith('messages:') and is_secret_peer(int(scope.split(':')[1])):
            return []
        history = RecentSearches(self.root)
        if clear:
            return history.clear(account, scope)
        return history.list(account, scope) if query is None else history.remember(account, scope, query)

    async def api_frequent_peers(self, account):
        from tg_ascii.recent_searches import frequent_peers
        self.check_active_account(account)
        stamp, peers = self.__dict__.get('_frequent_peers', {}).get(account, (0, []))
        if stamp and time.monotonic() - stamp < 300:
            return peers
        backend = self.backend
        if self.connection != 'online' or backend is None:
            return peers
        peers = await asyncio.wait_for(frequent_peers(backend), 6)
        self.check_active_account(account)
        self.__dict__.setdefault('_frequent_peers', {})[account] = (time.monotonic(), peers)
        return peers

    async def api_search_global(self, query):
        """Public chats and people (contacts.search) and messages from every chat."""
        backend = self.backend
        query = str(query or '').strip()
        if backend is None or len(query) < 2:
            return {'chats': [], 'messages': []}
        chats, messages = [], []
        try:
            for chat in (await asyncio.wait_for(backend.search_public(query), 30))[:30]:
                chats.append({'id': chat.id, 'name': self.text(chat.name), 'kind': chat.kind,
                              'unread': 0, 'pinned': False, 'muted': False, 'archived': False,
                              'unread_mark': False, 'preview': '', 'out': False, 'date': None})
        except Exception:
            pass
        try:
            found, _more = await asyncio.wait_for(backend.global_messages(query), 30)
            for peer, name, message in found[:40]:
                messages.append({'peer': peer, 'name': self.text(name), 'message': self.message_json(message)})
        except Exception:
            pass
        return {'chats': chats, 'messages': messages}

    async def api_contacts(self):
        cached = self.cached_detail('contacts')
        if cached is not None:
            return cached
        account, backend = self.account, self.backend
        contacts = await self._contacts()
        self.check_backend_context(account, backend)
        return self.remember_detail('contacts', contacts)

    async def _contacts(self):
        from telethon import utils
        users = await asyncio.wait_for(self.backend.contacts(), 30)
        seconds = bool(self.prefs and self.prefs.values.get('show_seconds'))
        from tg_ascii.telegram_actions import peer_activity
        result = []
        for user in users:
            if getattr(user, 'deleted', False):
                continue
            try:
                status = peer_activity(user, seconds)
            except Exception:
                status = ''
            result.append({'id': user.id, 'name': self.text(utils.get_display_name(user) or str(user.id)),
                           'first': getattr(user, 'first_name', '') or '', 'last': getattr(user, 'last_name', '') or '',
                           'phone': getattr(user, 'phone', '') or '',
                           'username': getattr(user, 'username', '') or '', 'status': self.text(status or ''),
                           'emoji_status': emoji_status_id(user),
                           'kind': 'bot' if getattr(user, 'bot', False) else 'user'})
        result.sort(key=lambda item: item['name'].casefold())
        return result

    async def api_saved_messages(self):
        me = await asyncio.wait_for(self.backend.client.get_me(), 20)
        return {'id': me.id}

    async def api_resolve(self, value):
        chat = await asyncio.wait_for(self.backend.resolve_chat(str(value)), 30)
        return self.chat_json(chat)

    async def api_profile(self, peer):
        cached = self.cached_detail(('profile', peer))
        if cached is not None:
            return cached
        return self.remember_detail(('profile', peer), await self._profile(peer))

    async def _profile(self, peer):
        from tg_ascii.contact_appearance import validated_contact
        account, backend = self.account, self.backend
        data = await asyncio.wait_for(backend.profile(peer), 30)
        if self.account != account or self.backend is not backend:
            raise ValueError('The active account changed.')
        seconds = bool(self.prefs and self.prefs.values.get('show_seconds'))
        status = ''
        try:
            from tg_ascii.telegram_actions import peer_activity
            status = peer_activity(data.get('entity'), seconds)
        except Exception:
            status = ''
        chat = next((item for item in self.chats if item.id == peer), None)
        members = data.get('members_count')
        can_join = can_leave = False
        try:
            from tg_ascii.chat_capabilities import capabilities_for
            caps = capabilities_for(entity=data.get('entity'))
            can_join, can_leave = bool(caps.can_join), bool(caps.can_leave)
        except Exception:
            pass
        usernames = [name for name in data.get('usernames') or [] if name]
        banner = await self.profile_banner(data.get('profile_color'))
        if self.account != account or self.backend is not backend:
            raise ValueError('The active account changed.')
        return {'id': peer, 'name': self.text(data.get('name', '')), 'usernames': usernames,
                'card': validated_contact(self.prefs.values if self.prefs else {}),
                'emoji_status': emoji_status_id(data.get('entity')),
                'phone': data.get('phone', '') or '', 'about': self.text(data.get('about', '') or ''),
                'status': self.text(status or ''), 'members': members if isinstance(members, int) else None,
                'common': data.get('common_chats_count') or 0, 'link': data.get('invite_link') or '',
                'muted': bool(chat.muted) if chat else False, 'kind': data.get('kind') or (chat.kind if chat else ''),
                'is_self': bool(data.get('is_self')), 'contact': bool(data.get('contact')),
                'forum': bool(data.get('forum')), 'creator': bool(data.get('creator')),
                'member': data.get('member', True) is not False, 'blocked': bool(data.get('blocked')),
                'first': data.get('first_name', '') or '', 'last': data.get('last_name', '') or '',
                # Desktop contact card: Telegram ID, birthday, badges, note, admins/online.
                'telegram_id': data.get('id') if data.get('is_user') else None,
                'birthday': birthday_text(data.get('birthday')), 'bot': bool(data.get('bot')),
                'premium': bool(data.get('premium')), 'verified': bool(data.get('verified')),
                'scam': bool(data.get('scam')), 'fake': bool(data.get('fake')), 'deleted': bool(data.get('deleted')),
                'note': self.text(data.get('note') or ''), 'online': data.get('online_count') or 0,
                'admins': data.get('admins_count') or 0, 'can_leave': can_leave, 'can_join': can_join,
                'personal_photo': bool(data.get('personal_photo')), 'has_photo': data.get('photo_id') is not None,
                'photo_id': str(data['photo_id']) if data.get('photo_id') else None,
                # Group / channel management: what this account may change (desktop: profile settings).
                'rights': {key: bool(data.get(key)) for key in ('can_edit_info', 'can_change_username', 'can_set_ttl', 'can_ban',
                                                                 'can_manage_reactions', 'can_invite', 'can_view_members')},
                'add_admins': bool(getattr(data.get('entity'), 'creator', False) or getattr(getattr(data.get('entity'), 'admin_rights', None), 'add_admins', False)),
                'creator': bool(getattr(data.get('entity'), 'creator', False)),
                'can_add_members': bool(data.get('can_invite') or (
                    data.get('kind') == 'group' and data.get('member')
                    and not getattr(data.get('default_banned_rights'), 'invite_users', False))),
                'can_link_discussion': data.get('kind') == 'channel' and bool(data.get('can_edit_info')),
                'is_channel': bool(data.get('is_channel')), 'ttl': int(data.get('ttl_period') or 0),
                'slowmode': int(data.get('slowmode_seconds') or 0), 'linked_chat': data.get('linked_chat_id') or None,
                'permissions': default_permissions(data.get('default_banned_rights')),
                'reactions': {'ChatReactionsNone': 'none', 'ChatReactionsSome': 'some'}.get(
                    type(data.get('available_reactions')).__name__, 'all'),
                'share_link': share_link(data, usernames),
                # Header band (desktop contact card): Telegram profile colour and its emoji pattern.
                'banner': banner, **self.profile_public_details(data),
                'contact_kind': 'contact' if data.get('contact') else 'user' if data.get('is_user') else data.get('kind'),
                'is_secret': bool(data.get('is_secret')),
                'secret': data.get('secret'),
                'user_id': data.get('user_id')}

    def profile_public_details(self, data):
        from telethon import types, utils

        def channel_peer(ident):
            return utils.get_peer_id(types.PeerChannel(ident)) if type(ident) is int and ident > 0 else None

        hours = data.get('work_hours')
        schedule = [[span.start_minute, span.end_minute] for span in getattr(hours, 'weekly_open', ()) or ()]
        intro = data.get('business_intro')
        sticker = getattr(intro, 'sticker', None)
        if isinstance(sticker, types.Document):
            self.remember_documents([sticker])
        verification = data.get('bot_verification')
        return {
            'address': self.text(getattr(data.get('location'), 'address', '') or ''),
            'work_hours': {'timezone': hours.timezone_id, 'periods': schedule} if hours and schedule else None,
            'linked_peer': channel_peer(data.get('linked_chat_id')),
            'personal_channel': channel_peer(data.get('personal_channel_id')),
            'personal_channel_message': data.get('personal_channel_message'),
            'business_intro': {'title': self.text(intro.title), 'description': self.text(intro.description),
                               'sticker': str(sticker.id) if isinstance(sticker, types.Document) else None} if intro else None,
            'bot_verification': {'icon': str(verification.icon), 'description': self.text(verification.description)} if verification else None,
            'phone_calls_available': data.get('phone_calls_private') is not True and data.get('phone_calls_available') is not False,
            'video_calls_available': data.get('phone_calls_private') is not True and data.get('video_calls_available') is not False,
        }

    async def api_personal_channel_preview(self, peer, id):
        from telethon import errors, types, utils

        peer, ident = int(peer), int(id)
        if utils.resolve_id(peer)[1] is not types.PeerChannel or ident <= 0:
            raise ValueError('Invalid channel message.')
        account, backend = self.account, self.backend
        try:
            raw = await asyncio.wait_for(backend.checked_message(peer, ident), 12)
        except (errors.RPCError, ValueError, TimeoutError):
            return None
        if self.account != account or self.backend is not backend:
            return None
        message = backend.message(raw)
        summary = ' '.join(preview_text(message).split())[:180]
        return {'text': self.text(summary), 'emojis': [[str(value), alt] for value, alt in (message.custom_emojis or ())][:24]}

    async def api_contact_card_appearance(self, account, changes=None):
        from tg_ascii.contact_appearance import CONTACT_DEFAULTS, validated_contact
        if self.account != account or not self.prefs:
            raise ValueError('The active account changed.')
        current = validated_contact(self.prefs.values)
        if changes is not None:
            if not isinstance(changes, dict) or changes.keys() - CONTACT_DEFAULTS.keys():
                raise ValueError('Invalid contact card settings.')
            updated = {**current, **changes}
            if validated_contact(updated) != updated:
                raise ValueError('Invalid contact card settings.')
            self.prefs.save(updated)
            current = updated
        return {'values': current, 'defaults': CONTACT_DEFAULTS}

    async def profile_banner(self, color):
        """Colours (#rrggbb) and pattern emoji of a profile colour, for this theme."""
        ident = getattr(color, 'color', None)
        pattern = getattr(color, 'background_emoji_id', None)
        if ident is None and not pattern:
            return None
        colors = []
        if ident is not None:
            dark = (self.prefs.values.get('theme') if self.prefs else 'dark') != 'light'
            cache = self.__dict__.setdefault('_banner_palettes', {})
            if (ident, dark) not in cache:
                try:
                    cache[(ident, dark)] = await asyncio.wait_for(self.backend.profile_palette(int(ident), dark), 15)
                except Exception:
                    cache[(ident, dark)] = []
            colors = ['#%06x' % (int(value) & 0xFFFFFF) for value in cache[(ident, dark)]][:3]
        return {'colors': colors, 'pattern': str(pattern) if pattern else None}

    async def api_profile_tab(self, peer, kind, offset=0):
        """Profile tabs (desktop: profile_tabs): pinned stories, gifts, profile
        music and similar channels, a page at a time."""
        from telethon import utils
        backend, peer = self.backend, int(peer)
        if kind == 'similar':
            chats = await asyncio.wait_for(backend.similar_channels(peer), 30)
            return {'items': [{'id': chat.id, 'name': self.text(chat.name), 'member': chat.member,
                               'emoji_status': emoji_status_id(chat.entity)} for chat in chats], 'next': None}
        if kind == 'posts':
            page = await asyncio.wait_for(backend.profile_posts(peer, int(offset or 0)), 30)
            items = [{'id': story.id, 'date': _timestamp(getattr(story, 'date', None)),
                      'caption': self.text(getattr(story, 'caption', '') or ''),
                      'kind': 'video' if type(getattr(getattr(story, 'media', None), 'document', None)).__name__ == 'Document' else 'photo'}
                     for story in page['items'] if hasattr(story, 'id')]
            return {'items': items, 'next': page['next'] if page['more'] else None}
        if kind == 'profile_music':
            page = await asyncio.wait_for(backend.profile_music(peer, int(offset or 0)), 30)
            items = []
            for document in page['items']:
                audio = next((a for a in getattr(document, 'attributes', ()) if type(a).__name__ == 'DocumentAttributeAudio'), None)
                items.append({'id': str(document.id), 'title': self.text(getattr(audio, 'title', '') or ''),
                              'performer': self.text(getattr(audio, 'performer', '') or ''),
                              'duration': int(getattr(audio, 'duration', 0) or 0)})
            return {'items': items, 'next': page['next'] if page['more'] else None}
        if kind == 'gifts':
            result = await asyncio.wait_for(backend.profile_gifts(peer, str(offset or '')), 30)
            people = {utils.get_peer_id(entity): utils.get_display_name(entity)
                      for entity in [*getattr(result, 'users', ()), *getattr(result, 'chats', ())]}
            items = []
            for saved in getattr(result, 'gifts', ()):
                gift = getattr(saved, 'gift', None)
                sticker = getattr(gift, 'sticker', None)
                if sticker is not None:
                    self.remember_documents([sticker])
                sender = getattr(saved, 'from_id', None)
                items.append({'title': self.text(getattr(gift, 'title', '') or ''),
                              'sticker': str(sticker.id) if sticker is not None and hasattr(sticker, 'id') else None,
                              'stars': getattr(gift, 'stars', None), 'from': self.text(people.get(utils.get_peer_id(sender), '')) if sender else '',
                              'date': _timestamp(getattr(saved, 'date', None)), 'message': self.text(getattr(getattr(saved, 'message', None), 'text', '') or '')})
            return {'items': items, 'next': getattr(result, 'next_offset', None) or None}
        raise ValueError('profile tab')

    async def api_join(self, peer):
        result = await asyncio.wait_for(self.backend.join_chat(peer), 30)
        from tg_ascii.pending_actions import Queued
        if isinstance(result, Queued):
            return {'queued': True}
        self.loop.create_task(self.refresh_chats())
        return result


    # -- more conversation tools (desktop parity) -------------------------------------
    async def api_pinned(self, peer, thread_root=None):
        if thread_root is not None and self.is_forum_chat(peer):
            messages = await self.forum_call('forum_search', int(peer), int(thread_root), pinned=True)
            return [self.message_json(m) for m in messages]
        request = (self.backend.pinned_messages(peer) if thread_root is None
                   else self.backend.search_discussion(peer, thread_root, pinned=True))
        messages = await asyncio.wait_for(request, 30)
        return [self.message_json(m) for m in messages]

    async def api_context(self, peer, id, account=None, topic_id=None, thread_root=None, window_peer=None):
        """Messages around an exact ID in its chat, forum topic, or discussion."""
        self.check_active_account(account)
        peer, ident = int(peer), int(id)
        owner, backend = self.account, self.backend
        if topic_id is not None or thread_root is not None:
            root = int(topic_id if topic_id is not None else thread_root)
            context, cached = self.discussion_view(window_peer)
            if context != (owner, peer, root):
                raise ValueError('The active conversation changed.')
            if topic_id is not None:
                request = backend.forum_history(peer, root, around=ident)
            else:
                request = backend.discussion_around(peer, root, ident)
            page = await asyncio.wait_for(request, 30)
            current, messages = self.discussion_view(window_peer)
            if self.locked or self.account != owner or self.backend is not backend or current != context or messages is not cached:
                raise ValueError('The active conversation changed.')
            cached.update((message.id, message) for message in page)
            return {'messages': [self.message_json(m) for m in page], 'next': page.next_offset,
                    'more': page.more, **self.translation_state(peer, page, root)}
        messages = await self.history_page(peer, asyncio.wait_for(backend.message_context(peer, ident), 30))
        if self.locked or self.account != owner or self.backend is not backend:
            raise ValueError('The active account changed.')
        self.histories[peer] = list(messages)
        return [self.message_json(m) for m in messages]

    async def api_delete_many(self, peer, ids, everyone=False):
        ids = [int(item) for item in ids][:100]
        account = self.account
        result = await self._action(self.backend.delete_selected_messages(peer, ids, bool(everyone)))
        self.on_change(account, 'delete', (peer, tuple(ids)))
        return result

    async def api_forward_many(self, peer, ids, destination, account=None, topic_id=None):
        self.check_active_account(account)
        ids = sorted(int(item) for item in ids)[:100]
        if topic_id is not None:
            await self.forum_call('forum_forward', int(destination), int(topic_id), int(peer), ids, account=account)
            return True
        return await self._action(self.backend.forward_selected_messages(peer, ids, 'me' if destination == 'me' else int(destination)))

    async def api_vote(self, peer, id, options, account=None):
        import base64
        self.send_reply(peer, None, None, account)
        chosen = [base64.b64decode(item) for item in options]
        result = await self._action(self.backend.vote_poll(peer, int(id), chosen))
        return result

    async def api_bot_button(self, peer, id, row, column, signature):
        account, backend = self.account, self.backend
        result = await asyncio.wait_for(backend.activate_bot_button(
            peer, int(id), int(row), int(column), bytes.fromhex(signature)), 60)
        self.check_backend_context(account, backend)
        answer = {}
        for key in ('notice', 'alert', 'url', 'copy', 'profile'):
            if result.get(key) not in (None, ''):
                answer[key] = result[key]
        message = result.get('message')
        if message is not None:
            answer['message'] = self.message_json(message)
            self.on_message(self.account, peer, message)
        if result.get('request_phone') or result.get('compose'):
            answer['notice'] = answer.get('notice') or 'This button needs the desktop app.'
        return answer

    async def api_reactions(self, peer, id):
        policy, standard, custom = await asyncio.wait_for(self.backend.reaction_choices(peer, int(id)), 30)
        return {'standard': [value for value in standard if isinstance(value, str)],
                # Custom emoji reactions (Telegram Premium), most recent first.
                'custom': [str(value) for value in custom or () if isinstance(value, int)][:40]}

    async def api_report_message(self, account, peer, id, option='', comment=''):
        from telethon import functions, types
        from tg_ascii.secret_chats import is_secret_peer

        self.check_active_account(account)
        peer, ident = int(peer), int(id)
        if is_secret_peer(peer) or ident <= 0 or len(option) > 2048 or len(comment) > 1024:
            raise ValueError('Invalid report.')
        backend = self.backend
        target = await backend.client.get_input_entity(peer)
        self.check_active_account(account)
        answer = await asyncio.wait_for(backend.client(functions.messages.ReportRequest(
            target, [ident], bytes.fromhex(option), str(comment))), 20)
        self.check_active_account(account)
        if isinstance(answer, types.ReportResultChooseOption):
            return {'title': answer.title, 'options': [{'text': item.text, 'option': item.option.hex()}
                                                        for item in answer.options]}
        if isinstance(answer, types.ReportResultAddComment):
            return {'comment': True, 'optional': bool(answer.optional), 'option': answer.option.hex()}
        return {'reported': isinstance(answer, types.ReportResultReported)}

    async def api_message_read_details(self, account, peer, id, group=False):
        self.check_active_account(account)
        backend = self.backend
        if group:
            from telethon import functions
            entity = await backend.client.get_input_entity(peer)
            readers = await asyncio.wait_for(backend.client(
                functions.messages.GetMessageReadParticipantsRequest(entity, int(id))), 10)
            result = {'readers': sorted(({'id': r.user_id, 'date': r.date.timestamp()} for r in readers
                                         if getattr(r, 'date', None)), key=lambda r: r['date'])}
        else:
            result = {'read': await self.api_read_time(peer, id)}
        self.check_active_account(account)
        return result

    async def api_read_time(self, peer, id):
        from telethon import errors
        from tg_ascii.i18n import tr
        seconds = bool(self.prefs and self.prefs.values.get('show_seconds'))
        try:
            return await asyncio.wait_for(self.backend.read_time(peer, int(id), seconds), 20)
        except errors.RPCError as error:
            name = getattr(error, 'message', '') or type(error).__name__
            if 'NOT_READ' in name:
                raise ValueError(tr('Not read yet.')) from None
            if 'PRIVACY' in name:
                raise ValueError(tr('Hidden by privacy settings.')) from None
            if 'TOO_OLD' in name:
                raise ValueError(tr('Telegram keeps read times for 7 days only.')) from None
            raise

    def _purge_peer_media(self, peer):
        self.forget_media_index()
        try:
            for item in self.media_folder().glob(f'{int(peer)}-*'):
                item.unlink(missing_ok=True)
        except OSError:
            pass

    async def api_clear_chat(self, peer, everyone=False):
        account, backend, store = self.account, self.backend, self.translations()
        result = await self._action(backend.clear_chat(peer, bool(everyone)))
        store.discard(peer)
        if self.account != account or self.backend is not backend:
            return result
        self.histories.pop(peer, None)
        self._purge_peer_media(peer)
        self.loop.create_task(self.refresh_chats())
        return result

    async def api_delete_chat(self, peer, everyone=False):
        account, backend, store = self.account, self.backend, self.translations()
        result = await self._action(backend.delete_chat(peer, bool(everyone)))
        self.forget_notification_chats(account, peer)
        store.discard(peer)
        if self.account != account or self.backend is not backend:
            return result
        self.chats = [chat for chat in self.chats if chat.id != peer]
        self.histories.pop(peer, None)
        self._purge_peer_media(peer)
        self.emit('chats', [self.chat_json(chat) for chat in self.visible_chats()])
        self.loop.create_task(self.refresh_chats())
        return result

    async def api_leave_chat(self, peer):
        account, backend, store = self.account, self.backend, self.translations()
        result = await self._action(backend.leave_chat(peer))
        self.forget_notification_chats(account, peer)
        store.discard(peer)
        if self.account != account or self.backend is not backend:
            return result
        self.chats = [chat for chat in self.chats if chat.id != peer]
        self._purge_peer_media(peer)
        self.emit('chats', [self.chat_json(chat) for chat in self.visible_chats()])
        self.loop.create_task(self.refresh_chats())
        return result

    # -- secret chats (E2E) -----------------------------------------------------------
    async def api_secret_start(self, peer):
        owner, backend = self.account, self.backend
        chat = await asyncio.wait_for(backend.start_secret_chat(int(peer)), 30)
        self.check_backend_context(owner, backend)
        await self.refresh_chats()
        self.check_backend_context(owner, backend)
        return self.chat_json(chat)

    async def api_secret_info(self, peer):
        from tg_ascii.secret_chats import TTL_CHOICES

        owner, backend = self.account, self.backend
        info = await backend.secret_chat_info(int(peer))
        self.check_backend_context(owner, backend)
        if not info:
            from tg_ascii.i18n import tr
            raise ValueError(tr('No hay sesión de chat secreto activa.'))
        return {**info, 'ttl_choices': [seconds for seconds, _ in TTL_CHOICES]}

    async def api_secret_ttl(self, peer, seconds):
        owner, backend = self.account, self.backend
        await asyncio.wait_for(backend.set_secret_ttl(int(peer), int(seconds or 0)), 30)
        self.check_backend_context(owner, backend)
        info = await backend.secret_chat_info(int(peer))
        self.check_backend_context(owner, backend)
        return info

    async def api_secret_rekey(self, peer):
        owner, backend = self.account, self.backend
        await asyncio.wait_for(backend.rekey_secret_chat(int(peer)), 30)
        self.check_backend_context(owner, backend)
        info = await backend.secret_chat_info(int(peer))
        self.check_backend_context(owner, backend)
        return info

    async def api_secret_screenshot(self, peer):
        await asyncio.wait_for(self.backend.notify_secret_screenshot(int(peer)), 30)
        return True

    async def api_secret_discard(self, peer, delete_history=True):
        peer = int(peer)
        account, backend = self.account, self.backend
        await asyncio.wait_for(backend.discard_secret_chat(peer, delete_history=bool(delete_history)), 30)
        self.__dict__.get('_secret_drafts', {}).pop((account, peer), None)
        if self.account != account or self.backend is not backend:
            return True
        if delete_history:
            self.chats = [chat for chat in self.chats if chat.id != peer]
            self.histories.pop(peer, None)
            self._purge_peer_media(peer)
            self.emit('chats', [self.chat_json(chat) for chat in self.visible_chats()])
        await self.refresh_chats()
        return True

    # -- my profile -----------------------------------------------------------------
    async def api_my_profile(self):
        data = await asyncio.wait_for(self.backend.profile('me'), 30)
        return {'first': data.get('first_name', ''), 'last': data.get('last_name', ''),
                'about': data.get('about', '') or '', 'username': (data.get('usernames') or [''])[0] or '',
                'phone': data.get('phone', '') or ''}

    async def api_save_my_profile(self, first, last, about, username):
        account, backend = self.account, self.backend
        current = await self.api_my_profile()
        self.check_backend_context(account, backend)
        if (first, last, about) != (current['first'], current['last'], current['about']):
            await self._action(backend.update_profile(str(first), str(last), str(about)))
            self.check_backend_context(account, backend)
        if username.strip().lstrip('@') != current['username']:
            await self._action(backend.update_username(username.strip().lstrip('@')))
            self.check_backend_context(account, backend)
        self.loop.create_task(self.accounts.refresh_account())
        result = await self.api_my_profile()
        self.check_backend_context(account, backend)
        return result

    # -- app lock (PIN) ------------------------------------------------------------
    def lock_path(self):
        return self.root / 'mobile' / 'lock.json'

    def lock_record(self):
        try:
            data = json.loads(self.lock_path().read_text('utf-8'))
            return data if isinstance(data, dict) and data.get('hash') else None
        except (OSError, ValueError):
            return None

    @staticmethod
    def pin_hash(pin, salt, rounds=200000):
        import hashlib
        return hashlib.pbkdf2_hmac('sha256', str(pin).encode('utf-8'), salt, rounds).hex()

    LOCK_DELAYS = (0, 60, 300, 3600)

    def write_lock(self, record):
        path = self.lock_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_suffix('.tmp')
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(record, stream)
        os.replace(temporary, path)

    def lock_info(self):
        record = self.lock_record() or {}
        return {'enabled': bool(record), 'biometric': bool(record.get('biometric')),
                'delay': int(record.get('delay', 0)) if record.get('delay', 0) in self.LOCK_DELAYS else 0,
                'biometric_available': self.biometric_available()}

    def biometric_available(self):
        try:
            return bool(self.native_biometric_available and self.native_biometric_available())
        except Exception:
            return False

    async def api_lock_info(self):
        return self.lock_info()

    async def api_lock_set(self, pin, current=''):
        """Turn the lock on or change the PIN. Only a salted PBKDF2 hash is kept (0600)."""
        from tg_ascii.i18n import tr
        record = self.lock_record()
        if record is not None and not self.pin_ok(current):
            raise ValueError(tr('Incorrect app password.'))
        pin = str(pin)
        if len(pin) < 4:
            raise ValueError(tr('PIN o contraseña') + ': 4+')
        salt = secrets.token_bytes(16)
        new = {'salt': salt.hex(), 'hash': self.pin_hash(pin, salt), 'rounds': 200000,
               'biometric': bool(record and record.get('biometric')), 'delay': int((record or {}).get('delay', 0))}
        self.write_lock(new)
        self.forget_notification_chats()
        await self.sync_push_registration()
        return self.lock_info()

    async def api_lock_options(self, biometric=None, delay=None):
        """Device authentication and when to lock; the app is unlocked to get here."""
        record = self.lock_record()
        if record is None:
            raise ValueError('lock')
        if biometric is not None:
            if biometric and not self.biometric_available():
                from tg_ascii.i18n import tr
                raise ValueError(tr('Device authentication is unavailable. Use your app password.'))
            record['biometric'] = bool(biometric)
        if delay is not None and int(delay) in self.LOCK_DELAYS:
            record['delay'] = int(delay)
        self.write_lock(record)
        return self.lock_info()

    def pin_ok(self, pin):
        import hmac
        record = self.lock_record()
        if record is None:
            return True
        expected = record['hash']
        got = self.pin_hash(pin, bytes.fromhex(record['salt']), int(record.get('rounds', 200000)))
        return hmac.compare_digest(expected, got)

    async def api_lock_remove(self, pin):
        from tg_ascii.i18n import tr
        if not self.pin_ok(pin):
            raise ValueError(tr('Incorrect app password.'))
        self.lock_path().unlink(missing_ok=True)
        self.locked = False
        await self.sync_push_registration()
        return self.lock_info()

    def lock(self):
        if self.lock_record() is not None and not self.locked:
            self.disconnect_tv()
            self.locked = True
            self.loop.create_task(self.close_media_requests())
            if getattr(self, 'call_pip', None):
                self.call_pip.close()
            if self.voice_recording is not None:
                self.loop.create_task(self.api_voice_cancel(capture=self.voice_recording['capture']))
            self.emit('lock', True)

    async def api_lock_now(self):
        self.lock()
        return self.locked

    def expect_external(self, seconds):
        self.external_until = max(self.external_until, time.monotonic() + seconds)

    async def api_expect_external(self, seconds=120):
        """The page opens a picker/viewer of the system: do not lock for that."""
        self.expect_external(min(300, max(0, float(seconds))))
        return True

    async def api_app_hidden(self, keep=False):
        """The app went to the background (keep: a picker of ours is open)."""
        keep = keep or time.monotonic() < self.external_until
        self.hidden_at = None if keep else time.monotonic()
        self.in_background = not keep
        if self.system == 'iOS':
            self.keep_connected()
        info = self.lock_info()
        if info['enabled'] and not keep and info['delay'] == 0:
            self.lock()
        self.sync_incoming_call_notification()
        return self.locked

    async def resume(self):
        """Back from the background (called by the shell, outside the page):
        make sure the page can reach us again and Telegram reconnects now.
        Returns the local server's port (it changes only if it had to)."""
        port = await self.server.ensure()
        self.port = port
        service = self.accounts.services.get(self.account) if self.accounts else None
        recovery = getattr(service, 'recovery', None)
        if self.stage == 'ready' and recovery is not None:
            account, backend = self.account, self.backend
            async def reconnect():
                try:
                    await asyncio.wait_for(recovery.ensure(force=True), 60)
                    connection = getattr(recovery, 'state', 'online') or 'online'
                except Exception:
                    connection = 'offline'
                if self.account != account or self.backend is not backend or self.stage != 'ready':
                    return
                self.connection = connection
                self.emit('connection', self.connection)
                if self.connection == 'online':
                    self.outbox.kick()
                    await self.refresh_chats()
            self.loop.create_task(reconnect())
        return port

    async def api_app_visible(self):
        hidden_at, self.hidden_at = getattr(self, 'hidden_at', None), None
        self.in_background = False
        if self.native_notify_refresh is not None:
            self.native_notify_refresh()
        if self.system == 'iOS':
            self.keep_connected()
        self.publish_wear_appearance()
        if self.draft_store.pending_records(self.account):
            self.schedule_draft_sync(pull=True)
        if self.open_peer is not None and not self.preview:
            self.clear_notifications(self.open_peer)
        info = self.lock_info()
        if info['enabled'] and hidden_at is not None and time.monotonic() - hidden_at >= info['delay']:
            self.lock()
        self.siri_vocabulary.sync(self, force=True)
        self.sync_incoming_call_notification()
        return {'locked': self.locked, 'biometric': info['biometric'] and info['biometric_available']}

    async def api_unlock(self, pin):
        from tg_ascii.i18n import tr
        if self.pin_verifying:
            raise ValueError(tr('Incorrect app password.'))
        self.pin_verifying = True
        try:
            await asyncio.sleep(0.4)
            if not await asyncio.to_thread(self.pin_ok, pin):
                raise ValueError(tr('Incorrect app password.'))
            self.unlocked()
            return True
        finally:
            self.pin_verifying = False

    def unlocked(self):
        self.locked = False
        self.hidden_at = None
        self.emit('lock', False)
        if self.feature('preload_startup'):
            self.loop.create_task(self.preload())
        if self.stage == 'choose_account':
            self.emit('stage', self.state_snapshot())

    async def api_unlock_biometric(self):
        """Face ID / Touch ID / fingerprint or the device code, through the system."""
        from tg_ascii.i18n import tr
        info = self.lock_info()
        if not info['biometric'] or self.native_biometric is None:
            raise ValueError(tr('Device authentication is unavailable. Use your app password.'))
        future = self.loop.create_future()
        self.expect_external(120)  # The system's screen covers the app meanwhile.
        self.native_biometric(tr('Unlock your messages'),
                              lambda ok: self.loop.call_soon_threadsafe(lambda: future.done() or future.set_result(bool(ok))))
        try:
            ok = await asyncio.wait_for(future, 120)
        finally:
            self.external_until = time.monotonic() + 3
        if not ok:
            raise ValueError(tr('Authentication was canceled or unsuccessful.'))
        self.unlocked()
        return True


    # -- avatars ------------------------------------------------------------------------
    def forget_avatar(self, peer):
        folder = self.root / 'mobile-avatars' / self.account
        for name in (f'{int(peer)}.jpg', f'{int(peer)}.none', f'{int(peer)}-big.jpg', f'{int(peer)}-big.none'):
            (folder / name).unlink(missing_ok=True)
        self.__dict__.setdefault('fresh_avatars', set()).add(int(peer))

    async def avatar_file(self, peer, big=False):
        account = self.account
        result = await self._avatar_file(peer, big)
        cache = getattr(self, 'ios_notice_cache', None)
        if cache and not big and self.accounts and self.account == account:
            try:
                cache.thumbnail(self.accounts.identities.get(account), peer, result)
            except OSError:
                pass
        return result

    async def _avatar_file(self, peer, big=False):
        """Profile photo of a chat/person, small or full size (cached a few days; None if it has none)."""
        folder = self.root / 'mobile-avatars' / self.account
        stem = f'{int(peer)}-big' if big else f'{int(peer)}'
        path, none = folder / f'{stem}.jpg', folder / f'{stem}.none'
        photo_id = self.photo_id(peer)
        if self.keep_loaded() and not big and photo_id is not None:
            # Keep more loaded: Telegram never changes the picture behind a photo
            # id, so the copy stays valid until the person sets another photo.
            if photo_id == 0:
                return None
            try:
                if path.is_file() and (folder / f'{stem}.id').read_text() == str(photo_id):
                    return path
            except OSError:
                pass
        week = 3 * 86400
        for candidate in (path, none):
            try:
                if time.time() - candidate.stat().st_mtime < week:
                    return path if candidate == path else None
            except OSError:
                pass
        backend = self.backend
        if backend is None or self.connection != 'online':
            return path if path.exists() else None
        if self._avatar_slots is None:
            self._avatar_slots = asyncio.Semaphore(4)
        from tg_ascii.secret_chats import is_secret_peer, secret_chat_id
        chat = next((item for item in self.chats if item.id == peer), None)
        target_id = int(peer)
        if is_secret_peer(target_id):
            sess = getattr(backend, 'secret_chats', None) and backend.secret_chats.sessions.get(secret_chat_id(target_id))
            if sess and sess.user_id:
                target_id = int(sess.user_id)
        target = getattr(chat, 'entity', None) or target_id
        fresh = self.__dict__.setdefault('fresh_avatars', set())
        if big or int(peer) in fresh:
            # The list's copy may predate a new (or personal) photo: ask Telegram.
            try:
                target = await asyncio.wait_for(backend.client.get_entity(target_id), 20)
            except Exception:
                pass
            if not big:
                fresh.discard(int(peer))
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        jobs = self.__dict__.setdefault('avatar_jobs', {})
        job = jobs.get(path)
        if job is None:
            job = jobs[path] = self.loop.create_task(self._download_avatar(backend, target, path, none, big))
            job.add_done_callback(lambda done: jobs.pop(path, None) if jobs.get(path) is done else None)
        return await asyncio.shield(job)

    async def _download_avatar(self, backend, target, path, none, big):
        # Written next to its place and renamed: a request arriving meanwhile
        # never reads half a picture.
        temporary = path.with_name(f'.{path.name}.{secrets.token_hex(4)}.part')
        photo_id = None if big else getattr(getattr(target, 'photo', None), 'photo_id', None)
        async with self._avatar_slots:
            try:
                result = await asyncio.wait_for(backend.client.download_profile_photo(
                    target, file=str(temporary), download_big=bool(big)), 60 if big else 30)
            except Exception:
                result = None
        if result:
            try:
                os.replace(result if isinstance(result, str) else temporary, path)
            except OSError:
                result = None
        if not result:
            temporary.unlink(missing_ok=True)
            none.touch()
            return None
        none.unlink(missing_ok=True)
        marker = path.with_suffix('.id')
        if photo_id:
            marker.write_text(str(photo_id))
        else:
            marker.unlink(missing_ok=True)
        return path

    def photo_id(self, peer):
        """The chat's current photo id from the list (0: no photo; None: unknown)."""
        chat = next((item for item in self.chats if item.id == peer), None)
        entity = getattr(chat, 'entity', None)
        if entity is None or not hasattr(entity, 'photo'):
            return None
        photo = entity.photo
        if photo is None or type(photo).__name__ in ('UserProfilePhotoEmpty', 'ChatPhotoEmpty'):
            return 0
        ident = getattr(photo, 'photo_id', None)
        return int(ident) if ident else None

    # -- more message types ----------------------------------------------------------------
    async def api_send_poll(self, peer, question, answers, multiple=False, quiz=False, correct=0,
                            anonymous=True, reply_to=None, thread_root=None, account=None, solution='',
                            open_answers=False, revoting=True, shuffle=False, hidden_results=False,
                            subscribers_only=False, countries=(), close_period=None, files=None, topic_id=None):
        reply_to = self.send_reply(peer, reply_to, thread_root, account)
        if topic_id is not None:
            reply_to = await self.forum_call('forum_reply', int(peer), int(topic_id),
                                           reply_to if reply_to != thread_root else None, account=account)
        answers = [str(item).strip() for item in answers]
        if not quiz:
            answers = [answer for answer in answers if answer]
        selected = (correct if isinstance(correct, list) else [int(correct or 0)]) if quiz else []
        account, backend = self.account, self.backend
        question = str(question).strip()
        options = dict(anonymous=bool(anonymous), multiple=bool(multiple or len(set(selected)) > 1),
                       quiz=bool(quiz), correct=selected, solution=str(solution) if quiz else '',
                       open_answers=bool(open_answers), revoting=bool(revoting), shuffle=bool(shuffle),
                       hidden_results=bool(hidden_results), subscribers_only=bool(subscribers_only),
                       countries=countries, close_period=close_period)
        paths = {}
        if files:
            if not isinstance(files, dict) or files.keys() - {'attached_media', 'solution_media'}:
                raise ValueError('Unknown poll attachment')
            paths = {slot: self.staged(key) for slot, key in files.items()}
            options.update(await asyncio.wait_for(
                backend.prepare_poll_attachments(peer, question, answers, paths, **options), 120))
            self.send_reply(peer, reply_to, thread_root, account)
            if backend is not self.backend:
                raise ValueError('The active account changed.')
        result = await self._action(backend.send_poll(peer, question, answers, reply_to=reply_to, **options))
        if paths:
            await self.api_discard_files(files.values())
        return result

    async def api_poll_answer(self, peer, id, answer, account=None):
        self.send_reply(peer, None, None, account)
        return await self._action(self.backend.append_poll_answer(peer, int(id), answer))

    async def api_poll_close(self, peer, id, account=None):
        self.send_reply(peer, None, None, account)
        return await self._action(self.backend.close_poll(peer, int(id)))

    async def api_send_contact(self, peer, first, last, phone, reply_to=None, thread_root=None, account=None, topic_id=None):
        reply_to = self.send_reply(peer, reply_to, thread_root, account)
        if topic_id is not None:
            reply_to = await self.forum_call('forum_reply', int(peer), int(topic_id),
                                           reply_to if reply_to != thread_root else None, account=account)
        return await self._action(self.backend.send_contact_card(peer, str(first), str(last), _plus(phone), reply_to=reply_to))

    async def api_save_to_saved(self, peer, id):
        account, backend = self.account, self.backend
        me = await asyncio.wait_for(backend.client.get_me(), 20)
        self.check_backend_context(account, backend)
        return await self._action(backend.forward_message(peer, int(id), me.id))

    # -- contact menu ------------------------------------------------------------------------
    async def api_common_chats(self, peer):
        chats = await asyncio.wait_for(self.backend.profile_common_chats(peer), 30)
        return [{'id': chat.id, 'name': self.text(chat.name), 'kind': chat.kind} for chat in chats]

    async def api_shared_media(self, peer, kind='photos', offset=0, account=None):
        kinds = {'photos': 'media', 'photos_only': 'photos', 'videos': 'videos',
                 'files': 'files', 'links': 'links', 'voice': 'voice', 'audio': 'audio', 'gifs': 'gifs', 'polls': 'polls'}
        if kind not in kinds:
            raise ValueError('kind')
        self.check_active_account(account)
        owner, backend = self.account, self.backend
        found = await asyncio.wait_for(backend.search_messages(int(peer), '', kinds[kind], int(offset)), 30)
        if self.account != owner or self.backend is not backend or self.locked:
            raise PermissionError('The active account changed.')
        messages = found[0] if isinstance(found, tuple) else found
        return [item for item in (self.message_json(m) for m in messages or []) if item]

    async def api_block(self, peer, blocked):
        return await self._action(self.backend.profile_block(peer, bool(blocked)))

    async def api_add_contact(self, first, last, phone, peer=None):
        """New contact by phone, or save the person being viewed (peer) as a contact."""
        if peer is not None:
            await asyncio.wait_for(self.backend.save_contact(peer, str(first), str(last), str(phone or '')), 30)
        else:
            user = await asyncio.wait_for(self.backend.add_contact(str(first), str(last), _plus(phone)), 30)
            return {'id': user.id}
        return True

    async def api_delete_contact(self, peer):
        return await self._action(self.backend.profile_delete_contact(peer))


    # -- appearance only on this device (backgrounds, icon, typeface) -------------------
    APPEARANCE = {'background': '', 'dim': 55, 'chats': {}, 'icon': 'default', 'font': '',
                  'layout': 'auto', 'side_width': 0, 'windows': [], 'watch_own': False,
                  'swipe_right': 'read', 'swipe_left': 'menu',
                  'keep_connected': False, 'background_sync': False, 'chat_sync': {}, 'effects': {},
                  'brand_logo': {}, 'brand_photo': '', 'official_logo': '', 'presentation': {}}
    LAYOUTS = ('auto', 'single', 'double')
    ICONS = tuple(NATIVE_LOGOS)
    FONTS = ('', 'courier', 'sans', 'serif', 'system', 'rounded', 'humanist', 'classic', 'book', 'mono', 'sf',
             # 3.2: Apple system faces and Android system families (web/app.js FONTS).
             'sf_rounded', 'sf_mono', 'new_york', 'sf_compact',
             'condensed', 'light', 'medium', 'noto_serif', 'typewriter', 'casual', 'handwriting', 'smallcaps')
    SWIPE_ACTIONS = ('none', 'menu', 'read', 'archive', 'pin', 'mute', 'profile', 'folders')

    def appearance_path(self):
        return self.root / 'mobile' / 'appearance.json'

    def stored_appearance(self):
        try:
            stored = json.loads(self.appearance_path().read_text('utf-8'))
        except (OSError, ValueError):
            return {}
        return stored if isinstance(stored, dict) else {}

    def appearance(self):
        values = dict(self.APPEARANCE)
        stored = self.stored_appearance()
        for key, default in self.APPEARANCE.items():
            if isinstance(stored.get(key), type(default)):
                values[key] = stored[key]
        # Older installs kept peer choices in the primary account's appearance file.
        if self.account != 'account':
            values['chats'] = values['chat_sync'] = {}
        values['chat_wallpapers'] = self.chat_wallpapers(self.account)
        folder = self.root / 'mobile-backgrounds'
        values['chats'] = {str(peer): name for peer, name in values['chats'].items()
                           if name == 'interface' or (folder / str(name)).is_file()}
        if values['background'] and not (folder / values['background']).is_file():
            values['background'] = ''
        values['dim'] = max(0, min(100, int(values['dim'])))
        values['icon'] = values['icon'] if values['icon'] in self.ICONS else 'default'
        values['brand_logo'] = self.brand_logo(values['brand_logo'], values['icon'])
        if values['brand_photo'] and self.logo_photo_file(values['brand_photo']) is None:
            values['brand_photo'] = ''
        if values['official_logo'] and self.official_logo_file(values['official_logo']) is None:
            values['official_logo'] = ''
        values['font'] = values['font'] if values['font'] in self.FONTS else ''
        values['layout'] = values['layout'] if values['layout'] in self.LAYOUTS else 'auto'
        values['side_width'] = max(0, min(4000, int(values['side_width'])))
        values['windows'] = [item for item in values['windows']
                             if isinstance(item, dict) and item.get('account') == self.account][:8]
        values['chat_sync'] = {str(peer): mode for peer, mode in values['chat_sync'].items() if mode in ('devices', 'both')}
        values['effects'] = effects_json(values['effects'])
        from .presentation import validated as validated_presentation
        values['presentation'] = validated_presentation(values['presentation'])
        return values

    def save_appearance(self, values):
        path = self.appearance_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_suffix('.tmp')
        stored_windows = self.stored_appearance().get('windows')
        if not isinstance(stored_windows, list):
            stored_windows = []
        other_windows = [item for item in stored_windows if isinstance(item, dict)
                         and item.get('account') and item['account'] != self.account]
        saved = {**values, 'windows': other_windows + values['windows']}
        saved.pop('chat_wallpapers', None)
        if self.account != 'account':
            legacy = self.stored_appearance()
            for key in ('chats', 'chat_sync'):
                saved[key] = legacy.get(key, {})
        temporary.write_text(json.dumps(saved), 'utf-8')
        temporary.replace(path)
        self.prune_backgrounds(saved)
        self.emit('appearance', values)
        self.publish_wear_appearance()
        return values

    def prune_backgrounds(self, values):
        folder = self.root / 'mobile-backgrounds'
        used = {values['background'], *values['chats'].values()}
        for item in folder.glob('*.jpg') if folder.is_dir() else ():
            if item.name not in used:
                item.unlink(missing_ok=True)

    @staticmethod
    def brand_logo(values, legacy='default'):
        from tg_ascii.logos import LOGO_PALETTES, VARIANTS
        variant, theme, color = NATIVE_LOGOS.get(legacy, NATIVE_LOGOS['default'])
        defaults = {'variant': variant, 'theme': theme, 'color': color}
        for key, allowed in (('variant', VARIANTS), ('color', LOGO_PALETTES), ('theme', ('dark', 'light'))):
            if isinstance(values.get(key), str) and values[key] in allowed:
                defaults[key] = values[key]
        return defaults

    async def api_logo_catalogue(self):
        from tg_ascii.logos import LOGO_PALETTES, VARIANTS
        return {'variants': list(VARIANTS.items()), 'colors': list(LOGO_PALETTES)}

    async def brand_logo_file(self, variant, theme, color):
        from tg_ascii.logos import LOGO_PALETTES, VARIANTS, brand_asset_path
        if variant not in VARIANTS or theme not in ('dark', 'light') or color not in LOGO_PALETTES:
            return None
        return await asyncio.to_thread(brand_asset_path, self.root / 'mobile', variant, theme, color, size=1024)

    def official_logo_file(self, key):
        source, _, name = str(key).partition('/')
        prefix = 'official-telegram-' if source == 'Telegram' else 'mobile-'
        if source not in ('Telegram', 'Android', 'iOS') or Path(name).name != name:
            return None
        if not name.startswith(prefix) or not name.endswith('.png'):
            return None
        folder = (self.root / 'mobile' / 'official-icons' / source).resolve()
        path = (folder / name).resolve()
        return path if path.parent == folder and path.is_file() else None

    async def api_official_logos(self, source):
        folder = self.root / 'mobile' / 'official-icons'
        if source == 'Telegram':
            from tg_ascii.official_icons import load_collection
            choices = await asyncio.to_thread(load_collection, folder / source)
        elif source in ('Android', 'iOS'):
            from tg_ascii.mobile_icons import load_mobile_icons
            choices = await asyncio.to_thread(load_mobile_icons, source, folder)
        else:
            raise ValueError('Invalid logo source.')
        return [{'label': label, 'key': source + '/' + path.name} for label, path in choices]

    def logo_photo_file(self, name):
        import re
        if not re.fullmatch(r'[0-9a-f]{32}\.jpg', str(name)):
            return None
        path = self.root / 'mobile-logos' / name
        return path if path.is_file() else None

    async def api_set_logo_photo(self, key, account=None):
        self.check_active_account(account)
        owner, backend = self.account, self.backend
        source, name, saved = self.staged(key), None, False
        folder = self.root / 'mobile-logos'
        try:
            name = await asyncio.to_thread(self.background_image, source, folder)
            self.check_backend_context(owner, backend)
            current = self.appearance()
            current.update(brand_photo=name, official_logo='')
            self.save_appearance(current)
            saved = True
            return current
        finally:
            source.unlink(missing_ok=True)
            if name is not None and not saved:
                (folder / name).unlink(missing_ok=True)

    async def api_appearance(self, values=None, account=None):
        current = self.appearance()
        if values:
            if isinstance(values.get('brand_logo'), dict):
                current.update(brand_logo=self.brand_logo(values['brand_logo']), brand_photo='', official_logo='')
                if values.get('apply_native_logo'):
                    logo = current['brand_logo']
                    values = {**values, 'icon': NAMES[logo['variant'], logo['theme'], logo['color']]}
            if 'official_logo' in values:
                logo = values['official_logo']
                if not isinstance(logo, str) or (logo and self.official_logo_file(logo) is None):
                    raise ValueError('Invalid official logo.')
                current.update(official_logo=logo, brand_photo='')
            if values.get('brand_photo') == '':
                current['brand_photo'] = ''
            if 'dim' in values:
                current['dim'] = max(0, min(100, int(values['dim'])))
            for direction in ('swipe_left', 'swipe_right'):
                if values.get(direction) in self.SWIPE_ACTIONS:
                    current[direction] = values[direction]
            if values.get('font') in self.FONTS:
                current['font'] = values['font']
            if 'watch_own' in values:
                current['watch_own'] = bool(values['watch_own'])
            if 'keep_connected' in values:
                current['keep_connected'] = bool(values['keep_connected'])
                if current['keep_connected'] and self.native_battery_exemption is not None:
                    self.native_battery_exemption()
            if values.get('layout') in self.LAYOUTS:
                current['layout'] = values['layout']
            if isinstance(values.get('effects'), dict):
                current['effects'] = effects_json({**current['effects'], **values['effects']})
            if isinstance(values.get('presentation'), dict):
                from .presentation import validated as validated_presentation
                current['presentation'] = validated_presentation(values['presentation'])
            if 'background_sync' in values:
                current['background_sync'] = bool(values['background_sync'])
            if 'side_width' in values:
                current['side_width'] = max(0, min(4000, int(values['side_width'] or 0)))
            if isinstance(values.get('windows'), list):
                if account != self.account:
                    raise ValueError('The active account changed.')
                # Only the active account can save its windows.
                keep = []
                for item in values['windows'][:8]:
                    if isinstance(item, dict) and isinstance(item.get('peer'), int):
                        keep.append({'account': account, 'peer': item['peer'], 'name': str(item.get('name', ''))[:120],
                                     'docked': bool(item.get('docked')),
                                     **{key: int(item[key]) for key in ('x', 'y', 'w', 'h') if isinstance(item.get(key), (int, float))}})
                current['windows'] = keep
            if values.get('icon') in self.ICONS and values['icon'] != current['icon']:
                if self.native_icon is not None:
                    original = self.appearance()
                    future = self.loop.create_future()
                    self.native_icon(values['icon'], lambda ok: self.loop.call_soon_threadsafe(
                        lambda: future.done() or future.set_result(ok)))
                    # iOS finishes only when the user dismisses the system's
                    # confirmation, which can stay open for any length of time.
                    ok = await future if self.system == 'iOS' else await asyncio.wait_for(future, 30)
                    if not ok:
                        raise RuntimeError('icon')
                    changed = {k: v for k, v in current.items() if v != original[k]}
                    current = {**self.appearance(), **changed}
                current['icon'] = values['icon']
            if 'windows' in values and account != self.account:
                raise ValueError('The active account changed.')
            self.save_appearance(current)
            if 'keep_connected' in values:
                self.keep_connected()
        return current

    def background_image(self, path, folder=None):
        """Our own copy of a chosen picture: oriented, at most 2560 px, JPEG."""
        import uuid
        from PIL import Image, ImageOps
        folder = folder or self.root / 'mobile-backgrounds'
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        with Image.open(path) as image:
            if image.width * image.height > 40_000_000:
                raise ValueError('image too large')
            picture = ImageOps.exif_transpose(image).convert('RGB')
            picture.thumbnail((2560, 2560))
            target = folder / (uuid.uuid4().hex + '.jpg')
            picture.save(target, quality=90)
        return target.name

    async def api_set_background(self, key, target='interface', sync='', account=None):
        """Apply the picked background only to the account that began the edit."""
        self.check_active_account(account)
        owner, backend = self.account, self.backend
        path, name, applied = self.staged(key), None, False
        try:
            name = await asyncio.to_thread(self.background_image, path)
            self.check_backend_context(owner, backend)
            saved = self.root / 'mobile-backgrounds' / name
            current = self.appearance()
            if target == 'interface':
                if sync:
                    await asyncio.wait_for(self.upload_account_wallpaper(saved), 120)
                    self.check_backend_context(owner, backend)
                current['background'] = name
                current['background_sync'] = bool(sync)
            else:
                peer = str(int(target))
                if sync in ('devices', 'both'):
                    await asyncio.wait_for(backend.apply_wallpaper(int(target), saved, for_both=sync == 'both'), 120)
                    self.check_backend_context(owner, backend)
                    current['chat_sync'][peer] = sync
                else:
                    current['chat_sync'].pop(peer, None)
                current['chats'][peer] = name
            result = self.save_appearance(current)
            applied = True
            return result
        finally:
            path.unlink(missing_ok=True)
            if name is not None and not applied:
                (self.root / 'mobile-backgrounds' / name).unlink(missing_ok=True)

    async def upload_account_wallpaper(self, path):
        """Keep the general background in the account's Telegram wallpapers, where
        your other TG-ASCII devices pick it up (newest uploaded one wins)."""
        from telethon import functions, types
        client = self.backend.client
        uploaded = await client.upload_file(str(path))
        settings = types.WallPaperSettings()
        wallpaper = await client(functions.account.UploadWallPaperRequest(uploaded, 'image/jpeg', settings))
        await client(functions.account.SaveWallPaperRequest(types.InputWallPaper(wallpaper.id, wallpaper.access_hash), False, settings))

    async def wallpaper_image(self, wallpaper, backend=None):
        """Local copy (mobile-backgrounds) of a Telegram picture wallpaper; None for
        colours, gradients and patterns."""
        import hashlib
        document = getattr(wallpaper, 'document', None)
        if document is None or getattr(wallpaper, 'pattern', False):
            return None
        name = hashlib.md5(f'telegram-{wallpaper.id}'.encode()).hexdigest() + '.jpg'
        target = self.root / 'mobile-backgrounds' / name
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            backend = backend if backend is not None else self.backend
            data = await backend.client.download_media(document, file=bytes)
            temporary = target.with_suffix('.tmp')
            temporary.write_bytes(data)
            temporary.replace(target)
        return name

    async def _sync_background(self):
        try:
            await self.api_sync_background()
        except Exception as exc:
            print('background sync:', exc)

    async def api_sync_background(self):
        """Synchronised general background: the newest picture uploaded to the account."""
        from telethon import functions
        current = self.appearance()
        if not current.get('background_sync'):
            return current
        account, backend = self.account, self.backend
        result = await asyncio.wait_for(backend.client(functions.account.GetWallPapersRequest(hash=0)), 30)
        self.check_backend_context(account, backend)
        mine = [item for item in getattr(result, 'wallpapers', None) or ()
                if getattr(item, 'creator', False) and getattr(item, 'document', None) is not None and not getattr(item, 'pattern', False)]
        if not mine:
            return current
        name = await self.wallpaper_image(max(mine, key=lambda item: item.id), backend)
        self.check_backend_context(account, backend)
        if name and name != current['background']:
            current['background'] = name
            current = self.save_appearance(current)
            self.emit('appearance', current)
        return current

    async def api_clear_background(self):
        current = self.appearance()
        current['background'] = ''
        return self.save_appearance(current)

    def background_file(self, name):
        import re
        if not re.fullmatch(r'[0-9a-f]{32}\.jpg', str(name)):
            return None
        path = self.root / 'mobile-backgrounds' / name
        return path if path.is_file() else None

    # -- files and links outside the app ----------------------------------------------
    async def api_open_file(self, peer, id, action='file', account=None):
        """Full file, downloaded once, then: 'file' open it with the system viewer,
        'save' keep a copy on the device (Downloads), 'share' the share sheet."""
        if action not in ('file', 'save', 'share'):
            raise ValueError(action)
        self.check_active_account(account)
        owner, backend = self.account, self.backend
        from tg_ascii.secret_chats import is_secret_peer
        if is_secret_peer(int(peer)):
            return await self.open_secret_attachment(int(peer), int(id), action)
        message = next((m for m in self.histories.get(int(peer)) or [] if m.id == int(id)), None)
        chat = next((c for c in self.chats if c.id == int(peer)), None)
        if (getattr(message, 'protected', False) or has_expiry(message)
                or getattr(getattr(chat, 'entity', None), 'noforwards', False)):
            raise PermissionError('Protected content')
        if action in ('save', 'share'):
            rights = await asyncio.wait_for(backend.selected_message_policy(int(peer), [int(id)]), 30)
            if not rights.get('copy'):
                raise PermissionError('Protected content')
        if self.locked or self.account != owner or self.backend is not backend:
            raise PermissionError('The active account changed.')
        path = await asyncio.wait_for(self.media_file(int(peer), int(id), False), 600)
        if path is None:
            raise LookupError('no file')
        if self.locked or self.account != owner or self.backend is not backend:
            raise PermissionError('The active account changed.')
        name = Path(getattr(message, 'filename', '') or '').name
        if not name or name in ('.', '..') or chr(0) in name or name == path.name:
            return await self.open_file_with_system(path, action)
        import shutil
        folder = self.root / 'mobile-open'
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory = Path(tempfile.mkdtemp(dir=folder))
        keep = False

        def release():
            shutil.rmtree(directory, ignore_errors=True)

        try:
            named = directory / name
            await asyncio.to_thread(shutil.copyfile, path, named)
            if self.locked or self.account != owner or self.backend is not backend:
                raise PermissionError('The active account changed.')
            result = await self.open_file_with_system(named, action, release=release if self.system == 'iOS' else None)
            keep = self.system == 'iOS' and result['opened']
            return result
        finally:
            if not keep:
                release()

    async def open_secret_attachment(self, peer, ident, action):
        import shutil
        import tempfile

        if self.native_open is None:
            return {'opened': False, 'name': ''}
        root = self.root / 'secret-exports'
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        folder = Path(tempfile.mkdtemp(dir=root))
        keep = False

        def release():
            shutil.rmtree(folder, ignore_errors=True)

        try:
            path = await asyncio.wait_for(self.secret_preview_file(
                peer, ident, False, folder, original_name=True), 600)
            if path is None:
                raise LookupError('no file')
            result = await self.open_file_with_system(path, action,
                                                       release=release if self.system == 'iOS' else None)
            # iOS releases this URL when the preview or share activity ends.
            keep = result['opened'] and self.system == 'iOS'
            return result
        finally:
            if not keep:
                release()

    async def open_file_with_system(self, path, action, *, release=None):
        if self.native_open is None:
            return {'opened': False, 'name': path.name}
        future = self.loop.create_future()
        self.expect_external(120)  # Another app comes to the front.
        def done(ok):
            self.loop.call_soon_threadsafe(lambda: future.done() or future.set_result(ok))

        if release is None:
            self.native_open(action, str(path), done)
        else:
            self.native_open(action, str(path), done,
                             release=lambda: self.loop.call_soon_threadsafe(release))
        return {'opened': bool(await future), 'name': path.name}

    async def api_open_url(self, url):
        from tg_ascii.links import browser_url

        url = str(url or '').strip()
        if not url.lower().startswith(('tg://', 'mailto:')):
            url = browser_url(url)
        elif any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url):
            raise ValueError('Invalid URL')
        if self.native_open is None:
            return {'opened': False}
        future = self.loop.create_future()
        self.expect_external(120)  # Another app comes to the front.
        self.native_open('url', url, lambda ok: self.loop.call_soon_threadsafe(
            lambda: future.done() or future.set_result(ok)))
        return {'opened': bool(await asyncio.wait_for(future, 20))}

    async def api_outbox_retry(self, peer, key):
        for item in self.outbox.pending(self.account, peer):
            if item.key == key:
                self.outbox.retry(item)
        return True

    async def api_outbox_edit(self, peer, key, text):
        """Change the text of a message that is still waiting to be sent. It keeps
        its Telegram random id: if an earlier attempt did arrive, Telegram drops
        the edited copy instead of sending it twice (edit the delivered one then)."""
        from tg_ascii.i18n import tr
        text = str(text or '').strip()[:4096]
        if not text:
            raise ValueError(tr('Write a message…'))
        for item in self.outbox.pending(self.account, peer):
            if item.key == key:
                if item.state == 'sending' or item.paths:
                    raise RuntimeError(tr('Enviando...'))
                if text != item.text:
                    item.text, item.format_spans, item.custom_spans = text, [], []
                    if item.state == 'failed':
                        item.state, item.error, item.retry_at, item.attempts = 'waiting', '', 0.0, 0
                    self.outbox.save()
                    self.outbox.changed(item.account, item.peer)
                    self.outbox.kick()
                return True
        return False

    async def api_outbox_remove(self, peer, key):
        for item in self.outbox.pending(self.account, peer):
            if item.key == key and item.state != 'sending':
                self.outbox.remove(item)
        return True

    async def _action(self, coroutine):
        from tg_ascii.pending_actions import Queued
        result = await asyncio.wait_for(coroutine, ACTION_TIMEOUT)
        if isinstance(result, Queued):
            return {'queued': True}
        message = self.message_json(result)
        return {'queued': False, 'message': message}

    async def api_edit(self, peer, id, text):
        return await self._action(self.backend.edit_existing(peer, id, text))

    async def api_delete(self, peer, id, everyone=False):
        account = self.account
        result = await self._action(self.backend.delete_message(peer, id, bool(everyone)))
        self.on_change(account, 'delete', (peer, (id,)))
        return result

    async def api_forward(self, peer, id, destination, account=None, topic_id=None):
        self.check_active_account(account)
        if topic_id is not None:
            await self.forum_call('forum_forward', int(destination), int(topic_id), int(peer), [int(id)], account=account)
            return True
        return await self._action(self.backend.forward_message(peer, id, destination))

    async def api_react(self, peer, id, value):
        if isinstance(value, str) and value.isdigit():
            value = int(value)  # a custom emoji reaction (document id)
        result = await self._action(self.backend.react(peer, id, value))
        self.loop.create_task(self.refresh_message(peer, id))
        return result

    async def api_pin_message(self, peer, id, unpin=False):
        return await self._action(self.backend.pin_message(peer, id, bool(unpin)))

    async def _chat_flag(self, peer, attribute, value, coroutine):
        chat = next((item for item in self.chats if item.id == peer), None)
        if chat is not None:
            setattr(chat, attribute, value)
            self.emit('chats', [self.chat_json(item) for item in self.visible_chats()])
            self.schedule_save()
        return await self._action(coroutine)

    async def api_pin_chat(self, peer, pinned):
        account, backend = self.account, self.backend
        if self.prefs.values.get('local_pins'):
            order = self.local_order()
            if order is None:
                order = [chat.id for chat in self.chats if chat.pinned]
            order = [item for item in order if item != peer]
            if pinned:
                order.insert(0, peer)
            self.local_pins.save_order(account, order)
            self.emit('chats', [self.chat_json(chat) for chat in self.visible_chats()])
            return {'queued': False}
        result = await self._action(backend.pin(peer, bool(pinned)))
        if account == self.account and not result['queued']:
            await self.refresh_chats()
        return result

    async def api_move_pin(self, peer, direction, account):
        self.check_active_account(account)
        chat = next(c for c in self.chats if c.id == peer)
        if direction not in (-1, 1) or not self.is_pinned(chat):
            raise ValueError('Invalid move')
        order = self.local_order()
        if order is None:
            await self.backend.move_pinned(peer, direction, chat.archived)
            if account == self.account:
                await self.refresh_chats()
        else:
            visible = [c.id for c in self.visible_chats(chat.archived) if self.is_pinned(c)]
            target = visible.index(peer) + direction
            if 0 <= target < len(visible):
                order = order.copy()
                a, b = order.index(peer), order.index(visible[target])
                order[a], order[b] = order[b], order[a]
                self.local_pins.save_order(account, order)
                self.emit('chats', [self.chat_json(c) for c in self.visible_chats()])
        return True

    async def api_mute_chat(self, peer, muted, duration=None):
        """duration: seconds muted (None: until turned back on), as Desktop's Mute menu."""
        duration = int(duration) if duration else None
        return await self._chat_flag(peer, 'muted', bool(muted), self.backend.mute_chat(peer, bool(muted), duration))

    async def api_mark_read_chat(self, peer):
        """Read everything in a chat without opening it (Desktop: Mark as read)."""
        account, backend = self.account, self.backend
        latest = await asyncio.wait_for(backend.client.get_messages(peer, limit=1), 20)
        self.check_backend_context(account, backend)
        chat = next((item for item in self.chats if item.id == peer), None)
        marked = bool(getattr(chat, 'unread_mark', False))
        if chat is not None:
            chat.unread, chat.unread_mark = 0, False
            self.emit('chats', [self.chat_json(item) for item in self.visible_chats()])
            self.schedule_save()
        if latest:
            await asyncio.wait_for(backend.mark_read(peer, latest[0].id), 20)
            self.check_backend_context(account, backend)
        if marked:
            await backend.set_chat_unread(peer, False)
        return {'read': True}

    async def api_chats_batch(self, peers, action, value=True, account=None):
        """Selected chats in the list: archive, mute, read, pin, folder, delete."""
        self.check_active_account(account)
        owner = self.account
        done = 0
        for peer in [int(item) for item in peers][:200]:
            self.check_active_account(owner)
            try:
                if action == 'archive':
                    await self.api_archive_chat(peer, bool(value))
                elif action == 'mute':
                    await self.api_mute_chat(peer, bool(value))
                elif action == 'read':
                    await (self.api_mark_read_chat(peer) if value else self.api_mark_unread(peer, True))
                elif action == 'pin':
                    await self.api_pin_chat(peer, bool(value))
                elif action == 'folder':
                    await self.api_folder_membership(int(value), peer, True, owner)
                elif action == 'delete':
                    chat = next((item for item in self.chats if item.id == peer), None)
                    if chat is not None and chat.kind in ('group', 'channel'):
                        await self.api_leave_chat(peer)
                    else:
                        await self.api_delete_chat(peer)
                else:
                    raise ValueError(action)
                done += 1
            except ValueError:
                raise
            except Exception as exc:
                print('batch:', action, peer, exc)
        self.check_active_account(owner)
        return {'done': done}

    async def api_folder_pin(self, folder, peer, account, pinned=None, direction=None):
        from telethon import utils
        self.check_active_account(account)
        backend = self.backend
        records = await backend.folders()
        record = next(item for item in records if item.id == folder)
        if direction is None:
            await backend.pin_in_folder(record, peer, bool(pinned))
        else:
            order = [utils.get_peer_id(p) for p in record.pinned_peers]
            source = order.index(peer)
            target = source + direction
            if direction in (-1, 1) and 0 <= target < len(order):
                order[source], order[target] = order[target], order[source]
                await backend.reorder_folder_pins(record, order)
        self.check_active_account(account)
        return await self.api_folders(True)

    async def api_folder_membership(self, folder, peer, include=True, account=None):
        self.check_active_account(account)
        account, backend = self.account, self.backend
        records = {item.id: item for item in self.folder_records}
        if int(folder) not in records:
            await self.api_folders(True)
            records = {item.id: item for item in self.folder_records}
        record = records.get(int(folder))
        if record is None:
            raise ValueError('folder')
        self.check_active_account(account)
        await asyncio.wait_for(backend.folder_membership(record, int(peer), bool(include)), 30)
        return await self.api_folders(True, account)

    async def api_scheduled(self, peer, thread_root=None):
        from tg_ascii.backend import Message
        items = (await self.forum_call('forum_scheduled', int(peer), int(thread_root))
                 if thread_root is not None and self.is_forum_chat(peer)
                 else await asyncio.wait_for(self.backend.scheduled_history(peer), 30))
        result = []
        for raw in items:
            try:
                message = self.backend.message(raw) if hasattr(self.backend, 'message') else raw
            except Exception:
                continue
            data = self.message_json(message) if isinstance(message, Message) else None
            if data is not None and (thread_root is None or (data.get('topic_id') or data['thread_root']) == thread_root):
                data['scheduled'] = _timestamp(getattr(raw, 'date', None))
                result.append(data)
        return result

    async def api_scheduled_action(self, peer, id, send_now=False):
        await asyncio.wait_for(self.backend.change_scheduled(peer, int(id), bool(send_now)), 30)
        return await self.api_scheduled(peer)

    # -- contact card (desktop: contact_tools) -------------------------------------
    async def api_contact_note(self, peer, text):
        from telethon import functions, types, utils
        client = self.backend.client
        user = utils.get_input_user(await client.get_input_entity(peer))
        note = types.TextWithEntities(text=str(text or '')[:4096], entities=[])
        await asyncio.wait_for(client(functions.contacts.UpdateContactNoteRequest(user, note)), 30)
        return True

    async def api_suggest_birthday(self, peer, day, month, year=None):
        from datetime import date
        from telethon import functions, types, utils
        day, month, year = int(day), int(month), int(year) if year else None
        date(year or 2000, month, day)  # a real calendar date (29 Feb with no year is fine)
        client = self.backend.client
        user = utils.get_input_user(await client.get_input_entity(peer))
        await asyncio.wait_for(client(functions.users.SuggestBirthdayRequest(user, types.Birthday(day=day, month=month, year=year))), 30)
        return True

    async def api_contact_photo(self, peer, key=None, suggest=False):
        """Suggest a profile photo to a person, or set one only this account sees
        (key=None and suggest=False removes that personal photo). Desktop: contact_tools."""
        from telethon import functions, utils
        client = self.backend.client
        user = utils.get_input_user(await client.get_input_entity(peer))
        path = self.staged(key) if key else None
        try:
            uploaded = await client.upload_file(str(path)) if path else None
            # save: set (with a file) or remove (without) the personal photo; suggest: propose one.
            await asyncio.wait_for(client(functions.photos.UploadContactProfilePhotoRequest(
                user, suggest=bool(suggest) or None, save=None if suggest else True, file=uploaded)), 60)
        except Exception as exc:
            print('contact photo:', type(exc).__name__, exc, flush=True)
            raise
        finally:
            if path is not None:
                path.unlink(missing_ok=True)
        if not suggest:
            self.forget_avatar(int(peer))
        return True

    # -- translation and Telegram AI (desktop: message_tools, desktop_tools) --------
    def text_entities_json(self, value):
        """Translated / AI text with its custom emoji, for the page."""
        return self.display_translation(translated_content(value))

    def display_translation(self, content):
        raw = content['text']
        shown = self.text(raw)
        return {'text': shown, 'emojis': content.get('emojis') or [],
                'formats': (content.get('formats') or []) if shown == raw else []}

    def translations(self):
        """This account's automatic chat translations (chat_translations.py)."""
        from .chat_translations import ChatTranslations
        store = self.__dict__.get('_translations')
        if store is None or store[0] != self.account:
            store = (self.account, ChatTranslations(self.root / 'mobile', self.account))
            self._translations = store
        return store[1]

    def translation_key(self, peer, thread_root):
        if thread_root is None:
            return int(peer)
        if type(thread_root) is not int or thread_root <= 0:
            raise ValueError('Invalid discussion thread.')
        return f'{int(peer)}/{thread_root}'

    def translation_state(self, peer, messages, thread_root=None):
        key = self.translation_key(peer, thread_root)
        store = self.translations()
        language = store.language(key)
        translated = {}
        if language:
            cached = store.lookup(key, language, ((m.id, m.raw_text or m.text) for m in messages))
            for ident, value in cached.items():
                translated[str(ident)] = self.display_translation(value)
        return {'translate': language, 'translated': translated}

    async def api_set_chat_translation(self, peer, language=None, thread_root=None, window_peer=None):
        """Translate this conversation automatically (Premium) into language, or stop."""
        from tg_ascii.i18n import tr
        from tg_ascii.secret_chats import is_secret_peer

        peer = int(peer)
        key = self.translation_key(peer, thread_root)
        account, backend = self.account, self.backend
        if is_secret_peer(peer):
            raise ValueError('Secret chat messages cannot be translated by Telegram.')
        if language and (backend is None or not await asyncio.wait_for(backend.premium_enabled(), 20)):
            raise ValueError(tr('Automatic chat translation requires Telegram Premium.'))
        if self.account != account or self.backend is not backend:
            raise ValueError('The active account changed.')
        if thread_root is not None and self.discussion_view(window_peer)[0] != (account, peer, thread_root):
            raise ValueError('The active discussion changed.')
        store = self.translations()
        store.set_language(key, str(language) if language else None)
        messages = self.histories.get(peer) or () if thread_root is None else self.discussion_view(window_peer)[1].values()
        result = self.translation_state(peer, messages, thread_root)
        self.emit('chat_translation', {'account': account, 'peer': peer, 'thread_root': thread_root, **result})
        return result

    async def api_translate(self, peer, ids, language, chat=False, thread_root=None, window_peer=None):
        """Telegram translation, with local caching for automatic translation."""
        from tg_ascii.secret_chats import is_secret_peer

        peer, language = int(peer), str(language)
        if is_secret_peer(peer):
            raise ValueError('Secret chat messages cannot be translated by Telegram.')
        ids = [int(item) for item in ids][:200]
        account, backend = self.account, self.backend
        if not chat:
            result = await asyncio.wait_for(backend.translate_messages(peer, ids, language, premium=False), 120)
            return {str(ident): self.text_entities_json(value) for ident, value in result.items()}
        key = self.translation_key(peer, thread_root)
        context, discussion = self.discussion_view(window_peer)
        if thread_root is not None and context != (self.account, peer, thread_root):
            raise ValueError('The active discussion changed.')
        messages = discussion.values() if thread_root is not None else self.histories.get(peer) or ()
        store = self.translations()
        if store.language(key) != language:
            return {}
        texts = {m.id: (m.raw_text or m.text or '') for m in messages if m.id in ids}
        found, missing = {}, []
        saved = store.lookup(key, language, texts.items())
        for ident in ids:
            cached = saved.get(ident)
            if cached is not None:
                found[str(ident)] = self.display_translation(cached)
            else:
                missing.append(ident)
        if missing:
            result = await asyncio.wait_for(backend.translate_messages(peer, missing, language, premium=True), 120)
            if self.account != account or self.backend is not backend or store.language(key) != language:
                return {}
            current = self.discussion_view(window_peer)[1].values() if thread_root is not None else self.histories.get(peer) or ()
            if thread_root is not None and self.discussion_view(window_peer)[0] != context:
                return {}
            current_texts = {m.id: (m.raw_text or m.text or '') for m in current if m.id in texts}
            rows = []
            for ident, value in result.items():
                content = translated_content(value)
                found[str(ident)] = self.display_translation(content)
                if int(ident) in texts and current_texts.get(int(ident)) == texts[int(ident)]:
                    rows.append((int(ident), texts[int(ident)], content))
            store.store(key, language, rows)
        return found

    async def api_summarize(self, peer, id, language):
        result = await asyncio.wait_for(self.backend.summarize_message(int(peer), int(id), str(language)), 90)
        return self.text_entities_json(result)

    async def api_transcribe(self, peer, id):
        from telethon import errors
        from tg_ascii.i18n import tr
        try:
            result = await asyncio.wait_for(self.backend.transcribe_audio(int(peer), int(id)), 90)
        except errors.PremiumAccountRequiredError:
            raise ValueError(tr('Transcribing voice messages requires Telegram Premium.'))
        return {'text': self.text(getattr(result, 'text', '') or ''), 'pending': bool(getattr(result, 'pending', False))}

    async def api_compose_ai(self, text, mode='proofread', language='en', emojis=()):
        """Proofread, add emoji or translate the text being written (Telegram AI)."""
        spans, position = [], 0
        for ident, alt in emojis or ():  # match successive occurrences of each fallback
            start = str(text).find(alt, position)
            if start >= 0:
                spans.append((start, start + len(alt), int(ident), alt))
                position = start + len(alt)
        result = await asyncio.wait_for(self.backend.compose_ai(str(text), (), spans, str(mode), str(language)), 90)
        return self.text_entities_json(result)

    async def api_premium(self):
        return {'premium': bool(await asyncio.wait_for(self.backend.premium_enabled(), 20))}

    # -- channel comments (desktop: discussion threads) -------------------------------
    def discussion_view(self, window_peer=None):
        if window_peer is None:
            return self.open_discussion, self.discussion_messages
        return self.window_discussions.get(window_peer, (None, {}))

    def active_discussions(self):
        return [self.discussion_view(), *self.window_discussions.values()]

    async def api_comments(self, peer, id, window_peer=None):
        """Open the post's discussion in the requesting window."""
        if window_peer is None:
            self.open_revision += 1
            revision = self.open_revision
        else:
            if window_peer not in self.window_peers:
                raise ValueError('The chat window is no longer open.')
            revision = object()
            self.window_revisions[window_peer] = revision

        def current():
            active = self.open_revision if window_peer is None else self.window_revisions.get(window_peer)
            return active == revision and not self.locked

        account, backend = self.account, self.backend
        found = await asyncio.wait_for(backend.discussion_message(int(peer), int(id)), 30)
        if not current():
            raise ValueError('The active conversation changed.')
        group, root = found['peer'], found['root_id']
        if window_peer is not None and window_peer not in (int(peer), group):
            raise ValueError('The chat window is no longer open.')
        page = await asyncio.wait_for(backend.discussion_history(group, root), 30)
        if self.account != account or self.backend is not backend:
            raise ValueError('The active account changed.')
        if not current():
            raise ValueError('The active conversation changed.')
        discussion = [found['root'], *page]
        context = (account, group, root)
        messages = {message.id: message for message in discussion}
        if window_peer is None:
            self.open_discussion, self.discussion_messages = context, messages
            self.open_peer = None
        else:
            self.window_discussions[window_peer] = (context, messages)
        self.loop.create_task(self._read_comments(backend, group, root, list(page)))
        return {'peer': group, 'root_id': root, 'root': self.message_json(found['root']),
                'draft': self.draft_record(group, root), 'outbox': [item for item in self.outbox_items(account, group)['items'] if item['thread_root'] == root],
                'messages': [item for item in (self.message_json(m) for m in page) if item],
                'next': page.next_offset, 'more': page.more, **self.translation_state(group, discussion, root)}

    async def api_comments_older(self, peer, root_id, offset, window_peer=None):
        peer, root_id = int(peer), int(root_id)
        account, backend = self.account, self.backend
        page = await asyncio.wait_for(backend.discussion_history(peer, root_id, int(offset)), 30)
        if self.account != account or self.backend is not backend:
            raise ValueError('The active account changed.')
        context, messages = self.discussion_view(window_peer)
        if context == (account, peer, root_id):
            messages.update((message.id, message) for message in page)
        return {'messages': [item for item in (self.message_json(m) for m in page) if item],
                'next': page.next_offset, 'more': page.more, **self.translation_state(peer, page, root_id)}

    async def _read_comments(self, backend, peer, root_id, messages):
        if self.locked or backend is not self.backend or not any(
                context == (self.account, peer, root_id) for context, _ in self.active_discussions()):
            return
        try:
            newest = max((m.id for m in messages), default=0)
            if newest:
                if self.is_forum_chat(peer):
                    await backend.forum_mark_read(peer, root_id, newest)
                else:
                    await backend.read_discussion(peer, root_id, newest)
        except Exception:
            pass

    # -- call history (desktop: Calls list) ---------------------------------------
    async def enable_call_manager(self):
        if self.stage != 'ready' or self.backend is None or self.native_call_available is None:
            return
        async with self.call_manager_lock:
            if self.call_manager is not None or not await asyncio.to_thread(self.native_call_available):
                return
            from tg_ascii.calls import CallManager
            backend = self.backend
            if backend is None or self.stage != 'ready':
                return
            factory = self.native_call_manager or CallManager
            manager = factory(backend.client, self.on_native_call,
                                  engine_factory=self.native_call_engine, available=self.native_call_available)
            await manager.enable()
            self.call_manager = manager

    def on_native_call(self, snapshot):
        self.emit('native_call', self.call_json(snapshot))
        if self.native_callkit_update is not None:
            chat = next((item for item in self.chats if item.id == snapshot.get('peer')), None)
            name = self.text(chat.name) if chat is not None and not self.locked else ''
            self.native_callkit_update({**snapshot, 'name': name})
        if self.native_telecom is not None:
            manager = self.call_manager
            token = snapshot.get('token')

            async def control(answer):
                if self.call_manager is not manager or not manager or manager.snapshot.get('token') != token:
                    return
                phase = manager.snapshot.get('state')
                if answer:
                    if phase == 'incoming' and not self.locked and not self.in_background:
                        await self.api_call_action('accept', token=token)
                elif phase not in ('idle', 'ended'):
                    await manager.decline(token=token)

            def schedule(answer):
                future = asyncio.run_coroutine_threadsafe(control(answer), self.loop)
                future.add_done_callback(lambda result: result.exception() if not result.cancelled() else None)

            self.native_telecom(snapshot, lambda: schedule(True), lambda: schedule(False))
        self.sync_incoming_call_notification()

    def sync_incoming_call_notification(self):
        notify = self.native_incoming_call
        if notify is None:
            return
        manager = self.call_manager
        snapshot = manager.snapshot if manager else {}
        token = snapshot.get('token')
        notice = None
        if token and snapshot.get('state') == 'incoming' and (self.in_background or self.locked):
            if not self.prefs or self.prefs.values.get('notifications', True):
                notice = (manager, token)
        if notice == self._incoming_call_notice:
            return
        self._incoming_call_notice = notice
        if notice is None:
            notify(None, None)
            return

        async def decline():
            if self.call_manager is manager and manager.snapshot.get('token') == token:
                if manager.snapshot.get('state') == 'incoming':
                    await manager.decline(token=token)

        def schedule_decline():
            future = asyncio.run_coroutine_threadsafe(decline(), self.loop)
            future.add_done_callback(lambda result: result.exception() if not result.cancelled() else None)

        notify(token, schedule_decline)

    async def close_call_manager(self):
        if getattr(self, 'call_pip', None):
            self.call_pip.close()
        async with self.call_manager_lock:
            manager, self.call_manager = self.call_manager, None
            if self.native_telecom is not None:
                self.native_telecom({}, None, None)
            self.sync_incoming_call_notification()
            if self.native_callkit_update is not None:
                self.native_callkit_update({})
            group, self.group_call_manager = self.group_call_manager, None
            self._channel_calls = None
            for item in (group, manager):
                if item:
                    await item.close()

    def call_json(self, snapshot):
        return {**snapshot, 'can_pip': bool(getattr(self, 'call_pip', None)), 'can_share_screen': hasattr(self.call_manager, 'share_screen')}

    async def api_call_state(self):
        await self.enable_call_manager()
        manager = self.call_manager
        return {'available': manager is not None, 'call': self.call_json(manager.snapshot) if manager else None}

    async def api_call_action(self, action, peer=None, token=None, video=False, value=False):
        return await self._call_action(action, peer, token, video, value)

    async def _call_action(self, action, peer=None, token=None, video=False, value=False, *, from_system=False):
        from tg_ascii.i18n import tr
        await self.enable_call_manager()
        manager = self.call_manager
        if manager is None:
            raise ValueError(tr('Calls are unavailable on this device.'))
        if action != 'start' and (not token or token != manager.snapshot['token']):
            raise ValueError(tr('This call is no longer active'))
        if action in ('start', 'accept') or (action == 'camera' and value):
            await self.native_call_permission(value if action == 'camera' else video)
            if self.call_manager is not manager or self.locked:
                raise ValueError(tr('This call is no longer active'))
        if action == 'accept' and not from_system and self.native_callkit_answer is not None:
            result = await self.native_callkit_answer(token, video)
            if result is not None:
                return result
        if action == 'start':
            await manager.start(int(peer), video)
        elif action == 'accept':
            await manager.accept(peer, video, token=token)
        elif action == 'end':
            await manager.decline(peer, token=token)
        elif action == 'mute':
            await manager.mute(value, token=token)
        elif action == 'screen' and hasattr(manager, 'share_screen'):
            await manager.share_screen(bool(value), token=token)
        elif action == 'camera':
            if manager.snapshot.get('screen'):
                raise ValueError(tr('Stop sharing screen'))
            await manager.set_camera(value, token=token)
        else:
            raise ValueError('call action')
        return self.call_json(manager.snapshot)

    async def api_call_pip(self, token, group=False):
        pip = getattr(self, 'call_pip', None)
        return bool(pip and await pip.open(token, group))

    async def api_call_frames(self, token):
        if getattr(self, 'call_pip', None) and self.call_pip.matches(token):
            return {}
        manager = self.call_manager
        if manager is None or manager.snapshot['token'] != token:
            return {}
        from .android_calls import frame_jpeg
        frames = {'remote': manager.take_frame(), 'local': manager.take_local_frame()}
        encoded = await asyncio.gather(*(asyncio.to_thread(frame_jpeg, frame)
                                         for frame in frames.values() if frame and frame['token'] == token))
        if self.locked or self.call_manager is not manager or manager.snapshot['token'] != token:
            return {}
        return dict(zip((key for key, frame in frames.items() if frame and frame['token'] == token), encoded))

    # -- group voice/video chats and conferences (desktop: calls_group, channel_calls) --
    async def enable_group_call_manager(self):
        if self.stage != 'ready' or self.backend is None or self.native_group_call_manager is None:
            return None
        async with self.call_manager_lock:
            if self.group_call_manager is None:
                if not await asyncio.to_thread(self.native_call_available):
                    return None
                backend = self.backend
                manager = self.native_group_call_manager(
                    backend.client, lambda snapshot: self.emit('group_call', self.group_call_json(snapshot)),
                    available=self.native_call_available)
                await manager.enable()
                if self.backend is not backend or self.stage != 'ready':
                    await manager.close()
                    return None
                self.group_call_manager = manager
            return self.group_call_manager

    def group_call_json(self, snapshot):
        if not snapshot:
            return None
        manager = self.group_call_manager
        chat = next((item for item in self.chats if item.id == snapshot.get('peer')), None)
        return {**snapshot, 'name': self.text(chat.name) if chat else '',
                'conference': bool(manager and manager.conference),
                'can_pip': bool(getattr(self, 'call_pip', None)),
                'can_manage': bool(manager and manager.can_manage),
                'can_share_screen': bool(manager and hasattr(manager, 'share_screen'))}

    def channel_calls(self):
        from tg_ascii.channel_calls import ChannelCalls
        client = self.backend.client
        if self._channel_calls is None or self._channel_calls.client is not client:
            self._channel_calls = ChannelCalls(client)
        return self._channel_calls

    async def api_group_call_state(self):
        manager = await self.enable_group_call_manager()
        return {'available': manager is not None,
                'call': self.group_call_json(manager.snapshot) if manager else None}

    async def api_group_call_info(self, peer):
        """Whether the group or channel has a voice/video chat now, and what you may do."""
        from tg_ascii.i18n import tr
        manager = await self.enable_group_call_manager()
        if manager is None:
            raise ValueError(tr('Calls are unavailable on this device.'))
        info = await asyncio.wait_for(self.channel_calls().info(int(peer)), 25)
        scheduled = info.get('scheduled')
        return {**info, 'scheduled': _timestamp(scheduled) if scheduled else None,
                'title': self.text(info.get('title') or '')}

    async def api_conference_invitation(self, peer, message):
        """A conference invitation message: whether it can still be joined."""
        from tg_ascii.conference_invitations import invitation
        info = await asyncio.wait_for(invitation(self.backend, int(peer), int(message)), 25)
        return {**info, 'title': self.text(info.get('title') or ''),
                'participants': [self.text(name) for name in info.get('participants') or ()][:20]}

    async def api_group_call_manage(self, peer, call_id, action, value=None):
        """Administrators: end, start or cancel a scheduled call, or (anyone) be
        notified when it starts, without joining it (desktop: Channel calls)."""
        from tg_ascii.i18n import tr
        if action not in ('end', 'start', 'cancel', 'subscribe'):
            raise ValueError('group call action')
        if self.backend is None:
            raise ValueError(tr('Calls are unavailable on this device.'))
        await asyncio.wait_for(self.channel_calls().change(
            int(peer), int(call_id), action, **({'enabled': bool(value)} if action == 'subscribe' else {})), 25)
        return await self.api_group_call_info(peer)

    async def api_group_call_action(self, action, peer=None, token=None, video=False, value=None,
                                    user=None, title=None, message=None):
        from tg_ascii.i18n import tr
        manager = await self.enable_group_call_manager()
        if manager is None:
            raise ValueError(tr('Calls are unavailable on this device.'))
        starts = {'join': {}, 'create': {'create': True}, 'conference': {'conference': True},
                  'invitation': {'conference': int(message or 0)}}
        if action in starts:
            if self.call_manager is not None and self.call_manager.snapshot.get('state') not in ('idle', 'ended'):
                raise ValueError(tr('Another call is already active'))
            if action == 'invitation' and not message:
                raise ValueError('call invitation')
            await manager.start(int(peer), video=bool(video), **starts[action])
            return self.group_call_json(manager.snapshot)
        if not token or token != manager.snapshot.get('token'):
            raise ValueError(tr('This call is no longer active'))
        if action == 'leave':
            await manager.hangup(token=token)
        elif action == 'end_all':
            await manager.end_for_everyone(token=token)
        elif action == 'mute':
            await manager.mute(bool(value), token=token)
        elif action == 'screen' and hasattr(manager, 'share_screen'):
            await manager.share_screen(bool(value), token=token)
        elif action == 'camera':
            if manager.snapshot.get('screen'):
                raise ValueError(tr('Stop sharing screen'))
            if value:
                await self.native_call_permission(True)
            await manager.set_camera(bool(value), token=token)
        elif action == 'raise_hand':
            me = await self.backend.client.get_me(input_peer=False)
            await manager.participant_action(me.id, token=token, raise_hand=bool(value))
        elif action == 'mute_participant':
            await manager.participant_action(int(user), token=token, muted=bool(value))
        elif action == 'participant_volume':
            if type(value) is not int or not 0 <= value <= 200:
                raise ValueError(tr('Invalid local volume'))
            await manager.local_participant_volume(int(user), token=token, volume=value * 100)
        elif action == 'invite':
            await manager.invite(int(user), token=token)
        elif action == 'view':
            await manager.view_participant(int(user), token=token, screen=bool(value))
        elif action == 'title':
            await manager.edit_title(str(title or ''), token=token)
        elif action == 'join_muted':
            await manager.set_join_muted(bool(value), token=token)
        elif action == 'record':
            await manager.set_recording(bool(value), token=token, title=str(title or ''))
        else:
            raise ValueError('group call action')
        return self.group_call_json(manager.snapshot)

    async def api_group_call_details(self, token, offset=0):
        """Participants (and pending invitations) plus the call's settings."""
        manager = self.group_call_manager
        if manager is None or manager.snapshot.get('token') != token:
            return {'items': [], 'next': None, 'control': {}}
        page = await manager.participants(token=token, offset=int(offset or 0))
        control = await manager.control_info(token=token)
        scheduled = control.get('scheduled')
        control = {**control, 'title': self.text(control.get('title') or ''),
                   'scheduled': _timestamp(scheduled) if scheduled else None}
        items = [{**item, 'name': self.text(item.get('name') or '')} for item in page['items']]
        return {'items': items, 'next': page['next'], 'control': control}

    async def api_group_call_frames(self, token):
        if getattr(self, 'call_pip', None) and self.call_pip.matches(token):
            return {}
        manager = self.group_call_manager
        if manager is None or manager.snapshot.get('token') != token:
            return {}
        from .android_calls import frame_jpeg
        local = manager.take_local_frame()
        grid = manager.video_grid
        tiles = []
        if grid:
            frames = manager.take_frames()
            tiles = [str(ssrc) for ssrc in manager.active_tiles()]
        else:
            frame = manager.take_frame()
            frames = {'remote': frame} if frame else {}

        def encode():
            images = {str(ssrc): frame_jpeg(frame, 240 if len(tiles) > 1 else 480)
                      for ssrc, frame in frames.items() if frame['token'] == token}
            result = {'tiles': tiles, 'cameras': images} if grid else images
            if local and local['token'] == token:
                result['local'] = frame_jpeg(local)
            return result

        result = await asyncio.to_thread(encode)
        if self.locked or self.group_call_manager is not manager or manager.snapshot.get('token') != token:
            return {}
        return result

    async def api_calls(self, offset=None, missed=False):
        from tg_ascii.call_outcomes import LABELS
        from tg_ascii.i18n import tr

        result = await asyncio.wait_for(self.backend.call_history(offset, bool(missed)), 30)
        items = []
        for item in result['items']:
            outcome = item.get('outcome')
            label = LABELS.get(outcome) if outcome != 'ended' else None
            items.append({**item, 'name': self.text(item['name']), 'date': _timestamp(item['date']),
                          'outcome_label': tr(label) if label else ''})
        return {**result, 'items': items}

    # -- Telegram Premium (desktop: profile customization, privacy) ----------------------
    async def api_premium_settings(self):
        from tg_ascii.profile_customization import color_options
        backend = self.backend
        me = await asyncio.wait_for(backend.client.get_me(), 20)
        premium = bool(getattr(me, 'premium', False))
        status = getattr(me, 'emoji_status', None)
        until = getattr(status, 'until', None)

        # Telegram's seven built-in name colours come without a palette.
        builtin = {0: [0xe17076], 1: [0xfaa774], 2: [0xa695e7], 3: [0x7bc862], 4: [0x6ec9cb], 5: [0x65aadd], 6: [0xee7aae]}

        def colors(items):
            result = []
            for item in items:
                palette = []
                for source in (getattr(item, 'colors', None), getattr(item, 'dark_colors', None)):
                    palette = (getattr(source, 'colors', None) or getattr(source, 'bg_colors', None)
                               or getattr(source, 'palette_colors', None) or [])
                    if palette:
                        break
                palette = palette or builtin.get(item.color_id, [])
                result.append({'id': item.color_id, 'colors': ['#%06x' % (value & 0xFFFFFF) for value in palette[:3]]})
            return result
        try:
            names, profiles = await asyncio.gather(color_options(backend), color_options(backend, profile=True))
        except Exception:
            names, profiles = [], []
        try:
            privacy = await asyncio.wait_for(backend.global_privacy(), 20)
        except Exception:
            privacy = None
        return {'premium': premium,
                'emoji_status': {'id': str(getattr(status, 'document_id', '') or ''), 'until': until.timestamp() if until else None}
                if getattr(status, 'document_id', None) else None,
                'name_color': getattr(getattr(me, 'color', None), 'color', None),
                'profile_color': getattr(getattr(me, 'profile_color', None), 'color', None),
                'name_colors': colors(names), 'profile_colors': colors(profiles),
                'privacy': {key: bool(getattr(privacy, key, False)) for key in
                            ('hide_read_marks', 'archive_and_mute_new_noncontact_peers', 'new_noncontact_peers_require_premium')}
                if privacy is not None else None}

    async def api_set_emoji_status(self, id=None, duration=None):
        from tg_ascii.profile_customization import set_native
        value = None
        if id:
            value = int(id)
            if duration:
                value = {'document_id': int(id), 'until': int(time.time() + int(duration))}
        await asyncio.wait_for(set_native(self.backend, 'emoji_status', value), 30)
        return await self.api_premium_settings()

    async def api_set_color(self, field, color=None):
        from tg_ascii.profile_customization import set_native
        if field not in ('name_color', 'profile_color'):
            raise ValueError(field)
        await asyncio.wait_for(set_native(self.backend, field, {'color': int(color)} if color is not None else None), 30)
        return await self.api_premium_settings()

    async def api_global_privacy(self, changes):
        await asyncio.wait_for(self.backend.save_global_privacy({str(key): bool(value) for key, value in dict(changes).items()}), 30)
        return await self.api_premium_settings()

    # -- articles and checklists (desktop: advanced messaging) ---------------------------
    async def api_send_article(self, peer, source, format='markdown', rtl=False, noautolink=False, reply_to=None, account=None, thread_root=None, topic_id=None):
        reply_to = self.send_reply(peer, reply_to, thread_root, account)
        if topic_id is not None:
            reply_to = await self.forum_call('forum_reply', int(peer), int(topic_id),
                                           reply_to if reply_to != thread_root else None, account=account)
        from telethon import errors
        from tg_ascii.i18n import tr
        try:
            await asyncio.wait_for(self.backend.send_article(int(peer), str(source), format=str(format), rtl=bool(rtl),
                                                             noautolink=bool(noautolink), reply_to=reply_to), 60)
        except errors.RPCError as exc:
            print('article:', type(exc).__name__, exc, flush=True)
            raise ValueError(tr('Telegram did not accept the article') + f' ({getattr(exc, "message", "") or type(exc).__name__}).')
        return True

    async def api_send_checklist(self, peer, title, items, reply_to=None, account=None, thread_root=None, topic_id=None):
        reply_to = self.send_reply(peer, reply_to, thread_root, account)
        if topic_id is not None:
            reply_to = await self.forum_call('forum_reply', int(peer), int(topic_id),
                                           reply_to if reply_to != thread_root else None, account=account)
        await asyncio.wait_for(self.backend.send_checklist(int(peer), str(title), [str(item) for item in items if str(item).strip()][:30],
                                                           reply_to=reply_to), 60)
        return True

    async def api_article(self, peer, id):
        """A whole article: its text and how many photos it has (carousel)."""
        from tg_ascii.rich_articles import rich_article_text
        account, backend = self.account, self.backend
        rich, own = await asyncio.wait_for(backend.article_state(int(peer), int(id)), 60)
        if self.account != account or self.backend is not backend or self.locked:
            raise PermissionError('The active account changed.')
        return {'text': self.text(rich_article_text(rich) or ''), 'photos': len(getattr(rich, 'photos', None) or ()), 'own': own}

    async def article_photo(self, peer, ident, index):
        from telethon import types
        account, backend = self.account, self.backend
        raw, restricted = await self.media_message(peer, ident, account, backend, fresh=True, article=True)
        rich = getattr(raw, 'rich_message', None)
        if rich is None or getattr(rich, 'part', False):
            rich, _own = await backend.article_state(int(peer), int(ident))
        if self.account != account or self.backend is not backend or self.locked:
            raise PermissionError('The active account changed.')
        photos = list(getattr(rich, 'photos', None) or ())
        if not 0 <= index < len(photos):
            raise LookupError('photo')
        media = types.MessageMediaPhoto(photo=photos[index])
        if restricted:
            return await self.transient_media().file(account, backend, peer, ident, raw, False, 'original',
                                                     media=media, variant=('article', index))
        folder = self.media_folder()
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = folder / f'{int(peer)}-{int(ident)}-a{index}.jpg'
        if not target.is_file():
            await backend.download_media(media, target)
        if self.account != account or self.backend is not backend or self.locked:
            target.unlink(missing_ok=True)
            raise PermissionError('The active account changed.')
        return target

    # -- group and channel management (desktop: community management) ---------------------
    async def api_group_change(self, peer, field, value=None, key=None, account=None):
        """Title, description, photo (staged key; None removes), username, auto-delete,
        slow mode, default permissions, reactions or a new invite link."""
        if account is not None and account != self.account:
            raise ValueError('The active account changed.')
        path = self.staged(key) if field == 'photo' and key else None
        result = await asyncio.wait_for(self.backend.profile_change(int(peer), field, str(path) if path else value), 120)
        if path is not None:
            path.unlink(missing_ok=True)
        if field == 'photo':
            self.forget_avatar(int(peer))
        link = getattr(result, 'link', None)
        return {'link': link} if link else True

    async def api_member(self, peer, user, account=None):
        from tg_ascii.i18n import tr
        from tg_ascii.profile_details import PERMISSIONS
        if account is not None and account != self.account:
            raise ValueError('The active account changed.')
        found = await asyncio.wait_for(self.backend.community_member(int(peer), int(user)), 30)
        rights, banned = found['rights'], found['banned']
        from telethon import types
        entity = found['entity']
        channel = isinstance(entity, types.Channel)
        own_rights = getattr(entity, 'admin_rights', None)
        return {'role': found['role'], 'rank': getattr(found['participant'], 'rank', '') or '',
                'can_admin': found['can_admin'], 'can_ban': found['can_ban'], 'basic': not channel,
                'can_restrict': found['can_ban'] and channel and bool(entity.megagroup),
                'admin_rights': [[key, tr(label), bool(getattr(rights, key, False)),
                                  bool(entity.creator or getattr(own_rights, key, False))]
                                 for key, label in found['fields'].items()],
                'permissions': [[key, tr(label), allowed] for key, label, allowed in permission_rows(banned, PERMISSIONS, tr)],
                'until': int(banned.until_date.timestamp()) if getattr(banned, 'until_date', None) else None}

    async def api_member_admin(self, peer, user, changes, rank=None, account=None):
        if account is not None and account != self.account:
            raise ValueError('The active account changed.')
        await asyncio.wait_for(self.backend.community_admin(int(peer), int(user), changes, rank), 30)
        return True

    async def api_member_restrict(self, peer, user, changes=None, action='restrict', duration=None, account=None):
        from datetime import datetime, timedelta, timezone
        if account is not None and account != self.account:
            raise ValueError('The active account changed.')
        if duration is not None and (type(duration) is not int or not 60 <= duration <= 366 * 86400):
            raise ValueError('Invalid restriction duration.')
        until = datetime.now(timezone.utc) + timedelta(seconds=duration) if duration is not None else None
        await asyncio.wait_for(self.backend.community_restrict(int(peer), int(user), changes,
                                                               action=action, until=until), 30)
        return True

    async def api_community_permissions(self, peer):
        from tg_ascii.i18n import tr
        from tg_ascii.profile_details import PERMISSIONS
        data = await asyncio.wait_for(self.backend.profile(int(peer)), 30)
        if data.get('kind') != 'group' or not data.get('can_ban'):
            raise PermissionError(tr('Telegram does not allow this action for your account.'))
        return permission_rows(data.get('default_banned_rights'), PERMISSIONS, tr)

    async def api_members_add(self, peer, users, account=None):
        if account is not None and account != self.account:
            raise ValueError('The active account changed.')
        result = await asyncio.wait_for(self.backend.community_add(int(peer), users), 60)
        return {'missing': len(getattr(result, 'missing_invitees', ()) or ())}

    async def api_discussion_groups(self, peer):
        result = await asyncio.wait_for(self.backend.discussion_groups(int(peer)), 30)
        return {'linked': result['linked'], 'items': [{**item, 'name': self.text(item['name'])} for item in result['items']]}

    async def api_set_discussion(self, peer, group=None, expected=None, expose=False, migrate=False, account=None):
        if account is not None and account != self.account:
            raise ValueError('The active account changed.')
        await asyncio.wait_for(self.backend.set_discussion_group(int(peer), int(group) if group else None,
                                                                 expected_link=expected, expose_history=bool(expose), migrate=bool(migrate)), 60)
        return True

    async def api_share_contacts(self, target, people, account=None, topic_id=None):
        """Contact cards for people with a phone, a profile link for the rest."""
        from telethon import utils
        self.check_active_account(account)
        backend = self.backend
        client = backend.client
        sent = 0
        for ident in [int(item) for item in people][:50]:
            person = await client.get_entity(ident)
            if self.backend is not backend or self.locked:
                raise ValueError('The contact selection is no longer active.')
            phone = getattr(person, 'phone', None)
            first = getattr(person, 'first_name', '') or utils.get_display_name(person) or str(person.id)
            last = getattr(person, 'last_name', '') or ''
            if phone:
                reply = await self.forum_call('forum_reply', int(target), int(topic_id), account=account) if topic_id is not None else None
                await backend.send_contact_card(int(target), first, last, '+' + str(phone).lstrip('+'), reply_to=reply)
            else:
                username = getattr(person, 'username', None)
                link = f'https://t.me/{username}' if username else f'tg://user?id={person.id}'
                text = f'{utils.get_display_name(person) or first}\n{link}'
                if topic_id is not None:
                    await self.forum_call('forum_send', int(target), int(topic_id), text, account=account)
                else:
                    await backend.send(int(target), text)
            sent += 1
            await asyncio.sleep(0.3)
        return {'sent': sent}

    async def api_members(self, peer, offset=0, query='', admins=False, mode='members'):
        result = await asyncio.wait_for(self.backend.profile_members(int(peer), int(offset), str(query or ''), bool(admins), str(mode)), 30)
        seconds = bool(self.prefs and self.prefs.values.get('show_seconds'))
        from tg_ascii.telegram_actions import peer_activity
        items = []
        for item in result['items']:
            try:
                status = peer_activity(item.get('activity_entity'), seconds)
            except Exception:
                status = ''
            items.append({'id': item['id'], 'name': self.text(item['name']), 'role': item['role'], 'rank': self.text(item.get('rank') or ''),
                          'status': self.text(status or '')})
        return {'items': items, 'next': result['next_offset'], 'more': result['more']}

    async def api_create_community(self, title, about='', channel=False, account=None, forum=False):
        if account is not None and account != self.account:
            raise ValueError('The active account changed.')
        chat = await asyncio.wait_for(self.backend.create_community(title, about, channel, forum=bool(forum)), 60)
        if account is None or account == self.account:
            self.loop.create_task(self.refresh_chats())
        return self.chat_json(chat)

    async def api_create_group(self, title, people):
        title = str(title or '').strip()
        if not title:
            from tg_ascii.i18n import tr
            raise ValueError(tr('Nombre del grupo:'))
        chat, missing = await asyncio.wait_for(self.backend.create_group(title, [int(item) for item in people]), 60)
        return {'id': chat.id, 'name': self.text(chat.name), 'kind': 'group', 'missing': int(missing or 0)}

    async def api_archive_chat(self, peer, archived):
        return await self._chat_flag(peer, 'archived', bool(archived), self.backend.archive_chat(peer, bool(archived)))

    async def api_mark_unread(self, peer, unread):
        return await self._chat_flag(peer, 'unread_mark', bool(unread), self.backend.set_chat_unread(peer, bool(unread)))

    async def api_search_messages(self, peer, query, thread_root=None, date=None, day_bounds=None):
        account, backend = self.account, self.backend
        if date:
            messages = await self.search_day(backend, int(peer), str(query or '').strip(), str(date), thread_root, day_bounds)
        elif thread_root is not None and self.is_forum_chat(peer):
            messages = await backend.forum_search(peer, thread_root, query)
        elif thread_root is not None:
            messages = await backend.search_discussion(peer, thread_root, query)
        else:
            messages = await backend.search_messages(peer, query)
        if self.account != account or self.backend is not backend:
            raise ValueError('The active account changed.')
        if isinstance(messages, tuple):
            messages = messages[0]
        return [self.message_json(m) for m in messages or []]

    async def search_day(self, backend, peer, query, day, thread_root, day_bounds):
        """Search the device's local day, or find its very first message."""
        from datetime import datetime, timedelta, timezone
        from tg_ascii.secret_chats import is_secret_peer

        midnight = datetime.strptime(day, '%Y-%m-%d')
        if day_bounds is None:
            day_bounds = (int(midnight.timestamp()), int((midnight + timedelta(days=1)).timestamp()))
        lower, upper = day_bounds
        if (type(lower) is not int or type(upper) is not int or not 0 < upper - lower <= 172800
                or abs(lower - midnight.replace(tzinfo=timezone.utc).timestamp()) > 86400):
            raise ValueError('Invalid date range.')
        start, end = (datetime.fromtimestamp(value, timezone.utc) for value in (lower, upper))
        def matches(text):
            return query.casefold() in (text or '').casefold()

        if is_secret_peer(peer):
            manager = backend.secret_chats
            page = manager.history(peer)
            found = []
            while page:
                for message in reversed(page):
                    stamp = _timestamp(message.date)
                    if stamp is None or stamp >= upper:
                        continue
                    if stamp < lower:
                        return found
                    if matches(message.raw_text or message.text):
                        if query:
                            found.append(message)
                            if len(found) == 100:
                                return found
                        else:
                            found = [message]
                page = manager.older_messages(peer, page[0].id)
            return found

        async def collect():
            if query and thread_root is None:
                messages = await backend.client.get_messages(peer, search=query, offset_date=end, limit=100)
                return [item for item in messages if item.date and start <= item.date < end]
            # Telegram's replies iterator ignores the search argument. Apply the
            # text filter to just this thread and day. For a date alone iterate
            # from midnight forwards, so busy chats still land at the first item.
            options = {'offset_date': end if query else start - timedelta(seconds=1), 'reverse': not query}
            if thread_root is not None:
                options['reply_to'] = int(thread_root)
            found = []
            async for item in backend.client.iter_messages(peer, **options):
                if not item.date:
                    continue
                if (query and item.date < start) or (not query and item.date >= end):
                    break
                if start <= item.date < end and matches(item.message):
                    found.append(item)
                    if len(found) >= (100 if query else 1):
                        break
            return found

        found = await asyncio.wait_for(collect(), 30)
        await backend.resolve_missing_senders(found)
        return [backend.message(item) for item in found]

    # settings
    async def api_notify_preferences(self, peer=None):
        from .notification_settings import read_settings
        backend = self.backend
        if peer is None:
            records = await asyncio.wait_for(backend.notification_settings(), 20)
            return {key: read_settings(record, self.system) for key, record in records.items()}
        from telethon import functions, types
        input_peer = await backend.client.get_input_entity(int(peer))
        record = await asyncio.wait_for(backend.client(functions.account.GetNotifySettingsRequest(
            types.InputNotifyPeer(input_peer))), 20)
        return read_settings(record, self.system)

    async def api_save_notify_preferences(self, target, changes, account):
        from .notification_settings import changes_from_web
        if account != self.account:
            raise ValueError('The active account changed.')
        values = changes_from_web(changes)
        await asyncio.wait_for(self.backend.save_notification_settings(target, values), 20)
        if values.get('show_previews') is False:
            peer = int(target) if str(target).removeprefix('-').isdigit() else None
            self.forget_notification_chats(account, peer)
        return True

    async def api_notify_exceptions(self):
        from telethon import functions, types, utils
        result = await asyncio.wait_for(self.backend.client(functions.account.GetNotifyExceptionsRequest(
            compare_sound=True, compare_stories=True)), 20)
        peers = {utils.get_peer_id(entity): self.text(utils.get_display_name(entity))
                 for entity in (*getattr(result, 'users', ()), *getattr(result, 'chats', ()))}
        identifiers = dict.fromkeys(utils.get_peer_id(update.peer.peer) for update in getattr(result, 'updates', ())
                                   if isinstance(update, types.UpdateNotifySettings)
                                   and isinstance(update.peer, types.NotifyPeer))
        return [{'id': peer, 'name': peers.get(peer) or str(peer)} for peer in identifiers]

    async def api_notify_reactions_and_contacts(self):
        from telethon import functions
        from .notification_settings import read_reactions
        client = self.backend.client
        reactions, signups_silent = await asyncio.wait_for(asyncio.gather(
            client(functions.account.GetReactionsNotifySettingsRequest()),
            client(functions.account.GetContactSignUpNotificationRequest()),
        ), 20)
        return {'reactions': read_reactions(reactions), 'contacts_joining': not signups_silent}

    async def api_save_notify_reactions(self, changes, account):
        from telethon import functions
        from .notification_settings import reactions_from_web
        if account != self.account:
            raise ValueError('The active account changed.')
        client = self.backend.client
        current = await asyncio.wait_for(client(functions.account.GetReactionsNotifySettingsRequest()), 20)
        await asyncio.wait_for(client(functions.account.SetReactionsNotifySettingsRequest(
            reactions_from_web(current, changes))), 20)
        return True

    async def api_ringtones(self):
        """The account's saved notification sounds (Telegram ringtones)."""
        from telethon import functions
        result = await asyncio.wait_for(self.backend.client(functions.account.GetSavedRingtonesRequest(hash=0)), 20)
        items = []
        for document in getattr(result, 'ringtones', ()) or ():
            audio = next((a for a in getattr(document, 'attributes', ()) if type(a).__name__ == 'DocumentAttributeAudio'), None)
            named = next((a for a in getattr(document, 'attributes', ()) if type(a).__name__ == 'DocumentAttributeFilename'), None)
            title = getattr(audio, 'title', None) or getattr(named, 'file_name', None) or str(document.id)
            items.append({'id': f'ringtone:{document.id}', 'title': self.text(str(title))[:60]})
        return items

    async def api_notify_reset(self, account):
        """Telegram's 'Reset all notifications' (exceptions included)."""
        from telethon import functions
        if account != self.account:
            raise ValueError('The active account changed.')
        await asyncio.wait_for(self.backend.client(functions.account.ResetNotifySettingsRequest()), 20)
        return True

    async def api_save_notify_contacts(self, enabled, account):
        from telethon import functions
        if account != self.account or type(enabled) is not bool:
            raise ValueError('Invalid notification setting.')
        return await asyncio.wait_for(self.backend.client(functions.account.SetContactSignUpNotificationRequest(
            silent=not enabled)), 20)

    async def api_siri_chats(self, account, peers=None):
        return self.siri_vocabulary.configure(self, account, peers)

    async def api_settings(self, values=None):
        if values:
            changes = {key: value for key, value in values.items() if key in self.settings_snapshot()
                       and key not in ('advanced_features', 'font_min', 'font_max', 'radius_max')}
            if isinstance(values.get('advanced_features'), dict):
                # The desktop's Complex features, on unless turned off here (mobile_features).
                stored = dict(self.prefs.values.get('mobile_features') or {})
                stored.update({key: value for key, value in values['advanced_features'].items()
                               if (key in MOBILE_FEATURES or key in MOBILE_FEATURES_OFF) and type(value) is bool})
                changes['mobile_features'] = stored
            self.prefs.save(changes)
            await self.apply_settings_changes(changes)
        return self.settings_snapshot()

    async def apply_settings_changes(self, changes, request_permission=True):
        from tg_ascii.i18n import set_language
        if 'app_display_name' in changes and getattr(self, 'native_display_name', None):
            self.native_display_name(self.prefs.values.get('app_display_name'))
            if getattr(self, 'native_home_name', None):
                self.native_home_name(self.prefs.values.get('app_display_name'))
        if 'local_pins' in changes:
            if changes['local_pins'] and self.chats and self.account not in self.local_pins.values:
                self.local_pins.save_order(self.account, [c.id for c in self.chats if c.pinned])
            self.emit('chats', [self.chat_json(c) for c in self.visible_chats()])
        if changes.get('mobile_features', {}).get('preload_startup'):
            self.loop.create_task(self.preload())
        set_language(self.prefs.values['language'])
        if request_permission and changes.get('notifications') and self.native_notify_permission is not None:
            self.native_notify_permission()
        if 'notifications' in changes:
            self.keep_connected()
            if not self.prefs.values.get('notifications', True) and self.native_notify_disable:
                self.native_notify_disable()
        if changes.get('notify_preview') is False or changes.get('notifications') is False:
            self.forget_notification_chats()
        if 'notify_preview' in changes or 'notifications' in changes:
            await self.sync_push_registration()
        self.apply_keep_loaded()
        self.emit('settings', self.settings_snapshot())
        self.publish_wear_appearance()

    async def api_reset_settings(self, scope, account):
        from .settings_reset import reset_settings
        return await reset_settings(self, scope, account)


    # -- Complex features › Keep more loaded / Prepare content at startup (3.0.0.2) --
    def feature(self, key):
        return bool(self.prefs) and mobile_features(self.prefs.values).get(key, False)

    def keep_loaded(self):
        return self.feature('keep_loaded')

    def apply_keep_loaded(self):
        """Memory budgets and the offline copy follow the switch (shared core)."""
        from tg_ascii import resources
        resources.set_keep_loaded(self.keep_loaded())
        if not self.keep_loaded():
            self.forget_details()

    def cached_detail(self, key):
        """A profile or the contact list asked for a few minutes ago (Keep more loaded)."""
        if not self.keep_loaded():
            return None
        found = self.__dict__.get('detail_cache', {}).get((self.account, key))
        if found is not None and time.monotonic() - found[0] < KEEP_DETAILS:
            return found[1]
        return None

    def remember_detail(self, key, value):
        if self.keep_loaded():
            cache = self.__dict__.setdefault('detail_cache', {})
            cache[(self.account, key)] = (time.monotonic(), value)
            while len(cache) > 200:
                cache.pop(next(iter(cache)))
        return value

    def forget_details(self):
        self.__dict__.pop('detail_cache', None)

    def forget_fresh_histories(self):
        self.__dict__.get('history_fresh', {}).clear()

    async def refresh_history(self, peer):
        """Keep more loaded: a chat reloaded a few minutes ago, with the
        connection up since then (live updates arrived meanwhile), only asks
        Telegram for the messages newer than the last one it has, as the
        official apps do. Otherwise the latest page is read again."""
        from tg_ascii.secret_chats import is_secret_peer
        fresh = self.__dict__.setdefault('history_fresh', {})
        cached = self.histories.get(peer)
        if (self.keep_loaded() and cached and not is_secret_peer(peer) and self.connection == 'online'
                and not self.in_background and time.monotonic() - fresh.get(peer, float('-inf')) < KEEP_FRESH):
            return await self.reload_newer(peer)
        return await self.reload_history(peer)

    async def reload_newer(self, peer):
        backend = self.backend
        previous = self.histories.get(peer)
        if backend is None or not previous:
            return await self.reload_history(peer)
        newest = max(message.id for message in previous)

        async def request():
            raw = await backend.client.get_messages(peer, min_id=newest, limit=100)
            if len(raw) >= 100:
                raise OverflowError('gap')  # many new messages: read the latest page instead
            await backend.resolve_missing_senders(raw)
            messages = [backend.message(item) for item in reversed(raw)]
            maximum = getattr(backend, 'read_max', {}).get(peer, 0)
            for message in messages:
                message.read = message.outgoing and message.id <= maximum
            return messages
        try:
            arrived = await self.history_page(peer, request(), include_new=True)
        except Exception:
            return await self.reload_history(peer)
        if backend is not self.backend or self.histories.get(peer) is not previous:
            return
        known = {message.id for message in previous}
        additions = [message for message in arrived if message.id not in known]
        if not additions:
            return  # nothing new: the screen is already up to date
        previous.extend(additions)
        previous.sort(key=lambda message: message.id)
        del previous[:-400]
        self.emit('history', {'peer': peer, 'messages': [self.message_json(m) for m in previous],
                              **self.translation_state(peer, previous)})
        self.schedule_save()

    async def preload(self):
        """Complex features › Prepare content at startup: once per account and
        launch, after the chat list, prepare what the first screens show."""
        from tg_ascii.secret_chats import is_secret_peer
        account, backend = self.account, self.backend
        done = self.__dict__.setdefault('preloaded_accounts', set())
        if not self.feature('preload_startup') or backend is None or account in done:
            return

        def current():
            return (self.account == account and self.backend is backend and not self.locked
                    and self.connection == 'online' and self.feature('preload_startup'))
        active = self.__dict__.setdefault('preloading_accounts', set())
        if not current() or not self.chats or account in active:
            return
        active.add(account)
        try:
            await self._prepare_chats(current)
            if current():
                done.add(account)
        finally:
            active.discard(account)

    async def _prepare_chats(self, current):
        from tg_ascii.secret_chats import is_secret_peer
        chats = self.visible_chats()[:80]
        slots = asyncio.Semaphore(3)

        async def gently(work):
            async with slots:
                if not current():
                    work.close()
                    return
                try:
                    await asyncio.wait_for(work, 60)
                except Exception:
                    pass
        # Profile photos of the list, then the latest messages of the first chats.
        previews_enabled = self.prefs.values.get('photo_previews', True)
        await asyncio.gather(*(gently(self.avatar_file(chat.id)) for chat in chats))
        for chat in chats[:12]:
            if not current():
                return
            if not is_secret_peer(chat.id) and chat.id not in self.__dict__.get('history_fresh', {}):
                await gently(self.reload_history(chat.id))
                await asyncio.sleep(0.2)  # well under Telegram's request limits
        previews = []
        for chat in chats[:12]:
            if is_secret_peer(chat.id):
                continue
            visual = [m for m in self.histories.get(chat.id) or () if m.media_kind in VISUAL_KINDS and m.media is not None]
            previews += [(chat.id, m.id) for m in visual[-6:]]
        if previews_enabled and self.prefs.values.get('inline_media', True):
            await asyncio.gather(*(gently(self.media_file(peer, ident, True)) for peer, ident in previews[:60]))
        emoji = {int(ident) for chat in chats for ident, _ in (self.previews.get(chat.id) or {}).get('emojis') or ()}
        await asyncio.gather(*(gently(self.sticker_file(ident)) for ident in list(emoji)[:80]))


    def default_reaction(self, account):
        values = self.prefs.values
        return str(values.get('mobile_quick_reactions', {}).get(account) or values.get('quick_reaction') or '👍')

    async def api_default_reaction_choices(self):
        """Standard reactions and recently used custom emoji (desktop: Reactions picker)."""
        account, backend = self.account, self.backend
        standard = await asyncio.wait_for(backend.available_reactions(), 20)
        custom = []
        try:
            from telethon import functions, types
            recent = await asyncio.wait_for(backend.client(functions.messages.GetRecentReactionsRequest(limit=50, hash=0)), 20)
            custom = [str(item.document_id) for item in getattr(recent, 'reactions', ()) if isinstance(item, types.ReactionCustomEmoji)]
        except Exception:
            pass
        if self.account != account or self.backend is not backend:
            raise ValueError('The active account changed.')
        current = self.default_reaction(account)
        if current.isascii() and current.isdecimal():
            custom.insert(0, current)
        return {'standard': [value for value in standard if isinstance(value, str)],
                'custom': list(dict.fromkeys(custom))[:40], 'current': current}

    async def api_set_default_reaction(self, value, account):
        """Save this account's double-tap reaction and try to sync it to Telegram."""
        backend = self.backend
        if account != self.account:
            raise ValueError('The active account changed.')
        value = str(value or '').strip()
        if not value or len(value) > 32:
            raise ValueError('reaction')
        stored = int(value) if value.isascii() and value.isdecimal() else value
        if isinstance(stored, int) and not 0 < stored < 2 ** 63:
            raise ValueError('reaction')
        choices = {**self.prefs.values.get('mobile_quick_reactions', {}), account: str(stored)}
        self.prefs.save({'mobile_quick_reactions': choices})
        self.emit('settings', self.settings_snapshot())
        try:
            synced = await asyncio.wait_for(backend.set_default_reaction(stored), 20)
        except Exception:
            synced = False
        return {'current': str(stored), 'synced': bool(synced)}

    async def api_alias(self, key, alias):
        aliases = dict(self.prefs.values.get('account_aliases') or {})
        if alias.strip():
            aliases[key] = alias
        else:
            aliases.pop(key, None)
        self.prefs.save({'account_aliases': aliases})
        return self.account_list()

    # accounts
    async def switch_finished(self, state):
        self.open_peer, self.preview = None, False
        self.open_revision += 1
        self.open_discussion = None
        self.discussion_messages.clear()
        self.window_discussions.clear()
        self.window_revisions.clear()
        self.window_peers.clear()
        self.floating_peers.clear()
        self.load_snapshot()
        self.emit('chats', [self.chat_json(chat) for chat in self.visible_chats()])
        self.after_login(state)

    @suspend_vocabulary
    async def api_account_select(self, key):
        await self.close_media_requests()
        await self.cancel_current_voice()
        await self.save_snapshot()
        await self.close_call_manager()
        self.disconnect_tv()
        state = await self.accounts.select(key)
        await self.switch_finished(state)
        return state

    @suspend_vocabulary
    async def api_account_add(self):
        await self.close_media_requests()
        self.disconnect_tv()
        await self.cancel_current_voice()
        await self.save_snapshot()
        await self.close_call_manager()
        state = await self.accounts.add()
        await self.switch_finished(state)
        return state

    async def api_account_reorder(self, keys):
        self.accounts.reorder(list(keys))
        return self.account_list()

    @suspend_vocabulary
    async def api_logout(self, key):
        self.disconnect_tv()
        if key == self.account:
            await self.cancel_current_voice()
            await self.close_call_manager()
        self._push_logging_out.add(key)
        try:
            if getattr(self, 'ios_notice_cache', None):
                self.ios_notice_cache.sync(self)
            await self.unregister_push_account(key)
            state = await self.accounts.logout(key)
        finally:
            self._push_logging_out.discard(key)
            if key not in self.accounts.entries:
                from tg_ascii.recent_searches import RecentSearches
                RecentSearches(self.root).forget_account(key)
                self.__dict__.get('_frequent_peers', {}).pop(key, None)
                self.siri_vocabulary.forget(key)
                self.forget_notification_chats(key)
                if (self.root / 'mobile' / 'notification-receipts.sqlite3').is_file():
                    with self.android_receipts() as db:
                        db.execute('DELETE FROM receipts WHERE account=?', (key,))
                import shutil
                shutil.rmtree(self.root / 'mobile-avatars' / key, ignore_errors=True)
                self.purge_account_drafts(key)
                self.purge_chat_wallpapers(key)
                if self.__dict__.get('_translations', (None,))[0] == key:
                    self.__dict__.pop('_translations', None)
                for suffix in ('.json', '.invalid.json', '.sqlite3', '.sqlite3-journal'):
                    (self.root / 'mobile' / f'translations-{key}{suffix}').unlink(missing_ok=True)
            if getattr(self, '_push_token', None):
                self.loop.create_task(self.sync_push_registration())
        await self.switch_finished(state)
        return state

    def purge_account_drafts(self, account):
        for key, task in tuple(self.draft_pull_jobs.items()):
            if key[0] == account:
                task.cancel()
                self.draft_pull_jobs.pop(key, None)
        job = self.draft_jobs.pop(account, None)
        if job is not None:
            job.cancel()
        self.loaded_draft_accounts.discard(account)
        secret_drafts = self.__dict__.get('_secret_drafts', {})
        for key in tuple(secret_drafts):
            if key[0] == account:
                del secret_drafts[key]
        self.draft_store.remove_account(account)
        for owner in tuple(self.draft_store.records):
            if owner.startswith(f'discussion:{account}:'):
                self.draft_store.remove(owner)
        self.draft_store.flush()
        legacy = self.root / 'mobile' / f'drafts-{account}.json'
        legacy.unlink(missing_ok=True)
        legacy.with_suffix('.migrated.json').unlink(missing_ok=True)

    # -- remote push registration (APNs / FCM -> account.registerDevice) --------------
    def install_notification_permission(self, enable, disable=None):
        """Called on the worker loop; native setup may finish after login."""
        self.native_notify_permission = enable
        self.native_notify_disable = disable
        if self.stage == 'ready':
            self.apply_notification_permission()

    def apply_notification_permission(self):
        if self.prefs:
            callback = (self.native_notify_permission if self.prefs.values.get('notifications', True)
                        else self.native_notify_disable)
            if callback:
                callback()

    def register_push_token(self, token_type, token, sandbox=False):
        token = str(token or '').strip()
        if not token:
            return
        self._push_token = (int(token_type), token, bool(sandbox))
        def accepted():
            if self._push_stopped:
                return
            self._push_retry_native = False
            self._push_status = {'state': 'registering', 'provider': 'APNs' if token_type == 1 else 'FCM', 'error': None}
            self.schedule_push_check(0)
        self.loop.call_soon_threadsafe(accepted)

    def schedule_push_check(self, delay):
        if self._push_stopped:
            return
        if self._push_check is not None:
            self._push_check.cancel()
        def run():
            self._push_check = None
            if self.prefs and not self.prefs.values.get('notifications', True):
                return
            if self._push_retry_native and self.native_push_retry is not None:
                self.native_push_retry()
            elif getattr(self, '_push_token', None):
                self.loop.create_task(self.sync_push_registration())
            elif self.native_push_retry is not None:
                self.native_push_retry()
        self._push_check = self.loop.call_later(max(0, delay), run)

    def native_push_failed(self, provider, code, retry=True, native=False):
        """Only fixed/numeric error codes, never provider payloads or tokens."""
        if self._push_stopped:
            return
        if code in ('permission_denied', 'permission_not_requested'):
            self._push_permission = 'denied' if code == 'permission_denied' else 'not_requested'
        self._push_status = {'state': 'retrying' if retry else 'unavailable', 'provider': provider,
                             'error': str(code)[:80]}
        self._push_retry_native = native
        if retry:
            self.schedule_push_check(self._push_retry_delay)
            self._push_retry_delay = min(300, self._push_retry_delay * 2)
        elif self._push_check is not None:
            self._push_check.cancel()
            self._push_check = None

    async def api_notification_status(self):
        return {**self._push_status, 'permission': self._push_permission,
                'token_received': bool(getattr(self, '_push_token', None)),
                'registered_accounts': len(self._push_registered), 'connected_accounts': len(self.push_clients()),
                'sandbox': bool(getattr(self, '_push_token', (None, None, False))[2])}

    async def connect_saved_push_account(self, key):
        """Attach a known saved session while keeping the start-up chooser open."""
        async with self._startup_account_gate:
            if self.stage != 'choose_account' or key in self._push_logging_out:
                return
            if not self.accounts.identities.get(key):
                return
            service = self.accounts.service(key)
            if service.backend is None and service.session_path.with_suffix('.session').is_file():
                if await service.connect(self.accounts.credentials) == 'ready':
                    await self.accounts.register(key)

    async def prepare_android_push_accounts(self):
        if self.stage == 'loading':
            await self._push_ready.wait()
        if self.stage == 'choose_account':
            for key in tuple(self.accounts.identities):
                await self.connect_saved_push_account(key)
            if self.stage == 'loading':
                await self._push_ready.wait()
        return self.stage != 'error'

    async def sync_android_badge(self, sent_at, user_id=None):
        """Discover actual unread messages via MTProto, restricted to the addressed account if present."""
        if not isinstance(sent_at, int) or sent_at <= 0:
            return 1
        if self.stage == 'loading':
            await self._push_ready.wait()
        if self.stage == 'error':
            return 2
        if not self.prefs or not self.prefs.values.get('notifications', True):
            return 1
        if user_id is not None:
            if type(user_id) is not int or user_id <= 0:
                return 1
            keys = [key for key, identity in self.accounts.identities.items() if identity == user_id]
            if len(keys) != 1:
                return 1
        else:
            keys = tuple(self.accounts.identities if self.stage == 'choose_account' else self.push_clients())
        # WorkManager retries failures. Give every account a chance to post before reporting one.
        results = await asyncio.gather(*(self._sync_account_badge(key, sent_at - 90, user_id) for key in keys),
                                       return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result
        return 0 if any(results) else 1

    async def _sync_account_badge(self, key, cutoff, user_id):
        if self.stage == 'choose_account':
            await self.connect_saved_push_account(key)
        if self.stage == 'loading':
            await self._push_ready.wait()
        client = self.push_clients().get(key)
        if client is None or (user_id is not None and self.accounts.identities.get(key) != user_id):
            return False
        delivered = False
        async for item in client.iter_dialogs():
            raw = item.message
            if raw is None or raw.date is None:
                continue
            if raw.date.timestamp() < cutoff:
                if item.pinned or getattr(item.dialog, 'folder', None) is not None:
                    continue
                break
            read_through = item.dialog.read_inbox_max_id
            if not item.unread_count or raw.id <= read_through:
                continue
            # A newer outgoing message or call can conceal the incoming message that woke us.
            if raw.out or getattr(raw, 'action', None) is not None:
                async for earlier in client.iter_messages(item.input_entity, offset_id=raw.id, min_id=read_through):
                    if earlier.date is None or earlier.date.timestamp() < cutoff:
                        break
                    if not earlier.out and getattr(earlier, 'action', None) is None:
                        raw = earlier
                        break
                if raw.out or getattr(raw, 'action', None) is not None:
                    continue
            if (self.push_clients().get(key) is not client
                    or (user_id is not None and self.accounts.identities.get(key) != user_id)):
                continue
            ident = (key, item.id, raw.id)
            if ident in self.recent_incoming_messages:
                job = self.recent_incoming_messages[ident]
                if job is not None:
                    await asyncio.shield(job)
                continue
            service = self.accounts.services[key]
            # Dialog state already includes this message. Posting directly avoids incrementing
            # the local unread counter a second time when a socket update also arrives.
            if await self.notify(key, item.id, service.backend.message(raw)):
                delivered = True
        return delivered

    async def refresh_android_push_token(self, token):
        if not await self.prepare_android_push_accounts():
            return 2
        info = (2, token, False)
        self._push_token = info
        await self.sync_push_registration()
        if self._push_token != info or (self.prefs and not self.prefs.values.get('notifications', True)):
            return 1
        for key, client in self.push_clients().items():
            registered = self._push_registered.get(key)
            if not registered or registered[:2] != (client, info):
                return 2
        return 0

    def push_clients(self):
        services = getattr(self.accounts, 'services', {}) or {}
        return {key: service.backend.client for key, service in tuple(services.items())
                if key not in self._push_logging_out
                and getattr(getattr(service, 'backend', None), 'client', None) is not None}

    def push_other_users(self, key, clients):
        identities = getattr(self.accounts, 'identities', {}) or {}
        return tuple(sorted({uid for other, uid in identities.items()
                             if other != key and other in clients and type(uid) is int and uid > 0}))

    async def sync_push_registration(self):
        from telethon import functions

        generation, accounts = self._push_generation, self.accounts
        def current():
            return not self._push_stopped and self._push_generation == generation and self.accounts is accounts
        if not current():
            return
        cache = getattr(self, 'ios_notice_cache', None)
        if cache:
            cache.sync(self)
        async with self._push_gate:
            if not current():
                return
            info = getattr(self, '_push_token', None)
            if not info or self.accounts is None:
                return
            token_type, token, sandbox = info
            live = self.push_clients()
            failure = None
            now = time.monotonic()
            for key in set(self._push_registered_at) - live.keys():
                self._push_registered_at.pop(key, None)
            for key, client in live.items():
                if self._push_token != info or self.push_clients().get(key) is not client:
                    continue
                others = self.push_other_users(key, live)
                registration = (client, info, others)
                previous = self._push_registered.get(key)
                if self.prefs and not self.prefs.values.get('notifications', True):
                    if await self.remove_push_registration(previous or registration, ()):
                        if not current():
                            return
                        self._push_registered.pop(key, None)
                    continue
                if token_type == 1 and self.prefs:
                    period = 0 if self.lock_record() or not self.prefs.values.get('notify_preview', True) else -1
                    if self._push_privacy.get(key) != (client, period):
                        try:
                            updated = await asyncio.wait_for(client(functions.account.UpdateDeviceLockedRequest(period)), 8)
                        except Exception:
                            updated = False
                        if not current():
                            return
                        if updated:
                            self._push_privacy[key] = (client, period)
                        else:
                            failure = 'privacy_registration'
                        if not updated and period == 0:
                            # Retry on reconnect before enabling previews on a protected device.
                            if await self.remove_push_registration(previous or registration, ()):
                                self._push_registered.pop(key, None)
                            continue
                if previous == registration and now - self._push_registered_at.get(key, 0) < 23 * 3600:
                    continue
                if previous and previous[1] != info:
                    await self.remove_push_registration(previous, ())
                    if not current():
                        return
                    self._push_registered.pop(key, None)
                if self._push_token != info or self.push_clients().get(key) is not client:
                    continue
                try:
                    result = await asyncio.wait_for(client(functions.account.RegisterDeviceRequest(
                        token_type=token_type, token=token, app_sandbox=sandbox,
                        secret=b'', other_uids=list(others))), 20)
                    if not current():
                        return
                    if result:
                        self._push_registered[key] = registration
                        self._push_registered_at[key] = time.monotonic()
                    else:
                        failure = 'registration_rejected'
                except Exception as error:
                    failure = type(error).__name__
            if not current():
                return
            if self.prefs and not self.prefs.values.get('notifications', True):
                if self._push_check is not None:
                    self._push_check.cancel()
                    self._push_check = None
                self._push_status = {'state': 'disabled', 'provider': 'APNs' if token_type == 1 else 'FCM', 'error': None}
            elif failure:
                self.native_push_failed('APNs' if token_type == 1 else 'FCM', failure)
            elif live:
                self._push_retry_delay = 5
                self._push_status = {'state': 'registered', 'provider': 'APNs' if token_type == 1 else 'FCM', 'error': None}
                self.schedule_push_check(min(max(1, 23 * 3600 - (time.monotonic() - self._push_registered_at.get(key, 0))) for key in live))

    @staticmethod
    async def remove_push_registration(registration, others):
        from telethon import functions

        client, (token_type, token, _sandbox), _other_users = registration
        try:
            return bool(await asyncio.wait_for(client(functions.account.UnregisterDeviceRequest(
                token_type=token_type, token=token, other_uids=list(others))), 5))
        except Exception:
            return False

    async def unregister_push_account(self, key):
        async with self._push_gate:
            self._push_privacy.pop(key, None)
            registration = self._push_registered.pop(key, None)
            if registration:
                await self.remove_push_registration(registration, self.push_other_users(key, self.push_clients()))

    def receive_push_payload(self, payload):
        return asyncio.run_coroutine_threadsafe(self._handle_push_payload(payload), self.loop)

    async def _handle_push_payload(self, payload):
        from tg_ascii.push_notifications import parse_hint
        from telethon import functions, utils
        from telethon.types import InputDialogPeer
        hint = parse_hint(payload if isinstance(payload, str) else json.dumps(payload))
        if hint is None:
            return 1  # UIBackgroundFetchResultNoData
        try:
            async with asyncio.timeout(23):
                if self.stage == 'loading':
                    await self._push_ready.wait()
                identities = getattr(self.accounts, 'identities', {}) or {}
                account = next((k for k, uid in identities.items() if uid == hint.user_id), None)
                if self.stage == 'choose_account' and account is not None:
                    await self.connect_saved_push_account(account)
                    if self.stage == 'loading':
                        await self._push_ready.wait()
                    if self.accounts.identities.get(account) != hint.user_id:
                        return 1
                if self.stage == 'error':
                    return 2
                services = getattr(self.accounts, 'services', {}) or {}
                client = self.push_clients().get(account)
                if client is None:
                    return 1
                backend = services[account].backend
                await client.catch_up()
                if hint.peer is None or hint.message_id is None:
                    return 1
                peer = await client.get_input_entity(hint.peer)
                dialogs, raw = await asyncio.gather(
                    client(functions.messages.GetPeerDialogsRequest([InputDialogPeer(peer)])),
                    client.get_messages(peer, ids=hint.message_id))
                dialog = next(iter(getattr(dialogs, 'dialogs', ())), None)
                if (raw is None or getattr(raw, 'id', None) != hint.message_id
                        or getattr(raw, 'out', False) or dialog is None
                        or getattr(dialog, 'read_inbox_max_id', 0) >= hint.message_id):
                    return 1
                raw_peer = getattr(raw, 'peer_id', None)
                if raw_peer is not None and utils.get_peer_id(raw_peer) != hint.peer:
                    return 1
                if self.push_clients().get(account) is not client:
                    return 1
                already_seen = (account, hint.peer, hint.message_id) in self.recent_incoming_messages
                delivery = self.on_message(account, hint.peer, backend.message(raw))
                if delivery is not None:
                    await asyncio.shield(delivery)
                return 1 if already_seen else 0  # NoData / NewData
        except Exception:
            return 2  # UIBackgroundFetchResultFailed

    # app data (1.5.3)
    def _mobile_cache_bytes(self, clear=False):
        import shutil
        from tg_ascii.app_data import folder_size
        total = 0
        for name in MOBILE_CACHE_FOLDERS:
            folder = self.root / name
            if not folder.is_symlink() and folder.is_dir():
                size = folder_size(folder)
                if clear:
                    shutil.rmtree(folder, ignore_errors=True)
                    size -= folder_size(folder) if folder.exists() else 0
                total += max(0, size)
        return total

    async def api_cache_size(self):
        from tg_ascii.app_data import cache_size, human_size
        total = await asyncio.to_thread(lambda: cache_size(self.root) + self._mobile_cache_bytes())
        return human_size(total)

    async def api_clear_cache(self):
        from tg_ascii.app_data import remove_cache, human_size
        freed = await asyncio.to_thread(lambda: remove_cache(self.root) + self._mobile_cache_bytes(clear=True))
        self.forget_media_index()
        return human_size(freed)

    @suspend_vocabulary
    async def api_delete_all(self):
        from tg_ascii.app_data import safe_to_wipe, wipe
        for key in list(self.accounts.entries):
            try:
                await asyncio.wait_for(self.accounts.logout(key), 30)
            except Exception:
                pass
        await self.shutdown()
        if safe_to_wipe(self.root):
            await asyncio.to_thread(wipe, self.root)
        self.siri_vocabulary.accounts.clear()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.loop.create_task(self.boot())
        return True



UNLOCKED_METHODS = {'state', 'launch_ready', 'strings', 'languages', 'unlock', 'lock_now', 'unlock_biometric', 'lock_info',
                    'app_hidden', 'app_visible', 'draft', 'close'}


def _text(value):
    return getattr(value, 'text', value) if value is not None else ''


EFFECT_LIMITS = {'text_border': 16, 'text_shadow': 32, 'text_underline': 32, 'button_border': 48, 'button_shadow': 48,
                 'menu_border': 48, 'menu_shadow': 48}
EFFECT_FLAGS = ('text_bold', 'text_italic', 'text_strike', 'text_uppercase')


def effects_json(values):
    """Text and control effects (desktop: visual_effects) plus bold / italic /
    strikethrough / capitals for message text."""
    import re
    values = values if isinstance(values, dict) else {}
    result = {}
    for key, limit in EFFECT_LIMITS.items():
        size = values.get(key)
        result[key] = size if type(size) is int and 0 <= size <= limit else 0
        color = values.get(key + '_color')
        result[key + '_color'] = color.lower() if isinstance(color, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', color) else ''
    for key in EFFECT_FLAGS:
        result[key] = values.get(key) is True
    return result


# Desktop "Complex features" that exist on mobile; on mobile they start on (the
# app already offered them): 'mobile_features' keeps only the ones turned off.
MOBILE_FEATURES = ('polls', 'checklists', 'locations', 'contacts', 'articles', 'stars_gifts', 'links', 'stories',
                   'chat_translation', 'call_history', 'calls', 'chat_list_activity', 'contact_list_details')
# 3.0.0.2: off unless turned on (Complex features): Keep more loaded and
# Prepare content at startup.
MOBILE_FEATURES_OFF = ('keep_loaded', 'preload_startup', 'media_originals', 'native_liquid_glass')
KEEP_FRESH = 600      # seconds a reloaded chat is trusted while the connection stays up
KEEP_DETAILS = 300    # seconds profiles and the contact list are reused
# Calls that change a profile or the contacts: the kept copies are dropped.
CHANGES_DETAILS = ('contact', 'block', 'profile', 'group', 'member', 'username', 'photo', 'bio', 'name',
                   'privacy', 'emoji_status', 'leave', 'join', 'delete_chat', 'note')


def mobile_features(values):
    stored = values.get('mobile_features') if isinstance(values.get('mobile_features'), dict) else {}
    features = {key: stored.get(key, True) is not False for key in MOBILE_FEATURES}
    features.update({key: stored.get(key) is True for key in MOBILE_FEATURES_OFF})
    return features


def emoji_status_id(entity):
    """The custom emoji id of a user's (or channel's) emoji status, while it lasts."""
    status = getattr(entity, 'emoji_status', None)
    ident = getattr(status, 'document_id', None)
    until = getattr(status, 'until', None)
    if not ident:
        return None
    if until is not None:
        import datetime as _dt
        moment = until if isinstance(until, _dt.datetime) else _dt.datetime.fromtimestamp(int(until), _dt.timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=_dt.timezone.utc)
        if moment <= _dt.datetime.now(_dt.timezone.utc):
            return None
    return str(ident)


def custom_emoji_spans(text, entities, limit=20):
    """[[document id, alt text]] of the custom emoji entities of a text."""
    spans, raw = [], None
    for entity in entities or ():
        ident = getattr(entity, 'document_id', None)
        if not ident:
            continue
        raw = raw if raw is not None else text.encode('utf-16-le')
        try:
            alt = raw[entity.offset * 2:(entity.offset + entity.length) * 2].decode('utf-16-le')
        except (UnicodeDecodeError, AttributeError, TypeError):
            continue
        spans.append([str(ident), alt])
    return spans[:limit]


def formats_json(message, shown, visual):
    """Return UTF-16 ranges matching the web composer's string offsets."""
    raw = message.raw_text or ''
    if not raw or (not visual and shown != raw):
        return []
    return text_format_ranges(raw, getattr(message, 'entities', None) or ())


def translated_content(value):
    text = getattr(value, 'text', '') or ''
    entities = getattr(value, 'entities', None) or ()
    return {'text': text, 'emojis': custom_emoji_spans(text, entities, limit=None),
            'formats': text_format_ranges(text, entities)}


def text_format_ranges(raw, entities):
    from tg_ascii.links import browser_url, message_links
    from tg_ascii.message_tools import entity_spans

    try:
        spans, _emojis = entity_spans(raw, entities)
    except (AttributeError, TypeError, ValueError):
        spans = []
    spans = [span for span in spans if span[2] != 'link']
    for start, end, target in message_links(raw, entities):
        try:
            url = browser_url(target)
        except ValueError:
            continue
        spans.append((start, end, 'link', url))
    if not spans:
        return []
    offsets = [0]
    for character in raw:
        offsets.append(offsets[-1] + (2 if ord(character) > 0xffff else 1))
    return [[offsets[start], offsets[end], style, argument or ''] for start, end, style, argument in spans][:300]


def default_permissions(banned):
    """What members may do by default: {permission: allowed}."""
    from tg_ascii.profile_details import PERMISSIONS
    return {key: allowed for key, _label, allowed in permission_rows(banned, PERMISSIONS, lambda text: text)}


def permission_rows(banned, permissions, tr):
    rows = []
    for key, label in permissions.items():
        blocked = bool(getattr(banned, key, False))
        if key in ('send_plain', 'send_stickers', 'send_gifs', 'send_polls', 'embed_links') and getattr(banned, 'send_messages', False):
            blocked = True
        if key in ('send_photos', 'send_videos', 'send_roundvideos', 'send_audios', 'send_voices', 'send_docs') and getattr(banned, 'send_media', False):
            blocked = True
        rows.append((key, tr(label), not blocked))
    return rows


def share_link(data, usernames):
    """A link that opens this person, group or channel (desktop: profile link)."""
    if usernames:
        return f'https://t.me/{usernames[0]}'
    if data.get('is_user') and data.get('phone'):
        return 'https://t.me/+' + str(data['phone']).lstrip('+')
    if data.get('is_user') and data.get('entity') is not None:
        return f'tg://user?id={data["entity"].id}'
    return data.get('invite_link') or ''


def birthday_text(birthday):
    if birthday is None or not getattr(birthday, 'day', None):
        return ''
    text = f'{birthday.day:02d}/{birthday.month:02d}'
    return text + (f'/{birthday.year}' if getattr(birthday, 'year', None) else '')


def media_dimensions(media):
    """Width and height of a photo/video/sticker (the page reserves its space
    before the preview arrives). (0, 0) when Telegram does not say."""
    try:
        photo = getattr(media, 'photo', None)
        if photo is not None:
            sizes = [size for size in getattr(photo, 'sizes', None) or ()
                     if getattr(size, 'w', 0) and getattr(size, 'h', 0)]
            if sizes:
                largest = max(sizes, key=lambda size: size.w * size.h)
                return int(largest.w), int(largest.h)
        document = getattr(media, 'document', None) or media
        for attribute in getattr(document, 'attributes', None) or ():
            width, height = getattr(attribute, 'w', 0), getattr(attribute, 'h', 0)
            if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
                return width, height
    except Exception:
        pass
    return 0, 0


def audio_json(message):
    """Voice message / audio file details (duration, voice) for the player."""
    if message.media_kind != 'audio':
        document = getattr(message.media, 'document', None)
        if any(type(item).__name__ == 'DocumentAttributeVideo' and getattr(item, 'round_message', False)
               for item in getattr(document, 'attributes', None) or ()):
            return {'round': True}  # video message (circle): can be transcribed
        return {}
    document = getattr(message.media, 'document', None)
    for attribute in getattr(document, 'attributes', None) or ():
        if type(attribute).__name__ == 'DocumentAttributeAudio':
            return {'voice': bool(getattr(attribute, 'voice', False)), 'duration': int(getattr(attribute, 'duration', 0) or 0),
                    'performer': getattr(attribute, 'performer', None), 'title': getattr(attribute, 'title', None)}
    return {}


def poll_attachment_kind(media):
    from telethon.tl import types

    if isinstance(media, types.MessageMediaPhoto):
        return 'photo'
    if isinstance(media, types.MessageMediaDocument) and getattr(media.document, 'mime_type', '') == 'video/mp4':
        return 'video'
    return None


def poll_json(media):
    """A poll in a message: question, answers with votes and the options to vote."""
    import base64
    poll = getattr(media, 'poll', None)
    if poll is None or type(media).__name__ != 'MessageMediaPoll':
        return None
    results = {bytes(item.option): item for item in (getattr(media.results, 'results', None) or [])}
    total = getattr(media.results, 'total_voters', 0) or 0
    answers = []
    for answer in poll.answers:
        result = results.get(bytes(answer.option))
        answers.append({'option': base64.b64encode(bytes(answer.option)).decode(), 'text': str(_text(answer.text)),
                        'voters': getattr(result, 'voters', 0) or 0, 'chosen': bool(getattr(result, 'chosen', False)),
                        'correct': bool(getattr(result, 'correct', False))})
    return {'question': str(_text(poll.question)), 'answers': answers, 'total': total, 'closed': bool(poll.closed),
            'multiple': bool(poll.multiple_choice), 'quiz': bool(poll.quiz),
            'revoting': not (poll.quiz or poll.revoting_disabled), 'open_answers': bool(poll.open_answers),
            'hidden_results': bool(poll.hide_results_until_close), 'shuffle': bool(poll.shuffle_answers),
            'creator': bool(poll.creator), 'solution': getattr(media.results, 'solution', None) or '',
            'attached_media': poll_attachment_kind(media.attached_media),
            'solution_media': poll_attachment_kind(media.results.solution_media),
            'voted': any(item['chosen'] for item in answers)}


def keyboard_json(markup):
    """Bot buttons: inline keyboards under a message (rows of buttons)."""
    from tg_ascii.bot_buttons import button_action, button_supported
    rows = getattr(markup, 'rows', None)
    if not rows or type(markup).__name__ != 'ReplyInlineMarkup':
        return None
    result = []
    for r, row in enumerate(rows):
        line = []
        for c, button in enumerate(row.buttons):
            kind, _action = button_action(button)
            line.append({'text': str(getattr(button, 'text', '')), 'kind': kind or '', 'row': r, 'column': c,
                         'signature': bytes(button).hex(), 'supported': bool(button_supported(button))})
        result.append(line)
    return result


def scheduled_at(value):
    """ISO time chosen in the page (local time, 'YYYY-MM-DDTHH:MM') -> outbox
    schedule string, or None to send now. Telegram needs it in the future."""
    if not value:
        return None
    from datetime import datetime, timedelta
    moment = datetime.fromisoformat(str(value))
    if moment.tzinfo is None:
        moment = moment.astimezone()
    if moment <= datetime.now().astimezone() + timedelta(seconds=30):
        raise ValueError('The scheduled time must be in the future.')
    return moment.isoformat()


def preview_text(message):
    """Chat list summary: '[Photo] caption' instead of the file line."""
    from tg_ascii.i18n import tr
    labels = {'image': '[Photo]', 'video': '[Video]', 'sticker': 'Sticker', 'audio': '[Audio]', 'file': 'File'}
    kind = getattr(message, 'media_kind', '')
    if kind in labels and getattr(message, 'media', None) is not None:
        label = tr('Voice message') if kind == 'audio' and audio_json(message).get('voice') else tr(labels[kind])
        if not label.startswith('['):
            label = f'[{label}]'
        if kind == 'file' and getattr(message, 'filename', ''):
            label += ' ' + message.filename
        caption = getattr(message, 'raw_text', '') or ''
        return (label + ' ' + caption).strip()
    return getattr(message, 'text', '') or ''


def qr_svg(url):
    import qrcode
    import qrcode.image.svg
    image = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    return image.to_string(encoding='unicode')
