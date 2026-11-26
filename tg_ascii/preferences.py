"""Private, atomic local settings. Never stores OTPs, passwords or session keys."""
import json
import os
from pathlib import Path
import tempfile
from .visual_effects import EFFECT_DEFAULTS, validated_effects
from .contact_appearance import CONTACT_DEFAULTS, validated_contact

MAX_SETTINGS_BYTES = 2 * 1024 * 1024

def shows_preview(values, kind):
    """Inline preview for a message of ``kind``; photos also obey photo_previews (3.2)."""
    if not values.get('inline_media', True):
        return False
    return kind != 'image' or values.get('photo_previews', True)


# 3.2: wider limits, shared with the mobile settings.
FONT_SIZE_RANGE = (8, 40)
RADIUS_RANGE = (0, 48)
LAYOUT_RANGES = {
    'button_padding_x': (0, 48, 7), 'button_padding_y': (0, 32, 4),
    'chat_row_height': (0, 180, 0), 'message_line_spacing': (0, 40, 0),
    'bubble_gap': (0, 80, 14), 'bubble_width_percent': (40, 100, 76),
    'bubble_width_limit': (200, 2000, 570),
}
PALETTE_OVERRIDES = {'panel_color': 'panel', 'secondary_text_color': 'muted',
                     'divider_color': 'line', 'title_color': 'strong'}

DEFAULTS = {'interface_background':'', 'custom_icon':'', 'official_icon_label':'', 'animated_emoji':True, 'reduce_animations':False, 'telegram_backgrounds':False, 'text_color':'', 'background_color':'', 'accent_color':'', 'bubble_in_color':'', 'bubble_out_color':'', 'app_display_name':'', 'button_radius':0, 'menu_radius':0, 'bubble_radius':0, 'language': 'en', 'font_size': 12, 'ascii_text': False,
            'enter_send': True, 'compact': False, 'inline_media': True, 'photo_previews': True, 'local_pins': False,
            'notifications': True, 'notify_preview': True, 'notify_sound': True,
            'notify_active': False, 'theme': 'dark', 'logo_theme': 'dark',
            'font_family': '', 'background_notifications': True, 'logo_variant': 'title-short', 'logo_color': 'default', 'bubbles': False, 'quick_reaction': '👍'}
DEFAULTS.update(EFFECT_DEFAULTS)
DEFAULTS.update(CONTACT_DEFAULTS)
DEFAULTS.update({key: bounds[2] for key, bounds in LAYOUT_RANGES.items()})
DEFAULTS.update({key: '' for key in PALETTE_OVERRIDES})
DEFAULTS['sync_customizations'] = True
DEFAULTS['ask_account_startup'] = True
# 1.5.3: keep a copy of the chat list and recent messages to open offline.
DEFAULTS['offline_copy'] = True
# 1.5.4: open at login (off by default) and local, visual-only account names.
DEFAULTS['open_at_login'] = False
DEFAULTS['account_aliases'] = {}
DEFAULTS['mobile_quick_reactions'] = {}
DEFAULTS['show_seconds'] = False
# 1.4: open enlarged photos directly in the operating system's viewer.
DEFAULTS['native_image_viewer'] = False
DEFAULTS['native_media_editor'] = False
DEFAULTS['native_file_preview'] = False
# 1.4.1/1.5 choice settings: value must be one of the listed options.
CHOICES = {
    # Composer shortcuts; '' = automatic (follows "Enter sends messages").
    'shortcut_send': ('', ('', 'Return', 'Shift+Return', 'Mod+Return', 'Alt+Return', 'Ctrl+Return')),
    'shortcut_newline': ('', ('', 'Return', 'Shift+Return', 'Mod+Return', 'Alt+Return', 'Ctrl+Return')),
    # How a word that does not fit at the end of a line is handled.
    'line_breaking': ('auto', ('auto', 'word', 'char', 'hyphen', 'syllable')),
    # Resource profiles; 'normal' is exactly the pre-1.5 behaviour.
    'resource_cpu': ('normal', ('limited', 'normal', 'unlimited')),
    'resource_ram': ('normal', ('limited', 'normal', 'unlimited')),
    'resource_gpu': ('normal', ('limited', 'normal', 'unlimited')),
    'resource_network': ('normal', ('limited', 'normal', 'unlimited')),
    # 1.5.0.1: animation frame rate limit; 'auto' = as before (30 fps).
    'frame_limit': ('auto', ('auto', '15', '24', '30', '60', '120', 'unlimited')),
    # 1.5.1: device or app menus (menu_style.py); 'default' = as before.
    'menu_style': ('default', ('default', 'system', 'app', 'custom')),
}
for _key, (_default, _options) in CHOICES.items():
    DEFAULTS[_key] = _default
# 1.5: prepare everything at startup (slower start, smoother use). Off by default.
DEFAULTS['preload_startup'] = False
# 1.5.1: per-kind choices for menu_style 'custom' ({kind: 'system'|'app'}).
DEFAULTS['menu_custom'] = {}
from .advanced_features import validated_features
DEFAULTS['advanced_features'] = validated_features({})
# Mobile app: the same features, on unless turned off there (explicit choices only).
DEFAULTS['mobile_features'] = {}


def animations_allowed(values):
    """False when Personalization › Disable all animations is on (3.0.0.2, off by default)."""
    return not values.get('reduce_animations', False)


def animated_emoji_enabled(values):
    """Animated emoji and stickers play: their own switch and the global one agree."""
    return bool(values.get('animated_emoji', True)) and animations_allowed(values)


def data_root():
    return Path(os.environ.get('TG_ASCII_DATA_DIR', str(Path.home() / '.tg-ascii'))).expanduser()


def read_json(path, fallback):
    try:
        # Damaged/imported settings must not allocate an unbounded string on
        # the GUI thread, or crash startup with deeply nested JSON.
        with Path(path).open('rb') as stream:
            data = stream.read(MAX_SETTINGS_BYTES + 1)
        if len(data) > MAX_SETTINGS_BYTES:
            return fallback.copy()
        value = json.loads(data.decode('utf-8'))
        pending = [(value, 0)]
        while pending:
            current, depth = pending.pop()
            if depth > 32:
                return fallback.copy()
            if isinstance(current, dict):
                pending.extend((item, depth + 1) for item in current.values())
            elif isinstance(current, list):
                pending.extend((item, depth + 1) for item in current)
        return value if isinstance(value, dict) else fallback.copy()
    except (OSError, ValueError, RecursionError):
        return fallback.copy()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='settings-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Preferences:
    def __init__(self, root=None, demo=False):
        self.path = (Path(root) if root else data_root()) / 'preferences.json'
        self.demo = demo
        self.listeners = []
        self.values = DEFAULTS.copy()
        if not demo:
            raw = read_json(self.path, {})
            self.values.update({k: v for k, v in raw.items() if k in DEFAULTS})
            from .menu_style import migrate
            self.values.update(migrate(raw))  # 1.5.1: old "always with the system" switches
        self.values = self.validated(self.values)

    @staticmethod
    def validated(values):
        result = DEFAULTS.copy()
        result.update(validated_effects(values))
        result.update(validated_contact(values))
        from .advanced_features import validated_features
        result['advanced_features'] = validated_features(values.get('advanced_features'))
        from .advanced_features import FEATURES
        mobile = values.get('mobile_features')
        result['mobile_features'] = ({key: value for key, value in mobile.items() if (key in FEATURES or key in ('preload_startup', 'native_liquid_glass')) and type(value) is bool}
                                     if isinstance(mobile, dict) else {})
        from .i18n import LANGUAGES
        if isinstance(values.get('language'), str) and values['language'] in LANGUAGES:
            result['language'] = values['language']
        for key in ('theme', 'logo_theme'):
            if values.get(key) in ('dark', 'light', 'system'): result[key] = values[key]
        from .logos import LOGO_PALETTES, VARIANTS
        if isinstance(values.get('logo_variant'), str) and values['logo_variant'] in VARIANTS: result['logo_variant'] = values['logo_variant']
        if isinstance(values.get('logo_color'), str) and values['logo_color'] in LOGO_PALETTES:
            result['logo_color'] = values['logo_color']
        reaction = values.get('quick_reaction', '👍')
        if (type(reaction) is int and reaction > 0) or (isinstance(reaction, str) and 0 < len(reaction) <= 32): result['quick_reaction'] = reaction
        mobile_reactions = values.get('mobile_quick_reactions')
        if isinstance(mobile_reactions, dict):
            result['mobile_quick_reactions'] = {account: reaction for account, reaction in mobile_reactions.items()
                                                 if isinstance(account, str) and 0 < len(account) <= 40
                                                 and isinstance(reaction, str) and 0 < len(reaction) <= 32}
        family = values.get('font_family', '')
        if isinstance(family, str) and len(family) <= 160 and not any(ord(c) < 32 for c in family):
            result['font_family'] = family
        import re
        name = values.get('app_display_name', '')
        if isinstance(name, str) and len(name) <= 64 and name.isprintable():
            result['app_display_name'] = name.strip()
        for key in ('text_color','background_color','accent_color','bubble_in_color','bubble_out_color',*PALETTE_OVERRIDES):
            color=values.get(key,'')
            if isinstance(color,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',color):result[key]=color.lower()
        for key in ('button_radius','menu_radius','bubble_radius'):
            value=values.get(key,0)
            if type(value) is int and RADIUS_RANGE[0]<=value<=RADIUS_RANGE[1]:result[key]=value
        for key, (low, high, default) in LAYOUT_RANGES.items():
            value = values.get(key, default)
            if type(value) is int and low <= value <= high:
                result[key] = value
        for key in ('interface_background','custom_icon'):
            path=values.get(key,'')
            if isinstance(path,str) and len(path)<=4096 and not any(ord(c)<32 for c in path):result[key]=path
        # Telegram API terms (core.telegram.org/api/terms, 2.4): an unofficial client must
        # not use the official Telegram logo. A copy chosen before 3.4.1 reverts to TeleGraph's.
        label=values.get('official_icon_label','')
        if isinstance(label,str) and label:result['custom_icon']=''
        result['official_icon_label']=''
        size = values.get('font_size', 12)
        result['font_size'] = size if type(size) is int and FONT_SIZE_RANGE[0] <= size <= FONT_SIZE_RANGE[1] else 12
        from .menu_style import validated_custom
        result['menu_custom'] = validated_custom(values.get('menu_custom'))
        aliases = values.get('account_aliases')
        if isinstance(aliases, dict):
            result['account_aliases'] = {key: ' '.join(value.split())[:40] for key, value in aliases.items()
                                         if isinstance(key, str) and len(key) <= 40 and isinstance(value, str)
                                         and value.strip() and not any(ord(c) < 32 for c in value)}
        for key, (_, options) in CHOICES.items():
            if values.get(key) in options:
                result[key] = values[key]
        for key in (k for k, v in DEFAULTS.items() if type(v) is bool):
            if type(values.get(key)) is bool:
                result[key] = values[key]
        custom_icon = result['custom_icon']
        if custom_icon.startswith('mobile:'):
            color = custom_icon.removeprefix('mobile:')
            if color in LOGO_PALETTES:
                result.update(logo_variant='title-short', logo_color=color,
                              logo_theme='light' if color == 'light' else 'dark',
                              custom_icon='', official_icon_label='')
        return result

    def save(self, values):
        updated = self.validated({**self.values, **values})
        if updated == self.values:
            return
        if not self.demo:
            write_json(self.path, updated)
        self.values = updated
        for callback in tuple(self.listeners):
            callback()
