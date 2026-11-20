import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

from telethon import functions as f, types as t

from tg_ascii.backend import TelegramBackend
from tg_ascii.customization_sync import (ThemeOverrides, apply_chat_theme, local_theme_wallpaper,
    palette_for_chat, render_cached_wallpaper, server_chat_appearance, sync_enabled, theme_settings)
from tg_ascii.preferences import Preferences


def sample_theme():
    return t.Theme(8, 12, 'example', 'Example', emoticon='🌙', settings=[
        t.ThemeSettings(t.BaseThemeDay(), 0x123456, message_colors=[0xddeeff]),
        t.ThemeSettings(t.BaseThemeNight(), 0xabcdef, message_colors=[0x112233])])


class SyncPolicyTests(unittest.TestCase):
    def test_sync_is_default_and_opt_out_is_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            prefs = Preferences(directory)
            self.assertTrue(sync_enabled(prefs))
            prefs.save({'sync_customizations': False})
            self.assertFalse(sync_enabled(Preferences(directory)))

    def test_local_overrides_are_separate_by_account_chat_and_survive_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ThemeOverrides(directory)
            store.save('a', 42, {'local_only': True, 'emoticon': '🌙', 'palette': {'bg': '#112233'}})
            restored = ThemeOverrides(directory)
            self.assertEqual(restored.get('a', 42)['emoticon'], '🌙')
            self.assertIsNone(restored.get('a', 43))
            self.assertIsNone(restored.get('b', 42))
            restored.save('a', 42, None)
            self.assertIsNone(ThemeOverrides(directory).get('a', 42))

    def test_local_palette_validates_imported_values_and_no_background_means_local_default(self):
        with tempfile.TemporaryDirectory() as directory:
            app = NS(preferences=Preferences(directory), ui_account='a', active=42, demo=False)
            app._chat_theme_overrides = ThemeOverrides(directory)
            app._chat_theme_overrides.save('a', 42, {'local_only': True, 'wallpaper': None,
                'palette': {'bg': '#123456', 'text': 'not a color', 'unknown': '#456789'}})
            self.assertEqual(palette_for_chat(app, {'bg': '#000000', 'text': '#ffffff'}),
                             {'bg': '#123456', 'text': '#ffffff'})
            self.assertEqual(local_theme_wallpaper(app), (True, None))

    def test_day_night_settings_match_current_appearance(self):
        self.assertEqual(theme_settings(sample_theme(), False).accent_color, 0x123456)
        self.assertEqual(theme_settings(sample_theme(), True).accent_color, 0xabcdef)

    def test_demo_overrides_never_write(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ThemeOverrides(directory, demo=True)
            store.save('demo', 1, {'local_only': True})
            self.assertEqual(list(Path(directory).iterdir()), [])


class ChatThemeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = AsyncMock()
        self.client.add_event_handler = Mock()
        self.client.get_input_entity.return_value = t.InputPeerUser(42, 123)
        self.client.return_value = NS(themes=[sample_theme()])
        self.backend = TelegramBackend(self.client)

    async def test_native_catalogue_is_cached_and_simultaneous_dialogs_share_request(self):
        result = await asyncio.gather(*(self.backend.chat_themes() for _ in range(8)))
        self.assertTrue(all(items[0].emoticon == '🌙' for items in result))
        self.client.assert_awaited_once()
        self.assertIsInstance(self.client.call_args.args[0], f.account.GetChatThemesRequest)

    async def test_selection_and_reset_use_native_input_chat_theme(self):
        await self.backend.set_chat_theme(42, '🌙')
        request = self.client.call_args.args[0]
        self.assertIsInstance(request, f.messages.SetChatThemeRequest)
        self.assertEqual(request.peer.user_id, 42)
        self.assertEqual(request.theme.emoticon, '🌙')
        await self.backend.set_chat_theme(42, '')
        self.assertIsInstance(self.client.call_args.args[0].theme, t.InputChatThemeEmpty)

    async def test_unknown_or_invalid_theme_never_mutates_telegram(self):
        for value in ('unknown', 42, 'a' * 100):
            with self.assertRaises(ValueError):
                await self.backend.set_chat_theme(42, value)
        self.assertFalse(any(isinstance(call.args[0], f.messages.SetChatThemeRequest)
                             for call in self.client.call_args_list))

    async def test_local_mode_renders_and_saves_without_server_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ThemeOverrides(directory)
            result = await apply_chat_theme(self.backend, store, 'account', 42, sample_theme(), directory,
                                            synchronize=False, dark=True)
            self.client.assert_not_awaited()
            self.assertEqual(result['palette']['selected'], '#112233')
            self.assertEqual(ThemeOverrides(directory).get('account', 42)['emoticon'], '🌙')

    async def test_successful_sync_removes_override_only_after_server_accepts(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ThemeOverrides(directory)
            store.save('a', 42, {'local_only': True, 'emoticon': 'old'})
            self.backend.set_chat_theme = AsyncMock(side_effect=ConnectionError)
            with self.assertRaises(ConnectionError):
                await apply_chat_theme(self.backend, store, 'a', 42, sample_theme(), directory)
            self.assertEqual(store.get('a', 42)['emoticon'], 'old')
            self.backend.set_chat_theme.side_effect = None
            await apply_chat_theme(self.backend, store, 'a', 42, sample_theme(), directory)
            self.assertIsNone(store.get('a', 42))
            self.backend.set_chat_theme.assert_awaited_with(42, '🌙')

    async def test_server_theme_is_loaded_from_current_profile(self):
        self.backend.profile = AsyncMock(return_value={'chat_theme': t.ChatTheme('🌙')})
        result = await server_chat_appearance(self.backend, 42, Path('/unused'), dark=True)
        self.assertEqual(result['emoticon'], '🌙')
        self.assertEqual(result['palette']['selected'], '#112233')

    async def test_server_theme_change_notifies_the_correct_chat(self):
        self.backend.on_change = Mock()
        update = t.UpdateNewMessage(t.MessageService(7, t.PeerUser(42),
            action=t.MessageActionSetChatTheme(t.ChatTheme('🌙'))), 1, 1)
        await self.backend.account_event(update)
        self.backend.on_change.assert_called_once_with('chat_theme', 42)

    async def test_wallpaper_render_is_reused_only_for_identical_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            wallpaper = t.WallPaperNoFile(7, settings=t.WallPaperSettings(background_color=0x123456))
            async def render(backend, item, folder):
                folder.mkdir(parents=True)
                target = folder / f'telegram-wallpaper-{item.id}.jpg'
                target.write_bytes(b'preview')
                return target
            with patch('tg_ascii.telegram_wallpapers.wallpaper_file', side_effect=render) as renderer:
                first = await render_cached_wallpaper(self.backend, wallpaper, directory)
                self.assertEqual(await render_cached_wallpaper(self.backend, wallpaper, directory), first)
                self.assertEqual(renderer.await_count, 1)
                wallpaper.settings.background_color = 0x654321
                second = await render_cached_wallpaper(self.backend, wallpaper, directory)
                self.assertNotEqual(first, second)
                self.assertEqual(renderer.await_count, 2)
