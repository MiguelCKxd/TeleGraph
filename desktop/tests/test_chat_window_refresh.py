"""Authoritative reconnect snapshots and push races in pinned conversation views."""
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

from tg_ascii.desktop import Desktop


class ChatWindowRefreshTests(unittest.TestCase):
    def model(self):
        app = NS(closed=False, closing=False, _chat_only=True,
                 _pinned_account='a', _pinned_peer=41, ui_account='a', active=41,
                 demo=True, service=NS(entries={'a': {}}, backend=object()),
                 messages=[NS(id=1, text='old'), NS(id=2, text='deleted offline')],
                 render_messages=Mock(), refresh_wallpaper=Mock(), acknowledge_visible=Mock(),
                 status=Mock(), show_error=Mock(), worker=Mock())
        def submit(coroutine, loaded, failed):
            coroutine.close()
            app.loaded, app.failed = loaded, failed
        app.worker.submit.side_effect = submit
        return app

    def test_refresh_replaces_stale_edits_and_removes_messages_deleted_offline(self):
        app = self.model()
        Desktop.refresh_chat_window(app)
        fresh = NS(id=1, text='new server edit')
        app.loaded([fresh])
        self.assertEqual(app.messages, [fresh])
        self.assertFalse(app._refresh_pending)
        self.assertEqual(app._history_incoming, {})

    def test_push_after_snapshot_start_wins_without_reintroducing_deleted_history(self):
        app = self.model()
        Desktop.refresh_chat_window(app)
        live = NS(id=3, text='new while loading')
        edited = NS(id=1, text='push edit')
        app._history_incoming[3] = live
        app._history_changes = [('edit', (41, edited)), ('delete', (41, [2]))]
        app.loaded([NS(id=1, text='server snapshot'), NS(id=2, text='deleted during request')])
        self.assertEqual(app.messages, [edited, live])

    def test_removed_account_drops_late_result_without_accessing_another_backend(self):
        app = self.model()
        Desktop.refresh_chat_window(app)
        app.service.entries.clear()
        app.loaded([NS(id=9, text='late')])
        self.assertEqual([item.id for item in app.messages], [1, 2])
        app.render_messages.assert_not_called()


if __name__ == '__main__':
    unittest.main()
