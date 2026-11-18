"""Pure, account-scoped UI capabilities from Telegram facts already in memory.

This is presentation policy, not authorization. Telegram still validates each
mutation. Missing administrative/full-profile facts never grant special rights.
"""
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace

from telethon import types as t


def _true(value, name):
    return getattr(value, name, None) is True


def _seconds(value):
    if isinstance(value, datetime): return value.timestamp()
    return value if type(value) in (int, float) else None


def _number(values, key, default):
    value = values.get(key, default)
    return value if type(value) in (int, float) and value >= 0 else default


def gift_action_available(record, action, *, config=None, date=None, now=None):
    """Gift ownership is checked by the caller; dates/status decide its actions."""
    if any(_true(record, name) for name in ('refunded', 'converted', 'upgraded')): return False
    now = datetime.now(UTC).timestamp() if now is None else _seconds(now)
    if action == 'visibility': return True
    if action == 'upgrade': return _true(record, 'can_upgrade')
    if action == 'transfer':
        available = _seconds(getattr(record, 'can_transfer_at', None))
        return isinstance(getattr(record, 'gift', None), t.StarGiftUnique) and (available is None or available <= now)
    if action == 'convert':
        duration = _number(config or {}, 'stargifts_convert_period_max', 0)
        received = _seconds(getattr(record, 'date', None) or date)
        return (bool(getattr(record, 'convert_stars', 0)) and not _true(record, 'auction_acquired')
                and received is not None and duration > 0 and 0 <= now - received < duration)
    return False


@dataclass(frozen=True)
class ChatCapabilities:
    kind: str = 'unknown'
    readable: bool = False
    writable: bool = False
    member: bool = False
    premium: bool = False
    creator: bool = False
    actions: frozenset = frozenset()
    entity: object = field(default=None, repr=False, compare=False)
    full: object = field(default=None, repr=False, compare=False)
    config: dict = field(default_factory=dict, repr=False, compare=False)

    def allows(self, action):
        aliases = {'send': 'send_text', 'poll': 'send_polls', 'location': 'send_locations',
                   'contact': 'send_contacts', 'article': 'send_articles',
                   'pin': 'pin_message', 'star_reaction': 'star_react'}
        return aliases.get(action, action) in self.actions

    @property
    def can_send(self): return self.allows('send')
    @property
    def can_poll(self): return self.allows('poll')
    @property
    def can_checklist(self): return self.allows('checklist')
    @property
    def can_gift(self): return self.allows('gift')
    @property
    def can_star_react(self): return self.allows('star_react')
    @property
    def can_article(self): return self.allows('article')
    @property
    def can_join(self): return self.allows('join')
    @property
    def can_leave(self): return self.allows('leave')
    @property
    def can_manage(self): return self.allows('manage')

    def allows_gift(self, gift, *, resale=False):
        if not self.allows('gift'): return False
        disallowed = getattr(self.full, 'disallowed_gifts', None)
        category = 'unique' if resale or isinstance(gift, t.StarGiftUnique) else 'limited' if _true(gift, 'limited') else 'unlimited'
        if _true(disallowed, 'disallow_' + category + '_stargifts'): return False
        if not resale and (_true(gift, 'sold_out') or _true(gift, 'auction')): return False
        if _true(gift, 'require_premium') and not self.premium: return False
        return not (_true(gift, 'limited_per_user') and not getattr(gift, 'per_user_remains', 0))

    def allows_message(self, action, message, *, now=None):
        if not self.readable or type(getattr(message, 'id', None)) is not int or message.id <= 0:
            return False
        now = datetime.now(UTC).timestamp() if now is None else _seconds(now)
        outgoing = _true(message, 'outgoing') or _true(message, 'out')
        service = _true(message, 'service') or getattr(message, 'action', None) is not None
        media = getattr(message, 'media', None)
        kind = getattr(message, 'media_kind', '')
        date = _seconds(getattr(message, 'date', None))
        age = max(0, now - date) if date is not None else None
        admin = getattr(self.entity, 'admin_rights', None)
        own_edit = outgoing and self.writable
        admin_edit = self.creator or _true(admin, 'edit_messages')
        if action in ('reply', 'reply_message'): return not service and self.writable
        if action in ('forward', 'forward_message'):
            return not service and self.allows('forward') and not (_true(message, 'protected') or _true(message, 'noforwards'))
        if action in ('pin', 'pin_message'): return not service and self.allows('pin_message')
        if action in ('delete', 'delete_message'):
            if self.kind in ('self', 'user', 'bot', 'secret'): return True
            if self.kind == 'channel':
                return self.member and (self.creator or _true(admin, 'delete_messages') or outgoing and _true(admin, 'post_messages'))
            return self.member and (outgoing or self.creator or _true(admin, 'delete_messages'))
        if action in ('read_time', 'readtime'):
            return (self.kind == 'user' and outgoing and _true(message, 'read') and not service
                    and self.full is not None and not _true(self.full, 'read_dates_private') and age is not None
                    and age <= _number(self.config, 'pm_read_date_expire_period', 604800))
        if action in ('edit', 'edit_message', 'edit_article', 'edit_checklist'):
            if service or getattr(message, 'via_bot_id', None) or getattr(message, 'fwd_from', None) or _true(message, 'forwarded'): return False
            if not (own_edit or self.kind == 'channel' and admin_edit): return False
            if action in ('edit', 'edit_message') and kind in ('poll', 'checklist', 'location', 'contact', 'gift', 'article', 'sticker', 'voice', 'video_note'):
                return False
            if action == 'edit_article' and (kind != 'article' or not outgoing): return False
            if action == 'edit_checklist' and (kind != 'checklist' or not outgoing or not self.premium): return False
            unlimited = self.kind == 'self' or self.kind == 'channel' or self.kind == 'group' and (self.creator or _true(admin, 'pin_messages'))
            return unlimited or age is not None and age <= _number(self.config, 'edit_time_limit', 172800)
        if action == 'star_react': return not service and self.allows(action)
        if action in ('react', 'reaction'): return not service and self.allows('react')
        if action in ('vote', 'retract_vote', 'close_poll', 'append_poll_answer', 'delete_poll_answer', 'poll_voters'):
            if not isinstance(media, t.MessageMediaPoll): return False
            poll = media.poll
            if action == 'poll_voters': return _true(poll, 'public_voters')
            if poll.closed: return False
            if action == 'close_poll': return outgoing or _true(poll, 'creator') or self.creator or admin is not None
            if action in ('append_poll_answer', 'delete_poll_answer'):
                return self.allows('poll') and _true(poll, 'open_answers')
            chosen = any(_true(item, 'chosen') for item in media.results.results or ())
            if chosen and (poll.quiz or poll.revoting_disabled): return False
            if action == 'retract_vote' and not chosen: return False
            if poll.subscribers_only and not self.member: return False
            # A country restriction can be checked only against cached app config.
            return not (poll.countries_iso2 and self.config.get('phone_country_iso2') not in poll.countries_iso2)
        if action in ('toggle_checklist', 'append_checklist'):
            if not isinstance(media, t.MessageMediaToDo) or not self.writable: return False
            name = 'others_can_complete' if action == 'toggle_checklist' else 'others_can_append'
            return outgoing or _true(media.todo, name)
        return False


def capabilities_for(chat=None, *, entity=None, full=None, premium=False, self_id=None, config=None, now=None):
    """Compute capabilities without fetching entities, permissions or Premium."""
    config = dict(config) if isinstance(config, dict) else {}
    entity = entity if entity is not None else getattr(chat, 'entity', None)
    kind = getattr(chat, 'kind', 'unknown')
    ident = getattr(chat, 'id', getattr(entity, 'id', None))
    from .secret_chats import is_secret_peer
    if kind == 'secret' or is_secret_peer(ident):
        active = getattr(chat, 'member', None) is not False
        actions = {'read', 'delete_history', 'clear_history'}
        if active:
            actions.update(('send_text', 'send_photos', 'send_videos', 'send_docs',
                            'send_stickers', 'send_gifs', 'send_voices', 'send_audios'))
        return ChatCapabilities('secret', True, active, active, bool(premium), True,
                                frozenset(actions), None, None, config)
    if isinstance(entity, t.User): kind = 'bot' if entity.bot else 'user'
    elif isinstance(entity, t.Chat): kind = 'group'
    elif isinstance(entity, t.Channel): kind = 'group' if entity.megagroup or entity.gigagroup else 'channel'
    if ident is not None and ident == self_id or _true(entity, 'is_self'): kind = 'self'
    premium = premium is True
    known = isinstance(entity, (t.User, t.Chat, t.Channel)) and not _true(entity, 'min')
    forbidden = isinstance(entity, (t.ChatForbidden, t.ChannelForbidden, t.UserEmpty))
    unavailable = forbidden or _true(entity, 'deleted') or _true(entity, 'deactivated') or getattr(entity, 'migrated_to', None) is not None
    creator = _true(entity, 'creator')
    admin = getattr(entity, 'admin_rights', None) if known else None
    now = datetime.now(UTC).timestamp() if now is None else _seconds(now)
    personal = getattr(entity, 'banned_rights', None)
    expiry = _seconds(getattr(personal, 'until_date', None))
    if expiry is not None and 0 < expiry < now: personal = None
    default = getattr(entity, 'default_banned_rights', None) if not (creator or admin is not None) else None
    def banned(name): return _true(personal, name) or _true(default, name)
    member = (getattr(chat, 'member', None) is True or known and not _true(entity, 'left')) and not unavailable
    if _true(entity, 'left') or banned('view_messages'): member = False
    readable = kind in ('self', 'user', 'bot', 'group', 'channel') and not unavailable and not banned('view_messages')
    writable = readable and not _true(full, 'blocked') and not banned('send_messages')
    if kind in ('group', 'channel'): writable = writable and known and member
    if kind == 'channel': writable = writable and (creator or _true(admin, 'post_messages'))
    if kind == 'group' and _true(entity, 'gigagroup'): writable = writable and (creator or admin is not None)
    if (_true(entity, 'contact_require_premium') or _true(full, 'contact_require_premium')) and not premium: writable = False
    paid = getattr(full, 'send_paid_messages_stars', None) or getattr(entity, 'send_paid_messages_stars', None)
    if type(paid) in (int, float) and paid > 0 and kind != 'self': writable = False
    actions = set()
    if readable:
        actions.update(('read', 'delete_history'))
        if kind in ('self', 'user', 'bot', 'group'): actions.add('clear_history')
        if not (_true(entity, 'noforwards') or _true(full, 'noforwards_my_enabled') or _true(full, 'noforwards_peer_enabled')):
            actions.add('forward')
        if premium and not _true(full, 'translations_disabled'): actions.add('translate')
        if not isinstance(getattr(full, 'available_reactions', None), t.ChatReactionsNone) and not banned('send_reactions'):
            actions.add('react')
        if kind in ('self', 'user'): actions.add('wallpaper')
        if kind == 'channel' and _true(full, 'paid_reactions_available') and not banned('send_reactions'): actions.add('star_react')
        gifts_allowed = kind in ('self', 'user') or kind == 'channel' and _true(full, 'stargifts_available')
        if gifts_allowed and not config.get('stargifts_blocked') and not _true(full, 'blocked'): actions.add('gift')
        if kind == 'user' and not _true(full, 'blocked') and not _true(getattr(full, 'disallowed_gifts', None), 'disallow_premium_gifts'):
            actions.add('gift_premium')
    if readable and kind in ('group', 'channel'):
        if not member and not creator and isinstance(entity, t.Channel): actions.add('join')
        if member and not creator: actions.add('leave')
        if creator or admin is not None: actions.add('manage')
    if writable:
        if not banned('send_plain'): actions.update(('send_text', 'send_articles'))
        media_allowed = not banned('send_media')
        for category in ('photos', 'videos', 'docs', 'stickers', 'gifs', 'voices', 'audios', 'roundvideos'):
            if media_allowed and not banned('send_' + category): actions.add('send_' + category)
        if _true(full, 'voice_messages_forbidden'):
            actions.difference_update(('send_voices', 'send_roundvideos'))
        if media_allowed:
            actions.update(('send_contacts', 'send_locations'))
            if premium: actions.add('checklist')
        if media_allowed and not banned('send_polls') and kind != 'user': actions.add('send_polls')
        if kind != 'bot' and 'send_text' in actions: actions.add('schedule')
        if kind == 'bot': actions.add('bot_action')
    pin_private = kind == 'self' or kind in ('user', 'bot') and _true(full, 'can_pin_message')
    pin_channel = member and kind == 'channel' and (creator or _true(admin, 'edit_messages'))
    pin_group = member and kind == 'group' and (creator or _true(admin, 'pin_messages') or known and admin is None and not banned('pin_messages'))
    if readable and (pin_private or pin_channel or pin_group): actions.add('pin_message')
    return ChatCapabilities(kind, readable, writable, bool(member), premium, creator,
                            frozenset(actions), entity, full, config)


def account_premium(app):
    """Cached Premium for the account selected in this window, never a network check."""
    service = getattr(app, 'service', None)
    profile = getattr(getattr(service, 'backend', None), 'account_profile', None)
    premium = getattr(profile, 'premium', None)
    if type(premium) is bool: return premium
    entries = getattr(service, 'entries', {})
    entry = entries.get(getattr(app, 'ui_account', None), {}) if isinstance(entries, dict) else {}
    return isinstance(entry, dict) and entry.get('premium') is True


def chat_capabilities(app, peer=None, *, chat=None):
    """Read only this window's account backend; never call a client method."""
    peer = getattr(app, 'active', None) if peer is None else peer
    if peer is None: return ChatCapabilities()
    backend = getattr(getattr(app, 'service', None), 'backend', None)
    entities = getattr(backend, '_capability_entities', {})
    entity = entities.get(peer) if isinstance(entities, dict) else None
    # Real dialogs/updates populate this account-owned index. Do not scan the
    # whole dialog list for every visible message in the normal render path.
    if chat is None and entity is None:
        chat = next((item for item in getattr(app, 'chats', ()) if item.id == peer), None)
    if entity is None: entity = getattr(chat, 'entity', None)
    full_cache = getattr(backend, '_capability_full', {})
    full = full_cache.get(peer) if isinstance(full_cache, dict) else None
    profile = getattr(backend, 'account_profile', None)
    self_id = getattr(profile, 'user_id', None)
    from .secret_chats import is_secret_peer
    if chat is None:
        chat = SimpleNamespace(
            id=peer,
            kind='secret' if is_secret_peer(peer) else ('self' if peer == self_id else 'unknown'),
        )
    return capabilities_for(chat, entity=entity, full=full, premium=account_premium(app),
                            self_id=self_id, config=getattr(backend, '_capability_config', None))


def message_capabilities(app, message, peer=None):
    capabilities = chat_capabilities(app, peer)
    return MessageCapabilities(capabilities, message)


@dataclass(frozen=True)
class MessageCapabilities:
    chat: ChatCapabilities
    message: object = field(repr=False, compare=False)

    def allows(self, action): return self.chat.allows_message(action, self.message)
