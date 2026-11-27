"""A failed avatar fetch pauses only that request, briefly and in memory."""
import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

from telethon.errors import FloodWaitError

from tg_ascii_mobile import core as core_module
from tg_ascii_mobile.core import AVATAR_ERROR_PAUSE, AVATAR_FLOOD_LIMIT, AVATAR_PAUSE_LIMIT, Core
from tg_ascii_mobile.ios_notice_cache import NoticeCache, PHOTO_LIFETIME


class AvatarErrorPauseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.core = Core(Path(self.directory.name), 'iOS')
        self.core.loop.close()
        self.core.loop = asyncio.get_running_loop()
        self.entity = NS(photo=NS(photo_id=91))
        self.error = OSError('synthetic network failure')
        self.backend = self.make_backend()
        self.core.accounts = NS(current='qa', identities={'qa': 7, 'other': 8}, entries={'qa': {}, 'other': {}},
                                services={'qa': NS(backend=self.backend), 'other': NS(backend=self.make_backend())})
        self.core.prefs = NS(values={'mobile_features': {'keep_loaded': False}})
        self.core.connection = 'online'
        self.core.chats = [NS(id=42, entity=self.entity), NS(id=43, entity=self.entity)]
        self.cache = self.core.ios_notice_cache = NoticeCache(Path(self.directory.name) / 'app-group')
        self.cache.sync(self.core)
        self.now = time.monotonic()
        clock = patch.object(core_module, 'avatar_clock', side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)

    async def asyncTearDown(self):
        self.cache.close()
        await asyncio.gather(*tuple(self.cache.jobs.values()), return_exceptions=True)

    def make_backend(self):
        async def download(peer, *, file, download_big):
            if self.error is not None:
                raise self.error
            if file is bytes:
                return b'new real photo'
            Path(file).write_bytes(b'new real photo')
            return file
        return NS(client=NS(download_profile_photo=AsyncMock(side_effect=download),
                            get_entity=AsyncMock(return_value=self.entity)))

    @property
    def attempts(self):
        return self.backend.client.download_profile_photo.await_count

    def path(self, peer=42, account='qa', big=False):
        return self.core.root / 'mobile-avatars' / account / f'{peer}{"-big" if big else ""}.jpg'

    async def test_repeated_failures_make_one_attempt_until_the_pause_elapses(self):
        for _ in range(10):
            self.assertIsNone(await self.core.avatar_file(42))
        self.assertEqual(self.attempts, 1)
        self.assertFalse(self.path().with_suffix('.none').exists())  # not a confirmed absence
        self.now += AVATAR_ERROR_PAUSE - 1
        await self.core.avatar_file(42)
        self.assertEqual(self.attempts, 1)
        self.now += 2
        await self.core.avatar_file(42)
        self.assertEqual(self.attempts, 2)  # retried once, then paused again
        await self.core.avatar_file(42)
        self.assertEqual(self.attempts, 2)

    async def test_success_after_the_pause_clears_it(self):
        await self.core.avatar_file(42)
        self.error, self.now = None, self.now + AVATAR_ERROR_PAUSE + 1
        self.assertEqual(await self.core.avatar_file(42), self.path())
        self.assertNotIn(str(self.path()), self.core._avatar_pause)
        self.assertEqual(self.cache.read_photo(self.cache.root / '7/42.jpg'), b'new real photo')

    async def test_confirmed_absence_is_not_a_pause_and_keeps_its_marker(self):
        self.error = None
        self.backend.client.download_profile_photo.side_effect = None
        self.backend.client.download_profile_photo.return_value = None
        self.assertIsNone(await self.core.avatar_file(42))
        self.assertTrue(self.path().with_suffix('.none').exists())
        self.assertNotIn(str(self.path()), self.core._avatar_pause)

    async def test_pause_returns_the_existing_copy_as_offline_does(self):
        self.path().parent.mkdir(parents=True)
        self.path().write_bytes(b'expired viewer photo')
        old = time.time() - PHOTO_LIFETIME - 86400
        os.utime(self.path(), (old, old))
        self.assertIsNone(await self.core.avatar_file(42))  # the failed request itself
        self.assertEqual(await self.core.avatar_file(42), self.path())
        self.assertEqual(self.attempts, 1)
        self.assertFalse((self.cache.root / '7/42.jpg').exists())  # an expired copy is never shared

    async def test_pause_is_per_peer_and_size(self):
        await self.core.avatar_file(42)
        await self.core.avatar_file(43)
        self.assertEqual(self.attempts, 2)
        await self.core.avatar_file(42, True)
        self.assertEqual(self.attempts, 3)
        entity_lookups = self.backend.client.get_entity.await_count
        await self.core.avatar_file(42, True)
        self.assertEqual(self.attempts, 3)
        self.assertEqual(self.backend.client.get_entity.await_count, entity_lookups)  # no lookup either

    async def test_account_change_discards_pauses(self):
        await self.core.avatar_file(42)
        self.core.accounts.current = 'other'
        await self.core.avatar_file(42)
        other = self.core.accounts.services['other'].backend.client.download_profile_photo
        self.assertEqual(other.await_count, 1)
        self.core.accounts.current = 'qa'
        await self.core.avatar_file(42)
        self.assertEqual(self.attempts, 2)

    async def test_backend_change_discards_pauses(self):
        await self.core.avatar_file(42)
        replacement = self.make_backend()
        self.core.accounts.services['qa'] = NS(backend=replacement)
        await self.core.avatar_file(42)
        self.assertEqual(replacement.client.download_profile_photo.await_count, 1)

    async def test_late_failure_of_a_previous_account_records_nothing(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def slow(*args, **kwargs):
            started.set()
            await release.wait()
            raise OSError('late')
        self.backend.client.download_profile_photo.side_effect = slow
        request = asyncio.create_task(self.core.avatar_file(42))
        await started.wait()
        self.core.accounts.current = 'other'
        release.set()
        self.assertIsNone(await request)
        self.assertEqual(len(self.core._avatar_pauses(self.core.account, self.core.backend)), 0)
        self.core.accounts.current = 'qa'
        self.backend.client.download_profile_photo.side_effect = None
        self.backend.client.download_profile_photo.return_value = None
        await self.core.avatar_file(42)
        self.assertEqual(self.attempts, 2)

    async def test_forget_avatar_lifts_the_pause(self):
        await self.core.avatar_file(42)
        await self.core.avatar_file(42, True)
        self.core.forget_avatar(42)
        await self.core.avatar_file(42)
        await self.core.avatar_file(42, True)
        self.assertEqual(self.attempts, 4)

    async def test_failure_of_a_download_invalidated_by_forget_avatar_records_no_pause(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def slow(*args, **kwargs):
            started.set()
            await release.wait()
            raise OSError('old photo request failed')
        self.backend.client.download_profile_photo.side_effect = slow
        request = asyncio.create_task(self.core.avatar_file(42))
        await started.wait()
        self.core.forget_avatar(42)  # e.g. the person set a new photo meanwhile
        release.set()
        self.assertIsNone(await request)  # the waiting UI request ends normally
        self.assertNotIn(str(self.path()), self.core._avatar_pause)
        self.error = None
        self.backend.client.download_profile_photo.side_effect = self.make_backend().client.download_profile_photo.side_effect
        lookups = self.backend.client.get_entity.await_count
        self.assertEqual(await self.core.avatar_file(42), self.path())
        self.assertEqual(self.attempts, 2)
        self.assertEqual(self.backend.client.get_entity.await_count, lookups + 1)  # fresh request honoured
        self.assertNotIn(42, self.core.fresh_avatars)

    async def test_invalidated_download_cannot_lift_a_later_pause(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def slow(*args, **kwargs):
            started.set()
            await release.wait()
            return None
        self.backend.client.download_profile_photo.side_effect = slow
        request = asyncio.create_task(self.core.avatar_file(42))
        await started.wait()
        self.core.forget_avatar(42)
        later = str(self.path())
        self.core._avatar_failed('qa', self.backend, later)  # a pause belonging to newer work
        release.set()
        await request
        self.assertIn(later, self.core._avatar_pause)

    async def test_forget_avatar_during_notice_preparation_does_not_restore_its_pause(self):
        self.core.prefs.values['mobile_features']['keep_loaded'] = True
        self.path().parent.mkdir(parents=True)
        self.path().write_bytes(b'old viewer photo')
        self.path().with_suffix('.id').write_text('91')
        old = time.time() - PHOTO_LIFETIME - 86400
        os.utime(self.path(), (old, old))
        async def picture(*args):
            self.core.forget_avatar(42)
            return None
        with patch.object(self.cache, 'picture', side_effect=picture):
            await self.core.avatar_file(42)
        self.assertNotIn('notice:42', self.core._avatar_pause)

    async def test_old_notice_preparation_cannot_lift_a_newer_reservation(self):
        self.core.prefs.values['mobile_features']['keep_loaded'] = True
        def old_viewer_copy():
            self.path().parent.mkdir(parents=True, exist_ok=True)
            self.path().write_bytes(b'old viewer photo')
            self.path().with_suffix('.id').write_text('91')
            old = time.time() - PHOTO_LIFETIME - 86400
            os.utime(self.path(), (old, old))
        old_viewer_copy()
        calls = []
        async def picture(*args):
            calls.append(args)
            if len(calls) == 1:
                self.core.forget_avatar(42)
                old_viewer_copy()  # an expired keep-loaded copy again, as ios34 reproduced
                await self.core.avatar_file(42)  # newer request: reserves again, gets no copy
                return b'copy found by the older call'
            return None
        with patch.object(self.cache, 'picture', side_effect=picture):
            await self.core.avatar_file(42)
        self.assertEqual(len(calls), 2)
        self.assertIn('notice:42', self.core._avatar_pause)  # the newer reservation survives

    async def test_flood_wait_is_respected_and_bounded(self):
        self.error = FloodWaitError(request=None, capture=600)
        await self.core.avatar_file(42)
        self.now += AVATAR_ERROR_PAUSE + 1
        await self.core.avatar_file(42)
        self.assertEqual(self.attempts, 1)
        self.now += 600
        await self.core.avatar_file(42)
        self.assertEqual(self.attempts, 2)
        self.error = FloodWaitError(request=None, capture=10 ** 9)
        self.now += 601
        await self.core.avatar_file(42)
        deadline = self.core._avatar_pause[str(self.path())]
        self.assertEqual(deadline, self.now + AVATAR_FLOOD_LIMIT)

    async def test_timeouts_and_storage_errors_pause_too(self):
        for error in (TimeoutError(), RuntimeError('synthetic')):
            self.error = error
            await self.core.avatar_file(42)
            await self.core.avatar_file(42)
            self.now += AVATAR_ERROR_PAUSE + 1
        self.assertEqual(self.attempts, 2)
        self.error = None
        with patch('tg_ascii_mobile.core.os.replace', side_effect=OSError('synthetic storage failure')):
            await self.core.avatar_file(42)
        await self.core.avatar_file(42)
        self.assertEqual(self.attempts, 3)
        self.assertFalse(self.path().with_suffix('.none').exists())

    async def test_cancellation_is_not_recorded_as_a_failure(self):
        started = asyncio.Event()
        async def hang(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()
        self.backend.client.download_profile_photo.side_effect = hang
        request = asyncio.create_task(self.core.avatar_file(42))
        await started.wait()
        self.core.avatar_jobs[self.path()].cancel()
        with self.assertRaises(asyncio.CancelledError):
            await request
        self.assertNotIn(str(self.path()), self.core._avatar_pause)
        self.backend.client.download_profile_photo.side_effect = None
        self.backend.client.download_profile_photo.return_value = None
        await self.core.avatar_file(42)
        self.assertEqual(self.attempts, 2)

    async def test_pause_map_is_bounded_oldest_first(self):
        self.core.chats = []
        for peer in range(1, AVATAR_PAUSE_LIMIT + 41):
            await self.core.avatar_file(peer)
        pauses = self.core._avatar_pause
        self.assertEqual(len(pauses), AVATAR_PAUSE_LIMIT)
        self.assertNotIn(str(self.path(1)), pauses)
        self.assertIn(str(self.path(AVATAR_PAUSE_LIMIT + 40)), pauses)

    async def test_failing_notice_preparation_is_attempted_once_per_pause(self):
        self.core.prefs.values['mobile_features']['keep_loaded'] = True
        self.path().parent.mkdir(parents=True)
        self.path().write_bytes(b'old viewer photo')
        self.path().with_suffix('.id').write_text('91')
        old = time.time() - PHOTO_LIFETIME - 86400
        os.utime(self.path(), (old, old))
        for _ in range(10):
            self.assertEqual(await self.core.avatar_file(42), self.path())
            await asyncio.gather(*tuple(self.cache.jobs.values()), return_exceptions=True)
        self.assertEqual(self.attempts, 1)
        self.error, self.now = None, self.now + AVATAR_ERROR_PAUSE + 1
        await self.core.avatar_file(42)
        await asyncio.gather(*tuple(self.cache.jobs.values()), return_exceptions=True)
        self.assertEqual(self.attempts, 2)
        self.assertEqual(self.cache.read_photo(self.cache.root / '7/42.jpg'), b'new real photo')
        await self.core.avatar_file(42)  # a fresh shared copy is reused locally
        self.assertEqual(self.attempts, 2)


if __name__ == '__main__':
    unittest.main()
