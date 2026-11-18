import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
from telethon import errors
from tg_ascii.auth import authenticate, get_credentials, load_credentials, normalize_phone, save_credentials, SetupError


class ConfigTests(unittest.TestCase):
    def test_phone_formats(self):
        self.assertEqual(normalize_phone('+34 612 345 678'), '+34612345678')
        self.assertEqual(normalize_phone('+56 (9) 1234-5678'), '+56912345678')
        self.assertEqual(normalize_phone('0034 612345678'), '+34612345678')
        for value in ['not-a-phone', '123', '+34hello', '0044', '+0123456789', '612345678']:
            with self.assertRaises(ValueError): normalize_phone(value)

    def test_saved_config_is_private_and_skips_prompts(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            credentials = (12345, 'a' * 32)
            save_credentials(root, credentials)
            self.assertEqual(load_credentials(root), credentials)
            self.assertEqual(set(json.loads((root / 'config.json').read_text(encoding='utf-8'))), {'api_id', 'api_hash'})
            if os.name == 'posix':
                self.assertEqual(stat.S_IMODE((root / 'config.json').stat().st_mode), 0o600)
            self.assertEqual(list(root.glob('*.tmp')), [])
            def unexpected(_): self.fail('No solicitar datos guardados')
            self.assertEqual(get_credentials(root, read=unexpected, secret=unexpected), (credentials, False))

    def test_validation_and_no_save_without_consent(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            values, hashes = iter(['abc', '0', '12345', 'n']), iter(['broken', 'b' * 32])
            credentials, remember = get_credentials(Path(tmp), read=lambda _: next(values), secret=lambda _: next(hashes), write=lambda _: None)
            self.assertEqual(credentials, (12345, 'b' * 32))
            self.assertFalse(remember)
            self.assertFalse((Path(tmp) / 'config.json').exists())

    def test_corrupt_config_can_be_reconfigured(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            (root / 'config.json').write_text('broken-json', encoding='utf-8')
            with self.assertRaises(SetupError): load_credentials(root)
            values = iter(['12345', 's'])
            result, remember = get_credentials(root, configure=True, read=lambda _: next(values), secret=lambda _: 'c' * 32, write=lambda _: None)
            self.assertTrue(remember)
            self.assertEqual(result[0], 12345)


class LoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_session_skips_otp(self):
        client = SimpleNamespace(is_user_authorized=AsyncMock(return_value=True))
        await authenticate(client, read=lambda _: self.fail('No solicitar telefono'))

    async def test_phone_code_and_2fa_retries(self):
        client = SimpleNamespace(is_user_authorized=AsyncMock(return_value=False),
            send_code_request=AsyncMock(side_effect=[errors.PhoneNumberInvalidError(None), SimpleNamespace(phone_code_hash='test')]),
            sign_in=AsyncMock(side_effect=[errors.PhoneCodeInvalidError(None), errors.SessionPasswordNeededError(None), errors.PasswordHashInvalidError(None), object()]))
        phones = iter(['+34612345678', '+34612345679'])
        secrets = iter(['11111', '22222', 'incorrect-test-password', 'correct-test-password'])
        await authenticate(client, read=lambda _: next(phones), secret=lambda _: next(secrets), write=lambda _: None)
        self.assertEqual(client.send_code_request.call_count, 2)
        self.assertEqual(client.send_code_request.call_args_list[0].args[0], '+34612345678')
        self.assertEqual(client.sign_in.call_count, 4)

    async def test_expired_code_does_not_resend_in_loop(self):
        client = SimpleNamespace(is_user_authorized=AsyncMock(return_value=False), send_code_request=AsyncMock(return_value=SimpleNamespace(phone_code_hash='test')), sign_in=AsyncMock(side_effect=errors.PhoneCodeExpiredError(None)))
        with self.assertRaises(SetupError):
            await authenticate(client, read=lambda _: '+34612345678', secret=lambda _: '11111', write=lambda _: None)
        self.assertEqual(client.send_code_request.call_count, 1)
