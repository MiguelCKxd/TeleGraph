from copy import deepcopy
import tempfile
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace as NS
from unittest import TestCase
from unittest.mock import Mock, patch

from tg_ascii.appearance import app_palette, configure_shapes
from tg_ascii.backend import Message
from tg_ascii.bubbles import BubbleView
from tg_ascii.desktop_customization import DesktopCustomization
from tg_ascii.interface_store import InterfaceStore, appearance
from tg_ascii.preferences import DEFAULTS, LAYOUT_RANGES, PALETTE_OVERRIDES, Preferences


class Appearance341Tests(TestCase):
    def test_every_new_value_roundtrips_preferences_and_saved_design_and_resets(self):
        values = {key: bounds[1] for key, bounds in LAYOUT_RANGES.items()}
        values.update({key: '#123abc' for key in PALETTE_OVERRIDES})
        values.update(bubble_in_color='#112233', bubble_out_color='#aabbcc')
        with tempfile.TemporaryDirectory() as directory:
            prefs = Preferences(directory)
            prefs.save(values)
            self.assertEqual({key: Preferences(directory).values[key] for key in values}, values)
            store = InterfaceStore(directory)
            document = store.load(store.save_profile('Spacing', prefs.values))
            self.assertEqual({key: document['appearance'][key] for key in values}, values)
            app = NS(preferences=prefs, interface_store=store, show_error=Mock())
            with patch('tg_ascii.motion.restore_motion'):
                DesktopCustomization.restore_interface_defaults(app)
            self.assertEqual({key: Preferences(directory).values[key] for key in values},
                             {key: DEFAULTS[key] for key in values})
            app.show_error.assert_not_called()

    def test_malformed_import_cannot_create_unbounded_widgets_or_colors(self):
        for bad in (True, 10**400, float('nan'), -1, '42', []):
            values = Preferences.validated({key: bad for key in LAYOUT_RANGES})
            self.assertEqual({key: values[key] for key in LAYOUT_RANGES},
                             {key: DEFAULTS[key] for key in LAYOUT_RANGES})
        checked = appearance({key: '#ffffff; bad' for key in PALETTE_OVERRIDES})
        self.assertEqual(checked, {key: '' for key in PALETTE_OVERRIDES})

    def test_independent_palette_does_not_override_unselected_roles(self):
        base = app_palette(DEFAULTS)
        for key, role in PALETTE_OVERRIDES.items():
            changed = app_palette({**DEFAULTS, key: '#123abc'})
            self.assertEqual(changed[role], '#123abc')
            self.assertEqual({k: v for k, v in changed.items() if k != role},
                             {k: v for k, v in base.items() if k != role})


class Appearance341TkTests(TestCase):
    def setUp(self):
        self.root = tk.Tk(); self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def test_button_padding_changes_real_widget_and_does_not_accumulate_with_effects(self):
        style = ttk.Style(self.root); style.theme_use('clam')
        values = deepcopy(DEFAULTS)
        button = ttk.Button(self.root, text='Example')
        configure_shapes(self.root, style, values, app_palette(values))
        self.root.update_idletasks()
        initial = (button.winfo_reqwidth(), button.winfo_reqheight())
        values.update(button_padding_x=30, button_padding_y=18, button_border_width=2, button_shadow_size=3)
        configure_shapes(self.root, style, values, app_palette(values))
        self.root.update_idletasks()
        bigger = (button.winfo_reqwidth(), button.winfo_reqheight())
        self.assertGreater(bigger[0], initial[0]); self.assertGreater(bigger[1], initial[1])
        for _ in range(30):
            configure_shapes(self.root, style, values, app_palette(values))
        self.root.update_idletasks()
        self.assertEqual((button.winfo_reqwidth(), button.winfo_reqheight()), bigger)
        configure_shapes(self.root, style, DEFAULTS, app_palette(DEFAULTS))
        self.root.update_idletasks()
        self.assertEqual((button.winfo_reqwidth(), button.winfo_reqheight()), initial)

    def test_message_geometry_changes_and_cached_nodes_are_rebuilt(self):
        values = deepcopy(DEFAULTS); values.update(bubbles=True, animated_emoji=False)
        app = NS(preferences=NS(values=values), font_family='Arial', ui_account='a', active=1,
                 message_actions=Mock(), reply_message=Mock(), quick_react=Mock(),
                 message_accent=lambda m: ('#123abc',), text_display=lambda text, *args: text,
                 draw_bubble_wallpaper=Mock(), reply_cache={})
        view = BubbleView(self.root, app, width=800, height=600)
        self.addCleanup(view.destroy)
        # The hidden test window has no real layout width; its canvas primitives
        # and fonts are real, with a deterministic viewport width for wrapping.
        view.winfo_width = lambda: 800
        messages = [Message(1, 'A', 'word ' * 80, '12:34'), Message(2, 'B', 'Second', '12:35')]
        view.render(messages)
        initial_height = view._nodes[1]['height']
        initial_epoch = view.generation
        values.update(message_line_spacing=10, bubble_gap=40, bubble_width_percent=40, bubble_width_limit=260)
        view.render(messages)
        self.assertGreater(view._nodes[1]['height'], initial_height)
        self.assertGreater(view.generation, initial_epoch)
        changed_height = view._nodes[1]['height']
        view.render(messages)
        self.assertEqual(view._nodes[1]['height'], changed_height)
        values.update({key: DEFAULTS[key] for key in LAYOUT_RANGES})
        view.render(messages)
        self.assertEqual(view._nodes[1]['height'], initial_height)
        values.update(bubble_width_percent=100,bubble_width_limit=2000)
        view.render(messages)
        self.assertLessEqual(view.bbox('message:1')[2],800)
