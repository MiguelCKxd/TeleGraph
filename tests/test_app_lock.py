import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock,patch

from tg_ascii import app_lock as lock


class LockStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record=lock.make_record('example password')
        cls.next_record=lock.make_record('replacement password',True,False)

    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.store=lock.LockStore(directory.name)

    def test_password_verification_and_random_salts(self):
        self.assertTrue(lock.verify_password(self.record,'example password'))
        self.assertFalse(lock.verify_password(self.record,'wrong password'))
        self.assertFalse(lock.verify_password(self.record,None))
        self.assertNotEqual(lock.make_record('example password')['salt'],self.record['salt'])
        self.assertEqual(self.record['iterations'],600_000)
        self.assertNotIn('example password',json.dumps(self.record))

    def test_non_text_password_and_untrusted_kdf_cost(self):
        for password in (None,7,b'password'):
            with self.assertRaises(ValueError):lock.make_record(password)
        for field,value in (('iterations',600_000_000),('schema',True),('biometric',1),('digest','00'),('salt',None)):
            with self.subTest(field=field),self.assertRaises(lock.InvalidLock):
                lock.checked_record({**self.record,field:value})

    def test_exact_passwords_have_no_length_or_character_requirements(self):
        for password in ('','7','a','  ',' !🙂漢字\t ','é','e\u0301','x'*4097):
            with self.subTest(password_length=len(password)):
                record=lock.make_record(password)
                self.assertTrue(lock.verify_password(record,password))
                self.assertFalse(lock.verify_password(record,password+'!'))
                self.assertEqual(lock.password_bytes(password),password.encode('utf-8'))
                self.assertLess(len(json.dumps(record)),lock.MAX_RECORD_BYTES)

    def test_passwords_are_not_trimmed_or_unicode_normalized(self):
        record=lock.make_record(' é ')
        for other in ('é',' é','é ',' e\u0301 '):
            self.assertFalse(lock.verify_password(record,other))

    def test_empty_password_can_be_saved_changed_and_disabled(self):
        empty=lock.make_record('')
        self.store.save(empty,expected=None)
        self.assertTrue(lock.verify_password(self.store.load(),''))
        with self.assertRaises(ValueError):self.store.disable('not empty',expected=empty)
        self.store.save(self.next_record,expected=empty)
        self.assertTrue(lock.verify_password(self.store.load(),'replacement password'))
        self.store.save(empty,expected=self.next_record)
        self.store.disable('',expected=empty)
        self.assertIsNone(self.store.load())

    def test_roundtrip_is_private_and_separate_from_settings(self):
        self.assertIsNone(self.store.load())
        self.store.save(self.record,expected=None)
        self.assertEqual(self.store.load(),self.record)
        self.assertEqual(json.loads(self.store.path.with_suffix('.json.backup').read_text(encoding='utf-8')),self.record)
        if os.name!='nt':self.assertEqual(self.store.path.stat().st_mode&0o777,0o600)
        from tg_ascii.preferences import Preferences
        prefs=Preferences(self.store.path.parent)
        prefs.save({'theme':'light'})
        from tg_ascii.preferences import DEFAULTS
        prefs.save(DEFAULTS)
        self.assertEqual(self.store.load(),self.record)

    def test_corrupt_missing_backup_not_used_to_silently_unlock(self):
        for raw in ('[]','{}','[ '*1100+'] '*1100,'x'*5000,'{"schema":1}'):
            self.store.path.write_text(raw,encoding='utf-8')
            with self.subTest(raw=raw[:10]),self.assertRaises(lock.InvalidLock):self.store.load()

    @unittest.skipIf(os.name=='nt','Symlinks may require additional privilege on Windows')
    def test_symlink_is_rejected_even_when_target_missing(self):
        self.store.path.symlink_to(self.store.path.parent/'missing')
        with self.assertRaises(lock.InvalidLock):self.store.load()

    def test_stale_settings_cannot_overwrite_new_password(self):
        self.store.save(self.record)
        self.store.save(self.next_record,expected=self.record)
        with self.assertRaises(ValueError):self.store.save(self.record,expected=self.record)
        self.assertEqual(self.store.load(),self.next_record)

    def test_simultaneous_compare_and_swap_has_one_winner(self):
        self.store.save(self.record);ready=threading.Barrier(3);results=[]
        def save(value):
            ready.wait()
            try:self.store.save(value,expected=self.record);results.append(True)
            except ValueError:results.append(False)
        values=[{**self.next_record,'lock_on_hide':flag} for flag in (True,False)]
        threads=[threading.Thread(target=save,args=(value,)) for value in values]
        for thread in threads:thread.start()
        ready.wait()
        for thread in threads:thread.join(3)
        self.assertEqual(sorted(results),[False,True])
        self.assertIn(self.store.load(),values)

    def test_disable_requires_current_password_and_expected_record(self):
        self.store.save(self.record)
        with self.assertRaises(ValueError):self.store.disable('wrong password')
        self.assertEqual(self.store.load(),self.record)
        with self.assertRaises(ValueError):self.store.disable('example password',expected=self.next_record)
        self.store.disable('example password',expected=self.record)
        self.assertIsNone(self.store.load())
        self.assertFalse(self.store.path.with_suffix('.json.backup').exists())

    def test_failed_backup_removal_keeps_protection(self):
        self.store.save(self.record)
        original=Path.unlink
        def unlink(path,*args,**kwargs):
            if str(path).endswith('.backup'):raise PermissionError('no')
            return original(path,*args,**kwargs)
        with patch.object(Path,'unlink',unlink),self.assertRaises(PermissionError):self.store.disable('example password')
        self.assertEqual(self.store.load(),self.record)


class LockStartupTests(unittest.TestCase):
    def setUp(self):
        mocked=patch('tg_ascii.notifications.clear_locked_notification_history')
        mocked.start();self.addCleanup(mocked.stop)

    def test_accounts_start_only_after_successful_gate(self):
        store=Mock();store.load.return_value={'enabled':True}
        start=Mock();root=Mock()
        with patch.object(lock,'UnlockPanel') as panel:
            lock.startup_gate(root,store,start)
            start.assert_not_called()
            panel.call_args.args[2]();start.assert_called_once()

    def test_corruption_also_enters_gate_and_disabled_starts_directly(self):
        start=Mock();root=Mock();store=Mock()
        store.load.side_effect=lock.InvalidLock('damaged')
        with patch.object(lock,'UnlockPanel') as panel:
            lock.startup_gate(root,store,start);panel.assert_called_once();start.assert_not_called()
        store.load.side_effect=None;store.load.return_value=None
        lock.startup_gate(root,store,start);start.assert_called_once()

    def test_linked_window_uses_owner_lock_and_defers_latest_action(self):
        owner=NS(_app_locked=True,_app_lock_panel=Mock())
        view=NS(_linked_owner=owner);action=Mock()
        self.assertTrue(lock.show_locked(view,action))
        self.assertIs(owner._after_unlock,action);action.assert_not_called()
        owner._app_locked=False
        self.assertFalse(lock.show_locked(view))


if __name__=='__main__':unittest.main()
