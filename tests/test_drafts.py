import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from tg_ascii.drafts import DraftStore
from tg_ascii_mobile.core import Core


class DraftBackend:
    def __init__(self):
        self.records = {}
        self._protected_drafts = set()
        self.offline = False

    async def fetch_drafts(self):
        if self.offline:
            raise OSError('offline')
        return self.records.copy()

    async def save_draft(self, peer, text, formats, custom, reply):
        if self.offline:
            raise OSError('offline')
        if text or reply:
            self.records[peer] = {'text': text, 'formats': formats, 'custom': custom, 'reply': reply}
        else:
            self.records.pop(peer, None)


class MobileDraftTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.core = Core(self.root, 'test')
        self.core.loop.close()
        self.core.loop = asyncio.get_running_loop()
        self.backend = DraftBackend()
        self.core.accounts = SimpleNamespace(current='account', services={
            'account': SimpleNamespace(backend=self.backend),
        })
        self.core.stage = 'ready'

    async def asyncTearDown(self):
        for task in list(self.core.draft_jobs.values()):
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def sync(self):
        await self.core.sync_drafts('account', self.backend, pull=True)

    async def test_window_layout_and_open_requests_are_scoped_to_the_account(self):
        import json

        path = self.core.appearance_path()
        path.parent.mkdir()
        path.write_text(json.dumps({'windows': [{'peer': 10, 'name': 'Legacy'}]}))
        self.assertEqual(self.core.appearance()['windows'], [])
        first = await self.core.api_appearance({'windows': [{'peer': 20, 'name': 'First'}]}, account='account')
        self.assertEqual(first['windows'][0]['name'], 'First')

        self.core.accounts.current = 'other'
        self.assertEqual(self.core.appearance()['windows'], [])
        with self.assertRaisesRegex(ValueError, 'account changed'):
            await self.core.api_window_open(20, account='account')
        with self.assertRaisesRegex(ValueError, 'account changed'):
            await self.core.api_system_window(20, account='account')
        with self.assertRaisesRegex(ValueError, 'account changed'):
            await self.core.api_appearance({'windows': []}, account='account')
        second = await self.core.api_appearance({'windows': [{'peer': 20, 'name': 'Second'}]}, account='other')
        self.assertEqual(second['windows'][0]['name'], 'Second')

        self.core.accounts.current = 'account'
        self.assertEqual(self.core.appearance()['windows'], first['windows'])

    async def test_floating_window_loads_the_same_draft_as_the_main_chat(self):
        await self.core.api_draft(10, 'account', 'Text', formats=[[0, 4, 'bold', '']], reply=42)
        self.core.reload_history = AsyncMock()
        result = await self.core.api_window_open(10, 'account', read=False)
        self.assertEqual(result['draft'], self.core.draft_record(10))
        self.assertEqual(result['draft']['reply'], 42)
        self.assertEqual(result['draft']['formats'], [(0, 4, 'bold', '')])
        self.core.locked = True
        await self.core.api_draft(10, 'account', 'Last text')
        self.core.locked = False
        await self.core.api_window_close(10, 'account')
        self.core.locked = True
        with self.assertRaises(PermissionError):
            await self.core.api_draft(10, 'account', 'Rejected')
        self.assertEqual(self.core.draft_record(10)['text'], 'Last text')

    async def test_secret_text_draft_reopens_from_encrypted_local_store(self):
        from tg_ascii.secret_chats import SecretChatManager, SecretChatSession

        self.backend.client = SimpleNamespace(session=SimpleNamespace(auth_key=SimpleNamespace(key=b'qa-key')))
        manager = SecretChatManager(self.backend, self.root)
        session = SecretChatSession(12, state='active')
        manager.sessions[12] = session
        self.backend.secret_chats = manager
        manager._save()
        text = 'borrador secreto de prueba'
        self.core.set_draft(session.peer_id, {'text': text, 'reply': 8})
        encrypted = manager.store.files_dir / 'draft-12.bin'
        self.assertNotIn(text.encode(), encrypted.read_bytes())
        self.assertFalse(self.core.draft_store.pending_records())

        self.core._secret_drafts.clear()
        self.backend.secret_chats = SecretChatManager(self.backend, self.root)
        record = self.core.draft_record(session.peer_id)
        self.assertEqual((record['text'], record['reply']), (text, 8))
        self.core.set_draft(session.peer_id, '')
        self.assertFalse(encrypted.exists())

    async def test_retry_identical_draft_after_disk_error_survives_restart(self):
        for root in (None, 35):
            for text in ('keep this', ''):
                with self.subTest(root=root, text=text):
                    with patch('tg_ascii.drafts.write_json', side_effect=OSError('disk full')):
                        with self.assertRaises(OSError):
                            await self.core.api_draft(10, 'account', text, thread_root=root)
                    await self.core.api_draft(10, 'account', text, thread_root=root)
                    reopened = DraftStore(self.root / 'mobile')
                    owner, key = self.core.draft_location(10, root)
                    self.assertEqual((reopened.get(owner, key) or {}).get('text', ''), text)
                    if root is None:
                        self.assertIn('account', self.core.draft_jobs)
                        await self.core.sync_drafts('account', self.backend)
                        self.assertEqual(self.backend.records.get(10, {}).get('text', ''), text)

    async def test_sync_reads_latest_pending_draft_before_uploading_each_chat(self):
        self.core.set_draft(10, 'old first')
        self.core.set_draft(20, 'old second')
        sent = []
        save = self.backend.save_draft

        async def save_and_edit_other(peer, text, formats, custom, reply):
            sent.append((peer, text))
            if len(sent) == 1:
                self.core.set_draft(20 if peer == 10 else 10, 'latest edit')
            await save(peer, text, formats, custom, reply)

        self.backend.save_draft = save_and_edit_other
        await self.core.sync_drafts('account', self.backend)
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[1][1], 'latest edit')
        self.assertFalse(self.core.draft_store.pending_records('account'))

    async def test_logout_purges_only_that_accounts_drafts_after_success(self):
        self.core.accounts.entries = {'account': {}, 'other': {}}
        self.core.close_call_manager = AsyncMock()
        self.core.switch_finished = AsyncMock()
        from tg_ascii_mobile.chat_translations import ChatTranslations
        translations = self.core.translations()
        translations.set_language(10, 'es')
        other = ChatTranslations(self.root / 'mobile', 'other')
        other.set_language(10, 'fr')
        self.core.set_draft(10, 'cloud draft')
        self.core.set_draft(20, 'discussion draft', thread_root=3)
        self.core.draft_store.put('discussion:other:20', 3, {'text': 'other discussion'}, pending=False)
        self.core._secret_drafts = {('account', 9): {'text': 'secret'}, ('other', 9): {'text': 'other'}}
        legacy = self.root / 'mobile' / 'drafts-account.migrated.json'
        legacy.write_text('{}')
        self.core.accounts.logout = AsyncMock(side_effect=OSError)
        with self.assertRaises(OSError):
            await self.core.api_logout('account')
        self.assertIsNotNone(self.core.draft_store.get('account', 10))
        self.assertTrue(legacy.exists())
        self.assertEqual(translations.language(10), 'es')

        async def logout(key):
            del self.core.accounts.entries[key]
            return 'ready'

        self.core.accounts.logout = logout
        await self.core.api_logout('account')
        restored = DraftStore(self.root / 'mobile')
        self.assertIsNone(restored.get('account', 10))
        self.assertIsNone(restored.get('discussion:account:20', 3))
        self.assertEqual(restored.get('discussion:other:20', 3)['text'], 'other discussion')
        self.assertNotIn(('account', 9), self.core._secret_drafts)
        self.assertIn(('other', 9), self.core._secret_drafts)
        self.assertFalse(legacy.exists())
        self.assertFalse(translations.path.exists())
        self.assertEqual(other.language(10), 'fr')

    async def test_restart_recovers_attachment_reply_and_unicode_format(self):
        path = self.core.staging_path('example.txt')
        path.write_text('fixture', encoding='utf-8')
        await self.core.api_draft(101, 'account', '🐱 hola',
                                  formats=[[2, 6, 'bold', '']], custom=[[0, 1, '123', '🐱']],
                                  reply=7, files=[path.name])
        self.core.draft_store = DraftStore(self.root / 'mobile')
        self.core.prune_staging(age=0)
        record = self.core.draft_record(101)
        self.assertEqual(record['text'], '🐱 hola')
        self.assertEqual(record['formats'], [(2, 6, 'bold', '')])
        self.assertEqual(record['custom'], [[0, 1, '123', '🐱']])
        self.assertEqual(record['reply'], 7)
        self.assertEqual(record['files'][0]['key'], path.name)
        self.assertEqual(self.core.draft_record(102)['text'], '')
        self.core.accounts.current = 'another'
        self.assertEqual(self.core.draft_record(101)['text'], '')
        with self.assertRaises(ValueError):
            await self.core.api_draft(101, 'account', 'old account')

    async def test_thread_edit_and_clear_notify_other_composers(self):
        import json

        events = asyncio.Queue()
        self.core.subscribers.add(events)
        for text in ('comment', ''):
            await self.core.api_draft(101, 'account', text, thread_root=15)
            event = json.loads(events.get_nowait())
            self.assertEqual(event['type'], 'draft')
            self.assertEqual(event['data'], {
                'account': 'account', 'peer': 101, 'thread_root': 15,
                'record': self.core.draft_record(101, 15)})
            self.assertEqual(event['data']['record']['text'], text)
            self.assertTrue(events.empty())
        self.assertFalse(self.core.draft_jobs)

    async def test_discussion_drafts_survive_restart_and_send_only_clears_that_thread(self):
        peer = -1000000000101
        await self.core.api_draft(peer, 'account', 'group draft')
        await self.core.api_draft(peer, 'account', 'thread one', thread_root=10)
        await self.core.api_draft(peer, 'account', 'thread two', thread_root=20)
        self.core.draft_store = DraftStore(self.root / 'mobile')
        await self.sync()
        self.assertEqual(self.backend.records[peer]['text'], 'group draft')
        queued = []
        self.core.outbox = SimpleNamespace(add=lambda item, require_persistence: queued.append(item))
        await self.core.api_send(peer, 'thread one', thread_root=10, account='account')
        self.assertEqual((queued[0].peer, queued[0].reply_to, queued[0].thread_root), (peer, 10, 10))
        self.assertEqual(self.core.draft_record(peer, 10)['text'], '')
        self.assertEqual(self.core.draft_record(peer, 20)['text'], 'thread two')
        self.assertEqual(self.core.draft_record(peer)['text'], 'group draft')

    async def test_locked_background_can_finish_only_the_open_composer_write(self):
        peer = -1000000000101
        self.core.open_discussion = ('account', peer, 10)
        self.core.locked = True
        payload = {'peer': peer, 'account': 'account', 'text': 'last line', 'thread_root': 10}
        self.assertTrue(await self.core.call('draft', payload))
        with self.assertRaises(PermissionError):
            await self.core.call('draft', {**payload, 'thread_root': 20})
        with self.assertRaises(PermissionError):
            await self.core.call('open', {'peer': peer})
        with self.assertRaises(ValueError):
            await self.core.call('draft', {**payload, 'account': 'wrong'})
        self.core.draft_store = DraftStore(self.root / 'mobile')
        self.assertEqual(self.core.draft_record(peer, 10)['text'], 'last line')
        self.assertEqual(self.core.draft_record(peer, 20)['text'], '')

    async def test_discussion_upload_preserves_caption_and_reply_in_outbox(self):
        from tg_ascii.outbox import build_operation

        peer = -1000000000101
        path = self.core.staging_path('picture.png')
        path.write_bytes(b'attachment')
        await self.core.api_draft(peer, 'account', 'Another thread', thread_root=20)
        queued = []
        self.core.outbox = SimpleNamespace(add=lambda item, require_persistence: queued.append((item, require_persistence)))
        await self.core.api_send_files(peer, [path.name], caption='🐱 hola', reply_to=12,
                                       spans=[[2, 6, 'bold', '']], custom=[[0, 1, '123', '🐱']],
                                       thread_root=10, account='account')
        item, persisted = queued[0]
        self.assertTrue(persisted)
        self.assertEqual((item.peer, item.thread_root), (peer, 10))
        sender = SimpleNamespace(send_formatted=AsyncMock())
        await build_operation(sender, item)
        sender.send_formatted.assert_awaited_once_with(
            peer, '🐱 hola', [(2, 6, 'bold', '')], [(0, 1, 123, '🐱')], path.resolve(), None,
            reply_to=12, as_photo=True, silent=False, schedule=None)
        self.assertEqual(self.core.draft_record(peer, 20)['text'], 'Another thread')
        with self.assertRaisesRegex(ValueError, 'active account'):
            await self.core.api_send_voice(peer, path.name, duration=4, thread_root=10, account='other')
        self.assertEqual(len(queued), 1)

    async def test_offline_clear_retries_without_resurrecting_cloud_draft(self):
        await self.core.api_draft(101, 'account', 'unread draft')
        await self.sync()
        self.backend.offline = True
        await self.core.api_draft(101, 'account', '')
        await self.sync()
        self.core.draft_store = DraftStore(self.root / 'mobile')
        self.assertEqual(self.backend.records[101]['text'], 'unread draft')
        self.assertEqual(self.core.draft_record(101)['text'], '')
        self.backend.offline = False
        await self.sync()
        self.assertNotIn(101, self.backend.records)
        self.assertFalse(self.core.draft_store.pending_records('account'))

    async def test_remote_clear_removes_clean_copy_and_preserves_local_attachment(self):
        path = self.core.staging_path('example.txt')
        path.touch()
        await self.core.api_draft(101, 'account', 'draft', files=[path.name])
        await self.sync()
        self.backend.records.clear()
        await self.sync()
        record = self.core.draft_record(101)
        self.assertEqual(record['text'], '')
        self.assertEqual(record['files'][0]['key'], path.name)

    async def test_richer_remote_draft_is_not_overwritten(self):
        self.backend._protected_drafts.add(101)
        self.backend.records[101] = {'text': 'from Telegram', 'unsupported': True}
        await self.core.api_draft(101, 'account', 'local draft')
        await self.sync()
        self.assertEqual(self.backend.records[101]['text'], 'from Telegram')
        self.assertEqual(self.core.draft_record(101)['text'], 'local draft')

    async def test_failed_enqueue_keeps_draft(self):
        await self.core.api_draft(101, 'account', 'keep if queue fails')

        def reject(item, *, require_persistence):
            self.assertTrue(require_persistence)
            raise OSError('disk unavailable')

        self.core.outbox = SimpleNamespace(add=reject)
        with self.assertRaises(OSError):
            await self.core.api_send(101, 'keep if queue fails', account='account')
        self.assertEqual(self.core.draft_record(101)['text'], 'keep if queue fails')

    async def test_old_mobile_draft_imports_once(self):
        source = self.root / 'mobile' / 'drafts-account.json'
        source.parent.mkdir(parents=True)
        source.write_text('{"101":{"text":"old mobile draft","date":1}}', encoding='utf-8')
        self.core.load_drafts()
        self.assertEqual(self.core.draft_record(101)['text'], 'old mobile draft')
        self.assertTrue(source.with_suffix('.migrated.json').is_file())
        await self.core.api_draft(101, 'account', '')
        await self.sync()
        self.core.draft_store = DraftStore(self.root / 'mobile')
        self.core.loaded_draft_accounts.clear()
        self.core.load_drafts()
        self.assertEqual(self.core.draft_record(101)['text'], '')
