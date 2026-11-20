"""Card preferences are safe local presentation, persisted with saved designs."""
import json
import tempfile
import tkinter as tk
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from tg_ascii.contact_appearance import (
    ACTIONS,
    CONTACT_DEFAULTS,
    SECTIONS,
    card_style,
    ordered_actions,
    ordered_sections,
    restore_contact_preferences,
    save_contact_preferences,
    validated_contact,
)
from tg_ascii.desktop_customization import DesktopCustomization
from tg_ascii.interface_store import InterfaceStore, appearance, default_layout
from tg_ascii.preferences import DEFAULTS, Preferences
from tg_ascii.themes import apply_local_appearance, apply_widget


class ContactAppearanceTests(unittest.TestCase):
    def test_default_matches_contract_and_has_no_io_or_tk_dependencies(self):
        with patch('builtins.open', side_effect=AssertionError('unexpected file IO')):
            style = card_style({})
            self.assertEqual((style['width'], style['avatar_size'], style['padding'], style['gap']), (620, 96, 16, 8))
            self.assertEqual(ordered_sections({}, SECTIONS), list(SECTIONS))
            self.assertEqual(ordered_actions({}, ACTIONS), list(ACTIONS))
            self.assertEqual(appearance(DEFAULTS).keys() & CONTACT_DEFAULTS.keys(), CONTACT_DEFAULTS.keys())

    def test_malformed_import_restores_safe_values_and_never_keeps_unknown_data(self):
        values = {'contact_card_width': 10**400, 'contact_avatar_size': True,
                  'contact_border_width': -1, 'contact_density': [], 'contact_alignment': {},
                  'contact_round_avatar': 'yes', 'contact_background': 'red',
                  'contact_text': '#A0B1C2', 'contact_accent': '#123456;command',
                  'contact_hidden_sections': ['settings', 'photos', 'photos', 'secrets', {}],
                  'contact_hidden_actions': ['manage', 'message'],
                  'contact_section_order': ['links', 'links', 'password', None],
                  'contact_action_order': ['refresh'], 'api_hash': 'never stored'}
        checked = Preferences.validated(values)
        self.assertEqual(checked['contact_card_width'], 620)
        self.assertEqual(checked['contact_avatar_size'], 96)
        self.assertEqual(checked['contact_density'], 'comfortable')
        self.assertEqual(checked['contact_alignment'], 'left')
        self.assertTrue(checked['contact_round_avatar'])
        self.assertEqual(checked['contact_text'], '#a0b1c2')
        self.assertEqual(checked['contact_background'], '')
        self.assertEqual(checked['contact_hidden_sections'], ['photos'])
        self.assertEqual(checked['contact_hidden_actions'], ['message'])
        self.assertEqual(checked['contact_section_order'], ['links', *(key for key in SECTIONS if key!='links')])
        self.assertNotIn('api_hash', checked)

    def test_visibility_only_filters_available_sections_and_actions(self):
        values = {'contact_section_order': ['links', 'photos'], 'contact_hidden_sections': ['info', 'settings'],
                  'contact_action_order': ['refresh', 'manage'], 'contact_hidden_actions': ['notifications', 'manage']}
        self.assertEqual(ordered_sections(values, ['info', 'links', 'settings']), ['links', 'settings'])
        self.assertEqual(ordered_actions(values, ['message', 'manage', 'notifications']), ['manage', 'message'])
        self.assertEqual(ordered_sections(values, []), [])
        self.assertEqual(ordered_actions(values, []), [])

    def test_density_changes_spacing_without_overriding_avatar_and_theme(self):
        for density, pair in [('compact', (8, 4)), ('comfortable', (16, 8)), ('spacious', (24, 12))]:
            style = card_style({'contact_density': density, 'contact_avatar_size': 144, 'theme': 'light'})
            self.assertEqual((style['padding'], style['gap']), pair)
            self.assertEqual(style['avatar_size'], 144)
            self.assertEqual(style['background'], '')

    def test_preference_lists_are_owned_and_validation_cannot_mutate_defaults(self):
        values = validated_contact({})
        values['contact_section_order'].reverse()
        values['contact_hidden_actions'].append('message')
        self.assertEqual(validated_contact({}), CONTACT_DEFAULTS)
        prefs = Preferences(demo=True)
        prefs.save(values)
        values['contact_section_order'].clear()
        self.assertEqual(prefs.values['contact_section_order'], list(reversed(SECTIONS)))

    def test_save_is_local_with_sync_on_or_off_and_reset_preserves_account_preferences(self):
        for enabled in (True, False):
            prefs = Preferences(demo=True)
            prefs.save({'sync_customizations': enabled, 'language': 'es', 'theme': 'light'})
            app = NS(preferences=prefs, service=Mock(), worker=Mock())
            callback = Mock()
            save_contact_preferences(app, {'contact_density': 'compact'}, callback)
            self.assertEqual(prefs.values['contact_density'], 'compact')
            callback.assert_called_once_with()
            restore_contact_preferences(app)
            self.assertEqual(prefs.values['contact_density'], 'comfortable')
            self.assertEqual(prefs.values['sync_customizations'], enabled)
            self.assertEqual(prefs.values['language'], 'es')
            self.assertEqual(prefs.values['theme'], 'light')
            self.assertEqual(app.service.mock_calls, [])
            self.assertEqual(app.worker.mock_calls, [])

    def test_saved_layout_and_restart_keep_contact_choices(self):
        with tempfile.TemporaryDirectory() as directory:
            prefs = Preferences(directory)
            prefs.save({'contact_density': 'compact', 'contact_section_order': ['links', 'photos'],
                        'contact_hidden_actions': ['message'], 'contact_accent': '#abcdef'})
            store = InterfaceStore(directory)
            path = store.save_profile('Card design', prefs.values)
            document = store.load(path)
            restore_contact_preferences(NS(preferences=prefs))
            prefs.save(document['appearance'])
            restarted = Preferences(directory)
            self.assertEqual(restarted.values['contact_density'], 'compact')
            self.assertEqual(restarted.values['contact_section_order'][:2], ['links', 'photos'])
            self.assertEqual(restarted.values['contact_hidden_actions'], ['message'])
            self.assertEqual(restarted.values['contact_accent'], '#abcdef')

    def test_global_recovery_includes_contact_defaults_without_contact_data(self):
        prefs = Preferences(demo=True)
        prefs.save({'contact_card_width': 960, 'contact_hidden_sections': ['info'], 'theme': 'light'})
        app = NS(preferences=prefs, interface_store=Mock(), show_error=Mock())
        with patch('tg_ascii.motion.restore_motion'):
            DesktopCustomization.restore_interface_defaults(app)
        self.assertEqual(validated_contact(prefs.values), CONTACT_DEFAULTS)
        self.assertEqual(prefs.values['theme'], DEFAULTS['theme'])
        app.interface_store.commit.assert_called_once_with(default_layout())
        app.show_error.assert_not_called()

    def test_editable_template_contains_only_supported_default_card_keys(self):
        root = Path(__file__).resolve().parents[1]
        raw = json.loads((root/'tg_ascii/interface_templates/contact-card.json').read_text(encoding='utf-8'))
        self.assertEqual(raw['appearance'], CONTACT_DEFAULTS)
        self.assertEqual(appearance(raw['appearance']), deepcopy(CONTACT_DEFAULTS))

    def test_local_header_color_and_border_survive_the_global_theme_pass(self):
        widget = Mock(spec=tk.Canvas)
        widget._corner_overlay = False
        widget._local_appearance = {'background': '#123456', 'highlightbackground': '#abcdef',
                                    'highlightcolor': '#abcdef', 'highlightthickness': 2}
        widget.winfo_children.return_value = []
        with patch('tg_ascii.themes._font_family', None), patch('tg_ascii.appearance.shape_widget') as shape:
            shape.side_effect = lambda canvas: canvas.configure(highlightthickness=7)
            apply_widget(widget)
        self.assertEqual(widget.configure.call_args.kwargs, widget._local_appearance)

    def test_local_style_hook_never_accepts_commands_or_invalid_tk_options(self):
        widget = Mock(_local_appearance={'command': 'exec', 'background': 'not a color',
                                        'highlightthickness': 100, 'foreground': '#aabbcc'})
        apply_local_appearance(widget)
        widget.configure.assert_called_once_with(foreground='#aabbcc')


if __name__ == '__main__':
    unittest.main()
