"""Explicit local preference resets, independent from accounts and app data."""
import asyncio
from copy import deepcopy

from tg_ascii.preferences import DEFAULTS, write_json
from tg_ascii.visual_effects import EFFECT_DEFAULTS

APPEARANCE_PREFS = ('language', 'theme', 'font_size', 'font_family', 'app_display_name',
                    'text_color', 'background_color', 'accent_color', 'bubble_in_color',
                    'bubble_out_color', 'bubbles')
CUSTOMIZATION_PREFS = ('reduce_animations', 'bubble_radius', 'button_radius', 'menu_radius',
                       'interface_background', 'custom_icon', 'official_icon_label',
                       'logo_theme', 'logo_variant', 'logo_color', 'telegram_backgrounds',
                       *EFFECT_DEFAULTS)
APPEARANCE_LOOK = ('font', 'layout', 'side_width', 'windows', 'presentation')
CUSTOMIZATION_LOOK = ('background', 'dim', 'chats', 'chat_sync', 'background_sync', 'effects',
                       'icon', 'brand_logo', 'brand_photo', 'official_logo', 'native_dialogs')


async def reset_settings(core, scope, account):
    if scope not in ('appearance', 'customization', 'all'):
        raise ValueError('Invalid settings scope.')
    lock = core.__dict__.setdefault('_settings_reset_lock', asyncio.Lock())
    async with lock:
        core.check_active_account(account)
        if core.locked or core.stage != 'ready':
            raise PermissionError('Open and unlock the active account.')
        if core.__dict__.get('_writing_wallpapers'):
            raise RuntimeError('Wallpaper change in progress')
        # Native icon confirmation can suspend this operation. Do it before
        # changing any other preference, then revalidate the account.
        if scope in ('customization', 'all') and core.appearance()['icon'] != 'default':
            await core.api_appearance({'icon': 'default'}, account=account)
            core.check_active_account(account)
            if core.locked:
                raise PermissionError('Open and unlock the active account.')
            if core.__dict__.get('_writing_wallpapers'):
                raise RuntimeError('Wallpaper change in progress')
        keys = DEFAULTS if scope == 'all' else APPEARANCE_PREFS if scope == 'appearance' else CUSTOMIZATION_PREFS
        values = {key: deepcopy(DEFAULTS[key]) for key in keys}
        changes = {key: value for key, value in values.items() if core.prefs.values.get(key) != value}
        core.prefs.save(values)
        keys = core.APPEARANCE if scope == 'all' else APPEARANCE_LOOK if scope == 'appearance' else CUSTOMIZATION_LOOK
        stored = core.stored_appearance()
        stored.update({key: deepcopy(core.APPEARANCE[key]) for key in keys})
        write_json(core.appearance_path(), stored)
        if scope in ('customization', 'all'):
            # Reset local per-account choices without editing a Telegram
            # wallpaper or deleting the user's source image, session or cache.
            for path in (core.root / 'chat-wallpapers').glob('*/settings.json'):
                write_json(path, {})
        if scope == 'all':
            vocabulary = core.siri_vocabulary
            write_json(vocabulary.path, {})
            vocabulary.accounts = {}
            vocabulary.sync(core)
        look = core.save_appearance(core.appearance())
        core.keep_connected()
        await core.apply_settings_changes(changes, request_permission=False)
        return {'settings': core.settings_snapshot(), 'appearance': look}
