"""Seekable original Telegram video bytes for PyAV's decoding thread.

The decoder reads on its own thread; all Telegram work stays on the account's
asyncio loop. Only requested 512 KiB blocks are downloaded, with a 2 MiB LRU
per open viewer. Nothing is written to disk and closing cancels pending reads.
"""
import asyncio
from collections import OrderedDict
from concurrent.futures import CancelledError
from dataclasses import dataclass
import io
import threading
from types import SimpleNamespace

from telethon import errors, types

BLOCK_SIZE = 512 * 1024
CACHE_BLOCKS = 4
READ_TIMEOUT = 45


@dataclass(frozen=True)
class StreamDescriptor:
    backend: object
    loop: object
    peer: int
    ident: int
    document: object
    cacheable: bool = True
    current: object = None


async def describe(backend, peer, ident, media, *, refresh=False):
    from .media_cache import has_expiry
    from .secret_chats import is_secret_peer
    if is_secret_peer(peer) or has_expiry(media):
        return None
    raw = await backend.media_message(peer, ident) if refresh else media
    source = getattr(raw, 'media', None) or raw
    document = getattr(source, 'document', None)
    if (has_expiry(raw) or not isinstance(document, types.Document) or document.size <= 0
            or not document.mime_type.startswith('video/')):
        return None
    return StreamDescriptor(backend, asyncio.get_running_loop(), peer, ident, document,
                            not bool(getattr(raw, 'noforwards', False) or getattr(raw, 'protected', False)))


class TelegramVideoReader(io.RawIOBase):
    def __init__(self, descriptor):
        super().__init__()
        self.descriptor = descriptor
        self.document = descriptor.document
        self.cacheable = descriptor.cacheable
        self.position = 0
        self.blocks = OrderedDict()
        self.stopped = threading.Event()
        self.guard = threading.Lock()
        self.pending = None

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.position

    def check(self):
        current = self.descriptor.current
        if (self.stopped.is_set() or getattr(self.descriptor.backend, '_transfers_closed', False)
                or (current is not None and not current())):
            raise OSError('Video stream closed')

    def seek(self, offset, whence=io.SEEK_SET):
        self.check()
        if whence == io.SEEK_CUR: offset += self.position
        elif whence == io.SEEK_END: offset += self.document.size
        elif whence != io.SEEK_SET: raise ValueError('Invalid seek origin')
        if offset < 0: raise ValueError('Negative video offset')
        self.position = offset
        return offset

    def read(self, size=-1):
        self.check()
        # PyAV supplies small explicit sizes. Bound even an unusual caller's
        # read so a large movie can never become a single in-memory buffer.
        size = min(BLOCK_SIZE, self.document.size - self.position, size if size >= 0 else BLOCK_SIZE)
        if size <= 0: return b''
        result = bytearray()
        while size > 0:
            number, offset = divmod(self.position, BLOCK_SIZE)
            payload = self.blocks.pop(number, None)
            if payload is None:
                operation = self.fetch(number)
                try:
                    future = asyncio.run_coroutine_threadsafe(operation, self.descriptor.loop)
                except Exception:
                    operation.close()
                    raise
                with self.guard:
                    self.pending = future
                    if self.stopped.is_set(): future.cancel()
                try:
                    payload = future.result(READ_TIMEOUT + 35)
                except (TimeoutError, CancelledError) as exc:
                    future.cancel()
                    raise OSError('Video read interrupted') from exc
                except Exception as exc:
                    raise OSError('Unable to read Telegram video') from exc
                finally:
                    with self.guard:
                        self.pending = None
            self.check()
            if self.cacheable:
                self.blocks[number] = payload
                while len(self.blocks) > CACHE_BLOCKS:
                    self.blocks.popitem(last=False)
            count = min(size, len(payload) - offset)
            if count <= 0: raise OSError('Incomplete Telegram video block')
            result.extend(payload[offset:offset + count])
            self.position += count
            size -= count
        return bytes(result)

    def readinto(self, target):
        payload = self.read(len(target))
        target[:len(payload)] = payload
        return len(payload)

    async def fetch(self, number):
        from .flood_control import read_with_flood_wait
        from .resources import network_slots
        from .telegram_features import DOWNLOAD_CONCURRENCY
        from .transfers import transfer_scope
        backend = self.descriptor.backend
        offset = number * BLOCK_SIZE
        expected = min(BLOCK_SIZE, self.document.size - offset)
        slots = getattr(backend, '_download_slots', None)
        if slots is None:
            slots = backend._download_slots = asyncio.Semaphore(network_slots(DOWNLOAD_CONCURRENCY))
        async def attempt():
            self.check()
            async with slots:
                iterator = backend.client.iter_download(self.document, offset=offset, request_size=BLOCK_SIZE,
                    chunk_size=BLOCK_SIZE, limit=1, file_size=self.document.size)
                try:
                    data = bytes(await asyncio.wait_for(iterator.__anext__(), READ_TIMEOUT))
                    self.check()
                    if len(data) != expected: raise OSError('Incomplete Telegram video block')
                    return data
                finally:
                    await iterator.close()
        async with transfer_scope(backend):
            for retry in range(2):
                try:
                    return await read_with_flood_wait(backend, 'download', attempt)
                except (errors.FileReferenceExpiredError, errors.FilerefUpgradeNeededError,
                        errors.FileReferenceInvalidError, errors.FileReferenceEmptyError):
                    if retry: raise
                    raw = await asyncio.wait_for(backend.media_message(self.descriptor.peer, self.descriptor.ident), 30)
                    from .media_cache import has_expiry
                    document = getattr(getattr(raw, 'media', None), 'document', None)
                    if (has_expiry(raw) or not isinstance(document, types.Document)
                            or document.id != self.document.id or document.size != self.document.size):
                        raise OSError('The Telegram video changed')
                    self.document = document
                    if getattr(raw, 'noforwards', False):
                        self.cacheable = False
                        self.blocks.clear()

    def abort(self):
        self.stopped.set()
        with self.guard:
            if self.pending is not None: self.pending.cancel()

    def close(self):
        self.abort()
        self.blocks.clear()
        super().close()


class StreamingFrames:
    """Create/close the decoder on its render thread; abort is thread safe."""
    def __init__(self, descriptor):
        self.reader = TelegramVideoReader(descriptor)
        self.video = None
        self.count = 1
        self.image = SimpleNamespace(info={'duration': 40})

    def viewport(self, size, scale=1):
        if self.video is None:
            from .video_frames import VideoFrames
            self.video = VideoFrames(self.reader)
        self.video.viewport(size, scale)

    def get(self, index):
        result = self.video.get(index)
        self.count, self.image = self.video.count, self.video.image
        return result

    def abort(self): self.reader.abort()

    def close(self):
        self.reader.abort()
        try:
            if self.video is not None: self.video.close()
        finally:
            self.reader.close()
