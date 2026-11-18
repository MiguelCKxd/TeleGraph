from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from tg_ascii.drafts import DraftStore, DraftManager, valid_record


class DraftPersistenceTests(unittest.TestCase):
    def test_unicode_format_custom_emoji_reply_and_attachment_survive_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            store = DraftStore(folder)
            record = {'text': 'Hi 😀', 'custom': [(3, 4, 12345, '😀')], 'formats': [(0, 2, 'bold', '')],
                      'files': [str(Path(folder)/'photo.jpg')], 'reply': 7}
            store.put('account', -22, record)
            store.flush()
            loaded = DraftStore(folder).get('account', -22)
            self.assertEqual(loaded['text'], record['text'])
            self.assertEqual(loaded['custom'], record['custom'])
            self.assertEqual(loaded['formats'], record['formats'])
            self.assertEqual(loaded['reply'], 7)
            self.assertTrue(loaded['pending'])
            self.assertIsNone(DraftStore(folder).get('other', -22))

    def test_empty_unmodified_composer_does_not_block_remote_draft(self):
        with tempfile.TemporaryDirectory() as folder:
            store = DraftStore(folder)
            store.put('account', 1, {'text': ''})
            self.assertFalse(store.get('account', 1))

    def test_unchanged_remote_draft_does_not_need_network_write(self):
        with tempfile.TemporaryDirectory() as folder:
            store = DraftStore(folder)
            store.put('account', 1, {'text': 'From phone'}, pending=False)
            store.put('account', 1, {'text': 'From phone'})
            self.assertFalse(store.get('account', 1)['pending'])
            store.put('account', 1, {'text': ''})
            self.assertTrue(store.get('account', 1)['pending'])

    def test_corrupt_spans_are_ignored_and_accounts_are_isolated(self):
        record = valid_record({'text': 'abc', 'formats': [(0, 999, 'bold', ''), (0, 2, 'execute', 'bad')],
                               'custom': [(0, 2, 9, 'incorrect')], 'reply': -1})
        self.assertEqual(record['formats'], [])
        self.assertEqual(record['custom'], [])
        self.assertIsNone(record['reply'])
        with tempfile.TemporaryDirectory() as folder:
            store = DraftStore(folder)
            store.put('a', 1, {'text': 'one'})
            store.put('b', 1, {'text': 'two'})
            store.remove('a')
            self.assertEqual(store.get('b', 1)['text'], 'two')

    def test_demo_does_not_write_drafts(self):
        with tempfile.TemporaryDirectory() as folder:
            store = DraftStore(folder, demo=True)
            store.put('account', 1, {'text': 'test'})
            store.flush()
            self.assertFalse(store.path.exists())


class CloudDraftTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.backend = SimpleNamespace(save_draft=AsyncMock(), fetch_drafts=AsyncMock(return_value={}))
        self.app = SimpleNamespace(demo=False, preferences=SimpleNamespace(path=Path(self.temp.name)/'preferences.json'),
            service=SimpleNamespace(entries={'account': {}}, services={'account': SimpleNamespace(backend=self.backend)}),
            ui_account='account', active=None, stage='ready', drafts={}, rich_drafts={}, format_drafts={},
            render_chats=Mock(), status=Mock(), closed=False, closing=False)
        self.manager = DraftManager(self.app)

    async def test_pending_draft_saved_with_entities_and_only_once(self):
        self.manager.store.put('account', 42, {'text': 'hello', 'formats': [(0, 5, 'bold', '')], 'reply': 9})
        await self.manager.sync_pending()
        self.backend.save_draft.assert_awaited_once_with(42, 'hello', [(0, 5, 'bold', '')], [], 9)
        await self.manager.sync_pending()
        self.assertEqual(self.backend.save_draft.await_count, 1)

    async def test_offline_failure_keeps_dirty_draft_for_reconnect(self):
        self.manager.store.put('account', 42, {'text': 'never lose this'})
        self.backend.save_draft.side_effect = ConnectionError('offline')
        with self.assertRaises(ConnectionError):
            await self.manager.sync_pending()
        self.assertTrue(self.manager.store.get('account', 42)['pending'])
        self.assertTrue(DraftStore(self.temp.name).get('account', 42)['pending'])

    async def test_new_edit_during_save_is_not_marked_synchronized(self):
        self.manager.store.put('account', 42, {'text': 'first'})
        async def save(*args):
            self.manager.store.put('account', 42, {'text': 'second'})
        self.backend.save_draft.side_effect = save
        await self.manager.sync_pending()
        self.assertTrue(self.manager.store.get('account', 42)['pending'])
        self.assertEqual(self.manager.store.get('account', 42)['text'], 'second')

    async def test_remote_client_draft_populates_editor_data_and_clear_event_removes_text(self):
        self.manager.remote('account', 42, {'text': 'From mobile', 'formats': [(0, 4, 'bold', '')], 'reply': 3})
        self.assertEqual(self.app.drafts[42][0], 'From mobile')
        self.assertEqual(self.app.format_drafts[('account', 42)], [(0, 4, 'bold', '')])
        self.assertEqual(self.app.reply_drafts[('account', 42)], 3)
        await self.manager.sync_pending()
        self.backend.save_draft.assert_not_awaited()
        self.manager.remote('account', 42, {'text': ''})
        self.assertEqual(self.app.drafts[42][0], '')

    async def test_remote_update_cannot_erase_unsaved_local_edit(self):
        self.manager.store.put('account', 42, {'text': 'new local text'})
        self.manager.remote('account', 42, {'text': 'old server text'})
        self.assertEqual(self.manager.store.get('account', 42)['text'], 'new local text')

    async def test_richer_remote_draft_is_readable_and_never_overwritten(self):
        self.manager.remote('account', 42, {'text': 'quoted reply', 'unsupported': True})
        self.manager.store.put('account', 42, {'text': 'edited', 'unsupported': True})
        await self.manager.sync_pending()
        self.backend.save_draft.assert_not_awaited()

    async def prepare_pull(self, records):
        self.app.service.backend = self.backend
        self.backend.fetch_drafts.return_value = records
        self.app.worker = Mock()
        self.manager.persist_async = Mock()
        self.manager.pull(force=True)
        coroutine, loaded, failed = self.app.worker.submit.call_args.args
        return await coroutine, loaded

    async def test_complete_snapshot_clears_missing_server_draft_but_keeps_pending_local(self):
        self.manager.store.put('account', 42, {'text': 'deleted on phone'}, pending=False)
        self.manager.store.put('account', 43, {'text': 'new offline edit'}, pending=True)
        records, loaded = await self.prepare_pull({})
        loaded(records)
        self.assertIsNone(self.manager.store.get('account', 42))
        self.assertEqual(self.app.drafts[42][0], '')
        self.assertEqual(self.manager.store.get('account', 43)['text'], 'new offline edit')

    async def test_push_that_arrives_during_snapshot_wins_over_old_snapshot(self):
        records, loaded = await self.prepare_pull({42: {'text': 'older snapshot'}})
        self.manager.remote('account', 42, {'text': 'newer push'})
        loaded(records)
        self.assertEqual(self.app.drafts[42][0], 'newer push')
        self.assertEqual(self.manager.store.get('account', 42)['text'], 'newer push')

    async def test_background_account_update_replaces_stashed_state_and_preserves_formatting(self):
        self.app.service.entries['second'] = {}
        self.app.account_states = {'second': {'drafts': {42: ('outdated', None)}}}
        self.manager.remote('second', 42, {'text': 'From phone', 'formats': [(0, 4, 'bold', '')], 'reply': 8})
        self.assertEqual(self.app.account_states['second']['drafts'][42][0], 'From phone')
        self.app.ui_account = 'second'
        self.app.drafts = self.app.account_states['second']['drafts']
        self.manager.restore_account()
        self.assertEqual(self.app.drafts[42][0], 'From phone')
        self.assertEqual(self.app.format_drafts[('second', 42)], [(0, 4, 'bold', '')])
        self.assertEqual(self.app.reply_drafts[('second', 42)], 8)
        self.manager.remote('second', 42, {'text': ''})
        self.assertEqual(self.app.account_states['second']['drafts'][42][0], '')
        self.assertNotIn(('second', 42), self.app.reply_drafts)

    async def test_one_offline_account_does_not_prevent_another_saving_its_drafts(self):
        self.manager.store.put('account', 42, {'text': 'offline'})
        self.manager.store.put('second', 42, {'text': 'online'})
        second = SimpleNamespace(save_draft=AsyncMock())
        self.app.service.entries['second'] = {}
        self.app.service.services['second'] = SimpleNamespace(backend=second)
        self.backend.save_draft.side_effect = ConnectionError
        with self.assertRaises(ConnectionError):
            await self.manager.sync_pending()
        second.save_draft.assert_awaited_once()
        self.assertFalse(self.manager.store.get('second', 42)['pending'])
        self.assertTrue(self.manager.store.get('account', 42)['pending'])

    async def test_late_updates_and_snapshot_cannot_recreate_logged_out_drafts(self):
        self.app._logging_out_accounts = {'account'}
        self.app.active = 42
        self.app.editor = Mock()
        self.app.editor.get.return_value = 'old composer'
        self.manager.snapshot()
        self.manager.remote('account', 42, {'text': 'late update'})
        self.assertIsNone(self.manager.store.get('account', 42))
        self.app._logging_out_accounts.clear()
        self.app.service.entries.clear()
        self.manager.remote('account', 42, {'text': 'after logout'})
        self.assertIsNone(self.manager.store.get('account', 42))

    async def test_pending_drafts_are_not_sent_during_logout(self):
        self.manager.store.put('account', 42, {'text': 'keep local until logout confirmed'})
        self.app._logging_out_accounts = {'account'}
        await self.manager.sync_pending()
        self.backend.save_draft.assert_not_awaited()
        self.assertTrue(self.manager.store.get('account', 42)['pending'])

    async def test_explicit_final_sync_during_logout_is_limited_to_the_selected_account(self):
        self.manager.store.put('account', 42, {'text': 'save before logout'})
        self.manager.store.put('second', 42, {'text': 'other account'})
        second = SimpleNamespace(save_draft=AsyncMock())
        self.app.service.entries['second'] = {}
        self.app.service.services['second'] = SimpleNamespace(backend=second)
        self.app._logging_out_accounts = {'account'}
        await self.manager.sync_pending(account='account', allow_logout=True)
        self.backend.save_draft.assert_awaited_once()
        second.save_draft.assert_not_awaited()
        self.assertFalse(self.manager.store.get('account', 42)['pending'])
        self.assertTrue(self.manager.store.get('second', 42)['pending'])

    async def test_final_logout_sync_refuses_to_discard_pending_draft_without_backend(self):
        self.manager.store.put('account', 42, {'text': 'not synchronized'})
        self.app.service.services['account'].backend = None
        with self.assertRaises(ValueError):
            await self.manager.sync_pending(account='account', allow_logout=True)
        self.assertTrue(self.manager.store.get('account', 42)['pending'])
        self.assertEqual(DraftStore(self.temp.name).get('account', 42)['text'], 'not synchronized')

    async def test_final_logout_sync_refuses_to_discard_edited_richer_draft(self):
        self.manager.store.put('account', 42, {'text': 'local edit of rich draft', 'unsupported': True})
        with self.assertRaises(ValueError):
            await self.manager.sync_pending(account='account', allow_logout=True)
        self.backend.save_draft.assert_not_awaited()
        self.assertTrue(self.manager.store.get('account', 42)['pending'])

    async def test_remote_draft_with_clean_visible_editor_updates_cleanly(self):
        self.app.active = 42
        self.app.restore_draft = Mock()
        editor = Mock()
        editor.winfo_exists.return_value = True
        editor.edit_modified.return_value = False
        editor.get.return_value = ''
        self.app.editor = editor
        self.manager.remote('account', 42, {'text': 'Typing on phone'})
        self.assertEqual(self.app.drafts[42][0], 'Typing on phone')
        self.assertFalse(self.manager.store.get('account', 42)['pending'])
        self.app.restore_draft.assert_called_once()

    async def test_pull_preserves_local_draft_with_attachments(self):
        self.manager.store.put('account', 42, {'text': 'attachment draft', 'files': ['photo.png']}, pending=False)
        records, loaded = await self.prepare_pull({})
        loaded(records)
        record = self.manager.store.get('account', 42)
        self.assertIsNotNone(record)
        self.assertEqual(record['files'], ['photo.png'])


if __name__ == '__main__':
    unittest.main()
