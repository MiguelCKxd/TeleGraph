import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from telethon import errors, functions
from tg_ascii_mobile.core import Core


class PushDiagnosticTests(IsolatedAsyncioTestCase):
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
        self.core._push_permission = 'granted'
        self.client = AsyncMock(return_value=True)
        self.core.accounts = NS(services={'a': NS(backend=NS(client=self.client))}, identities={'a': 42})

    async def test_privacy_timeout_keeps_accepted_registration_distinct(self):
        self.client.side_effect = [TimeoutError('private RPC text'), True]
        await self.core.sync_push_registration()
        status = await self.core.api_notification_status()
        # Previews allowed: the accepted registration is not denied; privacy is a warning.
        self.assertEqual((status['state'], status['phase'], status['error']), ('registered', None, None))
        self.assertEqual((status['privacy_warning'], status['privacy_warning_accounts']), ('TimeoutError', 1))
        self.assertEqual((status['registered_accounts'], status['connected_accounts'], status['pending_accounts']),
                         (1, 1, 0))
        self.assertIsInstance(self.client.await_args.args[0], functions.account.RegisterDeviceRequest)
        self.assertNotIn('private', repr(status))
        self.assertNotIn('synthetic-only-token', repr(status))

    async def test_privacy_failure_with_lock_still_prevents_registration(self):
        self.core.lock_record.return_value = {'hash': 'synthetic'}
        self.client.side_effect = [TimeoutError('private'), True]
        await self.core.sync_push_registration()
        status = await self.core.api_notification_status()
        self.assertEqual((status['phase'], status['error']), ('privacy', 'TimeoutError'))
        self.assertEqual((status['registered_accounts'], status['pending_accounts']), (0, 1))
        requests = [call.args[0] for call in self.client.await_args_list]
        self.assertEqual([type(request) for request in requests],
                         [functions.account.UpdateDeviceLockedRequest, functions.account.UnregisterDeviceRequest])
        self.assertEqual(requests[0].period, 0)

    async def test_registration_rejection_and_privacy_false_have_different_phases(self):
        self.client.side_effect = [True, False]
        await self.core.sync_push_registration()
        status = await self.core.api_notification_status()
        self.assertEqual((status['phase'], status['error']), ('telegram', 'registration_rejected'))
        self.assertIsNone(status['privacy_warning'])
        self.core._push_privacy.clear()
        self.client.side_effect = [False, True]
        await self.core.sync_push_registration()
        status = await self.core.api_notification_status()
        self.assertEqual((status['state'], status['phase'], status['error']), ('registered', None, None))
        self.assertEqual(status['privacy_warning'], 'privacy_registration')
        self.assertEqual(status['registered_accounts'], 1)

    async def test_explicit_rpc_category_and_native_failure_are_separate(self):
        self.client.side_effect = [True, errors.TokenInvalidError(request=None)]
        await self.core.sync_push_registration()
        status = await self.core.api_notification_status()
        self.assertEqual((status['phase'], status['error']), ('telegram', 'TokenInvalidError'))
        self.core.native_push_failed('APNs', 'APNs_-1009', True, True)
        status = await self.core.api_notification_status()
        self.assertEqual((status['phase'], status['error']), ('native', 'APNs_-1009'))
        self.core.native_push_failed('APNs', 'permission_query_failed', False, True)
        self.assertEqual((await self.core.api_notification_status())['phase'], 'permission')

    async def test_count_excludes_stale_token_client_and_other_account_set(self):
        await self.core.sync_push_registration()
        self.assertEqual((await self.core.api_notification_status())['registered_accounts'], 1)
        token = self.core._push_token
        self.core._push_token = (1, 'rotated-synthetic-token', False)
        self.assertEqual((await self.core.api_notification_status())['registered_accounts'], 0)
        self.core._push_token = token
        self.core.accounts.services['a'].backend.client = AsyncMock()
        self.assertEqual((await self.core.api_notification_status())['registered_accounts'], 0)
        self.core.accounts.services['a'].backend.client = self.client
        self.core.accounts.services['b'] = NS(backend=NS(client=AsyncMock()))
        self.core.accounts.identities['b'] = 43
        status = await self.core.api_notification_status()
        self.assertEqual((status['registered_accounts'], status['connected_accounts'], status['pending_accounts']),
                         (0, 2, 2))
        self.core.accounts.services.clear()
        status = await self.core.api_notification_status()
        self.assertEqual((status['registered_accounts'], status['connected_accounts']), (0, 0))

    async def test_unknown_code_and_exception_text_never_cross_bridge(self):
        self.core.native_push_failed('APNs', 'unknown code with private payload')
        status = await self.core.api_notification_status()
        self.assertEqual(status['error'], 'registration_error')
        self.assertNotIn('private', repr(status))
        class UnknownError(Exception):
            def __str__(self):
                raise AssertionError('Do not format raw errors')
        self.assertEqual(self.core.push_error_code(UnknownError()), 'registration_error')

    async def test_success_clears_failure_phase(self):
        self.core.native_push_failed('APNs', 'TokenInvalidError', phase='telegram')
        await self.core.sync_push_registration()
        status = await self.core.api_notification_status()
        self.assertEqual((status['state'], status['phase'], status['error']), ('registered', None, None))

    async def test_generic_rpc_retains_only_confirmed_literal_code(self):
        for code in ('APP_PUSH_APIKEY_MISSING', 'TOKEN_EMPTY', 'TOKEN_INVALID',
                     'TOKEN_TYPE_INVALID', 'TOKEN_WAS_INVALIDATED'):
            with self.subTest(code=code):
                error = errors.BadRequestError(request=None, message=code)
                self.assertEqual(self.core.push_error_code(error), code)
                # The code is sanitized again when saved in the status.
                self.core.native_push_failed('APNs', self.core.push_error_code(error), phase='telegram')
                self.assertEqual((await self.core.api_notification_status())['error'], code)

    async def test_unlisted_or_decorated_rpc_message_is_never_exposed(self):
        for message in ('APP_PUSH_API_KEY_MISSING', 'APP_PUSH_APIKEY_MISSING private payload',
                        'private prefix TOKEN_INVALID', ' TOKEN_EMPTY', 'TOKEN_EMPTY\n',
                        'unknown private payload', {'TOKEN_INVALID': 'private'}, None):
            with self.subTest(message=message):
                error = errors.BadRequestError(request=None, message=message)
                self.assertEqual(self.core.push_error_code(error), 'BadRequestError')
                self.core.native_push_failed('APNs', self.core.push_error_code(error), phase='telegram')
                status = await self.core.api_notification_status()
                self.assertNotIn('private', repr(status))
                self.assertEqual(status['error'], 'BadRequestError')
        class LocalError(Exception):
            message = 'TOKEN_INVALID'
        self.assertEqual(self.core.push_error_code(LocalError()), 'registration_error')

    async def test_missing_provider_rpc_survives_registration_pipeline(self):
        self.client.side_effect = [True, errors.BadRequestError(request=None, message='APP_PUSH_APIKEY_MISSING')]
        await self.core.sync_push_registration()
        status = await self.core.api_notification_status()
        self.assertEqual((status['phase'], status['error'], status['registered_accounts']),
                         ('telegram', 'APP_PUSH_APIKEY_MISSING', 0))
        self.assertEqual(self.client.await_count, 2)
        self.assertLessEqual(self.core._push_check.when() - self.core.loop.time(), 5)
