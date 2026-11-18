"""On-demand membership, history and profile requests, scoped to one backend."""
from datetime import datetime, timezone
from telethon import functions as f, types as t, utils
from .i18n import tr

MUTE_PRESETS = ((3600, 'Silenciar 1 hora'), (28800, 'Silenciar 8 horas'),
                (172800, 'Silenciar 2 días'), (-1, 'Silenciar para siempre'))


def mute_deadline(seconds, now=None):
    if type(seconds) is not int or seconds < -1:
        raise ValueError(tr('Duración no válida.'))
    if seconds == -1:
        timestamp = 2147483647
    elif seconds == 0:
        timestamp = 0
    else:
        timestamp = min(2147483647, int((now or datetime.now(timezone.utc)).timestamp()) + seconds)
    return datetime.fromtimestamp(timestamp, timezone.utc)


class HistoryPage(list):
    def __init__(self, items=(), *, next_offset=0, more=False):
        super().__init__(items)
        self.next_offset, self.more = next_offset, more


class PeerTools:
    def channel_call_controls(self):
        controls = getattr(self, '_channel_call_controls', None)
        if controls is None:
            from .channel_calls import ChannelCalls
            controls = self._channel_call_controls = ChannelCalls(self.client)
        return controls

    async def read_discussion(self, peer, root_id, max_id):
        if any(type(value) is not int or value <= 0 for value in (root_id, max_id)):
            raise ValueError(tr('Mensaje no válido.'))
        entity = await self.client.get_input_entity(peer)
        return await self.client(f.messages.ReadDiscussionRequest(entity, root_id, max_id))

    async def discussion_message(self, peer, post_id):
        """Resolve the forwarded discussion root without joining its group."""
        if type(post_id) is not int or post_id <= 0:
            raise ValueError(tr('Mensaje no válido.'))
        source = await self.client.get_input_entity(peer)
        source_id = utils.get_peer_id(source)
        result = await self.client(f.messages.GetDiscussionMessageRequest(source, post_id))
        for entity in [*getattr(result, 'users', ()), *getattr(result, 'chats', ())]:
            self.cache_name(utils.get_peer_id(entity), utils.get_display_name(entity))
            if hasattr(self, '_capability_entities') and isinstance(self._capability_entities, dict):
                self._capability_entities[utils.get_peer_id(entity)] = entity
        roots = [m for m in result.messages if getattr(m, 'peer_id', None) is not None
                 and utils.get_peer_id(m.peer_id) != source_id and not isinstance(m, t.MessageEmpty)]
        if not roots:
            raise ValueError(tr('No hay un hilo de comentarios disponible para esta publicación.'))
        root = roots[0]
        await self.resolve_missing_senders([root])
        return {'peer': utils.get_peer_id(root.peer_id), 'root_id': root.id,
                'root': self.message(root), 'unread_count': getattr(result, 'unread_count', 0)}

    async def discussion_history(self, peer, root_id, offset=0):
        if type(root_id) is not int or root_id <= 0 or type(offset) is not int or offset < 0:
            raise ValueError(tr('Mensaje no válido.'))
        entity = await self.client.get_input_entity(peer)
        result = await self.client(f.messages.GetRepliesRequest(entity, root_id,
            offset_id=offset, offset_date=None, add_offset=0, limit=80, max_id=0, min_id=0, hash=0))
        for item in [*getattr(result, 'users', ()), *getattr(result, 'chats', ())]:
            self.cache_name(utils.get_peer_id(item), utils.get_display_name(item))
        raw = [m for m in result.messages if not isinstance(m, t.MessageEmpty)]
        await self.resolve_missing_senders(raw)
        # The raw cursor is independent of filtered rows and rendering order.
        return HistoryPage([self.message(m) for m in reversed(raw)],
            next_offset=result.messages[-1].id if result.messages else offset,
            more=len(result.messages) == 80)

    async def search_discussion(self, peer, root_id, query='', pinned=False):
        if type(root_id) is not int or root_id <= 0:
            raise ValueError(tr('Mensaje no válido.'))
        entity = await self.client.get_input_entity(peer)
        filter_type = t.InputMessagesFilterPinned if pinned else t.InputMessagesFilterEmpty
        result = await self.client(f.messages.SearchRequest(
            peer=entity, q=query, top_msg_id=root_id, filter=filter_type(),
            min_date=None, max_date=None, offset_id=0, add_offset=0, limit=50, max_id=0, min_id=0, hash=0))
        for item in [*getattr(result, 'users', ()), *getattr(result, 'chats', ())]:
            self.cache_name(utils.get_peer_id(item), utils.get_display_name(item))
        messages = [message for message in result.messages if not isinstance(message, t.MessageEmpty)]
        await self.resolve_missing_senders(messages)
        return [self.message(message) for message in messages]

    async def join_chat(self, peer):
        entity = await self.client.get_entity(peer)
        if not isinstance(entity, t.Channel):
            raise ValueError(tr('Para un grupo privado necesitas su enlace de invitación.'))
        if not getattr(entity, 'left', False):
            return {'joined': True, 'requested': False}
        from telethon.errors import InviteRequestSentError
        try:
            await self.client(f.channels.JoinChannelRequest(entity))
        except InviteRequestSentError:
            return {'joined': False, 'requested': True}
        return {'joined': True, 'requested': False}

    async def inspect_invite(self, token):
        import re
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', token):
            raise ValueError(tr('Enlace de invitación no válido.'))
        return await self.client(f.messages.CheckChatInviteRequest(token))

    async def join_invite(self, token):
        current = await self.inspect_invite(token)
        if isinstance(current, t.ChatInviteAlready):
            return {'joined': True, 'requested': False, 'peer': utils.get_peer_id(current.chat)}
        from telethon.errors import InviteRequestSentError
        try:
            result = await self.client(f.messages.ImportChatInviteRequest(token))
        except InviteRequestSentError:
            return {'joined': False, 'requested': True, 'peer': None}
        chats = getattr(result, 'chats', ())
        return {'joined': True, 'requested': False, 'peer': utils.get_peer_id(chats[0]) if chats else None}

    async def leave_chat(self, peer):
        entity = await self.client.get_entity(peer)
        if isinstance(entity, t.Channel):
            return await self.client(f.channels.LeaveChannelRequest(entity))
        if isinstance(entity, t.Chat):
            return await self.client(f.messages.DeleteChatUserRequest(entity.id, t.InputUserSelf(), revoke_history=False))
        raise ValueError(tr('Elige un grupo o canal.'))

    async def similar_channels(self, peer):
        from .backend import Chat
        entity = await self.client.get_entity(peer)
        if not isinstance(entity, t.Channel) or not entity.broadcast:
            return []
        result = await self.client(f.channels.GetChannelRecommendationsRequest(entity))
        return [Chat(utils.get_peer_id(item), utils.get_display_name(item), kind='channel',
                     member=not bool(getattr(item, 'left', False)), entity=item) for item in result.chats]

    async def poll_messages(self, peer, query='', offset=0):
        # Telegram has no dedicated poll search filter. One bounded history page
        # per click retains the raw cursor even if it contains no polls.
        messages = await self.client.get_messages(peer, search=query, limit=100, offset_id=offset)
        selected = [m for m in messages if isinstance(getattr(m, 'media', None), t.MessageMediaPoll)]
        await self.resolve_missing_senders(selected)
        return HistoryPage([self.message(m) for m in selected],
                           next_offset=messages[-1].id if messages else offset,
                           more=len(messages) == 100)

    async def call_history(self, offset=None, missed=False):
        ident = offset or 0
        # Telegram Desktop uses messages.search with an empty peer for calls.
        # searchGlobal rejects this filter on the live API (INPUT_FILTER_INVALID).
        result = await self.client(f.messages.SearchRequest(
            peer=t.InputPeerEmpty(), q='', filter=t.InputMessagesFilterPhoneCalls(missed=missed),
            min_date=None, max_date=None, offset_id=ident, add_offset=0, limit=50,
            max_id=0, min_id=0, hash=0))
        for entity in [*getattr(result, 'users', ()), *getattr(result, 'chats', ())]:
            self.cache_name(utils.get_peer_id(entity), utils.get_display_name(entity))
            if hasattr(self, '_capability_entities') and isinstance(self._capability_entities, dict):
                self._capability_entities[utils.get_peer_id(entity)] = entity
        items = []
        for message in result.messages:
            action = getattr(message, 'action', None)
            if not isinstance(action, (t.MessageActionPhoneCall, t.MessageActionConferenceCall)):
                continue
            ident = utils.get_peer_id(message.peer_id)
            reason = type(getattr(action, 'reason', None)).__name__
            from .call_outcomes import discard_outcome
            outcome=discard_outcome(getattr(action,'reason',None))
            items.append({'id': message.id, 'peer': ident, 'name': self.names.get(ident, str(ident)),
                'date': message.date, 'outgoing': bool(message.out), 'video': bool(action.video),
                'duration': getattr(action, 'duration', None), 'outcome':outcome,
                'conference':isinstance(action,t.MessageActionConferenceCall),
                'missed': bool(getattr(action, 'missed', False)) or reason.endswith(('Missed', 'Busy'))})
        # A final page needs no cursor. Resolving its last peer unnecessarily
        # can fail for an old/deleted contact and hide otherwise valid history.
        last = result.messages[-1] if len(result.messages) == 50 else None
        cursor = last.id if last else None
        return {'items': items, 'next': cursor, 'more': len(result.messages) == 50 and cursor != offset}

    async def profile_posts(self, peer, offset=0):
        result = await self.client(f.stories.GetPinnedStoriesRequest(await self.client.get_input_entity(peer), offset, 30))
        items = list(result.stories)
        return {'items': items, 'next': items[-1].id if items else offset,
                'more': len(items) == 30}

    async def profile_music(self, peer, offset=0):
        entity = await self.client.get_input_entity(peer)
        result = await self.client(f.users.GetSavedMusicRequest(utils.get_input_user(entity), offset, 30, 0))
        items = list(getattr(result, 'documents', ()))
        return {'items': items, 'next': offset + len(items), 'more': offset + len(items) < getattr(result, 'count', 0)}

    async def set_profile_tab(self, name):
        choices = {'posts': t.ProfileTabPosts, 'gifts': t.ProfileTabGifts,
                   'media': t.ProfileTabMedia, 'files': t.ProfileTabFiles,
                   'music': t.ProfileTabMusic, 'voice': t.ProfileTabVoice,
                   'links': t.ProfileTabLinks, 'gifs': t.ProfileTabGifs}
        if name not in choices:
            raise ValueError(tr('Pestaña no válida.'))
        return await self.client(f.account.SetMainProfileTabRequest(choices[name]()))

    async def save_profile_music(self, document, remove=False, after=None):
        return await self.client(f.account.SaveMusicRequest(utils.get_input_document(document),
            unsave=remove, after_id=utils.get_input_document(after) if after is not None else None))
