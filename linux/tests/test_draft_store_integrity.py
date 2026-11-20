import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from tg_ascii.drafts import DraftStore


class DraftStoreIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def asset(self, store, account='account', peer=1):
        source = self.root/'recording.ogg'
        source.write_bytes(b'private audio draft')
        store.put(account, peer, {'text': 'caption', 'files': [store.register_asset(source)]})
        store.flush()
        return Path(store.get(account, peer)['files'][0])

    def test_more_than_two_megabytes_of_valid_drafts_survive_restart_without_loss(self):
        store = DraftStore(self.root)
        text = 'á😀' * 2000
        for peer in range(600):
            store.put('account', peer, {'text': text, 'reply': peer + 1})
        store.flush()
        self.assertGreater(store.path.stat().st_size, 2 * 1024 * 1024)
        restored = DraftStore(self.root)
        self.assertIsNone(restored.load_error)
        self.assertEqual(len(restored.records['account']), 600)
        for peer in range(600):
            self.assertEqual(restored.get('account', peer)['text'], text)
            self.assertEqual(restored.get('account', peer)['reply'], peer + 1)

    def test_corrupt_json_is_reported_and_preserved_byte_for_byte_before_replacement(self):
        original = b'{"account": {"1": {"text": "unfinished'
        (self.root/'drafts.json').write_bytes(original)
        store = DraftStore(self.root)
        self.assertIsNotNone(store.load_error)
        self.assertEqual(store.path.read_bytes(), original)
        store.put('account', 2, {'text': 'new safe draft'})
        store.flush()
        self.assertEqual(store.recovery_path.read_bytes(), original)
        self.assertEqual(DraftStore(self.root).get('account', 2)['text'], 'new safe draft')

    def test_invalid_document_shape_keeps_original_and_salvages_valid_drafts(self):
        original = {'account': {'1': {'text': 'recoverable'}, '2': {'text': 123}}, 'bad': []}
        path = self.root/'drafts.json'
        path.write_text(json.dumps(original), encoding='utf-8')
        before = path.read_bytes()
        store = DraftStore(self.root)
        self.assertIsNotNone(store.load_error)
        self.assertEqual(store.get('account', 1)['text'], 'recoverable')
        store.flush()
        self.assertEqual(store.recovery_path.read_bytes(), before)
        self.assertEqual(DraftStore(self.root).get('account', 1)['text'], 'recoverable')

    def test_failed_recovery_backup_never_overwrites_original(self):
        original = b'invalid original must remain'
        (self.root/'drafts.json').write_bytes(original)
        store = DraftStore(self.root)
        store.put('account', 1, {'text': 'new draft'})
        with patch.object(store, '_copy_asset', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                store.flush()
        self.assertEqual(store.path.read_bytes(), original)
        store.flush()
        self.assertEqual(store.recovery_path.read_bytes(), original)

    def test_corrupt_formatting_is_salvaged_without_discarding_the_original(self):
        original = {'account': {'1': {'text': 'safe text', 'formats': [[0, 999, 'bold', '']]}}}
        path = self.root/'drafts.json'
        path.write_text(json.dumps(original), encoding='utf-8')
        before = path.read_bytes()
        store = DraftStore(self.root)
        self.assertIsNotNone(store.load_error)
        self.assertEqual(store.get('account', 1)['text'], 'safe text')
        self.assertEqual(store.get('account', 1)['formats'], [])
        store.flush()
        self.assertEqual(store.recovery_path.read_bytes(), before)

    def test_assets_remain_until_all_accounts_and_duplicate_windows_release_them(self):
        store = DraftStore(self.root)
        target = self.asset(store)
        for owner in ('second', 'linked:account', 'linked:account:1'):
            store.put(owner, 1, {'text': 'shared', 'files': [str(target)]})
        store.flush()
        store.remove_account('account')
        store.flush()
        self.assertTrue(target.exists())
        self.assertEqual(set(store.records), {'second'})
        store.remove('second')
        store.flush()
        self.assertFalse(target.exists())
        self.assertFalse(store._assets)
        self.assertFalse(store._ready_assets)

    def test_logout_namespace_cannot_remove_a_different_account_with_common_prefix(self):
        store = DraftStore(self.root)
        owners = ('a', 'linked:a', 'linked:a:1', 'ab', 'linked:ab', 'linked:a:other')
        for owner in owners:
            store.put(owner, 1, {'text': owner})
        store.remove_account('a')
        self.assertEqual(set(store.records), {'ab', 'linked:ab', 'linked:a:other'})

    def test_visible_composer_holds_asset_even_when_its_old_store_record_is_removed(self):
        store = DraftStore(self.root)
        target = self.asset(store)
        store.set_active_assets([target])
        store.remove('account')
        store.flush()
        self.assertTrue(target.exists())
        store.set_active_assets([])
        store.flush()
        self.assertFalse(target.exists())

    def test_cleanup_never_deletes_external_files_or_files_mentioned_by_recovery_copy(self):
        store = DraftStore(self.root)
        external = self.root/'external.txt'
        external.write_bytes(b'user attachment')
        target = self.asset(store)
        store.put('account', 2, {'text': 'external', 'files': [str(external)]})
        store.flush()
        (self.root/'drafts-recovery-example.json').write_bytes(b'corrupted references')
        restored = DraftStore(self.root)
        restored.remove('account')
        restored.flush()
        self.assertTrue(target.exists())
        self.assertTrue(external.exists())

    def test_failed_atomic_draft_write_does_not_delete_previous_attachments(self):
        store = DraftStore(self.root)
        target = self.asset(store)
        store.remove('account')
        with patch('tg_ascii.drafts.write_json', side_effect=OSError('write failed')):
            with self.assertRaises(OSError):
                store.flush()
        self.assertTrue(target.exists())
        self.assertEqual(DraftStore(self.root).get('account', 1)['files'], [str(target)])
        store.flush()
        self.assertFalse(target.exists())

    def test_new_reference_during_atomic_write_prevents_asset_cleanup(self):
        store = DraftStore(self.root)
        target = self.asset(store)
        store.remove('account')
        from tg_ascii.preferences import write_json
        def write(path, snapshot):
            store.put('linked:account', 1, {'text': 'still open', 'files': [str(target)]})
            write_json(path, snapshot)
        with patch('tg_ascii.drafts.write_json', side_effect=write):
            store.flush()
        self.assertTrue(target.exists())
        store.flush()
        self.assertEqual(DraftStore(self.root).get('linked:account', 1)['files'], [str(target)])

    def test_asset_removed_during_copy_is_collected_only_after_copy_finishes(self):
        store = DraftStore(self.root)
        source = self.root/'recording.ogg'
        source.write_bytes(b'audio')
        store.put('account', 1, {'text': 'copy', 'files': [store.register_asset(source)]})
        target = store._assets[str(source)]
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        original = store._copy_asset
        errors = []
        def copy(source, destination):
            started.set()
            if not release.wait(3):
                raise TimeoutError('test copy not released')
            original(source, destination)
            self.assertTrue(target.exists())
        def flush():
            try:
                store.flush()
            except Exception as error:
                errors.append(error)
        with patch.object(store, '_copy_asset', side_effect=copy):
            worker = threading.Thread(target=flush)
            worker.start()
            self.assertTrue(started.wait(3))
            store.remove('account')
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertFalse(target.exists())
        self.assertTrue(source.exists())


if __name__ == '__main__':
    unittest.main()
