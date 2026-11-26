"""The same appearance API used by users must retain and reset local choices."""
import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from tg_ascii.preferences import Preferences
from tg_ascii_mobile.core import Core


class PresentationSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.core = Core(Path(self.directory.name), 'iOS')
        self.core.loop.close()
        self.core.loop = asyncio.get_running_loop()
        self.core.prefs = Preferences(self.core.root)
        self.core.accounts = SimpleNamespace(current='fixture', services={})
        self.core.locked = False

    async def test_user_settings_survive_reload_and_reset_preserves_font_and_corners(self):
        await self.core.api_appearance({'font': 'sf'})
        await self.core.api_settings({'button_radius': 18})
        choice = {'controls':'icons', 'navigation':'tabs', 'title_color':'#123ABC', 'avatar_size':56,
                  'show_online':False, 'private_sender_names':False, 'list_title':'Mis chats'}
        saved = await self.core.api_appearance({'presentation':choice})
        self.assertEqual(saved['presentation']['title_color'], '#123abc')
        self.assertEqual(self.core.stored_appearance()['presentation'], saved['presentation'])
        reloaded = self.core.appearance()['presentation']
        self.assertEqual(reloaded['navigation'], 'tabs')
        self.assertEqual(reloaded['list_title'], 'Mis chats')
        reset = await self.core.api_appearance({'presentation':{}})
        self.assertEqual(reset['presentation']['controls'], 'brackets')
        self.assertEqual(reset['presentation']['navigation'], 'menu')
        self.assertEqual(reset['font'], 'sf')
        self.assertEqual(self.core.prefs.values['button_radius'], 18)

    async def test_invalid_import_cannot_inject_styles_or_unbounded_dimensions(self):
        result = await self.core.api_appearance({'presentation':{
            'title_color':'url(https://invalid.test)', 'avatar_size':1000000, 'row_height':True,
            'show_online':'false', 'navigation':'script', 'private_data':'discard', 'list_title':'x'*500}})
        stored = result['presentation']
        self.assertEqual(stored['title_color'], '')
        self.assertEqual(stored['avatar_size'], 0)
        self.assertEqual(stored['row_height'], 0)
        self.assertTrue(stored['show_online'])
        self.assertEqual(stored['navigation'], 'menu')
        self.assertNotIn('private_data', stored)
        self.assertEqual(len(stored['list_title']), 80)
