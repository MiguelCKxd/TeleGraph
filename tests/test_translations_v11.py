"""New dialogs must remain usable in every primary UI language."""
import ast
from collections import Counter
from pathlib import Path
from string import Formatter
import unittest

from tg_ascii.advanced_features import FEATURES
from tg_ascii.i18n import TRANSLATIONS
from tg_ascii.translations import CATALOGUES
from tg_ascii.translations_v11 import KEYS


class ReleaseTranslationTests(unittest.TestCase):
    def test_formatted_prompts_preserve_each_placeholder_in_every_language(self):
        formatter = Formatter()
        self.assertEqual(len(KEYS), len(set(KEYS)))
        for key in KEYS:
            fields = Counter(item[1] for item in formatter.parse(key) if item[1] is not None)
            for language in ('es', 'ru', 'pl', 'ca', 'ca-valencia', 'uk'):
                text = CATALOGUES[language][key]
                actual = Counter(item[1] for item in formatter.parse(text) if item[1] is not None)
                self.assertEqual(actual, fields, (language, key))
                self.assertTrue(text.strip(), (language, key))

    def test_dynamic_feature_and_dialog_labels_have_real_catalogue_entries(self):
        labels = {label for pair in FEATURES.values() for label in pair}
        path = Path(__file__).resolve().parents[1] / 'tg_ascii' / 'desktop_advanced.py'
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, 'id', getattr(node.func, 'attr', ''))
            index = {'AdvancedDialog': 2, 'field': 1, 'button': 1,
                     '_check': 1, '_entity_field': 2}.get(name)
            if index is not None and len(node.args) > index:
                labels.update(child.value for child in ast.walk(node.args[index])
                              if isinstance(child, ast.Constant) and isinstance(child.value, str))
        for label in labels:
            english = TRANSLATIONS.get(label, label)
            for language in ('es', 'ru', 'pl', 'ca', 'ca-valencia', 'uk'):
                self.assertIn(english, CATALOGUES[language], (language, label))
