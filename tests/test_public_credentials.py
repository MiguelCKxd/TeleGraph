"""Public builds must boot without a network or a publisher credential."""
import ctypes as C
import importlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType
from unittest import TestCase, IsolatedAsyncioTestCase, skipUnless
from unittest.mock import AsyncMock, patch

from tg_ascii_mobile.core import Core
from tg_ascii_mobile import ios_credentials

FIXTURE_ID = 12345
FIXTURE_HASH = 'ab' * 16


class PublicPhoneTests(IsolatedAsyncioTestCase):
    def new_core(self, directory):
        app = Core(directory, 'iOS', 'es')
        self.addCleanup(app.loop.close)
        return app

    async def test_setup_restart_and_edit(self):
        state = {}

        def save(keys):
            state['keychain'] = keys

        with TemporaryDirectory() as directory, patch.dict(sys.modules, {'tg_ascii._app_credentials': None}), \
                patch.object(ios_credentials, 'load', lambda: state.get('keychain')), \
                patch.object(ios_credentials, 'save', save):
            client = AsyncMock()
            client.is_user_authorized.return_value = False
            with patch.object(Core, 'client_factory', return_value=client) as factory:
                first = self.new_core(directory)
                await first._boot()
                self.assertEqual(first.stage, 'credentials')
                with self.assertRaises(ValueError):
                    await first.call('login.credentials', {'api_id': 'bad', 'api_hash': FIXTURE_HASH})
                factory.assert_not_called()
                self.assertFalse(state)
                self.assertTrue(await first.call('login.credentials', {'api_id': FIXTURE_ID, 'api_hash': FIXTURE_HASH}))
                self.assertEqual(first.stage, 'phone')
                self.assertFalse((Path(directory) / 'config.json').exists())
                self.assertNotIn(FIXTURE_HASH, json.dumps(first.state_snapshot()))
                again = self.new_core(directory)
                await again._boot()
                self.assertEqual(again.stage, 'phone')
                self.assertEqual(factory.call_args.args[1:3], (FIXTURE_ID, FIXTURE_HASH))
                self.assertTrue(await again.call('login.edit_credentials', {}))
                self.assertEqual(again.stage, 'credentials')

    async def test_empty_and_bundled_modules(self):
        for included in (False, True):
            module = ModuleType('tg_ascii._app_credentials')
            if included:
                module.API_ID, module.API_HASH = FIXTURE_ID, FIXTURE_HASH
            with self.subTest(included=included), TemporaryDirectory() as directory, \
                    patch.dict(sys.modules, {'tg_ascii._app_credentials': module}), \
                    patch.object(ios_credentials, 'load', return_value=None) as load:
                app = self.new_core(directory)
                client = AsyncMock()
                client.is_user_authorized.return_value = False
                with patch.object(Core, 'client_factory', return_value=client) as new_client:
                    await app._boot()
                    self.assertEqual(app.stage, 'phone' if included else 'credentials')
                    self.assertEqual(new_client.called, included)
                    self.assertEqual(load.called, not included)
                    self.assertEqual(app.personal_api, not included)
                    if included:
                        self.assertFalse(await app.call('login.edit_credentials', {}))


class PublicWatchTests(IsolatedAsyncioTestCase):
    async def test_absent_empty_bundled_and_rehydrated_keys(self):
        source = Path(__file__).resolve().parents[1] / 'watch' / 'python' / 'tgwatch' / '__init__.py'
        spec = importlib.util.spec_from_file_location('fixture_tgwatch', source)

        def launch():
            watch = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(watch)
            return watch

        for bundled in (None, ModuleType('_app_credentials')):
            with self.subTest(module=bundled), patch.dict(sys.modules, {'_app_credentials': bundled}):
                for _ in range(2):  # Reset the Python engine as happens on a relaunch.
                    watch = launch()
                    self.assertTrue(await watch._handle({'op': 'uses_personal_api'}))
                    with self.assertRaises(ValueError):
                        await watch._handle({'op': 'configure_api', 'api_id': 1, 'api_hash': ''})
                    self.assertTrue(await watch._handle({'op': 'configure_api', 'api_id': FIXTURE_ID, 'api_hash': FIXTURE_HASH}))
                    client = AsyncMock()
                    client.is_connected = lambda: True
                    client.is_user_authorized.return_value = False
                    with patch('telethon.TelegramClient', return_value=client) as factory:
                        self.assertEqual(await watch._handle({'op': 'status'}), {'authorized': False, 'name': ''})
                        self.assertEqual(factory.call_args.args[1:], (FIXTURE_ID, FIXTURE_HASH))
        module = ModuleType('_app_credentials')
        module.API_ID, module.API_HASH = FIXTURE_ID, FIXTURE_HASH
        with patch.dict(sys.modules, {'_app_credentials': module}):
            watch = launch()
            self.assertFalse(await watch._handle({'op': 'uses_personal_api'}))
            self.assertFalse(await watch._handle({'op': 'configure_api'}))


@skipUnless(sys.platform == 'darwin', 'uses CoreFoundation for fixture dictionaries')
class KeychainQueryTests(TestCase):
    def test_native_query_and_protection_without_accessing_real_keychain(self):
        cf, security = ios_credentials._libraries()
        cf.CFDictionaryGetValue.argtypes = [C.c_void_p, C.c_void_p]
        cf.CFDictionaryGetValue.restype = C.c_void_p
        slot = []

        def constant(name):
            return C.c_void_p.in_dll(security, name).value

        def lookup(query, name):
            return cf.CFDictionaryGetValue(query, constant(name))

        def copy(query, result):
            self.assertEqual(lookup(query, 'kSecClass'), constant('kSecClassGenericPassword'))
            self.assertTrue(lookup(query, 'kSecReturnData'))
            if not slot:
                return -25300
            C.cast(result, C.POINTER(C.c_void_p))[0] = cf.CFDataCreate(None, slot[0], len(slot[0]))
            return 0

        def store(query, changes):
            self.assertTrue(lookup(query, 'kSecAttrService'))
            self.assertTrue(lookup(query, 'kSecAttrAccount'))
            self.assertEqual(lookup(changes, 'kSecAttrAccessible'), constant('kSecAttrAccessibleWhenUnlockedThisDeviceOnly'))
            data = lookup(changes, 'kSecValueData')
            slot[:] = [C.string_at(cf.CFDataGetBytePtr(data), cf.CFDataGetLength(data))]
            return 0

        def delete(query):
            self.assertTrue(lookup(query, 'kSecAttrService'))
            slot.clear()
            return 0

        with patch.object(security, 'SecItemCopyMatching', copy), \
                patch.object(security, 'SecItemAdd', lambda query, _: store(query, query)), \
                patch.object(security, 'SecItemUpdate', lambda query, changes: store(query, changes) if slot else -25300), \
                patch.object(security, 'SecItemDelete', delete):
            self.assertIsNone(ios_credentials.load())
            ios_credentials.save((1, '11' * 16))
            ios_credentials.save((FIXTURE_ID, FIXTURE_HASH))
            self.assertEqual(ios_credentials.load(), (FIXTURE_ID, FIXTURE_HASH))
            ios_credentials.delete()
            self.assertIsNone(ios_credentials.load())
