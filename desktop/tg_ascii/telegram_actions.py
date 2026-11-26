"""Peer-scoped Telegram actions. Telegram remains authoritative for permissions."""
from telethon import functions, types, utils
from .i18n import tr
from .transfers import transfer_timeout, tracked_transfer


def activity_text(status, seconds=False):
    if isinstance(status, types.UserStatusOnline): return tr('Online')
    if isinstance(status, types.UserStatusOffline):
        return tr('Last seen') + ': ' + status.was_online.astimezone().strftime('%d/%m/%Y %H:%M:%S' if seconds else '%d/%m/%Y %H:%M')
    labels = {types.UserStatusRecently: 'Last seen recently', types.UserStatusLastWeek: 'Last seen within a week',
              types.UserStatusLastMonth: 'Last seen within a month',
              types.UserStatusEmpty: 'Last seen a long time ago'}
    return tr(labels.get(type(status), 'Last seen a long time ago'))


def peer_activity(entity, seconds=False):
    """Only people have presence. Privacy buckets never become exact dates."""
    if isinstance(entity, types.User):
        return tr('Bot') if entity.bot else activity_text(entity.status, seconds)
    if isinstance(entity, types.Channel):
        return tr('Group') if entity.megagroup else tr('Channel')
    return tr('Group') if isinstance(entity, types.Chat) else ''


class TelegramActions:
    async def profile_palette(self, color_id, dark=False):
        response=await self.client(functions.help.GetPeerProfileColorsRequest(hash=0))
        option=next((c for c in response.colors if c.color_id==color_id),None)
        colors=(option.dark_colors if dark and option.dark_colors else option.colors) if option else None
        return getattr(colors,'bg_colors',[]) or []

    @tracked_transfer
    async def set_wallpaper(self, peer, path):
        from .backend import attachment_path
        path=attachment_path(path)
        if path.suffix.lower() not in ('.jpg','.jpeg','.png'): raise ValueError(tr('Elige una imagen PNG o JPEG.'))
        with path.open('rb') as stream:
            async with transfer_timeout() as report:
                uploaded=await self.client.upload_file(stream,progress_callback=report)
                wallpaper=await self.client(functions.account.UploadWallPaperRequest(uploaded,'image/png' if path.suffix.lower()=='.png' else 'image/jpeg',types.WallPaperSettings(),for_chat=True))
                await self.client(functions.messages.SetChatWallPaperRequest(await self.client.get_input_entity(peer),
                                  wallpaper=types.InputWallPaper(wallpaper.id,wallpaper.access_hash),settings=wallpaper.settings,for_both=False))
                return wallpaper

    async def wallpaper_image(self, peer, destination):
        profile=await self.profile(peer)
        wallpaper=profile.get('wallpaper')
        if wallpaper and getattr(wallpaper,'document',None):
            return await self.download_media(wallpaper.document,destination)

    @tracked_transfer
    async def publish_story(self, path, caption='', audience='contacts', period=86400):
        from secrets import randbits
        from .backend import attachment_path
        path=attachment_path(path)
        rules={'contacts':types.InputPrivacyValueAllowContacts,'everyone':types.InputPrivacyValueAllowAll,'close':types.InputPrivacyValueAllowCloseFriends}
        if audience not in rules or period not in (21600,43200,86400,172800): raise ValueError('Invalid story settings')
        extension=path.suffix.lower()
        attributes=None
        if extension=='.mp4':
            from .video_metadata import mp4_metadata
            duration,width,height=mp4_metadata(path)
            attributes=[types.DocumentAttributeVideo(duration,width,height,supports_streaming=True)]
        elif extension not in ('.jpg','.jpeg','.png'): raise ValueError(tr('Choose a JPEG, PNG or MP4 file.'))
        with path.open('rb') as stream:
            async with transfer_timeout() as report:
                uploaded=await self.client.upload_file(stream,progress_callback=report)
                media=types.InputMediaUploadedDocument(uploaded,'video/mp4',attributes) if attributes else types.InputMediaUploadedPhoto(uploaded)
                return await self.client(functions.stories.SendStoryRequest(types.InputPeerSelf(),media,[rules[audience]()],
                                      caption=caption,period=period,random_id=randbits(63),pinned=False))

    async def webapp(self, peer):
        entity=await self.client.get_entity(peer)
        if not isinstance(entity,types.User) or not entity.bot: raise ValueError(tr('Choose a bot first.'))
        input_peer=await self.client.get_input_entity(entity)
        bot=utils.get_input_user(input_peer)
        if entity.bot_has_main_app:
            result=await self.client(functions.messages.RequestMainWebViewRequest(input_peer,bot,'web'))
        else:
            full=await self.client(functions.users.GetFullUserRequest(entity))
            menu=getattr(full.full_user.bot_info,'menu_button',None)
            if not isinstance(menu,types.BotMenuButton): raise ValueError(tr('This bot has no Mini App menu.'))
            result=await self.client(functions.messages.RequestWebViewRequest(input_peer,bot,'web',from_bot_menu=True,url=menu.url))
        return result.url

    async def search_public(self, query):
        from .backend import Chat
        if not query.strip(): return []
        response = await self.client(functions.contacts.SearchRequest(query.strip(), 50))
        entities = {utils.get_peer_id(e): e for e in response.users + response.chats}
        results, seen = [], set()
        for peer in response.my_results + response.results:
            ident = utils.get_peer_id(peer)
            if ident in seen or ident not in entities: continue
            seen.add(ident)
            entity = entities[ident]
            kind = 'bot' if getattr(entity, 'bot', False) else 'channel' if getattr(entity, 'broadcast', False) else 'user' if isinstance(entity, types.User) else 'group'
            results.append(Chat(ident, utils.get_display_name(entity), kind=kind,
                                member=not bool(getattr(entity, 'left', False)) if kind in ('group', 'channel') else None, entity=entity))
        return results

    async def search_messages(self, peer, query='', kind='all', offset=0):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            return self.secret_chats.search_messages(peer, query, kind, offset)
        if kind == 'polls':
            return await self.poll_messages(peer, query, offset)
        filters = {'all': types.InputMessagesFilterEmpty, 'photos': types.InputMessagesFilterPhotos,
                   'media': types.InputMessagesFilterPhotoVideo, 'videos': types.InputMessagesFilterVideo,
                   'files': types.InputMessagesFilterDocument, 'audio': types.InputMessagesFilterMusic,
                   'voice': types.InputMessagesFilterVoice, 'links': types.InputMessagesFilterUrl,
                   'gifs': types.InputMessagesFilterGif}
        if kind not in filters: raise ValueError('Unknown media filter')
        messages = await self.client.get_messages(peer, search=query, filter=filters[kind](), limit=50, offset_id=offset)
        await self.resolve_missing_senders(messages)
        return [self.message(m) for m in messages]

    async def save_contact(self, peer, first, last='', phone=''):
        if not first.strip(): raise ValueError(tr('El nombre es obligatorio.'))
        entity = await self.client.get_entity(peer)
        if not isinstance(entity, types.User): raise ValueError(tr('Choose a person, not a channel or group.'))
        # An empty phone preserves the ability to add a contact by username.
        await self.client(functions.contacts.AddContactRequest(entity, first.strip(), last.strip(), phone.strip(), add_phone_privacy_exception=False))
        return entity

    async def mute_chat(self, peer, muted, duration=None):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            sess = self.secret_chats.session_for_peer(peer)
            sess.muted = bool(muted)
            self.secret_chats._save()
            self.secret_chats._emit_dialogs()
            return True
        entity = await self.client.get_input_entity(peer)
        from .peer_tools import mute_deadline
        until = mute_deadline((-1 if duration is None else duration) if muted else 0)
        result = await self.client(functions.account.UpdateNotifySettingsRequest(
            types.InputNotifyPeer(entity), types.InputPeerNotifySettings(mute_until=until)))
        self.invalidate_notification_policy()
        return result

    async def archive_chat(self, peer, archived):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            sess = self.secret_chats.session_for_peer(peer)
            sess.archived = bool(archived)
            self.secret_chats._save()
            self.secret_chats._emit_dialogs()
            return True
        return await self.client.edit_folder(peer, folder=1 if archived else 0)

    async def history_permissions(self,peer):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            return {'entity': None, 'person': True, 'delete_all': True, 'clear_self': True, 'clear_all': True}
        entity=await self.client.get_entity(peer)
        person=isinstance(entity,types.User)
        group=isinstance(entity,types.Chat) or isinstance(entity,types.Channel) and bool(entity.megagroup)
        owner=bool(getattr(entity,'creator',False))
        can_remove=bool(getattr(getattr(entity,'admin_rights',None),'delete_messages',False))
        return {'entity':entity,'person':person,'delete_all':person or owner,
                'clear_self':person or group,'clear_all':person or group and (owner or can_remove)}

    async def delete_chat(self, peer, everyone=False):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            return await self.secret_chats.discard(peer, delete_history=True)
        if not everyone: return await self.client.delete_dialog(peer,revoke=False)
        info=await self.history_permissions(peer)
        if not info['delete_all']: raise ValueError(tr('Telegram does not allow this action for your account.'))
        entity=info['entity']
        if isinstance(entity,types.User): return await self.client.delete_dialog(entity,revoke=True)
        if isinstance(entity,types.Channel): return await self.client(functions.channels.DeleteChannelRequest(entity))
        if isinstance(entity,types.Chat): return await self.client(functions.messages.DeleteChatRequest(entity.id))
        raise ValueError(tr('Telegram does not allow this action for your account.'))

    async def clear_chat(self,peer,everyone=False):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            return await self.secret_chats.flush_history(peer)
        info=await self.history_permissions(peer)
        if not info['clear_all' if everyone else 'clear_self']:
            raise ValueError(tr('Telegram does not allow this action for your account.'))
        # Freeze the boundary; new arrivals must survive a long clear operation.
        latest=await self.client.get_messages(peer,limit=1)
        if not latest: return 0
        maximum=latest[0].id
        entity=info['entity']
        if isinstance(entity,types.Channel):
            await self.client(functions.channels.DeleteHistoryRequest(entity,maximum,for_everyone=everyone))
        else:
            while True:
                result=await self.client(functions.messages.DeleteHistoryRequest(
                    await self.client.get_input_entity(peer),max_id=maximum,just_clear=True,revoke=everyone))
                if not getattr(result,'offset',0): break
        return maximum

    async def checked_message(self, peer, ident):
        message = await self.client.get_messages(peer, ids=ident)
        if message is None or utils.get_peer_id(message.peer_id) != peer:
            raise ValueError(tr('This message is no longer available in this chat.'))
        return message

    async def delete_message(self, peer, ident, everyone=False):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            return await self.secret_chats.delete_messages(peer, [ident])
        await self.checked_message(peer, ident)
        return await self.client.delete_messages(peer, [ident], revoke=everyone)

    async def forward_message(self, peer, ident, destination):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer) or is_secret_peer(destination):
            raise ValueError(tr('Los mensajes de chats secretos no se pueden reenviar.'))
        await self.checked_message(peer, ident)
        return await self.client.forward_messages(destination, [ident], from_peer=peer)

    async def selected_message_policy(self,peer,identifiers):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            ids = list(dict.fromkeys(identifiers))
            return {'copy': bool(ids), 'forward': False, 'delete_self': bool(ids), 'delete_all': bool(ids)}
        ids=list(dict.fromkeys(identifiers))
        if len(ids)==1:
            messages=[await self.checked_message(peer,ids[0])]
        elif ids:
            # Telethon batches IDs (and applies its own rate limits for large
            # selections), avoiding one sequential RPC for every selected row.
            result=await self.client.get_messages(peer,ids=ids)
            found={m.id:m for m in result if m is not None and getattr(m,'peer_id',None) is not None
                   and utils.get_peer_id(m.peer_id)==peer}
            if any(ident not in found for ident in ids):
                raise ValueError(tr('This message is no longer available in this chat.'))
            messages=[found[ident] for ident in ids]
        else:messages=[]
        entity=await self.client.get_entity(peer)
        channel=isinstance(entity,types.Channel)
        person=isinstance(entity,types.User)
        admin=bool(getattr(entity,'creator',False) or getattr(getattr(entity,'admin_rights',None),'delete_messages',False))
        protected=bool(getattr(entity,'noforwards',False) or any(getattr(m,'noforwards',False) or getattr(m,'ttl_period',None) for m in messages))
        ordinary=bool(messages) and all(isinstance(m,types.Message) for m in messages)
        return {'copy':ordinary and not protected,'forward':ordinary and not protected,
                'delete_self':bool(messages) and not channel,
                'delete_all':bool(messages) and (person or admin or all(getattr(m,'out',False) for m in messages))}

    async def delete_selected_messages(self,peer,identifiers,everyone=False):
        from .secret_chats import is_secret_peer
        ids=list(dict.fromkeys(identifiers))
        if not ids:return
        if is_secret_peer(peer):
            return await self.secret_chats.delete_messages(peer, ids)
        policy=await self.selected_message_policy(peer,ids)
        if not policy['delete_all' if everyone else 'delete_self']:
            raise ValueError(tr('Telegram does not allow this action for your account.'))
        return await self.client.delete_messages(peer,ids,revoke=everyone)

    async def forward_selected_messages(self,peer,identifiers,destination):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer) or is_secret_peer(destination):
            raise ValueError(tr('Los mensajes de chats secretos no se pueden reenviar.'))
        ids=list(dict.fromkeys(identifiers))
        if not ids:return
        policy=await self.selected_message_policy(peer,ids)
        if not policy['forward']:raise ValueError(tr('Telegram does not allow this action for your account.'))
        return await self.client.forward_messages(destination,ids,from_peer=peer)

    async def set_chat_unread(self,peer,unread):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            sess = self.secret_chats.session_for_peer(peer)
            sess.unread = 1 if unread else 0
            self.secret_chats._save()
            self.secret_chats._emit_dialogs()
            return True
        if not unread:
            latest=await self.client.get_messages(peer,limit=1)
            if latest:await self.client.send_read_acknowledge(peer,max_id=latest[0].id)
        return await self.client(functions.messages.MarkDialogUnreadRequest(
            types.InputDialogPeer(await self.client.get_input_entity(peer)),unread=unread))

    async def edit_existing(self, peer, ident, text, file=None, entities=None):
        original = await self.checked_message(peer, ident)
        if entities is None:
            entities = original.entities if text == original.raw_text else []
        result = await self.client.edit_message(peer, ident, text, file=file,
                                                parse_mode=None, formatting_entities=entities)
        return self.message(result)

    async def read_time(self, peer, ident, seconds=False):
        await self.checked_message(peer, ident)
        result = await self.client(functions.messages.GetOutboxReadDateRequest(await self.client.get_input_entity(peer), ident))
        from .timestamps import date_text
        return date_text(result.date,{'show_seconds':seconds})

    async def profile_photo(self, peer, destination):
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
        from .flood_control import read_with_flood_wait
        return await read_with_flood_wait(self, 'download', lambda: self.client.download_profile_photo(
            peer, file=str(destination), download_big=True))

    async def bot_commands(self, peer):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer): return []
        entity = await self.client.get_entity(peer)
        if not isinstance(entity, types.User) or not entity.bot: return []
        response = await self.client(functions.users.GetFullUserRequest(entity))
        return getattr(response.full_user.bot_info, 'commands', []) or []
