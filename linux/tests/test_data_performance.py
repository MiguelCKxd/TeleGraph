"""Bounded data work, preserving cancellation, pending edits and cache semantics."""
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

from telethon import types, utils

from tg_ascii.backend import TelegramBackend, Chat
from tg_ascii.drafts import DraftStore, DraftManager
from tg_ascii.translation_queue import schedule
from tg_ascii.telegram_features import compile_folder, matches_folder


class DraftWorkTests(unittest.IsolatedAsyncioTestCase):
    async def test_unchanged_flush_does_not_copy_or_serialize_all_saved_drafts(self):
        with tempfile.TemporaryDirectory() as root:
            store = DraftStore(root)
            for peer in range(600):
                store.put('account', peer, {'text': 'saved'}, pending=False)
            store.flush()
            with patch('tg_ascii.drafts.copy_records') as copy, patch('tg_ascii.drafts.write_json') as write:
                for _ in range(50):
                    store.put('account', 1, {'text': 'saved'})
                    store.flush()
                copy.assert_not_called()
                write.assert_not_called()

    async def test_cloud_snapshot_copies_only_pending_records_and_ack_preserves_new_edits(self):
        with tempfile.TemporaryDirectory() as root:
            store = DraftStore(root)
            for peer in range(600):
                store.put('account', peer, {'text': 'saved'}, pending=False)
            store.put('account', 42, {'text': 'new', 'files': ['image.png']})
            from tg_ascii.drafts import copy_record
            with patch('tg_ascii.drafts.copy_record', wraps=copy_record) as copy:
                pending = store.pending_records()
            self.assertEqual(copy.call_count, 1)
            self.assertEqual(set(pending['account']), {'42'})
            pending['account']['42']['files'].clear()
            self.assertEqual(store.get('account', 42)['files'], ['image.png'])
            store.put('account', 42, {'text': 'newer'})
            store.mark_synced('account', 42, pending['account']['42'])
            self.assertTrue(store.get('account', 42)['pending'])
            store.mark_synced('account', 42, store.get('account', 42))
            self.assertEqual(store.pending_records(), {})
            store.flush()
            self.assertFalse(DraftStore(root).get('account', 42)['pending'])

    async def test_edit_during_atomic_write_remains_dirty_for_the_next_flush(self):
        with tempfile.TemporaryDirectory() as root:
            store = DraftStore(root)
            store.put('account', 42, {'text': 'first'})
            from tg_ascii.preferences import write_json
            def write(path, snapshot):
                store.put('account', 42, {'text': 'newer during write'})
                write_json(path, snapshot)
            with patch('tg_ascii.drafts.write_json', side_effect=write):
                store.flush()
            self.assertEqual(DraftStore(root).get('account', 42)['text'], 'first')
            store.flush()
            self.assertEqual(DraftStore(root).get('account', 42)['text'], 'newer during write')

    async def test_many_edits_while_saving_share_one_worker_job_and_keep_latest_text(self):
        with tempfile.TemporaryDirectory() as root:
            queued = []
            app = NS(demo=False, preferences=NS(path=Path(root)/'preferences.json'),
                     service=NS(entries={}, services={}), worker=NS(submit=lambda *args:queued.append(args)),
                     status=Mock(), closed=False, closing=False)
            manager = DraftManager(app)
            latest = ['first']
            manager.snapshot = lambda:manager.store.put('account', 42, {'text': latest[0]})
            manager.persist_async()
            for number in range(100):
                latest[0] = 'edit ' + str(number)
                manager.persist_async()
            self.assertEqual(len(queued), 1)
            operation, success, _ = queued.pop()
            success(await operation)
            self.assertEqual(len(queued), 1)
            operation, success, _ = queued.pop()
            success(await operation)
            self.assertFalse(queued)
            self.assertEqual(DraftStore(root).get('account', 42)['text'], 'edit 99')


class SenderBatchTests(unittest.IsolatedAsyncioTestCase):
    def backend(self):
        client = AsyncMock()
        client.add_event_handler = Mock()
        return TelegramBackend(client), client

    async def test_burst_of_distinct_senders_shares_one_network_lookup(self):
        backend, client = self.backend()
        client.get_entity.side_effect = lambda ids:[types.User(ident, first_name=str(ident)) for ident in ids]
        await asyncio.gather(*(backend.resolve_missing_senders([NS(sender_id=ident, sender=None, out=False)])
                               for ident in range(1, 51)))
        client.get_entity.assert_awaited_once()
        self.assertEqual(set(client.get_entity.call_args.args[0]), set(range(1, 51)))
        self.assertEqual(len(backend.names), 50)
        self.assertFalse(backend._sender_jobs)
        self.assertIsNone(backend._sender_collecting)

    async def test_new_and_already_running_sender_batches_keep_their_own_identity_context(self):
        backend, client = self.backend()
        started, release = asyncio.Event(), asyncio.Event()
        async def fetch(ids):
            if ids == [1]:
                started.set()
                await release.wait()
            return [types.User(ident, first_name=str(ident)) for ident in ids]
        client.get_entity.side_effect = fetch
        first = asyncio.create_task(backend.resolve_missing_senders([NS(sender_id=1, sender=None, out=False)]))
        await started.wait()
        second = asyncio.create_task(backend.resolve_missing_senders(
            [NS(sender_id=ident, sender=None, out=False) for ident in (2, 1)]))
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(first, second)
        self.assertEqual(backend.names, {1:'1', 2:'2'})
        self.assertEqual(client.get_entity.await_count, 2)
        self.assertFalse(backend._sender_jobs)

    async def test_failed_large_entity_batch_uses_four_fallback_workers_not_one_task_per_sender(self):
        backend, client = self.backend()
        started, never = asyncio.Event(), asyncio.Event()
        active = 0
        async def fetch(ids):
            nonlocal active
            if isinstance(ids, list):
                return []
            active += 1
            if active == 4:
                started.set()
            await never.wait()
        client.get_entity.side_effect = fetch
        baseline = len(asyncio.all_tasks())
        task = asyncio.create_task(backend.resolve_missing_senders(
            [NS(sender_id=ident, sender=None, out=False) for ident in range(1, 1001)]))
        async with asyncio.timeout(3):
            await started.wait()
        self.assertEqual(active, 4)
        self.assertLess(len(asyncio.all_tasks()) - baseline, 25)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(backend._sender_jobs)


class TranslationMemoryTests(unittest.TestCase):
    def test_old_attempts_are_released_and_negative_cache_stays_bounded_without_retry_loop(self):
        app = NS(ui_account='a', active=1, demo=False, chat_translations={'a:1':'es'}, preferences=NS(values={'advanced_features': {'chat_translation': True}}),
                 translated={}, translation_pending=set(), translation_failed=set(),
                 service=NS(entries={'a':{'premium':True}}, backend=Mock()), chats=[Chat(1,'Synthetic',entity=types.User(1))], worker=Mock(), root=Mock(),
                 status=Mock(), render_messages=Mock())
        with patch('tg_ascii.translation_queue.FAILURE_CACHE_LIMIT', 4):
            for page in range(20):
                app.messages = [NS(id=page*10+offset, text='Text '+str(page*10+offset), raw_text=None)
                                for offset in range(10)]
                app._translation_after = 0
                schedule(app)
                operation, done, _ = app.worker.submit.call_args.args
                operation.close()
                done({})
                self.assertLessEqual(len(app.translation_failed), 4)
                self.assertEqual(len(app._translation_attempted), 10)
                calls = app.worker.submit.call_count
                app._translation_after = 0
                schedule(app)
                self.assertEqual(app.worker.submit.call_count, calls)


class MessageAllocationTests(unittest.TestCase):
    def test_sticker_pack_title_is_normalized_once_per_multiword_search(self):
        from tg_ascii.sticker_search import matching_packs, normalized
        packs = [NS(title='Gatitos MUY simpáticos', short_name=str(i)) for i in range(100)]
        with patch('tg_ascii.sticker_search.normalized', wraps=normalized) as normalize:
            self.assertEqual(matching_packs(packs, 'gatitos muy simpaticos'), packs)
            self.assertEqual(normalize.call_count, 101)
        self.assertEqual(matching_packs(iter(packs), ''), packs)

    def test_utf16_buffer_is_only_built_when_custom_emoji_entities_need_it(self):
        calls = []
        class Text(str):
            def encode(self, *args, **kwargs):
                calls.append(args)
                return super().encode(*args, **kwargs)
        client = Mock()
        backend = TelegramBackend(client)
        ordinary = types.Message(1, peer_id=types.PeerUser(1), date=datetime.now(timezone.utc),
                                 out=True, message=Text('Hi 😀'))
        self.assertEqual(backend.message(ordinary).raw_text, ordinary.raw_text)
        self.assertEqual(calls, [])
        ordinary.entities = [types.MessageEntityCustomEmoji(3, 2, 99)]
        self.assertEqual(backend.message(ordinary).custom_emojis, ((99, '😀'),))
        self.assertEqual(calls, [('utf-16-le',)])


class FolderCompilationTests(unittest.TestCase):
    def test_compiled_filters_keep_overrides_types_and_mutable_source_changes(self):
        folder = NS(exclude_peers=[types.PeerUser(1)], include_peers=[types.PeerUser(1), types.PeerUser(2)],
                    pinned_peers=[types.PeerUser(3)], exclude_read=True, exclude_archived=True,
                    exclude_muted=True, bots=True, groups=True, broadcasts=False, contacts=True,
                    non_contacts=False)
        compiled = compile_folder(folder)
        chat = NS(id=1, kind='user', contact=True, archived=False, unread=1, unread_mark=False, muted=False)
        self.assertFalse(matches_folder(chat, folder, compiled))
        for peer in (2, 3):
            chat.id = peer
            chat.archived = chat.muted = True
            chat.unread = 0
            self.assertTrue(matches_folder(chat, folder, compiled))
        chat.id = 4
        self.assertFalse(matches_folder(chat, folder, compiled))
        chat.archived = chat.muted = False
        self.assertFalse(matches_folder(chat, folder, compiled))
        chat.unread_mark = True
        self.assertTrue(matches_folder(chat, folder, compiled))
        for kind, contact, expected in [('bot', False, True), ('group', False, True), ('channel', False, False),
                                        ('user', True, True), ('user', False, False)]:
            chat.kind, chat.contact = kind, contact
            self.assertEqual(matches_folder(chat, folder, compiled), expected)
            self.assertEqual(matches_folder(chat, folder), expected)
        folder.non_contacts = True
        self.assertTrue(matches_folder(chat, folder, compile_folder(folder)))
        self.assertFalse(matches_folder(chat, folder, compiled))
        self.assertTrue(matches_folder(chat, None, compile_folder(None)))

    def test_thousand_chats_only_convert_folder_peers_once(self):
        folder = NS(exclude_peers=[], include_peers=[types.PeerUser(i) for i in range(100)], pinned_peers=[])
        chats = [NS(id=i, kind='user', contact=False) for i in range(1000)]
        with patch('tg_ascii.telegram_features.utils.get_peer_id', wraps=utils.get_peer_id) as convert:
            compiled = compile_folder(folder)
            selected = [chat.id for chat in chats if matches_folder(chat, folder, compiled)]
        self.assertEqual(selected, list(range(100)))
        self.assertEqual(convert.call_count, 100)


class NotificationWorkTests(unittest.IsolatedAsyncioTestCase):
    def backend(self):
        client = AsyncMock()
        client.add_event_handler = Mock()
        client.get_entity.return_value = types.User(42, first_name='A')
        client.get_input_entity.return_value = types.InputPeerUser(42, 7)
        client.return_value = types.PeerNotifySettings()
        return TelegramBackend(client), client

    async def test_burst_shares_policy_reads_and_specific_defaults_run_in_parallel(self):
        backend, client = self.backend()
        both_started, release = asyncio.Event(), asyncio.Event()
        async def settings(request):
            if client.await_count == 2:
                both_started.set()
            await release.wait()
            return types.PeerNotifySettings(show_previews=True)
        client.side_effect = settings
        tasks = [asyncio.create_task(backend.notification_policy(42)) for _ in range(50)]
        async with asyncio.timeout(3):
            await both_started.wait()
        self.assertEqual(client.await_count, 2)
        release.set()
        results = await asyncio.gather(*tasks)
        self.assertTrue(all(result == {'enabled':True, 'preview':True, 'sound':True} for result in results))
        client.get_entity.assert_awaited_once()
        await backend.notification_policy(42)
        self.assertEqual(client.await_count, 2)
        self.assertFalse(backend._notification_cache._sticker_jobs)

    async def test_remote_update_during_fetch_revalidates_before_returning_policy(self):
        backend, client = self.backend()
        started, release = asyncio.Event(), asyncio.Event()
        muted = types.PeerNotifySettings(mute_until=datetime(2037, 1, 1, tzinfo=timezone.utc))
        async def settings(request):
            if client.await_count <= 2:
                started.set()
                await release.wait()
                return types.PeerNotifySettings()
            return muted
        client.side_effect = settings
        task = asyncio.create_task(backend.notification_policy(42))
        await started.wait()
        await backend.state_event(types.UpdateNotifySettings(types.NotifyPeer(types.PeerUser(42)), muted))
        release.set()
        self.assertFalse((await task)['enabled'])
        self.assertEqual(client.await_count, 4)
        self.assertEqual(client.get_entity.await_count, 2)

    async def test_mutations_invalidate_and_mute_expiration_is_not_cached(self):
        backend, client = self.backend()
        clock = Mock()
        clock.now.return_value = datetime(2036, 1, 1, tzinfo=timezone.utc)
        client.return_value = types.PeerNotifySettings(mute_until=datetime(2037, 1, 1, tzinfo=timezone.utc))
        with patch('tg_ascii.telegram_extras.datetime', clock):
            self.assertFalse((await backend.notification_policy(42))['enabled'])
            clock.now.return_value = datetime(2038, 1, 1, tzinfo=timezone.utc)
            self.assertTrue((await backend.notification_policy(42))['enabled'])
        self.assertEqual(client.await_count, 2)
        await backend.mute_chat(42, True)
        await backend.notification_policy(42)
        self.assertEqual(client.await_count, 5)
        await backend.save_notification_settings('private', {'show_previews':False})
        await backend.notification_policy(42)
        self.assertEqual(client.await_count, 8)
        await backend.profile_notify(42, {'silent':True})
        await backend.notification_policy(42)
        self.assertEqual(client.await_count, 11)

    async def test_cancelling_one_waiter_preserves_shared_read_and_close_reclaims_pending(self):
        backend, client = self.backend()
        started, never = asyncio.Event(), asyncio.Event()
        async def settings(request):
            started.set()
            await never.wait()
        client.side_effect = settings
        one = asyncio.create_task(backend.notification_policy(42))
        two = asyncio.create_task(backend.notification_policy(42))
        await started.wait()
        one.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await one
        self.assertFalse(two.done())
        backend.presence = AsyncMock()
        await backend.close()
        with self.assertRaises(asyncio.CancelledError):
            await two
        self.assertFalse(backend._notification_cache._sticker_jobs)
        client.disconnect.assert_awaited_once()

    async def test_one_failed_read_cancels_sibling_rpc(self):
        backend, client = self.backend()
        started, cancelled = asyncio.Event(), asyncio.Event()
        async def settings(request):
            if isinstance(request.peer, types.InputNotifyPeer):
                await started.wait()
                raise OSError('Disconnected')
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        client.side_effect = settings
        with self.assertRaises(OSError):
            await backend.notification_policy(42)
        self.assertTrue(cancelled.is_set())
        self.assertFalse(backend._notification_cache._sticker_jobs)


if __name__ == '__main__':
    unittest.main()
