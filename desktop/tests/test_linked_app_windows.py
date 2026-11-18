"""Shared full-app views: no Tk, Telegram, credentials or external processes."""
from concurrent.futures import Future
from pathlib import Path
from queue import SimpleQueue
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock

from tg_ascii.accounts import Accounts, AccountsView
from tg_ascii.desktop import Desktop
from tg_ascii.drafts import DraftStore
from tg_ascii.interface_windows import WindowWorker, forward_chat_event, forward_chat_change, purge_window_drafts
from tg_ascii.preferences import Preferences
from tg_ascii.interface_store import InterfaceStore


class AccountsViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_selections_are_independent_and_never_open_duplicate_services(self):
        with tempfile.TemporaryDirectory() as directory:
            owner = Accounts(demo=True, root=directory)
            owner.entries['b' * 32] = {'label': 'B'}
            a, b = NS(backend=object()), NS(backend=object())
            owner.services.update(account=a, **{'b' * 32: b})
            first, second = AccountsView(owner), AccountsView(owner)
            await first.select('b' * 32)
            self.assertIs(first.backend, b.backend)
            self.assertIs(second.backend, a.backend)
            self.assertEqual(owner.current, 'account')
            self.assertIs(first.entries, second.entries)
            self.assertIs(first.services, owner.services)
            await first.close()
            self.assertIs(second.backend, a.backend)
            with self.assertRaises(ValueError): await first.add()
            with self.assertRaises(ValueError): await first.logout('account')

    async def test_lost_authorization_is_not_opened_twice(self):
        owner = Accounts(demo=True)
        service = NS(backend=None, connect=AsyncMock())
        owner.services['account'] = service
        view = AccountsView(owner)
        with self.assertRaises(ValueError): await view.select('account')
        service.connect.assert_not_called()


class ViewWorkerTests(unittest.TestCase):
    def setUp(self):
        self.app = NS(closed=False, _view_generation=0)
        self.callbacks = []
        self.futures = []
        def submit(coroutine, done, failed):
            coroutine.close()
            self.callbacks.append((done, failed))
            result = Future()
            self.futures.append(result)
            return result
        self.owner = NS(loop=object(), events=SimpleQueue(), submit=submit, stop=Mock())
        self.worker = WindowWorker(self.app, self.owner)

    async def operation(self): return 42

    def test_close_cancels_only_local_jobs_and_never_shared_loop(self):
        success = Mock()
        self.worker.submit(self.operation(), success, Mock())
        self.worker.stop()
        self.callbacks[0][0](42)
        success.assert_not_called()
        self.assertTrue(self.futures[0].cancelled())
        self.owner.stop.assert_not_called()
        self.assertFalse(self.worker.pending)

    def test_account_generation_suppresses_late_callback_and_disposes_image(self):
        success = Mock()
        self.worker.submit(self.operation(), success, Mock())
        self.app._view_generation += 1
        image = Mock()
        self.callbacks[0][0](image)
        success.assert_not_called()
        image.close.assert_called_once()

    def test_stopped_submission_closes_unstarted_coroutine(self):
        self.worker.stop()
        operation = self.operation()
        self.assertTrue(self.worker.submit(operation, Mock(), Mock()).cancelled())
        self.assertIsNone(operation.cr_frame)


class WindowStateTests(unittest.TestCase):
    def test_event_fanout_visits_each_view_once_and_secondary_never_fans_back(self):
        views = [NS(closed=False, closing=False, account_event=Mock(), account_change=Mock()) for _ in range(2)]
        owner = NS(_app_windows=views, _chat_windows=[])
        forward_chat_event(owner, 'a', 42, 'message')
        forward_chat_change(owner, 'a', 'draft', ('42', {}))
        for view in views:
            view.account_event.assert_called_once_with(('a', 42, 'message'))
            view.account_change.assert_called_once_with(('a', 'draft', ('42', {})))
        secondary = NS(_linked_owner=owner, _chat_windows=[])
        forward_chat_event(secondary, 'a', 42, 'message')
        for view in views: self.assertEqual(view.account_event.call_count, 1)

    def test_preferences_and_layout_emit_only_on_actual_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            preferences = Preferences(root=directory, demo=True)
            layout = InterfaceStore(directory, demo=True)
            pref_event, design_event = Mock(), Mock()
            preferences.listeners.append(pref_event)
            layout.listeners.append(design_event)
            preferences.save({'theme': 'light'})
            preferences.save({'theme': 'light'})
            document = {**layout.document, 'name': 'Changed'}
            layout.commit(document)
            layout.commit(document)
            layout.undo(); layout.redo()
            pref_event.assert_called_once()
            self.assertEqual(design_event.call_count, 3)

    def test_logout_purges_active_and_closed_window_drafts_only_for_chosen_account(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = DraftStore(root/'window-drafts'/'window-1')
            closed = DraftStore(root/'window-drafts'/'window-2')
            for store in (active, closed):
                store.put('a', 42, {'text': 'A'})
                store.put('b', 42, {'text': 'B'})
                store.flush()
            owner = NS(service=NS(root=root), preferences=NS(path=root/'preferences.json'), demo=False,
                       _app_windows=[NS(closed=False, draft_manager=NS(store=active))])
            purge_window_drafts(owner, 'a')
            self.assertIsNone(active.get('a', 42))
            reopened = DraftStore(closed.path.parent)
            self.assertIsNone(reopened.get('a', 42))
            self.assertEqual(reopened.get('b', 42)['text'], 'B')

    def test_child_disk_error_prevents_parent_destroy_or_worker_stop(self):
        child = NS(closing=True, draft_manager=NS(close_pending=False, close_error=OSError('disk')))
        owner = NS(closed=False, closing=True, root=Mock(), worker=Mock(), draft_manager=None,
                   _app_windows=[child], show_error=Mock())
        Desktop.finish_close(owner, None)
        self.assertFalse(owner.closing)
        self.assertFalse(child.closing)
        owner.root.destroy.assert_not_called()
        owner.worker.stop.assert_not_called()
        owner.show_error.assert_called_once()


if __name__ == '__main__': unittest.main()
