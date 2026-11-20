import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tg_ascii.desktop import Desktop
from tg_ascii.preferences import Preferences


class StartupAccountTests(unittest.TestCase):
    def app(self, entries, ask=True):
        return SimpleNamespace(service=SimpleNamespace(entries=entries, current=next(iter(entries))),
            preferences=SimpleNamespace(values={'ask_account_startup': ask}), start_chosen_account=Mock())

    def test_one_account_opens_directly_even_with_chooser_enabled(self):
        app = self.app({'account': {}})
        with patch('tg_ascii.startup_accounts.show_account_chooser') as chooser:
            Desktop.begin_startup(app)
        chooser.assert_not_called()
        app.start_chosen_account.assert_called_once_with('account', False)

    def test_several_accounts_wait_for_selection_before_connecting(self):
        app = self.app({'account': {}, 'second': {}})
        with patch('tg_ascii.startup_accounts.show_account_chooser') as chooser:
            Desktop.begin_startup(app)
        chooser.assert_called_once_with(app, False)
        app.start_chosen_account.assert_not_called()

    def test_disabled_chooser_uses_last_account(self):
        app = self.app({'account': {}, 'second': {}}, ask=False)
        app.service.current = 'second'
        with patch('tg_ascii.startup_accounts.show_account_chooser') as chooser:
            Desktop.begin_startup(app)
        chooser.assert_not_called()
        app.start_chosen_account.assert_called_once_with('second', False)

    def test_preference_survives_restart_and_rejects_non_boolean(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Preferences(folder)
            self.assertTrue(settings.values['ask_account_startup'])
            settings.save({'ask_account_startup': False})
            self.assertFalse(Preferences(folder).values['ask_account_startup'])
            settings.save({'ask_account_startup': 'false'})
            self.assertTrue(settings.values['ask_account_startup'])


if __name__ == '__main__':
    unittest.main()
