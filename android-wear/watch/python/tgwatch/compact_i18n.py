"""Interface strings for the shared forum modules in the standalone watch zip."""
import os

from tg_ascii.forum_labels import LABELS


def tr(value):
    language = os.environ.get('TGWATCH_LANGUAGE', 'en')
    return LABELS.get(language, LABELS['en']).get(value, value)
