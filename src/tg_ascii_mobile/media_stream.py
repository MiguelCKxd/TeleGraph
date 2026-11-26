"""Bounded, account-scoped byte ranges for the WebView's video player.

Only the requested original Telegram document blocks are read. The cache is
small and in memory: a video need not occupy its full size on disk to start or
seek. Saving/sharing continues to use the atomic full-file downloader.
"""
import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
import time

from telethon import errors, types
from tg_ascii.media_cache import has_expiry
from .media_lifetime import expiry_date

BLOCK_SIZE = 512 * 1024
CACHE_BLOCKS = 8  # 4 MiB across all players/accounts, not per document.
MAX_VIEWS = 3
MAX_PENDING = 8
IDLE_SECONDS = 30
BLOCK_TIMEOUT = 45


@dataclass(eq=False)
class VideoSource:
    account: str
    backend: object
    peer: int
    ident: int
    document: object
    cacheable: bool
    touched: float = field(default_factory=time.monotonic)
    valid: bool = True
    deadline: float | None = None

    @property
    def size(self):
        return self.document.size

    @property
    def mime(self):
        return self.document.mime_type


class VideoRanges:
    def __init__(self, core):
        self.core = core
        self.views = OrderedDict()
        self.blocks = OrderedDict()
        self.pending = {}
        self.waiters = {}
        self.slots = asyncio.Semaphore(2)
        self.source_lock = asyncio.Lock()
        self.expiry = None

    def current(self, source):
        return (source.valid and (source.deadline is None or time.time() < source.deadline)
                and not self.core.locked and self.core.account == source.account
                and self.core.backend is source.backend)

    def check(self, source):
        if not self.current(source):
            self.drop(source)
            raise PermissionError('The active account changed.')

    def drop(self, source):
        source.valid = False
        for key, value in list(self.views.items()):
            if value is source:
                del self.views[key]
        self.forget_blocks(source)
        for key, task in list(self.pending.items()):
            if key[0] is source:
                task.cancel()
                del self.pending[key]

    def revoke(self, account, peer, identifiers):
        for source in list(self.views.values()):
            if source.account == account and (peer is None or source.peer == peer) and source.ident in identifiers:
                self.drop(source)

    def forget_blocks(self, source):
        for key in list(self.blocks):
            if key[0] is source:
                del self.blocks[key]

    def prune(self):
        self.expiry = None
        cutoff = time.monotonic() - IDLE_SECONDS
        for source in list(self.views.values()):
            busy = any(key[0] is source for key in self.pending)
            if (source.touched < cutoff and not busy) or not self.current(source):
                self.drop(source)
        if self.views:
            self.expiry = asyncio.get_running_loop().call_later(IDLE_SECONDS, self.prune)

    def close(self):
        if self.expiry:
            self.expiry.cancel()
            self.expiry = None
        for source in list(self.views.values()):
            self.drop(source)

    async def source(self, peer, ident, view):
        async with self.source_lock:
            return await self.find_source(peer, ident, view)

    async def find_source(self, peer, ident, view):
        account, backend = self.core.account, self.core.backend
        if self.core.locked or backend is None:
            raise PermissionError('The active account changed.')
        for previous in list(self.views.values()):
            if not self.current(previous):
                self.drop(previous)
        key = (account, id(backend), peer, ident, view)
        source = self.views.pop(key, None)
        if source and time.monotonic() - source.touched < IDLE_SECONDS:
            source.touched = time.monotonic()
            self.views[key] = source
            return source
        if source:
            self.drop(source)
        # Resolve the actual current document once for this viewer. A new open
        # does not resurrect an edited/deleted message using old media metadata.
        classify = getattr(self.core, 'media_message', None)
        if classify is None:
            raw = await asyncio.wait_for(self.core._fetch_message(backend, peer, ident), 30)
            protected = bool(getattr(raw, 'noforwards', False))
        else:
            raw, protected = await asyncio.wait_for(
                classify(peer, ident, account, backend, fresh=True), 30)
        if self.core.locked or self.core.account != account or self.core.backend is not backend:
            raise PermissionError('The active account changed.')
        media = getattr(raw, 'media', None)
        document = getattr(media, 'document', None)
        if (not isinstance(document, types.Document) or document.size <= 0
                or not document.mime_type.startswith('video/')):
            return None
        source = VideoSource(account, backend, peer, ident, document,
                             not protected and not has_expiry(raw), deadline=expiry_date(raw))
        self.check(source)
        self.views[key] = source
        while len(self.views) > MAX_VIEWS:
            self.drop(next(iter(self.views.values())))
        if self.expiry is None:
            self.expiry = asyncio.get_running_loop().call_later(IDLE_SECONDS, self.prune)
        return source

    async def block(self, source, number):
        self.check(source)
        source.touched = time.monotonic()
        key = (source, number)
        cached = self.blocks.pop(key, None)
        if cached is not None:
            self.blocks[key] = cached
            return cached
        task = self.pending.get(key)
        if task is None:
            if len(self.pending) >= MAX_PENDING:
                raise ConnectionError('Too many active video reads')
            task = self.pending[key] = asyncio.create_task(self.fetch(source, number))
            def finished(done):
                if self.pending.get(key) is done:
                    self.pending.pop(key, None)
                if not done.cancelled():
                    done.exception()  # a disconnected last reader may no longer await it
            task.add_done_callback(finished)
        self.waiters[key] = self.waiters.get(key, 0) + 1
        try:
            # There may be two WebKit range readers of this block. Cancelling
            # one socket must not cancel the other's read.
            payload = await asyncio.shield(task)
        finally:
            count = self.waiters.get(key, 1) - 1
            if count:
                self.waiters[key] = count
            else:
                self.waiters.pop(key, None)
                if not task.done():
                    task.cancel()
                if self.pending.get(key) is task:
                    self.pending.pop(key, None)
        self.check(source)
        if source.cacheable:
            self.blocks[key] = payload
            self.blocks.move_to_end(key)
            while len(self.blocks) > CACHE_BLOCKS:
                self.blocks.popitem(last=False)
        return payload

    async def fetch(self, source, number):
        offset = number * BLOCK_SIZE
        expected = min(BLOCK_SIZE, source.size - offset)
        if expected <= 0:
            raise ValueError('Invalid media range')
        from tg_ascii.telegram_features import DOWNLOAD_CONCURRENCY
        from tg_ascii.resources import network_slots
        backend = source.backend
        slots = getattr(backend, '_download_slots', None)
        if slots is None:
            slots = backend._download_slots = asyncio.Semaphore(network_slots(DOWNLOAD_CONCURRENCY))
        async with self.slots, slots:
            self.check(source)
            for attempt in range(2):
                iterator = backend.client.iter_download(source.document, offset=offset,
                    request_size=BLOCK_SIZE, chunk_size=BLOCK_SIZE, limit=1, file_size=source.size)
                try:
                    payload = bytes(await asyncio.wait_for(iterator.__anext__(), BLOCK_TIMEOUT))
                    self.check(source)
                    if len(payload) != expected:
                        raise ConnectionError('Incomplete Telegram video block')
                    return payload
                except (errors.FileReferenceExpiredError, errors.FilerefUpgradeNeededError):
                    if attempt:
                        raise
                    raw = await asyncio.wait_for(self.core._fetch_message(backend, source.peer, source.ident), 30)
                    self.check(source)
                    media = getattr(raw, 'media', None)
                    document = getattr(media, 'document', None)
                    if has_expiry(raw):
                        self.drop(source)
                        raise PermissionError('Temporary media cannot reuse this viewer.')
                    if (not isinstance(document, types.Document) or document.id != source.document.id
                            or document.size != source.size or not document.mime_type.startswith('video/')):
                        self.drop(source)
                        raise PermissionError('The video changed.')
                    from .media_lifetime import transient
                    chat = next((chat for chat in getattr(self.core, 'chats', ()) if chat.id == source.peer), None)
                    if transient(raw, chat):
                        source.cacheable = False
                        self.forget_blocks(source)
                    source.document = document
                finally:
                    await iterator.close()
