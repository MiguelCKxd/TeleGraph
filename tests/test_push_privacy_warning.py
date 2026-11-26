"""A failed UpdateDeviceLocked with previews allowed is a retried warning, not a denied registration."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock

from telethon import errors, functions
from tg_ascii_mobile.core import Core

UDL = 'UpdateDeviceLockedRequest'
REGISTER = 'RegisterDeviceRequest'
UNREGISTER = 'UnregisterDeviceRequest'


class PushPrivacyWarningTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.core = Core(Path(folder.name), 'iOS')
        self.core.loop.close()
        self.core.loop = asyncio.get_running_loop()
        self.addCleanup(lambda: self.core._push_check.cancel() if self.core._push_check else None)
        self.core.stage = 'ready'
        self.core.prefs = NS(values={'notifications': True, 'notify_preview': True})
        self.core.lock_record = Mock(return_value=None)
        self.core._push_token = (1, 'synthetic-only-token', False)
        self.calls, self.udl, self.register = [], [TimeoutError('private RPC text')], [True]
        self.client = self.fake_client()
        self.core.accounts = NS(services={'a': NS(backend=NS(client=self.client))}, identities={'a': 42})

    def fake_client(self):
        async def client(request):
            name = type(request).__name__
            self.calls.append(name)
            queue = self.udl if name == UDL else self.register if name == REGISTER else [True]
            value = queue.pop(0) if len(queue) > 1 else queue[0]
            if isinstance(value, BaseException):
                raise value
            return value
        return client

    async def status(self):
        await self.core.sync_push_registration()
        return await self.core.api_notification_status()

    def delay(self):
        return self.core._push_check.when() - self.core.loop.time()

    async def test_warning_retries_at_bounded_interval_without_reregistering(self):
        status = await self.status()
        self.assertEqual((status['state'], status['privacy_warning'], status['registered_accounts']),
                         ('registered', 'TimeoutError', 1))
        self.assertEqual(self.calls, [UDL, REGISTER])
        self.assertLessEqual(self.delay(), Core.PUSH_PRIVACY_RETRY)
        self.assertGreater(self.delay(), Core.PUSH_PRIVACY_RETRY - 5)
        self.calls.clear()
        await self.core.sync_push_registration()  # what the 300 s timer runs
        self.assertEqual(self.calls, [UDL])  # registration cache still valid: no new RegisterDevice
        self.assertLessEqual(self.delay(), Core.PUSH_PRIVACY_RETRY)  # persistent failure keeps the cadence

    async def test_privacy_success_clears_warning_and_returns_to_renewal(self):
        self.udl = [TimeoutError(), True]
        await self.status()
        status = await self.status()
        self.assertEqual((status['state'], status['privacy_warning'], status['privacy_warning_accounts']),
                         ('registered', None, 0))
        self.assertGreater(self.delay(), 22 * 3600)
        self.assertEqual(self.calls.count(REGISTER), 1)

    async def test_protected_previews_policy_is_unchanged(self):
        self.core.lock_record.return_value = {'hash': 'synthetic'}
        self.udl = [False]
        status = await self.status()
        self.assertEqual((status['state'], status['phase'], status['error'], status['registered_accounts']),
                         ('retrying', 'privacy', 'privacy_registration', 0))
        self.assertIsNone(status['privacy_warning'])
        self.assertEqual(self.calls, [UDL, UNREGISTER])

    async def test_switching_to_protected_replaces_warning_with_failure(self):
        await self.status()
        self.core.prefs.values['notify_preview'] = False
        self.udl = [False]
        status = await self.status()
        self.assertEqual((status['state'], status['phase']), ('retrying', 'privacy'))
        self.assertIsNone(status['privacy_warning'])

    async def test_registration_error_is_still_reported_with_warning_separate(self):
        self.register = [errors.BadRequestError(None, 'APP_PUSH_APIKEY_MISSING')]
        status = await self.status()
        self.assertEqual((status['state'], status['phase'], status['error'], status['registered_accounts']),
                         ('retrying', 'telegram', 'APP_PUSH_APIKEY_MISSING', 0))
        self.assertEqual(status['privacy_warning'], 'TimeoutError')
        self.assertLessEqual(self.delay(), 5)

    async def test_disabling_notifications_clears_warning(self):
        await self.status()
        self.core.prefs.values['notifications'] = False
        status = await self.status()
        self.assertEqual((status['state'], status['privacy_warning'], status['privacy_warning_accounts']),
                         ('disabled', None, 0))
        self.assertEqual(self.core._push_privacy_warnings, {})

    async def test_generation_change_hides_and_drops_old_warning(self):
        await self.status()
        old = self.core._push_privacy_warnings['a']
        self.core._push_generation += 1
        self.assertIsNone((await self.core.api_notification_status())['privacy_warning'])
        await self.core.sync_push_registration()
        self.assertIsNot(self.core._push_privacy_warnings.get('a'), old)
        self.assertTrue(all(entry[2] == self.core._push_generation
                            for entry in self.core._push_privacy_warnings.values()))

    async def test_shutdown_resets_warnings(self):
        await self.status()
        self.core.close_media_requests = Mock(side_effect=RuntimeError('stop after push reset'))
        with self.assertRaises(RuntimeError):
            await self.core.shutdown()
        self.assertEqual(self.core._push_privacy_warnings, {})

    async def test_client_or_account_change_drops_stale_warning(self):
        await self.status()
        replacement = self.fake_client()
        self.core.accounts.services['a'] = NS(backend=NS(client=replacement))
        self.assertIsNone((await self.core.api_notification_status())['privacy_warning'])
        self.udl = [True]
        await self.core.sync_push_registration()
        self.assertNotIn('a', self.core._push_privacy_warnings)

    async def test_unregistering_account_clears_warning(self):
        await self.status()
        await self.core.unregister_push_account('a')
        self.assertNotIn('a', self.core._push_privacy_warnings)

    async def test_status_carries_fixed_codes_only(self):
        status = await self.status()
        text = repr(status)
        for secret in ('private', 'synthetic-only-token', '42'):
            self.assertNotIn(secret, text)
        self.assertIs(type(status['privacy_warning_accounts']), int)
