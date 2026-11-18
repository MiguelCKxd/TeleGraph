"""Logout preserves server drafts and never reuses another identity's locals."""
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

from tg_ascii.accounts import Accounts
from tg_ascii.desktop_plus import DesktopPlus
from tg_ascii.desktop_tools import DesktopTools
from tg_ascii.drafts import DraftManager, DraftStore
from tg_ascii.preferences import read_json, write_json
from tg_ascii.profile_customization import purge_account_customization


class LogoutFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.events = []
        self.first = NS(save_draft=AsyncMock(side_effect=lambda *args: self.events.append('save')))
        self.second = NS(save_draft=AsyncMock())
        self.linked = NS(account='a', closed=False, attachment=None,
                         persist_draft=Mock(), close=Mock())
        self.other_window = NS(account='b', closed=False, attachment=None,
                               persist_draft=Mock(), close=Mock())
        self.app = NS(busy=False, demo=False, root=Mock(), ui_account='a', active=None, stage='ready',
            preferences=NS(path=self.root/'preferences.json'),
            service=NS(current='a', entries={'a': {}, 'b': {}}, labels={'a': 'A', 'b': 'B'},
                       services={'a': NS(backend=self.first), 'b': NS(backend=self.second)}, backend=self.first),
            drafts={}, rich_drafts={('a', 1): [], ('b', 2): []}, format_drafts={},
            popups=[], account_states={'a': {'drafts': {}}, 'b': {'active': 2, 'drafts': {2: ('stale', None)}}},
            account_unread={'a': 1, 'b': 2}, _chat_windows=[self.linked, self.other_window],
            show_error=Mock(), login_stage=Mock(), call=Mock(), closed=False, closing=False,
            status=Mock(), local_pins=NS(values={'a': [1], 'b': [2]}),
            wallpapers={'a:1': 'shared', 'b:2': 'shared'}, chat_translations={'a:1': 'es', 'b:2': 'en'})
        self.manager = self.app.draft_manager = DraftManager(self.app)
        self.manager.store.put('a', 1, {'text': 'save before revocation'})
        self.manager.store.put('b', 2, {'text': 'restore before showing B', 'reply': 7})
        self.manager.store.put('linked:a', 1, {'text': 'private window'})
        self.manager.store.put('linked:a:1', 1, {'text': 'second private window'})
        self.manager.store.put('linked:b', 2, {'text': 'keep other window'})
        write_json(self.root/'profile-designs.json', {'a': {'first_name': 'Local A'}, 'b': {'first_name': 'Local B'}})

        async def logout(key):
            self.events.append('logout')
            self.app.service.entries.pop(key)
            self.app.service.services.pop(key)
            self.app.service.current = 'b'
            self.app.service.backend = self.second
            return 'ready'
        self.app.service.logout = AsyncMock(side_effect=logout)

    def begin(self):
        with patch('tg_ascii.desktop_tools.messagebox.askyesno', return_value=True):
            DesktopTools.logout_account(self.app)
        return self.app.call.call_args.args

    async def test_saves_only_selected_account_before_logout_and_restores_next_account_before_ui(self):
        def show(stage):
            self.assertEqual(stage, 'ready')
            self.assertEqual(self.app.ui_account, 'b')
            self.assertEqual(self.app.drafts[2][0], 'restore before showing B')
            self.assertEqual(self.app.reply_drafts[('b', 2)], 7)
        self.app.login_stage.side_effect = show
        operation, done, _, _ = self.begin()
        self.assertIn('a', self.app._logging_out_accounts)
        done(await operation)
        self.assertEqual(self.events, ['save', 'logout'])
        self.second.save_draft.assert_not_awaited()
        self.assertEqual(set(self.manager.store.records), {'b', 'linked:b'})
        self.assertIsNone(DraftStore(self.root).get('a', 1))
        self.assertEqual(read_json(self.root/'profile-designs.json', {}), {'b': {'first_name': 'Local B'}})
        self.linked.persist_draft.assert_called_once_with(capture_only=True)
        self.linked.close.assert_called_once_with(discard_draft=True)
        self.other_window.close.assert_not_called()
        self.assertNotIn('a', self.app._logging_out_accounts)
        self.assertNotIn('a', self.app.account_states)
        self.assertNotIn(('a', 1), self.app.rich_drafts)
        self.assertEqual(self.app.local_pins.values, {'b': [2]})
        self.assertEqual(self.app.wallpapers, {'b:2': 'shared'})

    async def test_failed_draft_sync_never_revokes_or_purges_and_releases_ui_guard(self):
        self.first.save_draft.side_effect = ConnectionError('offline')
        operation, _, _, failed = self.begin()
        with self.assertRaises(ConnectionError) as caught:
            await operation
        failed(caught.exception)
        self.app.service.logout.assert_not_awaited()
        self.assertTrue(self.manager.store.get('a', 1)['pending'])
        self.assertTrue(DraftStore(self.root).get('a', 1)['pending'])
        self.assertIn('a', read_json(self.root/'profile-designs.json', {}))
        self.assertEqual(self.app.ui_account, 'a')
        self.assertNotIn('a', self.app._logging_out_accounts)
        self.linked.close.assert_not_called()
        self.app.show_error.assert_called_once_with(caught.exception)

    async def test_unavailable_backend_or_unsupported_pending_draft_cancels_logout(self):
        for unsupported in (False, True):
            with self.subTest(unsupported=unsupported):
                self.app.service.services['a'].backend = self.first if unsupported else None
                self.manager.store.put('a', 1, {'text': 'keep locally', 'unsupported': unsupported}, pending=True)
                operation, _, _, failed = self.begin()
                with self.assertRaises(ValueError) as caught:
                    await operation
                failed(caught.exception)
                self.app.service.logout.assert_not_awaited()
                self.assertTrue(self.manager.store.get('a', 1)['pending'])
                self.assertNotIn('a', self.app._logging_out_accounts)

    async def test_cleanup_io_failure_after_revocation_still_restores_next_account_and_reports_error(self):
        operation, _, _, failed = self.begin()
        with patch('tg_ascii.profile_customization.write_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError) as caught:
                await operation
        failed(caught.exception)
        self.app.service.logout.assert_awaited_once_with('a')
        self.assertEqual(self.app.ui_account, 'b')
        self.assertEqual(self.app.drafts[2][0], 'restore before showing B')
        self.app.login_stage.assert_called_once_with('ready')
        self.app.show_error.assert_called_once_with(caught.exception)
        self.linked.close.assert_called_once_with(discard_draft=True)

    async def test_failed_revocation_keeps_synced_local_drafts_and_windows(self):
        self.app.service.logout.side_effect = ConnectionError('cannot log out')
        operation, _, _, failed = self.begin()
        with self.assertRaises(ConnectionError) as caught:
            await operation
        failed(caught.exception)
        self.assertEqual(self.manager.store.get('a', 1)['text'], 'save before revocation')
        self.assertIn('linked:a', self.manager.store.records)
        self.linked.close.assert_not_called()
        self.assertIn('a', read_json(self.root/'profile-designs.json', {}))
        self.assertEqual(self.app.ui_account, 'a')

    async def test_last_account_cleanup_error_keeps_returned_login_stage(self):
        for stage in ('phone', 'credentials'):
            with self.subTest(stage=stage):
                self.app.service.entries = {'a': {}}
                self.app.service.current = self.app.ui_account = 'a'
                self.app.service.services = {'a': NS(backend=self.first)}
                self.app.service.backend = self.first
                self.app.login_stage.reset_mock()
                async def logout(key):
                    self.app.service.entries.clear()
                    self.app.service.services.clear()
                    self.app.service.current = 'c' * 32
                    self.app.service.backend = None
                    return stage
                self.app.service.logout.side_effect = logout
                operation, _, _, failed = self.begin()
                with patch('tg_ascii.profile_customization.write_json', side_effect=OSError('disk full')):
                    with self.assertRaises(OSError) as caught:
                        await operation
                failed(caught.exception)
                self.assertEqual(self.app.ui_account, 'c' * 32)
                self.assertEqual(self.app.drafts, {})
                self.app.login_stage.assert_called_once_with(stage)
                self.assertNotIn('a', self.app._logging_out_accounts)

    async def test_last_account_registry_error_before_connect_shows_retry(self):
        from tg_ascii.desktop import Desktop
        self.app.service.entries = {'a': {}}
        self.app.service.connect = AsyncMock(return_value='phone')
        self.app.clear = Mock()
        self.app.container = Mock()
        self.app.show_error = lambda error: Desktop.show_error(self.app, error)
        self.app.login_stage.side_effect = lambda stage: setattr(self.app, 'stage', stage)
        async def logout(key):
            self.app.service.entries.clear()
            self.app.service.services.clear()
            self.app.service.current = 'c' * 32
            self.app.service.backend = None
            raise OSError('registry cannot be saved')
        self.app.service.logout.side_effect = logout
        operation, _, _, failed = self.begin()
        with self.assertRaises(OSError) as caught:
            await operation
        with patch('tg_ascii.desktop.ttk.Label'), patch('tg_ascii.desktop.ttk.Button') as button, \
             patch('tg_ascii.desktop.messagebox.showerror'):
            failed(caught.exception)
        self.app.login_stage.assert_called_once_with('connecting')
        self.assertEqual(button.call_count, 1)
        button.call_args.kwargs['command']()
        retry, callback, _ = self.app.call.call_args.args
        self.assertEqual(await retry, 'phone')
        self.assertIs(callback, self.app.login_stage)
        self.app.service.connect.assert_awaited_once()
        self.assertEqual(self.app.ui_account, 'c' * 32)


class LogoutIsolationTests(unittest.TestCase):
    def test_empty_registry_uses_fresh_slot_and_never_inherits_legacy_account(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertEqual(Accounts(root=root).current, 'account')
            write_json(root/'accounts.json', {'active': 'account', 'accounts': {}})
            fresh = Accounts(root=root)
            self.assertNotEqual(fresh.current, 'account')
            self.assertRegex(fresh.current, r'^[a-f0-9]{32}$')
            write_json(root/'accounts.json', {'active': fresh.current, 'accounts': {}})
            self.assertEqual(Accounts(root=root).current, fresh.current)

    def test_purge_only_removes_selected_views_and_owned_photo_not_shared_resources(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shared = root/'wallpaper.png'
            shared.write_bytes(b'shared resource')
            for name, entries in {
                'profile-designs.json': {'a': {}, 'ab': {}, 'b': {}},
                'local-pins.json': {'a': [1], 'ab': [2], 'b': [3]},
                'wallpapers.json': {'a:1': str(shared), 'b:1': str(shared), 'ab:1': str(shared)},
                'translations.json': {'a:1': 'es', 'b:1': 'en'},
                'chat-themes.json': {'a:1': 'dark', 'wallpaper:a:1': str(shared), 'b:1': 'light', 'wallpaper:b:1': str(shared)},
            }.items():
                write_json(root/name, entries)
            photos = {}
            for key in ('a', 'b'):
                directory = root/'profile-photos'/hashlib.sha256(key.encode()).hexdigest()
                directory.mkdir(parents=True)
                photos[key] = directory/('0'*32+'.image')
                photos[key].write_bytes(b'owned local photo')
            unknown = photos['a'].with_name('keep-user-file.png')
            unknown.write_bytes(b'unknown file')
            purge_account_customization(root, 'a')
            self.assertEqual(set(read_json(root/'profile-designs.json', {})), {'ab', 'b'})
            self.assertEqual(set(read_json(root/'local-pins.json', {})), {'ab', 'b'})
            self.assertEqual(set(read_json(root/'wallpapers.json', {})), {'b:1', 'ab:1'})
            self.assertEqual(set(read_json(root/'chat-themes.json', {})), {'b:1', 'wallpaper:b:1'})
            self.assertFalse(photos['a'].exists())
            self.assertTrue(photos['b'].exists())
            self.assertTrue(unknown.exists())
            self.assertTrue(shared.exists())

    def test_late_account_change_does_not_repopulate_old_state(self):
        app = NS(service=NS(entries={'b': {}}), ui_account='b', account_states={},
                 _chat_windows=[Mock()], _logging_out_accounts=set())
        DesktopPlus.account_change(app, ('a', 'draft', (1, {'text': 'late'})))
        app._chat_windows[0].change.assert_not_called()
        self.assertEqual(app.account_states, {})


if __name__ == '__main__':
    unittest.main()
