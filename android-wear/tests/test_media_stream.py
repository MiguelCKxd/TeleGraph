import asyncio
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from telethon import errors, types
from tg_ascii_mobile.media_stream import BLOCK_SIZE, CACHE_BLOCKS, VideoRanges
from tg_ascii_mobile.server import Server


def document(size, ident=123):
    return types.Document(ident, 1, b'file-ref', datetime.now(timezone.utc), 'video/mp4', size, 4, [])


def data(offset, size):
    pattern = bytes(range(256))
    return (pattern * ((size + offset % 256 + 255) // 256))[offset % 256:offset % 256 + size]


class Iterator:
    def __init__(self, client, offset, size):
        self.client, self.offset, self.size = client, offset, size
        self.closed = False
        client.iterators.append(self)

    async def __anext__(self):
        self.client.started.set()
        if self.client.gate:
            await self.client.gate.wait()
        return data(self.offset, min(BLOCK_SIZE, self.size - self.offset))

    async def close(self):
        self.closed = True


class Client:
    def __init__(self):
        self.iterators, self.gate = [], None
        self.started = asyncio.Event()

    def iter_download(self, item, *, offset, request_size, chunk_size, limit, file_size):
        assert request_size == chunk_size == BLOCK_SIZE and limit == 1
        return Iterator(self, offset, file_size)


class VideoRangeTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.client = Client()
        self.backend = SimpleNamespace(client=self.client)
        self.raw = SimpleNamespace(media=types.MessageMediaDocument(document=document(BLOCK_SIZE * 100 + 37)))
        self.core = SimpleNamespace(token='token', account='first', backend=self.backend, locked=False,
            media_folder=lambda: self.folder, _media_index=AsyncMock(return_value={}),
            _fetch_message=AsyncMock(side_effect=lambda *args: self.raw), media_file=AsyncMock(return_value=None))
        self.server = Server(self.core)
        self.port = await self.server.start()
        self.addAsyncCleanup(self.shutdown)

    async def shutdown(self):
        self.server.video_ranges.close()
        self.server.server.close()
        await self.server.server.wait_closed()

    async def connect(self, byte_range='0-1', view='fixture'):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.port)
        request = (f'GET /media?peer=42&id=8&thumb=0&stream={view} HTTP/1.1\r\n'
                   f'Host: 127.0.0.1:{self.port}\r\nX-TG-Token: token\r\nConnection: close\r\n')
        if byte_range is not None:
            request += f'Range: bytes={byte_range}\r\n'
        writer.write((request + '\r\n').encode())
        await writer.drain()
        return reader, writer

    async def request(self, byte_range='0-1', view='fixture'):
        reader, writer = await self.connect(byte_range, view)
        try:
            response = await asyncio.wait_for(reader.read(), 5)
            head, body = response.split(b'\r\n\r\n', 1)
            return head.decode(), body
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_start_and_seek_need_only_requested_original_blocks(self):
        head, body = await self.request()
        self.assertIn('206 Partial Content', head)
        self.assertIn('Content-Type: video/mp4', head)
        self.assertIn(f'Content-Range: bytes 0-1/{self.raw.media.document.size}', head)
        self.assertEqual(body, data(0, 2))
        self.assertEqual(len(self.client.iterators), 1)
        self.core.media_file.assert_not_awaited()
        self.assertTrue(self.client.iterators[0].closed)
        head, body = await self.request(f'{BLOCK_SIZE - 7}-{BLOCK_SIZE + 13}')
        self.assertEqual(body, data(BLOCK_SIZE - 7, 21))
        self.assertEqual(len(self.client.iterators), 2, 'The WebKit probe must be reused')
        head, body = await self.request('-17')
        self.assertEqual(body, data(self.raw.media.document.size - 17, 17))
        self.assertEqual(len(self.client.iterators), 3)
        self.core._fetch_message.assert_awaited_once()

    async def test_invalid_ranges_do_not_download_and_small_full_body_matches(self):
        head, body = await self.request(str(self.raw.media.document.size) + '-')
        self.assertIn('416 Range Not Satisfiable', head)
        self.assertEqual(body, b'')
        self.assertFalse(self.client.iterators)
        head, body = await self.request('-0')
        self.assertIn('416 Range Not Satisfiable', head)
        self.raw.media.document = document(BLOCK_SIZE * 2 + 37, ident=124)
        head, body = await self.request(None, 'small')
        self.assertIn('200 OK', head)
        self.assertEqual(body, data(0, self.raw.media.document.size))
        self.assertEqual(len(self.client.iterators), 3)

    async def test_two_readers_share_a_block_and_one_cancel_does_not_interrupt_the_other(self):
        self.client.gate = asyncio.Event()
        first = asyncio.create_task(self.request('0-8'))
        await self.client.started.wait()
        second = asyncio.create_task(self.request('4-12'))
        for _ in range(100):
            if next(iter(self.server.video_ranges.waiters.values()), 0) == 2:
                break
            await asyncio.sleep(.005)
        self.assertEqual(len(self.client.iterators), 1)
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        self.client.gate.set()
        _, body = await second
        self.assertEqual(body, data(4, 9))
        self.assertEqual(len(self.client.iterators), 1)

    async def test_closed_player_cancels_its_only_remote_read(self):
        self.client.gate = asyncio.Event()
        _, writer = await self.connect()
        await self.client.started.wait()
        writer.close()
        await writer.wait_closed()
        for _ in range(100):
            if self.client.iterators[0].closed:
                break
            await asyncio.sleep(.01)
        self.assertTrue(self.client.iterators[0].closed)
        self.assertFalse(self.server.video_ranges.pending)
        self.assertFalse(self.server.video_ranges.blocks)

    async def test_account_switch_during_fetch_never_returns_video_bytes(self):
        self.client.gate = asyncio.Event()
        pending = asyncio.create_task(self.request())
        await self.client.started.wait()
        self.core.account = 'second'
        self.client.gate.set()
        head, body = await pending
        self.assertIn('403 Forbidden', head)
        self.assertEqual(body, b'account')
        self.assertFalse(self.server.video_ranges.blocks)

    async def test_cache_has_one_global_bound_and_explicit_close_releases_it(self):
        for number in range(CACHE_BLOCKS + 4):
            await self.request(f'{number * BLOCK_SIZE}-{number * BLOCK_SIZE + 1}')
        cache = self.server.video_ranges.blocks
        self.assertEqual(len(cache), CACHE_BLOCKS)
        self.assertEqual(sum(map(len, cache.values())), CACHE_BLOCKS * BLOCK_SIZE)
        for i in range(4):
            await self.request(view=f'view-{i}')
        self.assertLessEqual(len(self.server.video_ranges.views), 3)
        self.assertLessEqual(sum(map(len, cache.values())), CACHE_BLOCKS * BLOCK_SIZE)
        self.server.video_ranges.close()
        self.assertFalse(cache)
        self.assertFalse(self.server.video_ranges.views)

    async def test_cached_original_is_used_without_network_even_offline(self):
        cached = self.folder / '42-8.mp4'
        cached.write_bytes(data(0, 1000))
        self.core._media_index.return_value = {'42-8': cached.name}
        self.core.backend = None
        _, body = await self.request('10-17')
        self.assertEqual(body, data(10, 8))
        self.core._fetch_message.assert_not_awaited()
        self.core.media_file.assert_not_awaited()

    async def test_non_video_keeps_full_file_fallback(self):
        original = self.folder / 'photo.jpg'
        original.write_bytes(b'original')
        self.core.media_file.return_value = original
        self.raw.media = types.MessageMediaDocument(document=document(8))
        self.raw.media.document.mime_type = 'image/png'
        _, body = await self.request('0-7')
        self.assertEqual(body, b'original')
        self.assertFalse(self.client.iterators)
        self.core.media_file.assert_awaited_once_with(42, 8, False)

    async def test_protected_video_is_viewable_without_block_cache(self):
        self.raw.noforwards = True
        _, body = await self.request()
        self.assertEqual(body, data(0, 2))
        self.assertFalse(self.server.video_ranges.blocks)

    async def test_temporary_videos_stream_without_disk_fallback_or_block_retention(self):
        for view in ('selfdestruct', 'autodelete'):
            self.raw.media.ttl_seconds = 10 if view == 'selfdestruct' else None
            self.raw.ttl_period = 60 if view == 'autodelete' else None
            self.raw.date = datetime.now(timezone.utc)
            _, body = await self.request(view=view)
            self.assertEqual(body, data(0, 2))
            self.assertFalse(self.server.video_ranges.blocks)
        self.core.media_file.assert_not_awaited()

    async def test_auto_delete_deadline_and_delete_event_invalidate_already_open_stream(self):
        self.raw.ttl_period = 1
        self.raw.date = datetime.now(timezone.utc)
        source = await self.server.video_ranges.source(42, 8, 'expiry')
        await self.server.video_ranges.block(source, 0)
        source.deadline = 1
        with self.assertRaises(PermissionError):
            await self.server.video_ranges.block(source, 0)
        self.assertFalse(source.valid)
        source = await self.server.video_ranges.source(42, 8, 'delete')
        self.server.video_ranges.revoke('first', 42, [8])
        with self.assertRaises(PermissionError):
            await self.server.video_ranges.block(source, 0)
        self.assertFalse(self.server.video_ranges.views)

    async def test_extensionless_original_has_video_mime_and_preserves_bytes(self):
        cached = self.folder / '42-8'
        cached.write_bytes(b'\x00\x00\x00\x20ftypisom' + b'original-video')
        self.core._media_index.return_value = {'42-8': cached.name}
        head, body = await self.request('4-11')
        self.assertIn('Content-Type: video/mp4', head)
        self.assertEqual(body, b'ftypisom')
        self.core._fetch_message.assert_not_awaited()

    async def test_unsupported_remote_stream_uses_atomic_file_fallback(self):
        original = self.folder / 'fallback.mp4'
        original.write_bytes(b'original-video')
        self.core.media_file.return_value = original
        def unsupported(*args, **kwargs):
            raise RuntimeError('unsupported CDN stream')
        self.client.iter_download = unsupported
        head, body = await self.request('0-7')
        self.assertIn('206 Partial Content', head)
        self.assertEqual(body, b'original')
        self.core.media_file.assert_awaited_once_with(42, 8, False)

    async def test_reference_refresh_rechecks_new_protection_and_purges_blocks(self):
        source = await self.server.video_ranges.source(42, 8, 'refresh')
        await self.server.video_ranges.block(source, 0)
        self.assertTrue(self.server.video_ranges.blocks)
        old = self.client.iter_download
        failed = False
        def refresh(item, **kwargs):
            nonlocal failed
            iterator = old(item, **kwargs)
            if not failed:
                failed = True
                async def expired():
                    raise errors.FileReferenceExpiredError(None)
                iterator.__anext__ = expired
            return iterator
        self.client.iter_download = refresh
        self.raw.noforwards = True
        self.assertEqual(await self.server.video_ranges.block(source, 1), data(BLOCK_SIZE, BLOCK_SIZE))
        self.assertFalse(source.cacheable)
        self.assertFalse(self.server.video_ranges.blocks)
        self.assertTrue(all(item.closed for item in self.client.iterators))

    async def test_reference_refresh_to_temporary_media_blocks_reuse(self):
        source = await self.server.video_ranges.source(42, 8, 'refresh')
        await self.server.video_ranges.block(source, 0)
        old = self.client.iter_download
        def refresh(item, **kwargs):
            iterator = old(item, **kwargs)
            async def expired():
                raise errors.FileReferenceExpiredError(None)
            iterator.__anext__ = expired
            return iterator
        self.client.iter_download = refresh
        self.raw.media.ttl_seconds = 10
        with self.assertRaises(PermissionError):
            await self.server.video_ranges.block(source, 1)
        self.assertFalse(self.server.video_ranges.blocks)
        self.assertFalse(self.server.video_ranges.views)
