"""Account-scoped chat backgrounds and opt-in Telegram wallpaper operations."""
import asyncio
import copy
import gzip
import hashlib
import json
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

from tg_ascii.preferences import write_json

COLOR_FIELDS = ('background_color', 'second_background_color', 'third_background_color', 'fourth_background_color')


def wallpaper_options(options, original=None):
    from telethon import types
    settings = copy.copy(original) if original is not None else types.WallPaperSettings()
    if 'colors' in options:
        colors = options['colors']
        if not isinstance(colors, list) or not 1 <= len(colors) <= 4 or not all(
                isinstance(color, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', color) for color in colors):
            raise ValueError('Invalid wallpaper colors')
        for index, field in enumerate(COLOR_FIELDS):
            setattr(settings, field, int(colors[index][1:], 16) if index < len(colors) else None)
    for name in ('blur', 'motion'):
        if name in options:
            setattr(settings, name, bool(options[name]))
    if settings.second_background_color is not None:
        settings.rotation = int(options.get('rotation', settings.rotation or 0)) % 360
    else:
        settings.rotation = None
    if 'intensity' in options:
        settings.intensity = max(-100, min(100, int(options['intensity'])))
    return settings


def web_pattern(source, target, settings):
    """Draw compressed Telegram vector patterns natively in the WebView, using only path geometry."""
    with gzip.open(source, 'rb') as stream:
        data = stream.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024 or re.search(br'<!\s*(?:DOCTYPE|ENTITY)\b', data, re.I):
        raise ValueError('Unsupported pattern')
    source_svg = ET.fromstring(data)
    viewbox = source_svg.get('viewBox')
    if not viewbox:
        viewbox = '0 0 ' + source_svg.get('width', '512') + ' ' + source_svg.get('height', '512')
    if not re.fullmatch(r'[-+0-9.eE, ]{5,100}', viewbox):
        raise ValueError('Unsupported pattern dimensions')
    svg = ET.Element('svg', xmlns='http://www.w3.org/2000/svg', viewBox=viewbox, preserveAspectRatio='xMidYMid slice')
    defs = ET.SubElement(svg, 'defs')
    colors = [getattr(settings, field) for field in COLOR_FIELDS if getattr(settings, field, None) is not None] or [0xd6e2d1]
    gradient = ET.SubElement(defs, 'linearGradient', id='gradient', x2='0', y2='1',
                             gradientTransform=f'rotate({settings.rotation or 0} .5 .5)')
    for index, color in enumerate(colors):
        ET.SubElement(gradient, 'stop', offset=str(index / max(1, len(colors) - 1)),
                      attrib={'stop-color': f'#{color:06x}'})
    ET.SubElement(svg, 'rect', width='100%', height='100%', fill='url(#gradient)')
    intensity = 50 if settings.intensity is None else settings.intensity
    ink = 'white' if intensity < 0 else 'black'
    group = ET.SubElement(svg, 'g', fill=ink, opacity=str(abs(intensity) / 100))
    # Telegram's illustrated patterns export stroke-only paths via simple CSS classes.
    def paint_attributes(declarations):
        attributes = {}
        for prop, value in declarations:
            prop, value = prop.strip(), value.strip()
            if prop in ('stroke', 'fill') and re.fullmatch(r'none|black|white|#[a-fA-F0-9]{3,8}', value):
                attributes[prop] = 'none' if value == 'none' else ink
            elif prop in ('stroke-width', 'stroke-miterlimit') and re.fullmatch(r'\d{1,3}(?:\.\d+)?', value):
                attributes[prop] = value
            elif prop == 'stroke-linecap' and value in ('round', 'butt', 'square'):
                attributes[prop] = value
            elif prop == 'stroke-linejoin' and value in ('round', 'miter', 'bevel'):
                attributes[prop] = value
        return attributes

    classes = {}
    for style in source_svg.iter():
        if style.tag.split('}')[-1] == 'style' and style.text:
            for name, rules in re.findall(r'\.([A-Za-z_][\w-]*)\s*\{([^{}]+)\}', style.text):
                classes[name] = paint_attributes(rule.split(':', 1) for rule in rules.split(';') if ':' in rule)

    def geometry(node, parent):
        tag = node.tag.split('}')[-1]
        if tag not in ('svg', 'g', 'path'):
            return
        dest = ET.SubElement(parent, 'g') if tag == 'g' else parent
        if tag == 'path':
            d = node.get('d', '')
            if not re.fullmatch('[MmZzLlHhVvCcSsQqTtAaEe0-9+.,\\s-]+', d):
                return
            dest = ET.SubElement(parent, 'path', d=d)
            dest.attrib.update(paint_attributes(node.attrib.items()))
            for classname in node.get('class', '').split():
                dest.attrib.update(classes.get(classname, {}))
            if node.get('fill-rule') == 'evenodd':
                dest.set('fill-rule', 'evenodd')
        transform = node.get('transform', '')
        if transform and re.fullmatch(r'(?:(?:matrix|translate|scale|rotate|skewX|skewY)\([-+.0-9eE, ]+\)\s*)+', transform):
            dest.set('transform', transform)
        for child in node:
            geometry(child, dest)
    geometry(source_svg, group)
    if not group.findall('.//path'):
        raise ValueError('Unsupported pattern geometry')
    ET.ElementTree(svg).write(target, encoding='utf-8')


class ChatWallpapers:
    def wallpaper_dir(self, account):
        folder = self.root / 'chat-wallpapers' / hashlib.sha256(account.encode()).hexdigest()
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        return folder

    def purge_chat_wallpapers(self, account):
        shutil.rmtree(self.wallpaper_dir(account), ignore_errors=True)
        self.__dict__.pop('_wallpaper_catalog', None)

    def chat_wallpapers(self, account):
        path = self.wallpaper_dir(account) / 'settings.json'
        try:
            result = json.loads(path.read_text('utf-8'))
        except (OSError, ValueError):
            return {}
        return result if isinstance(result, dict) else {}

    def chat_wallpaper_file(self, account, name, preview=False):
        if self.account != account or not re.fullmatch(r'[a-f0-9]{32}\.(jpg|svg)', str(name)):
            return None
        folder = self.wallpaper_dir(account)
        path = (folder / "previews" if preview else folder) / name
        return path if path.is_file() else None

    async def api_wallpaper_gallery(self, account):
        self.check_active_account(account)
        from telethon import functions, types
        backend = self.backend
        result = await backend.client(functions.account.GetWallPapersRequest(0))
        self.check_active_account(account)
        records = list(result.wallpapers)
        self._wallpaper_catalog = (backend, {str(item.id): item for item in records})
        return [dict(id=str(item.id), name=getattr(item, 'slug', '') or str(item.id),
                     colors=[f'#{getattr(item.settings, field):06x}' for field in COLOR_FIELDS
                             if getattr(getattr(item, 'settings', None), field, None) is not None],
                     has_file=isinstance(item, types.WallPaper), pattern=bool(getattr(item, 'pattern', False)),
                     motion=bool(getattr(getattr(item, 'settings', None), 'motion', False)),
                     blur=bool(getattr(getattr(item, 'settings', None), 'blur', False)),
                     intensity=getattr(getattr(item, 'settings', None), 'intensity', None),
                     rotation=getattr(getattr(item, 'settings', None), 'rotation', None))
                for item in records]

    async def render_chat_wallpaper(self, backend, folder, wallpaper, settings, upload=None):
        from tg_ascii.wallpaper_render import render_wallpaper
        record = SimpleNamespace(settings=settings, document=True, pattern=False) if upload else copy.copy(wallpaper)
        record.settings = settings
        vector = False
        doc = getattr(record, 'document', None)
        if upload:
            source = upload
        elif doc:
            if getattr(doc, 'size', 0) > 12 * 1024 * 1024:
                raise ValueError('Wallpaper is too large')
            source = await backend.download_media(doc, folder / 'source')
            vector = getattr(doc, 'mime_type', '') == 'application/x-tgwallpattern'
        else:
            source = None
        target = folder / (uuid.uuid4().hex + ('.svg' if vector else '.jpg'))
        if vector:
            await asyncio.to_thread(web_pattern, source, target, settings)
        else:
            await asyncio.to_thread(render_wallpaper, record, source, target)
        return target

    async def api_follow_chat_wallpapers(self, account, enabled):
        self.check_active_account(account)
        records = self.chat_wallpapers(account)
        records['_follow'] = bool(enabled)
        write_json(self.wallpaper_dir(account) / 'settings.json', records)
        appearance = self.appearance()
        self.emit('appearance', appearance)
        return appearance

    async def api_remote_chat_wallpaper(self, account, peer):
        from telethon import functions, types
        self.check_active_account(account)
        records = self.chat_wallpapers(account)
        if not (records.get('_follow') or records.get(str(peer), {}).get('sync')):
            return None
        backend = self.backend
        entity = await backend.client.get_input_entity(int(peer))
        if isinstance(entity, types.InputPeerUser):
            response = await backend.client(functions.users.GetFullUserRequest(entity))
            wallpaper = getattr(response.full_user, 'wallpaper', None)
        elif isinstance(entity, types.InputPeerChannel):
            response = await backend.client(functions.channels.GetFullChannelRequest(entity))
            wallpaper = getattr(response.full_chat, 'wallpaper', None)
        else:
            return None
        if not wallpaper:
            return None
        settings = wallpaper_options({}, getattr(wallpaper, 'settings', None))
        identity = hashlib.sha256(bytes(wallpaper)).hexdigest()[:32]
        folder = self.wallpaper_dir(account)
        vector = getattr(getattr(wallpaper, 'document', None), 'mime_type', '') == 'application/x-tgwallpattern'
        name = identity + ('.svg' if vector else '.jpg')
        if not (folder / name).exists():
            with tempfile.TemporaryDirectory(dir=folder) as scratch:
                rendered = await self.render_chat_wallpaper(backend, Path(scratch), wallpaper, settings)
                self.check_active_account(account)
                rendered.replace(folder / name)
        self.check_active_account(account)
        return dict(file=name, motion=bool(settings.motion))

    async def api_apply_chat_wallpaper(self, account, target='all', source='fill', options=None,
                                       sync='', key=None, catalog_id=None, preview=False):
        pending = self.__dict__.setdefault('_writing_wallpapers', set())
        identity = (account, str(target))
        if not preview:
            if identity in pending:
                raise RuntimeError('Wallpaper change in progress')
            pending.add(identity)
        try:
            return await self._apply_chat_wallpaper(account, target, source, options, sync, key, catalog_id, preview)
        finally:
            if not preview:
                pending.discard(identity)

    async def _apply_chat_wallpaper(self, account, target, source, options, sync, key, catalog_id, preview):
        from telethon import types, functions
        self.check_active_account(account)
        if not account or sync not in ('', 'devices', 'both') or (target == 'all' and sync == 'both'):
            raise ValueError('Invalid wallpaper scope')
        target = 'all' if target == 'all' else str(int(target))
        backend = self.backend
        folder = self.wallpaper_dir(account)
        record = types.WallPaperNoFile(0)
        upload = None
        if source == 'gallery':
            owner, catalog = getattr(self, '_wallpaper_catalog', (None, {}))
            if owner is not backend or str(catalog_id) not in catalog:
                raise ValueError('Reopen the wallpaper gallery')
            record = catalog[str(catalog_id)]
        elif source == 'image':
            if key:
                upload = self.staged(key)
            else:
                saved = self.chat_wallpapers(account).get(target, {})
                original_name = saved.get('original', '')
                if not re.fullmatch(r'[a-f0-9]{32}\.jpg', original_name):
                    raise ValueError('Choose an image')
                upload = folder / original_name
        elif source not in ('fill', 'reset', 'interface'):
            raise ValueError('Invalid wallpaper source')
        settings = wallpaper_options(options or {}, getattr(record, 'settings', None))
        with tempfile.TemporaryDirectory(dir=folder) as scratch:
            scratch = Path(scratch)
            original = None
            if upload:
                original = (scratch / await asyncio.to_thread(self.background_image, upload, scratch)) if key else upload
            if source == 'interface' and (sync or target == 'all'):
                raise ValueError('Invalid wallpaper scope')
            target_file = None if source in ('reset', 'interface') else await self.render_chat_wallpaper(
                backend, scratch, record, settings, original)
            self.check_active_account(account)
            if preview:
                if not target_file:
                    raise ValueError('Select a wallpaper')
                previews = folder / 'previews'
                previews.mkdir(mode=0o700, exist_ok=True)
                target_file.replace(previews / target_file.name)
                for expired in sorted(previews.iterdir(), key=lambda path: path.stat().st_mtime, reverse=True)[12:]:
                    expired.unlink(missing_ok=True)
                return dict(file=target_file.name, motion=bool(settings.motion))
            if sync:
                client = backend.client
                peer = None if target == 'all' else await client.get_input_entity(int(target))
                if sync == 'both' and not isinstance(peer, types.InputPeerUser):
                    raise ValueError('Both participants requires a private chat')
                if source == 'reset' and not peer:
                    catalog = await client(functions.account.GetWallPapersRequest(0))
                    record = next((wall for wall in catalog.wallpapers if getattr(wall, 'default', False)
                                   and isinstance(wall, types.WallPaper)), None)
                    if not record:
                        raise ValueError('Select a Telegram wallpaper to restore the default')
                    settings = wallpaper_options({}, record.settings)
                if original:
                    uploaded = await client.upload_file(str(original))
                    record = await client(functions.account.UploadWallPaperRequest(uploaded, 'image/jpeg', settings,
                                                                                    for_chat=True if peer else None))
                if isinstance(record, types.WallPaper):
                    reference = types.InputWallPaper(record.id, record.access_hash)
                elif peer:
                    reference = types.InputWallPaperNoFile(record.id)
                else:
                    raise ValueError('Telegram keeps global solid and gradient backgrounds on this device.')
                self.check_active_account(account)
                if peer:
                    await client(functions.messages.SetChatWallPaperRequest(peer,
                        wallpaper=reference if source != 'reset' else None, settings=settings if source != 'reset' else None,
                        for_both=sync == 'both' or None))
                else:
                    await client(functions.account.InstallWallPaperRequest(reference, settings))
            # Commit to the originating account even if it switched while Telegram was answering.
            if self.account != account and account not in getattr(self.accounts, 'entries', {}):
                raise ValueError('Account removed')
            records = self.chat_wallpapers(account)
            old = records.get(target, {})
            if target_file:
                target_file.replace(folder / target_file.name)
                records[target] = dict(file=target_file.name, motion=bool(settings.motion), sync=sync, source=source,
                                       options=options or {}, catalog_id=str(catalog_id) if source == 'gallery' else None)
                if original:
                    if key:
                        original.replace(folder / original.name)
                    records[target]['original'] = original.name
            elif source == 'interface':
                records[target] = {'interface': True}
            else:
                records.pop(target, None)
            write_json(folder / 'settings.json', records)
            old_file = old.get('file')
            if isinstance(old_file, str) and re.fullmatch(r'[a-f0-9]{32}\.(jpg|svg)', old_file):
                (folder / old_file).unlink(missing_ok=True)
            old_source = old.get('original', '')
            if (re.fullmatch(r'[a-f0-9]{32}\.jpg', old_source) and
                    old_source != records.get(target, {}).get('original')):
                (folder / old_source).unlink(missing_ok=True)
            if upload and key:
                upload.unlink(missing_ok=True)
        self.check_active_account(account)
        appearance = self.appearance()
        if target != 'all' and target in appearance['chats']:
            appearance['chats'].pop(target, None)
            appearance['chat_sync'].pop(target, None)
            return self.save_appearance(appearance)
        self.emit('appearance', appearance)
        return appearance
