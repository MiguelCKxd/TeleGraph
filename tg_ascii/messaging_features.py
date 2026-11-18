"""Peer-scoped Telegram features; no local simulation of server permissions."""
import asyncio
from telethon import functions as f, types as t, utils
from .i18n import tr
from .sticker_search import cached

PRIVACY_KEYS = {
    'Phone number': 'PhoneNumber', 'Find me by phone': 'AddedByPhone',
    'Last seen and online': 'StatusTimestamp', 'Profile photo': 'ProfilePhoto',
    'Bio': 'About', 'Birthday': 'Birthday', 'Forwarded messages': 'Forwards',
    'Calls': 'PhoneCall', 'Peer-to-peer calls': 'PhoneP2P',
    'Groups and channels': 'ChatInvite', 'Voice messages': 'VoiceMessages',
}
BASE_RULES = {'Everyone': t.InputPrivacyValueAllowAll, 'Contacts only': t.InputPrivacyValueAllowContacts,
              'Nobody': t.InputPrivacyValueDisallowAll}


def reaction_value(value):
    if isinstance(value, int) and value > 0: return t.ReactionCustomEmoji(value)
    if isinstance(value, str) and value and len(value) <= 32: return t.ReactionEmoji(value)
    raise ValueError('Invalid reaction')


def reaction_id(value):
    if isinstance(value, t.ReactionEmoji): return value.emoticon
    if isinstance(value, t.ReactionCustomEmoji): return value.document_id
    return None


def reaction_allowed(value,policy):
    allowed=policy['allowed']
    if allowed is not None and value not in allowed: return False
    if isinstance(value,int):
        if allowed is None and not policy['custom']: return False
        return policy['premium'] or value in policy['existing']
    return True


def parse_schedule(value,now=None):
    from datetime import datetime,timezone
    try: result=datetime.strptime(value.strip(),'%Y-%m-%d %H:%M').astimezone()
    except ValueError: raise ValueError(tr('Local date and time (YYYY-MM-DD HH:MM)')) from None
    if (result-(now or datetime.now(timezone.utc))).total_seconds()<15:
        raise ValueError(tr('Choose a future date and time.'))
    return result


def privacy_base(rules):
    for rule in rules:
        for label, cls in BASE_RULES.items():
            if type(rule).__name__ == cls.__name__.removeprefix('Input'): return label
    return None


class MessagingFeatures:
    async def app_config(self):
        result = await cached(self, ('app-config', getattr(self, '_config_epoch', 0)),
                              lambda: self.client(f.help.GetAppConfigRequest(hash=0)), ttl=3600)
        from .advanced_messaging import config_values
        self._capability_config = config_values(result)
        return result

    async def reaction_policy(self, peer, original=None):
        """Reuse account facts/config; refresh the chat's permissions before sending."""
        premium=await self.premium_enabled()
        maximum=3 if premium else 1
        config=await self.app_config()
        values=getattr(getattr(config,'config',None),'value',())
        for item in values:
            if item.key == ('reactions_user_max_premium' if premium else 'reactions_user_max_default'):
                number=getattr(item.value,'value',maximum)
                if isinstance(number,(int,float)) and 1 <= number <= 100: maximum=int(number)
        entity=await self.client.get_input_entity(peer) if peer is not None else None
        available=t.ChatReactionsAll(allow_custom=True)
        if isinstance(entity,t.InputPeerChannel):
            full=await self.client(f.channels.GetFullChannelRequest(entity))
            available=getattr(full.full_chat,'available_reactions',None) or t.ChatReactionsNone()
        elif isinstance(entity,t.InputPeerChat):
            full=await self.client(f.messages.GetFullChatRequest(entity.chat_id))
            available=getattr(full.full_chat,'available_reactions',None) or t.ChatReactionsNone()
        allowed=None
        if isinstance(available,t.ChatReactionsNone): allowed=set()
        elif isinstance(available,t.ChatReactionsSome): allowed={reaction_id(r) for r in available.reactions}
        existing={reaction_id(r.reaction) for r in getattr(getattr(original,'reactions',None),'results',[])}
        return {'maximum':maximum,'premium':premium,'allowed':allowed,'custom':bool(getattr(available,'allow_custom',False)),
                'existing':existing}

    async def react(self, peer, ident, value):
        original=await self.checked_message(peer,ident)
        chosen=sorted((r for r in getattr(getattr(original,'reactions',None),'results',[])
                       if r.chosen_order is not None and reaction_id(r.reaction) is not None),key=lambda r:r.chosen_order)
        selected=[r.reaction for r in chosen]
        if any(reaction_id(r)==value for r in selected):
            selected=[r for r in selected if reaction_id(r)!=value]
        else:
            policy=await self.reaction_policy(peer,original)
            if not reaction_allowed(value,policy): raise ValueError(tr('This reaction is unavailable for your account or this chat.'))
            selected=(selected+[reaction_value(value)])[-policy['maximum']:]
        await self.client(f.messages.SendReactionRequest(await self.client.get_input_entity(peer),ident,
                          reaction=selected,add_to_recent=True))
        self._reaction_epoch = getattr(self, '_reaction_epoch', 0) + 1
        refreshed=await self.checked_message(peer,ident)
        await self.resolve_missing_senders([refreshed])
        return self.message(refreshed)

    async def reaction_choices(self,peer,ident):
        original=await self.checked_message(peer,ident) if ident is not None else None
        # Independent metadata reads can travel together; repeated picker windows
        # share in-flight/catalogue requests through the bounded account cache.
        policy, standard, recent = await asyncio.gather(
            self.reaction_policy(peer,original), self.available_reactions(),
            cached(self, ('recent-reactions', getattr(self, '_reaction_epoch', 0)),
                   lambda: self.client(f.messages.GetRecentReactionsRequest(limit=50,hash=0)), ttl=60))
        custom=[reaction_id(r) for r in getattr(recent,'reactions',[]) if isinstance(r,t.ReactionCustomEmoji)]
        custom += [v for v in policy['existing'] if isinstance(v,int)]
        return policy,[v for v in standard if reaction_allowed(v,policy)],list(dict.fromkeys(v for v in custom if reaction_allowed(v,policy)))

    async def set_default_reaction(self, value):
        """Telegram's default reaction (official apps' double tap): an emoji or
        a custom emoji id (Premium). Returns False when Telegram refuses it."""
        reaction = t.ReactionCustomEmoji(int(value)) if isinstance(value, int) or str(value).isdigit() else t.ReactionEmoji(str(value))
        try:
            await self.client(f.messages.SetDefaultReactionRequest(reaction))
            return True
        except Exception:
            return False

    async def available_reactions(self):
        result = await cached(self, ('available-reactions', getattr(self, '_config_epoch', 0)),
                              lambda: self.client(f.messages.GetAvailableReactionsRequest(hash=0)), ttl=3600)
        return [r.reaction for r in result.reactions if not getattr(r, 'inactive', False)]

    async def scheduled_history(self,peer):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer): return []
        result=await self.client(f.messages.GetScheduledHistoryRequest(await self.client.get_input_entity(peer),hash=0))
        return sorted(result.messages,key=lambda m:m.date)

    async def change_scheduled(self,peer,ident,send_now=False):
        items=await self.scheduled_history(peer)
        if not any(m.id==ident for m in items): raise ValueError(tr('This message is no longer available in this chat.'))
        request=f.messages.SendScheduledMessagesRequest if send_now else f.messages.DeleteScheduledMessagesRequest
        return await self.client(request(await self.client.get_input_entity(peer),[ident]))

    async def pin_message(self, peer, ident, unpin=False, for_both=False):
        await self.checked_message(peer, ident)
        return await self.client(f.messages.UpdatePinnedMessageRequest(
            await self.client.get_input_entity(peer), ident, unpin=unpin, silent=True, pm_oneside=not for_both))

    async def pinned_messages(self, peer):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer): return []
        messages = await self.client.get_messages(peer, limit=50, filter=t.InputMessagesFilterPinned())
        await self.resolve_missing_senders(messages)
        return [self.message(m) for m in messages if isinstance(m, t.Message)]

    async def message_context(self, peer, ident):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            return self.secret_chats.message_context(peer, ident)
        target = await self.checked_message(peer, ident)
        surrounding = await self.client.get_messages(peer, limit=60, offset_id=ident, add_offset=-30)
        await self.resolve_missing_senders([target,*surrounding])
        result = {m.id: self.message(m) for m in surrounding if isinstance(m, t.Message) and utils.get_peer_id(m.peer_id) == peer}
        result[ident] = self.message(target)
        return sorted(result.values(), key=lambda m:m.id)

    async def older_messages(self, peer, before):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            return self.secret_chats.older_messages(peer, before)
        from .flood_control import read_with_flood_wait
        result = await read_with_flood_wait(self, 'history',
                                            lambda: self.client.get_messages(peer, limit=60, offset_id=before))
        await self.resolve_missing_senders(result)
        return sorted([self.message(m) for m in result if isinstance(m,t.Message)], key=lambda m:m.id)

    async def global_messages(self, query, offset=None):
        rate, peer, ident = offset or (0, t.InputPeerEmpty(), 0)
        response = await self.client(f.messages.SearchGlobalRequest(query, t.InputMessagesFilterEmpty(),
            None, None, rate, peer, ident, 50))
        entities = {utils.get_peer_id(e):e for e in response.users + response.chats}
        for ident,entity in entities.items():self.cache_name(ident,utils.get_display_name(entity))
        await self.resolve_missing_senders(response.messages)
        found = []
        for message in response.messages:
            if not isinstance(message,t.Message): continue
            pid = utils.get_peer_id(message.peer_id)
            entity = entities.get(pid)
            # Bind senders supplied with the search response for display.
            sender = entities.get(utils.get_peer_id(message.from_id)) if message.from_id else entity
            if sender is not None: message._sender = sender
            found.append((pid, utils.get_display_name(entity) if entity else str(pid), self.message(message)))
        more = None
        if response.messages and getattr(response,'next_rate',None) is not None:
            last = response.messages[-1]
            more = (response.next_rate, await self.client.get_input_entity(last.peer_id), last.id)
        return found, more

    async def chat_header(self, peer):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            return self.secret_chats.chat_header(peer)
        entity = await self.client.get_entity(peer)
        from .capability_cache import remember
        remember(self, entity)
        commands, mini = [], False
        if isinstance(entity,t.User) and entity.bot:
            response = await self.client(f.users.GetFullUserRequest(entity))
            remember(self, entity, response.full_user)
            info = response.full_user.bot_info
            commands = getattr(info,'commands',[]) or []
            mini = bool(getattr(entity,'bot_has_main_app',False) or isinstance(getattr(info,'menu_button',None),t.BotMenuButton))
        from .telegram_actions import peer_activity
        return {'name':utils.get_display_name(entity), 'status':peer_activity(entity), 'activity_entity':entity,
                'emoji':getattr(getattr(entity,'emoji_status',None),'document_id',None),
                'commands':commands, 'mini':mini}

    async def presence(self, online):
        return await self.client(f.account.UpdateStatusRequest(offline=not online))

    async def typing(self, peer, active=True):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            return await self.secret_chats.set_typing(peer, active)
        return await self.client(f.messages.SetTypingRequest(await self.client.get_input_entity(peer),
            t.SendMessageTypingAction() if active else t.SendMessageCancelAction()))

    async def privacy(self, label):
        return await self.client(f.account.GetPrivacyRequest(getattr(t,'InputPrivacyKey'+PRIVACY_KEYS[label])()))

    async def save_privacy(self, label, base, snapshot, allow=None, deny=None):
        current = await self.privacy(label)
        if [r.to_dict() for r in current.rules] != [r.to_dict() for r in snapshot.rules]:
            raise ValueError(tr('Privacy changed on another device. Reopen this panel.'))
        rules=[]
        for rule in current.rules:
            name=type(rule).__name__
            if name in ('PrivacyValueAllowAll','PrivacyValueDisallowAll','PrivacyValueAllowContacts'): continue
            if allow is not None and name=='PrivacyValueAllowUsers': continue
            if deny is not None and name=='PrivacyValueDisallowUsers': continue
            cls=getattr(t,'Input'+name,None)
            if cls is None: raise ValueError(tr('Unsupported privacy rule; no changes were saved.'))
            args={k:v for k,v in rule.to_dict().items() if k!='_'}
            if 'users' in args: args['users']=[utils.get_input_user(await self.client.get_input_entity(u)) for u in args['users']]
            rules.append(cls(**args))
        for ids,cls in [(allow,t.InputPrivacyValueAllowUsers),(deny,t.InputPrivacyValueDisallowUsers)]:
            if ids:
                users=[utils.get_input_user(await self.client.get_input_entity(u)) for u in ids]
                rules.insert(0,cls(users))
        if allow is not None and deny is not None and set(allow)&set(deny): raise ValueError(tr('A contact cannot be in both exception lists.'))
        rules.append(BASE_RULES[base]())
        return await self.client(f.account.SetPrivacyRequest(getattr(t,'InputPrivacyKey'+PRIVACY_KEYS[label])(),rules))

    async def global_privacy(self):
        return await self.client(f.account.GetGlobalPrivacySettingsRequest())

    async def save_global_privacy(self, changes):
        allowed={'hide_read_marks','archive_and_mute_new_noncontact_peers','new_noncontact_peers_require_premium'}
        if not set(changes)<=allowed: raise ValueError('Unsupported privacy setting')
        current=await self.global_privacy()
        for key,value in changes.items(): setattr(current,key,bool(value))
        return await self.client(f.account.SetGlobalPrivacySettingsRequest(current))

    async def apply_wallpaper(self, peer, path=None, for_both=False):
        input_peer=await self.client.get_input_entity(peer)
        if not isinstance(input_peer,t.InputPeerUser):
            raise ValueError(tr('Synchronized backgrounds are available in private chats.'))
        if path is None:
            return await self.client(f.messages.SetChatWallPaperRequest(input_peer,for_both=for_both))
        uploaded=await self.client.upload_file(str(path))
        settings=t.WallPaperSettings()
        wallpaper=await self.client(f.account.UploadWallPaperRequest(uploaded,'image/jpeg',settings,for_chat=True))
        return await self.client(f.messages.SetChatWallPaperRequest(input_peer,for_both=for_both,
            wallpaper=t.InputWallPaper(wallpaper.id,wallpaper.access_hash),settings=settings))

    async def message_palettes(self):
        response=await self.client(f.help.GetPeerColorsRequest(hash=0))
        return {option.color_id:{'light':getattr(option.colors,'colors',[]) or [],
            'dark':getattr(option.dark_colors or option.colors,'colors',[]) or []} for option in response.colors}

    async def reply_contexts(self,peer,ids):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            return self.secret_chats.reply_contexts(peer, ids)
        messages=await self.client.get_messages(peer,ids=list(ids)[:80])
        await self.resolve_missing_senders(messages)
        return {m.id:self.message(m) for m in messages if isinstance(m,t.Message) and utils.get_peer_id(m.peer_id)==peer}

    async def sender_style(self,peer):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            try:
                peer = self.secret_chats.session_for_peer(peer).user_id
            except Exception:
                return (None, None, None)
        entity=await self.client.get_entity(peer)
        color=getattr(entity,'color',None)
        from .profile_customization import overlay_sender
        return overlay_sender(self,getattr(entity,'id',None),
            (getattr(color,'color',None),getattr(color,'background_emoji_id',None),getattr(getattr(entity,'emoji_status',None),'document_id',None)))
