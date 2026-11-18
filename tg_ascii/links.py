"""Validated browser/deep-link targets and UTF-16-aware Telegram entities."""
import re
from bisect import bisect_right
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlsplit

DOMAIN = r'(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}'
URL_PATTERN = re.compile(r'(?<![@\w])(?:https?://[^\s<>"\x00-\x1f]+|'+DOMAIN+r'(?:[/:?#][^\s<>"\x00-\x1f]*)?)', re.IGNORECASE)


def browser_url(value):
    value=value.strip()
    if value.lower().startswith(('www.','t.me/')): value='https://'+value
    if any(ord(c)<32 or c.isspace() for c in value): raise ValueError('Invalid URL')
    if '://' not in value and re.match(r'^'+DOMAIN+r'(?:[/:?#]|$)', value, re.IGNORECASE): value='https://'+value
    parsed=urlsplit(value)
    if parsed.scheme.lower() not in ('https','http') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Only public HTTP(S) links can be opened')
    return value


def detected_links(text):
    for match in URL_PATTERN.finditer(text):
        value=match.group().rstrip('.,;:!?')
        for opening,closing in (('(',')'),('[',']'),('{','}')):
            while value.endswith(closing) and value.count(closing)>value.count(opening): value=value[:-1]
        try: target=browser_url(value)
        except ValueError: continue
        yield match.start(),match.start()+len(value),target


@dataclass(frozen=True)
class LinkTarget:
    kind: str
    url: str = ''
    peer: str | int | None = None
    message_id: int | None = None
    value: str = ''
    profile: bool = False
    comment_id: int | None = None


_USERNAME = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{0,31}$')
_SLUG = re.compile(r'^[a-zA-Z0-9_-]{1,256}$')
_TELEGRAM = {'t.me', 'telegram.me', 'telegram.dog', 'www.t.me', 'www.telegram.me'}
_WEB_ROUTES = {'nft', 'auction', 'giftcode', 'invoice', 'premium', 'stars', 'boost', 'm',
               'socks', 'proxy', 'login', 'auth', 'confirmphone', 'contact', 'share', 'msg',
               'setlanguage', 'addtheme', 'addstyle', 'bg', 'iv', 'a', 'k', 'z', 'web', 'call'}


def _positive(value):
    if not isinstance(value, str) or not value.isascii() or not value.isdigit() or not 0 < int(value) < 2 ** 63:
        raise ValueError('Invalid Telegram identifier')
    return int(value)


def link_target(value):
    """Parse supported links without executing tg:// commands in another app."""
    if not isinstance(value, str): raise TypeError('Invalid link')
    value = value.strip()
    if not value or len(value) > 8192 or any(ord(char) < 32 or char.isspace() for char in value):
        raise ValueError('Invalid link')
    if value.startswith(('#', '$')) and re.fullmatch(r'[#\$]\w{1,256}', value, re.UNICODE):
        return LinkTarget('hashtag', value=value)
    if value.startswith('@') and _USERNAME.fullmatch(value[1:]):
        return LinkTarget('peer', peer=value[1:], profile=True)
    parsed = urlsplit(value)
    if parsed.scheme.lower() == 'tg':
        if parsed.username or parsed.password or parsed.port or parsed.netloc and parsed.path not in ('', '/'):
            raise ValueError('Invalid Telegram link')
        action = (parsed.netloc or parsed.path).strip('/').lower()
        query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=30)
        get = lambda key: query.get(key, [''])[0]
        if action == 'user': return LinkTarget('peer', peer=_positive(get('id')), profile=True)
        if action == 'resolve':
            peer = get('domain')
            if not _USERNAME.fullmatch(peer):
                phone = get('phone')
                if not re.fullmatch(r'\+?[0-9]{5,15}', phone): raise ValueError('Invalid Telegram username')
                peer = '+' + phone.lstrip('+')
            # Explicit bot/web-app commands are opened on Telegram's HTTPS page;
            # neither /start nor authentication tokens are executed by this parser.
            if any(key in query for key in ('start', 'startgroup', 'startchannel', 'startapp', 'game', 'attach', 'direct')):
                return LinkTarget('browser', url='https://t.me/' + peer + ('?' + parsed.query if parsed.query else ''))
            address = 'https://t.me/' + peer + ('/' + str(_positive(get('post'))) if get('post') else '')
            if get('comment'): address += '?comment=' + str(_positive(get('comment')))
            return LinkTarget('peer', url=address, peer=peer, message_id=_positive(get('post')) if get('post') else None,
                              profile='profile' in query, comment_id=_positive(get('comment')) if get('comment') else None)
        if action == 'privatepost':
            address = 'https://t.me/c/' + str(_positive(get('channel'))) + '/' + str(_positive(get('post')))
            if get('comment'): address += '?comment=' + str(_positive(get('comment')))
            return LinkTarget('peer', url=address, peer=-1_000_000_000_000 - _positive(get('channel')),
                              message_id=_positive(get('post')), comment_id=_positive(get('comment')) if get('comment') else None)
        if action in ('addstickers', 'addemoji'):
            if not _SLUG.fullmatch(get('set')): raise ValueError('Invalid sticker set')
            return LinkTarget('pack', value=get('set'), url='https://t.me/' + action + '/' + get('set'))
        if action in ('join', 'addlist'):
            token = get('invite' if action == 'join' else 'slug')
            if not _SLUG.fullmatch(token): raise ValueError('Invalid invite link')
            return LinkTarget('invite' if action == 'join' else 'folder', value=token,
                              url='https://t.me/' + ('+' if action == 'join' else 'addlist/') + token)
        raise ValueError('This Telegram link action is not supported. Open its HTTPS page in Telegram instead.')
    url = browser_url(value)
    parsed = urlsplit(url)
    host, path = parsed.hostname.lower(), parsed.path.strip('/')
    if host.endswith('.t.me') and host not in _TELEGRAM:
        username = host[:-5]
        if not _USERNAME.fullmatch(username) or username in _WEB_ROUTES:
            return LinkTarget('browser', url=url)
        path = username + ('/' + path if path else '')
        host = 't.me'
    if host not in _TELEGRAM: return LinkTarget('browser', url=url)
    parts = [unquote(part) for part in path.split('/') if part]
    query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=30)
    if not parts: return LinkTarget('browser', url=url)
    if any(key in query for key in ('start', 'startgroup', 'startchannel', 'startapp', 'game', 'attach', 'direct')):
        return LinkTarget('browser', url=url)
    first = parts[0]
    if first in ('addstickers', 'addemoji', 'addlist', 'joinchat') and len(parts) == 2:
        if not _SLUG.fullmatch(parts[1]): raise ValueError('Invalid Telegram link')
        return LinkTarget('pack' if first in ('addstickers', 'addemoji') else 'folder' if first == 'addlist' else 'invite',
                          value=parts[1], url=url)
    if first.startswith('+') and len(parts) == 1:
        token = first[1:]
        if re.fullmatch(r'[0-9]{5,15}', token): return LinkTarget('peer', peer=first, profile='profile' in query)
        if not _SLUG.fullmatch(token): raise ValueError('Invalid Telegram invitation')
        return LinkTarget('invite', value=token, url=url)
    comment = _positive(query['comment'][0]) if query.get('comment', [''])[0] else None
    if first == 'c' and len(parts) in (3, 4):
        return LinkTarget('peer', peer=-1_000_000_000_000 - _positive(parts[1]),
                          message_id=_positive(parts[-1]), comment_id=comment)
    if first in _WEB_ROUTES: return LinkTarget('browser', url=url)
    if _USERNAME.fullmatch(first) and 1 <= len(parts) <= 3:
        if len(parts) > 1:
            if not all(part.isascii() and part.isdigit() for part in parts[1:]): return LinkTarget('browser', url=url)
            return LinkTarget('peer', peer=first, message_id=_positive(parts[-1]), comment_id=comment)
        return LinkTarget('peer', peer=first, profile='profile' in query)
    return LinkTarget('browser', url=url)


def message_links(text, entities=()):
    """Python-index ranges; explicit Telegram entities take priority over regex."""
    from telethon import types as t
    entities = [entity for entity in entities or () if isinstance(entity, (
        t.MessageEntityTextUrl, t.MessageEntityUrl, t.MessageEntityMention,
        t.MessageEntityHashtag, t.MessageEntityCashtag, t.MessageEntityMentionName))
        and type(entity.offset) is int and type(entity.length) is int and entity.offset >= 0 and entity.length > 0]
    needed = {value for entity in entities for value in (entity.offset, entity.offset + entity.length)}
    positions, offset = {0: 0}, 0
    if needed:
        last = max(needed)
        for index, char in enumerate(text):
            offset += 2 if ord(char) > 0xffff else 1
            if offset in needed: positions[offset] = index + 1
            if offset >= last: break
    explicit = []
    for entity in entities or ():
        start, end = positions.get(entity.offset), positions.get(entity.offset + entity.length)
        if start is None or end is None or start >= end: continue
        content, target = text[start:end], None
        if isinstance(entity, t.MessageEntityTextUrl): target = entity.url
        elif isinstance(entity, (t.MessageEntityUrl, t.MessageEntityMention, t.MessageEntityHashtag, t.MessageEntityCashtag)): target = content
        elif isinstance(entity, t.MessageEntityMentionName): target = 'tg://user?id=' + str(entity.user_id)
        if target is None: continue
        try: link_target(target)
        except (ValueError, TypeError): continue
        explicit.append((start, end, target))
    # Telegram may combine style and link entities. Only clickable spans need
    # de-duplication; a sorted sweep avoids quadratic work on long articles.
    result = []
    for start, end, target in sorted(explicit, key=lambda item: (item[0], -item[1])):
        if not result or start >= result[-1][1]: result.append((start, end, target))
    starts = [item[0] for item in result]
    candidates = list(detected_links(text))
    for match in re.finditer(r'tg:(?://)?[^\s<>"\x00-\x1f]+', text, re.IGNORECASE):
        candidate = match.group().rstrip('.,;!')
        for opening, closing in (('(', ')'), ('[', ']'), ('{', '}')):
            while candidate.endswith(closing) and candidate.count(closing) > candidate.count(opening):
                candidate = candidate[:-1]
        try: link_target(candidate)
        except ValueError: continue
        candidates.append((match.start(), match.start() + len(candidate), candidate))
    candidates.extend((match.start(), match.end(), match.group()) for match in re.finditer(
        r'(?<![\w@])@[A-Za-z][A-Za-z0-9_]{0,31}\b|(?<!\w)[#\$]\w{1,256}', text, re.UNICODE))
    fallback, previous_end = [], -1
    for start, end, target in sorted(candidates, key=lambda item: (item[0], -item[1])):
        if start < previous_end: continue
        index = bisect_right(starts, start)
        if index and result[index - 1][1] > start or index < len(result) and result[index][0] < end: continue
        fallback.append((start, end, target)); previous_end = end
    return sorted(result + fallback)
