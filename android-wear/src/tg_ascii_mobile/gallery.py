"""Paged profile photos for the mobile gallery, scoped to one Telegram session."""
import asyncio
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

from telethon import functions, types
from tg_ascii.profile_media import compose_profile, photo_markup, prepare_profile_photo, profile_history


class ProfileGallery:
    def gallery_backend(self, account):
        if self.locked or not account or self.account != account or self.backend is None:
            raise PermissionError('The active account changed.')
        return self.backend

    async def api_profile_photos(self, peer, account, offset=0):
        backend = self.gallery_backend(account)
        peer, offset = int(peer), max(0, int(offset))
        target = peer
        from tg_ascii.secret_chats import is_secret_peer, secret_chat_id
        if is_secret_peer(peer):
            session = backend.secret_chats.sessions.get(secret_chat_id(peer))
            if not session:
                return {'items': [], 'next': None}
            target = session.user_id
        photos, total = await asyncio.wait_for(profile_history(backend, target, offset, 20), 30)
        if self.gallery_backend(account) is not backend:
            raise PermissionError('The active account changed.')
        cache = self.__dict__.setdefault('gallery_photos', OrderedDict())
        items = []
        for position, photo in enumerate(photos, offset):
            key = (account, peer, photo.id)
            cache[key] = (backend, photo)
            cache.move_to_end(key)
            animated = not photo_markup(photo) and any(isinstance(size, types.VideoSize)
                                                         for size in photo.video_sizes or ())
            items.append({'id': str(photo.id), 'offset': position, 'kind': 'video' if animated else 'image'})
        while len(cache) > 256:
            cache.popitem(last=False)
        cursor = offset + len(photos)
        more = len(photos) == 20 and (total is None or cursor < total)
        return {'items': items, 'next': cursor if more else None}

    async def profile_gallery_file(self, peer, photo_id, account, offset, thumbnail=False):
        backend = self.gallery_backend(account)
        peer, photo_id, offset = int(peer), int(photo_id), max(0, int(offset))
        key = (account, peer, photo_id)
        cached = getattr(self, 'gallery_photos', {}).get(key)
        if not cached or cached[0] is not backend:
            # A very long gallery may have evicted the reference. Verify the ID
            # within its page again so a changed profile never opens another photo.
            await self.api_profile_photos(peer, account, offset // 20 * 20)
            cached = getattr(self, 'gallery_photos', {}).get(key)
        if not cached or cached[0] is not backend:
            return None
        photo = cached[1]
        folder = self.root / 'mobile-avatars' / account / 'history'
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        # The shared downloader renders photos, profile videos and emoji markup.
        # A markup-only picture on mobile uses the mobile sticker thumbnail decoder.
        try:
            path = await prepare_profile_photo(SimpleNamespace(preview_dir=folder), backend, account, peer, photo, thumbnail)
        except ModuleNotFoundError as error:
            if error.name != 'tg_ascii.animation':
                raise
            markup = photo_markup(photo)
            if isinstance(markup, types.VideoSizeEmojiMarkup):
                ident = markup.emoji_id
            else:
                pack = await backend.client(functions.messages.GetStickerSetRequest(markup.stickerset, hash=0))
                if self.gallery_backend(account) is not backend:
                    raise PermissionError('The active account changed.')
                self.remember_documents(pack.documents)
                ident = markup.sticker_id
            if self.gallery_backend(account) is not backend:
                raise PermissionError('The active account changed.')
            symbol = await self.sticker_file(ident)
            path = folder / f'{peer}-{photo_id}-{"thumb" if thumbnail else "full"}.png'
            if not symbol:
                return None
            await asyncio.to_thread(compose_profile, symbol, path, markup.background_colors, 160 if thumbnail else 800)
        if self.gallery_backend(account) is not backend:
            raise PermissionError('The active account changed.')
        return Path(path) if path else None

    async def api_open_profile_photo(self, peer, account, action, photo=None, offset=0):
        if action not in ('save', 'share'):
            raise ValueError('Unknown file action')
        backend = self.gallery_backend(account)
        if photo is None:
            path = await self.avatar_file(int(peer), True)
        else:
            path = await self.profile_gallery_file(peer, photo, account, offset)
        if self.gallery_backend(account) is not backend or not path:
            raise LookupError('No photo.')
        return await self.open_file_with_system(path, action)
