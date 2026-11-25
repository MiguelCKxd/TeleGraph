import tempfile
import unittest
from pathlib import Path

from tg_ascii import launcher_names as names


class LauncherNameTests(unittest.TestCase):
    def test_safe_file_names(self):
        self.assertEqual(names.safe_file_name('Mi: Telegram?'), 'Mi Telegram')
        self.assertEqual(names.safe_file_name('  ...  '), 'TeleGraph')
        self.assertEqual(names.safe_file_name('CON'), 'TeleGraph')
        self.assertEqual(names.chosen_name({'app_display_name': ' '}), 'TeleGraph')

    def test_renames_own_shortcuts_and_back_to_default(self):
        with tempfile.TemporaryDirectory() as root:
            desktop, start = Path(root, 'Desktop'), Path(root, 'Programs')
            desktop.mkdir(); start.mkdir()
            (desktop / 'TeleGraph.lnk').write_text('a', encoding='utf-8'); (start / 'TeleGraph.lnk').write_text('b', encoding='utf-8')
            (desktop / 'Other.lnk').write_text('c', encoding='utf-8')
            done = names.apply_renames(names.plan_renames([desktop, start], 'Mi Telegram'))
            self.assertEqual(sorted(p.name for p in done), ['Mi Telegram.lnk', 'Mi Telegram.lnk'])
            names.remember(root, 'Mi Telegram')
            self.assertEqual(names.remembered(root), ['Mi Telegram'])
            # Reset: the remembered custom name finds the shortcut again.
            done = names.apply_renames(names.plan_renames([desktop], 'TeleGraph', names.remembered(root)))
            self.assertEqual([p.name for p in done], ['TeleGraph.lnk'])
            self.assertTrue((desktop / 'Other.lnk').exists())

    def test_existing_target_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            (folder / 'TeleGraph.lnk').write_text('a', encoding='utf-8'); (folder / 'Mi Telegram.lnk').write_text('user', encoding='utf-8')
            self.assertEqual(names.plan_renames([folder], 'Mi Telegram'), [])


if __name__ == '__main__':
    unittest.main()
