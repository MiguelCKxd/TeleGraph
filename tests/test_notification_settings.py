import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock

from telethon import types

from tg_ascii_mobile.core import Core
from tg_ascii_mobile.notification_settings import changes_from_web, reactions_from_web, read_settings


class NotificationSettingsTests(TestCase):
    def test_provider_environment_for_simulator_and_signed_devices(self):
        from tg_ascii_mobile.notify_native import apns_uses_sandbox
        with TemporaryDirectory() as tmp:
            profile = Path(tmp) / 'embedded.mobileprovision'
            self.assertTrue(apns_uses_sandbox(profile, 'simulator-uuid'))
            self.assertFalse(apns_uses_sandbox(profile, None))
            for environment in ('development', 'production'):
                profile.write_bytes(f'<key>aps-environment</key>\n<string>{environment}</string>'.encode())
                self.assertEqual(apns_uses_sandbox(profile, None), environment == 'development')

    def test_platform_sound_takes_precedence(self):
        settings = types.PeerNotifySettings(
            ios_sound=types.NotificationSoundNone(),
            android_sound=types.NotificationSoundRingtone(25),
            other_sound=types.NotificationSoundDefault(),
        )
        self.assertEqual(read_settings(settings, 'iOS')['sound'], 'none')
        self.assertEqual(read_settings(settings, 'Android')['sound'], 'ringtone:25')
        self.assertEqual(read_settings(settings, 'macOS-dev')['sound'], 'default')

    def test_delta_keeps_unrelated_fields_out_of_request(self):
        changes = changes_from_web({'mute_until': 0, 'stories_muted': True})
        self.assertEqual(set(changes), {'mute_until', 'stories_muted'})
        self.assertEqual(changes['mute_until'].timestamp(), 0)
        with self.assertRaises(ValueError):
            changes_from_web({'show_previews': 'false'})

    def test_reaction_delta_preserves_other_scopes_and_ringtone(self):
        sound = types.NotificationSoundRingtone(25)
        before = types.ReactionsNotifySettings(sound, True, stories_notify_from=types.ReactionNotificationsFromContacts())
        after = reactions_from_web(before, {'messages': 'all', 'show_previews': False})
        self.assertIs(after.sound, sound)
        self.assertIsInstance(after.messages_notify_from, types.ReactionNotificationsFromAll)
        self.assertIsInstance(after.stories_notify_from, types.ReactionNotificationsFromContacts)
        self.assertIsNone(before.messages_notify_from)
        self.assertTrue(before.show_previews)
        self.assertFalse(after.show_previews)


class LocalNotificationTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.core = Core(Path(directory.name), 'iOS')
        self.addCleanup(self.core.loop.close)
        self.backend = SimpleNamespace(notification_policy=AsyncMock())
        self.core.accounts = SimpleNamespace(current='qa', entries={'qa': {}},
                                            services={'qa': SimpleNamespace(backend=self.backend)})
        self.core.prefs = SimpleNamespace(values={'notifications': True, 'notify_preview': True})
        self.core.native_notify = Mock()
        self.core.in_background = True
        self.message = SimpleNamespace(outgoing=False, service=False, read=False, sender='QA')

    async def test_remote_muting_suppresses_local_alert(self):
        self.backend.notification_policy.return_value = {'enabled': False, 'preview': True, 'sound': True}
        await self.core.notify('qa', 42, self.message)
        self.core.native_notify.assert_not_called()

    async def test_private_silent_notification_never_reads_or_emits_body(self):
        self.backend.notification_policy.return_value = {'enabled': True, 'preview': False, 'sound': False}
        await self.core.notify('qa', 42, self.message)
        self.backend.notification_policy.assert_awaited_once_with(42, platform='iOS')
        self.assertEqual(self.core.native_notify.call_args.args[:3], ('qa', 42, 'QA'))
        self.assertEqual(self.core.native_notify.call_args.args[-2:], (1, False))

    async def test_protected_notification_hides_sender_and_account(self):
        self.core.lock_record = lambda: {'hash': 'test'}
        self.backend.notification_policy.return_value = {'enabled': True, 'preview': True, 'sound': True}
        await self.core.notify('qa', 42, self.message)
        self.assertEqual(self.core.native_notify.call_args.args[2], 'TeleGraph')

    async def test_logout_during_policy_lookup_does_not_post(self):
        async def policy(*args, **kwargs):
            self.core.accounts.services.pop('qa')
            return {'enabled': True, 'preview': True, 'sound': True}
        self.backend.notification_policy.side_effect = policy
        await self.core.notify('qa', 42, self.message)
        self.core.native_notify.assert_not_called()

    async def test_foreground_group_uses_sender_and_routes_banner_to_main_window(self):
        self.core.in_background = False
        self.message.sender_id, self.message.text = 701, 'mensaje'
        self.core.chats = [SimpleNamespace(id=-99, name='Grupo', muted=False)]
        self.backend.notification_policy.return_value = {'enabled': True, 'preview': True, 'sound': True}
        main, secondary = asyncio.Queue(), asyncio.Queue()
        secondary.window_account = 'qa'
        self.core.subscribers = {main, secondary}
        await self.core.notify('qa', -99, self.message)
        packet = json.loads(main.get_nowait())
        self.assertEqual(packet['type'], 'message_notice')
        self.assertEqual(packet['data'], {'account': 'qa', 'peer': -99, 'title': 'QA', 'sender': 701,
                                         'conversation': 'Grupo', 'body': 'mensaje'})
        self.assertTrue(secondary.empty())
        self.core.native_notify.assert_not_called()
        self.core.open_peer = -99
        await self.core.notify('qa', -99, self.message)
        self.assertTrue(main.empty())

    async def test_duplicate_android_notice_skips_avatar_download(self):
        self.core.system = 'Android'
        self.message.id, self.message.text = 11, 'texto'
        self.backend.client = SimpleNamespace(download_profile_photo=AsyncMock(return_value=b'avatar'))
        self.backend.notification_policy.return_value = {'enabled': True, 'preview': True, 'sound': True}
        await self.core.notify('qa', 42, self.message)
        await self.core.notify('qa', 42, self.message)
        self.backend.client.download_profile_photo.assert_awaited_once()
        self.core.native_notify.assert_called_once()

    async def test_disabling_notices_during_avatar_fetch_allows_a_later_retry(self):
        self.core.system = 'Android'
        self.message.id, self.message.text = 12, 'texto'
        async def disable(*args, **kwargs):
            self.core.prefs.values['notifications'] = False
            return b'avatar'
        self.backend.client = SimpleNamespace(download_profile_photo=AsyncMock(side_effect=disable))
        self.backend.notification_policy.return_value = {'enabled': True, 'preview': True, 'sound': True}
        await self.core.notify('qa', 42, self.message)
        self.core.native_notify.assert_not_called()
        self.core.prefs.values.update(notifications=True, notify_preview=False)
        await self.core.notify('qa', 42, self.message)
        self.backend.client.download_profile_photo.assert_awaited_once()
        self.core.native_notify.assert_called_once()
        self.assertFalse(self.core.native_notify.call_args.kwargs)

    async def test_background_avatar_comes_from_sending_account_and_hidden_preview_omits_it(self):
        self.message.sender_id, self.message.text = 701, 'mensaje'
        folder = self.core.root / 'mobile-avatars' / 'qa'
        folder.mkdir(parents=True)
        (folder / '701.jpg').write_bytes(b'cached jpeg')
        self.backend.notification_policy.return_value = {'enabled': True, 'preview': True, 'sound': True}
        await self.core.notify('qa', -99, self.message)
        self.assertEqual(self.core.native_notify.call_args.kwargs,
                         {'sender': '701', 'picture': b'cached jpeg', 'conversation': ''})
        self.core.prefs.values['notify_preview'] = False
        await self.core.notify('qa', -99, self.message)
        self.assertFalse(self.core.native_notify.call_args.kwargs)
        self.assertNotIn('mensaje', self.core.native_notify.call_args.args)


class NotificationExtensionCacheTests(TestCase):
    def test_removing_account_or_disabling_previews_removes_its_photos_and_policy_access(self):
        import plistlib
        from tg_ascii_mobile.ios_notice_cache import NoticeCache
        with TemporaryDirectory() as tmp:
            cache = NoticeCache(tmp)
            core = SimpleNamespace(accounts=SimpleNamespace(entries={'a': {}, 'b': {}}, identities={'a': 7, 'b': 8}),
                                   prefs=SimpleNamespace(values={}), _push_logging_out=set(), lock_record=lambda: None)
            cache.sync(core)
            cache.thumbnail(7, 42, b'photo for account 7')
            cache.thumbnail(8, 42, b'photo for account 8')
            core._push_logging_out.add('a')
            cache.sync(core)
            self.assertFalse((cache.root / '7').exists())
            self.assertEqual((cache.root / '8/42.jpg').read_bytes(), b'photo for account 8')
            core.prefs.values['notify_preview'] = False
            cache.sync(core)
            self.assertFalse((cache.root / '8').exists())
            self.assertEqual(plistlib.loads((cache.root / 'policy.plist').read_bytes())['accounts'], [])
            cache.thumbnail(8, 42, b'stale fetch')
            self.assertFalse((cache.root / '8').exists())
