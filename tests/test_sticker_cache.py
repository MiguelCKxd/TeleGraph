import asyncio
import gzip
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from tg_ascii_mobile.core import Core


class StickerCacheTests(IsolatedAsyncioTestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.core = Core(self.root, 'Android')
        self.addCleanup(self.core.loop.close)
        self.doc = SimpleNamespace(id=19, mime_type='application/x-tgsticker', size=74, thumbs=[1])
        self.backend = SimpleNamespace(client=SimpleNamespace(download_media=AsyncMock()),
                                       custom_emoji_documents=AsyncMock(return_value=[self.doc]))
        self.core.accounts = SimpleNamespace(current='test', services={'test': SimpleNamespace(backend=self.backend)})

    async def test_parallel_animation_and_thumbnail_requests_reuse_document_and_downloads(self):
        async def download(document, file, thumb=None):
            await asyncio.sleep(0)
            if file is bytes:
                return gzip.compress(b'{"frames":2}')
            self.assertEqual(thumb, -1)
            file.write(b'thumbnail')
            return file

        self.backend.client.download_media.side_effect = download
        requests = [method(self.doc.id) for _ in range(20)
                    for method in (self.core.sticker_file, self.core.sticker_animation)]
        paths = await asyncio.gather(*requests)
        self.assertEqual({path.read_bytes() for path in paths}, {b'thumbnail', b'{"frames":2}'})
        self.assertEqual(self.backend.client.download_media.await_count, 2)
        self.backend.custom_emoji_documents.assert_awaited_once_with([19])
        self.assertEqual(len(self.core._sticker_locks), 0)
        self.core.accounts = None
        self.assertEqual(paths[0], await self.core.sticker_file(19))
        self.assertEqual(paths[1], await self.core.sticker_animation(19))

    async def test_cached_thumbnail_can_be_read_during_a_video_download(self):
        folder = self.root / 'mobile-stickers'
        folder.mkdir()
        still = folder / '19.webp'
        still.write_bytes(b'old thumbnail')
        self.doc.mime_type = 'video/webm'
        entered, release = asyncio.Event(), asyncio.Event()

        async def download(document, file, thumb=None):
            entered.set()
            await release.wait()
            file.write(b'video')
            return file

        self.backend.client.download_media.side_effect = download
        task = asyncio.create_task(self.core.sticker_animation(19))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            self.assertEqual(await asyncio.wait_for(self.core.sticker_file(19), 1), still)
        finally:
            release.set()
        self.assertEqual((await task).read_bytes(), b'video')

    async def test_cancelled_static_download_is_never_served_and_can_retry(self):
        entered = asyncio.Event()
        self.doc.mime_type = 'image/webp'

        async def interrupted(document, file, thumb=None):
            file.write(b'partial')
            file.flush()
            entered.set()
            await asyncio.Event().wait()

        async def complete(document, file, thumb=None):
            file.write(b'complete')
            return file

        client = self.backend.client
        client.download_media.side_effect = interrupted
        task = asyncio.create_task(self.core.sticker_file(19))
        await asyncio.wait_for(entered.wait(), 1)
        folder = self.root / 'mobile-stickers'
        self.assertFalse((folder / '19.webp').exists())
        concurrent = asyncio.create_task(self.core.sticker_file(19))
        client.download_media.side_effect = complete
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        result = await asyncio.wait_for(concurrent, 1)
        self.assertEqual(list(folder.iterdir()), [result])
        self.assertEqual(result.read_bytes(), b'complete')
        self.assertIsNone(await self.core.sticker_animation(19))
        self.core.accounts = None
        self.assertIsNone(await self.core.sticker_animation(19))

    async def test_cache_size_and_clear_include_assets_and_preserve_user_data(self):
        for name in ('mobile-stickers', 'mobile-media', 'mobile-avatars', 'media-cache', 'offline-cache',
                     'mobile-outgoing', 'designs'):
            folder = self.root / name
            folder.mkdir()
            (folder / 'data').write_bytes(b'abc')
        for name in ('translations-test.sqlite3', 'drafts.json'):
            (self.root / name).write_bytes(b'preserved')
        self.assertEqual(await self.core.api_cache_size(), '15 B')
        self.assertEqual(await self.core.api_clear_cache(), '15 B')
        self.assertEqual(await self.core.api_cache_size(), '0 B')
        for name in ('mobile-outgoing/data', 'designs/data', 'translations-test.sqlite3', 'drafts.json'):
            self.assertTrue((self.root / name).read_bytes())
