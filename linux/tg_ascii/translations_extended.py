"""Offline language packs loaded on demand; keep at most three packs in memory."""
from collections.abc import Mapping
from functools import lru_cache
import json
from pathlib import Path

NEW_LANGUAGES = {
    'ar': 'العربية', 'fr': 'Français', 'nl': 'Nederlands', 'fi': 'Suomi',
    'be': 'Беларуская', 'ro': 'Română', 'sv': 'Svenska', 'nb': 'Norsk bokmål',
    'hi': 'हिन्दी', 'th': 'ไทย', 'bn': 'বাংলা', 'fil': 'Filipino',
    'ur': 'اردو', 'vi': 'Tiếng Việt', 'he': 'עברית',
    'es-x-chileno': 'Chileno', 'es-x-andaluz': 'Andaluz',
}
RTL_LANGUAGES = frozenset(('ar', 'ur', 'he'))
LOCALE_FILES = [code + '.json' for code in NEW_LANGUAGES]

@lru_cache(maxsize=3)
def _read(path):
    try:
        values = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(values, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in values.items()):
            return {}
        return values
    except (OSError, ValueError):
        # A damaged optional pack leaves the English interface usable.
        return {}

class Catalogue(Mapping):
    def __init__(self, path):
        self.path = path

    def __getitem__(self, key):
        return _read(self.path)[key]

    def __iter__(self):
        return iter(_read(self.path))

    def __len__(self):
        return len(_read(self.path))

    def get(self, key, default=None):
        return _read(self.path).get(key, default)

def load_catalogues(directory=None):
    root = Path(directory) if directory is not None else Path(__file__).with_name('locales')
    return {code: Catalogue(root / (code + '.json')) for code in NEW_LANGUAGES}
