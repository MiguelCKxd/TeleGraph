"""1.5.3: offline use, pending actions, clear cache / delete all data."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from telethon import errors, types

from tg_ascii import app_data, offline_store, pending_actions, tl_codec
from tg_ascii.backend import Chat, Message


def sample_message(ident=7):
    entity = types.MessageEntityBold(offset=0, length=4)
    photo = types.MessageMediaPhoto(photo=types.PhotoEmpty(id=99))
    markup = types.ReplyKeyboardHide(selective=True)
    return Message(ident, 'Ana', 'Hola mundo', '10:00', True, photo, 'image', 'a.jpg', 12, ((5, '🙂'),), 'Hola',
                   (entity,), None, True, (('👍', 2, True),), 42, 3, None, markup, True,
                   datetime(2026, 11, 9, 10, 0, tzinfo=timezone.utc))


class CodecTests(unittest.TestCase):
    def test_messages_and_chats_round_trip_with_telegram_objects(self):
        message = sample_message()
        record = json.loads(json.dumps(tl_codec.encode_record(message)))
        back = tl_codec.decode_record(Message, record)
        self.assertEqual(back.text, 'Hola mundo')
        self.assertEqual(back.entities[0].to_dict(), message.entities[0].to_dict())
        self.assertEqual(bytes(back.media), bytes(message.media))
        self.assertEqual(bytes(back.reply_markup), bytes(message.reply_markup))
        self.assertEqual(back.reactions, (('👍', 2, True),))
        self.assertEqual(back.custom_emojis, ((5, '🙂'),))
        self.assertEqual(back.date, message.date)
        chat = Chat(5, 'QA', 3, entity=types.User(id=5, first_name='QA'))
        again = tl_codec.decode_record(Chat, json.loads(json.dumps(tl_codec.encode_record(chat))))
        self.assertEqual((again.id, again.name, again.unread, again.entity.first_name), (5, 'QA', 3, 'QA'))

    def test_unknown_objects_are_dropped_not_pickled(self):
        record = tl_codec.encode_record(Message(1, 'a', 'b', 'c', media=object()))
        self.assertIsNone(record['media'])
        with self.assertRaises(tl_codec.Unsupported):
            tl_codec.encode(object())


class OfflineStoreTests(unittest.TestCase):
    def test_write_read_and_purge(self):
        with tempfile.TemporaryDirectory() as root:
            folder = types.DialogFilter(id=2, title=types.TextWithEntities(text='Work', entities=[]), pinned_peers=[], include_peers=[], exclude_peers=[])
            offline_store.write(root, 'acc', [Chat(1, 'One'), Chat(2, 'Two', 4)], [folder], {1: [sample_message(1), sample_message(2)]})
            path = offline_store.path(root, 'acc')
            if os.name != 'nt':
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            chats, folders, histories = offline_store.read(root, 'acc')
            self.assertEqual([c.name for c in chats], ['One', 'Two'])
            self.assertEqual(folders[0].id, 2)
            self.assertEqual([m.id for m in histories[1]], [1, 2])
            offline_store.purge(root, 'acc')
            self.assertIsNone(offline_store.read(root, 'acc'))

    def test_damaged_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as root:
            path = offline_store.path(root, 'acc')
            path.parent.mkdir(parents=True)
            path.write_text('{broken', encoding='utf-8')
            self.assertIsNone(offline_store.read(root, 'acc'))

    def test_snapshot_keeps_this_account_and_open_chat(self):
        app = SimpleNamespace(ui_account='a', active=3, messages=[sample_message(9)], chats=[Chat(3, 'x')],
                              folder_records=[], _history_cache={('a', 1): [sample_message(1)], ('b', 2): [sample_message(2)]})
        account, chats, folders, histories = offline_store.snapshot(app)
        self.assertEqual(account, 'a')
        self.assertEqual(sorted(histories), [1, 3])


class FakeRecovery:
    def __init__(self, state='online'):
        self.state = state


class FakeBackend:
    """Stands in for TelegramBackend: the same wrapper is applied to it."""
    demo = False

    def __init__(self):
        self.calls = []
        self.fail = None

    async def archive_chat(self, peer, archived):
        if self.fail:
            raise self.fail
        self.calls.append(('archive_chat', peer, archived))
        return True

    async def react(self, peer, ident, value):
        if self.fail:
            raise self.fail
        self.calls.append(('react', peer, ident, value))
        return f'updated {ident}'


def wrapped_backend():
    backend = FakeBackend()
    for name in ('archive_chat', 'react'):
        original = getattr(FakeBackend, name)
        pending_actions._originals.setdefault(name, original)
        setattr(backend, name, pending_actions._wrap(name, original).__get__(backend))
    return backend


class PendingActionsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.changes = []
        self.client = Mock(is_connected=Mock(return_value=False))
        self.service = SimpleNamespace(root=Path(self.folder.name), client=self.client,
                                       recovery=FakeRecovery('offline'),
                                       on_change=lambda kind, payload: self.changes.append((kind, payload)))
        self.backend = wrapped_backend()
        self.service.backend = self.backend
        self.queue = pending_actions.PendingActions(self.service, 'acc')
        self.backend.pending_actions = self.queue

    async def test_offline_actions_wait_and_are_sent_in_order_when_back(self):
        first = await self.backend.archive_chat(5, True)
        second = await self.backend.react(5, 10, '👍')
        self.assertIsInstance(first, pending_actions.Queued)
        self.assertIsInstance(second, pending_actions.Queued)
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(self.changes[-1], ('pending', {'count': 2}))
        answers = []
        second.record.callbacks.append(lambda value, failed: answers.append((value, failed)))
        self.client.is_connected.return_value = True
        self.service.recovery.state = 'online'
        await self.queue.flush()
        self.assertEqual(self.backend.calls, [('archive_chat', 5, True), ('react', 5, 10, '👍')])
        self.assertEqual(answers, [('updated 10', False)])
        self.assertEqual(self.queue.records, [])
        self.assertFalse(self.queue.path.exists())

    async def test_repeated_changes_keep_only_the_last(self):
        await self.backend.archive_chat(5, True)
        await self.backend.archive_chat(5, False)
        await self.backend.archive_chat(6, True)
        self.assertEqual([r.args for r in self.queue.records], [[5, False], [6, True]])

    async def test_queue_survives_a_restart(self):
        await self.backend.react(5, 10, '❤')
        if os.name != 'nt':
            self.assertEqual(self.queue.path.stat().st_mode & 0o777, 0o600)
        again = pending_actions.PendingActions(self.service, 'acc')
        self.assertEqual([(r.method, r.args) for r in again.records], [('react', [5, 10, '❤'])])

    async def test_connection_drop_while_online_is_queued(self):
        self.client.is_connected.return_value = True
        self.service.recovery.state = 'online'
        self.backend.fail = ConnectionError('dropped')
        result = await self.backend.archive_chat(5, True)
        self.assertIsInstance(result, pending_actions.Queued)
        self.backend.fail = errors.ChatAdminRequiredError(None)
        with self.assertRaises(errors.ChatAdminRequiredError):
            await self.backend.react(5, 1, 'x')  # Refusals are shown, never queued.
        self.assertEqual(len(self.queue.records), 1)

    async def test_replay_stops_on_connection_problems_and_drops_refusals(self):
        await self.backend.archive_chat(5, True)
        await self.backend.react(5, 10, '👍')
        self.client.is_connected.return_value = True
        self.service.recovery.state = 'online'
        self.backend.fail = ConnectionError('again')
        await self.queue.flush()
        self.assertEqual(len(self.queue.records), 2)
        self.backend.fail = errors.MessageIdInvalidError(None)
        await self.queue.flush()
        self.assertEqual(self.queue.records, [])
        self.assertTrue(any(kind == 'pending' and payload.get('failed') for kind, payload in self.changes))

    async def test_unsupported_values_stay_in_memory_only(self):
        await self.backend.react(5, 10, object())
        self.assertFalse(self.queue.records[0].persist)
        self.assertFalse(self.queue.path.exists())


class RandomIdTests(unittest.TestCase):
    def test_forwards_reuse_the_same_random_ids(self):
        from telethon.tl import functions
        from tg_ascii import outbox
        pending_actions._patch_forward_ids()
        ids = []

        async def build():
            return functions.messages.ForwardMessagesRequest(from_peer=types.InputPeerSelf(), id=[1, 2], to_peer=types.InputPeerSelf())
        first = asyncio.run(outbox.with_random_ids(ids, build()))
        second = asyncio.run(outbox.with_random_ids(ids, build()))
        self.assertEqual(first.random_id, second.random_id)
        self.assertEqual(len(first.random_id), 2)


class DesktopHandlingTests(unittest.TestCase):
    def app(self):
        events = []
        app = SimpleNamespace(status=Mock(), chats=[Chat(5, 'x')], render_chats=Mock(), demo=True,
                              worker=SimpleNamespace(events=SimpleNamespace(put=events.append)), show_error=Mock())
        return app, events

    def test_list_changes_show_at_once(self):
        app, _ = self.app()
        record = pending_actions.Record('archive_chat', [5, True], {})
        success = Mock()
        self.assertTrue(pending_actions.handle(app, pending_actions.Queued(record), success))
        success.assert_called_once()
        self.assertTrue(app.chats[0].archived)
        app.render_chats.assert_called()

    def test_results_that_are_needed_arrive_when_sent(self):
        app, events = self.app()
        record = pending_actions.Record('react', [5, 10, '👍'], {})
        success = Mock()
        self.assertTrue(pending_actions.handle(app, pending_actions.Queued(record), success))
        success.assert_not_called()
        record.callbacks[0]('updated', False)
        self.assertEqual(events, [(success, 'updated')])
        self.assertFalse(pending_actions.handle(app, 'plain value', success))


class OfflineStartTests(unittest.IsolatedAsyncioTestCase):
    async def test_signed_in_device_opens_without_network(self):
        from tg_ascii.desktop_service import DesktopService
        with tempfile.TemporaryDirectory() as root:
            session = SimpleNamespace(auth_key=SimpleNamespace(key=b'k' * 256))
            client = Mock(session=session, connect=AsyncMock(side_effect=OSError('no network')),
                          disconnect=AsyncMock(), is_connected=Mock(return_value=False))
            service = DesktopService(root=root, client_factory=lambda *a, **k: client)
            with patch('tg_ascii.desktop_service.TelegramBackend') as backend_class, \
                    patch('tg_ascii.recovery.Recovery.start'):
                backend_class.return_value = SimpleNamespace(account_profile=Mock(), demo=False)
                self.assertEqual(await service.connect((12345, 'a' * 32)), 'ready')
            self.assertTrue(service.offline_start)
            self.assertEqual(service.recovery.state, 'offline')
            self.assertIs(service.backend.pending_actions, service.pending)

    async def test_new_device_without_network_still_reports_the_error(self):
        from tg_ascii.desktop_service import DesktopService
        with tempfile.TemporaryDirectory() as root:
            client = Mock(session=SimpleNamespace(auth_key=None), connect=AsyncMock(side_effect=ConnectionError('x')),
                          disconnect=AsyncMock())
            service = DesktopService(root=root, client_factory=lambda *a, **k: client)
            with self.assertRaises(ConnectionError):
                await service.connect((12345, 'a' * 32))

    async def test_accounts_register_offline_with_saved_identity(self):
        from tg_ascii.accounts import Accounts
        with tempfile.TemporaryDirectory() as root:
            key = 'a' * 32
            Path(root, 'accounts.json').write_text(json.dumps({'active': key, 'accounts': {key: {'label': 'QA', 'user_id': 77}}}), encoding='utf-8')
            accounts = Accounts(root=root)
            accounts.services[key] = SimpleNamespace(offline_start=True)
            await accounts.register(key)
            self.assertEqual((accounts.labels[key], accounts.identities[key]), ('QA', 77))
            self.assertIn(key, accounts.failures)


class AppDataTests(unittest.TestCase):
    def test_clear_cache_keeps_everything_else(self):
        with tempfile.TemporaryDirectory() as root:
            for name in ('media-cache/a/x.bin', 'offline-cache/a.json', 'drafts.json', 'account.session', 'preferences.json'):
                path = Path(root, name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'12345')
            self.assertEqual(app_data.cache_size(root), 10)
            self.assertEqual(app_data.remove_cache(root), 10)
            self.assertFalse(Path(root, 'media-cache').exists())
            self.assertTrue(Path(root, 'drafts.json').exists() and Path(root, 'account.session').exists())

    def test_wipe_only_deletes_a_real_data_folder(self):
        with tempfile.TemporaryDirectory() as parent:
            empty = Path(parent, 'empty'); empty.mkdir()
            self.assertFalse(app_data.safe_to_wipe(empty))
            self.assertFalse(app_data.safe_to_wipe(Path.home()))
            data = Path(parent, 'data'); data.mkdir()
            (data / 'preferences.json').write_text('{}', encoding='utf-8')
            self.assertTrue(app_data.safe_to_wipe(data))
            self.assertTrue(app_data.wipe(data))
            self.assertFalse(data.exists())
            self.assertTrue(empty.exists())

    def test_lifecycle_wipes_after_close_and_restarts(self):
        from tg_ascii import app_lifecycle
        with tempfile.TemporaryDirectory() as parent:
            data = Path(parent, 'data'); data.mkdir(); (data / 'accounts.json').write_text('{}', encoding='utf-8')
            app_lifecycle.request_wipe(data)
            with patch('tg_ascii.app_lifecycle.relaunch') as relaunch, patch('threading.Thread'):
                app_lifecycle.finish()
            relaunch.assert_called_once()
            self.assertFalse(data.exists())
            app_lifecycle.request(None)


if __name__ == '__main__':
    unittest.main()


class DemoSafetyTests(unittest.TestCase):
    def test_demo_never_touches_the_real_data_folder(self):
        status = Mock()
        app = SimpleNamespace(demo=True, status=status, service=SimpleNamespace(root='/nonexistent'), root=None)
        with patch('tg_ascii.app_dialogs.messagebox.askyesno') as ask:
            app_data.clear_cache(app)
            app_data.delete_all_data(app)
        ask.assert_not_called()
        self.assertEqual(status.set.call_count, 2)
