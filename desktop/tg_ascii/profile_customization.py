"""Account profile appearance: native Telegram writes or a visible local override."""
import asyncio
from datetime import date,datetime,timezone
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile
import threading

from telethon import functions as f, types as t

from .customization_sync import label, sync_enabled
from .preferences import read_json, write_json
from .sticker_search import cached

FIELDS = {'name_color', 'profile_color', 'emoji_status', 'birthday', 'personal_channel', 'identity', 'photo', 'main_tab'}
PROFILE_TABS={'posts':t.ProfileTabPosts,'gifts':t.ProfileTabGifts,'media':t.ProfileTabMedia,'files':t.ProfileTabFiles,
              'music':t.ProfileTabMusic,'voice':t.ProfileTabVoice,'links':t.ProfileTabLinks,'gifs':t.ProfileTabGifs}
_design_lock = threading.RLock()
MAX_LOCAL_PHOTO_BYTES = 64 * 1024 * 1024


def validate(field, value):
    if field not in FIELDS:
        raise ValueError('Unknown profile setting.')
    if value is None:
        return None
    if field=='main_tab':
        if not isinstance(value,str) or value not in PROFILE_TABS:raise ValueError('Invalid profile tab.')
        return value
    if field=='emoji_status' and isinstance(value,dict):
        if set(value)!={'document_id','until'}:raise ValueError('Invalid emoji status.')
        ident=validate(field,value['document_id']);until=value['until']
        if ident is None or type(until) is not int or not 0<until<=2147483647:raise ValueError('Invalid emoji status expiry.')
        return {'document_id':ident,'until':until}
    if field == 'identity':
        if not isinstance(value, dict) or set(value) != {'first_name', 'last_name', 'about'}:
            raise ValueError('Invalid profile details.')
        result = {}
        for key, text in value.items():
            if not isinstance(text, str) or len(text) > (4096 if key == 'about' else 256):
                raise ValueError('Profile text is too long.')
            if any(ord(char) < 32 and not (key == 'about' and char in '\n\t') or ord(char) == 127 for char in text):
                raise ValueError('Invalid profile text.')
            result[key] = text if key == 'about' else text.strip()
        if not result['first_name']:
            raise ValueError('A first name is required.')
        return result
    if field == 'photo':
        # Only generated basenames, never arbitrary paths from an imported file.
        if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}\.image', value):
            raise ValueError('Invalid local profile photo.')
        return value
    if field in ('name_color', 'profile_color'):
        if not isinstance(value, dict) or set(value) - {'color', 'background_emoji_id'}:
            raise ValueError('Invalid color palette.')
        color, emoji = value.get('color'), value.get('background_emoji_id')
        if color is not None and (type(color) is not int or not 0 <= color <= 65535):
            raise ValueError('Invalid color palette.')
        if emoji is not None and (type(emoji) is not int or not 0 < emoji < 2**63):
            raise ValueError('Invalid custom emoji.')
        return {'color': color, 'background_emoji_id': emoji} if color is not None or emoji is not None else None
    if field == 'birthday':
        if not isinstance(value, dict) or set(value) - {'day', 'month', 'year'}:
            raise ValueError('Invalid birthday.')
        day, month, year = value.get('day'), value.get('month'), value.get('year')
        if type(day) is not int or type(month) is not int or year is not None and type(year) is not int:
            raise ValueError('Invalid birthday.')
        if year is not None and not 1900 <= year <= date.today().year:
            raise ValueError('Invalid birthday year.')
        parsed = date(year if year is not None else 2000, month, day)
        if year is not None and parsed > date.today():
            raise ValueError('Birthday cannot be in the future.')
        return {'day': day, 'month': month, 'year': year}
    if type(value) is not int or value == 0 or not -(2**63) < value < 2**63:
        raise ValueError('Invalid Telegram identifier.')
    if field == 'emoji_status' and value < 0:
        raise ValueError('Invalid custom emoji.')
    return value


def load_design(path, account):
    raw = read_json(path, {}).get(account, {})
    result = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            try:
                result[key] = validate(key, value)
            except (ValueError, TypeError, OverflowError):
                continue
    return result


def configure_design(backend, root, account):
    backend.profile_design_path = Path(root) / 'profile-designs.json'
    backend.profile_design_account = account
    backend.local_profile_design = load_design(backend.profile_design_path, account)


def save_design(backend, field, value, *, remove=False):
    with _design_lock:
        design = dict(getattr(backend, 'local_profile_design', {}))
        if remove:
            design.pop(field, None)
        else:
            design[field] = validate(field, value)
        _write_design(backend, design)


def _write_design(backend, design):
    if design == getattr(backend, 'local_profile_design', {}):
        return
    path = getattr(backend, 'profile_design_path', None)
    if path is not None:
        data = read_json(path, {})
        account = backend.profile_design_account
        if design:
            data[account] = design
        else:
            data.pop(account, None)
        write_json(path, data)
    backend.local_profile_design = design


def clear_design(backend):
    with _design_lock:
        previous = local_photo(backend, 'me')
        changed = bool(getattr(backend, 'local_profile_design', {}))
        _write_design(backend, {})
        _remove_photo(previous)
    callback = getattr(backend, 'on_change', None)
    identity = getattr(getattr(backend, 'account_profile', None), 'user_id', None)
    if changed and callback and identity is not None:
        callback('accents', identity)


def purge_account_customization(root, account):
    """Forget one logged-out account's local views, preserving shared resources."""
    root = Path(root)
    selectors = {
        'profile-designs.json': lambda key: key == account,
        'local-pins.json': lambda key: key == account,
        'wallpapers.json': lambda key: key.startswith(account + ':'),
        'translations.json': lambda key: key.startswith(account + ':'),
        'chat-themes.json': lambda key: key.startswith(account + ':') or key.startswith('wallpaper:' + account + ':'),
    }
    with _design_lock:
        for filename, selected in selectors.items():
            path = root / filename
            data = read_json(path, {})
            updated = {key: value for key, value in data.items() if not selected(key)}
            if updated != data:
                write_json(path, updated)
        # Photos are owned by exactly one account; theme/background resources
        # may be shared by other accounts or layouts and are deliberately kept.
        base = root / 'profile-photos'
        directory = base / hashlib.sha256(account.encode('utf-8')).hexdigest()
        if not base.is_symlink() and not directory.is_symlink() and directory.is_dir():
            for path in directory.iterdir():
                if re.fullmatch(r'[a-f0-9]{32}\.image', path.name):
                    _remove_photo(path)
            try:
                directory.rmdir()
            except OSError:
                pass


def _photo_folder(backend):
    path = getattr(backend, 'profile_design_path', None)
    account = getattr(backend, 'profile_design_account', None)
    if path is None or not isinstance(account, str):
        raise ValueError('Local profile storage is not available.')
    digest = hashlib.sha256(account.encode('utf-8')).hexdigest()
    return Path(path).parent / 'profile-photos' / digest


def local_photo(backend, peer):
    """Resolve an owned photo for this account without an extra Telegram request."""
    profile = getattr(backend, 'account_profile', None)
    identity = getattr(profile, 'user_id', None)
    if peer not in ('me', 'self') and not isinstance(peer, t.InputPeerSelf):
        from telethon.utils import get_peer_id
        try:
            if identity is None or get_peer_id(peer) != identity:
                return None
        except (TypeError, ValueError):
            return None
    value = getattr(backend, 'local_profile_design', {}).get('photo')
    if value is None:
        return None
    try:
        path = _photo_folder(backend) / validate('photo', value)
        # A local settings file cannot redirect the profile viewer outside its folder.
        if path.is_symlink() or path.resolve().parent != _photo_folder(backend).resolve():
            return None
        return str(path) if path.is_file() else None
    except (OSError, ValueError):
        return None


def _remove_photo(path):
    if path:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass  # A viewer on Windows may briefly still have the old image open.


def _copy_photo(backend, filename):
    """Copy and validate off the UI/network thread, with bounded file reads."""
    from PIL import Image
    import uuid
    from .backend import attachment_path
    source = attachment_path(filename)
    directory = _photo_folder(backend)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = directory / (uuid.uuid4().hex + '.image')
    descriptor, temporary = tempfile.mkstemp(prefix='photo-', dir=directory)
    try:
        with os.fdopen(descriptor, 'wb') as output, source.open('rb') as original:
            if not stat.S_ISREG(os.fstat(original.fileno()).st_mode):
                raise ValueError('Choose a regular image file.')
            size = 0
            while block := original.read(256 * 1024):
                size += len(block)
                if size > MAX_LOCAL_PHOTO_BYTES:
                    raise ValueError('Profile image exceeds 64 MB.')
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        with Image.open(temporary) as image:
            if image.format not in ('PNG', 'JPEG'):
                raise ValueError('Choose a PNG or JPEG image.')
            image.verify()
        os.replace(temporary, target)
        return target
    finally:
        Path(temporary).unlink(missing_ok=True)


async def apply_profile_identity(backend, first, last, about, synchronize=True):
    value = validate('identity', {'first_name': first, 'last_name': last, 'about': about})
    if synchronize:
        result = await backend.update_profile(value['first_name'], value['last_name'], value['about'])
        if result is False:
            raise ValueError('Telegram did not accept the profile change.')
        if isinstance(result, t.User):
            backend.account_profile.remember(result)
        save_design(backend, 'identity', None, remove=True)
    else:
        save_design(backend, 'identity', value)


async def apply_profile_photo(backend, filename, synchronize=True):
    if synchronize:
        result = await backend.update_photo(filename)
        if result is False:
            raise ValueError('Telegram did not accept the profile photo.')
        previous = local_photo(backend, 'me')
        save_design(backend, 'photo', None, remove=True)
        _remove_photo(previous)
        return
    copy = asyncio.create_task(asyncio.to_thread(_copy_photo, backend, filename))
    try:
        path = await asyncio.shield(copy)
    except asyncio.CancelledError:
        # to_thread keeps running after cancellation: reclaim its eventual output.
        def cleanup(task):
            if not task.cancelled() and task.exception() is None:
                _remove_photo(task.result())
        copy.add_done_callback(cleanup)
        raise
    try:
        previous = local_photo(backend, 'me')
        save_design(backend, 'photo', path.name)
    except BaseException:
        _remove_photo(path)
        raise
    _remove_photo(previous)


def refresh_profile_photos(app, account, peer):
    """Invalidate only this account's own avatar, preserving other cached photos."""
    if account != app.ui_account:
        return
    key = (account, peer, 'avatar')
    getattr(app, 'avatar_images', {}).pop(key, None)
    getattr(app, 'preview_cache', {}).pop(key, None)
    getattr(app, '_avatar_status', {}).pop((account, peer), None)
    getattr(app, 'preview_failed', set()).discard(key)
    if hasattr(app, 'load_avatars'):
        app.load_avatars()
    if getattr(app, 'active', None) == peer and hasattr(app, 'refresh_header'):
        app.refresh_header()


def overlay_profile(backend, profile):
    if profile['id'] != backend.account_profile.user_id:
        return profile
    design = getattr(backend, 'local_profile_design', {})
    result = dict(profile)
    for field, value in design.items():
        if field == 'identity' and value is not None:
            result.update(value)
            result['name'] = ' '.join(part for part in (value['first_name'], value['last_name']) if part)
        elif field == 'name_color':
            result['color'] = t.PeerColor(**value) if value is not None else None
        elif field == 'profile_color':
            result[field] = t.PeerColor(**value) if value is not None else None
        elif field == 'emoji_status':
            result[field] = status_object(value)
        elif field=='main_tab':
            result[field]=PROFILE_TABS[value]() if value is not None else None
        elif field == 'birthday':
            result[field] = t.Birthday(**value) if value is not None else None
        elif field == 'personal_channel':
            from telethon.utils import resolve_id
            result['personal_channel_id'] = resolve_id(value)[0] if value is not None else None
    result['local_profile_fields'] = tuple(design)
    return result


def overlay_sender(backend, identity, style):
    if identity != backend.account_profile.user_id:
        return style
    design = getattr(backend, 'local_profile_design', {})
    color, pattern, status = style
    if 'name_color' in design:
        selected = design['name_color'] or {}
        color, pattern = selected.get('color'), selected.get('background_emoji_id')
    if 'emoji_status' in design:
        status = design['emoji_status']
        if isinstance(status,dict):status=status['document_id'] if status['until']>datetime.now(timezone.utc).timestamp() else None
    return color, pattern, status


async def color_options(backend, profile=False):
    request = f.help.GetPeerProfileColorsRequest if profile else f.help.GetPeerColorsRequest
    result = await cached(backend, ('profile-colors' if profile else 'name-colors', getattr(backend, '_config_epoch', 0)),
                          lambda: backend.client(request(hash=0)), ttl=3600)
    return [item for item in result.colors if not getattr(item, 'hidden', False)]


def status_object(value):
    if isinstance(value,dict):
        until=datetime.fromtimestamp(value['until'],timezone.utc)
        return t.EmojiStatus(value['document_id'],until=until) if until>datetime.now(timezone.utc) else t.EmojiStatusEmpty()
    return t.EmojiStatus(value) if value is not None else t.EmojiStatusEmpty()


async def set_native(backend, field, value):
    value = validate(field, value)
    if field in ('identity', 'photo'):
        raise ValueError('Use the profile identity or photo action.')
    if field in ('name_color', 'profile_color'):
        request = f.account.UpdateColorRequest(for_profile=field == 'profile_color',
                                               color=t.PeerColor(**value) if value is not None else None)
    elif field == 'emoji_status':
        request = f.account.UpdateEmojiStatusRequest(status_object(value))
    elif field=='main_tab':
        if value is None:raise ValueError('Choose a profile tab.')
        request=f.account.SetMainProfileTabRequest(PROFILE_TABS[value]())
    elif field == 'birthday':
        request = f.account.UpdateBirthdayRequest(t.Birthday(**value) if value is not None else None)
    else:
        if value is None:
            channel = t.InputChannelEmpty()
        else:
            peer = await backend.client.get_input_entity(value)
            if not isinstance(peer, t.InputPeerChannel):
                raise ValueError('Choose a channel.')
            channel = t.InputChannel(peer.channel_id, peer.access_hash)
        request = f.account.UpdatePersonalChannelRequest(channel)
    result = await backend.client(request)
    if result is False:
        raise ValueError('Telegram did not accept the profile change.')
    return result


async def apply_profile_design(backend, field, value, synchronize=True):
    value = validate(field, value)
    if synchronize:
        await set_native(backend, field, value)
        save_design(backend, field, None, remove=True)
    else:
        save_design(backend, field, value)
    if backend.on_change and backend.account_profile.user_id is not None:
        backend.on_change('accents', backend.account_profile.user_id)


def open_profile_customization(app):
    import tkinter as tk
    from tkinter import ttk
    from .app_dialogs import Choice, scrollable
    from .i18n import tr
    if app.demo or app.busy:
        return
    account, backend = app.ui_account, app.service.backend
    window, outer = app.dialog(label('Profile design', 'Diseño del perfil'), '600x720')
    explanation = label('Compatible changes sync with Telegram. Premium and server permissions still apply.',
        'Los cambios compatibles se sincronizan con Telegram. Se respetan Premium y los permisos del servidor.') if sync_enabled(app.preferences) else label(
        'Local preview only. Other people and devices continue to see your Telegram profile.',
        'Vista local. Otras personas y dispositivos siguen viendo tu perfil de Telegram.')
    ttk.Label(outer, text=explanation, wraplength=510).pack(fill='x', pady=8)
    frame = scrollable(outer)
    loading = ttk.Label(frame, text=tr('Loading...')); loading.pack(fill='x')
    def valid():
        return window.winfo_exists() and account == app.ui_account and backend is app.service.backend
    def use_server_profile():
        if not valid() or app.busy:
            return
        had_photo = 'photo' in getattr(backend, 'local_profile_design', {})
        try:
            clear_design(backend)
        except OSError as exc:
            app.show_error(exc); return
        window.destroy()
        if had_photo:
            refresh_profile_photos(app, account, backend.account_profile.user_id)
        app.render_messages(False)
        open_profile_customization(app)
    ttk.Button(outer, text=label('Remove local overrides and use Telegram profile',
        'Quitar cambios locales y usar el perfil de Telegram'), command=use_server_profile).pack(fill='x', pady=6)
    def apply(field, value):
        if not valid() or app.busy:
            return
        def done(_):
            if valid():
                app.status.set(tr('Profile updated.'))
                app.render_messages(False)
        app.call(apply_profile_design(backend, field, value, sync_enabled(app.preferences)), done, tr('Saving...'))
    async def fetch():
        if not sync_enabled(app.preferences) or backend.account_profile.premium:
            return await asyncio.gather(backend.profile(), color_options(backend), color_options(backend, True))
        return await backend.profile(), [], []
    def loaded(result):
        if not valid():
            return
        loading.destroy()
        profile, names, profiles = result
        premium_design = not sync_enabled(app.preferences) or backend.account_profile.premium
        for field, title, options in [('name_color', label('Name and reply color', 'Color del nombre y las respuestas'), names),
                                       ('profile_color', label('Profile color', 'Color del perfil'), profiles)]:
            if not premium_design: continue
            group = ttk.LabelFrame(frame, text=title, padding=8); group.pack(fill='x', pady=6)
            current = profile.get('color' if field == 'name_color' else field)
            chosen = [getattr(current, 'background_emoji_id', None)]
            values = [None] + [item.color_id for item in options]
            current_color = getattr(current, 'color', None)
            if current_color not in values:
                values.append(current_color)
            picker = Choice(group, values=[tr('Default') if item is None else str(item) for item in values])
            picker.current(values.index(current_color)); picker.pack(fill='x')
            swatches = ttk.Frame(group); swatches.pack(fill='x', pady=5)
            for item in options:
                colors = getattr(getattr(item, 'colors', None), 'colors', None) or getattr(getattr(item, 'colors', None), 'palette_colors', None) or []
                if colors:
                    tk.Button(swatches, text=str(item.color_id), bg=f'#{colors[0] & 0xffffff:06x}',
                        command=lambda ident=item.color_id, choice=picker, ids=values:choice.current(ids.index(ident))).pack(side='left')
            status = tk.StringVar(value=str(chosen[0] or '—'))
            ttk.Label(group, textvariable=status).pack(anchor='w')
            def pick(chosen=chosen, status=status):
                def selected(document):
                    if valid():
                        chosen[0] = document.id; status.set(str(document.id))
                app.telegram_picker(True, selected)
            ttk.Button(group, text=label('Choose emoji pattern', 'Elegir patrón de emoji'), command=pick).pack(side='left')
            ttk.Button(group, text=tr('Remove'), command=lambda choice=chosen, text=status:(choice.__setitem__(0, None), text.set('—'))).pack(side='left')
            ttk.Button(group, text=tr('Save'), command=lambda key=field, choice=picker, ids=values, emoji=chosen:apply(key,
                {'color': ids[choice.current()], 'background_emoji_id': emoji[0]})).pack(side='right')
        if premium_design:
            group = ttk.LabelFrame(frame, text=label('Emoji status', 'Estado de emoji'), padding=8); group.pack(fill='x', pady=6)
            durations=[0,3600,7200,28800,172800,604800]
            duration=Choice(group,values=[tr(v) for v in ('Sin caducidad','1 hora','2 horas','8 horas','2 días','1 semana')]);duration.current(0);duration.pack(fill='x',pady=4)
            def status_selected(document):
                if not valid():return
                seconds=durations[duration.current()]
                apply('emoji_status',{'document_id':document.id,'until':int(datetime.now(timezone.utc).timestamp())+seconds} if seconds else document.id)
            ttk.Button(group, text=tr('Custom emoji'), command=lambda:app.telegram_picker(True, status_selected)).pack(side='left')
            ttk.Button(group, text=tr('Remove'), command=lambda:apply('emoji_status', None)).pack(side='right')
        group=ttk.LabelFrame(frame,text=tr('Pestaña principal del perfil'),padding=8);group.pack(fill='x',pady=6)
        tabs=list(PROFILE_TABS);titles=('Publicaciones','Regalos','Multimedia','Archivos','Música','Voz','Enlaces','GIFs')
        main=Choice(group,values=[tr(value) for value in titles]);main.pack(fill='x')
        chosen=next((key for key,cls in PROFILE_TABS.items() if isinstance(profile.get('main_tab'),cls)),None)
        main.set(tr('Elegir pestaña')) if chosen is None else main.current(tabs.index(chosen))
        ttk.Button(group,text=tr('Save'),command=lambda:apply('main_tab',tabs[main.current()]) if main.current()>=0 else None).pack(anchor='e')
        ttk.Button(group,text=tr('Ver mi perfil y contenido público'),command=app.show_my_profile).pack(fill='x',pady=4)
        ttk.Button(group,text=tr('Privacy'),command=app.privacy_dialog).pack(fill='x')
        group = ttk.LabelFrame(frame, text=label('Birthday · DD/MM or DD/MM/YYYY', 'Cumpleaños · DD/MM o DD/MM/AAAA'), padding=8); group.pack(fill='x', pady=6)
        birthday = profile.get('birthday')
        text = f'{birthday.day:02d}/{birthday.month:02d}' + (f'/{birthday.year}' if birthday.year else '') if birthday else ''
        value = tk.StringVar(value=text)
        ttk.Entry(group, textvariable=value).pack(fill='x')
        def save_birthday():
            try:
                parts = [int(item) for item in value.get().strip().split('/')]
                if len(parts) not in (2, 3):
                    raise ValueError('DD/MM or DD/MM/YYYY')
                selected = validate('birthday', {'day': parts[0], 'month': parts[1], 'year': parts[2] if len(parts) == 3 else None})
            except ValueError as exc:
                app.show_error(exc); return
            apply('birthday', selected)
        ttk.Button(group, text=tr('Save'), command=save_birthday).pack(side='left')
        ttk.Button(group, text=tr('Remove'), command=lambda:apply('birthday', None)).pack(side='right')
        group = ttk.LabelFrame(frame, text=tr('Personal channel'), padding=8); group.pack(fill='x', pady=6)
        channels = [None] + [chat for chat in app.chats if chat.kind == 'channel' and getattr(getattr(chat, 'entity', None), 'creator', False) and (getattr(chat.entity, 'username', None) or any(getattr(u, 'active', False) for u in (getattr(chat.entity, 'usernames', None) or ())))]
        choice = Choice(group, values=[label('None', 'Ninguno')] + [chat.name for chat in channels[1:]])
        from telethon.utils import resolve_id
        current_channel = profile.get('personal_channel_id')
        selected = next((index for index, chat in enumerate(channels) if chat is not None and resolve_id(chat.id)[0] == current_channel), 0)
        choice.current(selected); choice.pack(fill='x')
        ttk.Button(group, text=tr('Save'), command=lambda:apply('personal_channel', channels[choice.current()].id if choice.current() else None)).pack(anchor='e')
        ttk.Label(group, text=label('Telegram only accepts an eligible channel you own.', 'Telegram solo acepta un canal propio que cumpla sus requisitos.'), wraplength=460).pack(fill='x')
    app.worker.submit(fetch(), loaded, lambda exc:app.show_error(exc) if valid() else None)
