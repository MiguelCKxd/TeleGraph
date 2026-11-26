import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from tg_ascii.preferences import Preferences
from tg_ascii_mobile.core import Core
from tg_ascii_mobile.presentation import DEFAULTS, OPTIONAL_RANGES, validated


class ExpandedPresentationTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.core = Core(Path(temporary.name), 'iOS')
        self.core.loop.close()
        self.core.loop = asyncio.get_running_loop()
        self.core.prefs = Preferences(self.core.root)
        self.core.accounts = NS(current='fixture', services={}, entries={'fixture': {}})
        self.core.stage = 'ready'
        self.core.keep_connected = Mock()
        self.core.apply_settings_changes = AsyncMock()
        self.core.publish_wear_appearance = Mock()

    async def test_independent_sizes_spacing_visibility_and_colors_persist_through_disk_reload(self):
        values = {'message_font_size': 24, 'header_font_size': 27, 'name_font_size': 20,
                  'preview_font_size': 18, 'metadata_font_size': 12, 'message_line_height': 170,
                  'message_gap': 11, 'message_padding_x': 17, 'message_padding_y': 9,
                  'button_height': 56, 'preview_lines': 3, 'bubble_alignment': 'center',
                  'list_avatars': False, 'list_times': False, 'list_badges': False,
                  'incoming_text_color': '#123ABC', 'outgoing_text_color': '#456DEF',
                  'incoming_metadata_color': '#abcdef', 'outgoing_metadata_color': '#987654'}
        result = await self.core.api_appearance({'presentation': values}, account='fixture')
        expected = {**values, 'incoming_text_color': '#123abc', 'outgoing_text_color': '#456def'}
        fresh = Core(self.core.root, 'iOS')
        self.addCleanup(fresh.loop.close)
        fresh.prefs, fresh.accounts = Preferences(self.core.root), self.core.accounts
        for key, value in expected.items():
            self.assertEqual(result['presentation'][key], value)
            self.assertEqual(fresh.appearance()['presentation'][key], value)
        self.assertEqual(self.core.prefs.values['font_size'], Preferences(self.core.root).values['font_size'])

    async def test_zero_inherits_and_invalid_dimensions_colors_and_alignment_are_discarded(self):
        for key, (low, high) in OPTIONAL_RANGES.items():
            for value in (0, low, high):
                self.assertEqual(validated({key: value})[key], value)
            for value in (-1, 1, high + 1, True, '24', 24.5, float('nan')):
                self.assertEqual(validated({key: value})[key], 0, (key, value))
        result = validated({'button_height': 12, 'preview_lines': 100, 'list_avatars': 'false',
                            'incoming_text_color': 'url(private)', 'outgoing_metadata_color': '#fff',
                            'bubble_alignment': 'absolute'})
        self.assertEqual(result['button_height'], 44)
        self.assertEqual(result['preview_lines'], 1)
        self.assertTrue(result['list_avatars'])
        self.assertEqual(result['incoming_text_color'], '')
        self.assertEqual(result['outgoing_metadata_color'], '')
        self.assertEqual(result['bubble_alignment'], 'direction')

    async def test_composition_reset_preserves_existing_fonts_radii_and_bubble_backgrounds(self):
        self.core.prefs.save({'button_radius': 19, 'bubble_radius': 23, 'bubble_in_color': '#224466'})
        await self.core.api_appearance({'font': 'sf', 'presentation': {'message_font_size': 28,
            'incoming_text_color': '#fedcba', 'preview_lines': 4}}, account='fixture')
        result = await self.core.api_appearance({'presentation': {}}, account='fixture')
        self.assertEqual(result['presentation'], DEFAULTS)
        self.assertEqual(result['font'], 'sf')
        self.assertEqual(self.core.prefs.values['button_radius'], 19)
        self.assertEqual(self.core.prefs.values['bubble_radius'], 23)
        self.assertEqual(self.core.prefs.values['bubble_in_color'], '#224466')

    async def test_global_appearance_reset_includes_new_controls_without_touching_accounts(self):
        sentinel = self.core.root / 'fixture.session'
        sentinel.write_bytes(b'synthetic account sentinel')
        await self.core.api_appearance({'presentation': {'message_font_size': 28, 'preview_lines': 4,
            'list_times': False, 'outgoing_metadata_color': '#aabbcc'}}, account='fixture')
        result = await self.core.api_reset_settings('appearance', 'fixture')
        self.assertEqual(result['appearance']['presentation'], DEFAULTS)
        self.assertEqual(sentinel.read_bytes(), b'synthetic account sentinel')
        self.assertEqual(self.core.accounts.current, 'fixture')
