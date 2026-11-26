"""Telegram API terms 2.4: an unofficial client must not use the official Telegram logo.

TeleGraph 3.4.1 no longer offers, downloads or ships Telegram's official artwork.
A selection made in an earlier version returns to the TeleGraph icon, while an
icon the user created with "Custom app icon" is kept.
"""
from pathlib import Path
import sys
import tempfile
import unittest

from tg_ascii.preferences import Preferences

validated = Preferences.validated

ROOT = Path(__file__).resolve().parents[1]


class NoOfficialLogosTests(unittest.TestCase):
    def test_previous_official_selection_reverts_to_telegraph_icon(self):
        result = validated({'custom_icon': '/tmp/custom-icons/official.png',
                            'official_icon_label': 'Android · ic_launcher_round'})
        self.assertEqual((result['custom_icon'], result['official_icon_label']), ('', ''))

    def test_user_custom_icon_is_kept(self):
        result = validated({'custom_icon': '/tmp/custom-icons/mine.png', 'official_icon_label': ''})
        self.assertEqual((result['custom_icon'], result['official_icon_label']), ('/tmp/custom-icons/mine.png', ''))

    def test_saved_preferences_migrate_on_load(self):
        with tempfile.TemporaryDirectory() as directory:
            prefs = Preferences(Path(directory))
            prefs.save({'custom_icon': str(Path(directory) / 'official.png'), 'official_icon_label': 'Logo'})
            reloaded = Preferences(Path(directory))
            self.assertEqual((reloaded.values['custom_icon'], reloaded.values['official_icon_label']), ('', ''))

    def test_feature_and_artwork_are_gone(self):
        self.assertFalse((ROOT / 'tg_ascii' / 'official_icons.py').exists())
        self.assertFalse((ROOT / 'tg_ascii' / 'mobile_icons.py').exists())
        self.assertFalse((ROOT / 'tg_ascii' / 'assets' / 'official-icons').exists())
        settings = (ROOT / 'tg_ascii' / 'desktop_settings.py').read_text(encoding='utf-8')
        self.assertNotIn('official_icons', settings)

    def test_release_does_not_package_official_artwork(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        try:
            import build_release
        finally:
            sys.path.remove(str(ROOT / 'tools'))
        self.assertFalse([name for name in build_release.ASSETS if 'official' in name])
        self.assertNotIn('official_icons.py', build_release.SOURCE_MODULES)
        self.assertNotIn('mobile_icons.py', build_release.SOURCE_MODULES)


if __name__ == '__main__':
    unittest.main()
