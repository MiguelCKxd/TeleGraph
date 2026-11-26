import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from telethon import errors

from tg_ascii.auth import load_credentials, normalize_phone, save_credentials, SetupError
from tg_ascii.desktop_service import DesktopService


def login_service(root, authorized=False):
    client = SimpleNamespace(connect=AsyncMock(), disconnect=AsyncMock(), send_code_request=AsyncMock(),
                             is_user_authorized=AsyncMock(return_value=authorized), sign_in=AsyncMock())
    return DesktopService(root=root, client_factory=Mock(return_value=client)), client


class ConfigTests(unittest.IsolatedAsyncioTestCase):
    def test_phone_formats(self):
        self.assertEqual(normalize_phone('+34 612 345 678'), '+34612345678')
        self.assertEqual(normalize_phone('+56 (9) 1234-5678'), '+56912345678')
        self.assertEqual(normalize_phone('0034 612345678'), '+34612345678')
        for value in ['not-a-phone', '123', '+34hello', '0044', '+0123456789', '612345678']:
            with self.assertRaises(ValueError):
                normalize_phone(value)

    async def test_saved_config_is_private_and_opens_the_phone_form(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True), \
                patch('tg_ascii.desktop_service.bundled_credentials', return_value=None):
            root = Path(tmp)
            credentials = (12345, 'a' * 32)
            save_credentials(root, credentials)
            self.assertEqual(load_credentials(root), credentials)
            self.assertEqual(set(json.loads((root / 'config.json').read_text(encoding='utf-8'))), {'api_id', 'api_hash'})
            if os.name == 'posix':
                self.assertEqual(stat.S_IMODE((root / 'config.json').stat().st_mode), 0o600)
            self.assertEqual(list(root.glob('*.tmp')), [])
            service, _ = login_service(root)
            self.assertEqual(await service.connect(), 'phone')
            self.assertEqual(service.credentials, credentials)

    async def test_validation_and_no_save_without_consent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service, _ = login_service(root)
            for credentials in [('abc', 'b' * 32), (0, 'b' * 32), (12345, 'broken')]:
                with self.assertRaises(ValueError):
                    await service.connect(credentials)
            service.client_factory.assert_not_called()
            self.assertEqual(await service.connect((12345, 'b' * 32), remember=False), 'phone')
            self.assertFalse(service.remember)
            self.assertFalse((root / 'config.json').exists())

    async def test_corrupt_config_returns_to_credentials_and_can_be_reconfigured(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True), \
                patch('tg_ascii.desktop_service.bundled_credentials', return_value=None):
            root = Path(tmp)
            (root / 'config.json').write_text('broken-json', encoding='utf-8')
            with self.assertRaises(SetupError):
                load_credentials(root)
            service, _ = login_service(root)
            self.assertEqual(await service.connect(), 'credentials')
            self.assertEqual(await service.connect(configure=True), 'credentials')
            self.assertEqual(await service.connect((12345, 'c' * 32), remember=True), 'phone')
            self.assertTrue(service.remember)


class LoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_session_skips_otp(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, client = login_service(Path(tmp), authorized=True)
            with patch.object(service, 'ready', return_value='ready') as ready:
                self.assertEqual(await service.connect((12345, 'a' * 32)), 'ready')
                ready.assert_called_once_with()
            client.send_code_request.assert_not_awaited()

    async def test_phone_code_and_2fa_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, client = login_service(Path(tmp))
            await service.connect((12345, 'a' * 32))
            user = object()
            client.send_code_request.side_effect = [errors.PhoneNumberInvalidError(None),
                                                    SimpleNamespace(phone_code_hash='test-hash')]
            client.sign_in.side_effect = [errors.PhoneCodeInvalidError(None), errors.SessionPasswordNeededError(None),
                                          errors.PasswordHashInvalidError(None), user]
            with self.assertRaises(errors.PhoneNumberInvalidError):
                await service.request_code('+34 612 345 678')
            self.assertEqual(await service.request_code('+34 612 345 679'), 'code')
            self.assertEqual(client.send_code_request.await_args.args, ('+34612345679',))
            with self.assertRaises(errors.PhoneCodeInvalidError):
                await service.verify_code('11 111')
            self.assertEqual(await service.verify_code('22-222'), 'password')
            client.sign_in.assert_awaited_with(phone='+34612345679', code='22222', phone_code_hash='test-hash')
            with self.assertRaises(errors.PasswordHashInvalidError):
                await service.verify_password('incorrect')
            with patch.object(service, 'ready', return_value='ready') as ready:
                self.assertEqual(await service.verify_password('correct'), 'ready')
                ready.assert_called_once_with(user)
            self.assertEqual(client.sign_in.await_count, 4)
            self.assertEqual(client.send_code_request.await_count, 2)

    async def test_expired_code_does_not_resend_in_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, client = login_service(Path(tmp))
            await service.connect((12345, 'a' * 32))
            client.send_code_request.return_value = SimpleNamespace(phone_code_hash='expired')
            client.sign_in.side_effect = errors.PhoneCodeExpiredError(None)
            await service.request_code('+34612345678')
            with self.assertRaises(errors.PhoneCodeExpiredError):
                await service.verify_code('11111')
            client.send_code_request.assert_awaited_once()
