from datetime import date
from pathlib import Path
from types import SimpleNamespace as NS
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock

from telethon import functions as f, types as t

from tg_ascii.backend import TelegramBackend
from tg_ascii.profile_customization import (apply_profile_design, clear_design, color_options,
    configure_design, load_design, overlay_profile, overlay_sender, set_native, validate)


class ProfileCustomizationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.client = AsyncMock()
        self.client.add_event_handler = Mock()
        self.client.return_value = True
        self.backend = TelegramBackend(self.client)
        self.backend.account_profile.remember(t.User(10, premium=True))
        configure_design(self.backend, self.folder.name, 'account')

    async def test_local_design_is_persisted_per_account_without_network_mutation(self):
        await apply_profile_design(self.backend, 'name_color', {'color': 4, 'background_emoji_id': 99}, False)
        self.client.assert_not_awaited()
        self.assertEqual(load_design(self.backend.profile_design_path, 'account')['name_color']['color'], 4)
        self.assertEqual(load_design(self.backend.profile_design_path, 'another'), {})
        self.assertEqual(overlay_sender(self.backend, 10, (None, None, None)), (4, 99, None))
        self.assertEqual(overlay_sender(self.backend, 20, (1, 2, 3)), (1, 2, 3))

    async def test_local_status_birthday_and_channel_render_only_own_profile(self):
        for field, value in [('emoji_status', 99), ('birthday', {'day': 29, 'month': 2, 'year': None}),
                             ('personal_channel', -1000000000042), ('profile_color', {'color': 3})]:
            await apply_profile_design(self.backend, field, value, False)
        profile = overlay_profile(self.backend, {'id': 10})
        self.assertEqual(profile['emoji_status'].document_id, 99)
        self.assertEqual(profile['birthday'].day, 29)
        self.assertIsNone(profile['birthday'].year)
        self.assertEqual(profile['personal_channel_id'], 42)
        self.assertEqual(profile['profile_color'].color, 3)
        self.assertEqual(overlay_profile(self.backend, {'id': 20}), {'id': 20})
        self.client.assert_not_awaited()

    async def test_native_colors_use_palette_ids_and_emoji_pattern(self):
        await apply_profile_design(self.backend, 'profile_color', {'color': 7, 'background_emoji_id': 99})
        request = self.client.call_args.args[0]
        self.assertIsInstance(request, f.account.UpdateColorRequest)
        self.assertTrue(request.for_profile)
        self.assertEqual(request.color.color, 7)
        self.assertEqual(request.color.background_emoji_id, 99)
        self.client.get_me.assert_not_awaited()

    async def test_native_status_and_removal_use_telegram_types(self):
        await set_native(self.backend, 'emoji_status', 99)
        request = self.client.call_args.args[0]
        self.assertIsInstance(request, f.account.UpdateEmojiStatusRequest)
        self.assertEqual(request.emoji_status.document_id, 99)
        await set_native(self.backend, 'emoji_status', None)
        self.assertIsInstance(self.client.call_args.args[0].emoji_status, t.EmojiStatusEmpty)

    async def test_native_birthday_omits_optional_year_and_can_remove(self):
        await set_native(self.backend, 'birthday', {'day': 29, 'month': 2})
        request = self.client.call_args.args[0]
        self.assertIsInstance(request, f.account.UpdateBirthdayRequest)
        self.assertIsNone(request.birthday.year)
        await set_native(self.backend, 'birthday', None)
        self.assertIsNone(self.client.call_args.args[0].birthday)

    async def test_personal_channel_resolves_identity_and_rejects_non_channel(self):
        self.client.get_input_entity.return_value = t.InputPeerChannel(42, 123)
        await set_native(self.backend, 'personal_channel', -1000000000042)
        request = self.client.call_args.args[0]
        self.assertIsInstance(request, f.account.UpdatePersonalChannelRequest)
        self.assertEqual(request.channel.channel_id, 42)
        self.assertEqual(request.channel.access_hash, 123)
        await set_native(self.backend, 'personal_channel', None)
        self.assertIsInstance(self.client.call_args.args[0].channel, t.InputChannelEmpty)
        self.client.get_input_entity.return_value = t.InputPeerUser(42, 123)
        self.client.reset_mock()
        with self.assertRaises(ValueError):
            await set_native(self.backend, 'personal_channel', 42)
        self.client.assert_not_awaited()

    async def test_sync_failure_preserves_local_override_and_never_claims_success(self):
        await apply_profile_design(self.backend, 'emoji_status', 99, False)
        self.client.side_effect = ConnectionError
        with self.assertRaises(ConnectionError):
            await apply_profile_design(self.backend, 'emoji_status', 100, True)
        self.assertEqual(self.backend.local_profile_design['emoji_status'], 99)
        self.client.side_effect = None
        self.client.return_value = False
        with self.assertRaises(ValueError):
            await apply_profile_design(self.backend, 'emoji_status', 100, True)
        self.assertEqual(self.backend.local_profile_design['emoji_status'], 99)

    async def test_successful_sync_removes_only_changed_local_field(self):
        await apply_profile_design(self.backend, 'emoji_status', 99, False)
        await apply_profile_design(self.backend, 'name_color', {'color': 7}, False)
        await apply_profile_design(self.backend, 'emoji_status', 100, True)
        self.assertNotIn('emoji_status', self.backend.local_profile_design)
        self.assertEqual(self.backend.local_profile_design['name_color']['color'], 7)

    async def test_revert_local_design_does_not_write_telegram(self):
        await apply_profile_design(self.backend, 'emoji_status', 99, False)
        clear_design(self.backend)
        self.assertEqual(load_design(self.backend.profile_design_path, 'account'), {})
        self.client.assert_not_awaited()

    async def test_color_catalogues_are_cached_separately(self):
        self.client.return_value = NS(colors=[NS(color_id=1, hidden=False), NS(color_id=2, hidden=True)])
        for _ in range(2):
            self.assertEqual([item.color_id for item in await color_options(self.backend)], [1])
            await color_options(self.backend, True)
        self.assertEqual(self.client.await_count, 2)

    async def test_bad_values_never_make_server_requests(self):
        for field, value in [('name_color', {'color': -1}), ('profile_color', {'color': True}),
                             ('emoji_status', True), ('birthday', {'day': 31, 'month': 2}),
                             ('birthday', {'day': 1, 'month': 1, 'year': date.today().year + 1}),
                             ('birthday', {'day': True, 'month': 1}), ('unknown', None)]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                await set_native(self.backend, field, value)
        self.client.assert_not_awaited()

    async def test_empty_color_selection_uses_native_reset(self):
        self.assertIsNone(validate('profile_color', {'color': None, 'background_emoji_id': None}))
        await set_native(self.backend, 'profile_color', {'color': None})
        self.assertIsNone(self.client.call_args.args[0].color)

    async def test_corrupt_local_design_does_not_crash_or_apply_invalid_values(self):
        path = Path(self.folder.name) / 'profile-designs.json'
        path.write_text('{"account":{"emoji_status":true,"birthday":{},"unknown":"bad","name_color":{"color":2}}}', encoding='utf-8')
        self.assertEqual(load_design(path, 'account'), {'name_color': {'color': 2, 'background_emoji_id': None}})
