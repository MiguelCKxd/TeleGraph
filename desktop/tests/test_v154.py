"""1.5.4: open at login, saved independent windows, account aliases and order."""
import asyncio
import json
import os
from pathlib import Path
import plistlib
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from tg_ascii import autostart, saved_windows
from tg_ascii.preferences import DEFAULTS, Preferences


class AutostartTests(unittest.TestCase):
    def test_off_by_default(self):
        self.assertIs(DEFAULTS['open_at_login'], False)

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS LaunchAgent')
    def test_macos_agent_is_created_and_removed(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertFalse(autostart.is_enabled(home))
            autostart.set_enabled(True, home)
            path = autostart._agent_path(home)
            agent = plistlib.loads(path.read_bytes())
            self.assertTrue(agent['RunAtLoad'])
            self.assertEqual(agent['ProgramArguments'], autostart.command())
            self.assertTrue(autostart.is_enabled(home))
            autostart.set_enabled(False, home)
            self.assertFalse(path.exists())

    def test_frozen_bundle_opens_the_app(self):
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder, 'TG-ASCII.app', 'Contents', 'MacOS', 'TG-ASCII')
            executable.parent.mkdir(parents=True)
            executable.write_text('', encoding='utf-8')
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(executable)), \
                    patch.object(sys, 'platform', 'darwin'):
                self.assertEqual(autostart.command(), ['/usr/bin/open', str(executable.parents[2].resolve())])


class SavedWindowTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.main = Path(self.folder.name)

    def test_registry_defaults_rename_order_and_flags(self):
        data = saved_windows.load(self.main)
        self.assertEqual((data['save'], data['reopen'], data['windows']), (False, False, []))
        first = saved_windows.new_window(self.main, True)
        second = saved_windows.new_window(self.main, True)
        saved_windows.rename(self.main, first, '  Work   window ')
        saved_windows.move(self.main, second, -1)
        saved_windows.set_open_at_start(self.main, first, True)
        saved_windows.set_flag(self.main, 'reopen', True)
        data = saved_windows.load(self.main)
        self.assertEqual([item['id'] for item in data['windows']], [second, first])
        self.assertEqual(data['windows'][1], {'id': first, 'name': 'Work window', 'open_at_start': True})
        self.assertEqual(saved_windows.display_name(data, data['windows'][0]), 'Window 1')
        if os.name != 'nt':
            self.assertEqual((self.main / 'windows.json').stat().st_mode & 0o777, 0o600)

    def test_temporary_windows_are_not_listed_and_old_folders_are_adopted(self):
        temporary = saved_windows.new_window(self.main, False)
        old = 'a' * 32
        (self.main / 'windows' / old).mkdir(parents=True)
        (self.main / 'windows' / 'not-a-window').mkdir()
        data = saved_windows.load(self.main)
        self.assertEqual([item['id'] for item in data['windows']], [old])
        child = self.main / 'windows' / temporary
        self.assertTrue(saved_windows.temporary(child))
        self.assertEqual(saved_windows.main_root(child), self.main)
        self.assertIsNone(saved_windows.window_title(self.main))
        self.assertIn('·', saved_windows.window_title(child))

    def test_remove_folder_never_leaves_the_windows_folder(self):
        ident = saved_windows.new_window(self.main, True)
        with self.assertRaises(ValueError):
            saved_windows.window_dir(self.main, '../../etc')
        self.assertTrue(saved_windows.remove_folder(self.main, ident))
        self.assertFalse((self.main / 'windows' / ident).exists())
        self.assertTrue(self.main.exists())

    def test_reopen_only_the_chosen_windows(self):
        chosen = saved_windows.new_window(self.main, True)
        other = saved_windows.new_window(self.main, True)
        saved_windows.set_open_at_start(self.main, chosen, True)
        app = SimpleNamespace(demo=False, service=SimpleNamespace(root=self.main))
        with patch('tg_ascii.saved_windows.launch') as launch:
            self.assertEqual(saved_windows.reopen_at_start(app), [])  # Option off.
            saved_windows.set_flag(self.main, 'reopen', True)
            self.assertEqual(saved_windows.reopen_at_start(app), [chosen])
            child = SimpleNamespace(demo=False, service=SimpleNamespace(root=self.main / 'windows' / other))
            self.assertEqual(saved_windows.reopen_at_start(child), [])  # Never from a child window.
        launch.assert_called_once_with(self.main, chosen)

    def test_new_window_is_temporary_unless_saving_is_on(self):
        app = SimpleNamespace(demo=False, service=SimpleNamespace(root=self.main))
        with patch('tg_ascii.saved_windows.launch', return_value=Mock(poll=Mock(return_value=None))):
            first = saved_windows.open_window(app)
            saved_windows.set_flag(self.main, 'save', True)
            second = saved_windows.open_window(app)
        self.assertTrue((self.main / 'windows' / first / '.temporary').exists())
        self.assertEqual([item['id'] for item in saved_windows.load(self.main)['windows']], [second])

    def test_delete_signs_out_then_removes(self):
        ident = saved_windows.new_window(self.main, True)
        with patch('tg_ascii.saved_windows.sign_out_folder', AsyncMock(return_value=1)) as sign_out:
            failed = asyncio.run(saved_windows.delete_window(self.main, ident))
        sign_out.assert_awaited_once()
        self.assertEqual(failed, 1)
        self.assertEqual(saved_windows.load(self.main)['windows'], [])
        self.assertFalse((self.main / 'windows' / ident).exists())

    def test_a_running_window_is_not_deleted(self):
        ident = saved_windows.new_window(self.main, True)
        from tg_ascii.instance import InstanceLock
        lock = InstanceLock(self.main / 'windows' / ident)
        try:
            self.assertTrue(saved_windows.running(self.main, ident))
            with self.assertRaises(RuntimeError):
                asyncio.run(saved_windows.delete_window(self.main, ident))
        finally:
            lock.close()
        self.assertFalse(saved_windows.running(self.main, ident))


class AccountTests(unittest.TestCase):
    def test_aliases_are_validated(self):
        values = Preferences.validated({'account_aliases': {'a': '  Work  ', 'b': '', 'c': 'bad\nname', 5: 'x'}})
        self.assertEqual(values['account_aliases'], {'a': 'Work'})

    def test_alias_is_shown_instead_of_the_telegram_name(self):
        from tg_ascii.desktop_features import account_label
        app = SimpleNamespace(preferences=SimpleNamespace(values={'account_aliases': {'a': 'Work'}}),
                              service=SimpleNamespace(labels={'a': 'Ana', 'b': 'Bea'}))
        self.assertEqual((account_label(app, 'a'), account_label(app, 'b')), ('Work', 'Bea'))

    def test_account_order_is_saved(self):
        from tg_ascii.accounts import Accounts
        with tempfile.TemporaryDirectory() as root:
            a, b = 'a' * 32, 'b' * 32
            Path(root, 'accounts.json').write_text(json.dumps({'active': a, 'accounts': {a: {'label': 'A'}, b: {'label': 'B'}}}), encoding='utf-8')
            accounts = Accounts(root=root)
            accounts.reorder([b, a])
            self.assertEqual(list(json.loads(Path(root, 'accounts.json').read_text(encoding='utf-8'))['accounts']), [b, a])
            self.assertEqual(list(Accounts(root=root).entries), [b, a])



class LatinAmericanSpanishTests(unittest.TestCase):
    def tearDown(self):
        from tg_ascii import i18n
        i18n.set_language('en')

    def test_listed_right_after_spanish(self):
        from tg_ascii import i18n
        codes = list(i18n.LANGUAGES)
        self.assertEqual(codes[codes.index('es') + 1], 'es-419')
        self.assertEqual(Preferences.validated({'language': 'es-419'})['language'], 'es-419')

    def test_regional_words_with_agreement(self):
        from tg_ascii.spanish_latam import latam
        self.assertEqual(latam('Pulsa el botón del ordenador para ver el vídeo'), 'Presiona el botón de la computadora para ver el video')
        self.assertEqual(latam('Abrir en este ordenador'), 'Abrir en esta computadora')
        self.assertEqual(latam('Los ordenadores y MÓVILES'), 'Las computadoras y CELULARES')

    def test_fields_links_and_names_are_kept(self):
        from tg_ascii.spanish_latam import latam
        from tg_ascii.translations_extra import fields
        source = 'Vídeo {vídeo} https://example.com/vídeo @móvil /pulsa TG-ASCII Telegram'
        output = latam(source)
        self.assertEqual(fields(output), fields(source))
        for exact in ('{vídeo}', 'https://example.com/vídeo', '@móvil', '/pulsa'):
            self.assertIn(exact, output)
        self.assertTrue(output.startswith('Video '))

    def test_every_label_is_spanish_and_inline_captions_too(self):
        from tg_ascii import i18n
        from tg_ascii.interface_layout import caption
        i18n.set_language('es-419')
        self.assertEqual(i18n.tr('Ajustes'), i18n.tr('Settings'))
        self.assertNotEqual(i18n.tr('Settings'), 'Settings')
        self.assertIn('computadora', i18n.tr('Open TG-ASCII when I log in to this computer'))
        self.assertEqual(caption('Restart app', 'Reiniciar la app'), 'Reiniciar la app')
        from tg_ascii.day_separators import day_label
        from datetime import date
        self.assertEqual(day_label(date(2020, 3, 5), today=date(2026, 1, 1)), '5 de marzo de 2020')


if __name__ == '__main__':
    unittest.main()
