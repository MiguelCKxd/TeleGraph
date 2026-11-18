"""Contact lookup must not reopen an old account's editor after switching."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from tg_ascii.desktop_actions import DesktopActions


class ContactAccountScopeTests(unittest.TestCase):
    def fixture(self):
        window = Mock()
        window.winfo_exists.return_value = True
        backend = NS(profile=AsyncMock(return_value={'is_user': True}))
        app = NS(busy=False, demo=False, ui_account='first', service=NS(backend=backend),
                 dialog=Mock(return_value=(window, Mock())),
                 field=Mock(return_value=NS(get=lambda:'@synthetic_contact')),
                 edit_contact=Mock(), show_error=Mock())
        callbacks = []
        def call(operation, loaded, status):
            operation.close()
            callbacks.append(loaded)
        app.call = call
        with patch('tg_ascii.desktop_actions.ttk.Button') as button:
            DesktopActions.add_username_contact(app)
            find = button.call_args.kwargs['command']
        return app, backend, window, find, callbacks

    def test_changed_account_or_closed_window_does_not_start_lookup(self):
        for change in ('account', 'backend', 'window'):
            with self.subTest(change=change):
                app, backend, window, find, callbacks = self.fixture()
                if change == 'account': app.ui_account = 'second'
                elif change == 'backend': app.service.backend = object()
                else: window.winfo_exists.return_value = False
                find()
                backend.profile.assert_not_called()
                self.assertEqual(callbacks, [])

    def test_late_lookup_result_never_reopens_stale_editor(self):
        for change in ('account', 'backend', 'window'):
            with self.subTest(change=change):
                app, backend, window, find, callbacks = self.fixture()
                find()
                backend.profile.assert_called_once_with('synthetic_contact')
                if change == 'account': app.ui_account = 'second'
                elif change == 'backend': app.service.backend = object()
                else: window.winfo_exists.return_value = False
                callbacks[0]({'is_user': True})
                app.edit_contact.assert_not_called()
                app.show_error.assert_not_called()

    def test_current_lookup_still_opens_editor(self):
        app, backend, window, find, callbacks = self.fixture()
        profile = {'is_user': True}
        find(); callbacks[0](profile)
        app.edit_contact.assert_called_once_with(profile, backend, window)


if __name__ == '__main__':
    unittest.main()
