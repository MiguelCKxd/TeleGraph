"""Which menus and windows the app uses: the device's or its own (1.5.1, 1.5.2).

Without Complex features › Customizable menus, every kind uses LIGHTEST.
With it on:

Settings › Customization › Menus:

- ``default``  exactly the behaviour until now (DEFAULTS below).
- ``system``   the device's own menu/window wherever one exists.
- ``app``      TG-ASCII's own menu/window wherever one exists.
- ``custom``   chosen per kind in ``menu_custom``.

Every kind below has both versions. Things with no equivalent on one side
(for example the macOS menu bar, the tray menu or the text-input prompts) are
not listed and keep working as before.
"""
import sys

KINDS = (
    # kind,              behaviour until now
    ('context_menu',     'system'),   # right click / ⋯ menus
    ('message_box',      'system'),   # notices and yes/no confirmations
    ('file_picker',      'system'),   # open / save / choose folder
    ('color_picker',     'system'),
    ('emoji_picker',     'system'),   # the "Emoji" button next to search fields
    ('image_viewer',     'app'),      # photos received in chats
    ('video_player',     'app'),      # videos and GIFs received in chats
    ('audio_player',     'app'),      # voice notes and music received in chats
    ('file_viewer',      'app'),      # other files received in chats
    ('media_editor',     'app'),      # edit a photo/video before sending
    ('file_preview',     'app'),      # preview a file before sending
)
DEFAULTS = dict(KINDS)
MODES = ('default', 'system', 'app', 'custom')

# 1.5.2: with Complex features › Customizable menus OFF, each kind uses the
# version that costs least and feels smoothest:
#  - device menus, dialogs, pickers and palettes are native and instant, and
#    create no Tk widgets (the app versions build hundreds for files/emoji);
#  - videos play in the device player: hardware decoding instead of PyAV;
#  - photos, audio, received files and the editor stay in the app: they reuse
#    what is already loaded instead of launching another application;
#  - files attach at once with the app preview one click away (the device
#    option opens Quick Look or a full app for every attached file).
LIGHTEST = {
    'context_menu': 'system', 'message_box': 'system', 'file_picker': 'system',
    'color_picker': 'system', 'emoji_picker': 'system',
    'image_viewer': 'app', 'video_player': 'system', 'audio_player': 'app',
    'file_viewer': 'app', 'media_editor': 'app',
    'file_preview': 'app',
}
CHOICES = ('system', 'app')

_mode = 'default'
_custom = {}


def configure(values, root=None):
    """Read the preferences; called at start and after every settings save."""
    global _mode, _custom
    values = values or {}
    from . import custom_menus
    custom_menus.configure(values, root)
    mode = values.get('menu_style', 'default')
    _mode = mode if mode in MODES else 'default'
    _custom = validated_custom(values.get('menu_custom'))


def validated_custom(value):
    if not isinstance(value, dict):
        return {}
    return {kind: choice for kind, choice in value.items() if kind in DEFAULTS and choice in CHOICES}


def choice(kind):
    """'system' or 'app' for this kind under the current setting."""
    from . import custom_menus
    if not custom_menus.enabled():
        return LIGHTEST.get(kind, 'system')
    if custom_menus.active(kind):
        return 'app'  # The user's own version is built on the app side.
    default = DEFAULTS.get(kind, 'system')
    if _mode == 'system':
        return 'system'
    if _mode == 'app':
        return 'app'
    if _mode == 'custom':
        return _custom.get(kind, default)
    return default


def uses_system(kind):
    return choice(kind) == 'system'


def migrate(raw):
    """1.5.1: the three old 'Always … with the system …' switches become the
    matching kinds of a custom menu setting, so nobody loses a choice."""
    features = raw.get('advanced_features') if isinstance(raw.get('advanced_features'), dict) else {}
    if 'menu_style' in raw:
        # 1.5.2: whoever already chose menus in 1.5.1 keeps that choice working.
        if raw.get('menu_style') in MODES and raw.get('menu_style') != 'default' and 'custom_menus' not in features:
            return {'advanced_features': {**features, 'custom_menus': True}}
        return {}
    old = {'native_image_viewer': 'image_viewer', 'native_media_editor': 'media_editor',
           'native_file_preview': 'file_preview'}
    chosen = {kind: 'system' for key, kind in old.items() if raw.get(key) is True}
    if not chosen:
        return {}
    # 1.5.2: choosing per kind lives behind Complex features › Customizable menus.
    return {'menu_style': 'custom', 'menu_custom': chosen, 'advanced_features': {**features, 'custom_menus': True}}


def platform_name():
    return 'macOS' if sys.platform == 'darwin' else 'Windows' if sys.platform == 'win32' else 'system'
