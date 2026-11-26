"""Device-local presentation options exposed by Appearance/Personalization."""
import re

DEFAULTS = {
    'controls': 'brackets', 'navigation': 'menu', 'header_alignment': 'left',
    'separators': 'dashed', 'separator_inset': 0, 'row_height': 0,
    'avatar_size': 0, 'title_weight': 700, 'title_color': '', 'secondary_color': '',
    'panel_color': '', 'separator_color': '', 'badge_color': '', 'control_color': '',
    'show_online': True, 'private_sender_names': True, 'bubble_border': True,
    'bubble_width': 88, 'list_title': '', 'primary_action': 'menu', 'text_decoration': True,
}
CHOICES = {'controls': ('brackets', 'plain', 'icons'), 'navigation': ('menu', 'tabs'),
           'header_alignment': ('left', 'center'), 'separators': ('dashed', 'solid', 'none'),
           'primary_action': ('menu', 'compose')}
RANGES = {'separator_inset': (0, 160), 'row_height': (0, 160), 'avatar_size': (0, 96),
          'title_weight': (400, 800), 'bubble_width': (50, 100)}


def validated(value):
    source = value if isinstance(value, dict) else {}
    result = DEFAULTS.copy()
    if isinstance(source.get('list_title'), str):
        result['list_title'] = ' '.join(source['list_title'].split())[:80]
    for key, choices in CHOICES.items():
        if source.get(key) in choices:
            result[key] = source[key]
    for key, (low, high) in RANGES.items():
        number = source.get(key)
        if type(number) is int and low <= number <= high:
            result[key] = number
    for key, default in DEFAULTS.items():
        if isinstance(default, bool) and type(source.get(key)) is bool:
            result[key] = source[key]
        elif key.endswith('_color'):
            color = source.get(key)
            if isinstance(color, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', color):
                result[key] = color.lower()
    return result
