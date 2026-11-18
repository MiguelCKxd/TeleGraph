"""Server-backed profile fields and permission-scoped profile settings."""
import asyncio
from telethon import functions as f, types as t, utils
from .i18n import tr

PERMISSIONS = {
    'send_plain':'Messages', 'send_photos':'Photos', 'send_videos':'Videos',
    'send_audios':'Audio', 'send_voices':'Voice messages', 'send_roundvideos':'Video messages',
    'send_docs':'Files', 'send_stickers':'Stickers', 'send_gifs':'GIFs', 'send_polls':'Polls',
    'embed_links':'Link previews', 'invite_users':'Add members', 'pin_messages':'Pinned messages',
    'change_info':'Change chat info', 'manage_topics':'Manage topics',
}


def profile_fields(entity, full):
    person=isinstance(entity,t.User);channel=isinstance(entity,t.Channel)
    group=isinstance(entity,t.Chat) or channel and bool(entity.megagroup)
    owner=bool(getattr(entity,'creator',False));admin=getattr(entity,'admin_rights',None)
    rights=getattr(entity,'default_banned_rights',None)
    member=not bool(getattr(entity,'left',False) or getattr(entity,'kicked',False))
    def can(flag):return not person and member and (owner or bool(getattr(admin,flag,False)))
    can_info=can('change_info') or group and member and not bool(getattr(rights,'change_info',False))
    usernames=[getattr(entity,'username',None)]+[u.username for u in (getattr(entity,'usernames',None) or []) if u.active]
    participants=getattr(getattr(full,'participants',None),'participants',None)
    count=getattr(full,'participants_count',None)
    if count is None:count=getattr(entity,'participants_count',None)
    if count is None and participants is not None:count=len(participants)
    return dict(kind='bot' if person and entity.bot else 'user' if person else 'group' if group else 'channel',
        usernames=list(dict.fromkeys(u for u in usernames if u)),contact=bool(getattr(entity,'contact',False)),
        is_self=bool(getattr(entity,'is_self',False)),premium=bool(getattr(entity,'premium',False)),
        verified=bool(getattr(entity,'verified',False)),scam=bool(getattr(entity,'scam',False)),fake=bool(getattr(entity,'fake',False)),
        blocked=bool(getattr(full,'blocked',False)),common_chats_count=getattr(full,'common_chats_count',0),
        members_count=count,admins_count=getattr(full,'admins_count',None),online_count=getattr(full,'online_count',None),
        linked_chat_id=getattr(full,'linked_chat_id',None),personal_channel_id=getattr(full,'personal_channel_id',None),
        location=getattr(full,'location',None) or getattr(full,'business_location',None),
        personal_channel_message=getattr(full,'personal_channel_message',None),
        work_hours=getattr(full,'business_work_hours',None),
        business_intro=getattr(full,'business_intro',None),bot_verification=getattr(full,'bot_verification',None),
        phone_calls_available=getattr(full,'phone_calls_available',None),
        phone_calls_private=getattr(full,'phone_calls_private',None),
        video_calls_available=getattr(full,'video_calls_available',None),
        main_tab=getattr(full,'main_tab',None),stargifts_count=getattr(full,'stargifts_count',0),
        saved_music=getattr(full,'saved_music',None),stories_pinned_available=bool(getattr(full,'stories_pinned_available',False)),
        notify_settings=getattr(full,'notify_settings',None),ttl_period=getattr(full,'ttl_period',0) or 0,
        slowmode_seconds=getattr(full,'slowmode_seconds',0) or 0,
        available_reactions=getattr(full,'available_reactions',None),default_banned_rights=rights,
        invite_link=getattr(getattr(full,'exported_invite',None),'link',None),
        protected_content=bool(getattr(entity,'noforwards',False)),forum=bool(getattr(entity,'forum',False)),
        join_request=bool(getattr(entity,'join_request',False)),hidden_prehistory=bool(getattr(full,'hidden_prehistory',False)),
        member=member,creator=owner,can_edit_info=bool(can_info),can_ban=can('ban_users'),can_invite=can('invite_users'),
        can_view_members=not person and (isinstance(entity,t.Chat) or bool(getattr(full,'can_view_participants',False))),
        can_manage_reactions=can('change_info'),can_change_username=channel and owner and bool(getattr(full,'can_set_username',False)),
        can_set_ttl=(person and not entity.bot and not getattr(entity,'is_self',False)) or can('delete_messages'),
        is_channel=channel)


class ProfileDetails:
    async def profile_members(self,peer,offset=0,query='',admins=False,mode='members'):
        if type(offset) is not int or offset<0 or mode not in ('members','restricted','removed'):
            raise ValueError('Invalid member page')
        entity=await self.client.get_entity(peer)
        if isinstance(entity,t.Channel):
            filter=t.ChannelParticipantsAdmins() if admins else t.ChannelParticipantsBanned(query) if mode=='restricted' else t.ChannelParticipantsKicked(query) if mode=='removed' else t.ChannelParticipantsSearch(query)
            result=await self.client(f.channels.GetParticipantsRequest(entity,filter,offset,50,0))
            people={u.id:u for u in result.users};parts=result.participants
            total=result.count
        elif isinstance(entity,t.Chat):
            result=await self.client(f.messages.GetFullChatRequest(entity.id))
            people={u.id:u for u in result.users}
            parts=list(getattr(result.full_chat.participants,'participants',[]) or [])
            if admins:parts=[p for p in parts if isinstance(p,(t.ChatParticipantAdmin,t.ChatParticipantCreator))]
            if query:parts=[p for p in parts if query.casefold() in utils.get_display_name(people.get(p.user_id)).casefold()]
            total=len(parts);parts=parts[offset:offset+50]
        else:raise ValueError(tr('Choose a group or channel.'))
        records=[]
        for part in parts:
            user_id=getattr(part,'user_id',None)
            if user_id is None and isinstance(getattr(part,'peer',None),t.PeerUser):user_id=part.peer.user_id
            user=people.get(user_id)
            if user is None:continue
            from .community_management import role
            from .telegram_actions import peer_activity
            records.append({'id':user.id,'name':utils.get_display_name(user),'role':role(part),'rank':getattr(part,'rank','') or '',
                            'activity':peer_activity(user),'activity_entity':user})
        return {'items':records,'next_offset':offset+len(parts),'more':bool(parts) and offset+len(parts)<total}

    async def profile_common_chats(self,peer,max_id=0):
        from .backend import Chat
        result=await self.client(f.messages.GetCommonChatsRequest(await self.client.get_input_entity(peer),max_id,50))
        return [Chat(utils.get_peer_id(c),utils.get_display_name(c),kind='channel' if getattr(c,'broadcast',False) else 'group', entity=c) for c in result.chats]

    async def profile_notify(self,peer,changes):
        if not changes:return
        allowed={'show_previews','mute_until','sound','stories_muted','stories_hide_sender','stories_sound','silent'}
        if set(changes)-allowed:raise ValueError('Unsupported notification setting')
        result = await self.client(f.account.UpdateNotifySettingsRequest(t.InputNotifyPeer(await self.client.get_input_entity(peer)),t.InputPeerNotifySettings(**changes)))
        self.invalidate_notification_policy()
        return result

    async def profile_block(self,peer,blocked):
        entity=await self.client.get_entity(peer)
        if not isinstance(entity,t.User) or getattr(entity,'is_self',False):raise ValueError(tr('Choose a person, not a channel or group.'))
        return await self.client((f.contacts.BlockRequest if blocked else f.contacts.UnblockRequest)(entity))

    async def profile_delete_contact(self,peer):
        entity=await self.client.get_entity(peer)
        if not isinstance(entity,t.User):raise ValueError(tr('Choose a person, not a channel or group.'))
        return await self.client(f.contacts.DeleteContactsRequest([entity]))

    async def profile_change(self,peer,field,value):
        # Re-read rights and current values; Telegram still enforces permissions.
        current=await asyncio.wait_for(self.profile(peer),30)
        rights={'title':'can_edit_info','about':'can_edit_info','photo':'can_edit_info',
                'username':'can_change_username','ttl':'can_set_ttl','slowmode':'can_ban',
                'permissions':'can_ban','reactions':'can_manage_reactions','invite':'can_invite'}
        if field not in rights or not current.get(rights[field]):raise ValueError(tr('Telegram does not allow this action for your account.'))
        entity=await asyncio.wait_for(self.client.get_input_entity(peer),30)
        if field=='title':
            value=value.strip()
            if not value or len(value)>128:raise ValueError(tr('Invalid chat title.'))
            request=f.channels.EditTitleRequest(entity,value) if current['is_channel'] else f.messages.EditChatTitleRequest(-current['id'],value)
        elif field=='about':
            if len(value)>255:raise ValueError(tr('Description is too long.'))
            request=f.messages.EditChatAboutRequest(entity,value)
        elif field=='username':
            import re
            value=value.strip().lstrip('@')
            if value and not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{4,31}',value):raise ValueError(tr('El usuario debe tener de 5 a 32 letras, numeros o guiones bajos.'))
            request=f.channels.UpdateUsernameRequest(entity,value)
        elif field=='photo':
            from .backend import attachment_path
            if value is None:photo=t.InputChatPhotoEmpty()
            else:
                path=attachment_path(value)
                if path.suffix.lower() not in ('.jpg','.jpeg','.png'):raise ValueError(tr('Elige una imagen PNG o JPEG.'))
                from .transfers import transfer_scope,transfer_timeout
                with path.open('rb') as stream:
                    async with transfer_scope(self),transfer_timeout() as report:
                        photo=t.InputChatUploadedPhoto(file=await self.client.upload_file(stream,progress_callback=report))
                        request=f.channels.EditPhotoRequest(entity,photo) if current['is_channel'] else f.messages.EditChatPhotoRequest(-current['id'],photo)
                        return await self.client(request)
            request=f.channels.EditPhotoRequest(entity,photo) if current['is_channel'] else f.messages.EditChatPhotoRequest(-current['id'],photo)
        elif field=='ttl':
            if value not in (0,86400,604800,2678400):raise ValueError('Unsupported auto-delete period')
            request=f.messages.SetHistoryTTLRequest(entity,value)
        elif field=='slowmode':
            if current['kind']!='group' or not current['is_channel'] or value not in (0,10,30,60,300,900,3600):raise ValueError('Unsupported slow mode')
            request=f.channels.ToggleSlowModeRequest(entity,value)
        elif field=='permissions':
            if current['kind']!='group' or set(value)-set(PERMISSIONS) or any(type(v) is not bool for v in value.values()):raise ValueError('Unsupported permissions')
            from .community_management import merge_restrictions
            banned=merge_restrictions(current.get('default_banned_rights'),value)
            request=f.messages.EditChatDefaultBannedRightsRequest(entity,banned)
        elif field=='reactions':
            if value not in ('all','none'):raise ValueError('Unsupported reactions')
            request=f.messages.SetChatAvailableReactionsRequest(entity,t.ChatReactionsAll(allow_custom=True) if value=='all' else t.ChatReactionsNone())
        else:request=f.messages.ExportChatInviteRequest(entity)
        return await self.client(request)
