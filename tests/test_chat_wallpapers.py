from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from PIL import Image
from telethon import errors, functions, types
from tg_ascii_mobile.core import Core


class ChatWallpaperTests(IsolatedAsyncioTestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.core = Core(self.folder, 'iOS')
        self.core.loop.close()
        self.client = AsyncMock()
        self.backend = SimpleNamespace(client=self.client)
        self.core.accounts = SimpleNamespace(current='first', services={'first': SimpleNamespace(backend=self.backend)})
        self.core.emit = Mock()
        self.core.publish_wear_appearance = Mock()
        self.opts = {'colors': ['#113344', '#886611'], 'rotation': 45, 'motion': True}

    async def apply(self, **params):
        return await self.core.call('apply_chat_wallpaper', dict(account='first', **params))

    async def test_global_and_peer_are_independent_and_account_scoped(self):
        values = await self.apply(options=self.opts)
        self.assertEqual(values['background'], '')
        self.assertEqual(values['chat_wallpapers']['all']['telegram_link'], 'https://t.me/bg/113344-886611?rotation=45')
        all_file = values['chat_wallpapers']['all']['file']
        with Image.open(self.core.chat_wallpaper_file('first', all_file)) as image:
            self.assertNotEqual(image.getpixel((0, 0)), image.getpixel((0, 900)))
        values = await self.apply(target=42, options={'colors': ['#ff0000']})
        peer_file = values['chat_wallpapers']['42']['file']
        self.assertNotEqual(all_file, peer_file)
        self.assertFalse(self.client.called)
        self.core.accounts.current = 'second'
        self.assertEqual(self.core.appearance()['chat_wallpapers'], {})
        self.assertIsNone(self.core.chat_wallpaper_file('first', peer_file))
        self.core.accounts.current = 'first'
        after = await self.apply(target=42, source='reset')
        self.assertEqual(set(after['chat_wallpapers']), {'all'})
        self.assertIsNone(self.core.chat_wallpaper_file('first', peer_file))
        self.assertTrue(self.core.chat_wallpaper_file('first', all_file).is_file())

    async def test_fills_sync_for_peer_but_global_fill_is_local(self):
        self.client.get_input_entity.return_value = types.InputPeerUser(42, 123)
        await self.apply(target=42, options=self.opts, sync='devices')
        request = self.client.await_args.args[0]
        self.assertIsInstance(request, functions.messages.SetChatWallPaperRequest)
        self.assertIsInstance(request.wallpaper, types.InputWallPaperNoFile)
        self.assertEqual(request.settings.second_background_color, 0x886611)
        self.assertFalse(request.for_both)
        self.assertTrue(bytes(request))
        self.client.reset_mock()
        with self.assertRaisesRegex(ValueError, 'global'):
            await self.apply(options=self.opts, sync='devices')
        self.assertFalse(self.client.called)
        await self.apply(target=42, source='reset', sync='devices')
        self.assertIsNone(self.client.await_args.args[0].wallpaper)

    async def test_premium_denial_keeps_previous_wallpaper_and_allows_personal_retry(self):
        from tg_ascii.i18n import get_language, set_language
        from tg_ascii_mobile.strings import install
        install()
        self.addCleanup(set_language, get_language())
        set_language('es')
        self.client.get_input_entity.return_value = types.InputPeerUser(42, 123)
        initial = await self.apply(target=42, options=self.opts)
        previous = initial['chat_wallpapers']['42']
        self.client.side_effect = errors.PremiumAccountRequiredError(request=None)
        with self.assertRaisesRegex(ValueError, 'Telegram Premium.*solo para ti'):
            await self.apply(target=42, options={'colors': ['#abcdef']}, sync='both')
        self.assertEqual(self.core.appearance()['chat_wallpapers']['42'], previous)
        self.assertTrue(self.core.chat_wallpaper_file('first', previous['file']).is_file())
        self.client.side_effect = None
        result = await self.apply(target=42, options={'colors': ['#abcdef']}, sync='devices')
        self.assertEqual(result['chat_wallpapers']['42']['options']['colors'], ['#abcdef'])
        self.assertFalse(self.client.await_args.args[0].for_both)

    async def test_both_participants_only_in_private_chats_and_global_reset_uses_default(self):
        self.client.get_input_entity.return_value = types.InputPeerUser(42, 123)
        await self.apply(target=42, options=self.opts, sync='both')
        request = self.client.await_args.args[0]
        self.assertIsInstance(request, functions.messages.SetChatWallPaperRequest)
        self.assertTrue(request.for_both)
        await self.apply(target=42, source='reset', sync='both')
        request = self.client.await_args.args[0]
        self.assertIsNone(request.wallpaper)
        self.assertTrue(request.for_both)
        self.client.reset_mock()
        self.client.get_input_entity.return_value = types.InputPeerChannel(77, 456)
        with self.assertRaisesRegex(ValueError, 'private chat'):
            await self.apply(target=-10077, options=self.opts, sync='both')
        with self.assertRaisesRegex(ValueError, 'scope'):
            await self.apply(options=self.opts, sync='both')
        self.assertFalse(any(isinstance(call.args[0], functions.messages.SetChatWallPaperRequest)
                             for call in self.client.await_args_list))
        default = types.WallPaper(5, 6, 'classic', SimpleNamespace(), default=True,
                                  settings=types.WallPaperSettings(background_color=0x223344))
        self.client.side_effect = lambda request: (SimpleNamespace(wallpapers=[default])
                                                   if isinstance(request, functions.account.GetWallPapersRequest) else None)
        await self.apply(source='reset', sync='devices')
        request = self.client.await_args.args[0]
        self.assertIsInstance(request, functions.account.InstallWallPaperRequest)
        self.assertEqual((request.wallpaper.id, request.wallpaper.access_hash), (5, 6))
        self.assertEqual(request.settings.background_color, 0x223344)

    async def test_picture_preview_upload_and_install(self):
        img = self.core.staging_path('photo.png')
        Image.new('RGB', (60, 100), 'red').save(img)
        preview = await self.apply(source='image', key=img.name, preview=True, options={'blur': True})
        self.assertTrue(img.is_file())
        self.assertTrue(self.core.chat_wallpaper_file('first', preview['file'], preview=True).is_file())
        self.assertFalse(self.client.called)
        self.client.return_value = types.WallPaper(91, 32, 'uploaded', types.DocumentEmpty(3))
        await self.apply(source='image', key=img.name, sync='devices', options={'blur': True})
        self.assertFalse(img.exists())
        first, second = [call.args[0] for call in self.client.await_args_list]
        self.assertIsInstance(first, functions.account.UploadWallPaperRequest)
        self.assertFalse(first.for_chat)
        self.assertIsInstance(second, functions.account.InstallWallPaperRequest)
        self.assertEqual(second.wallpaper.id, 91)
        self.assertTrue(second.settings.blur)
        current = self.core.appearance()['chat_wallpapers']['all']
        self.assertEqual(current['telegram_link'], 'https://t.me/bg/uploaded?mode=blur')
        original = self.core.wallpaper_dir('first') / current['original']
        self.assertTrue(original.is_file())
        changed = await self.apply(source='image', options={'blur': False})
        self.assertEqual(changed['chat_wallpapers']['all']['original'], original.name)
        self.assertFalse(changed['chat_wallpapers']['all']['options']['blur'])
        self.assertNotIn('telegram_link', changed['chat_wallpapers']['all'])
        await self.apply(source='reset')
        self.assertFalse(original.exists())

    async def test_repeat_gallery_select_keeps_long_identifier_and_original(self):
        wallpaper = types.WallPaperNoFile(987654321012345678, settings=types.WallPaperSettings(background_color=0x123456))
        self.client.return_value = SimpleNamespace(wallpapers=[wallpaper])
        rows = await self.core.call('wallpaper_gallery', {'account':'first'})
        self.assertEqual(rows[0]['id'], str(wallpaper.id))
        await self.apply(source='gallery', catalog_id=rows[0]['id'], options={'colors':['#000000']})
        self.assertEqual(wallpaper.settings.background_color, 0x123456)
        self.client.reset_mock()
        self.assertIsNone(await self.core.api_remote_chat_wallpaper('first', 2))
        self.assertFalse(self.client.called)

    async def test_vector_preview_uses_geometry_and_selection_survives_reload(self):
        import gzip
        doc = SimpleNamespace(mime_type='application/x-tgwallpattern', size=256)
        pattern = types.WallPaper(21, 56, 'leaves', doc, pattern=True,
                                  settings=types.WallPaperSettings(background_color=0x00ff00, intensity=25))
        self.client.return_value = SimpleNamespace(wallpapers=[pattern])
        async def download(document, path):
            with gzip.open(path, 'wb') as stream:
                stream.write(b'<!-- Generated by Illustrator --><svg width="100" height="100">'
                             b'<style>.st0{fill:none;stroke:#000000;stroke-width:3;}</style>'
                             b'<g transform="translate(1 2)"><path class="st0" d="M0 0L50 0L0 50Z"/></g></svg>')
            return path
        self.backend.download_media = AsyncMock(side_effect=download)
        await self.core.api_wallpaper_gallery('first')
        result = await self.apply(source='gallery', catalog_id='21', options={'intensity': 80})
        file = result['chat_wallpapers']['all']['file']
        self.assertEqual(result['chat_wallpapers']['all']['telegram_link'],
                         'https://t.me/bg/leaves?intensity=80&bg_color=00ff00')
        contents = self.core.chat_wallpaper_file('first', file).read_text()
        self.assertIn('opacity="0.8"', contents)
        self.assertIn('M0 0L50 0L0 50Z', contents)
        self.assertIn('stroke-width="3"', contents)
        self.assertIn('fill="none"', contents)
        self.assertEqual(self.core.appearance()['chat_wallpapers']['all']['catalog_id'], '21')


class PatternSafetyTests(IsolatedAsyncioTestCase):
    def pattern(self, folder, text, encoding):
        import gzip
        source = Path(folder) / 'pattern.tgv'
        with gzip.open(source, 'wb') as stream:
            stream.write(text.encode(encoding))
        return source

    def test_declarations_hidden_in_utf16_are_rejected(self):
        from tg_ascii_mobile.wallpapers import web_pattern
        hidden = ('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE svg [<!ENTITY a "aaaa">]>'
                  '<svg width="10" height="10"><path d="M0 0L5 5"/></svg>')
        settings = types.WallPaperSettings(background_color=0x00ff00, intensity=50)
        with TemporaryDirectory() as folder:
            for encoding in ('utf-16', 'utf-16-le'):
                with self.assertRaises(ValueError):
                    web_pattern(self.pattern(folder, hidden, encoding), Path(folder) / 'out.svg', settings)
            plain = '<svg width="10" height="10"><path d="M0 0L5 5"/></svg>'
            web_pattern(self.pattern(folder, plain, 'utf-8'), Path(folder) / 'out.svg', settings)
            self.assertIn('M0 0L5 5', (Path(folder) / 'out.svg').read_text())
