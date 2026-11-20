import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from telethon import types
from tg_ascii.backend import Message
from tg_ascii.translated_view import presentation, toggle_original, insert_button, clear_buttons
from tg_ascii.message_tools import display_segments
from tg_ascii.bubbles import rich_runs, BubbleView
from tg_ascii.desktop import Desktop


class TranslationViewTests(unittest.TestCase):
    def setUp(self):
        self.message = Message(7, 'Ana', 'Hola', '12:00', raw_text='Hola', sender_id=42,
                               reply_to_id=6, media=object(), filename='photo.jpg')
        self.key = ('a', 42, 7, 'en', 'Hola')
        self.app = NS(preferences=NS(values={'advanced_features': {'chat_translation': True}, 'bubbles': False, 'animated_emoji': False, 'inline_media': False}), ui_account='a', active=42, chat_translations={'a:42': 'en'},
                      service=NS(entries={'a': {'premium': True}}, backend=NS()),
                      translated={self.key: types.TextWithEntities('Hello', [])},
                      messages=[self.message], render_messages=Mock())

    def test_translation_replaces_only_presentation_and_toggle_is_reversible(self):
        body, key, label = presentation(self.app, self.message)
        self.assertEqual((body.text, body.raw_text, label), ('Hello', 'Hello', 'Show original'))
        self.assertIs(body.media, self.message.media)
        self.assertEqual((body.reply_to_id, body.sender_id), (6, 42))
        self.assertEqual(self.message.text, 'Hola')
        toggle_original(self.app, key)
        self.assertIs(presentation(self.app, self.message)[0], self.message)
        self.assertEqual(presentation(self.app, self.message)[2], 'Show translation')
        toggle_original(self.app, key)
        self.assertEqual(presentation(self.app, self.message)[0].text, 'Hello')
        self.app.render_messages.assert_called_with(False)

    def test_pending_empty_failed_or_disabled_translation_keeps_original(self):
        for value in (None, types.TextWithEntities('', []), types.TextWithEntities('  ', [])):
            self.app.translated[self.key] = value
            self.assertEqual(presentation(self.app, self.message), (self.message, None, ''))
        self.app.translated[self.key] = types.TextWithEntities('Hello', [])
        self.app.chat_translations.clear()
        self.assertIsNone(presentation(self.app, self.message)[1])

    def test_translated_entities_use_new_offsets_without_unicode_emoji_duplicate(self):
        self.app.translated[self.key] = types.TextWithEntities('Hello 😀 site', [
            types.MessageEntityCustomEmoji(6, 2, 99),
            types.MessageEntityTextUrl(9, 4, 'https://example.com')])
        body, _, _ = presentation(self.app, self.message)
        segments = list(display_segments(body))
        self.assertIn(99, segments)
        self.assertNotIn('😀', ''.join(v for v in segments if isinstance(v, str)))
        runs = list(rich_runs(body))
        self.assertIn(('◇', None, 99), runs)
        self.assertTrue(any(url == 'https://example.com' for _, url, _ in runs))
        self.assertEqual(self.message.entities, ())

    def test_stale_controls_cannot_toggle_other_account_chat_language_or_edited_message(self):
        for attr, value in [('ui_account', 'b'), ('active', 43), ('selection_kind', 'messages')]:
            original = getattr(self.app, attr, None)
            setattr(self.app, attr, value)
            toggle_original(self.app, self.key)
            self.app.render_messages.assert_not_called()
            setattr(self.app, attr, original)
        self.app.chat_translations['a:42'] = 'fr'
        toggle_original(self.app, self.key)
        self.app.chat_translations['a:42'] = 'en'
        self.message.text = 'Hola editado'
        toggle_original(self.app, self.key)
        self.app.render_messages.assert_not_called()

    def test_classic_renderer_passes_only_translated_body_to_content_renderer(self):
        app = self.app
        self.message.reply_to_id = None
        self.message.media = None
        app.history = Mock()
        app.history.mark_names.return_value = ()
        app.history.tag_names.return_value = ()
        app.history.yview.return_value = (0, 1)
        app.history.index.return_value = '1.0'
        app.text_display = lambda text, *args: text
        app.message_selected = lambda _: False
        app.insert_message_content = Mock()
        app.schedule_translations = Mock()
        with patch('tg_ascii.translated_view.insert_button') as button:
            Desktop.render_messages(app, False)
        self.assertEqual(app.insert_message_content.call_args.args[0].text, 'Hello')
        button.assert_called_once_with(app, self.key, 'Show original')
        self.assertEqual(app.messages[0].text, 'Hola')

    def test_classic_toggle_button_calls_handler_and_is_destroyed_on_repaint(self):
        self.app.history = Mock()
        clear_buttons(self.app)
        with patch('tkinter.ttk.Button') as button:
            insert_button(self.app, self.key, 'Show original')
            button.call_args.kwargs['command']()
            self.assertEqual(presentation(self.app, self.message)[2], 'Show translation')
            clear_buttons(self.app)
            button.return_value.destroy.assert_called_once()

    def test_bubble_renderer_does_not_append_original_beside_translation(self):
        canvas = Mock()
        canvas.app = self.app
        canvas._bindings = []
        canvas._nodes = {}
        canvas._job = None
        canvas.generation = 0
        canvas.yview.return_value = (0, 1)
        canvas.winfo_width.return_value = 800
        canvas.winfo_height.return_value = 500
        canvas.bbox.return_value = (0, 0, 100, 50)
        self.app.font_family = 'Menlo'
        self.app.preferences = NS(values={'theme': 'dark', 'font_size': 12, 'inline_media': False, 'advanced_features': {'chat_translation': True}})
        self.app.message_accent = lambda _: ['#00ff00']
        self.app.text_display = lambda value, *args: value
        self.app.draw_bubble_wallpaper = Mock()
        self.message.reply_to_id = None
        self.message.media = None
        fake_font = Mock()
        fake_font.measure.side_effect = lambda value: len(value) * 7
        fake_font.metrics.return_value = 17
        with patch('tg_ascii.bubbles.font.Font', return_value=fake_font):
            BubbleView.render(canvas, [self.message], False)
        texts = [call.kwargs.get('text', '') for call in canvas.create_text.call_args_list]
        self.assertIn('Hello', texts)
        self.assertNotIn('Hola', texts)
        self.assertTrue(canvas.interactive.called)


if __name__ == '__main__': unittest.main()
