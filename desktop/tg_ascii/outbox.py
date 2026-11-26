"""Offline-safe send queue (1.4.1).

A message is accepted instantly: the composer is cleared, the message waits in
the chat with a clock (◷) and is delivered when Telegram answers again, as the
official apps do. Nothing in the UI waits for the network.

Exactly-once delivery: every queued message owns the ``random_id`` values of
its Telegram send requests (SendMessage / SendMedia / InputSingleMedia). A
retry reuses the same ids, so if an earlier attempt did reach Telegram the
server rejects the copy with RANDOM_ID_DUPLICATE instead of posting it twice.

Only transport problems (no connection, reset, timeout) are retried
automatically. Telegram refusals (no permission, too long, ...) mark the
message as not sent, with Retry / Edit / Delete, and are never retried alone.
The queue is saved to ``outbox.json`` (0600) so pending messages survive a
restart; attachments are referenced by path, never copied.
"""
import asyncio
import contextvars
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime
import itertools
import json
import os
from pathlib import Path
import time

from telethon import errors

from .i18n import tr

TEXT_TIMEOUT = 25
MAX_BACKOFF = 30
CLOCK = '◷'
FAILED = '⚠'

_IDS = contextvars.ContextVar('tg_ascii_outbox_random_ids', default=None)
_installed = False


class RandomIds:
    """Same ids, same order, on every attempt of one queued message."""
    def __init__(self, values):
        self.values = values
        self.index = 0

    def next(self):
        if self.index >= len(self.values):
            self.values.append(int.from_bytes(os.urandom(8), 'big', signed=True))
        value = self.values[self.index]
        self.index += 1
        return value


def install():
    """Let queued sends choose their random_id; no effect on any other request."""
    global _installed
    if _installed:
        return
    from telethon.tl import functions, types
    for cls in (functions.messages.SendMessageRequest, functions.messages.SendMediaRequest, types.InputSingleMedia):
        original = cls.__init__

        def patched(self, *args, __original=original, **kwargs):
            __original(self, *args, **kwargs)
            ids = _IDS.get()
            if ids is not None and kwargs.get('random_id') is None:
                self.random_id = ids.next()
        cls.__init__ = patched
    _installed = True


async def with_random_ids(values, coroutine):
    token = _IDS.set(RandomIds(values))
    try:
        return await coroutine
    finally:
        _IDS.reset(token)


_sequence = itertools.count(1)


@dataclass
class Pending:
    account: str
    peer: int
    text: str = ''
    paths: list = field(default_factory=list)
    format_spans: list = field(default_factory=list)
    custom_spans: list = field(default_factory=list)
    reply_to: int | None = None
    silent: bool = False
    schedule: str | None = None
    voice: float = 0.0  # seconds; > 0: the one attachment is a voice message (Ogg/Opus)
    random_ids: list = field(default_factory=list)
    created: float = field(default_factory=time.time)
    state: str = 'waiting'  # waiting | sending | failed
    error: str = ''
    attempts: int = 0
    retry_at: float = 0.0
    key: int = field(default_factory=lambda: next(_sequence))
    progress: int = -1
    thread_root: int | None = None
    topic_id: int | None = None
    photo_quality: str | None = None

    def reserve_ids(self):
        """Allocate before persisting, including before the first upload/RPC."""
        count = max(1, len(self.paths))
        changed = len(self.random_ids) < count
        while len(self.random_ids) < count:
            self.random_ids.append(int.from_bytes(os.urandom(8), 'big', signed=True))
        return changed

    def schedule_date(self):
        return datetime.fromisoformat(self.schedule) if self.schedule else None

    def preview(self, limit=90):
        text = ' '.join(self.text.split())
        if self.paths:
            names = ', '.join(Path(item).name for item in self.paths[:3])
            text = f'[{names}{"…" if len(self.paths) > 3 else ""}] ' + text
        return text if len(text) <= limit else text[:limit - 1] + '…'


def transient(error):
    """Retry alone only what says nothing about the message itself."""
    if isinstance(error, errors.FloodWaitError):
        return True
    if isinstance(error, errors.RPCError):
        return isinstance(error, errors.ServerError) and not isinstance(error, errors.RandomIdDuplicateError)
    return isinstance(error, (ConnectionError, TimeoutError, OSError, asyncio.TimeoutError))


def build_operation(backend, item, progress=None, demo=False):
    """The exact backend call Desktop.send used before 1.4.1, from a queued item."""
    paths = [Path(value) for value in item.paths]
    text = item.text
    formats = [tuple(span) for span in item.format_spans]
    custom = [tuple(span) for span in item.custom_spans]
    schedule = item.schedule_date()
    quality={'photo_quality':item.photo_quality} if getattr(item,'photo_quality',None) is not None and not demo else {}
    if item.topic_id is not None:
        return backend.forum_send(item.peer, item.topic_id, text, formats, custom, paths=paths,
                                  reply_to=item.reply_to, progress=progress, silent=item.silent,
                                  schedule=schedule, voice=bool(item.voice), duration=item.voice,
                                  as_photo=bool(len(paths) == 1 and paths[0].suffix.lower() in
                                                ('.jpg', '.jpeg', '.png', '.webp')),**quality)
    if item.voice and len(paths) == 1 and not demo:
        return backend.send_audio(item.peer, paths[0], True, item.voice, reply_to=item.reply_to)
    if len(paths) > 1:
        return backend.send_batch(item.peer, paths, text, formats, custom, progress, reply_to=item.reply_to,
                                  silent=item.silent, schedule=schedule,**quality)
    path = paths[0] if paths else None
    photo = bool(path and path.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp'))
    if not demo and (formats or item.reply_to or photo or item.silent or schedule or (path and quality)):
        return backend.send_formatted(item.peer, text, formats, custom, path, progress if path else None,
                                      reply_to=item.reply_to, as_photo=photo, silent=item.silent, schedule=schedule,**quality)
    if path:
        if custom:
            return backend.send_custom(item.peer, text, custom, path, progress)
        return backend.send_attachment(item.peer, path, progress, caption=text)
    return backend.send_custom(item.peer, text, custom) if custom else backend.send(item.peer, text)


class Outbox:
    """Owned by the main window; every view of the same account shows it."""

    def __init__(self, app):
        install()
        self.app = app
        self.items = []
        self.inflight = {}
        self.listeners = []
        self.timer = None
        self.path = Path(app.service.root) / 'outbox.json' if not app.demo else None
        self.load()

    # -- persistence -------------------------------------------------------
    def load(self):
        if self.path is None or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        known = set(Pending.__dataclass_fields__)
        for raw in data if isinstance(data, list) else []:
            try:
                item = Pending(**{key: value for key, value in raw.items() if key in known and key != 'key'})
            except TypeError:
                continue
            item.state = 'failed' if item.state == 'failed' else 'waiting'
            item.retry_at = 0.0
            item.progress = -1
            self.items.append(item)

    def save(self, *, require_persistence=False):
        if self.path is None:
            return
        try:
            from .secret_chats import is_secret_peer
            records = [{key: value for key, value in asdict(item).items() if key not in ('key', 'progress', 'retry_at')}
                       for item in self.items if not is_secret_peer(item.peer)]
            if not records:
                if self.path.exists():
                    self.path.unlink()
                return
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if require_persistence:
                from .preferences import write_json
                write_json(self.path, records)
                return
            temporary = self.path.with_suffix('.tmp')
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(records, stream, ensure_ascii=False, default=str)
            os.replace(temporary, self.path)
        except (OSError, TypeError, ValueError) as exc:
            from .recovery import record_failure
            record_failure(self.app.service.root, 'outbox', exc)
            if require_persistence:
                raise

    # -- queue -------------------------------------------------------------
    def add(self, item, *, require_persistence=True):
        item.reserve_ids()
        self.items.append(item)
        try:
            if require_persistence:
                self.save(require_persistence=True)
            else:
                self.save()
        except Exception:
            self.items.pop()
            raise
        self.changed(item.account, item.peer)
        self.kick()
        return item

    def pending(self, account, peer):
        return [item for item in self.items if item.account == account and item.peer == peer]

    def remove(self, item):
        if item in self.items:
            self.items.remove(item)
            self.save()
            self.changed(item.account, item.peer)

    def retry(self, item):
        if item in self.items and item.state == 'failed':
            item.state, item.error, item.retry_at, item.attempts = 'waiting', '', 0.0, 0
            self.save()
            self.changed(item.account, item.peer)
            self.kick()

    def changed(self, account, peer):
        for listener in tuple(self.listeners):
            try:
                listener(account, peer)
            except Exception:
                pass

    def subscribe(self, listener):
        self.listeners.append(listener)

    def unsubscribe(self, listener):
        if listener in self.listeners:
            self.listeners.remove(listener)

    # -- delivery ----------------------------------------------------------
    def backend_for(self, account):
        service = self.app.service
        if account not in getattr(service, 'entries', {account: None}):
            return None
        try:
            child = service.service(account) if hasattr(service, 'service') else service
        except Exception:
            return None
        return getattr(child, 'backend', None)

    def offline(self, account):
        return account in (getattr(self.app.service, 'failures', None) or {})

    def kick(self):
        if getattr(self.app, 'closed', False) or getattr(self.app, 'closing', False):
            return
        now = time.monotonic()
        waiting = False
        from .resources import network_slots
        limit = network_slots(4)
        active = Counter(account for account, _ in self.inflight)
        seen, backends = set(), {}
        for item in list(self.items):
            if item.state == 'failed':
                continue
            waiting = True
            scope = (item.account, item.peer)
            if scope in seen:
                continue
            seen.add(scope)
            # One message at a time per chat keeps Telegram order = typing order.
            # Remember the head even when it is waiting for a retry.
            if scope in self.inflight or item.retry_at > now or active[item.account] >= limit:
                continue
            if item.account not in backends:
                backends[item.account] = self.backend_for(item.account)
            backend = backends[item.account]
            if backend is None:
                continue
            self.start(item, backend)
            if scope in self.inflight:
                active[item.account] += 1
        if self.timer is not None:
            try:
                self.app.root.after_cancel(self.timer)
            except Exception:
                pass
            self.timer = None
        if waiting:
            try:
                self.timer = self.app.root.after(2000, self._tick)
            except Exception:
                self.timer = None

    def _tick(self):
        self.timer = None
        self.kick()

    def start(self, item, backend):
        app = self.app
        scope = (item.account, item.peer)
        if item.reserve_ids():
            # Migrate queues written before ids were reserved at enqueue time.
            try:
                self.save(require_persistence=True)
            except (OSError, TypeError, ValueError) as exc:
                from .auth import error_message
                item.state, item.error = 'failed', error_message(exc)
                self.changed(*scope)
                return
        item.state, item.attempts = 'sending', item.attempts + 1
        self.inflight[scope] = item
        self.changed(*scope)

        def progress(sent, total):
            value = min(100, int(sent * 100 / total)) if total else 0
            if value != item.progress:
                item.progress = value
                app.worker.events.put((lambda _: self.changed(*scope), None))

        async def deliver():
            operation = build_operation(backend, item, progress if item.paths else None, demo=app.demo)
            coroutine = with_random_ids(item.random_ids, operation)
            if item.paths:
                return await coroutine  # transfer_timeout already bounds inactivity.
            return await asyncio.wait_for(coroutine, TEXT_TIMEOUT)

        def done(message):
            self.inflight.pop(scope, None)
            self.remove(item)
            if item.schedule is None:
                from .interface_windows import publish_local_message
                for value in message if isinstance(message, list) else [message]:
                    if value is not None:
                        publish_local_message(app, item.account, item.peer, value)
            if getattr(app, 'ui_account', None) == item.account:
                app.status.set(tr('Scheduled messages') if item.schedule else tr('Enviado.'))
            self.kick()

        def failed(error):
            self.inflight.pop(scope, None)
            if item not in self.items:
                return
            if isinstance(error, errors.RandomIdDuplicateError):
                # An earlier attempt reached Telegram: never send it again.
                self.remove(item)
                refresh = getattr(app, 'refresh_open_history', None)
                if refresh is not None:
                    refresh(item.account, item.peer)
                self.kick()
                return
            item.progress = -1
            if transient(error):
                item.state = 'waiting'
                wait = getattr(error, 'seconds', None)
                recently_online = time.monotonic() - getattr(self, 'online_at', -1e9) < 15
                delay = max(1, wait) if wait else 1 if recently_online else min(MAX_BACKOFF, 2 ** min(item.attempts, 5))
                item.retry_at = time.monotonic() + delay
                item.error = ''
                # A silent socket looks connected; ask Recovery to check it now.
                try:
                    app.worker.submit(app.service.recover(item.account), lambda _: self.kick(), lambda _: None)
                except Exception:
                    pass
            else:
                from .auth import error_message
                item.state, item.error = 'failed', error_message(error)
            self.save()
            self.changed(*scope)
            self.kick()

        app.worker.submit(deliver(), done, failed)

    def online(self, account):
        self.online_at = time.monotonic()  # An attempt still failing on the old socket retries at once.
        for item in self.items:
            if item.account == account and item.state == 'waiting':
                item.retry_at = 0.0
        self.kick()
