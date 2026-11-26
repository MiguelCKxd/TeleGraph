"""Regressions found by reading the 3.4 desktop rendering paths."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

from telethon import types
from tg_ascii.desktop_actions import DesktopActions
from tg_ascii.desktop_bot_buttons import DesktopBotButtons


class ContactEditorThreadTests(unittest.TestCase):
    def test_contact_fields_are_read_before_running_network_coroutine(self):
        ui_thread = threading.get_ident()
        def field(value):
            def get():
                self.assertEqual(threading.get_ident(), ui_thread, 'Tk field accessed from worker')
                return value
            return NS(get=get)
        backend = NS(save_contact=AsyncMock(return_value=True))
        window = Mock()
        window.winfo_exists.return_value = True
        app = NS(busy=False, demo=True, ui_account='first', service=NS(backend=backend),
                 dialog=Mock(return_value=(window, Mock())), refresh=Mock(),
                 field=Mock(side_effect=[field('Ana'), field('Prueba'), field('+34000000000')]))
        operations = []
        app.call = lambda operation, done, status: operations.append((operation, done))
        with patch('tg_ascii.desktop_actions.ttk.Button') as button:
            DesktopActions.edit_contact(app, dict(id=42, first_name='', last_name='', phone=''), backend)
            save = button.call_args.kwargs['command']
        save()
        self.assertEqual(len(operations), 1)
        operation, done = operations.pop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(asyncio.run, operation).result(timeout=5)
        backend.save_contact.assert_awaited_once_with(42, 'Ana', 'Prueba', '+34000000000')
        done(result)
        app.refresh.assert_called_once()


class InlineKeyboardLifetimeTests(unittest.TestCase):
    def test_rebuilt_history_gets_its_own_resize_binding(self):
        message = NS(reply_markup=types.ReplyInlineMarkup([]))
        first, second = Mock(), Mock()
        first.winfo_width.return_value = second.winfo_width.return_value = 400
        # Behave like normal Tk widgets for attributes not previously set.
        first._bot_resize_bound = second._bot_resize_bound = False
        app = NS(history=first, bot_inline_widgets=[])
        canvases = [Mock(), Mock(), Mock()]
        with patch('tg_ascii.desktop_bot_buttons.visible_button_rows', return_value=[(0, [(0, object())])]), \
             patch('tg_ascii.desktop_bot_buttons.KeyboardCanvas', side_effect=canvases):
            DesktopBotButtons.insert_bot_buttons(app, message)
            DesktopBotButtons.insert_bot_buttons(app, message)
            self.assertEqual(first.bind.call_count, 1)
            app.history = second
            app.bot_inline_widgets = []
            DesktopBotButtons.insert_bot_buttons(app, message)
        self.assertEqual(second.bind.call_count, 1)
        second.bind.call_args.args[1](NS(width=640))
        canvases[2].configure.assert_called_with(width=612)


if __name__ == '__main__':
    unittest.main()
