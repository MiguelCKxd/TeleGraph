"""Contact list search (1.4.0.1): name, @username or phone, accent-insensitive."""
import unicodedata

from telethon import utils


def _fold(value):
    text = unicodedata.normalize('NFKD', str(value or '')).casefold()
    return ''.join(ch for ch in text if not unicodedata.combining(ch))


def contact_matches(person, query):
    query = _fold(query).strip()
    if not query:
        return True
    digits = ''.join(ch for ch in query if ch.isdigit())
    names = [utils.get_display_name(person), getattr(person, 'first_name', ''), getattr(person, 'last_name', ''),
             getattr(person, 'username', '')] + [getattr(item, 'username', '') for item in getattr(person, 'usernames', None) or ()]
    haystack = ' '.join(_fold(name) for name in names if name)
    if all(part in haystack for part in query.lstrip('@').split()):
        return True
    phone = str(getattr(person, 'phone', '') or '')
    return bool(digits) and len(digits) >= 3 and digits in phone
