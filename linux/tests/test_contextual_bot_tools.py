"""Invalid actions stay absent; supported read-only/opt-in actions stay reachable."""
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
from telethon import types as t

from tg_ascii.backend import Chat, Message
from tg_ascii.bot_buttons import button_available
from tg_ascii.chat_capabilities import capabilities_for
from tg_ascii.desktop_bot_buttons import DesktopBotButtons, paint_buttons, visible_button_rows
from tg_ascii.desktop_tools import DesktopTools
from tg_ascii.desktop_modern import DesktopModern, privacy_global_fields
from tg_ascii.i18n import set_language
from tg_ascii.translation_queue import schedule
from tg_ascii.translated_view import presentation


def context(kind='user', premium=False):
    entity = (t.User(7, bot=kind == 'bot') if kind in ('bot', 'user') else
              t.Channel(7, 'Synthetic channel', t.ChatPhotoEmpty(), 0, broadcast=True))
    peer = 7 if kind in ('bot', 'user') else -1000000000007
    backend = NS(account_profile=NS(user=t.User(100, premium=premium, phone='123'), user_id=100, premium=premium),
                 activate_bot_button=Mock(return_value='operation'))
    app = NS(ui_account='a', active=peer, demo=False, busy=False, selection_kind=None, closed=False,
             preferences=NS(values={'advanced_features': {}, 'theme': 'dark', 'font_size': 12}),
             chats=[Chat(peer, 'Synthetic', kind=kind, entity=entity)], service=NS(backend=backend, entries={'a': {'premium': premium}}),
             root=Mock(), status=Mock(), call=Mock(), complex_settings=Mock(), font_family='Arial',
             press_bot_button=Mock(), format_dialog=Mock(), audio_menu=Mock(), schedule_message=Mock(),
             send=Mock(), ai_dialog=Mock(), translation_dialog=Mock(), editor=Mock(), record_audio=Mock())
    app.editor.get.return_value = 'Draft'
    return app


def inline(*buttons):
    return Message(10, 'Bot', 'Synthetic', '12:00', reply_markup=t.ReplyInlineMarkup([t.KeyboardInlineButtonRow(list(buttons))]))


class ContextualBotTests(unittest.TestCase):
    def test_readonly_channel_keeps_callbacks_links_copy_but_not_sending(self):
        app = context('channel')
        caps = capabilities_for(app.chats[0])
        self.assertFalse(caps.writable)
        for action in (t.InlineButtonTypeCallback(b'1'), t.InlineButtonTypeUrl('https://example.com'), t.InlineButtonTypeCopy('Copy')):
            self.assertTrue(button_available(t.KeyboardInlineButton('Action', action), caps))
        self.assertFalse(button_available(t.KeyboardButton('Send', t.ButtonTypeDefault()), caps))
        self.assertFalse(button_available(t.KeyboardButton('Phone', t.ButtonTypeRequestPhone()), caps))
        self.assertFalse(button_available(t.KeyboardInlineButton('Local file', t.InlineButtonTypeUrl('file:///private')), caps))

    def test_unsupported_removed_and_original_column_survives_reflow(self):
        app = context('bot')
        unavailable = t.KeyboardInlineButton('Password', t.InlineButtonTypeCallback(b'private', requires_password=True))
        usable = t.KeyboardInlineButton('Next', t.InlineButtonTypeCallback(b'next'))
        message = inline(unavailable, usable)
        rows = list(visible_button_rows(app, message))
        self.assertEqual(rows, [(0, [(1, usable)])])
        canvas = Mock(); canvas.bot_font = None; canvas.bbox.return_value = (0, 0, 80, 24)
        callbacks = []
        with patch('tg_ascii.desktop_bot_buttons.font.Font'):
            paint_buttons(canvas, app, message, 0, 0, 300, interactive=lambda item, callback: callbacks.append(callback))
        self.assertEqual(canvas.create_rectangle.call_count, 1)
        callbacks[0]()
        self.assertEqual(app.press_bot_button.call_args.args[1:3], (0, 1))
        with patch('tg_ascii.desktop_bot_buttons.messagebox.showinfo') as info:
            DesktopBotButtons.press_bot_button(app, message, 0, 0, unavailable, ('a', app.active))
        info.assert_not_called(); app.call.assert_not_called()

    def test_request_phone_requires_private_bot_and_cached_number(self):
        button = t.KeyboardButton('Phone', t.ButtonTypeRequestPhone())
        message = Message(10, 'Bot', 'Phone', '12:00', reply_markup=t.ReplyKeyboardMarkup([t.KeyboardButtonRow([button])]))
        bot = context('bot')
        self.assertTrue(list(visible_button_rows(bot, message)))
        bot.service.backend.account_profile.user.phone = None
        self.assertFalse(list(visible_button_rows(bot, message)))
        self.assertFalse(list(visible_button_rows(context('user'), message)))

    def test_force_reply_cannot_send_in_readonly_channel(self):
        app = context('channel')
        request = Message(10, 'Bot', 'Reply', '12:00', reply_markup=t.ReplyKeyboardForceReply())
        app.bot_keyboard_key = ('a', app.active, 10)
        app.bot_keyboard_cache = {('a', app.active): request}
        app.reply_message = Mock()
        DesktopBotButtons.toggle_bot_keyboard(app)
        app.reply_message.assert_not_called()


class ContextualTranslationTests(unittest.TestCase):
    def app(self, premium=True):
        app = context(premium=premium)
        app.preferences.values['advanced_features']['chat_translation'] = True
        app.chat_translations = {'a:7': 'es'}
        app.messages = [Message(10, 'Synthetic', 'Hello', '12:00')]
        app.translated, app.translation_pending, app.translation_failed = {}, set(), set()
        app.worker, app.render_messages = Mock(), Mock()
        return app

    def test_nonpremium_or_chat_disabled_never_requests_translation(self):
        for premium, disabled in ((False, False), (True, True)):
            with self.subTest(premium=premium, disabled=disabled):
                app = self.app(premium)
                app.service.backend._capability_full = {7: NS(translations_disabled=disabled)}
                schedule(app)
                app.worker.submit.assert_not_called()

    def test_premium_revocation_cancels_pending_and_hides_existing_translation(self):
        app = self.app()
        schedule(app)
        operation, done, _ = app.worker.submit.call_args.args
        operation.close()
        job = app._translation_job
        app.translated[('a', 7, 10, 'es', 'Hello')] = t.TextWithEntities('Hola', [])
        app.service.backend.account_profile.premium = False
        schedule(app)
        job.cancel.assert_called_once()
        self.assertEqual(presentation(app, app.messages[0]), (app.messages[0], None, ''))
        done({10: t.TextWithEntities('Late result', [])})
        self.assertEqual(app.translated[('a', 7, 10, 'es', 'Hello')].text, 'Hola')

    def test_missing_chat_never_starts_saved_translation(self):
        app = self.app(); app.chats = []
        schedule(app)
        app.worker.submit.assert_not_called()


class ContextualToolMenuTests(unittest.TestCase):
    def setUp(self): set_language('en')

    def test_translation_entry_only_premium_and_disabled_opens_settings(self):
        app = context(premium=False)
        self.assertNotIn('Translate chat', dict(DesktopTools.composer_tool_actions(app)))
        app.service.backend.account_profile.premium = True
        actions = dict(DesktopTools.composer_tool_actions(app))
        actions['Translate chat · Disabled']()
        app.complex_settings.assert_called_once()
        app.preferences.values['advanced_features']['chat_translation'] = True
        self.assertIn('Translate chat', dict(DesktopTools.composer_tool_actions(app)))

    def test_readonly_channel_has_translation_but_no_composer_actions(self):
        app = context('channel', premium=True)
        self.assertEqual(list(dict(DesktopTools.composer_tool_actions(app))), ['Translate chat · Disabled'])

    def test_bot_has_no_scheduling_and_voice_restrictions_preserve_audio_files(self):
        bot = context('bot')
        self.assertNotIn('Schedule message', dict(DesktopTools.composer_tool_actions(bot)))
        app = context()
        app.service.backend._capability_full = {7: NS(voice_messages_forbidden=True)}
        app.composer_controls = Mock()
        with patch('tg_ascii.app_dialogs.popup_menu') as popup:
            DesktopTools.audio_menu(app)
        self.assertEqual([label for label, _ in popup.call_args.args[1]], ['Send audio file'])

    def test_global_privacy_honors_server_exception_and_keeps_disable_reachable(self):
        self.assertEqual(set(privacy_global_fields(False, {}, NS())), {'hide_read_marks'})
        configured = {'autoarchive_setting_available': True, 'new_noncontact_peers_require_premium_without_ownpremium': True}
        self.assertEqual(len(privacy_global_fields(False, configured, NS())), 3)
        self.assertEqual(len(privacy_global_fields(True, {}, NS())), 3)
        current = NS(archive_and_mute_new_noncontact_peers=True)
        self.assertIn('archive_and_mute_new_noncontact_peers', privacy_global_fields(False, {}, current))

    def test_voice_privacy_control_uses_cached_premium_without_rpc(self):
        for premium in (False, True):
            with self.subTest(premium=premium):
                app = context(premium=premium); app.dialog = Mock(return_value=(Mock(), Mock()))
                with patch('tg_ascii.desktop_modern.scrollable'), patch('tg_ascii.desktop_modern.ttk.Button') as button:
                    DesktopModern.privacy_dialog(app)
                labels = [call.kwargs['text'] for call in button.call_args_list]
                self.assertEqual('Voice messages' in labels, premium)
                app.call.assert_not_called()

    def test_individual_translation_is_available_without_premium_but_not_for_media_placeholder(self):
        app = context()
        text = Message(1, 'Synthetic', 'Actual text', '12:00', raw_text='Actual text')
        self.assertEqual(DesktopTools.message_tool_kinds(app, text), ('translate', 'summary'))
        empty = Message(2, 'Synthetic', '[Audio]', '12:00', raw_text='', media_kind='audio')
        self.assertEqual(DesktopTools.message_tool_kinds(app, empty), ())

    def test_transcription_requires_voice_or_round_video_not_a_music_file(self):
        app = context()
        message = Message(2, 'Synthetic', '[Audio]', '12:00', raw_text='', media_kind='audio')
        message.media = NS(document=NS(attributes=[t.DocumentAttributeAudio(20, voice=False)]))
        self.assertEqual(DesktopTools.message_tool_kinds(app, message), ())
        message.media.document.attributes[0].voice = True
        self.assertEqual(DesktopTools.message_tool_kinds(app, message), ('transcribe',))
        message.media.document.attributes = [t.DocumentAttributeVideo(20, 200, 200, round_message=True)]
        self.assertEqual(DesktopTools.message_tool_kinds(app, message), ('transcribe',))


if __name__ == '__main__': unittest.main()
