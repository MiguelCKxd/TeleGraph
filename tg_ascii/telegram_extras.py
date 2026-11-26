"""Telegram RPCs for stickers, custom emoji, avatars and notification settings."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from telethon import functions, types
from .i18n import tr
from .transfers import transfer_timeout, tracked_transfer

CATEGORIES = {'private': types.InputNotifyUsers, 'groups': types.InputNotifyChats,
              'channels': types.InputNotifyBroadcasts}


async def notification_reads(client, peers):
    tasks = [asyncio.ensure_future(client(functions.account.GetNotifySettingsRequest(peer))) for peer in peers]
    try:
        return await asyncio.gather(*tasks)
    finally:
        # One failed read must not leave its sibling RPCs running indefinitely.
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def emoji_attribute(document):
    return next((a for a in getattr(document, 'attributes', ()) if isinstance(a, types.DocumentAttributeCustomEmoji)), None)


def sticker_alt(document):
    return next((a.alt for a in getattr(document, 'attributes', ()) if isinstance(a, (types.DocumentAttributeSticker, types.DocumentAttributeCustomEmoji))), '◈')


def custom_entities(text, spans):
    """Offsets are Python character positions; Telegram expects UTF-16 code units."""
    entities, end = [], 0
    for start, stop, document_id, alt in sorted(spans):
        if start < end or start < 0 or stop > len(text) or text[start:stop] != alt or not alt:
            raise ValueError(tr('Custom emoji changed. Insert it again.'))
        entities.append(types.MessageEntityCustomEmoji(len(text[:start].encode('utf-16-le')) // 2,
                        len(alt.encode('utf-16-le')) // 2, document_id))
        end = stop
    return entities


class TelegramExtras:
    async def custom_emoji_documents(self, identifiers):
        from .emoji_documents import documents
        return await documents(self, identifiers)

    async def sticker_packs(self, custom=False):
        from .sticker_search import cached
        async def fetch():
            request = functions.messages.GetEmojiStickersRequest if custom else functions.messages.GetAllStickersRequest
            result = await self.client(request(hash=0))
            return list(getattr(result, 'sets', []))
        return await cached(self,('packs',custom),fetch,60)

    async def sticker_documents(self, pack=None):
        """A pack's documents; None: recent stickers; 'recent_emoji': most used custom
        emoji; 'favourites': favourite stickers (the picker's first pages)."""
        from .sticker_search import cached
        if pack == 'recent_emoji':
            from .emoji_usage import recent_documents
            return await recent_documents(self)
        if pack == 'favourites':
            from .emoji_usage import favourite_stickers
            return await cached(self, ('documents', 'favourites'), lambda: favourite_stickers(self), 30)
        async def fetch():
            if pack is None:
                result = await self.client(functions.messages.GetRecentStickersRequest(hash=0))
                return list(getattr(result, 'stickers', []))
            result = await self.client(functions.messages.GetStickerSetRequest(
                types.InputStickerSetID(pack.id, pack.access_hash), hash=0))
            from .emoji_documents import catalogue
            catalogue(self).remember(result.documents)
            return result.documents
        key=('documents',getattr(pack,'id',None),getattr(pack,'hash',None))
        return await cached(self,key,fetch,300 if pack else 5)

    async def document_pack(self, document):
        if isinstance(document,int):
            docs=await self.custom_emoji_documents([document])
            if not docs: raise ValueError(tr('Pack unavailable.'))
            document=docs[0]
        attribute=next((a for a in getattr(document,'attributes',[]) if isinstance(a,(types.DocumentAttributeSticker,types.DocumentAttributeCustomEmoji))),None)
        if attribute is None or isinstance(attribute.stickerset,types.InputStickerSetEmpty):
            raise ValueError(tr('Pack unavailable.'))
        from .sticker_search import cached
        key=('pack_details',type(attribute.stickerset).__name__,getattr(attribute.stickerset,'id',None),getattr(attribute.stickerset,'short_name',None))
        return await cached(self,key,lambda:self.client(functions.messages.GetStickerSetRequest(attribute.stickerset,hash=0)),60)

    async def install_pack(self, pack):
        result=await self.client(functions.messages.InstallStickerSetRequest(types.InputStickerSetID(pack.id,pack.access_hash),archived=False))
        from .sticker_search import invalidate
        invalidate(self)
        return result

    async def send_sticker(self, peer, document, reply_to=None):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            return await self.secret_chats.send_sticker(peer, document, reply_to=reply_to)
        from telethon import errors, utils
        async def send(item):
            if isinstance(reply_to, types.InputReplyToMessage):
                request = functions.messages.SendMediaRequest(await self.client.get_input_entity(peer),
                    utils.get_input_media(item), '', reply_to=reply_to)
                return await self._structured_sent(request)
            return self.message(await self.client.send_file(peer, item, force_document=False, reply_to=reply_to))
        try:
            return await send(document)
        except (errors.FileReferenceExpiredError,errors.FileReferenceInvalidError,errors.FileReferenceEmptyError):
            # Telegram rejects expired references before sending. Refresh this exact
            # sticker once; never retry timeouts or other ambiguous send failures.
            attribute=next((a for a in getattr(document,'attributes',[]) if isinstance(a,types.DocumentAttributeSticker)),None)
            if attribute is not None and not isinstance(attribute.stickerset,types.InputStickerSetEmpty):
                result=await self.client(functions.messages.GetStickerSetRequest(attribute.stickerset,hash=0))
                documents=result.documents
            else:
                result=await self.client(functions.messages.GetRecentStickersRequest(hash=0))
                documents=result.stickers
            refreshed=next((d for d in documents if d.id==document.id),None)
            if refreshed is None: raise
            return await send(refreshed)

    @tracked_transfer
    async def send_custom(self, peer, text, spans, path=None, progress=None):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            async with transfer_timeout(progress) as report:
                return await self.secret_chats.send_formatted(peer, text, (), spans, path=path, progress=report)
        entities = custom_entities(text, spans)
        from .emoji_usage import note
        note(self, spans, text)
        if path is not None:
            from .backend import attachment_path
            with attachment_path(path).open('rb') as stream:
                async with transfer_timeout(progress) as report:
                    sent = await self.client.send_file(peer, stream, caption=text, formatting_entities=entities,
                                                      force_document=True, progress_callback=report)
        else:
            sent = await self.client.send_message(peer, text, formatting_entities=entities, parse_mode=None)
        return self.message(sent)

    async def avatar(self, peer, destination, entity=None):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            try:
                peer = self.secret_chats.session_for_peer(peer).user_id
            except Exception:
                return None
        from .profile_customization import local_photo
        local = local_photo(self, peer)
        if local is not None:
            return local
        # 1.4: with the dialog's own entity Telethon needs no extra get_entity()
        # RPC per avatar, a photo-less chat needs no request at all, and the
        # small photo is reused across launches by its immutable photo id.
        source = peer
        entry = None
        if entity is not None and hasattr(entity, 'photo'):
            photo = entity.photo
            if photo is None or isinstance(photo, (types.UserProfilePhotoEmpty, types.ChatPhotoEmpty)):
                return None
            source = entity
            from . import media_cache
            entry = media_cache.avatar_entry(self, getattr(photo, 'photo_id', None))
            if entry is not None and await asyncio.to_thread(media_cache.fetch, entry, destination):
                return str(destination)
        from .flood_control import read_with_flood_wait
        path = await read_with_flood_wait(self, 'download', lambda: self.client.download_profile_photo(
            source, file=str(destination), download_big=False))
        if path and entry is not None:
            from . import media_cache
            added = await asyncio.to_thread(media_cache.store, entry, path)
            await media_cache.prune_once(self, added)
        return str(path) if path else None

    async def notification_settings(self):
        settings = await notification_reads(self.client, (constructor() for constructor in CATEGORIES.values()))
        return dict(zip(CATEGORIES, settings))

    def invalidate_notification_policy(self):
        from .sticker_search import invalidate
        cache = getattr(self, '_notification_cache', None)
        if cache is not None:
            invalidate(cache)

    async def save_notification_settings(self, category, values):
        # Optional fields are omitted, so unrelated server settings remain intact.
        allowed = {'show_previews', 'silent', 'mute_until', 'sound', 'stories_muted', 'stories_hide_sender', 'stories_sound'}
        settings = types.InputPeerNotifySettings(**{k: v for k, v in values.items() if k in allowed})
        peer = CATEGORIES[category]() if category in CATEGORIES else types.InputNotifyPeer(await self.client.get_input_entity(int(category)))
        await self.client(functions.account.UpdateNotifySettingsRequest(peer, settings))
        self.invalidate_notification_policy()

    async def notification_policy(self, peer, platform=None):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            try:
                muted = bool(self.secret_chats.session_for_peer(peer).muted)
            except Exception:
                muted = False
            return {'enabled': not muted, 'preview': False, 'sound': not muted}
        from .sticker_search import cached
        from telethon.utils import get_peer_id
        cache = getattr(self, '_notification_cache', None)
        if cache is None:
            cache = self._notification_cache = SimpleNamespace()
        key = peer if isinstance(peer, (str, int)) else get_peer_id(peer)
        async def fetch():
            entity = await self.client.get_entity(peer)
            category = 'channels' if getattr(entity, 'broadcast', False) else 'groups' if isinstance(entity, (types.Chat, types.Channel)) else 'private'
            input_peer = await self.client.get_input_entity(entity)
            return await notification_reads(self.client, (types.InputNotifyPeer(input_peer), CATEGORIES[category]()))
        # Bursts for a chat share both reads. Account-local generations also
        # protect callers whose RPCs were overtaken by a remote mute update.
        async with asyncio.timeout(15):
            while True:
                generation = getattr(cache, '_sticker_generation', 0)
                specific, defaults = await cached(cache, key, fetch, ttl=5)
                if generation == getattr(cache, '_sticker_generation', 0):
                    break
        def setting(name, fallback):
            value = getattr(specific, name, None)
            return getattr(defaults, name, fallback) if value is None else value
        until = setting('mute_until', None)
        muted = bool(until and until.timestamp() > datetime.now(timezone.utc).timestamp())
        sound_name = {'iOS': 'ios_sound', 'Android': 'android_sound'}.get(platform, 'other_sound')
        sound = getattr(specific, sound_name, None)
        if sound is None:
            sound = getattr(specific, 'other_sound', None)
        if sound is None:
            sound = getattr(defaults, sound_name, None)
        if sound is None:
            sound = getattr(defaults, 'other_sound', None)
        return {'enabled': not muted, 'preview': setting('show_previews', True) is not False,
                'sound': not bool(setting('silent', False)) and not isinstance(sound, types.NotificationSoundNone)}

    async def mark_read(self, peer, message_id):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            return await self.secret_chats.mark_read(peer, message_id)
        await self.client.send_read_acknowledge(peer, max_id=message_id)

    async def edited_event(self, event):
        await self.resolve_missing_senders([event.message])
        if self.on_change: self.on_change('edit', (event.chat_id, self.message(event.message)))

    async def deleted_event(self, event):
        if self.on_change: self.on_change('delete', (event.chat_id, tuple(event.deleted_ids)))

    async def read_event(self, event):
        if event.outbox:
            if not hasattr(self, 'read_max'): self.read_max = {}
            self.read_max[event.chat_id] = max(self.read_max.get(event.chat_id, 0), event.max_id)
            if self.on_change: self.on_change('read', (event.chat_id, event.max_id))
        elif self.on_change: self.on_change('dialogs', None)

    async def state_event(self, update):
        from telethon.utils import get_peer_id
        self.process_advanced_update(update)
        self.forum_update(update)
        if isinstance(update, types.UpdateNotifySettings):
            self.invalidate_notification_policy()
        if self.on_change:
            if isinstance(update, types.UpdateMessageReactions):
                self.on_change('reaction',(get_peer_id(update.peer),update.msg_id))
            elif isinstance(update, types.UpdatePeerWallpaper):
                self.on_change('wallpaper',get_peer_id(update.peer))
            elif isinstance(update, types.UpdateUserEmojiStatus):
                self.on_change('emoji_status', (update.user_id, update.emoji_status))
            elif isinstance(update, types.UpdateUser): self.on_change('accents',update.user_id)
            elif isinstance(update, types.UpdateChannel): self.on_change('accents',get_peer_id(types.PeerChannel(update.channel_id)))
            elif isinstance(update, types.UpdateUserStatus):
                presence = getattr(self, '_presence', None)
                if presence is None: presence = self._presence = {}
                presence[update.user_id] = update.status  # Chat list ● mark (1.4).
                while len(presence) > 2048: presence.pop(next(iter(presence)))
                self.on_change('activity',(update.user_id,None))
            elif isinstance(update, (types.UpdateUserTyping,types.UpdateChatUserTyping,types.UpdateChannelUserTyping)):
                peer = update.user_id if isinstance(update,types.UpdateUserTyping) else -update.chat_id if isinstance(update,types.UpdateChatUserTyping) else get_peer_id(types.PeerChannel(update.channel_id))
                status = '' if isinstance(update.action,types.SendMessageCancelAction) else tr('Typing…') if isinstance(update.action,types.SendMessageTypingAction) else tr('Sending media…')
                self.on_change('activity',(peer,status))
            elif isinstance(update,types.UpdatePinnedMessages): self.on_change('pins',get_peer_id(update.peer))
            elif isinstance(update,types.UpdatePinnedChannelMessages): self.on_change('pins',get_peer_id(types.PeerChannel(update.channel_id)))
        relevant = tuple(getattr(types, name) for name in ('UpdateDialogPinned', 'UpdatePinnedDialogs',
                         'UpdateDialogFilter', 'UpdateDialogFilters', 'UpdateDialogFilterOrder', 'UpdateFolderPeers', 'UpdateDialogUnreadMark', 'UpdateNotifySettings') if hasattr(types, name))
        if isinstance(update, relevant) and self.on_change: self.on_change('dialogs', None)


def reconcile_history(messages, changes, peer):
    """Apply edits/deletions that arrived while a history snapshot was in flight."""
    from telethon.utils import resolve_id
    result = {message.id: message for message in messages}
    for kind, (event_peer, value) in changes:
        if kind in ('edit', 'advanced_media') and event_peer == peer and value.id in result:
            result[value.id] = value
        elif kind == 'delete' and (event_peer == peer or event_peer is None and resolve_id(peer)[1] is not types.PeerChannel):
            for identifier in value: result.pop(identifier, None)
    return sorted(result.values(), key=lambda message: message.id)
