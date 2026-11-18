"""Bridge between notification controls in the WebView and Telegram's TL types."""
from copy import copy
from datetime import datetime, timezone

from telethon import types


FLAGS = ('show_previews', 'silent', 'stories_muted', 'stories_hide_sender')


def read_settings(settings, platform):
    suffix = {'iOS': 'ios', 'Android': 'android'}.get(platform, 'other')
    result = {name: getattr(settings, name, None) for name in FLAGS}
    until = getattr(settings, 'mute_until', None)
    result['mute_until'] = int(until.timestamp()) if until is not None else None
    for wire, local in (('sound', f'{suffix}_sound'), ('stories_sound', f'stories_{suffix}_sound')):
        current = getattr(settings, local, None)
        if current is None:
            other = 'other_sound' if wire == 'sound' else 'stories_other_sound'
            current = getattr(settings, other, None)
        result[wire] = sound_name(current)
    return result


def sound_name(sound):
    if sound is None:
        return None
    if isinstance(sound, types.NotificationSoundNone):
        return 'none'
    if isinstance(sound, types.NotificationSoundDefault):
        return 'default'
    if isinstance(sound, types.NotificationSoundRingtone):
        return f'ringtone:{sound.id}'  # one of the account's saved ringtones
    return 'custom'


def parse_sound(value):
    if value == 'none':
        return types.NotificationSoundNone()
    if value == 'default':
        return types.NotificationSoundDefault()
    if isinstance(value, str) and value.startswith('ringtone:') and value[9:].isdigit():
        return types.NotificationSoundRingtone(int(value[9:]))
    raise ValueError('Invalid notification sound.')


def changes_from_web(changes):
    result = {}
    for key, value in changes.items():
        if key in FLAGS and type(value) is bool:
            result[key] = value
        elif key in ('sound', 'stories_sound'):
            result[key] = parse_sound(value)
        elif key == 'mute_until' and type(value) is int and 0 <= value <= 2**31 - 1:
            result[key] = datetime.fromtimestamp(value, timezone.utc)
        else:
            raise ValueError('Invalid notification setting.')
    return result


def reaction_scope(value):
    if isinstance(value, types.ReactionNotificationsFromAll):
        return 'all'
    if isinstance(value, types.ReactionNotificationsFromContacts):
        return 'contacts'
    return 'off'


def read_reactions(settings):
    return {**{key: reaction_scope(getattr(settings, key + '_notify_from', None))
               for key in ('messages', 'stories', 'poll_votes')},
            'show_previews': settings.show_previews, 'sound': sound_name(settings.sound)}


def reactions_from_web(current, changes):
    settings = copy(current)
    for key, value in changes.items():
        if key in ('messages', 'stories', 'poll_votes'):
            scopes = {'off': None, 'contacts': types.ReactionNotificationsFromContacts(),
                      'all': types.ReactionNotificationsFromAll()}
            if value not in scopes:
                raise ValueError('Invalid reaction notification scope.')
            setattr(settings, key + '_notify_from', scopes[value])
        elif key == 'show_previews' and type(value) is bool:
            settings.show_previews = value
        elif key == 'sound':
            settings.sound = parse_sound(value)
        else:
            raise ValueError('Invalid reaction notification setting.')
    return settings
