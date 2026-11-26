from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, TestCase

from PIL import Image

from tg_ascii_mobile.core import Core
from tg_ascii_mobile.wear_sync import appearance_publisher, decode_appearance


class WordmarkGeometryTests(TestCase):
    def test_short_marks_share_scale_and_stay_centered(self):
        from tg_ascii.logos import CLASSIC_MARK, LOGO_PALETTES, png_bytes

        ink = (*LOGO_PALETTES['default']['dark'][1], 255)
        bounds = []
        for mark in (CLASSIC_MARK, 'title-short'):
            image = Image.open(BytesIO(png_bytes(mark, size=128)))
            mask = Image.new('L', image.size)
            pixels = image.tobytes()
            mask.putdata([255 if pixels[i:i + 4] == bytes(ink) else 0 for i in range(0, len(pixels), 4)])
            left, top, right, bottom = mask.getbbox()
            self.assertLessEqual(abs(left - (128 - right)), 3)
            self.assertLessEqual(abs(top - (128 - bottom)), 3)
            bounds.append((right - left, bottom - top))
        self.assertLessEqual(abs(bounds[0][0] - bounds[1][0]), 1)
        self.assertLessEqual(abs(bounds[0][1] - bounds[1][1]), 1)


    def test_native_tile_and_padded_desktop_tile_use_the_same_margins(self):
        from tg_ascii.logos import LOGO_PALETTES, png_bytes

        ink = (*LOGO_PALETTES['default']['dark'][1], 255)
        for full_bleed, tile_width in ((True, 256), (False, 206)):
            icon = Image.open(BytesIO(png_bytes(size=256, full_bleed=full_bleed)))
            points = [x for x in range(icon.width)
                      if any(icon.getpixel((x, y)) == ink for y in range(icon.height))]
            self.assertAlmostEqual((max(points) - min(points) + 1) / tile_width, .75, delta=.01)


class WearAppearancePublisherTests(TestCase):
    def test_a_late_failure_cannot_replace_a_newer_appearance(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        timer = SimpleNamespace(cancel=Mock())
        loop = SimpleNamespace(call_later=Mock(return_value=timer))
        requests = []
        publish = appearance_publisher(loop, lambda packet, complete: requests.append((packet, complete)))

        publish({'font': 'serif'})
        first, complete_first = requests[0]
        complete_first(False)
        loop.call_later.assert_called_once()
        publish({'font': 'sans'})
        timer.cancel.assert_called_once()
        second, complete_second = requests[1]
        self.assertGreater(second['revision'], first['revision'])
        self.assertEqual(second['appearance'], {'font': 'sans'})
        complete_first(True)
        publish({'font': 'mono'})
        self.assertEqual(len(requests), 2)
        complete_second(True)
        self.assertEqual(requests[2][0]['appearance'], {'font': 'mono'})
        requests[2][1](True)
        publish({'font': 'mono'})
        self.assertEqual(len(requests), 3)


class MobileLogoTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.core = Core(Path(directory.name), 'Android')
        self.addCleanup(self.core.loop.close)

    async def test_legacy_native_icon_is_preserved_and_migrates_in_app_logo(self):
        self.core.save_appearance({**self.core.appearance(), 'icon': 'll_light', 'brand_logo': {}})
        look = self.core.appearance()
        self.assertEqual(look['icon'], 'll_light')
        self.assertEqual(look['brand_logo'], {'variant': 'lower-long', 'color': 'default', 'theme': 'light'})
        await self.core.api_appearance({'brand_logo': {'variant': 'telegraph-upper', 'color': 'blue', 'theme': 'dark'}})
        expected = {'variant': 'telegraph-upper', 'color': 'blue', 'theme': 'dark'}
        self.assertEqual(self.core.appearance()['brand_logo'], expected)
        self.assertEqual((await self.core.watch_request({'op': 'appearance'}))['brand_logo'], expected)
        self.assertEqual(self.core.appearance()['icon'], 'll_light')

    async def test_every_brand_choice_has_a_stable_launcher_id(self):
        from itertools import product
        from tg_ascii.logos import LOGO_PALETTES, VARIANTS
        from tg_ascii_mobile.native_logos import NAMES, NATIVE_LOGOS

        self.assertEqual(set(NAMES), set(product(VARIANTS, ('light', 'dark'), LOGO_PALETTES)))
        for choice, key in NAMES.items():
            self.assertEqual(NATIVE_LOGOS[key], choice)
        self.assertEqual(NAMES['title-short', 'dark', 'default'], 'default')

    async def test_launcher_change_waits_for_system_and_preserves_settings_on_failure(self):
        import asyncio
        from unittest.mock import Mock

        self.core.loop = asyncio.get_running_loop()
        options = {'variant': 'telegraph-upper', 'theme': 'light', 'color': 'pink'}
        request = {'brand_logo': options, 'apply_native_logo': True}
        before = self.core.appearance()
        for succeeds in (False, True):
            self.core.native_icon = Mock(side_effect=lambda key, done: done(succeeds))
            if succeeds:
                updated = await self.core.api_appearance(request)
                self.assertEqual(updated['icon'], 'telegraph_upper_pink_light')
                self.assertEqual(self.core.appearance()['brand_logo'], options)
            else:
                with self.assertRaises(RuntimeError):
                    await self.core.api_appearance(request)
                self.assertEqual(self.core.appearance(), before)
            self.core.native_icon.assert_called_once()

    async def test_wear_sync_carries_normalized_look_and_rejects_invalid_palette(self):
        from types import SimpleNamespace

        self.core.prefs = SimpleNamespace(values={'theme': 'light', 'font_size': 18, 'bubbles': True})
        sent = []
        self.core.native_wear_appearance = sent.append
        await self.core.api_appearance({'brand_logo': {'variant': 'telegraph-upper', 'color': 'blue', 'theme': 'dark'}})
        appearance = sent[-1]
        revision, look = decode_appearance(json.dumps({'revision': 17, 'appearance': appearance}))
        self.assertEqual(revision, 17)
        self.assertTrue(look['bubbles'])
        self.assertEqual(look['scale'], 1.5)
        self.assertEqual(look['bg'], '#f4f8f3')
        self.assertEqual(look['icon'], 'default')
        self.assertEqual(look['brand_logo']['variant'], 'telegraph-upper')
        appearance['bg'] = 'bad'
        self.assertIsNone(decode_appearance(json.dumps({'revision': 17, 'appearance': appearance})))

    async def test_generated_logo_is_cached_and_invalid_keys_are_rejected(self):
        path = await self.core.brand_logo_file('telegraph-title', 'light', 'orange')
        self.assertEqual(path.read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(path, await self.core.brand_logo_file('telegraph-title', 'light', 'orange'))
        self.assertIsNone(await self.core.brand_logo_file('../other', 'light', 'orange'))

    async def test_official_telegram_artwork_is_not_offered(self):
        # Telegram API terms 2.4: an unofficial client must not use the official logo.
        folder = self.core.root / 'mobile' / 'official-icons' / 'Telegram'
        folder.mkdir(parents=True)
        path = folder / 'official-telegram-sample.png'
        path.touch()  # A cache left by an earlier version is never served.
        self.assertIsNone(self.core.official_logo_file('Telegram/' + path.name))
        self.assertFalse(hasattr(self.core, 'api_official_logos'))
        with self.assertRaises(ValueError):
            await self.core.api_appearance({'official_logo': 'Telegram/' + path.name})
        self.assertEqual((await self.core.api_appearance({'official_logo': ''}))['official_logo'], '')

    async def test_saved_official_logo_reverts_to_telegraph_logo(self):
        self.core.save_appearance({**self.core.appearance(), 'official_logo': 'Android/mobile-0123456789abcdef01234567.png'})
        self.assertEqual(self.core.appearance()['official_logo'], '')

    async def test_logo_photo_survives_unrelated_background_cleanup(self):
        from PIL import Image
        staged = self.core.staging_path('fixture.png')
        Image.new('RGB', (32, 32), 'green').save(staged)
        updated = await self.core.api_set_logo_photo(staged.name)
        photo = updated['brand_photo']
        self.assertTrue(self.core.logo_photo_file(photo).is_file())
        self.assertEqual(self.core.appearance()['brand_photo'], photo)
        await self.core.api_appearance({'dim': 50})
        self.assertTrue(self.core.logo_photo_file(photo).is_file())
