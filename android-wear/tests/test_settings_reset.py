"""Reset the actual settings stores, never a login/session/message store."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from tg_ascii.i18n import set_language
from tg_ascii.preferences import DEFAULTS, Preferences, write_json
from tg_ascii_mobile.core import Core


class ResetSettingsTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        env = patch.dict('os.environ')
        env.start()
        self.addCleanup(env.stop)
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.addCleanup(set_language, 'en')
        self.core = c = Core(Path(temp.name), 'iOS')
        c.loop.close()
        c.loop = asyncio.get_running_loop()
        c.prefs = Preferences(c.root)
        c.accounts = SimpleNamespace(current='one', services={}, entries={'one': {}, 'two': {}})
        c.stage = 'ready'
        c.locked = False
        c.keep_connected = Mock()
        c.publish_wear_appearance = Mock()
        c.sync_push_registration = AsyncMock()
        c.native_notify_permission = Mock()
        c.native_display_name = Mock()
        c.native_home_name = Mock()
        c.prefs.save({'theme': 'light', 'language': 'es', 'font_size': 19, 'button_radius': 23,
                      'reduce_animations': True, 'notifications': False, 'app_display_name': 'Fixture',
                      'mobile_features': {'native_liquid_glass': True, 'media_originals': True},
                      'contact_round_avatar': False})
        c.save_appearance({**deepcopy(c.APPEARANCE), 'font': 'sf', 'layout': 'double',
                           'effects': {'bold': True}, 'swipe_right': 'archive',
                           'presentation': {'controls': 'icons'}})
        for account in c.accounts.entries:
            write_json(c.wallpaper_dir(account) / 'settings.json', {'_follow': True, 'all': {'file': 'test.jpg'}})
        self.kept = {}
        for name in ('accounts.json', 'one.session', 'two.session', 'messages.db', 'outbox.json', 'app-lock.json'):
            data = ('Synthetic protected record: ' + name).encode()
            path = c.root / name
            path.write_bytes(data)
            self.kept[path] = data

    def assert_accounts_preserved(self):
        self.assertEqual(self.core.accounts.current, 'one')
        self.assertEqual(set(self.core.accounts.entries), {'one', 'two'})
        for path, data in self.kept.items():
            self.assertEqual(path.read_bytes(), data, path.name)

    async def test_appearance_resets_only_its_own_controls(self):
        result = await self.core.api_reset_settings('appearance', 'one')
        self.assertEqual(result['settings']['theme'], DEFAULTS['theme'])
        self.assertEqual(result['settings']['font_size'], DEFAULTS['font_size'])
        self.assertEqual(result['appearance']['font'], '')
        self.assertEqual(result['appearance']['presentation']['controls'], 'brackets')
        self.assertEqual(result['settings']['button_radius'], 23)
        self.assertTrue(result['settings']['reduce_animations'])
        self.assertEqual(result['appearance']['swipe_right'], 'archive')
        self.assertTrue(self.core.chat_wallpapers('two')['_follow'])
        self.core.native_display_name.assert_called_with('')
        self.assert_accounts_preserved()

    async def test_customization_resets_backgrounds_effects_and_corners_only(self):
        result = await self.core.api_reset_settings('customization', 'one')
        self.assertEqual(result['settings']['button_radius'], 0)
        self.assertFalse(result['settings']['reduce_animations'])
        self.assertFalse(any(result['appearance']['effects'].values()))
        self.assertEqual(result['settings']['theme'], 'light')
        self.assertEqual(result['appearance']['font'], 'sf')
        self.assertEqual(result['appearance']['presentation']['controls'], 'icons')
        for account in ('one', 'two'):
            self.assertEqual(self.core.chat_wallpapers(account), {})
        self.assert_accounts_preserved()

    async def test_all_resets_preferences_features_and_siri_without_logout_or_new_permission(self):
        self.core.siri_vocabulary.accounts = {'one': [123], 'two': [456]}
        result = await self.core.api_reset_settings('all', 'one')
        self.assertEqual(Preferences(self.core.root).values, Preferences.validated(DEFAULTS))
        self.assertFalse(result['settings']['advanced_features']['native_liquid_glass'])
        self.assertFalse(result['settings']['advanced_features']['media_originals'])
        self.assertTrue(self.core.prefs.values['contact_round_avatar'])
        self.assertEqual(result['appearance']['swipe_right'], 'read')
        self.assertEqual(self.core.siri_vocabulary.accounts, {})
        self.core.native_notify_permission.assert_not_called()
        self.core.sync_push_registration.assert_awaited_once()
        self.assert_accounts_preserved()

    async def test_invalid_scope_wrong_account_and_lock_make_no_changes(self):
        before = self.core.prefs.path.read_bytes()
        for scope, account in (('sessions', 'one'), ('all', 'two')):
            with self.assertRaises(ValueError):
                await self.core.api_reset_settings(scope, account)
        self.core.locked = True
        with self.assertRaises(PermissionError):
            await self.core.api_reset_settings('all', 'one')
        self.assertEqual(self.core.prefs.path.read_bytes(), before)
        self.assert_accounts_preserved()

    async def test_native_icon_failure_keeps_other_preferences(self):
        icon = next(key for key in self.core.ICONS if key != 'default')
        await self.core.api_appearance({'icon': icon}, account='one')
        self.core.native_icon = lambda value, callback: callback(False)
        before = self.core.prefs.path.read_bytes()
        with self.assertRaises(RuntimeError):
            await self.core.api_reset_settings('all', 'one')
        self.assertEqual(self.core.prefs.path.read_bytes(), before)
        self.assertEqual(self.core.appearance()['icon'], icon)
        self.assert_accounts_preserved()
