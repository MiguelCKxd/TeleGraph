"""Regression for sender names, transient delivery failures and bot consent."""
from datetime import datetime, timezone
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch
from telethon import errors, types as t

from tg_ascii.backend import TelegramBackend, Message, Chat
from tg_ascii.bot_buttons import keyboard_message
from tg_ascii.desktop_bot_buttons import DesktopBotButtons
from tg_ascii.notifications import NotificationCenter, foreground_view
from tg_ascii.translation_queue import schedule
from tg_ascii.translated_view import presentation


class DeliveryRegression(unittest.IsolatedAsyncioTestCase):
    def backend(self):
        client = AsyncMock()
        client.add_event_handler = Mock()
        backend = TelegramBackend(client)
        return client, backend

    async def test_one_invalid_message_does_not_block_other_translations(self):
        client, backend = self.backend()
        async def translated(request):
            if 2 in request.id: raise errors.MsgIdInvalidError(request)
            return NS(result=[t.TextWithEntities('translated-' + str(ident), []) for ident in request.id])
        client.side_effect = translated
        result = await backend.translate_messages(42, [1, 2, 3], 'es')
        self.assertEqual(list(result), [1, 3])
        self.assertLessEqual(client.await_count, 5)

    async def test_flood_wait_is_not_split_into_a_storm_of_single_message_calls(self):
        client, backend = self.backend()
        client.side_effect = errors.FloodWaitError(None, capture=30)
        with self.assertRaises(errors.FloodWaitError):
            await backend.translate_messages(42, list(range(20)), 'es')
        self.assertEqual(client.await_count, 1)

    async def test_embedded_entity_recovers_sender_without_any_network_lookup(self):
        client, backend = self.backend()
        source = NS(id=1, out=False, from_id=t.PeerUser(7), sender_id=7, sender=None, raw_text='Hello',
                    date=datetime.now(timezone.utc), _entities={7: t.User(7, first_name='Ada')})
        await backend.resolve_missing_senders([source])
        self.assertEqual(backend.message(source).sender, 'Ada')
        client.get_entity.assert_not_called()

    async def test_phone_button_prepares_without_sharing_and_rechecks_exact_number(self):
        client, backend = self.backend()
        button = t.KeyboardButton('Contact', t.ButtonTypeRequestPhone())
        message = NS(peer_id=t.PeerUser(7), get_sender=AsyncMock(return_value=t.User(7, bot=True, first_name='Bot')),
                     reply_markup=t.ReplyKeyboardMarkup([t.KeyboardButtonRow([button])]))
        client.get_messages.return_value = message
        client.get_me.return_value = t.User(99, first_name='Test', phone='123456789')
        backend.send_contact_card = AsyncMock(return_value=Message(100, 'Me', 'Contact', '12:00'))
        prepared = await backend.activate_bot_button(7, 9, 0, 0, bytes(button))
        self.assertEqual(prepared['request_phone']['phone'], '123456789')
        backend.send_contact_card.assert_not_called()
        await backend.activate_bot_button(7, 9, 0, 0, bytes(button), phone_consent='different')
        backend.send_contact_card.assert_not_called()
        result = await backend.activate_bot_button(7, 9, 0, 0, bytes(button), phone_consent='123456789')
        self.assertEqual(result['message'].id, 100)
        backend.send_contact_card.assert_awaited_once_with(7, 'Test', '', '123456789', reply_to=9)
        message.reply_markup.rows[0].buttons[0] = t.KeyboardButton('Changed', t.ButtonTypeDefault())
        with self.assertRaises(ValueError):
            await backend.activate_bot_button(7, 9, 0, 0, bytes(button), phone_consent='123456789')
        self.assertEqual(backend.send_contact_card.await_count, 1)

    async def test_game_callback_and_user_profile_do_not_send_chat_messages(self):
        client, backend = self.backend()
        button = t.KeyboardInlineButton('Game', t.InlineButtonTypeGame())
        message = NS(peer_id=t.PeerUser(7), reply_markup=t.ReplyInlineMarkup([t.KeyboardInlineButtonRow([button])]))
        client.get_messages.return_value = message
        client.return_value = NS(message=None, alert=False, url='https://example.com/game')
        await backend.activate_bot_button(7, 9, 0, 0, bytes(button))
        self.assertTrue(client.call_args.args[0].game)
        button = t.KeyboardInlineButton('User', t.InlineButtonTypeUserProfile(123))
        message.reply_markup.rows[0].buttons[0] = button
        self.assertEqual(await backend.activate_bot_button(7, 9, 0, 0, bytes(button)), {'profile': 123})
        client.send_message.assert_not_called()


class DeliveryUITests(unittest.TestCase):
    def test_native_transient_failure_recovers_after_backoff(self):
        report = Mock()
        center = NotificationCenter(report)
        adapter = Mock()
        with patch('tg_ascii.notifications.sys.platform', 'win32'), patch('tg_ascii.notifications.WindowsCenter', side_effect=[OSError('temporary'), adapter]) as create, patch('tg_ascii.notifications.time.monotonic', side_effect=[100, 101, 131]):
            center.show('App', 'One', '1')
            center.show('App', 'Two', '2')
            center.show('App', 'Three', '3')
        self.assertEqual(create.call_count, 2)
        adapter.show.assert_called_once()
        self.assertFalse(center.unavailable)

    def test_focused_secondary_window_receives_notice_even_when_main_hidden(self):
        mainroot = NS(state=lambda: 'withdrawn')
        secondroot = NS(state=lambda: 'normal', master=mainroot)
        widget = NS(master=secondroot)
        mainroot.focus_displayof = secondroot.focus_displayof = lambda: widget
        second = NS(root=secondroot, closed=False)
        app = NS(root=mainroot, _app_windows=[second])
        self.assertIs(foreground_view(app), second)

    def test_force_reply_is_retained_and_cannot_resurrect_hidden_older_keyboard(self):
        request = Message(10, 'Bot', 'Reply please', '12:00', reply_markup=t.ReplyKeyboardForceReply())
        hidden = Message(11, 'Bot', 'Cancelled', '12:00', reply_markup=t.ReplyKeyboardHide())
        self.assertIs(keyboard_message([request]), request)
        self.assertIs(keyboard_message([request], previous=hidden), hidden)
        app = NS(bot_keyboard_key=('a', 7, 10), bot_keyboard_cache={('a', 7): request}, ui_account='a', active=7, chats=[Chat(7,'Bot',kind='bot',entity=t.User(7,bot=True))], reply_message=Mock())
        DesktopBotButtons.toggle_bot_keyboard(app)
        app.reply_message.assert_called_once_with(request)

    def test_phone_ui_requires_opt_in_before_even_requesting_account_details(self):
        app = NS(busy=False, demo=False, ui_account='a', active=7, preferences=NS(values={}), root=Mock(), chats=[Chat(7,'Bot',kind='bot',entity=t.User(7,bot=True))], complex_settings=Mock(),
                 service=NS(backend=NS(account_profile=NS(user=NS(phone='123')), activate_bot_button=Mock())))
        button = t.KeyboardButton('Phone', t.ButtonTypeRequestPhone())
        with patch('tg_ascii.desktop_bot_buttons.messagebox.showinfo') as info:
            DesktopBotButtons.press_bot_button(app, Message(10, 'Bot', 'Hello', '12:00',
                reply_markup=t.ReplyKeyboardMarkup([t.KeyboardButtonRow([button])])), 0, 0, button, ('a', 7))
        info.assert_not_called()
        app.complex_settings.assert_called_once()
        app.service.backend.activate_bot_button.assert_not_called()

    def app(self):
        app = NS(ui_account='a', active=7, demo=False, preferences=NS(values={'advanced_features': {'chat_translation': True}}),
                 chat_translations={'a:7': 'es'}, messages=[NS(id=1, text='Hello', raw_text='Hello')],
                 translated={}, translation_pending=set(), translation_failed=set(),
                 worker=Mock(), root=Mock(), status=Mock(), render_messages=Mock(), service=NS(entries={'a': {'premium': True}}, backend=Mock()), chats=[Chat(7,'Synthetic',entity=t.User(7))])
        app.schedule_translations = lambda: schedule(app)
        return app

    def test_transient_translation_retry_budget_is_bounded_and_text_not_blacklisted(self):
        app = self.app()
        for attempt in range(4):
            app._translation_after = 0
            schedule(app)
            operation, _, fail = app.worker.submit.call_args.args
            operation.close()
            fail(TimeoutError())
        self.assertEqual(app.worker.submit.call_count, 4)
        self.assertEqual(app.root.after.call_count, 3)
        self.assertFalse(app.translation_failed)
        app._translation_after = 0
        schedule(app)
        self.assertEqual(app.worker.submit.call_count, 4)

    def test_disabled_translation_cancels_pending_and_hides_cached_text(self):
        app = self.app()
        schedule(app)
        operation, _, _ = app.worker.submit.call_args.args
        operation.close()
        previous = app._translation_job
        app.preferences.values['advanced_features']['chat_translation'] = False
        schedule(app)
        previous.cancel.assert_called_once()
        message = Message(1, 'A', 'Hello', '12:00')
        app.translated[('a', 7, 1, 'es', 'Hello')] = t.TextWithEntities('Hola', [])
        self.assertEqual(presentation(app, message), (message, None, ''))
        self.assertIsNone(app._translation_job)


if __name__ == '__main__': unittest.main()
