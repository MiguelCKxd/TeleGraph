import unittest
from tg_ascii.translations_playful import build_catalogue, render_variant, LANGUAGES
from tg_ascii.translations_extra import fields

class PlayfulLocalesTests(unittest.TestCase):
    def test_regional_voices_are_distinct_and_opt_in(self):
        self.assertEqual(render_variant('Settings', 'Ajustes', 'es-x-chileno'), 'Ajustes, po')
        self.assertEqual(render_variant('Settings', 'Ajustes', 'es-x-andaluz'), 'Ajujteh')
        with self.assertRaises(ValueError):
            render_variant('Settings', 'Ajustes', 'es')

    def test_placeholders_links_commands_and_technical_words_are_preserved(self):
        source = 'El archivo {file} para {username}: https://example.com/estado /guardar Telegram Windows API ID Ctrl+Enter @todos'
        for code in LANGUAGES:
            output = render_variant('test', source, code)
            self.assertEqual(fields(output), fields(source))
            for exact in ('https://example.com/estado', '/guardar', 'Telegram', 'Windows', 'API ID', 'Ctrl+Enter', '@todos'):
                self.assertIn(exact, output)

    def test_purchase_values_whitespace_and_lines_remain_intact(self):
        source = ' Confirmar compra: {amount} Telegram Stars\nDestinatario: {recipient}\n\n¿Quieres comprarlo? '
        for code in LANGUAGES:
            output = build_catalogue({'purchase': source}, code)['purchase']
            self.assertTrue(output.startswith(' '))
            self.assertTrue(output.endswith(' '))
            self.assertEqual(output.count('\n'), 3)
            self.assertEqual(fields(output), {'amount', 'recipient'})
            self.assertIn('42', output.format(amount=42, recipient='User'))
