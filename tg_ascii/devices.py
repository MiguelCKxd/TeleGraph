"""Active Telegram sessions of one account ("Devices"), shared by desktop and mobile.

Lists the authorizations Telegram reports for the signed-in account, ends one
of them or every other one, and accepts a login QR (tg://login?token=...) the
way Telegram's own apps do when they scan the code shown by a new device.
Nothing here stores session data; it only calls the account's own client.
"""
import base64
from urllib.parse import parse_qs, urlsplit

from telethon import functions

TTL_CHOICES = (7, 30, 90, 183, 365)


def _text(value):
    return str(value or '').strip()


def session_json(item):
    """One authorization as plain data (hash as text: it does not fit in JS numbers)."""
    date = lambda value: int(value.timestamp()) if value else 0
    place = ', '.join(part for part in (_text(item.region), _text(item.country)) if part)
    return {
        'hash': str(item.hash),
        'current': bool(item.current),
        'device': _text(item.device_model),
        'platform': _text(item.platform),
        'system': _text(item.system_version),
        'app': ' '.join(part for part in (_text(item.app_name), _text(item.app_version)) if part),
        'official': bool(getattr(item, 'official_app', False)),
        'ip': _text(item.ip),
        'place': place,
        'active': date(item.date_active),
        'created': date(item.date_created),
        'pending': bool(getattr(item, 'password_pending', False)),
        'calls': not bool(getattr(item, 'call_requests_disabled', False)),
        'secret_chats': not bool(getattr(item, 'encrypted_requests_disabled', False)),
    }


async def list_sessions(client):
    """Current session first, then the most recently active."""
    result = await client(functions.account.GetAuthorizationsRequest())
    items = [session_json(item) for item in result.authorizations]
    items.sort(key=lambda item: (not item['current'], -item['active']))
    return {'sessions': items, 'ttl_days': int(getattr(result, 'authorization_ttl_days', 0) or 0)}


async def end_session(client, session_hash):
    session_hash = int(session_hash)
    if session_hash == 0:
        raise ValueError('current session')
    return bool(await client(functions.account.ResetAuthorizationRequest(hash=session_hash)))


async def end_other_sessions(client):
    return bool(await client(functions.auth.ResetAuthorizationsRequest()))


async def set_session_ttl(client, days):
    days = int(days)
    if days not in TTL_CHOICES:
        raise ValueError(days)
    return bool(await client(functions.account.SetAuthorizationTTLRequest(authorization_ttl_days=days)))


async def set_session_flags(client, session_hash, calls=None, secret_chats=None):
    """Whether that device may receive calls / new secret chats."""
    kwargs = {'hash': int(session_hash)}
    if calls is not None:
        kwargs['call_requests_disabled'] = not calls
    if secret_chats is not None:
        kwargs['encrypted_requests_disabled'] = not secret_chats
    return bool(await client(functions.account.ChangeAuthorizationSettingsRequest(**kwargs)))


def login_token(url):
    """The token inside a Telegram login QR, or None for any other text."""
    text = _text(url)
    parts = urlsplit(text)
    if parts.scheme.lower() != 'tg' or parts.netloc.lower() != 'login':
        return None
    token = parse_qs(parts.query).get('token', [''])[0]
    if not token:
        return None
    try:
        return base64.urlsafe_b64decode(token + '=' * (-len(token) % 4))
    except (ValueError, TypeError):
        return None


async def accept_login(client, url):
    """Sign the device that shows this QR in with this account."""
    token = login_token(url)
    if token is None:
        raise ValueError('not a Telegram login code')
    authorization = await client(functions.auth.AcceptLoginTokenRequest(token=token))
    return session_json(authorization)
