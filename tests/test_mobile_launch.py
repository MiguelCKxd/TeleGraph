import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from tg_ascii_mobile.core import Core
from tg_ascii_mobile.launch_appearance import launch_appearance


class MobileLaunchTests(unittest.TestCase):
    def test_early_siri_import_uses_bundled_mime_types_on_ios(self):
        # The test process may already have imported Telethon, so use the same
        # fresh interpreter state as the packaged app's first launch.
        probe = """
import mimetypes, sys, tempfile
with tempfile.NamedTemporaryFile() as database:
    mimetypes.knownfiles = [database.name]
    def sandbox(event, args):
        if event == 'open' and args[0] == database.name:
            raise PermissionError('host MIME database')
    sys.addaudithook(sandbox)
    original = sys.platform
    sys.platform = 'ios'
    import tg_ascii_mobile
    sys.platform = original
    from tg_ascii_mobile import siri
    assert mimetypes.guess_type('photo.png')[0] == 'image/png'
"""
        env = {**os.environ, 'PYTHONPATH': os.pathsep.join(sys.path)}
        subprocess.run([sys.executable, '-c', probe], check=True, env=env)

    def test_saved_brand_and_lock_at_cold_start(self):
        with TemporaryDirectory() as directory:
            core = Core.__new__(Core)
            core.root, core.prefs, core.locked = Path(directory), None, False
            (core.root / 'preferences.json').write_text(json.dumps({
                'theme': 'system', 'app_display_name': 'Mi mensajería', 'background_color': '#235678',
            }))
            name = 'a' * 32 + '.jpg'
            photo = core.root / 'mobile-logos' / name
            photo.parent.mkdir()
            photo.touch()
            wallpaper = core.root / 'mobile-backgrounds' / name
            wallpaper.parent.mkdir()
            wallpaper.touch()
            appearance = core.root / 'mobile' / 'appearance.json'
            appearance.parent.mkdir()
            appearance.write_text(json.dumps({
                'brand_photo': name, 'background': name, 'dim': 75,
                'font': 'classic', 'effects': {'text_bold': True},
            }))
            look = launch_appearance(core, system_dark=False)
            self.assertEqual((look['title'], look['background'], look['foreground'], look['logo']),
                             ('Mi mensajería', '#235678', '#14532d', photo))
            self.assertEqual((look['wallpaper'], look['opacity'], look['font'], look['bold']),
                             (wallpaper, .25, 'serif', True))
            core.locked = True
            locked = launch_appearance(core, system_dark=False)
            self.assertNotEqual(locked['logo'], photo)
            self.assertIsNone(locked['wallpaper'])

    def test_saved_platform_fonts_use_native_designs_and_families(self):
        with TemporaryDirectory() as directory:
            core = Core.__new__(Core)
            core.root, core.prefs, core.locked = Path(directory), None, False
            appearance = core.root / 'mobile' / 'appearance.json'
            appearance.parent.mkdir()
            choices = {
                'iOS': {'sf': 'system', 'sf_mono': 'monospace', 'sf_rounded': 'rounded',
                        'new_york': 'system-serif', 'sf_compact': 'SF Compact'},
                'Android': {'condensed': 'sans-serif-condensed', 'light': 'sans-serif-light',
                            'medium': 'sans-serif-medium', 'noto_serif': 'serif', 'typewriter': 'serif-monospace',
                            'casual': 'casual', 'handwriting': 'cursive', 'smallcaps': 'sans-serif-smallcaps'},
            }
            for system, fonts in choices.items():
                core.system = system
                for key, native in fonts.items():
                    with self.subTest(system=system, font=key):
                        appearance.write_text(json.dumps({'font': key}))
                        self.assertEqual(launch_appearance(core, system_dark=False)['font'], native)
