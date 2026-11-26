import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import sys
from types import ModuleType
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from tg_ascii_mobile.core import Core


class MobilePushRetryTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.core = Core(Path(folder.name), 'iOS')
        self.core.loop.close()
        self.core.loop = asyncio.get_running_loop()
        self.addCleanup(lambda: self.core._push_check.cancel() if self.core._push_check else None)
        self.core.stage = 'ready'
        self.client = AsyncMock(return_value=True)
        self.core.accounts = NS(services={'a': NS(backend=NS(client=self.client))}, identities={'a': 42})
        self.core._push_token = (1, 'private-qa-token', False)

    async def test_initial_failure_retries_without_another_reconnect(self):
        self.client.side_effect = [OSError('private text must not be logged'), True]
        await self.core.sync_push_registration()
        status = await self.core.api_notification_status()
        self.assertEqual((status['state'], status['error'], status['registered_accounts']), ('retrying', 'OSError', 0))
        self.assertNotIn('private', repr(status))
        self.assertLessEqual(self.core._push_check.when() - self.core.loop.time(), 5)
        self.core.schedule_push_check(0)
        await asyncio.sleep(.01)
        self.assertEqual(self.client.await_count, 2)
        self.assertEqual((await self.core.api_notification_status())['state'], 'registered')
        self.assertGreater(self.core._push_check.when() - self.core.loop.time(), 22 * 3600)

    async def test_renewal_and_deduplication_use_last_success(self):
        await self.core.sync_push_registration()
        await asyncio.gather(*(self.core.sync_push_registration() for _ in range(10)))
        self.assertEqual(self.client.await_count, 1)
        self.core._push_registered_at['a'] = time.monotonic() - 24 * 3600
        await self.core.sync_push_registration()
        self.assertEqual(self.client.await_count, 2)

    async def test_backoff_caps_and_disabled_notifications_cancel_timer(self):
        self.client.return_value = False
        for _ in range(10):
            await self.core.sync_push_registration()
        self.assertEqual(self.core._push_retry_delay, 300)
        self.assertLessEqual(self.core._push_check.when() - self.core.loop.time(), 300)
        self.core.prefs = NS(values={'notifications': False})
        await self.core.sync_push_registration()
        self.assertIsNone(self.core._push_check)
        self.assertEqual((await self.core.api_notification_status())['state'], 'disabled')

    async def test_native_failure_retries_apns_even_with_a_previous_token(self):
        self.core.native_push_retry = Mock()
        self.core.native_push_failed('APNs', 'APNs_3010', True, True)
        self.core.schedule_push_check(0)
        await asyncio.sleep(.01)
        self.core.native_push_retry.assert_called_once_with()
        self.client.assert_not_awaited()
        self.core.native_push_failed('APNs', 'permission_denied', False, True)
        self.assertIsNone(self.core._push_check)

    async def test_telegram_acceptance_does_not_erase_denied_os_permission(self):
        self.core.native_push_failed('APNs', 'permission_denied', False, True)
        await self.core.sync_push_registration()
        status = await self.core.api_notification_status()
        self.assertEqual(status['state'], 'registered')
        self.assertEqual(status['permission'], 'denied')
        self.assertEqual(status['registered_accounts'], 1)

    async def test_native_token_callback_clears_failure_and_replaces_retry(self):
        self.core.native_push_failed('APNs', 'APNs_3010', True, True)
        self.core.register_push_token(1, 'private-rotated-token', False)
        await asyncio.sleep(.01)
        self.assertFalse(self.core._push_retry_native)
        self.client.assert_awaited_once()
        self.assertEqual(self.client.await_args.args[0].token, 'private-rotated-token')
        self.assertEqual((await self.core.api_notification_status())['state'], 'registered')

    async def test_rpc_finishing_after_shutdown_cannot_register_or_rearm(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed(request):
            entered.set()
            await release.wait()
            return True
        self.client.side_effect = delayed
        task = asyncio.create_task(self.core.sync_push_registration())
        await asyncio.wait_for(entered.wait(), 1)
        self.core.close_media_requests = AsyncMock()
        self.core.cancel_current_voice = AsyncMock()
        self.core.save_snapshot = AsyncMock()
        self.core.close_call_manager = AsyncMock()
        self.core.siri_vocabulary.sync = Mock()
        self.core.accounts.close = AsyncMock()
        await self.core.shutdown()
        release.set()
        await task
        self.assertFalse(self.core._push_registered)
        self.assertIsNone(self.core._push_check)
        self.core.native_push_failed('APNs', 'late_failure')
        self.assertIsNone(self.core._push_check)

    async def test_ios_settings_recheck_recovers_denied_permission_without_prompt(self):
        from tg_ascii_mobile.notify_native import install_ios
        native = NS(applicationState=2, registerForRemoteNotifications=Mock())
        permission = NS(authorizationStatus=1)
        center = NS(requestAuthorizationWithOptions_completionHandler_=Mock(),
                    getNotificationSettingsWithCompletionHandler_=lambda done: done(permission))
        bundle = NS(bundleIdentifier='org.tgas.ios', objectForInfoDictionaryKey_=lambda _: False)
        classes = {
            'UNUserNotificationCenter': NS(currentNotificationCenter=lambda: center),
            'UIApplication': NS(sharedApplication=native), 'NSBundle': NS(mainBundle=bundle),
            'NSFileManager': NS(defaultManager=NS(containerURLForSecurityApplicationGroupIdentifier_=lambda _: None)),
        }
        class NSObject:
            @classmethod
            def alloc(cls): return cls()
            def init(self): return self
        objc = ModuleType('rubicon.objc')
        objc.NSObject, objc.ObjCClass, objc.ObjCInstance = NSObject, classes.__getitem__, lambda value: value
        objc.objc_method, objc.Block = lambda function: function, lambda function, *_: function
        objc.objc_id, objc.ObjCBlock = object, Mock()
        runtime = ModuleType('rubicon.objc.runtime')
        runtime.load_library = Mock()
        app = NS(core=self.core, on_main_thread=lambda callback: callback())
        self.core.stage = 'loading'  # OS callback may arrive before the account chooser.
        self.core.prefs = NS(values={'notifications': True})
        with patch.dict(sys.modules, {'rubicon.objc': objc, 'rubicon.objc.runtime': runtime}):
            install_ios(app)
            await asyncio.sleep(0)
            self.assertTrue(self.core.in_background)
            self.core.native_notify_refresh()
            await asyncio.sleep(0)
            self.assertEqual(self.core._push_status['error'], 'permission_denied')
            self.assertEqual((await self.core.api_notification_status())['permission'], 'denied')
            self.assertIsNone(self.core._push_check)
            permission.authorizationStatus = 2
            self.core.native_notify_refresh()
            await asyncio.sleep(0)
            native.registerForRemoteNotifications.assert_called_once_with()
            self.assertEqual((await self.core.api_notification_status())['permission'], 'granted')
            center.requestAuthorizationWithOptions_completionHandler_.assert_not_called()
            self.core._push_stopped = True
            self.core.native_notify_refresh()
            await asyncio.sleep(0)
            self.assertEqual(native.registerForRemoteNotifications.call_count, 1)
