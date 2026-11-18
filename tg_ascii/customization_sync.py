"""Native Telegram chat themes and explicit local-only appearance overrides."""
import hashlib
import json
from pathlib import Path
import re

from telethon import functions as f, types as t

from .preferences import read_json, write_json
from .sticker_search import cached


def label(english, spanish):
    from .i18n import get_language
    language = get_language()
    if language == 'es-419':
        from .spanish_latam import latam
        return latam(spanish)
    return spanish if language == 'es' else english


def sync_enabled(preferences):
    values = preferences if isinstance(preferences, dict) else preferences.values
    return values.get('sync_customizations', True) is True


def theme_settings(theme, dark=False):
    settings = getattr(theme, 'settings', None) or getattr(theme, 'theme_settings', None) or []
    for item in settings:
        is_dark = isinstance(item.base_theme, (t.BaseThemeNight, t.BaseThemeTinted))
        if is_dark == dark:
            return item
    return settings[0] if settings else None


def theme_palette(settings, dark=False):
    from .themes import DARK, LIGHT
    result = (DARK if dark else LIGHT).copy()
    if settings is None:
        return result
    color = lambda number: f'#{number & 0xffffff:06x}'
    result['strong'] = color(settings.accent_color)
    colors = getattr(settings, 'message_colors', None) or []
    if colors:
        result['selected'] = color(colors[0])
    return result


class ThemeOverrides:
    def __init__(self, root, demo=False):
        self.path = Path(root) / 'chat-themes.json'
        self.demo = demo
        self.values = {} if demo else read_json(self.path, {})

    def get(self, account, peer):
        value = self.values.get(f'{account}:{peer}')
        return value if isinstance(value, dict) and value.get('local_only') is True else None

    def save(self, account, peer, value):
        updated = dict(self.values)
        key = f'{account}:{peer}'
        if value is None:
            updated.pop(key, None)
        else:
            updated[key] = value
        if updated != self.values:
            if not self.demo:
                write_json(self.path, updated)
            self.values = updated


def overrides(app):
    app = getattr(app, '_linked_owner', None) or app
    store = getattr(app, '_chat_theme_overrides', None)
    if store is None:
        store = app._chat_theme_overrides = ThemeOverrides(app.preferences.path.parent, app.demo)
    return store


def local_theme_wallpaper(app):
    record = overrides(app).get(app.ui_account, app.active)
    return (True, record.get('wallpaper')) if record is not None else (False, None)


def wallpaper_is_local(app, account, peer):
    return overrides(app).get('wallpaper:' + account, peer) is not None


def mark_wallpaper_scope(app, account, peer, local):
    overrides(app).save('wallpaper:' + account, peer, {'local_only': True} if local else None)


def palette_for_chat(app, fallback):
    if not hasattr(app, 'ui_account') or not hasattr(app, 'active') or not hasattr(app.preferences, 'path'):
        return fallback
    record = overrides(app).get(app.ui_account, app.active)
    if record is None:
        active = getattr(app, '_active_chat_theme', None)
        record = active[1] if isinstance(active, tuple) and active[0] == (app.ui_account, app.active) else None
    colors = record.get('palette', {}) if isinstance(record, dict) else {}
    if not isinstance(colors, dict):
        return fallback
    valid = {k: v for k, v in colors.items() if k in fallback and isinstance(v, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', v)}
    return {**fallback, **valid} if valid else fallback


async def rendered_theme(backend, theme, directory, dark=False):
    settings = theme_settings(theme, dark)
    wallpaper = getattr(settings, 'wallpaper', None)
    path = None
    if wallpaper is not None:
        path = await render_cached_wallpaper(backend, wallpaper, directory)
    return {'emoticon': getattr(theme, 'emoticon', '') or '', 'palette': theme_palette(settings, dark),
            'wallpaper': str(path) if path else None}


async def render_cached_wallpaper(backend, wallpaper, directory):
    from .telegram_wallpapers import wallpaper_file
    # Settings distinguish day/night variants that share a Telegram wallpaper ID.
    signature = json.dumps(wallpaper.to_dict(), sort_keys=True, default=str).encode('utf-8')
    digest = hashlib.sha256(signature).hexdigest()[:24]
    folder = Path(directory) / digest
    target = folder / f'telegram-wallpaper-{wallpaper.id}.jpg'
    if target.is_file():
        return target
    return await wallpaper_file(backend, wallpaper, folder)


async def server_chat_appearance(backend, peer, directory, dark=False):
    profile = await backend.profile(peer)
    current = profile.get('chat_theme')
    emoticon = getattr(current, 'emoticon', None) or profile.get('theme_emoticon')
    result = {'emoticon': emoticon or '', 'palette': {}, 'wallpaper': None}
    theme = current if isinstance(current, t.ChatThemeUniqueGift) else None
    if emoticon:
        theme = next((item for item in await backend.chat_themes() if item.emoticon == emoticon), None)
    if theme is not None:
        result = await rendered_theme(backend, theme, directory, dark)
    wallpaper = profile.get('wallpaper')
    if wallpaper is not None:
        result['wallpaper'] = str(await render_cached_wallpaper(backend, wallpaper, directory))
    return result


class SyncedCustomization:
    async def chat_themes(self):
        response = await cached(self, ('chat-themes', getattr(self, '_config_epoch', 0)),
                                lambda: self.client(f.account.GetChatThemesRequest(hash=0)), ttl=3600)
        return [theme for theme in getattr(response, 'themes', []) if isinstance(theme, t.Theme) and theme.emoticon]

    async def set_chat_theme(self, peer, emoticon):
        if not isinstance(emoticon, str) or len(emoticon) > 32:
            raise ValueError('Invalid chat theme.')
        if emoticon and not any(item.emoticon == emoticon for item in await self.chat_themes()):
            raise ValueError('This chat theme is no longer available.')
        theme = t.InputChatTheme(emoticon) if emoticon else t.InputChatThemeEmpty()
        return await self.client(f.messages.SetChatThemeRequest(await self.client.get_input_entity(peer), theme))


async def apply_chat_theme(backend, store, account, peer, theme, directory, *, synchronize=True, dark=False):
    result = await rendered_theme(backend, theme, directory, dark) if theme is not None else {
        'emoticon': '', 'palette': {}, 'wallpaper': None}
    if synchronize:
        await backend.set_chat_theme(peer, result['emoticon'])
        store.save(account, peer, None)
    else:
        store.save(account, peer, {**result, 'local_only': True})
    return result


def open_chat_themes(app):
    from tkinter import ttk
    from .app_dialogs import scrollable, messagebox
    from .i18n import tr
    from .themes import resolve_theme
    if app.active is None or app.busy:
        return
    window, frame = app.dialog(label('Telegram chat themes', 'Temas de chat de Telegram'), '580x580')
    if app.demo:
        ttk.Label(frame, text=tr('Connect a Telegram account to load backgrounds.'), wraplength=490).pack(fill='x')
        return
    account, peer, backend = app.ui_account, app.active, app.service.backend
    synchronized = sync_enabled(app.preferences)
    explanation = label('Changes sync through Telegram and are visible to chat participants.',
                        'Los cambios se sincronizan en Telegram y son visibles para los participantes.') if synchronized else label(
        'Local only: this theme stays on this device. Telegram is not changed.',
        'Solo local: este tema se queda en este dispositivo. Telegram no cambia.')
    ttk.Label(frame, text=explanation, wraplength=490).pack(fill='x', pady=8)
    body = scrollable(frame)
    loading = ttk.Label(body, text=tr('Loading...')); loading.pack(fill='x')
    def valid():
        return window.winfo_exists() and (account, peer) == (app.ui_account, app.active) and backend is app.service.backend
    def apply(theme):
        if not valid() or app.busy:
            return
        # Re-read the setting: another window can change it while this dialog is open.
        synchronize = sync_enabled(app.preferences)
        if synchronize and not messagebox.askyesno(tr('Apply'), label(
                'Apply this theme in Telegram for chat participants?',
                '¿Aplicar este tema en Telegram para los participantes del chat?'), parent=window):
            return
        def done(result):
            if valid():
                app._active_chat_theme = ((account, peer), result)
                window.destroy()
                app.refresh_wallpaper()
                app.render_messages(False)
        app.call(apply_chat_theme(backend, overrides(app), account, peer, theme,
                 app.preferences.path.parent / 'wallpapers' / 'themes', synchronize=synchronize,
                 dark=resolve_theme(app.preferences.values.get('theme', 'dark')) == 'dark'), done, tr('Saving...'))
    def loaded(items):
        if not valid():
            return
        loading.destroy()
        ttk.Button(body, text=tr('Use default background'), command=lambda:apply(None)).pack(fill='x', pady=4)
        for theme in items:
            ttk.Button(body, text=f'{theme.emoticon}  {theme.title}', command=lambda item=theme:apply(item)).pack(fill='x', pady=4)
    app.worker.submit(backend.chat_themes(), loaded, lambda exc:app.show_error(exc) if valid() else None)
