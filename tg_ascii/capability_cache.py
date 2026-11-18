"""Account-local permission snapshots from replies already requested by the UI."""
from collections import OrderedDict


def _rights(value):
    if value is None:
        return None
    return tuple(sorted(vars(value).items()))


def _signature(entity):
    return (type(entity), *(getattr(entity, key, None) for key in (
        'left', 'kicked', 'deactivated', 'deleted', 'creator', 'bot', 'is_self',
        'premium', 'broadcast', 'megagroup', 'join_to_send', 'noforwards',
        'paid_reactions_available', 'blocked', 'voice_messages_forbidden',
        'can_pin_message', 'contact_require_premium', 'send_paid_messages_stars',
        'translations_disabled', 'read_dates_private', 'stargifts_available',
        'phone_calls_available', 'phone_calls_private', 'video_calls_available')),
        *(_rights(getattr(entity, key, None)) for key in (
            'admin_rights', 'banned_rights', 'default_banned_rights',
            'disallowed_gifts', 'available_reactions', 'emojiset')))


def remember(backend, entity, full=None, *, notify=True):
    from telethon import types, utils
    if not isinstance(entity, (types.User, types.Chat, types.Channel,
                               types.ChatForbidden, types.ChannelForbidden)):
        return
    peer = utils.get_peer_id(entity)
    changed = False
    for name, value, limit in (('_capability_entities', entity, 2048),
                               ('_capability_full', full, 256)):
        if value is None:
            continue
        cache = getattr(backend, name, None)
        if cache is None:
            cache = OrderedDict()
            setattr(backend, name, cache)
        # A minimal entity must not erase known admin/banned rights.
        if name == '_capability_entities' and getattr(entity, 'min', False) and peer in cache:
            continue
        before = cache.get(peer)
        changed = changed or before is None or _signature(before) != _signature(value)
        cache[peer] = value
        cache.move_to_end(peer)
        while len(cache) > limit:
            cache.popitem(last=False)
    if notify and changed and getattr(backend, 'on_change', None):
        backend.on_change('capabilities', peer)


def consume_update(backend, update):
    """Apply permission deltas without requesting another profile or dialog list."""
    from copy import copy
    from telethon import types, utils
    if isinstance(update, types.UpdateChatDefaultBannedRights):
        peer = utils.get_peer_id(update.peer)
        entity = getattr(backend, '_capability_entities', {}).get(peer)
        if entity is not None:
            entity = copy(entity)
            entity.default_banned_rights = update.default_banned_rights
            remember(backend, entity)
    elif isinstance(update, types.UpdatePeerBlocked):
        peer = utils.get_peer_id(update.peer_id)
        entity = getattr(backend, '_capability_entities', {}).get(peer)
        full = getattr(backend, '_capability_full', {}).get(peer)
        if entity is not None:
            from types import SimpleNamespace
            full = copy(full) if full is not None else SimpleNamespace()
            full.blocked = bool(update.blocked)
            remember(backend, entity, full)
