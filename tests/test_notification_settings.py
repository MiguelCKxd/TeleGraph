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
