import unittest
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch
from telethon import types as t, functions as f
from tg_ascii.backend import TelegramBackend, Message, Chat
from tg_ascii.bot_buttons import keyboard_message, button_supported
from tg_ascii.desktop_bot_buttons import DesktopBotButtons, paint_buttons


def keyboard(button=None):
    return t.ReplyKeyboardMarkup([t.KeyboardButtonRow([button or t.KeyboardButton('/start', t.ButtonTypeDefault())])], single_use=True)


class BotButtonTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = AsyncMock(); self.client.add_event_handler = Mock()
        self.backend = TelegramBackend(self.client)
        self.button = t.KeyboardButton('/help **literal**', t.ButtonTypeDefault())
        self.msg = NS(peer_id=t.PeerUser(7), reply_markup=keyboard(self.button))
        self.client.get_messages.return_value = self.msg
        self.backend.message = Mock(return_value=Message(99, 'Me', '/help', '12:00', True))

    async def activate(self):
        return await self.backend.activate_bot_button(7, 42, 0, 0, bytes(self.button))

    async def test_plain_button_sends_exact_command_to_captured_chat_once(self):
        result = await self.activate()
        self.client.send_message.assert_awaited_once_with(7, '/help **literal**', parse_mode=None, reply_to=42)
        self.assertEqual(result['message'].id, 99)

    async def test_callback_uses_payload_not_chat_message(self):
        self.button = t.KeyboardInlineButton('Next', t.InlineButtonTypeCallback(b'page:2'))
        self.msg.reply_markup = t.ReplyInlineMarkup([t.KeyboardInlineButtonRow([self.button])])
        self.client.return_value = NS(message='Done', alert=True, url=None)
        result = await self.activate()
        request = self.client.call_args.args[0]
        self.assertIsInstance(request, f.messages.GetBotCallbackAnswerRequest)
        self.assertEqual((request.peer, request.msg_id, request.data), (7, 42, b'page:2'))
        self.client.send_message.assert_not_awaited()
        self.assertEqual(result['notice'], 'Done'); self.assertTrue(result['alert'])

    async def test_changed_or_deleted_button_never_sends(self):
        self.msg.reply_markup = keyboard(t.KeyboardButton('/delete', t.ButtonTypeDefault()))
        with self.assertRaises(ValueError): await self.activate()
        self.client.get_messages.return_value = None
        with self.assertRaises(ValueError): await self.activate()
        self.client.send_message.assert_not_awaited(); self.client.assert_not_awaited()

    async def test_wrong_chat_and_negative_indices_rejected(self):
        self.msg.peer_id = t.PeerUser(8)
        with self.assertRaises(ValueError): await self.activate()
        self.msg.peer_id = t.PeerUser(7)
        with self.assertRaises(ValueError): await self.backend.activate_bot_button(7,42,-1,0,bytes(self.button))
        self.client.send_message.assert_not_awaited()

    async def test_url_is_validated_and_does_not_send(self):
        self.button = t.KeyboardInlineButton('Site', t.InlineButtonTypeUrl('https://example.com/help'))
        self.msg.reply_markup = keyboard(self.button)
        self.assertEqual((await self.activate())['url'], 'https://example.com/help')
        self.button = t.KeyboardInlineButton('Bad', t.InlineButtonTypeUrl('file:///etc/passwd'))
        self.msg.reply_markup = keyboard(self.button)
        with self.assertRaises(ValueError): await self.activate()
        self.client.send_message.assert_not_awaited()

    async def test_webapp_uses_clicked_url_and_bot_identity(self):
        self.button = t.KeyboardButton('App', t.ButtonTypeSimpleWebView('https://example.com/mini'))
        self.msg.reply_markup = keyboard(self.button)
        self.msg.get_sender = AsyncMock(return_value=t.User(7, bot=True, access_hash=9))
        self.client.get_input_entity.return_value = t.InputPeerUser(7, 9)
        self.client.return_value = NS(url='https://example.com/mini#auth')
        await self.activate()
        request = self.client.call_args.args[0]
        self.assertIsInstance(request, f.messages.RequestSimpleWebViewRequest)
        self.assertEqual(request.url, self.button.type.url)
        self.assertEqual(request.bot.user_id, 7)

    async def test_special_sensitive_buttons_never_share_data(self):
        for button in (t.KeyboardInlineButton('Protected', t.InlineButtonTypeCallback(b'data', requires_password=True)),):
            self.button = button; self.msg.reply_markup = keyboard(button)
            self.assertFalse(button_supported(button))
            with self.assertRaises(ValueError): await self.activate()
        self.client.send_message.assert_not_awaited(); self.client.assert_not_awaited()


class KeyboardStateTests(unittest.TestCase):
    def test_hide_wins_over_older_history_and_selective_ignored(self):
        old = Message(10,'Bot','Text','12:00',reply_markup=keyboard())
        hidden = Message(20,'Bot','Hidden','12:00',reply_markup=t.ReplyKeyboardHide())
        unrelated = Message(30,'Bot','Other user','12:00',reply_markup=keyboard(),keyboard_applicable=False)
        self.assertIs(keyboard_message([old,hidden,unrelated]), hidden)
        self.assertIs(keyboard_message([old], hidden), hidden)
        fresh = Message(40,'Bot','New','12:00',reply_markup=keyboard())
        self.assertIs(keyboard_message([fresh], hidden), fresh)

    def test_backend_retains_markup_and_checks_selective_target(self):
        client=AsyncMock();client.add_event_handler=Mock();backend=TelegramBackend(client)
        markup=keyboard();markup.selective=True
        source=NS(id=1,out=False,sender=None,sender_id=7,raw_text='Welcome',date=datetime.now(timezone.utc),reply_markup=markup,is_private=False,mentioned=False)
        converted=backend.message(source)
        self.assertIs(converted.reply_markup,markup);self.assertFalse(converted.keyboard_applicable)
        source.mentioned=True
        self.assertTrue(backend.message(source).keyboard_applicable)

    def test_old_account_selection_and_preview_cannot_activate(self):
        app=NS(busy=False,demo=False,ui_account='A',active=7,selection_kind=None,_preview_only=False)
        m=Message(1,'Bot','Text','12:00',reply_markup=keyboard())
        button=m.reply_markup.rows[0].buttons[0]
        # No service or root: any attempted send/dialog here would fail this test.
        DesktopBotButtons.press_bot_button(app,m,0,0,button,('B',7))
        app.selection_kind='messages'
        DesktopBotButtons.press_bot_button(app,m,0,0,button,('A',7))
        app.selection_kind=None;app._preview_only=True
        DesktopBotButtons.press_bot_button(app,m,0,0,button,('A',7))

    def test_grid_keeps_rows_and_correct_button_callbacks(self):
        app=NS(preferences=NS(values={'theme':'dark','font_size':12}),font_family='Menlo',ui_account='A',active=7,chats=[Chat(7,'Bot',kind='bot',entity=t.User(7,bot=True))],press_bot_button=Mock())
        message=Message(1,'Bot','Text','12:00',reply_markup=t.ReplyInlineMarkup([
            t.KeyboardInlineButtonRow([t.KeyboardInlineButton('One',t.InlineButtonTypeCallback(b'1')),t.KeyboardInlineButton('Two',t.InlineButtonTypeCallback(b'2'))]),
            t.KeyboardInlineButtonRow([t.KeyboardInlineButton('Three',t.InlineButtonTypeCallback(b'3'))])]))
        canvas=Mock();canvas.bot_font=None;canvas.bbox.return_value=(0,0,80,24)
        callbacks=[]
        with patch('tg_ascii.desktop_bot_buttons.font.Font'):
            height=paint_buttons(canvas,app,message,0,0,300,interactive=lambda _,cb:callbacks.append(cb))
        self.assertEqual(canvas.create_rectangle.call_count,3)
        self.assertGreaterEqual(height,64)
        callbacks[2]();self.assertEqual(app.press_bot_button.call_args.args[1:3],(0,1))
        callbacks[4]();self.assertEqual(app.press_bot_button.call_args.args[1:3],(1,0))

    def test_single_use_hides_only_after_success_and_preserves_draft(self):
        backend=NS(activate_bot_button=Mock(return_value='operation'))
        app=NS(busy=False,demo=False,ui_account='A',active=7,selection_kind=None,
            service=NS(backend=backend),chats=[Chat(7,'Bot',kind='bot',entity=t.User(7,bot=True))],bot_keyboard_hidden=set(),call=Mock(),account_event=Mock(),refresh_bot_keyboard=Mock())
        message=Message(1,'Bot','Text','12:00',reply_markup=keyboard())
        button=message.reply_markup.rows[0].buttons[0]
        DesktopBotButtons.press_bot_button(app,message,0,0,button,('A',7))
        self.assertEqual(app.bot_keyboard_hidden,set())
        app.call.call_args.args[1]({'message':Message(2,'Me','/start','12:00',True)})
        self.assertEqual(len(app.bot_keyboard_hidden),1);app.account_event.assert_called_once()


if __name__ == '__main__': unittest.main()
