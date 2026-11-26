"""Actions made without a connection wait in the app and are sent later (1.5.3).

Messages typed while offline already wait in the outbox (1.4.1). This module
does the same for everything else the interface sends to Telegram: reactions,
edits, deletions, pins, mute/archive/read, folders, polls, privacy, profile
changes, forwards, stickers, …

How it works:

* The Telegram methods listed in ``DEFERRABLE`` are wrapped once. When the
  account is offline (or the request fails because the connection dropped),
  the call is stored instead of failing and the wrapper returns ``Queued``.
* ``Desktop.call`` sees ``Queued``: the interface is unlocked at once, chat
  list changes (archive, mute, pin, unread) are applied locally and actions
  whose result is not needed finish right away. The rest finish when
  Telegram answers, with the real result.
* When Recovery reports the account online again, the queue is replayed in
  order. Requests that create messages (forwards, stickers, polls, …) reuse
  the same ``random_id`` values on every attempt, so Telegram never posts one
  twice. Repeated changes to the same thing keep only the last one (marking a
  chat read ten times sends one request).
* Telegram refusals are not retried: the action is dropped and the user is
  told which one could not be applied.
* The queue is saved to ``<data>/pending-actions/<account>.json`` (0600) so it
  survives a restart; values that cannot be stored stay in memory only.
"""
import asyncio
import contextvars
from dataclasses import dataclass, field
import functools
import itertools
import json
import os
from pathlib import Path
import time

from .tl_codec import decode, encode, Unsupported

DIRECTORY = 'pending-actions'

# method -> number of leading arguments that identify "the same thing".
# None: every call is kept (they do not replace each other).
DEFERRABLE = {
    # chats
    'archive_chat': 1, 'mute_chat': 1, 'pin': 1, 'pin_in_folder': 2, 'set_chat_unread': 1,
    'mark_read': 1, 'read_discussion': 2, 'save_draft': 1, 'set_chat_theme': 1,
    'clear_chat': None, 'delete_chat': 1, 'join_chat': 1, 'leave_chat': 1, 'join_invite': 1,
    'folder_membership': None,
    # messages
    'react': 2, 'delete_message': None, 'delete_selected_messages': None, 'edit_existing': 2,
    'pin_message': 2, 'change_scheduled': 2, 'vote_poll': 2, 'close_poll': 2, 'toggle_checklist': 3,
    'edit_location': 2, 'edit_checklist': 2, 'edit_article': 2,
    # new messages (exactly once thanks to random_id)
    'forward_message': None, 'forward_selected_messages': None, 'send_sticker': None,
    'send_location': None, 'send_poll': None, 'send_contact_card': None, 'send_checklist': None,
    'send_article': None,
    # contacts and profiles
    'save_contact': 1, 'add_contact': None, 'profile_delete_contact': 1, 'profile_block': 1,
    'profile_notify': None, 'profile_change': None, 'update_profile': 0, 'update_username': 0,
    'set_profile_tab': 0,
    # settings
    'save_notification_settings': 1, 'save_privacy': 1, 'save_global_privacy': None,
    # folders and stickers
    'mark_folder_read': None, 'save_folder': None, 'delete_folder': 1, 'reorder_folders': 0,
    'reorder_folder_pins': 1, 'toggle_folder_tags': 0, 'install_pack': None,
}
CREATES_MESSAGES = {'forward_message', 'forward_selected_messages', 'send_sticker', 'send_location',
                    'send_poll', 'send_contact_card', 'send_checklist', 'send_article'}
# Callers ignore the value: finish at once instead of waiting for Telegram.
FINISH_NOW = {'archive_chat', 'mute_chat', 'pin', 'pin_in_folder', 'set_chat_unread', 'mark_read',
              'read_discussion', 'save_draft', 'folder_membership', 'delete_message',
              'delete_selected_messages', 'delete_chat', 'forward_message', 'forward_selected_messages',
              'profile_notify', 'save_global_privacy', 'change_scheduled', 'reorder_folder_pins',
              'pin_message', 'join_chat', 'leave_chat', 'set_chat_theme', 'toggle_folder_tags',
              'reorder_folders', 'mark_folder_read', 'save_notification_settings', 'set_profile_tab'}
LABELS = {
    'archive_chat': 'Archive', 'mute_chat': 'Mute', 'pin': 'Fijar / Desfijar', 'pin_in_folder': 'Fijar / Desfijar',
    'set_chat_unread': 'Mark as unread', 'mark_read': 'Mark as read', 'read_discussion': 'Mark as read',
    'save_draft': 'Draft', 'set_chat_theme': 'Chat theme', 'clear_chat': 'Clear history',
    'delete_chat': 'Delete chat', 'join_chat': 'Unirse', 'leave_chat': 'Leave',
    'join_invite': 'Unirse', 'folder_membership': 'Add to folder', 'react': 'Reactions',
    'delete_message': 'Delete message', 'delete_selected_messages': 'Delete message',
    'edit_existing': 'Edit message', 'pin_message': 'Pinned messages', 'change_scheduled': 'Scheduled messages',
    'vote_poll': 'Vote', 'close_poll': 'Close poll', 'toggle_checklist': 'Checklist', 'edit_location': 'Location',
    'edit_checklist': 'Checklist', 'edit_article': 'Artículo', 'forward_message': 'Forward',
    'forward_selected_messages': 'Forward', 'send_sticker': 'Sticker', 'send_location': 'Location',
    'send_poll': 'Poll', 'send_contact_card': 'Share contact', 'send_checklist': 'Checklist',
    'send_article': 'Send article', 'save_contact': 'Save contact', 'add_contact': 'Add contact',
    'profile_delete_contact': 'Delete contact', 'profile_block': 'Block', 'profile_notify': 'Notifications',
    'profile_change': 'Profile', 'update_profile': 'Profile', 'update_username': 'Username',
    'set_profile_tab': 'Profile', 'save_notification_settings': 'Notifications', 'save_privacy': 'Privacy',
    'save_global_privacy': 'Privacy', 'mark_folder_read': 'Mark folder as read', 'save_folder': 'Folders',
    'delete_folder': 'Delete folder', 'reorder_folders': 'Folders', 'reorder_folder_pins': 'Folders',
    'toggle_folder_tags': 'Folders', 'install_pack': 'Stickers',
}

_REPLAYING = contextvars.ContextVar('tg_ascii_pending_replay', default=False)
_sequence = itertools.count(1)
_originals = {}
_installed = False


class Queued:
    """Returned instead of Telegram's answer when an action was stored."""
    def __init__(self, record):
        self.record = record

    def __bool__(self):
        return False

    def __repr__(self):
        return f'<Queued {self.record.method}>'


@dataclass
class Record:
    method: str
    args: list
    kwargs: dict
    random_ids: list = field(default_factory=list)
    created: float = field(default_factory=time.time)
    error: str = ''
    key: int = field(default_factory=lambda: next(_sequence))
    persist: bool = True
    callbacks: list = field(default_factory=list, repr=False)

    def reserve_ids(self):
        if self.method not in CREATES_MESSAGES:
            return False
        values = self.args[1] if len(self.args) > 1 else self.kwargs.get('identifiers', ())
        count = max(1, len(values)) if self.method == 'forward_selected_messages' else 1
        changed = len(self.random_ids) < count
        while len(self.random_ids) < count:
            self.random_ids.append(int.from_bytes(os.urandom(8), 'big', signed=True))
        return changed

    def scope(self):
        width = DEFERRABLE.get(self.method)
        if width is None:
            return None
        return (self.method, tuple(repr(value) for value in self.args[:width]))

    def peer(self):
        value = self.args[0] if self.args else None
        return value if isinstance(value, int) and not isinstance(value, bool) else None


def transport_failure(error):
    if isinstance(error, (ConnectionError, OSError, TimeoutError, asyncio.TimeoutError)):
        return True
    return type(error).__name__ == 'TransportReset'


def install():
    """Wrap the deferrable Telegram methods (once per process)."""
    global _installed
    if _installed:
        return
    from . import outbox
    outbox.install()
    _patch_forward_ids()
    from .backend import TelegramBackend
    for name in DEFERRABLE:
        original = getattr(TelegramBackend, name, None)
        if original is None or name in _originals:
            continue
        _originals[name] = original
        setattr(TelegramBackend, name, _wrap(name, original))
    _installed = True


def _patch_forward_ids():
    """Forwards carry one random_id per message: reuse them on every attempt."""
    from telethon.tl import functions
    from .outbox import _IDS
    cls = functions.messages.ForwardMessagesRequest
    if getattr(cls, '_tg_pending_ids', False):
        return
    original = cls.__init__

    def patched(self, *args, __original=original, **kwargs):
        __original(self, *args, **kwargs)
        ids = _IDS.get()
        if ids is not None and kwargs.get('random_id') is None:
            self.random_id = [ids.next() for _ in self.id]
    cls.__init__ = patched
    cls._tg_pending_ids = True


def _wrap(name, original):
    @functools.wraps(original)
    async def deferred(self, *args, **kwargs):
        queue = getattr(self, 'pending_actions', None)
        if queue is None or _REPLAYING.get():
            return await original(self, *args, **kwargs)
        if queue.offline():
            return Queued(queue.add(name, args, kwargs))
        random_ids = []
        try:
            if name in CREATES_MESSAGES:
                from .outbox import with_random_ids
                return await with_random_ids(random_ids, original(self, *args, **kwargs))
            return await original(self, *args, **kwargs)
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise  # Cancelled by the caller (timeout, window closed): not ours to resend.
            return Queued(queue.add(name, args, kwargs, random_ids))  # Connection reset mid-request.
        except Exception as error:
            if not transport_failure(error):
                raise
            return Queued(queue.add(name, args, kwargs, random_ids))
    deferred._tg_pending = name
    return deferred


class PendingActions:
    """One per signed-in account; lives on the worker thread's event loop."""

    def __init__(self, service, account):
        self.service = service
        self.account = account
        self.records = []
        self.lock = asyncio.Lock()
        self.path = Path(service.root) / DIRECTORY / f'{account}.json'
        self.load()

    # -- state ---------------------------------------------------------------
    def offline(self):
        client = getattr(self.service, 'client', None)
        recovery = getattr(self.service, 'recovery', None)
        if client is None or recovery is None:
            return True
        try:
            connected = client.is_connected()
        except Exception:
            connected = False
        return not connected or recovery.state != 'online'

    def add(self, method, args, kwargs, random_ids=None):
        previous = list(self.records)
        record = Record(method, list(args), dict(kwargs), list(random_ids or []))
        record.reserve_ids()
        scope = record.scope()
        if scope is not None:
            for old in [item for item in self.records if item.scope() == scope]:
                # The newest change wins; whoever waited for the old one gets the new answer.
                record.callbacks.extend(old.callbacks)
                self.records.remove(old)
        try:
            encode(record.args), encode(record.kwargs)
        except Unsupported:
            record.persist = False
        self.records.append(record)
        try:
            self.save(require_persistence=record.persist)
        except Exception:
            self.records = previous
            raise
        self.notify()
        return record

    def cancel(self, key):
        record = next((item for item in self.records if item.key == key), None)
        if record is not None:
            self.records.remove(record)
            self.save()
            self.notify()
        return record

    def clear(self):
        self.records = []
        self.save()
        self.notify()

    def notify(self, **extra):
        callback = getattr(self.service, 'on_change', None)
        if callback is not None:
            try:
                callback('pending', {'count': len(self.records), **extra})
            except Exception:
                pass

    # -- persistence ----------------------------------------------------------
    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        for raw in data if isinstance(data, list) else []:
            try:
                if raw.get('method') not in DEFERRABLE:
                    continue
                self.records.append(Record(raw['method'], list(decode(raw.get('args') or [])),
                                           dict(decode(raw.get('kwargs') or {})),
                                           [int(value) for value in raw.get('random_ids') or []],
                                           float(raw.get('created') or time.time())))
            except Exception:
                continue

    def save(self, *, require_persistence=False):
        records = []
        for record in self.records:
            if not record.persist:
                continue
            try:
                records.append({'method': record.method, 'args': encode(record.args), 'kwargs': encode(record.kwargs),
                                'random_ids': record.random_ids, 'created': record.created})
            except Unsupported:
                continue
        try:
            if not records:
                self.path.unlink(missing_ok=True)
                return
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = self.path.with_suffix('.tmp')
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(records, stream, ensure_ascii=False)
            os.replace(temporary, self.path)
        except (OSError, TypeError, ValueError) as exc:
            from .recovery import record_failure
            record_failure(self.service.root, 'pending_actions', exc)
            if require_persistence:
                raise

    # -- replay ---------------------------------------------------------------
    async def flush(self):
        """Send everything in order; stop at the first connection problem."""
        if not self.records or self.lock.locked():
            return
        async with self.lock:
            from telethon import errors
            from .outbox import with_random_ids
            backend = getattr(self.service, 'backend', None)
            while self.records and backend is not None and not self.offline():
                record = self.records[0]
                method = getattr(type(backend), record.method, None)
                original = getattr(method, '__wrapped__', method)
                if original is None:
                    self.records.pop(0)
                    continue
                token = _REPLAYING.set(True)
                try:
                    if record.method in CREATES_MESSAGES:
                        record.reserve_ids()
                        self.save(require_persistence=True)
                    operation = original(backend, *record.args, **record.kwargs)
                    if record.method in CREATES_MESSAGES:
                        operation = with_random_ids(record.random_ids, operation)
                    result = await asyncio.wait_for(operation, 60)
                except asyncio.CancelledError:
                    task = asyncio.current_task()
                    if task is not None and task.cancelling():
                        raise
                    break  # Connection reset: keep it for the next time.
                except errors.FloodWaitError as error:
                    await asyncio.sleep(min(60, max(1, error.seconds)))
                    continue
                except errors.RandomIdDuplicateError:
                    result = None  # An earlier attempt already reached Telegram.
                except Exception as error:
                    if transport_failure(error):
                        break
                    from .auth import error_message
                    if record not in self.records:
                        continue  # Cancelled/replaced while this RPC was running.
                    self.records.remove(record)
                    self.save()
                    self._answer(record, error, failed=True)
                    self.notify(failed=(record.method, error_message(error)))
                    continue
                finally:
                    _REPLAYING.reset(token)
                if record not in self.records:
                    continue  # Replacement owns the transferred callbacks.
                self.records.remove(record)
                self.save()
                self._answer(record, result)
                self.notify(done=record.method)

    def _answer(self, record, value, failed=False):
        for callback in record.callbacks:
            try:
                callback(value, failed)
            except Exception:
                pass


def attach(service, account):
    """Give a freshly signed-in service its queue (and wrap methods once)."""
    install()
    backend = getattr(service, 'backend', None)
    if backend is None or getattr(backend, 'demo', False):
        return None
    queue = getattr(service, 'pending', None)
    if queue is None or queue.account != account:
        queue = PendingActions(service, account)
        service.pending = queue
    backend.pending_actions = queue
    return queue


def purge(root, account=None):
    import shutil
    folder = Path(root) / DIRECTORY
    try:
        if account is None:
            shutil.rmtree(folder, ignore_errors=True)
        else:
            (folder / f'{account}.json').unlink(missing_ok=True)
    except OSError:
        pass


# -- interface side ------------------------------------------------------------
def local_effects(app, record):
    """Show chat list changes at once, as if Telegram had already answered."""
    if record.method not in ('archive_chat', 'mute_chat', 'pin', 'set_chat_unread'):
        return
    peer = record.peer()
    chat = next((item for item in getattr(app, 'chats', ()) if item.id == peer), None)
    if chat is None or len(record.args) < 2:
        return
    value = bool(record.args[1])
    if record.method == 'archive_chat':
        chat.archived = value
    elif record.method == 'mute_chat':
        chat.muted = value
    elif record.method == 'pin':
        chat.pinned = value
    else:
        chat.unread_mark = value
    try:
        app.render_chats()
    except Exception:
        pass
    from .offline_store import schedule_save
    schedule_save(app)


def handle(app, value, success, failure=None):
    """Desktop.call / window calls: True if ``value`` was a stored action."""
    if not isinstance(value, Queued):
        return False
    record = value.record
    from .i18n import tr
    try:
        app.status.set(tr('◷ Saved offline: it will be sent when the connection returns.'))
    except Exception:
        pass
    # Main window (for the chat list), whether called from it, a linked
    # window or a single-chat window.
    main = getattr(app, '_linked_owner', None) or getattr(app, 'app', None) or app
    if record.method in FINISH_NOW:
        local_effects(main, record)
        success(value)
        return True
    events = app.worker.events
    show = failure or getattr(app, 'show_error', None)
    if show is None:
        from .auth import error_message
        show = lambda error: app.status.set(error_message(error))

    def answered(result, failed):
        events.put((show, result) if failed else (success, result))
    record.callbacks.append(answered)
    return True


def queue_for(app, account=None):
    owner = getattr(app, '_linked_owner', None) or app
    account = owner.ui_account if account is None else account
    service = getattr(owner.service, 'services', {}).get(account) if hasattr(owner.service, 'services') else owner.service
    return getattr(service, 'pending', None)


def install_indicator(app):
    """A '◷ N' button next to the status bar while something waits."""
    from tkinter import ttk
    button = ttk.Button(app.root, text='', command=lambda: show_menu(app))
    app.pending_button = button
    return button


def update_indicator(app):
    button = getattr(app, 'pending_button', None)
    if button is None:
        return
    queue = queue_for(app)
    count = len(queue.records) if queue is not None else 0
    try:
        if not button.winfo_exists():
            return
        if count:
            from .i18n import tr
            button.configure(text='◷ ' + tr('{count} pending, sent when the connection returns').format(count=count))
            if not button.winfo_ismapped():
                button.pack(anchor='e', padx=8, before=app.status_label)
        elif button.winfo_ismapped():
            button.pack_forget()
    except Exception:
        pass


def describe(app, record):
    from .i18n import tr
    label = tr(LABELS.get(record.method, record.method))
    peer = record.peer()
    chat = next((item for item in getattr(app, 'chats', ()) if item.id == peer), None) if peer is not None else None
    return f'{label} · {chat.name}' if chat is not None else label


def show_menu(app):
    from .app_dialogs import popup_menu
    from .i18n import tr
    queue = queue_for(app)
    if queue is None or not queue.records:
        update_indicator(app)
        return
    owner = getattr(app, '_linked_owner', None) or app
    loop = owner.worker.loop

    def send_now():
        owner.worker.submit(_send_now(owner, queue), lambda _: None, lambda _: None)

    def cancel(key):
        loop.call_soon_threadsafe(queue.cancel, key)
    entries = [(tr('Try to send now'), send_now), None]
    for record in list(queue.records)[:30]:
        entries.append(('✕ ' + tr('Cancel') + ': ' + describe(owner, record), lambda key=record.key: cancel(key)))
    popup_menu(app.root, entries, anchor=getattr(app, 'pending_button', None))


async def _send_now(app, queue):
    try:
        recovery = getattr(queue.service, 'recovery', None)
        if recovery is not None:
            await recovery.ensure()
    except Exception:
        pass
    await queue.flush()


def on_change(app, account, payload):
    """Desktop.account_change for kind 'pending'."""
    if account != getattr(app, 'ui_account', None):
        return
    update_indicator(app)
    from .i18n import tr
    failed = payload.get('failed') if isinstance(payload, dict) else None
    if failed:
        method, message = failed
        app.status.set(tr('Could not apply "{action}": {reason}').format(action=tr(LABELS.get(method, method)), reason=message))
    elif isinstance(payload, dict) and payload.get('done') and not payload.get('count'):
        app.status.set(tr('Everything made offline has been sent.'))
        # One refresh once the whole queue is out, to show Telegram's state.
        job = getattr(app, '_pending_refresh_job', None)
        if job is None and hasattr(app, 'refresh') and not getattr(app, '_chat_only', False):
            def run():
                app._pending_refresh_job = None
                if not getattr(app, 'closed', False):
                    app.refresh()
            app._pending_refresh_job = app.root.after(800, run)
