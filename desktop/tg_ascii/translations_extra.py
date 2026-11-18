"""Bundled desktop translations: offline, UTF-8, independent of Telegram Premium."""
import json
from pathlib import Path
from string import Formatter

EXTRA_LANGUAGES = {
    'zh-Hans': '简体中文', 'ko': '한국어', 'ja': '日本語',
    'it': 'Italiano', 'pt': 'Português', 'el': 'Ελληνικά',
    'eu': 'Euskara', 'gl': 'Galego', 'oc-aran': 'Aranés', 'an': 'Aragonés',
}
LOCALE_FILES = ['keys.json'] + [code + '.txt' for code in EXTRA_LANGUAGES]


def fields(text):
    return {field for _, field, _, _ in Formatter().parse(text) if field is not None}


def load_catalogues(directory=None):
    directory = Path(directory) if directory else Path(__file__).with_name('locales')
    keys = json.loads((directory / 'keys.json').read_text(encoding='utf-8'))
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate translation keys')
    catalogues = {}
    for code in EXTRA_LANGUAGES:
        entries = {}
        for row in (directory / (code + '.txt')).read_text(encoding='utf-8').splitlines():
            index, value = row.split('|', 1)
            # Rows stay on one physical line; prompts preserve their layout.
            value = value.replace(r'\n', '\n')
            index = int(index)
            if index in entries or not 0 <= index < len(keys) or not value.strip():
                raise ValueError(f'Invalid translation entry: {code}:{index}')
            key = keys[index]
            if fields(key) != fields(value):
                raise ValueError(f'Translation placeholders differ: {code}:{index}')
            leading = key[:len(key) - len(key.lstrip())]
            trailing = key[len(key.rstrip()):]
            entries[index] = leading + value.strip() + trailing
        if set(entries) != set(range(len(keys))):
            raise ValueError(f'Incomplete translation catalogue: {code}')
        catalogues[code] = {key: entries[index] for index, key in enumerate(keys)}
    return catalogues
