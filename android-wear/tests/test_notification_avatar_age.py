"""Keep-loaded may reuse a photo by ID; notifications must prepare a fresh copy."""
import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

from tg_ascii_mobile.core import AVATAR_ERROR_PAUSE, Core
from tg_ascii_mobile.ios_notice_cache import NoticeCache, PHOTO_LIFETIME


class NotificationAvatarAgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.core = Core(Path(self.directory.name), 'iOS')
        self.core.loop.close()
        self.core.loop = asyncio.get_running_loop()
        self.entity = NS(photo=NS(photo_id=91))
        async def download(peer, *, file, download_big):
            if file is bytes:
                return b'new real photo'
            Path(file).write_bytes(b'new real photo')
            return file
        self.client = NS(download_profile_photo=AsyncMock(side_effect=download), get_entity=AsyncMock(return_value=self.entity))
        self.backend = NS(client=self.client)
        self.core.accounts = NS(current='qa', identities={'qa': 7}, entries={'qa': {}}, services={'qa': NS(backend=self.backend)})
        self.core.prefs = NS(values={'mobile_features': {'keep_loaded': True}})
        self.core.connection = 'online'
        self.core.chats = [NS(id=42, entity=self.entity)]
        self.cache = self.core.ios_notice_cache = NoticeCache(Path(self.directory.name) / 'app-group')
        self.cache.sync(self.core)
        self.source = self.core.root / 'mobile-avatars/qa/42.jpg'
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b'old viewer photo')
        self.source.with_suffix('.id').write_text('91')
        self.old_time = time.time() - PHOTO_LIFETIME - 86400
        os.utime(self.source, (self.old_time, self.old_time))
        self.shared = self.cache.root / '7/42.jpg'

    async def asyncTearDown(self):
        self.cache.close()
        await self.finish()

    def after_pause(self):
        """A later request, once the bounded failure pause has elapsed."""
        later = time.monotonic() + AVATAR_ERROR_PAUSE + 1
        return patch('tg_ascii_mobile.core.avatar_clock', return_value=later)

    async def finish(self):
        await asyncio.gather(*tuple(self.cache.jobs.values()), return_exceptions=True)

    async def block_download(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def slow(*args, **kwargs):
            started.set()
            await release.wait()
            return b'new real photo'
        self.client.download_profile_photo.side_effect = slow
        return started, release

    async def test_old_viewer_copy_prepares_future_notice_without_waiting_or_retouching(self):
        started, release = await self.block_download()
        path = await asyncio.wait_for(self.core.avatar_file(42), .5)
        await asyncio.wait_for(started.wait(), .5)
        self.assertEqual(path, self.source)
        self.assertAlmostEqual(path.stat().st_mtime, self.old_time, places=4)
        self.assertFalse(self.shared.exists())
        release.set()
        await self.finish()
        self.assertEqual(self.cache.read_photo(self.shared), b'new real photo')
        self.assertAlmostEqual(path.stat().st_mtime, self.old_time, places=4)

    async def test_old_source_cannot_overwrite_recent_shared_photo(self):
        self.cache.thumbnail(7, 42, b'recent shared photo')
        modified = self.shared.stat().st_mtime_ns
        for _ in range(3):
            await self.core.avatar_file(42)
        self.assertEqual(self.shared.read_bytes(), b'recent shared photo')
        self.assertEqual(self.shared.stat().st_mtime_ns, modified)
        self.client.download_profile_photo.assert_not_called()

    async def test_reopening_profile_does_not_cancel_an_active_refresh(self):
        started, release = await self.block_download()
        await self.core.avatar_file(42)
        await started.wait()
        task = self.cache.jobs[(7, 42)]
        await self.core.avatar_file(42)
        self.assertIs(self.cache.jobs[(7, 42)], task)
        self.assertEqual(task.cancelling(), 0)
        self.client.download_profile_photo.assert_awaited_once()
        release.set()
        await self.finish()
        await self.core.avatar_file(42)
        self.assertEqual(self.cache.read_photo(self.shared), b'new real photo')
        self.client.download_profile_photo.assert_awaited_once()

    async def test_known_absence_still_removes_recent_shared_photo(self):
        self.cache.thumbnail(7, 42, b'recent shared photo')
        self.entity.photo = None
        self.assertIsNone(await self.core.avatar_file(42))
        self.assertFalse(self.shared.exists())
        self.client.download_profile_photo.assert_not_called()

    async def test_privacy_revocation_discards_preparation_started_from_profile(self):
        started, release = await self.block_download()
        await self.core.avatar_file(42)
        await started.wait()
        self.core.prefs.values['notify_preview'] = False
        self.cache.sync(self.core)
        release.set()
        await self.finish()
        self.assertFalse(self.shared.exists())
        self.assertFalse((self.cache.root / '7').exists())

    async def test_offline_does_not_start_a_refresh_or_reactivate_stale_photo(self):
        self.core.connection = 'offline'
        self.assertEqual(await self.core.avatar_file(42), self.source)
        self.assertFalse(self.shared.exists())
        self.client.download_profile_photo.assert_not_called()

    async def test_default_off_refreshes_an_expired_photo_normally(self):
        self.core.prefs.values['mobile_features']['keep_loaded'] = False
        await self.core.avatar_file(42)
        self.assertEqual(self.cache.read_photo(self.shared), b'new real photo')
        self.assertEqual(self.source.read_bytes(), b'new real photo')
        self.client.download_profile_photo.assert_awaited_once()

    async def test_network_failure_preserves_recent_shared_photo_and_next_request_recovers(self):
        self.core.prefs.values['mobile_features']['keep_loaded'] = False
        self.cache.thumbnail(7, 42, b'recent shared photo')
        actual = self.client.download_profile_photo.side_effect
        self.client.download_profile_photo.side_effect = OSError('synthetic network failure')
        self.assertIsNone(await self.core.avatar_file(42))
        self.assertFalse(self.source.with_suffix('.none').exists())
        self.assertEqual(self.shared.read_bytes(), b'recent shared photo')
        self.client.download_profile_photo.side_effect = actual
        with self.after_pause():
            await self.core.avatar_file(42)
        self.assertEqual(self.shared.read_bytes(), b'new real photo')
        self.assertEqual(self.client.download_profile_photo.await_count, 2)

    async def test_storage_failure_is_not_recorded_as_absence(self):
        self.core.prefs.values['mobile_features']['keep_loaded'] = False
        self.cache.thumbnail(7, 42, b'recent shared photo')
        with patch('tg_ascii_mobile.core.os.replace', side_effect=OSError('synthetic storage failure')):
            self.assertIsNone(await self.core.avatar_file(42))
        self.assertFalse(self.source.with_suffix('.none').exists())
        self.assertFalse(list(self.source.parent.glob('*.part')))
        self.assertEqual(self.shared.read_bytes(), b'recent shared photo')
        with self.after_pause():
            await self.core.avatar_file(42)
        self.assertEqual(self.shared.read_bytes(), b'new real photo')

    async def test_backend_replaced_while_viewer_loads_cannot_publish_to_shared_cache(self):
        async def replaced(*args):
            self.core.accounts.services['qa'].backend = NS()
            return self.source
        self.core._avatar_file = AsyncMock(side_effect=replaced)
        await self.core.avatar_file(42)
        self.assertFalse(self.shared.exists())
        self.assertFalse(self.cache.jobs)

    async def test_android_fetch_failure_can_recover_without_a_false_negative_marker(self):
        self.core.system = 'Android'
        del self.core.ios_notice_cache
        self.core.prefs.values['mobile_features']['keep_loaded'] = False
        download = self.client.download_profile_photo.side_effect
        self.client.download_profile_photo.side_effect = OSError('synthetic')
        self.assertIsNone(await self.core.avatar_file(42))
        self.assertFalse(self.source.with_suffix('.none').exists())
        self.client.download_profile_photo.side_effect = download
        with self.after_pause():
            self.assertEqual(await self.core.avatar_file(42), self.source)
        self.assertEqual(self.source.read_bytes(), b'new real photo')

    async def test_success_without_photo_still_marks_absence_and_clears_shared_copy(self):
        self.core.prefs.values['mobile_features']['keep_loaded'] = False
        self.cache.thumbnail(7, 42, b'recent shared photo')
        self.client.download_profile_photo.side_effect = None
        self.client.download_profile_photo.return_value = None
        self.assertIsNone(await self.core.avatar_file(42))
        self.assertTrue(self.source.with_suffix('.none').exists())
        self.assertFalse(self.shared.exists())
        await self.core.avatar_file(42)
        self.client.download_profile_photo.assert_awaited_once()

    async def test_existing_negative_marker_keeps_conservative_privacy_behavior(self):
        self.core.chats = []  # no authoritative photo_id; existing .none stays authoritative
        self.source.with_suffix('.none').touch()
        self.cache.thumbnail(7, 42, b'recent shared photo')
        self.assertIsNone(await self.cache.picture(self.core, 'qa', 42, self.backend))
        self.assertFalse(self.shared.exists())
        self.client.download_profile_photo.assert_not_called()
