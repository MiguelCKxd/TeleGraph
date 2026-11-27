"""Synthetic accounts only: avatar work must not delay or leak an alert."""
import asyncio
import ast
import os
from pathlib import Path
import plistlib
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock
import sys

from tg_ascii_mobile.core import Core
from tg_ascii_mobile import notify_native
from tg_ascii_mobile.ios_notice_cache import MAX_PHOTO_BYTES, NoticeCache

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
from add_notification_target import add_notification_target
from configure_siri import configure_siri


class AvatarProjectTests(unittest.TestCase):
    def test_both_targets_receive_identical_helper_and_keep_signing_capabilities(self):
        with TemporaryDirectory() as folder:
            xcode = Path(folder)
            phone = xcode / 'TGASCII'
            phone.mkdir()
            (phone / 'main.m').write_text('int main(void) { return 0; }\n')
            (phone / 'TGASCII-Info.plist').write_bytes(plistlib.dumps({}))
            capabilities = {'aps-environment': 'development', 'com.apple.developer.usernotifications.communication': True}
            (xcode / 'TeleGraphPush.entitlements').write_bytes(plistlib.dumps(capabilities))
            (xcode / 'TG-ASCII.xcodeproj').mkdir()
            project = xcode / 'TG-ASCII.xcodeproj/project.pbxproj'
            project.write_text('''/* Begin PBXFileReference section */
/* End PBXFileReference section */
\t\tAAAAAAAAAAAAAAAAAAAAAAAA /* Root */ = {
\t\t\ttargets = (
\t\t\t);
\t\t};
\t\t60796EE119190F4100A9926B /* Phone */ = {
\t\t\tdependencies = (
\t\t\t);
\t\t\tbuildPhases = (
\t\t\t);
\t\t};
DEVELOPMENT_TEAM = TESTTEAM;
rootObject = AAAAAAAAAAAAAAAAAAAAAAAA /* Root */;
''')
            for _ in range(2):
                configure_siri(xcode)
                add_notification_target(xcode, '3.4.1', '3', 'org.tgas.synthetic')
            helper = 'TGNotificationPresentation.m'
            self.assertEqual((phone / 'main.m').read_text().count(f'#import "{helper}"'), 1)
            self.assertEqual((phone / helper).read_bytes(), (TOOLS / 'ios' / helper).read_bytes())
            self.assertEqual((phone / helper).read_bytes(), (xcode / 'TeleGraphNotificationService' / helper).read_bytes())
            info = plistlib.loads((xcode / 'TeleGraphNotificationService/Info.plist').read_bytes())
            self.assertEqual(info['NSUserActivityTypes'], ['INSendMessageIntent'])
            self.assertEqual(info['CFBundleVersion'], '3')
            self.assertIn('"-framework", ImageIO', project.read_text())
            self.assertIn('"-framework", UIKit', project.read_text())
            actual = plistlib.loads((xcode / 'TeleGraphPush.entitlements').read_bytes())
            for key, value in capabilities.items(): self.assertEqual(actual[key], value)
            self.assertEqual(actual['com.apple.security.application-groups'], ['group.org.tgas.synthetic'])


class LocalAvatarFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_or_failing_presenter_still_schedules_one_original_alert(self):
        # Execute the actual nested post function, without installing an APNs delegate
        # or requesting permissions. Only Objective-C scheduling is a synthetic double.
        module = ast.parse(Path(notify_native.__file__).read_text())
        install = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == 'install_ios')
        post = next(node for node in install.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'post')
        code = compile(ast.Module(body=[post], type_ignores=[]), str(notify_native.__file__), 'exec')
        for presenter in (None, Mock(side_effect=RuntimeError('synthetic decoration failure')), Mock(side_effect=lambda content, *args: content)):
            with self.subTest(presenter=presenter):
                scheduled, main_calls, keep = [], [], set()
                content = NS()
                classes = {'UNMutableNotificationContent': NS(alloc=lambda: NS(init=lambda: content)),
                           'UNNotificationRequest': NS(requestWithIdentifier_content_trigger_=lambda ident, content, trigger: NS(identifier=ident, content=content)),
                           'UNNotificationSound': NS(defaultSound='system')}
                def schedule(request, completion):
                    scheduled.append(request)
                    completion(None)
                def main(call):
                    main_calls.append(True)
                    call()
                namespace = {'ObjCClass': classes.__getitem__, 'Block': lambda callback, *args: callback,
                             'objc_id': None, 'keep': keep, 'core': NS(accounts=NS(identities={'a': 7})),
                             'carplay': False, 'decorate': presenter, 'app': NS(on_main_thread=main),
                             'center': NS(addNotificationRequest_withCompletionHandler_=schedule),
                             'notification_id': notify_native.notification_id}
                exec(code, namespace)
                await namespace['post']('a', -99, 'QA Sender', 'Synthetic body', 1, True, sender='42', picture=b'photo', conversation='QA group')
                self.assertEqual(len(scheduled), 1)
                self.assertEqual(main_calls, [True])
                self.assertEqual((content.title, content.body, content.threadIdentifier), ('QA Sender', 'Synthetic body', '7:-99'))
                self.assertFalse(keep)
                if presenter is not None:
                    presenter.assert_called_once_with(content, '7', '-99', '42', b'photo', 'QA group')


class AvatarCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.core = Core(Path(self.folder.name), 'iOS')
        self.addCleanup(self.core.loop.close)
        self.backend = NS(notification_policy=AsyncMock(return_value={'enabled': True, 'preview': True, 'sound': True}),
                          client=NS(download_profile_photo=AsyncMock(return_value=b'real-photo')))
        self.core.accounts = NS(current='a', entries={'a': {}}, identities={'a': 7}, services={'a': NS(backend=self.backend)})
        self.core.prefs = NS(values={'notifications': True, 'notify_preview': True})
        self.core.in_background = True
        self.core.native_notify = Mock()
        self.cache = self.core.ios_notice_cache = NoticeCache(self.folder.name)
        self.cache.sync(self.core)
        self.message = NS(id=11, sender_id=42, sender='QA Sender', outgoing=False, service=False, read=False, text='Synthetic')

    async def asyncTearDown(self):
        tasks = tuple(self.cache.jobs.values())
        self.cache.close()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def finish_photos(self):
        await asyncio.gather(*tuple(self.cache.jobs.values()), return_exceptions=True)

    async def test_no_network_wait_before_alert_and_real_photo_is_prepared_for_next_notice(self):
        released = asyncio.Event()
        async def slow(*args, **kwargs):
            await released.wait()
            return b'photo from account a'
        self.backend.client.download_profile_photo.side_effect = slow
        await asyncio.wait_for(self.core.notify('a', 42, self.message), .5)
        self.core.native_notify.assert_called_once()
        self.assertIsNone(self.core.native_notify.call_args.kwargs['picture'])
        self.assertFalse(released.is_set())
        released.set()
        await self.finish_photos()
        self.assertEqual((self.cache.root / '7/42.jpg').read_bytes(), b'photo from account a')
        await self.core.notify('a', 42, self.message)
        self.assertEqual(self.core.native_notify.call_args.kwargs['picture'], b'photo from account a')
        self.backend.client.download_profile_photo.assert_awaited_once()

    async def test_sender_photo_never_uses_group_photo_or_other_account_copy(self):
        self.cache.thumbnail(7, -99, b'group photo')
        wrong = self.core.root / 'mobile-avatars' / 'b'
        wrong.mkdir(parents=True)
        (wrong / '42.jpg').write_bytes(b'other account')
        await self.core.notify('a', -99, self.message)
        self.assertIsNone(self.core.native_notify.call_args.kwargs['picture'])
        await self.finish_photos()
        self.assertEqual((self.cache.root / '7/42.jpg').read_bytes(), b'real-photo')

    async def test_known_photo_less_sender_removes_old_copy_and_remains_photo_less(self):
        self.cache.thumbnail(7, 42, b'old photo')
        self.core.chats = [NS(id=42, name='QA', muted=False, entity=NS(photo=None))]
        await self.core.notify('a', 42, self.message)
        self.assertIsNone(self.core.native_notify.call_args.kwargs['picture'])
        self.assertEqual(self.core.photo_id(42), 0)
        self.assertFalse((self.cache.root / '7/42.jpg').exists())
        self.backend.client.download_profile_photo.assert_not_called()

    async def test_profile_photo_removal_clears_extension_and_pending_fetch(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def fetch(*args, **kwargs):
            started.set()
            try: await release.wait()
            except asyncio.CancelledError: pass
            return b'deleted photo'
        self.backend.client.download_profile_photo.side_effect = fetch
        await self.cache.picture(self.core, 'a', 42, self.backend)
        await started.wait()
        self.cache.thumbnail(7, 42, b'old photo')
        self.core.forget_avatar(42)
        await self.finish_photos()
        self.assertFalse((self.cache.root / '7/42.jpg').exists())

    async def test_cancel_before_first_step_does_not_leave_a_stale_job(self):
        self.cache.prepare(7, 42, self.backend, lambda: True)
        self.cache.forget(7, 42)
        await self.finish_photos()
        self.assertFalse(self.cache.jobs)

    async def test_privacy_logout_and_replaced_backend_reject_late_photo(self):
        for mutation in ('pin', 'previews', 'logout', 'backend', 'accounts'):
            with self.subTest(mutation=mutation):
                self.cache.closed = False
                self.core.lock_record = lambda: None
                self.core.prefs.values['notify_preview'] = True
                self.core._push_logging_out.clear()
                self.core.accounts = NS(current='a', entries={'a': {}}, identities={'a': 7}, services={'a': NS(backend=self.backend)})
                self.cache.sync(self.core)
                started, release = asyncio.Event(), asyncio.Event()
                async def fetch(*args, **kwargs):
                    started.set()
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        pass  # Even a downloader that ignores cancellation cannot repopulate.
                    return b'late photo'
                self.backend.client.download_profile_photo.side_effect = fetch
                await self.cache.picture(self.core, 'a', 42, self.backend)
                await started.wait()
                if mutation == 'pin': self.core.lock_record = lambda: {'hash': 'fixture'}
                elif mutation == 'previews': self.core.prefs.values['notify_preview'] = False
                elif mutation == 'logout': self.core._push_logging_out.add('a')
                elif mutation == 'backend': self.core.accounts.services['a'].backend = NS()
                else: self.core.accounts = None
                self.cache.sync(self.core)
                release.set()
                await self.finish_photos()
                self.assertFalse((self.cache.root / '7/42.jpg').exists())

    async def test_work_is_deduplicated_capped_and_shutdown_cancels_it(self):
        release = asyncio.Event()
        active = peak = 0
        async def fetch(*args, **kwargs):
            nonlocal active, peak
            active += 1; peak = max(peak, active)
            try: await release.wait()
            finally: active -= 1
        self.backend.client.download_profile_photo.side_effect = fetch
        for _ in range(2):
            for sender in range(1, 25):
                await self.cache.picture(self.core, 'a', sender, self.backend)
        self.assertEqual(len(self.cache.jobs), 16)
        self.assertEqual(peak, 2)
        tasks = tuple(self.cache.jobs.values())
        self.cache.close()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.assertFalse(self.cache.jobs)

    async def test_oversized_expired_negative_cache_and_no_identity(self):
        self.cache.thumbnail(7, 42, b'x' * (MAX_PHOTO_BYTES + 1))
        self.assertFalse((self.cache.root / '7/42.jpg').exists())
        self.cache.thumbnail(7, 42, b'old photo')
        path = self.cache.root / '7/42.jpg'
        os.utime(path, (1, 1))
        self.assertIsNone(self.cache.read_photo(path))
        folder = self.core.root / 'mobile-avatars/a'
        folder.mkdir(parents=True)
        (folder / '42.none').touch()
        self.assertIsNone(await self.cache.picture(self.core, 'a', 42, self.backend))
        self.assertFalse(path.exists())
        self.core.accounts.identities.clear()
        self.assertIsNone(await self.cache.picture(self.core, 'a', 43, self.backend))
        self.assertFalse(self.cache.jobs)
        self.assertEqual(plistlib.loads((self.cache.root / 'policy.plist').read_bytes())['accounts'], [])

    async def test_photo_failure_does_not_cancel_notice(self):
        self.backend.client.download_profile_photo.side_effect = OSError('synthetic')
        self.assertTrue(await self.core.notify('a', 42, self.message))
        await self.finish_photos()
        self.core.native_notify.assert_called_once()
        self.assertFalse((self.cache.root / '7/42.jpg').exists())

    async def test_confirmed_absent_photo_is_not_refetched_for_each_alert(self):
        self.backend.client.download_profile_photo.return_value = None
        await self.core.notify('a', 42, self.message)
        await self.finish_photos()
        await self.core.notify('a', 42, self.message)
        self.backend.client.download_profile_photo.assert_awaited_once()
        self.assertFalse((self.cache.root / '7/42.jpg').exists())
        self.core.forget_avatar(42)
        self.assertFalse((self.cache.root / '7/42.none').exists())

    async def test_reading_photo_does_not_extend_its_freshness_forever(self):
        folder = self.core.root / 'mobile-avatars/a'
        folder.mkdir(parents=True)
        path = folder / '42.jpg'
        path.write_bytes(b'cached')
        import time
        previous = time.time() - 10000
        os.utime(path, (previous, previous))
        await self.core.notify('a', 42, self.message)
        cached = self.cache.root / '7/42.jpg'
        self.assertAlmostEqual(cached.stat().st_mtime, previous, places=4)
        path.unlink()
        await self.core.notify('a', 42, self.message)
        self.assertAlmostEqual(cached.stat().st_mtime, previous, places=4)
        self.backend.client.download_profile_photo.assert_not_called()

    async def test_new_known_photo_overrides_negative_cache_without_becoming_a_fake_profile(self):
        self.backend.client.download_profile_photo.return_value = None
        await self.cache.picture(self.core, 'a', 42, self.backend)
        await self.finish_photos()
        self.assertTrue((self.cache.root / '7/42.none').exists())
        self.core.chats = [NS(id=42, entity=NS(photo=NS(photo_id=91)))]
        self.backend.client.download_profile_photo.return_value = b'new real photo'
        await self.cache.picture(self.core, 'a', 42, self.backend)
        await self.finish_photos()
        self.assertFalse((self.cache.root / '7/42.none').exists())
        self.assertEqual((self.cache.root / '7/42.jpg').read_bytes(), b'new real photo')
        self.assertEqual(self.core.photo_id(42), 91)

    async def test_viewer_cannot_republish_old_photo_when_current_entity_has_no_photo(self):
        self.core.chats = [NS(id=42, entity=NS(photo=None))]
        old = self.core.root / 'old.jpg'
        old.write_bytes(b'old viewer photo')
        self.core._avatar_file = AsyncMock(return_value=old)
        self.cache.thumbnail(7, 42, b'old shared copy')
        await self.core.avatar_file(42)
        self.assertFalse((self.cache.root / '7/42.jpg').exists())


if __name__ == '__main__':
    unittest.main()
