"""1.5.1: Settings › Menus (device or app menus)."""
import unittest
from unittest.mock import Mock, patch

from tg_ascii import menu_style
from tg_ascii.preferences import Preferences


ON = {'advanced_features': {'custom_menus': True}}


def on(**values):
    return {**ON, **values}


class MenuStyleTests(unittest.TestCase):
    def tearDown(self):
        menu_style.configure({})

    def test_default_is_exactly_the_previous_behaviour(self):
        menu_style.configure(on())
        self.assertEqual(menu_style.choice('context_menu'), 'system')
        self.assertEqual(menu_style.choice('file_picker'), 'system')
        self.assertEqual(menu_style.choice('image_viewer'), 'app')
        self.assertEqual(menu_style.choice('file_preview'), 'app')

    def test_prefer_device_app_and_custom(self):
        menu_style.configure(on(menu_style='system'))
        self.assertTrue(all(menu_style.choice(kind) == 'system' for kind, _ in menu_style.KINDS))
        menu_style.configure(on(menu_style='app'))
        self.assertTrue(all(menu_style.choice(kind) == 'app' for kind, _ in menu_style.KINDS))
        menu_style.configure(on(menu_style='custom', menu_custom={'message_box': 'app', 'video_player': 'system', 'bogus': 'app'}))
        self.assertEqual((menu_style.choice('message_box'), menu_style.choice('video_player'), menu_style.choice('context_menu')),
                         ('app', 'system', 'system'))

    def test_old_switches_are_migrated_and_validated(self):
        self.assertEqual(menu_style.migrate({'native_image_viewer': True}),
                         {'menu_style': 'custom', 'menu_custom': {'image_viewer': 'system'}, 'advanced_features': {'custom_menus': True}})
        self.assertEqual(menu_style.migrate({'native_image_viewer': False}), {})
        self.assertEqual(menu_style.migrate({'menu_style': 'default', 'native_image_viewer': True}), {})
        # 1.5.1 users who picked a mode keep it: the new feature is turned on once.
        self.assertEqual(menu_style.migrate({'menu_style': 'app', 'advanced_features': {'x': True}}),
                         {'advanced_features': {'x': True, 'custom_menus': True}})
        self.assertEqual(menu_style.migrate({'menu_style': 'app', 'advanced_features': {'custom_menus': False}}), {})
        values = Preferences.validated({'menu_style': 'custom', 'menu_custom': {'file_picker': 'app', 'x': 'y', 'emoji_picker': 'nope'}})
        self.assertEqual((values['menu_style'], values['menu_custom']), ('custom', {'file_picker': 'app'}))
        self.assertEqual(Preferences.validated({'menu_style': 'weird'})['menu_style'], 'default')

    def test_dialogs_follow_the_setting(self):
        from tg_ascii import app_dialogs, app_menus
        with patch.object(app_menus, 'askyesno', return_value=True) as app_version, \
             patch.object(app_dialogs._messagebox, 'askyesno', return_value=False) as system_version, \
             patch.object(app_dialogs, 'locked_parent', return_value=False):
            menu_style.configure(on())
            self.assertFalse(app_dialogs.messagebox.askyesno('t', 'm'))
            menu_style.configure(on(menu_style='app'))
            self.assertTrue(app_dialogs.messagebox.askyesno('t', 'm'))
            self.assertEqual((app_version.call_count, system_version.call_count), (1, 1))

    def test_context_menus_follow_the_setting(self):
        from tg_ascii import app_dialogs
        with patch.object(app_dialogs, 'rich_popup_menu', return_value='app-menu') as rich, \
             patch.object(app_dialogs, 'locked_parent', return_value=False), \
             patch('tg_ascii.custom_menus.active', return_value=False):
            menu_style.configure(on(menu_style='app'))
            self.assertEqual(app_dialogs.popup_menu(Mock(), [('A', lambda: None)]), 'app-menu')
            rich.assert_called_once()

    def test_file_patterns(self):
        from tg_ascii.app_menus import _matches, _patterns
        patterns = _patterns([('Photos', '*.jpg *.png')])[0][1]
        self.assertTrue(_matches('IMG.JPG', patterns))
        self.assertFalse(_matches('notes.txt', patterns))
        self.assertTrue(_matches('anything', _patterns(None)[0][1]))


class LightestAndCustomMenuTests(unittest.TestCase):
    def tearDown(self):
        menu_style.configure({})

    def test_feature_off_uses_the_lightest_version(self):
        import sys
        menu_style.configure({'menu_style': 'app'})  # Ignored while the feature is off.
        self.assertEqual(menu_style.choice('context_menu'), 'system')
        self.assertEqual(menu_style.choice('video_player'), 'system')
        self.assertEqual(menu_style.choice('image_viewer'), 'app')
        self.assertEqual(menu_style.choice('file_preview'), 'app')

    def test_customized_menu_is_used_and_errors_fall_back(self):
        import tempfile
        from pathlib import Path
        from tg_ascii import custom_menus
        with tempfile.TemporaryDirectory() as folder:
            menu_style.configure(on(), folder)
            path = custom_menus.ensure('message_box')
            self.assertTrue({'style.json', 'menu.py.example', 'LEEME.md'} <= {p.name for p in path.iterdir()})
            self.assertFalse(custom_menus.active('message_box'))  # Untouched template.
            self.assertEqual(menu_style.choice('message_box'), 'system')
            (path / 'style.json').write_text('{"background": "#112233", "button_labels": {"yes": "Vale"}}', encoding='utf-8')
            self.assertTrue(custom_menus.active('message_box'))
            self.assertEqual(menu_style.choice('message_box'), 'app')
            self.assertEqual(custom_menus.style('message_box')['button_labels'], {'yes': 'Vale'})
            (path / 'menu.py').write_text('def show(icon, buttons, title, message, parent, style):\n    return "mine"\n', encoding='utf-8')
            self.assertEqual(custom_menus.run('message_box', lambda: 'builtin', 'info', [], 't', 'm', None), 'mine')
            (path / 'menu.py').write_text('def show(*args):\n    raise RuntimeError("broken")\n', encoding='utf-8')
            self.assertEqual(custom_menus.run('message_box', lambda: 'builtin', 'info', [], 't', 'm', None), 'builtin')
            menu_style.configure({}, folder)
            self.assertFalse(custom_menus.active('message_box'))  # Feature off: never runs user code.

    def test_context_entries_rename_hide_and_order(self):
        from tg_ascii.app_dialogs import custom_entries
        a, b, c = (lambda: 1), (lambda: 2), (lambda: 3)
        result = custom_entries([('Reply', a), ('Copy text', b), None, ('Delete', c)],
                                {'rename': {'Copy text': 'Copiar'}, 'hide': ['Delete'], 'order': ['Copy text', 'Reply']})
        self.assertEqual([entry[0] for entry in result if entry], ['Copiar', 'Reply'])


if __name__ == '__main__':
    unittest.main()
