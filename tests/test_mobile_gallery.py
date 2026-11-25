import asyncio
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from telethon import types
from tg_ascii.backend import Message
from tg_ascii_mobile.core import Core


def photo(ident, video=False):
    return types.Photo(ident, 7, b'ref', datetime.now(timezone.utc), [], 4,
                       video_sizes=[types.VideoSize('v', 640, 480, 15)] if video else [])


class GalleryTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.core = Core(Path(directory.name), 'iOS')
        self.core.loop.close()
        self.core.loop = asyncio.get_running_loop()
        self.backend = SimpleNamespace(client=SimpleNamespace())
        self.core.accounts = SimpleNamespace(current='first', services={
            'first': SimpleNamespace(backend=self.backend), 'second': SimpleNamespace(backend=SimpleNamespace())})

    async def test_profile_history_pages_keep_int64_and_video_type(self):
        large_id = (1 << 60) + 61
        history = AsyncMock(side_effect=[
            ([photo(large_id - n, n == 0) for n in range(20)], 21),
            ([photo(large_id - 20)], 21)])
        with patch('tg_ascii_mobile.gallery.profile_history', history):
            first = await self.core.api_profile_photos(44, 'first')
            last = await self.core.api_profile_photos(44, 'first', first['next'])
        self.assertEqual(first['items'][0], {'id': str(large_id), 'kind': 'video', 'offset': 0})
        self.assertEqual(last, {'items': [{'id': str(large_id - 20), 'kind': 'image', 'offset': 20}], 'next': None})
        self.assertIn(('first', 44, large_id), self.core.gallery_photos)

    async def test_switch_rejects_pending_history_and_foreign_file(self):
        started, resume = asyncio.Event(), asyncio.Event()

        async def history(*args):
            started.set()
            await resume.wait()
            return [photo(81)], 1

        with patch('tg_ascii_mobile.gallery.profile_history', history):
            loading = asyncio.create_task(self.core.api_profile_photos(10, 'first'))
            await started.wait()
            self.core.accounts.current = 'second'
            resume.set()
            with self.assertRaises(PermissionError):
                await loading
        self.assertFalse(getattr(self.core, 'gallery_photos', None))
        with self.assertRaises(PermissionError):
            await self.core.profile_gallery_file(10, 81, 'first', 0)

    async def test_evicted_id_revalidates_page_and_lock_blocks_export(self):
        with patch('tg_ascii_mobile.gallery.profile_history', AsyncMock(return_value=([photo(701)], 21))) as history:
            path = await self.core.profile_gallery_file(44, 700, 'first', 20)
            history.assert_awaited_once_with(self.backend, 44, 20, 20)
            self.assertIsNone(path)
        self.core.locked = True
        with self.assertRaises(PermissionError):
            await self.core.api_open_profile_photo(44, 'first', 'share', 701, 20)

    async def test_export_rechecks_policy_before_downloading(self):
        self.backend.selected_message_policy = AsyncMock(return_value={'copy': False})
        self.core.media_file = AsyncMock()
        with self.assertRaises(PermissionError):
            await self.core.api_open_file(44, 82, 'save', account='first')
        self.core.media_file.assert_not_awaited()

    async def test_switch_during_native_download_blocks_share(self):
        self.backend.selected_message_policy = AsyncMock(return_value={'copy': True})
        self.core.open_file_with_system = AsyncMock()
        async def download(*args):
            self.core.accounts.current = 'second'
            return self.core.root / 'fixture.jpg'
        self.core.media_file = download
        with self.assertRaises(PermissionError):
            await self.core.api_open_file(44, 82, 'share', account='first')
        self.core.open_file_with_system.assert_not_awaited()

    async def test_two_named_ios_exports_release_only_their_own_files(self):
        original = self.core.root / 'media.png'
        original.write_bytes(b'fixture')
        self.core.media_file = AsyncMock(return_value=original)
        self.core.histories[44] = [Message(i, 'First', '', '12:00', filename='image.png') for i in (30, 31)]
        self.backend.selected_message_policy = AsyncMock(return_value={'copy': True})
        presented = []

        def native(action, name, done, *, release):
            presented.append((Path(name), release))
            done(True)

        self.core.native_open = native
        await asyncio.gather(self.core.api_open_file(44, 30, 'share'), self.core.api_open_file(44, 31, 'save'))
        self.assertEqual([p.read_bytes() for p, _ in presented], [b'fixture', b'fixture'])
        self.assertNotEqual(presented[0][0], presented[1][0])
        presented[0][1]()
        await asyncio.sleep(0)
        self.assertFalse(presented[0][0].exists())
        self.assertTrue(presented[1][0].exists())
        presented[1][1]()
        await asyncio.sleep(0)
        self.assertFalse(presented[1][0].exists())
