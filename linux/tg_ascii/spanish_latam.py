"""Latin American Spanish (es-419), derived from the app's Spanish text (1.5.4).

The interface is already written in neutral Spanish with "tú", so the
differences are a short list of everyday words (computadora, celular,
video, …). The conversion runs on the Spanish string the app was about to
show, so every label — including future ones — is covered, and is cached.

Format fields ({name}), links, @usernames, /commands and product names are
never touched. It only applies to interface text, never to messages.
"""
from functools import lru_cache
import re

CODE = 'es-419'
NAME = 'Español (Latinoamérica)'

# lower-case word → replacement (case is copied from the original word).
WORDS = {
    'ordenador': 'computadora', 'ordenadores': 'computadoras',
    'móvil': 'celular', 'móviles': 'celulares',
    'vídeo': 'video', 'vídeos': 'videos', 'videollamada': 'videollamada',
    'fichero': 'archivo', 'ficheros': 'archivos',
    'pulsa': 'presiona', 'pulsar': 'presionar', 'pulsas': 'presionas', 'pulsado': 'presionado',
    'pulsando': 'presionando', 'pulse': 'presione',
    'coger': 'tomar', 'coge': 'toma', 'cogido': 'tomado',
    'portátil': 'laptop', 'portátiles': 'laptops',
    'ratón': 'mouse', 'auriculares': 'audífonos',
    'pincha': 'haz clic', 'pinchar': 'hacer clic',
    'vuestro': 'su', 'vuestra': 'su', 'vuestros': 'sus', 'vuestras': 'sus',
    'zumo': 'jugo', 'gafas': 'lentes', 'billete': 'boleto', 'billetes': 'boletos',
    'aparcar': 'estacionar', 'conducir': 'manejar',
    # vosotros → ustedes (the app rarely addresses several people)
    'tenéis': 'tienen', 'podéis': 'pueden', 'queréis': 'quieren', 'estáis': 'están',
    'sois': 'son', 'habéis': 'han', 'hacéis': 'hacen', 'vais': 'van',
}
# Whole phrases first (they change gender or more than one word).
PHRASES = (
    (re.compile(r'\bel ordenador\b', re.I), 'la computadora'),
    (re.compile(r'\bun ordenador\b', re.I), 'una computadora'),
    (re.compile(r'\beste ordenador\b', re.I), 'esta computadora'),
    (re.compile(r'\bdel ordenador\b', re.I), 'de la computadora'),
    (re.compile(r'\bal ordenador\b', re.I), 'a la computadora'),
    (re.compile(r'\btu ordenador\b', re.I), 'tu computadora'),
    (re.compile(r'\blos ordenadores\b', re.I), 'las computadoras'),
    (re.compile(r'\bel portátil\b', re.I), 'la laptop'),
    (re.compile(r'\bun portátil\b', re.I), 'una laptop'),
    (re.compile(r'\bel ratón\b', re.I), 'el mouse'),
    (re.compile(r'\bpincha en\b', re.I), 'haz clic en'),
)
_PROTECTED = re.compile(r'(\{[^{}]*\}|https?://\S+|tg://\S+|@[\w]+|/[\w-]+|`[^`]*`|'
                        r'\b(?:TG-ASCII|Tg-As|Telegram|Premium|Windows|macOS|Linux|Android|iOS)\b)')
_WORD = re.compile(r'[^\W\d_]+', re.UNICODE)


def _case_like(original, value):
    if original.isupper() and len(original) > 1:
        return value.upper()
    if original[0].isupper():
        return value[0].upper() + value[1:]
    return value


def _phrase(text):
    for pattern, replacement in PHRASES:
        text = pattern.sub(lambda match, replacement=replacement: _case_like(match.group(), replacement), text)
    return text


def _word(match):
    original = match.group()
    value = WORDS.get(original.lower())
    return original if value is None else _case_like(original, value)


@lru_cache(maxsize=8192)
def latam(text):
    """Spanish (Spain) interface text → Latin American Spanish."""
    if not isinstance(text, str) or not text:
        return text
    pieces = _PROTECTED.split(text)
    for index in range(0, len(pieces), 2):
        pieces[index] = _WORD.sub(_word, _phrase(pieces[index]))
    return ''.join(pieces)
