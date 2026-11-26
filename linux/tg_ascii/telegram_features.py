"""Telegram RPC features. Mutations are called only by explicit GUI actions."""
from dataclasses import dataclass
from pathlib import Path
import asyncio
import os
import re
import tempfile

from telethon import functions, types, utils
from .auth import normalize_phone
from .i18n import tr
from .transfers import DownloadProgress, transfer_timeout, tracked_transfer

DOWNLOAD_IDLE_TIMEOUT=60
DOWNLOAD_CONCURRENCY=4


@dataclass
class Story:
    peer: object
    id: int
    name: str
    caption: str
    media: object


def title_text(value):
    return getattr(value, 'text', str(value))


@dataclass(frozen=True)
class CompiledFolder:
    excluded: frozenset
    included: frozenset
    exclude_archived: bool
    exclude_read: bool
    exclude_muted: bool
    kinds: frozenset
    contacts: bool
    non_contacts: bool


def compile_folder(folder):
    """Snapshot filter rules once per render, without caching mutable TL objects."""
    if folder is None:
        return None
    return CompiledFolder(
        frozenset(utils.get_peer_id(peer) for peer in getattr(folder, 'exclude_peers', [])),
        frozenset(utils.get_peer_id(peer) for peers in (folder.include_peers, folder.pinned_peers) for peer in peers),
        bool(getattr(folder, 'exclude_archived', False)), bool(getattr(folder, 'exclude_read', False)),
        bool(getattr(folder, 'exclude_muted', False)),
        frozenset(kind for kind, flag in (('bot', 'bots'), ('group', 'groups'), ('channel', 'broadcasts'))
                  if getattr(folder, flag, False)),
        bool(getattr(folder, 'contacts', False)), bool(getattr(folder, 'non_contacts', False)))


def in_chat_list(chat, folder, compiled, archive_view=False):
    """1.5.5: like Telegram, "All chats" leaves archived chats out (they have
    their own list); a custom folder keeps following its own rules."""
    if archive_view:
        return bool(getattr(chat, 'archived', False))
    if folder is None and getattr(chat, 'archived', False):
        return False
    return matches_folder(chat, folder, compiled)


def matches_folder(chat, folder, compiled=None):
    if folder is None:
        return True
    rules = compiled if compiled is not None else compile_folder(folder)
    if chat.id in rules.excluded:
        return False
    if chat.id in rules.included:
        return True
    if rules.exclude_archived and chat.archived:
        return False
    if rules.exclude_read and not (chat.unread or getattr(chat,'unread_mark',False)):
        return False
    if rules.exclude_muted and chat.muted:
        return False
    if chat.kind in ('bot', 'group', 'channel'):
        return chat.kind in rules.kinds
    return rules.contacts if chat.contact else rules.non_contacts


from .folder_features import FolderFeatures
from .profile_details import ProfileDetails, profile_fields


class TelegramFeatures(ProfileDetails, FolderFeatures):
    async def contacts(self):
        result = await self.client(functions.contacts.GetContactsRequest(hash=0))
        return result.users

    async def add_contact(self, first, last, phone):
        if not first.strip():
            raise ValueError(tr('El nombre es obligatorio.'))
        number = normalize_phone(phone)
        result = await self.client(functions.contacts.ImportContactsRequest([
            types.InputPhoneContact(client_id=0, phone=number, first_name=first.strip(), last_name=last.strip())]))
        if result.retry_contacts:
            raise ValueError(tr('Telegram pide reintentar mas tarde.'))
        if not result.users:
            raise ValueError(tr('No se encontro una cuenta accesible con ese numero.'))
        return result.users[0]

    async def resolve_chat(self, value):
        from .backend import Chat
        if isinstance(value, str):
            value = value.strip()
            if not value or value.startswith(('http:', 'https:', 'tg:')):
                raise ValueError(tr('Introduce un @usuario o telefono internacional.'))
        entity = await self.client.get_entity(value)
        from .capability_cache import remember
        remember(self, entity)
        kind = 'bot' if getattr(entity,'bot',False) else 'channel' if getattr(entity,'broadcast',False) else 'user' if isinstance(entity,types.User) else 'group'
        return Chat(utils.get_peer_id(entity), utils.get_display_name(entity), kind=kind,
                    member=not bool(getattr(entity,'left',False) or getattr(entity,'kicked',False)) if kind in ('group','channel') else None, entity=entity)

    async def create_group(self, title, users):
        from .backend import Chat
        if not title.strip() or not users:
            raise ValueError(tr('Escribe un titulo y selecciona participantes.'))
        peers = [await self.client.get_input_entity(user) for user in dict.fromkeys(users)]
        result = await self.client(functions.messages.CreateChatRequest(users=peers, title=title.strip()))
        # Recent Telegram layers wrap Updates in messages.InvitedUsers.
        updates = getattr(result, 'updates', result)
        chats = getattr(updates, 'chats', [])
        if not chats:
            raise ValueError(tr('Telegram no devolvio el grupo. Actualiza antes de reintentar.'))
        chat = chats[0]
        missing = getattr(result, 'missing_invitees', [])
        return Chat(utils.get_peer_id(chat), chat.title, kind='group', member=True, entity=chat), len(missing)

    async def profile(self, peer='me'):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            sess = self.secret_chats.session_for_peer(peer)
            info = self.secret_chats.chat_info(peer)
            try:
                base = await self.profile(sess.user_id)
            except Exception:
                base = {
                    'id': peer,
                    'name': sess.user_name or str(sess.user_id),
                    'first_name': sess.user_name or '',
                    'last_name': '',
                    'username': '',
                    'phone': '',
                    'about': '',
                    'is_user': True,
                    'bot': False,
                }
            return {
                **base,
                'id': peer,
                'user_id': sess.user_id,
                'name': f"🔒 {base.get('name') or sess.user_name}",
                'is_secret': True,
                'secret': info,
            }
        entity = await self.client.get_entity(peer)
        about = ''
        full = None
        if isinstance(entity, types.User):
            result = await self.client(functions.users.GetFullUserRequest(entity))
            full = result.full_user
            about = full.about or ''
        elif isinstance(entity, types.Channel):
            result = await self.client(functions.channels.GetFullChannelRequest(entity))
            full = result.full_chat
            about = full.about or ''
        elif isinstance(entity, types.Chat):
            result = await self.client(functions.messages.GetFullChatRequest(entity.id))
            full = result.full_chat
            about = getattr(full, 'about', '') or ''
        if full is not None:
            records=getattr(result,'users',()) if isinstance(entity,types.User) else getattr(result,'chats',())
            entity=next((current for current in records if type(current) is type(entity) and current.id==entity.id),entity)
        from .capability_cache import remember
        remember(self, entity, full)
        # Full-user data is authoritative, including photo removal/privacy changes.
        # Prefer the personal override, then the public photo, then its fallback.
        photo=next((value for value in (getattr(full,'personal_photo',None),
                   getattr(full,'profile_photo',None),getattr(full,'fallback_photo',None))
                   if isinstance(value,types.Photo)),None) if isinstance(entity,types.User) else None
        from .profile_customization import overlay_profile
        from .telegram_actions import peer_activity
        return overlay_profile(self, {**profile_fields(entity, full), 'id': utils.get_peer_id(entity), 'name': utils.get_display_name(entity),
                'first_name': getattr(entity, 'first_name', '') or '',
                'last_name': getattr(entity, 'last_name', '') or '',
                'username': getattr(entity, 'username', '') or '',
                'phone': getattr(entity, 'phone', '') or '', 'about': about,
                'display_photo':photo,'full_photo_known':isinstance(entity,types.User),
                'photo_id':getattr(photo,'id',None) if isinstance(entity,types.User) else getattr(getattr(entity,'photo',None),'photo_id',None),
                'deleted':bool(getattr(entity,'deleted',False)),
                'birthday': getattr(full, 'birthday', None), 'emoji_status': getattr(entity, 'emoji_status', None),
                # 1.4: private contact note and personal photo (visible only to you).
                'note': getattr(getattr(full, 'note', None), 'text', '') or '',
                'personal_photo': isinstance(getattr(full, 'personal_photo', None), types.Photo),
                'profile_color': getattr(entity, 'profile_color', None), 'color': getattr(entity, 'color', None), 'wallpaper': getattr(full, 'wallpaper', None),
                'chat_theme': getattr(full, 'theme', None), 'theme_emoticon': getattr(full, 'theme_emoticon', None),
                'activity': peer_activity(entity),
                'entity': entity, 'is_user': isinstance(entity, types.User), 'bot': bool(getattr(entity, 'bot', False))})

    async def update_profile(self, first, last, about):
        if not first.strip():
            raise ValueError(tr('El nombre es obligatorio.'))
        return await self.client(functions.account.UpdateProfileRequest(
            first_name=first.strip(), last_name=last.strip(), about=about))

    async def update_username(self, username):
        username = username.strip().lstrip('@')
        if username and not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{4,31}', username):
            raise ValueError(tr('El usuario debe tener de 5 a 32 letras, numeros o guiones bajos.'))
        return await self.client(functions.account.UpdateUsernameRequest(username))

    @tracked_transfer
    async def update_photo(self, filename):
        from .backend import attachment_path
        path = attachment_path(filename)
        if path.suffix.lower() not in ('.jpg', '.jpeg', '.png'):
            raise ValueError(tr('Elige una imagen PNG o JPEG.'))
        with path.open('rb') as stream:
            async with transfer_timeout() as report:
                uploaded = await self.client.upload_file(stream,progress_callback=report)
                return await self.client(functions.photos.UploadProfilePhotoRequest(file=uploaded))

    async def pin(self, peer, pinned):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            sess = self.secret_chats.session_for_peer(peer)
            sess.pinned = bool(pinned)
            self.secret_chats._save()
            self.secret_chats._emit_dialogs()
            return True
        entity = await self.client.get_input_entity(peer)
        return await self.client(functions.messages.ToggleDialogPinRequest(
            peer=types.InputDialogPeer(entity), pinned=pinned))

    async def move_pinned(self, peer, direction, archived=False):
        from .pin_order import move_pinned
        await move_pinned(self.client, peer, direction, archived)

    async def stories(self):
        results, state = [], None
        for page in range(10):
            response = await self.client(functions.stories.GetAllStoriesRequest(next=True if page else None, state=state))
            entities = {utils.get_peer_id(e): e for e in response.users + response.chats}
            for peer_stories in response.peer_stories:
                peer = peer_stories.peer
                name = utils.get_display_name(entities.get(utils.get_peer_id(peer))) or str(utils.get_peer_id(peer))
                stories = peer_stories.stories
                skipped = [s.id for s in stories if isinstance(s, types.StoryItemSkipped)]
                if skipped:
                    full = await self.client(functions.stories.GetStoriesByIDRequest(peer, skipped))
                    stories = [s for s in stories if not isinstance(s, types.StoryItemSkipped)] + full.stories
                for story in stories:
                    if isinstance(story, types.StoryItem):
                        results.append(Story(peer, story.id, name, story.caption or '', story.media))
            if not response.has_more:
                break
            state = response.state
        return results

    @tracked_transfer
    async def download_media(self, media, destination, progress=None, thumbnail=False, *, quality='original'):
        """Download atomically; progress is absolute bytes for the current attempt.

        Cancellation removes this attempt's partial file. A retry starts at
        zero; no byte-range resumption is implied by this API.
        """
        if quality not in ('original', 'display'):raise ValueError('Unknown media quality')
        from .secret_chats import SecretMedia
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        slots=getattr(self,'_download_slots',None)
        if slots is None:slots=self._download_slots=asyncio.Semaphore(__import__('tg_ascii.resources',fromlist=['x']).network_slots(DOWNLOAD_CONCURRENCY))
        progress_state = DownloadProgress(progress)
        if isinstance(media, SecretMedia) and hasattr(self, 'secret_chats'):
            # The existing secret-media cipher processes one complete file in
            # memory. Bound that cost separately instead of allowing every
            # visible attachment to allocate another full plaintext/ciphertext.
            secret_slots=getattr(self,'_secret_download_slots',None)
            if secret_slots is None:secret_slots=self._secret_download_slots=asyncio.Semaphore(1)
            async with secret_slots, slots:
                fd, temporary = tempfile.mkstemp(prefix='.tg-download-', suffix=target.suffix, dir=target.parent)
                os.close(fd)
                try:
                    async with transfer_timeout(progress_state.report, DOWNLOAD_IDLE_TIMEOUT) as report:
                        async def secret_progress(current, total):
                            # Encrypted transport padding is not part of the
                            # user-visible file. Preserve unknown totals.
                            size = media.size if not thumbnail and media.size > 0 else total
                            await report(min(current, size) if size else current, size)
                        result = await self.secret_chats.download_media(media, temporary, progress=secret_progress, thumbnail=thumbnail)
                    if result is None:
                        return None
                    size = Path(temporary).stat().st_size
                    await progress_state.report(size, size)
                    os.replace(temporary, target)
                    return str(target)
                finally:
                    Path(temporary).unlink(missing_ok=True)
        thumb=None
        if not thumbnail and quality=='display':
            from .media_quality import photo_variant
            thumb=photo_variant(media)
        if thumbnail:
            from .media_formats import original_thumbnail_supported
            document=getattr(media,'document',None) or getattr(media,'photo',None) or media
            thumbs=getattr(document,'thumbs',None) or getattr(document,'sizes',None) or []
            candidates=[item for item in thumbs if isinstance(item,(types.PhotoSize,types.PhotoCachedSize,types.PhotoSizeProgressive))]
            if candidates:
                area=lambda item:item.w*item.h
                if isinstance(document,types.Photo):
                    # Tiles need a modest preview, not the largest photo. Keep
                    # the full-resolution download unchanged for opening/zoom.
                    large_enough=[item for item in candidates if max(item.w,item.h)>=320]
                    thumb=(min(large_enough,key=area) if large_enough else max(candidates,key=area)).type
                else:
                    thumb=max(candidates,key=area).type
            elif isinstance(document,types.Document) and original_thumbnail_supported(document):
                if document.size>4*1024*1024: raise ValueError(tr('No hay vista previa disponible. Puedes guardar el archivo.'))
            else:
                stripped=next((item for item in thumbs if isinstance(item,types.PhotoStrippedSize)),None)
                if stripped: thumb=stripped.type
                else: raise ValueError(tr('No hay vista previa disponible. Puedes guardar el archivo.'))
        inferred_extension=False
        if not target.suffix and not target.is_file():
            source=getattr(media,'media',None) or media
            extension='.jpg' if thumb is not None else utils.get_extension(source)
            inferred_extension=bool(extension)
            target=target.with_suffix(extension)
        cache_entry=None
        if thumbnail and not inferred_extension:
            # Previews are keyed by immutable Telegram media ids: a hit avoids
            # the network entirely (see media_cache.py).
            from . import media_cache
            cache_entry=media_cache.preview_entry(self,media,thumb,target.suffix)
            if cache_entry is not None and await asyncio.to_thread(media_cache.fetch,cache_entry,target):
                return target
        async def attempt():
            # A FLOOD_WAIT is waited out *outside* the slot, so other
            # accounts/categories keep their concurrency meanwhile.
            nonlocal target
            async with slots:
                await progress_state.restart()
                fd,temporary=tempfile.mkstemp(prefix='.tg-download-',suffix=target.suffix,dir=target.parent)
                try:
                    with os.fdopen(fd,'wb') as stream:
                        # Timeout only when no bytes arrive. A large, active transfer
                        # may legitimately take much longer than a small RPC.
                        async with transfer_timeout(progress_state.report,DOWNLOAD_IDLE_TIMEOUT) as report:
                            async def written_progress(_current,total):
                                await report(stream.tell(),total)
                            result=await self.client.download_media(media,file=stream,
                                progress_callback=written_progress,thumb=thumb)
                        if result is None:
                            raise ValueError(tr('No hay vista previa disponible. Puedes guardar el archivo.'))
                        source=getattr(media,'media',None) or media
                        document=getattr(source,'document',None) or source
                        # Telegram supplies the exact byte size for a full document.
                        # A short final response can look like successful EOF to a
                        # downloader; never publish that incomplete replacement.
                        if thumb is None and isinstance(document,types.Document) and stream.tell()!=document.size:
                            raise OSError('Incomplete Telegram document download')
                        await progress_state.report(stream.tell(),stream.tell())
                    # Keep the previous file intact on cancellation, disconnection or
                    # disk error; consumers never observe a half-downloaded cache file.
                    if inferred_extension:
                        # The user chose the extensionless name, not an existing
                        # suffixed file. Match Telethon's collision-safe naming, at
                        # completion so concurrent downloads choose distinct names.
                        original=target
                        number=1
                        while target.exists() or target.is_symlink():
                            target=original.with_name(f'{original.stem} ({number}){original.suffix}')
                            number+=1
                    os.replace(temporary,target)
                    return target
                finally:
                    Path(temporary).unlink(missing_ok=True)
        from .flood_control import read_with_flood_wait
        result=await read_with_flood_wait(self,'download',attempt)
        if cache_entry is not None:
            from . import media_cache
            added=await asyncio.to_thread(media_cache.store,cache_entry,result)
            await media_cache.prune_once(self,added)
        return result

    async def view_story(self, story):
        await self.client(functions.stories.ReadStoriesRequest(story.peer, max_id=story.id))
        await self.client(functions.stories.IncrementStoryViewsRequest(story.peer, id=[story.id]))

    async def media_message(self, peer, message_id):
        result = await self.client.get_messages(peer, ids=message_id)
        if result is None or not result.media:
            raise ValueError(tr('El archivo ya no esta disponible.'))
        return result
