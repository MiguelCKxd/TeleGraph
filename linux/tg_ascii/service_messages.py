"""Readable text for Telegram service messages (all versions).

A service message (someone joined, a call, a pinned message...) has no text
of its own; the chat and the chat list show this instead of a placeholder.
Pure function of the action: never performs IO.
"""
from .i18n import tr


def _names(entities, limit=3):
    from telethon import utils
    names = [utils.get_display_name(entity) or '?' for entity in entities or ()]
    if len(names) > limit:
        return ', '.join(names[:limit]) + ' +' + str(len(names) - limit)
    return ', '.join(names)


def duration_text(seconds):
    seconds = max(0, int(seconds or 0))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f'{hours}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes}:{seconds:02d}'


def period_text(seconds):
    seconds = int(seconds or 0)
    for size, unit in ((86400 * 30, 'mo'), (86400 * 7, 'w'), (86400, 'd'), (3600, 'h'), (60, 'min')):
        if seconds >= size and seconds % size == 0:
            return f'{seconds // size} {unit}'
    return f'{seconds} s'


def service_text(action, actor='', users=(), outgoing=False):
    """The text of a service message. actor: who did it; users: the entities
    the action names (Telethon's Message.action_entities)."""
    from telethon.tl import types as t
    name = actor or '?'
    others = _names(users)
    kind = type(action).__name__
    if isinstance(action, t.MessageActionChatCreate):
        return tr('{name} created the group').format(name=name)
    if isinstance(action, t.MessageActionChannelCreate):
        return tr('Channel created')
    if isinstance(action, (t.MessageActionChatEditTitle, getattr(t, 'MessageActionChannelEditTitle', ()))):
        return tr('{name} changed the name to «{title}»').format(name=name, title=action.title)
    if isinstance(action, t.MessageActionChatEditPhoto):
        return tr('{name} changed the photo').format(name=name)
    if isinstance(action, t.MessageActionChatDeletePhoto):
        return tr('{name} removed the photo').format(name=name)
    if isinstance(action, t.MessageActionChatAddUser):
        if not others or others == name:
            return tr('{name} joined').format(name=name)
        return tr('{name} added {users}').format(name=name, users=others)
    if isinstance(action, (t.MessageActionChatJoinedByLink, t.MessageActionChatJoinedByRequest)):
        return tr('{name} joined').format(name=name)
    if isinstance(action, t.MessageActionChatDeleteUser):
        if not others or others == name:
            return tr('{name} left').format(name=name)
        return tr('{name} removed {users}').format(name=name, users=others)
    if isinstance(action, (t.MessageActionChatMigrateTo, t.MessageActionChannelMigrateFrom)):
        return tr('The group was upgraded to a supergroup')
    if isinstance(action, t.MessageActionPinMessage):
        return tr('{name} pinned a message').format(name=name)
    if isinstance(action, t.MessageActionHistoryClear):
        return tr('Chat history was cleared')
    if isinstance(action, t.MessageActionPhoneCall):
        icon = '📹 ' if action.video else '📞 '
        reason = type(action.reason).__name__ if action.reason else ''
        if reason.endswith('Missed') and not outgoing:
            return icon + tr('Missed call')
        if reason.endswith('Busy'):
            return icon + tr('Declined call')
        label = tr('Outgoing call') if outgoing else tr('Incoming call')
        return icon + label + (' · ' + duration_text(action.duration) if action.duration else '')
    if isinstance(action, t.MessageActionGroupCall):
        if action.duration:
            return '🎙 ' + tr('Voice chat ended') + ' · ' + duration_text(action.duration)
        return '🎙 ' + tr('{name} started a voice chat').format(name=name)
    if isinstance(action, t.MessageActionInviteToGroupCall):
        return '🎙 ' + tr('{name} invited {users} to the voice chat').format(name=name, users=others or '?')
    if isinstance(action, t.MessageActionGroupCallScheduled):
        when = action.schedule_date.astimezone().strftime('%Y-%m-%d %H:%M') if action.schedule_date else ''
        return '🎙 ' + tr('Voice chat scheduled') + (' · ' + when if when else '')
    if isinstance(action, t.MessageActionScreenshotTaken):
        return tr('{name} took a screenshot').format(name=name)
    if isinstance(action, t.MessageActionSetMessagesTTL):
        if action.period:
            return tr('Auto-delete timer: {duration}').format(duration=period_text(action.period))
        return tr('Auto-delete turned off')
    if isinstance(action, t.MessageActionContactSignUp):
        return tr('{name} joined Telegram').format(name=name)
    if isinstance(action, t.MessageActionSetChatTheme):
        return tr('{name} changed the chat theme').format(name=name)
    if kind == 'MessageActionSetChatWallPaper':
        return tr('{name} changed the chat wallpaper').format(name=name)
    if isinstance(action, t.MessageActionTopicCreate):
        return tr('{name} created the topic «{title}»').format(name=name, title=action.title)
    if kind.startswith(('MessageActionGift', 'MessageActionStarGift', 'MessageActionPrizeStars')):
        return '🎁 ' + tr('{name} sent a gift').format(name=name)
    if kind == 'MessageActionSuggestProfilePhoto':
        return tr('{name} suggested a profile photo').format(name=name)
    if kind == 'MessageActionBoostApply':
        return tr('{name} boosted the group').format(name=name)
    if isinstance(action, t.MessageActionCustomAction):
        return action.message
    return ''
