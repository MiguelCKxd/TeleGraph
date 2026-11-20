"""Desktop language resources and persistence, with no account or GUI access."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tg_ascii import i18n
from tg_ascii.preferences import Preferences
from tg_ascii.translations import CATALOGUES
from tg_ascii.translations_extra import EXTRA_LANGUAGES, fields, load_catalogues
from tg_ascii.translations_extended import NEW_LANGUAGES, load_catalogues as load_extended

ALL_ADDITIONAL_LANGUAGES = {**EXTRA_LANGUAGES, **NEW_LANGUAGES}


class LocaleTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language('en')

    def test_all_requested_languages_have_complete_catalogues(self):
        self.assertEqual(len(i18n.LANGUAGES), 35)  # 1.5.4: + es-419
        keys = set(CATALOGUES['ru'])
        for language in ALL_ADDITIONAL_LANGUAGES:
            with self.subTest(language=language):
                self.assertEqual(set(CATALOGUES[language]), keys)
                for key, translated in CATALOGUES[language].items():
                    self.assertTrue(translated.strip())
                    self.assertEqual(fields(key), fields(translated), key)
                    self.assertEqual(key[:len(key)-len(key.lstrip())], translated[:len(translated)-len(translated.lstrip())])
                    self.assertEqual(key[len(key.rstrip()):], translated[len(translated.rstrip()):])

    def test_spanish_source_and_english_source_use_same_translations(self):
        for language in ALL_ADDITIONAL_LANGUAGES:
            i18n.set_language(language)
            self.assertEqual(i18n.tr('Ajustes'), i18n.tr('Settings'))
            self.assertNotEqual(i18n.tr('Settings'), 'Settings')
            self.assertNotEqual(i18n.tr('Your phone number'), 'Your phone number')
            self.assertNotEqual(i18n.tr('Install release ZIP'), 'Install release ZIP')

    def test_preferences_round_trip_all_languages_and_preserve_other_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            prefs = Preferences(directory)
            self.assertEqual(prefs.values['language'], 'en')
            for language in i18n.LANGUAGES:
                prefs.save({'language': language, 'font_size': 14})
                restored = Preferences(directory)
                self.assertEqual(restored.values['language'], language)
                self.assertEqual(restored.values['font_size'], 14)
                self.assertFalse(restored.values['ascii_text'])

    def test_default_is_english_not_os_locale(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(i18n.detect_language(), 'en')
        self.assertEqual(Preferences.validated({'language': 'invalid'})['language'], 'en')

    def test_non_latin_strings_survive_render_translation(self):
        for code, expected in [('zh-Hans', '设置'), ('ja', '設定'), ('ko', '설정')]:
            i18n.set_language(code)
            self.assertEqual(i18n.tr('Settings'), expected)

    def test_multiline_payment_prompts_preserve_layout_and_values(self):
        key = '{title}\nRecipient: {recipient}\nTotal: {amount} Telegram Stars\n\nConfirm this purchase?'
        for language in ALL_ADDITIONAL_LANGUAGES:
            with self.subTest(language=language):
                translated = CATALOGUES[language][key]
                self.assertEqual(translated.count('\n'), key.count('\n'))
                self.assertNotIn(r'\n', translated)
                result = translated.format(title='Gift', recipient='Synthetic recipient', amount=123)
                self.assertIn('Synthetic recipient', result)
                self.assertIn('123', result)

    def test_staged_resources_load_without_original_source(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('release_locales', Path(__file__).resolve().parents[1] / 'tools/build_release.py')
        release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release)
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory) / 'stage'
            release.stage_source(stage, None)
            self.assertEqual(load_catalogues(stage / 'tg_ascii/locales'), load_catalogues())
            self.assertEqual(load_extended(stage / 'tg_ascii/locales'), load_extended())
            self.assertFalse((stage / 'tg_ascii/_app_credentials.py').exists())

    def test_rtl_languages_keep_logical_text_and_placeholders(self):
        for code in ('he', 'ar', 'ur'):
            i18n.set_language(code)
            self.assertTrue(i18n.is_rtl())
            key = 'Contacts synchronized: {count}'
            self.assertEqual(i18n.tr(key), CATALOGUES[code][key])
            self.assertIn('123', i18n.tr(key).format(count=123))
        self.assertFalse(i18n.is_rtl('es'))

    def test_new_catalogues_are_lazy_and_cache_is_bounded(self):
        from tg_ascii.translations_extended import _read
        _read.cache_clear()
        values = load_extended()
        self.assertEqual(_read.cache_info().currsize, 0)
        for code in values:
            self.assertTrue(values[code]['Settings'])
        self.assertLessEqual(_read.cache_info().currsize, 3)


if __name__ == '__main__':
    unittest.main()
