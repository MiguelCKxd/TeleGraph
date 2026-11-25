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


class WatchTypefaceTests(TestCase):
    def test_every_phone_font_has_a_wear_family(self):
        import ast
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / 'src/tg_ascii_mobile/core.py').read_text(encoding='utf-8')
        fonts = next(ast.literal_eval(node.value) for node in ast.walk(ast.parse(source))
                     if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', None) == 'FONTS')
        watch = (Path(__file__).resolve().parents[1] / 'src/tg_ascii_watch/app.py').read_text(encoding='utf-8')
        tree = ast.parse(watch)
        values = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
                  if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', None) in ('TYPEFACES', 'ANDROID_FAMILIES')}
        self.assertEqual(set(fonts) - {''} - set(values['TYPEFACES']), set())
        self.assertTrue(set(values['TYPEFACES'].values()) <= {'monospace', 'sans-serif', 'serif', 'cursive'})
        self.assertTrue(set(values['ANDROID_FAMILIES']) <= set(fonts))
