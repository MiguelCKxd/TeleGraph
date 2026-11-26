"""Lazy, server-authoritative group/channel membership and discussion controls."""
from copy import copy
from datetime import datetime, timezone
from telethon import functions as f, types as t, utils
from .i18n import tr
from .profile_details import PERMISSIONS

ADMIN_RIGHTS = {
    'change_info':'Change chat info', 'post_messages':'Post messages',
    'edit_messages':'Edit messages', 'delete_messages':'Delete messages',
    'ban_users':'Ban members', 'invite_users':'Add members', 'pin_messages':'Pinned messages',
    'add_admins':'Add administrators', 'anonymous':'Remain anonymous', 'manage_call':'Manage calls',
    'manage_topics':'Manage topics', 'post_stories':'Post stories', 'edit_stories':'Edit stories',
    'delete_stories':'Delete stories', 'manage_direct_messages':'Manage direct messages',
    'manage_ranks':'Manage member ranks', 'manage_linked_peers':'Manage linked chats',
    'manage_welcome_messages':'Manage welcome messages', 'other':'Other administrator privileges',
}
BROADCAST_ONLY={'post_messages','edit_messages','manage_direct_messages'}
GROUP_ONLY={'anonymous','manage_topics','manage_ranks','manage_welcome_messages'}


def admin_fields(entity):
    return {k:v for k,v in ADMIN_RIGHTS.items() if hasattr(t.ChatAdminRights(),k)
            and not (entity.megagroup and k in BROADCAST_ONLY)
            and not (not entity.megagroup and k in GROUP_ONLY)
            and not (k=='manage_topics' and not entity.forum)}


def role(participant):
    if isinstance(participant,(t.ChannelParticipantCreator,t.ChatParticipantCreator)):return 'Owner'
    if isinstance(participant,(t.ChannelParticipantAdmin,t.ChatParticipantAdmin)):return 'Administrator'
    if isinstance(participant,t.ChannelParticipantBanned):
        return 'Removed' if participant.banned_rights.view_messages else 'Restricted'
    return 'Member'


def merge_restrictions(before, changes):
    if set(changes)-set(PERMISSIONS) or any(type(v) is not bool for v in changes.values()):
        raise ValueError('Unsupported permissions')
    result=copy(before) if before is not None else t.ChatBannedRights(None)
    if result.send_messages:
        result.send_messages=False
        for key in ('send_plain','send_media','send_stickers','send_gifs','send_games','send_inline','embed_links','send_polls'):
            setattr(result,key,True)
    if result.send_media:
        result.send_media=False
        for key in ('send_photos','send_videos','send_roundvideos','send_audios','send_voices','send_docs'):
            setattr(result,key,True)
    for key,allowed in changes.items():setattr(result,key,not allowed)
    return result


class CommunityManagement:
    async def community_info(self, peer, *, allow_left=False):
        entity=await self.client.get_entity(peer)
        if isinstance(entity,t.Channel):
            response=await self.client(f.channels.GetFullChannelRequest(entity))
        elif isinstance(entity,t.Chat):
            response=await self.client(f.messages.GetFullChatRequest(entity.id))
        else:raise ValueError(tr('Choose a group or channel.'))
        # get_entity may return a cached entity with revoked rights. Full RPCs
        # carry the authoritative version alongside full_chat.
        entity=next((c for c in getattr(response,'chats',()) if c.id==entity.id),entity)
        if getattr(entity,'kicked',False) or getattr(entity,'left',False) and not allow_left:
            raise ValueError(tr('Telegram does not allow this action for your account.'))
        return entity,response.full_chat

    @staticmethod
    def community_can(entity, right):
        return bool(entity.creator or getattr(getattr(entity,'admin_rights',None),right,False))

    async def create_community(self,title,about='',broadcast=False, *, forum=False):
        from .backend import Chat
        if type(broadcast) is not bool or not isinstance(title,str) or not title.strip() or len(title.strip())>128:
            raise ValueError(tr('Invalid chat title.'))
        if not isinstance(about,str) or len(about)>255:raise ValueError(tr('Description is too long.'))
        if type(forum) is not bool or forum and broadcast:
            raise ValueError(tr('Choose a forum group.'))
        result=await self.client(f.channels.CreateChannelRequest(title.strip(),about,broadcast=broadcast,megagroup=not broadcast,forum=forum))
        entity=next((c for c in result.chats if isinstance(c,t.Channel) and bool(c.broadcast)==broadcast),None)
        if entity is None:raise ValueError(tr('Telegram no devolvio el grupo. Actualiza antes de reintentar.'))
        return Chat(utils.get_peer_id(entity),entity.title,kind='channel' if broadcast else 'group',member=True,entity=entity,forum=bool(entity.forum),has_link=bool(entity.has_link))

    async def discussion_groups(self, peer):
        entity,full=await self.community_info(peer)
        if not isinstance(entity,t.Channel) or not entity.broadcast or not self.community_can(entity,'change_info'):
            raise ValueError(tr('Telegram does not allow this action for your account.'))
        result=await self.client(f.channels.GetGroupsForDiscussionRequest())
        return {'linked':getattr(full,'linked_chat_id',None), 'items':[
            {'id':utils.get_peer_id(c),'name':c.title,'basic':isinstance(c,t.Chat)}
            for c in result.chats if isinstance(c,t.Chat) or isinstance(c,t.Channel) and c.megagroup]}

    async def set_discussion_group(self, peer, group, *, expected_link=None, expose_history=False, migrate=False):
        entity,full=await self.community_info(peer)
        if not isinstance(entity,t.Channel) or not entity.broadcast or not self.community_can(entity,'change_info'):
            raise ValueError(tr('Telegram does not allow this action for your account.'))
        if getattr(full,'linked_chat_id',None)!=expected_link:
            raise ValueError(tr('The linked discussion changed. Reopen this panel.'))
        target=t.InputChannelEmpty()
        if group is not None:
            chosen,gfull=await self.community_info(group)
            if not self.community_can(chosen,'change_info'):
                raise ValueError(tr('Telegram does not allow this action for your account.'))
            if isinstance(chosen,t.Chat):
                if not migrate:raise ValueError(tr('This group must be upgraded before linking.'))
                result=await self.client(f.messages.MigrateChatRequest(chosen.id))
                chosen=next(c for c in result.chats if isinstance(c,t.Channel) and c.megagroup)
                chosen,gfull=await self.community_info(chosen)
            if not chosen.megagroup or chosen.forum:
                raise ValueError(tr('Choose a discussion group without topics.'))
            if getattr(gfull,'linked_chat_id',None) not in (None,0,entity.id):
                raise ValueError(tr('This group is already linked to another channel.'))
            if getattr(gfull,'hidden_prehistory',False):
                if not expose_history:raise ValueError(tr('Linking requires visible history for new members.'))
                await self.client(f.channels.TogglePreHistoryHiddenRequest(chosen,False))
            target=utils.get_input_channel(chosen)
        result=await self.client(f.channels.SetDiscussionGroupRequest(utils.get_input_channel(entity),target))
        if result is False:raise ValueError(tr('Telegram did not apply the change. Refresh before retrying.'))
        return result

    async def community_member(self, peer, user):
        entity,full=await self.community_info(peer)
        person=await self.client.get_entity(user)
        if not isinstance(person,t.User):raise ValueError(tr('Choose a person, not a channel or group.'))
        if isinstance(entity,t.Channel):
            result=await self.client(f.channels.GetParticipantRequest(entity,person));part=result.participant
        else:
            part=next((p for p in getattr(full.participants,'participants',()) if p.user_id==person.id),None)
        owner=bool(entity.creator);admin=isinstance(part,(t.ChannelParticipantAdmin,t.ChatParticipantAdmin))
        protected=part is not None and role(part)=='Owner' or bool(person.is_self)
        editable=not protected and (owner or not admin or bool(getattr(part,'can_edit',False)))
        return {'entity':entity,'person':person,'participant':part,'role':role(part),
                'can_admin':editable and self.community_can(entity,'add_admins') and (isinstance(entity,t.Channel) or owner),
                'can_ban':editable and not admin and self.community_can(entity,'ban_users'),
                'rights':getattr(part,'admin_rights',None),'banned':getattr(part,'banned_rights',None),
                'fields':admin_fields(entity) if isinstance(entity,t.Channel) else {}}

    async def community_admin(self, peer, user, changes, rank=None):
        current=await self.community_member(peer,user);entity=current['entity']
        if not current['can_admin']:raise ValueError(tr('Telegram does not allow this action for your account.'))
        if not isinstance(changes,dict) or any(type(v) is not bool for v in changes.values()):raise ValueError('Unsupported admin rights')
        if isinstance(entity,t.Chat):
            if set(changes)!={'administrator'}:raise ValueError('Unsupported basic group admin rights')
            return await self.client(f.messages.EditChatAdminRequest(entity.id,utils.get_input_user(current['person']),changes['administrator']))
        if set(changes)-set(current['fields']):raise ValueError('Unsupported admin rights')
        before=current['rights'];rights=copy(before) if before is not None else t.ChatAdminRights()
        for key,enabled in changes.items():
            if enabled and not entity.creator and not getattr(entity.admin_rights,key,False):
                raise ValueError(tr('Telegram does not allow this action for your account.'))
            setattr(rights,key,enabled)
        if rank is None:rank=getattr(current['participant'],'rank','') or ''
        if not isinstance(rank,str) or len(rank)>16:raise ValueError(tr('Administrator title is too long.'))
        return await self.client(f.channels.EditAdminRequest(entity,utils.get_input_user(current['person']),rights,rank=rank))

    async def community_restrict(self, peer, user, changes=None, *, action='restrict', until=None):
        current=await self.community_member(peer,user);entity=current['entity']
        if not current['can_ban']:raise ValueError(tr('Telegram does not allow this action for your account.'))
        if action not in ('restrict','ban','unban','remove'):raise ValueError('Unsupported member action')
        if until is not None:
            now=datetime.now(timezone.utc)
            if action not in ('restrict','ban') or not isinstance(until,datetime) or until.tzinfo is None or not 30<=(until-now).total_seconds()<=366*86400:
                raise ValueError(tr('Duración no válida.'))
        if isinstance(entity,t.Chat):
            if action!='remove':raise ValueError(tr('This action requires a supergroup.'))
            return await self.client(f.messages.DeleteChatUserRequest(entity.id,utils.get_input_user(current['person']),revoke_history=False))
        if action=='restrict':
            if not entity.megagroup or current['role']=='Removed':raise ValueError(tr('Choose a group or channel.'))
            rights=merge_restrictions(current['banned'],changes or {})
            rights.until_date=until
        else:rights=t.ChatBannedRights(until_date=until,view_messages=action in ('ban','remove'))
        result=await self.client(f.channels.EditBannedRequest(entity,current['person'],rights))
        if action=='remove':
            # Explicit kick permits rejoining. Ban leaves view_messages in place.
            return await self.client(f.channels.EditBannedRequest(entity,current['person'],t.ChatBannedRights(None)))
        return result

    async def community_add(self, peer, users):
        entity,_=await self.community_info(peer)
        default=getattr(entity,'default_banned_rights',None)
        if not (self.community_can(entity,'invite_users') or (isinstance(entity,t.Chat) or entity.megagroup) and not getattr(default,'invite_users',False)):
            raise ValueError(tr('Telegram does not allow this action for your account.'))
        if not isinstance(users,(list,tuple)) or not 1<=len(users)<=50:
            raise ValueError(tr('Selecciona participantes en la lista.'))
        people=[];seen=set()
        for user in users:
            resolved=await self.client.get_input_entity(user)
            ident=utils.get_peer_id(resolved)
            if ident not in seen:seen.add(ident);people.append(utils.get_input_user(resolved))
        if isinstance(entity,t.Channel):return await self.client(f.channels.InviteToChannelRequest(entity,people))
        if len(people)!=1:raise ValueError(tr('Select one member at a time.'))
        return await self.client(f.messages.AddChatUserRequest(entity.id,people[0],fwd_limit=0))
