import unittest
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest import mock

from tg_ascii import i18n
from tg_ascii.desktop_actions import DesktopActions


class Root:
    def __init__(self): self.after_calls = []
    def after(self, delay, callback): self.after_calls.append((delay, callback))


class Worker:
    def __init__(self): self.jobs = []
    def submit(self, coroutine, success, failure):
        coroutine.close(); self.jobs.append((success, failure))


def app(selected=()):
    backend = NS(read_time=mock.AsyncMock(return_value='05:31'))
    values = {'show_seconds': False}
    a = NS(root=Root(), worker=Worker(), preferences=NS(values=values), ui_account='a', active=9,
           service=NS(backend=backend), selected_messages=set(selected))
    a.message_selected = lambda ident: ident in a.selected_messages
    return a, backend


def caps(read=True):
    return NS(allows_message=lambda action, message: read and action == 'read_time')


class MessageMenuDateTests(unittest.TestCase):
    def setUp(self):
        i18n.set_language('es')
        self.message = NS(id=4, edited_at=datetime(2026, 11, 25, 4, 30, tzinfo=timezone.utc))
        self.entries = [('Responder', lambda: None)]

    def show(self, a, backend, read=True):
        with mock.patch('tg_ascii.app_dialogs.popup_menu') as popup:
            DesktopActions.show_message_menu(a, self.message, self.entries, caps(read), backend, 'a', 9)
            return popup

    def test_read_and_edit_dates_head_the_menu(self):
        a, backend = app()
        with mock.patch('tg_ascii.app_dialogs.popup_menu') as popup:
            DesktopActions.show_message_menu(a, self.message, self.entries, caps(), backend, 'a', 9)
            popup.assert_not_called()  # waits for Telegram first
            a.worker.jobs[0][0]('05:31')
            entries = popup.call_args[0][1]
        self.assertEqual(entries[0][0], 'Hora de lectura: 05:31')
        self.assertFalse(entries[0][2])
        self.assertTrue(entries[1][0].startswith('Editado: '))
        self.assertIsNone(entries[2])
        self.assertEqual(entries[3:], self.entries)

    def test_slow_answer_opens_the_menu_once_and_caches_later_value(self):
        a, backend = app()
        with mock.patch('tg_ascii.app_dialogs.popup_menu') as popup:
            DesktopActions.show_message_menu(a, self.message, self.entries, caps(), backend, 'a', 9)
            a.root.after_calls[0][1]()
            a.worker.jobs[0][0]('05:31')
            self.assertEqual(popup.call_count, 1)
            self.assertTrue(popup.call_args[0][1][0][0].startswith('Editado'))

    def test_multiple_selection_hides_the_dates(self):
        a, backend = app(selected={4, 5})
        popup = self.show(a, backend)
        self.assertEqual(popup.call_args[0][1], self.entries)
        self.assertEqual(a.worker.jobs, [])

    def test_no_read_permission_still_shows_edit_date(self):
        a, backend = app()
        popup = self.show(a, backend, read=False)
        self.assertTrue(popup.call_args[0][1][0][0].startswith('Editado'))
        self.assertEqual(a.worker.jobs, [])


if __name__ == '__main__':
    unittest.main()
