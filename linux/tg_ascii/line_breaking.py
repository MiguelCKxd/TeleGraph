"""What happens to a word that does not fit at the end of a line (1.4.1).

Settings › Appearance › Line breaks:

- ``auto``     exactly as before 1.4.1 (bubbles cut anywhere; classic text
               keeps whole words). Default.
- ``word``     the whole word moves to the next line.
- ``char``     the word is cut where the line ends, no marker; lines stay
               full (justified with the app's monospace fonts).
- ``hyphen``   the word is cut where the line ends and a hyphen marks the
               break; lines stay full.
- ``syllable`` hyphen after the last syllable that fits, using the
               language's own hyphenation dictionary (Pyphen, LibreOffice
               patterns for ~70 languages).

Writing systems that do not hyphenate follow their own rules instead:
Chinese/Japanese (and kana/hangul runs without spaces) break between
characters with no marker; Arabic, Hebrew, Persian, Urdu… never hyphenate,
the whole word moves; Thai, Lao, Khmer, Myanmar break between clusters.
"""
from functools import lru_cache
import re
import unicodedata

from .text_layout import cluster_ends

MODES = ('auto', 'word', 'char', 'hyphen', 'syllable')
HYPHEN = '-'

# App language → hyphenation dictionary (Pyphen names).
DICTIONARIES = {
    'es': 'es', 'es-419': 'es', 'en': 'en_US', 'fr': 'fr', 'de': 'de_DE', 'it': 'it_IT', 'pt': 'pt_PT', 'pt-BR': 'pt_BR',
    'ca': 'ca', 'nl': 'nl_NL', 'pl': 'pl_PL', 'ru': 'ru_RU', 'uk': 'uk_UA', 'cs': 'cs_CZ', 'sk': 'sk_SK',
    'sv': 'sv', 'da': 'da_DK', 'nb': 'nb_NO', 'no': 'nb_NO', 'fi': 'fi_FI', 'hu': 'hu_HU', 'ro': 'ro_RO',
    'el': 'el_GR', 'bg': 'bg', 'hr': 'hr_HR', 'sr': 'sr', 'sl': 'sl_SI', 'lt': 'lt_LT', 'lv': 'lv_LV',
    'et': 'et_EE', 'tr': 'tr_TR', 'id': 'id_ID', 'ms': 'id_ID', 'eu': 'eu', 'gl': 'gl', 'is': 'is',
    'ga': 'ga_IE', 'cy': 'cy', 'be': 'be_BY', 'mn': 'mn_MN', 'af': 'af_ZA', 'sq': 'sq_AL', 'kk': 'ru_RU',
    'uz': 'uz_UZ', 'az': 'tr_TR', 'vi': None, 'hi': 'hi_IN', 'bn': 'bn_IN', 'ta': 'ta_IN', 'te': 'te_IN',
}
# Words of another script than the app language use that script's dictionary.
SCRIPT_FALLBACK = {'latin': 'en_US', 'cyrillic': 'ru_RU', 'greek': 'el_GR', 'devanagari': 'hi_IN'}
SCRIPT_OF_LANGUAGE = {'ru': 'cyrillic', 'uk': 'cyrillic', 'bg': 'cyrillic', 'sr': 'cyrillic', 'be': 'cyrillic',
                      'mn': 'cyrillic', 'kk': 'cyrillic', 'el': 'greek', 'hi': 'devanagari'}


def mode(values):
    value = (values or {}).get('line_breaking', 'auto')
    return value if value in MODES else 'auto'


def script(word):
    """The writing system that decides how this word may be broken."""
    for char in word:
        code = ord(char)
        if char.isspace() or not char.isalnum():
            continue
        if (0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF or 0x3040 <= code <= 0x30FF
                or 0xAC00 <= code <= 0xD7AF or 0xF900 <= code <= 0xFAFF or 0x20000 <= code <= 0x2FFFF):
            return 'cjk'
        if 0x0590 <= code <= 0x08FF or 0xFB1D <= code <= 0xFDFF or 0xFE70 <= code <= 0xFEFF:
            return 'rtl'
        if 0x0E00 <= code <= 0x0EFF or 0x1000 <= code <= 0x109F or 0x1780 <= code <= 0x17FF:
            return 'cluster'
        if 0x0400 <= code <= 0x052F:
            return 'cyrillic'
        if 0x0370 <= code <= 0x03FF:
            return 'greek'
        if 0x0900 <= code <= 0x097F:
            return 'devanagari'
        if 'LATIN' in unicodedata.name(char, ''):
            return 'latin'
        return 'other'
    return 'none'


def effective(selected, word):
    """The mode applied to this word after its script's own rules."""
    kind = script(word)
    if selected in ('hyphen', 'syllable'):
        if kind in ('cjk', 'cluster'):
            return 'char'
        if kind == 'rtl':
            return 'word'
        if selected == 'syllable' and kind not in ('latin', 'cyrillic', 'greek', 'devanagari'):
            return 'hyphen'
    if selected == 'word' and kind == 'cjk':
        return 'char'  # CJK has no spaces: "words" are single characters.
    return selected


@lru_cache(maxsize=16)
def _dictionary(name):
    if not name:
        return None
    try:
        import pyphen
        if name not in pyphen.LANGUAGES:
            name = pyphen.language_fallback(name)
            if not name:
                return None
        return pyphen.Pyphen(lang=name)
    except Exception:
        return None


def dictionary_for(word, language):
    kind = script(word)
    if SCRIPT_OF_LANGUAGE.get(language, 'latin') == kind:
        return _dictionary(DICTIONARIES.get(language, language))
    return _dictionary(SCRIPT_FALLBACK.get(kind))


def syllable_points(word, language):
    """Offsets where ``word`` may take a hyphen, from the language's patterns."""
    letters = re.match(r'^(\W*)(.*?)(\W*)$', word, re.S)
    lead, core = letters.group(1), letters.group(2)
    if len(core) < 4:
        return []
    found = dictionary_for(core, language)
    if found is not None:
        try:
            return [len(lead) + point for point in found.positions(core)]
        except Exception:
            pass
    return [len(lead) + point for point in _vowel_points(core)]


def _vowel_points(word):
    """Fallback without a dictionary: break between consonant clusters (V-CV)."""
    vowels = set('aeiouáéíóúàèìòùâêîôûäëïöüyAEIOUÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÄËÏÖÜY')
    points = []
    for index in range(2, len(word) - 1):
        if word[index] not in vowels and word[index - 1] in vowels and word[index + 1] in vowels:
            points.append(index)
    return points


def _fit(paragraph, start, ends, cluster, available, measure, suffix=''):
    """How many clusters from ``cluster`` fit in ``available`` (bisection)."""
    remaining = len(ends) - cluster
    low, high = 0, remaining
    while low < high:
        mid = (low + high + 1) // 2
        if measure(paragraph[start:ends[cluster + mid - 1]] + suffix) <= available:
            low = mid
        else:
            high = mid - 1
    return low


def layout(text, x, y, left, right, line, measure, selected, language):
    """Same contract as bubbles.layout_text_run, with the chosen break mode."""
    chunks = []
    for index, paragraph in enumerate(text.split('\n')):
        if index:
            x = left
            y += line
        tokens = [token for token in re.split(r'(\s+)', paragraph) if token]
        buffer, start_x = '', x

        def flush():
            nonlocal buffer
            if buffer:
                chunks.append((start_x, y, buffer))
                buffer = ''

        def newline():
            nonlocal x, y, start_x
            flush()
            x = start_x = left
            y += line

        for token in tokens:
            if token.isspace():
                width = measure(token)
                if x + width <= right:
                    buffer += token
                    x += width
                elif x > left:
                    newline()  # Spaces at the end of a line are not drawn.
                continue
            word = token
            while word:
                width = measure(word)
                available = right - x
                if width <= available:
                    buffer += word
                    x += width
                    break
                rule = effective(selected, word)
                if rule == 'word':
                    if x > left:
                        newline()
                        continue
                    rule = 'char'  # Longer than a whole line: cut it anyway.
                ends = cluster_ends(word)
                if rule == 'syllable':
                    points = [point for point in syllable_points(word, language) if 0 < point < len(word)]
                    fitting = [point for point in points if measure(word[:point] + HYPHEN) <= available]
                    if fitting:
                        point = fitting[-1]
                        buffer += word[:point] + HYPHEN
                        word = word[point:]
                        newline()
                        continue
                    if x > left:
                        newline()
                        continue
                    rule = 'hyphen'  # No syllable fits a whole line.
                if rule == 'hyphen':
                    count = _fit(word, 0, ends, 0, available, measure, HYPHEN)
                    # Keep at least two clusters on each side when possible.
                    if count >= 2 and len(ends) - count >= 1:
                        stop = ends[count - 1]
                        mark = HYPHEN if word[stop - 1].isalnum() and word[stop].isalnum() else ''
                        buffer += word[:stop] + mark
                        word = word[stop:]
                        newline()
                        continue
                    if x > left:
                        newline()
                        continue
                    rule = 'char'
                # char: fill the line exactly, no marker.
                count = _fit(word, 0, ends, 0, available, measure)
                if not count:
                    if x > left:
                        newline()
                        continue
                    count = 1
                stop = ends[count - 1]
                buffer += word[:stop]
                x += measure(word[:stop])
                word = word[stop:]
                if word:
                    newline()
        flush()
    return chunks, x, y


def text_wrap(values):
    """Tk Text widgets only know 'word' and 'char' wrapping."""
    selected = mode(values)
    return 'char' if selected in ('char', 'hyphen') else 'word'


def needs_canvas(values):
    """Hyphenated modes are drawn by the canvas chat view (Text cannot hyphenate)."""
    return mode(values) in ('hyphen', 'syllable')


def apply_text_widget(app, widget):
    """Plain Tk Text widgets: 'auto' keeps each widget's own wrap."""
    try:
        values = app.preferences.values
        if mode(values) != 'auto':
            widget.configure(wrap=text_wrap(values))
    except Exception:
        pass
