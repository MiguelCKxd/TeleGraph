"""Captions on the round Wear OS screen must fit inside its width."""
import textwrap
from unittest import TestCase

from tg_ascii_watch.app import BUTTON_INSET, round_wrap


class RoundScreenWrapTests(TestCase):
    def test_button_captions_leave_room_for_the_button_padding(self):
        caption = round_wrap('Entrar con código QR', 11, BUTTON_INSET)
        self.assertGreater(caption.count('\n'), 0)
        self.assertTrue(all(len(line) <= int(250 / 11) - BUTTON_INSET for line in caption.split('\n')))
        self.assertEqual(round_wrap('OK', 11, BUTTON_INSET), 'OK')

    def test_labels_wrap_as_before(self):
        text = 'Te hemos enviado el código a Telegram o por SMS.\n\nSegunda línea'
        for size in (10, 11, 13, 20):
            width = max(12, int(250 / size))
            old = '\n'.join(textwrap.fill(line, width) if line else '' for line in text.split('\n'))
            self.assertEqual(round_wrap(text, size), old)
