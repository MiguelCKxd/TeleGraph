"""Local contact-card appearance. This module never reads contacts or uses Telegram.

Only presentation identifiers are stored: hiding or reordering a section cannot
make data available that the server did not supply.
"""
import re

SECTIONS = ('info', 'photos', 'files', 'audio', 'voice', 'links', 'gifs', 'polls', 'posts', 'gifts', 'profile_music', 'similar', 'settings')
ACTIONS = ('message', 'call', 'video_call', 'notifications', 'edit_contact', 'share', 'add_username', 'membership', 'edit_self', 'profile_design', 'refresh', 'manage')
DENSITIES = ('compact', 'comfortable', 'spacious')
CONTACT_DEFAULTS = {
    'contact_card_width': 620,
    'contact_avatar_size': 96,
    'contact_density': 'comfortable',
    'contact_alignment': 'left',
    'contact_round_avatar': True,
    'contact_background': '',
    'contact_text': '',
    'contact_accent': '',
    'contact_border_width': 0,
    'contact_border_color': '',
    'contact_section_order': list(SECTIONS),
    'contact_hidden_sections': [],
    'contact_action_order': list(ACTIONS),
    'contact_hidden_actions': [],
}


def _identifiers(value, allowed):
    if not isinstance(value, (list, tuple)):
        return []
    result = []
    for item in value:
        if isinstance(item, str) and item in allowed and item not in result:
            result.append(item)
    return result


def validated_contact(values):
    result = {key: value.copy() if isinstance(value, list) else value
              for key, value in CONTACT_DEFAULTS.items()}
    for key, low, high in (('contact_card_width', 320, 1200),
                           ('contact_avatar_size', 48, 192),
                           ('contact_border_width', 0, 8)):
        value = values.get(key)
        if type(value) is int and low <= value <= high:
            result[key] = value
    for key, choices in (('contact_density', DENSITIES),
                         ('contact_alignment', ('left', 'center'))):
        if values.get(key) in choices:
            result[key] = values[key]
    if type(values.get('contact_round_avatar')) is bool:
        result['contact_round_avatar'] = values['contact_round_avatar']
    for suffix in ('background', 'text', 'accent', 'border_color'):
        key = 'contact_' + suffix
        color = values.get(key)
        if isinstance(color, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            result[key] = color.lower()
    for group, allowed, protected in (('section', SECTIONS, 'settings'),
                                      ('action', ACTIONS, 'manage')):
        key = f'contact_{group}_order'
        order = _identifiers(values.get(key), allowed)
        result[key] = order + [item for item in allowed if item not in order]
        key = f'contact_hidden_{group}s'
        result[key] = [item for item in _identifiers(values.get(key), allowed) if item != protected]
    return result


def card_style(values):
    values = validated_contact(values)
    density = values['contact_density']
    padding, gap = {'compact': (8, 4), 'comfortable': (16, 8), 'spacious': (24, 12)}[density]
    return {'width': values['contact_card_width'], 'avatar_size': values['contact_avatar_size'],
            'padding': padding, 'gap': gap, 'density': density,
            'alignment': values['contact_alignment'], 'round_avatar': values['contact_round_avatar'],
            **{key: values['contact_' + key] for key in
               ('background', 'text', 'accent', 'border_width', 'border_color')}}


def _ordered(values, available, group):
    values = validated_contact(values)
    # A caller supplies only supported sections/actions for the current peer.
    allowed = set(available)
    hidden = set(values[f'contact_hidden_{group}s'])
    return [item for item in values[f'contact_{group}_order'] if item in allowed and item not in hidden]


def ordered_sections(values, available):
    return _ordered(values, available, 'section')


def ordered_actions(values, available):
    return _ordered(values, available, 'action')


def save_contact_preferences(app, values, on_saved=None):
    """Update local preferences only; deliberately independent of the sync toggle."""
    app.preferences.save(validated_contact(values))
    if on_saved is not None:
        on_saved()


def restore_contact_preferences(app, on_saved=None):
    save_contact_preferences(app, CONTACT_DEFAULTS, on_saved)
