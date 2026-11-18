import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace

from tg_ascii.accounts import Accounts
from tg_ascii.desktop_service import DesktopService
from tg_ascii.preferences import DEFAULTS, Preferences, read_json


class ServiceRobustnessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.client = Mock(connect=AsyncMock(), disconnect=AsyncMock(),
                           is_user_authorized=AsyncMock(return_value=False))
        self.service = DesktopService(root=self.folder.name,
                                      client_factory=lambda *a, **k: self.client)
        self.addAsyncCleanup(self.service.close)

    async def test_connected_socket_with_stalled_authorization_times_out(self):
        async def never():
            await asyncio.Event().wait()
        self.client.is_user_authorized.side_effect = never
        with patch('tg_ascii.desktop_service.CONNECT_TIMEOUT', 0.01):
            with self.assertRaises(TimeoutError):
                await self.service.connect((12345, 'a' * 32))
        self.client.disconnect.assert_awaited_once()
        self.assertIsNone(self.service.client)

    async def test_cleanup_failure_does_not_hide_connection_failure(self):
        self.client.connect.side_effect = ConnectionError('original failure')
        self.client.disconnect.side_effect = OSError('cleanup failure')
        with self.assertRaisesRegex(ConnectionError, 'original failure'):
            await self.service.connect((12345, 'a' * 32))
        self.assertIsNone(self.service.client)

    async def test_code_request_times_out_without_resending_or_storing_code(self):
        await self.service.connect((12345, 'a' * 32))
        async def never(phone):
            await asyncio.Event().wait()
        self.client.send_code_request = AsyncMock(side_effect=never)
        with patch('tg_ascii.desktop_service.AUTH_TIMEOUT', 0.01):
            with self.assertRaises(TimeoutError):
                await self.service.request_code('+34612345678')
        self.client.send_code_request.assert_awaited_once()
        self.assertIsNone(self.service.code_hash)

    async def test_ready_is_idempotent_and_close_clears_state(self):
        self.client.is_user_authorized.return_value = True
        await self.service.connect((12345, 'a' * 32))
        backend, recovery = self.service.backend, self.service.recovery
        self.client.add_event_handler.reset_mock()
        self.assertEqual(self.service.ready(), 'ready')
        self.assertIs(self.service.backend, backend)
        self.assertIs(self.service.recovery, recovery)
        self.client.add_event_handler.assert_not_called()
        backend.close = AsyncMock()
        await self.service.close()
        await self.service.close()
        backend.close.assert_awaited_once()
        self.assertIsNone(self.service.backend)
        self.assertIsNone(self.service.client)
        self.assertTrue(recovery.closed)

    async def test_stalled_disconnect_is_bounded(self):
        await self.service.connect((12345, 'a' * 32))
        async def never():
            await asyncio.Event().wait()
        self.client.disconnect.side_effect = never
        with patch('tg_ascii.desktop_service.DISCONNECT_TIMEOUT', 0.01):
            with self.assertRaises(TimeoutError):
                await self.service.close()
        self.assertIsNone(self.service.client)


class SettingsRobustnessTests(unittest.TestCase):
    def test_invalid_container_values_do_not_crash_startup(self):
        for bad in ([], {}, ['en'], {'nested': 'value'}):
            with self.subTest(value=bad):
                values = Preferences.validated({'language': bad, 'logo_variant': bad})
                self.assertEqual(values['language'], DEFAULTS['language'])
                self.assertEqual(values['logo_variant'], DEFAULTS['logo_variant'])

    def test_deep_or_oversized_json_falls_back(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            path.write_text('{"nested":' + '[' * 2000 + '0' + ']' * 2000 + '}', encoding='utf-8')
            self.assertEqual(read_json(path, {'safe': True}), {'safe': True})
            path.write_text('{"large":"' + 'a' * 1024 + '"}', encoding='utf-8')
            with patch('tg_ascii.preferences.MAX_SETTINGS_BYTES', 100):
                self.assertEqual(read_json(path, {'safe': True}), {'safe': True})

    def test_unchanged_preferences_do_not_fsync_again(self):
        with tempfile.TemporaryDirectory() as folder:
            preferences = Preferences(folder)
            with patch('tg_ascii.preferences.write_json') as write:
                preferences.save({'font_size': preferences.values['font_size']})
                write.assert_not_called()
                preferences.save({'font_size': 16})
                write.assert_called_once()


class AccountRobustnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_malformed_active_account_falls_back(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'accounts.json'
            path.write_text('{"active": [], "accounts": {"account": {}}}', encoding='utf-8')
            self.assertEqual(Accounts(root=folder).current, 'account')

    async def test_unchanged_registry_does_not_write_again(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = Accounts(root=folder)
            with patch('tg_ascii.accounts.write_json') as write:
                manager.persist()
                write.assert_not_called()
                manager.entries['account'] = {'label': 'New', 'user_id': 1}
                manager.persist()
                manager.persist()
                write.assert_called_once()

    async def test_background_sessions_restore_in_parallel_with_a_limit(self):
        active = peak = 0
        started = []
        def factory(**kwargs):
            key = kwargs['session_path'].parent.name
            async def connect(*args):
                nonlocal active, peak
                started.append(key)
                active += 1
                peak = max(peak, active)
                try:
                    await asyncio.sleep(.01)
                    if key == '1' * 32:
                        raise ConnectionError('offline')
                    return 'ready'
                finally:
                    active -= 1
            return SimpleNamespace(connect=connect)
        with tempfile.TemporaryDirectory() as folder:
            manager = Accounts(demo=True, root=folder, factory=factory)
            manager.entries.update({str(i) * 32: {} for i in range(1, 8)})
            await asyncio.gather(manager.restore_saved(), manager.restore_saved())
            self.assertEqual(peak, 3)
            self.assertEqual(len(started), 7)
            self.assertEqual(len(set(started)), 7)
            self.assertIn('1' * 32, manager.failures)
            self.assertEqual(manager.labels['7' * 32], 'Demo')

    async def test_profile_registration_has_a_deadline(self):
        async def never():
            await asyncio.Event().wait()
        with tempfile.TemporaryDirectory() as folder:
            manager = Accounts(root=folder)
            manager.services['account'] = SimpleNamespace(
                client=SimpleNamespace(get_me=AsyncMock(side_effect=never)))
            with patch('tg_ascii.accounts.ACCOUNT_RPC_TIMEOUT', .01):
                with self.assertRaises(TimeoutError):
                    await manager.register('account')


if __name__ == '__main__':
    unittest.main()
