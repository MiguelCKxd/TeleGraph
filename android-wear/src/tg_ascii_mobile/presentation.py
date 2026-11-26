"""Device-local presentation options exposed by Appearance/Personalization."""
import re

DEFAULTS = {
    'controls': 'brackets', 'navigation': 'menu', 'header_alignment': 'left',
    'separators': 'dashed', 'separator_inset': 0, 'row_height': 0,
    'avatar_size': 0, 'title_weight': 700, 'title_color': '', 'secondary_color': '',
    'panel_color': '', 'separator_color': '', 'badge_color': '', 'control_color': '',
    'show_online': True, 'private_sender_names': True, 'bubble_border': True,
    'bubble_width': 88, 'list_title': '', 'primary_action': 'menu', 'text_decoration': True,
    'message_font_size': 0, 'header_font_size': 0, 'name_font_size': 0,
    'preview_font_size': 0, 'metadata_font_size': 0, 'message_line_height': 0,
    'message_gap': 0, 'message_padding_x': 0, 'message_padding_y': 0, 'button_height': 44,
    'preview_lines': 1, 'bubble_alignment': 'direction',
    'list_avatars': True, 'list_times': True, 'list_badges': True,
    'incoming_text_color': '', 'outgoing_text_color': '',
    'incoming_metadata_color': '', 'outgoing_metadata_color': '',
}
CHOICES = {'controls': ('brackets', 'plain', 'icons'), 'navigation': ('menu', 'tabs'),
           'header_alignment': ('left', 'center'), 'separators': ('dashed', 'solid', 'none'),
           'primary_action': ('menu', 'compose'),
           'bubble_alignment': ('direction', 'start', 'end', 'center')}
RANGES = {'separator_inset': (0, 160), 'row_height': (0, 160), 'avatar_size': (0, 96),
          'title_weight': (400, 800), 'bubble_width': (50, 100),
          'message_gap': (0, 48), 'message_padding_x': (0, 40), 'message_padding_y': (0, 32),
          'button_height': (44, 80), 'preview_lines': (1, 4)}
# Zero inherits the existing size; nonzero values remain readable and bounded.
OPTIONAL_RANGES = {'message_font_size': (8, 72), 'header_font_size': (8, 72),
                   'name_font_size': (8, 64), 'preview_font_size': (8, 48),
                   'metadata_font_size': (8, 40), 'message_line_height': (100, 240)}


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
    for key, (low, high) in OPTIONAL_RANGES.items():
        number = source.get(key)
        if type(number) is int and (number == 0 or low <= number <= high):
            result[key] = number
    for key, default in DEFAULTS.items():
        if isinstance(default, bool) and type(source.get(key)) is bool:
            result[key] = source[key]
        elif key.endswith('_color'):
            color = source.get(key)
            if isinstance(color, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', color):
                result[key] = color.lower()
    return result
