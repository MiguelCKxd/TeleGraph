"""Recently and frequently used emoji, standard and custom (all versions).

Telegram keeps recent and favourite *stickers* on its servers, but recent
emoji live on each device in the official apps: a list that starts with
Telegram's own defaults and reorders itself as you use emoji, the most used
rising and the least used dropping off. This keeps the same list per account,
next to the account's session (emoji_usage.json, 0600), and mixes in the
custom emoji of the account's recent reactions, which Telegram does keep
(messages.getRecentReactions). The emoji picker opens on it.
"""
import json
import math
import os
from pathlib import Path
import time

LIMIT = 200
HALF_LIFE = 14 * 86400  # a use counts half as much after two weeks
# Telegram Desktop's starting "Recently used" emoji, in its order.
DEFAULT_RECENT = ('😂', '😘', '❤️', '😍', '😊', '😁', '👍', '☺️', '😔', '😄', '😭', '💋', '😒', '😳', '😜',
                  '🙈', '😉', '😃', '😢', '😝', '😱', '😡', '😏', '😞', '😅', '😚', '🙊', '😌', '😀', '😋',
                  '😆', '👌', '😐', '😕')


def _path(backend):
    filename = getattr(getattr(getattr(backend, 'client', None), 'session', None), 'filename', None)
    if not filename:
        return None
    try:
        return Path(filename).parent / 'emoji_usage.json'
    except TypeError:
        return None


def _load(backend):
    cached = getattr(backend, '_emoji_usage', None)
    if cached is not None:
        return cached
    data = {}
    path = _path(backend)
    if path is not None:
        try:
            raw = json.loads(path.read_text('utf-8'))
            if not isinstance(raw, dict):
                raise ValueError('Invalid emoji history')
            for key, value in raw.items():
                key = str(key)
                if not key.startswith(('c:', 'e:')):
                    key = 'c:' + key  # first format: custom emoji ids only
                data[key] = (float(value[0]), float(value[1]))
        except (OSError, ValueError, TypeError, IndexError):
            data = {}
    backend._emoji_usage = data
    return data


def _save(backend, data):
    path = _path(backend)
    if path is None:
        return
    try:
        temporary = path.with_suffix('.tmp')
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump({str(key): list(value) for key, value in data.items()}, stream)
        os.replace(temporary, path)
    except OSError:
        pass


def score(entry, now=None):
    count, last = entry
    age = max(0.0, (now or time.time()) - last)
    return count * math.pow(0.5, age / HALF_LIFE) + (1.0 if age < 86400 else 0.0)


def standard_emoji(text, limit=50):
    """The standard emoji in a text (joined sequences, flags, skin tones, ...)."""
    import unicodedata
    found, index, text = [], 0, str(text or '')
    while index < len(text) and len(found) < limit:
        char = text[index]
        code = ord(char)
        if 0x1F1E6 <= code <= 0x1F1FF and index + 1 < len(text) and 0x1F1E6 <= ord(text[index + 1]) <= 0x1F1FF:
            found.append(text[index:index + 2]); index += 2; continue
        if unicodedata.category(char) == 'So' and (code >= 0x2190):
            end = index + 1
            while end < len(text):
                follower = ord(text[end])
                if follower in (0xFE0F, 0x20E3) or 0x1F3FB <= follower <= 0x1F3FF:
                    end += 1
                elif follower == 0x200D and end + 1 < len(text):
                    end += 2
                else:
                    break
            found.append(text[index:end]); index = end; continue
        index += 1
    return found


def note(backend, spans, text=''):
    """Record the emoji of a message being sent: custom emoji spans are
    (start, stop, document_id, alt) as for custom_entities; standard emoji are
    taken from the text (outside the custom emoji)."""
    keys = ['c:%d' % int(span[2]) for span in spans or () if len(span) > 2 and span[2]]
    plain = str(text or '')
    for span in sorted(spans or (), reverse=True):
        if len(span) > 1:
            plain = plain[:span[0]] + plain[span[1]:]
    keys += ['e:' + emoji for emoji in standard_emoji(plain)]
    if not keys:
        return
    data = _load(backend)
    now = time.time()
    for key in keys:
        count, _last = data.get(key, (0.0, now))
        data[key] = (count + 1.0, now)
    if len(data) > LIMIT:
        for ident in sorted(data, key=lambda key: score(data[key], now))[:len(data) - LIMIT]:
            del data[ident]
    _save(backend, data)


def frequent(backend, limit=60, standard=False):
    """Most used first: custom emoji ids, or (standard=True) items ('custom', id) /
    ('emoji', text) seeded with Telegram's default list."""
    data = _load(backend)
    now = time.time()
    if not standard:
        keys = [key for key in data if key.startswith('c:')]
        return [int(key[2:]) for key in sorted(keys, key=lambda key: score(data[key], now), reverse=True)[:limit]]
    scores = {key: score(value, now) for key, value in data.items()}
    for index, emoji in enumerate(DEFAULT_RECENT):  # below anything really used
        scores.setdefault('e:' + emoji, 0.5 * (1 - index / len(DEFAULT_RECENT)))
    ordered = sorted(scores, key=lambda key: scores[key], reverse=True)[:limit]
    return [('custom', int(key[2:])) if key.startswith('c:') else ('emoji', key[2:]) for key in ordered]


async def recent_items(backend, limit=80):
    """The mixed "Recently used" page: standard emoji as text, custom emoji as documents."""
    items = frequent(backend, limit, standard=True)
    identifiers = [value for kind, value in items if kind == 'custom']
    documents = {getattr(document, 'id', 0): document for document in (await backend.custom_emoji_documents(identifiers) if identifiers else [])}
    return [documents.get(value) if kind == 'custom' else value for kind, value in items
            if kind == 'emoji' or value in documents]


async def recent_documents(backend, limit=60):
    """Documents of the most used custom emoji, then those of recent reactions."""
    from telethon import functions, types
    identifiers = list(frequent(backend, limit))
    try:
        reactions = await backend.client(functions.messages.GetRecentReactionsRequest(limit=50, hash=0))
        for reaction in getattr(reactions, 'reactions', None) or ():
            if isinstance(reaction, types.ReactionCustomEmoji) and reaction.document_id not in identifiers:
                identifiers.append(reaction.document_id)
    except Exception:
        pass
    identifiers = identifiers[:limit]
    if not identifiers:
        return []
    documents = await backend.custom_emoji_documents(identifiers)
    order = {ident: index for index, ident in enumerate(identifiers)}
    return sorted(documents, key=lambda document: order.get(getattr(document, 'id', 0), len(order)))


async def favourite_stickers(backend):
    from telethon import functions
    result = await backend.client(functions.messages.GetFavedStickersRequest(hash=0))
    return list(getattr(result, 'stickers', None) or ())
