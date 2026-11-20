"""No actual push registrations, accounts or OS notifications are used."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import plistlib
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

from tg_ascii.notification_delivery import DeliveryLedger
from tg_ascii.notifications import NotificationCenter
from tg_ascii.push_notifications import PushController, PushHint, parse_hint
from tg_ascii.push_windows import PushUnavailable, capability, valid_channel_uri, WindowsPushChannel
from tg_ascii.push_macos import MacPushChannel, capability as mac_capability, valid_apns_token


class DeliveryLedgerTests(unittest.TestCase):
    def test_live_and_push_only_one_claim_and_failure_releases(self):
        ledger = DeliveryLedger()
        first = ledger.claim('a', 4, 7)
        self.assertIsNone(ledger.claim('a', 4, 7))
        ledger.commit(first)
        self.assertIsNone(ledger.claim('a', 4, 7))
        ledger.release(first)
        self.assertIsNotNone(ledger.claim('a', 4, 7))

    def test_expired_owner_cannot_delete_or_commit_a_newer_claim(self):
        now = [1000.0]
        ledger = DeliveryLedger(clock=lambda: now[0])
        first = ledger.claim('a', 4, 7)
        now[0] += ledger.RESERVATION + 1
        second = ledger.claim('a', 4, 7)
        self.assertIsNotNone(second)
        ledger.release(first)
        self.assertFalse(ledger.commit(first))
        self.assertIsNone(ledger.claim('a', 4, 7))
        self.assertTrue(ledger.commit(second))

    def test_accounts_and_chats_are_isolated(self):
        ledger = DeliveryLedger()
        for account, peer in [('a', 4), ('b', 4), ('a', 5)]:
            self.assertTrue(ledger.commit(ledger.claim(account, peer, 7)))

    def test_committed_id_survives_restart_without_message_content(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'delivery.sqlite'
            ledger = DeliveryLedger(path)
            ledger.commit(ledger.claim('private-account-label', 4, 7))
            ledger.close()
            again = DeliveryLedger(path)
            self.assertIsNone(again.claim('private-account-label', 4, 7))
            again.close()
            self.assertNotIn(b'private-account-label', path.read_bytes())

    def test_cross_connection_race_has_exactly_one_owner(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'delivery.sqlite'
            first, second = DeliveryLedger(path), DeliveryLedger(path)
            first._database(); second._database()
            with ThreadPoolExecutor(2) as executor:
                results = list(executor.map(lambda ledger: ledger.claim('a', 4, 7), (first, second)))
            self.assertEqual(sum(value is not None for value in results), 1)
            first.close(); second.close()

    def test_memory_keeps_recent_ids_when_limit_reached(self):
        ledger = DeliveryLedger(); ledger.LIMIT = 4
        for message in range(6):
            ledger.commit(ledger.claim('a', 4, message))
        self.assertEqual(len(ledger._memory), 4)
        for message in range(2, 6):
            self.assertIsNone(ledger.claim('a', 4, message))

    def test_expired_commits_can_be_forgotten(self):
        now = [1000.0]
        ledger = DeliveryLedger(clock=lambda: now[0])
        ledger.commit(ledger.claim('a', 4, 7))
        now[0] += ledger.RETENTION + 1
        self.assertIsNotNone(ledger.claim('a', 4, 7))

    def test_corrupt_cache_falls_back_without_losing_normal_notifications(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'delivery.sqlite'
            path.write_bytes(b'not a sqlite database')
            ledger = DeliveryLedger(path)
            self.assertTrue(ledger.commit(ledger.claim('a', 4, 7)))
            self.assertTrue(ledger.storage_error)
            self.assertIsNone(ledger.claim('a', 4, 7))
            self.assertEqual(path.read_bytes(), b'not a sqlite database')

    def test_database_failure_after_open_preserves_current_delivery_ids(self):
        with TemporaryDirectory() as temp:
            ledger = DeliveryLedger(Path(temp) / 'delivery.sqlite')
            committed = ledger.claim('a', 4, 7)
            self.assertTrue(ledger.commit(committed))
            pending = ledger.claim('a', 4, 8)
            ledger._connection.close()  # Simulate a lost connection after startup.
            self.assertTrue(ledger.commit(pending))
            self.assertTrue(ledger.storage_error)
            self.assertIsNone(ledger.claim('a', 4, 7))
            self.assertIsNone(ledger.claim('a', 4, 8))
            ledger.release(pending)
            self.assertIsNotNone(ledger.claim('a', 4, 8))

    def test_database_failure_during_claim_and_release_keeps_notifier_available(self):
        for operation in ('claim', 'release'):
            with self.subTest(operation=operation), TemporaryDirectory() as temp:
                ledger = DeliveryLedger(Path(temp) / 'delivery.sqlite')
                first = ledger.claim('a', 4, 7)
                ledger._connection.close()
                if operation == 'claim':
                    self.assertIsNotNone(ledger.claim('a', 4, 8))
                    self.assertIsNone(ledger.claim('a', 4, 7))
                else:
                    ledger.release(first)
                    self.assertIsNotNone(ledger.claim('a', 4, 7))
                self.assertTrue(ledger.storage_error)


class PushPayloadTests(unittest.TestCase):
    def test_channel_is_https_and_owned_by_wns(self):
        self.assertTrue(valid_channel_uri('https://db5.notify.windows.com/?token=secret'))
        for value in ('http://db5.notify.windows.com/a', 'https://notify.windows.com.evil/a',
                      'https://evil@notify.windows.com/a', 'https://notify.windows.com:45/a',
                      'https://notify.windows.com/a#fragment', 'file:///secret', None):
            self.assertFalse(valid_channel_uri(value))

    def test_payload_selects_account_and_channel_without_using_preview(self):
        payload = {'data': {'user_id': '22', 'loc_key': 'CHANNEL_MESSAGE_TEXT',
                   'custom': {'channel_id': '45', 'msg_id': '9'}, 'message': 'untrusted'}}
        self.assertEqual(parse_hint(json.dumps(payload)), PushHint(22, -1000000000045, 9))

    def test_maintenance_and_unknown_payloads_do_not_display_messages(self):
        for kind in ('SESSION_REVOKE', 'MESSAGE_MUTED', 'READ_HISTORY', 'DC_UPDATE'):
            self.assertEqual(parse_hint(json.dumps({'user_id': 22, 'loc_key': kind,
                'custom': {'from_id': 7, 'msg_id': 9}})), PushHint(22))
        for payload in ('[]', 'null', '{}', '{', 'x' * 65537, '{"data": []}', '{"user_id": -1}'):
            self.assertIsNone(parse_hint(payload))

    def test_other_platform_does_not_import_windows(self):
        with patch('tg_ascii.push_windows.sys.platform', 'darwin'):
            self.assertFalse(capability().available)


class NativeDeliveryFailureTests(unittest.TestCase):
    def test_retry_backoff_releases_claim_instead_of_dropping_it(self):
        center = NotificationCenter(Mock())
        center.unavailable = True
        center.retry_at = float('inf')
        failed = Mock()
        self.assertFalse(center.show('a', 'b', 'c', on_failed=failed))
        failed.assert_called_once()

    def test_asynchronous_permission_failure_releases_claim(self):
        adapter = Mock()
        center = NotificationCenter(Mock()); center.adapter = adapter
        failed = Mock()
        self.assertTrue(center.show('a', 'b', 'c', on_failed=failed))
        adapter.show.call_args.args[3]('denied')
        failed.assert_called_once()


class PushControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = AsyncMock(return_value=True)
        self.service = NS(client=self.client, backend=NS(message=lambda raw: raw), recovery=NS(ensure=AsyncMock()))
        self.accounts = NS(demo=False, entries={'a': {}}, services={'a': self.service}, identities={'a': 22})
        self.channel = NS(open=AsyncMock(return_value='https://db5.notify.windows.com/?secret'), close=AsyncMock())
        self.publish, self.report = Mock(), Mock()
        self.controller = PushController(self.accounts, self.publish, self.report, channel_factory=lambda: self.channel)

    async def asyncTearDown(self):
        await self.controller.close()

    async def drain(self):
        await asyncio.gather(*tuple(self.controller._tasks), return_exceptions=True)

    async def test_off_does_not_open_channel_or_register(self):
        await self.controller.configure(False)
        self.channel.open.assert_not_awaited()
        self.client.assert_not_awaited()

    async def test_registration_is_idempotent_and_disable_unregisters(self):
        await self.controller.configure(True)
        await self.controller.configure(True)
        self.channel.open.assert_awaited_once()
        self.assertEqual(self.client.await_count, 1)
        request = self.client.call_args.args[0]
        self.assertEqual(request.token_type, 8)
        self.assertEqual(request.secret, b'')
        await self.controller.configure(False)
        self.assertEqual(type(self.client.call_args.args[0]).__name__, 'UnregisterDeviceRequest')
        self.channel.close.assert_awaited_once()
        self.assertFalse(self.controller.registered)

    async def test_missing_platform_is_a_nonfatal_status(self):
        self.channel.open.side_effect = PushUnavailable('no package')
        await self.controller.configure(True)
        self.assertIsNone(self.controller.channel)
        self.client.assert_not_awaited()
        self.assertIn('normales', self.controller.status)

    async def test_registry_callbacks_do_not_repeat_failed_channel_requests(self):
        now = [100.0]
        self.controller.clock = lambda: now[0]
        self.channel.open.side_effect = PushUnavailable('no package')
        for _ in range(12):
            await self.controller.configure(True)
        self.channel.open.assert_awaited_once()
        now[0] += 61
        await self.controller.configure(True)
        self.assertEqual(self.channel.open.await_count, 2)

    async def test_unregister_removes_exact_registered_account_clients(self):
        await self.controller.configure(True)
        other = AsyncMock(return_value=True)
        self.accounts.services['b'] = NS(client=other, backend=object())
        # b has not reached ready/registration and must never be touched.
        await self.controller.configure(False)
        other.assert_not_awaited()

    async def test_payload_for_unregistered_account_never_opens_it(self):
        await self.controller.configure(True)
        self.client.reset_mock()
        self.controller.receive('{"user_id":99,"custom":{"from_id":4,"msg_id":7}}')
        await self.drain()
        self.client.assert_not_awaited()
        self.publish.assert_not_called()

    async def test_live_event_makes_delayed_push_free_of_network_work(self):
        await self.controller.configure(True)
        self.controller.note_live('a', 4, 7)
        self.client.reset_mock()
        self.controller.receive('{"user_id":22,"custom":{"from_id":4,"msg_id":7}}')
        await self.drain()
        self.client.assert_not_awaited()
        self.service.recovery.ensure.assert_not_awaited()

    async def test_push_is_validated_against_read_state_and_canonical_message(self):
        from telethon.types import InputPeerUser
        await self.controller.configure(True)
        self.client.get_input_entity = AsyncMock(return_value=InputPeerUser(4, 5))
        self.client.catch_up = AsyncMock()
        message = NS(out=False, id=7, text='from telegram')
        self.client.get_messages = AsyncMock(return_value=message)
        self.client.return_value = NS(dialogs=[NS(read_inbox_max_id=7)])
        payload = '{"user_id":22,"custom":{"from_id":4,"msg_id":7},"message":"never display"}'
        self.controller.receive(payload)
        await self.drain()
        self.publish.assert_not_called()
        self.client.return_value = NS(dialogs=[NS(read_inbox_max_id=6)])
        self.controller.receive(payload)
        await self.drain()
        self.publish.assert_called_once_with('a', 4, message)

    async def test_disabling_cancels_in_flight_recovery(self):
        await self.controller.configure(True)
        started = asyncio.Event()
        async def stalled():
            started.set()
            await asyncio.Future()
        self.service.recovery.ensure.side_effect = stalled
        self.controller.receive('{"user_id":22,"custom":{"from_id":4,"msg_id":7}}')
        await started.wait()
        await self.controller.configure(False)
        self.publish.assert_not_called()
        self.assertFalse(self.controller._tasks)


class WindowsChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_callback_cancels_native_duplicate_and_queues_raw_hint(self):
        channel = NS(uri='https://db5.notify.windows.com/a',
                     add_push_notification_received=Mock(return_value='event'),
                     remove_push_notification_received=Mock(), close=Mock())
        manager = NS(create_push_notification_channel_for_application_async=AsyncMock(return_value=channel))
        module = NS(PushNotificationChannelManager=manager, PushNotificationType=NS(RAW=3))
        receive = Mock(); transport = WindowsPushChannel()
        with patch('tg_ascii.push_windows.capability', return_value=NS(available=True)), \
             patch.dict('sys.modules', {'winrt.windows.networking.pushnotifications': module}):
            await transport.open(receive)
            event = NS(cancel=False, notification_type=3, raw_notification=NS(content='{"user_id":22}'))
            channel.add_push_notification_received.call_args.args[0](channel, event)
            self.assertTrue(event.cancel)
            await asyncio.sleep(0)
            receive.assert_called_once_with('{"user_id":22}')
            await transport.close()
        channel.remove_push_notification_received.assert_called_once_with('event')
        channel.close.assert_called_once()

    async def test_macos_apns_token_type_and_capability_detection(self):
        self.assertTrue(valid_apns_token('a' * 64))
        self.assertFalse(valid_apns_token('short'))
        self.assertFalse(valid_apns_token('g' * 64))
        with patch('tg_ascii.push_macos.sys.platform', 'win32'):
            self.assertFalse(mac_capability().available)
        with patch('tg_ascii.push_macos.sys.platform', 'darwin'), \
             patch('tg_ascii.push_macos._bundle_path', return_value=None):
            self.assertFalse(mac_capability().available)
        channel = MacPushChannel()
        with patch('tg_ascii.push_macos.capability', return_value=NS(available=True)), \
             patch('tg_ascii.push_macos._bundle_path', return_value=Path('/tmp/TG-ASCII.app')), \
             patch('tg_ascii.push_macos._entitlement_environment', return_value='development'), \
             patch.object(MacPushChannel, '_request_token', AsyncMock(return_value='A' * 64)):
            client = AsyncMock(return_value=True)
            service = NS(client=client, backend=NS(message=lambda raw: raw), recovery=NS(ensure=AsyncMock()))
            accounts = NS(demo=False, entries={'a': {}}, services={'a': service}, identities={'a': 22})
            controller = PushController(accounts, Mock(), Mock(), channel_factory=lambda: channel)
            await controller.configure(True)
            req = client.call_args.args[0]
            self.assertEqual(req.token_type, 1)
            self.assertTrue(req.app_sandbox)
            self.assertEqual(req.token, 'a' * 64)
            await controller.configure(False)
            unreg = client.call_args.args[0]
            self.assertEqual(unreg.token_type, 1)

    def test_mac_capability_uses_only_the_running_bundle(self):
        from tg_ascii import push_macos
        with TemporaryDirectory() as folder:
            home = Path(folder)
            app = home / 'Applications/TG-ASCII.app'
            (app / 'Contents/MacOS').mkdir(parents=True)
            (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': push_macos.APP_ID}))
            with patch.dict('sys.modules', {'Foundation': None}), patch.object(Path, 'home', return_value=home):
                with patch.object(push_macos.sys, 'executable', str(home / 'python')):
                    self.assertIsNone(push_macos._bundle_path())
                with patch.object(push_macos.sys, 'executable', str(app / 'Contents/MacOS/TG-ASCII')):
                    self.assertEqual(push_macos._bundle_path(), app.resolve())

    def test_profile_without_signed_push_entitlement_does_not_enable_apns(self):
        from tg_ascii import push_macos
        with TemporaryDirectory() as folder:
            bundle = Path(folder) / 'TG-ASCII.app'
            (bundle / 'Contents').mkdir(parents=True)
            (bundle / 'Contents/embedded.provisionprofile').touch()
            result = NS(returncode=0, stdout=plistlib.dumps({}))
            with patch.object(push_macos.subprocess, 'run', return_value=result) as run:
                self.assertIsNone(push_macos._entitlement_environment(bundle))
                run.assert_called_once()
                result.stdout = plistlib.dumps({'com.apple.developer.aps-environment': 'development'})
                self.assertEqual(push_macos._entitlement_environment(bundle), 'development')


class DesktopNotificationRaceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from tg_ascii.desktop_plus import DesktopPlus
        self.plus = DesktopPlus
        self.tasks = []
        self.backend = NS(notification_policy=AsyncMock(return_value={'enabled': True, 'preview': True, 'sound': False}))
        self.app = NS(demo=False, closed=False, closing=False, notify_seen=set(), notification_ledger=DeliveryLedger(),
            preferences=NS(values={'notifications': True, 'notify_preview': True, 'notify_sound': False, 'notify_active': False}),
            ui_account='a', active=6, root=NS(state=lambda: 'withdrawn', focus_displayof=lambda: None),
            chat_visible=lambda: False, service=NS(entries={'a': {}}, labels={'a': 'Account'}, service=lambda _: NS(backend=self.backend)),
            worker=NS(submit=lambda coroutine, success, failure: self.tasks.append((coroutine, success, failure))),
            notification_open_callback=Mock(), notification_reply_callback=Mock(), inline_notice=Mock(),
            notification_center=Mock())
        self.message = NS(id=7, outgoing=False, sender='Ada', text='authentic')

    async def drain(self):
        while self.tasks:
            coroutine, success, failure = self.tasks.pop(0)
            try:
                result = await coroutine
            except Exception as error:
                failure(error)
            else:
                success(result)

    async def test_live_and_push_race_produces_exactly_one_os_notice(self):
        self.plus.notify_message(self.app, 'a', 4, self.message)
        self.plus.notify_message(self.app, 'a', 4, self.message, source='push')
        await self.drain()
        self.app.notification_center.show.assert_called_once()
        self.app.notify_seen.clear()  # simulate a replay outside the small UI cache
        self.plus.notify_message(self.app, 'a', 4, self.message, source='push')
        await self.drain()
        self.app.notification_center.show.assert_called_once()

    async def test_native_failure_releases_for_a_later_push(self):
        self.plus.notify_message(self.app, 'a', 4, self.message)
        await self.drain()
        self.app.notification_center.show.call_args.kwargs['on_failed']()
        await self.drain()
        self.plus.notify_message(self.app, 'a', 4, self.message, source='push')
        await self.drain()
        self.assertEqual(self.app.notification_center.show.call_count, 2)

    async def test_muted_push_does_not_show_or_ring(self):
        self.backend.notification_policy.return_value['enabled'] = False
        self.plus.notify_message(self.app, 'a', 4, self.message, source='push')
        await self.drain()
        self.app.notification_center.show.assert_not_called()
        self.app.inline_notice.show.assert_not_called()


if __name__ == '__main__':
    unittest.main()
