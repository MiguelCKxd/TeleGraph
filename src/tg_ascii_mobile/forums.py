"""Account-scoped forum navigation using the shared Telegram backend."""
import asyncio


class MobileForums:
    def is_forum_chat(self, peer):
        known = self.__dict__.get('forum_peers', {})
        if (self.account, peer) in known:
            return known[(self.account, peer)]
        chat = next((item for item in self.chats if item.id == peer), None)
        return bool(chat and (getattr(chat, 'forum', False) or getattr(getattr(chat, 'entity', None), 'forum', False)))

    def message_scope(self, peer, message):
        topic = getattr(message, 'topic_id', None)
        if topic is None and self.is_forum_chat(peer):
            topic = 1
        return topic, topic or getattr(message, 'thread_id', None)

    def reading_message(self, account, peer, message):
        if account != self.account:
            return False
        topic, root = self.message_scope(peer, message)
        if topic is None and ((peer == self.open_peer and not self.preview) or peer in self.window_peers):
            return True
        return root is not None and any(context == (account, peer, root) for context, _ in self.active_discussions())

    async def api_forum_toggle(self, peer, enabled, migrate=False, account=None):
        chat = await self.forum_call('forum_toggle', int(peer), bool(enabled), migrate=bool(migrate), account=account)
        self.__dict__.setdefault('forum_peers', {})[(self.account, chat.id)] = bool(enabled)
        self.loop.create_task(self.refresh_chats())
        return self.chat_json(chat)

    async def forum_call(self, operation, *args, account=None, **kwargs):
        self.check_active_account(account)
        selected, backend = self.account, self.backend
        if self.locked or backend is None:
            raise PermissionError('locked')
        result = await asyncio.wait_for(getattr(backend, operation)(*args, **kwargs), 60)
        if self.account != selected or self.backend is not backend or self.locked:
            raise ValueError('The active account changed.')
        return result

    async def api_forum_topics(self, peer, query='', cursor=None, account=None, open_view=False, window_peer=None):
        self.check_active_account(account)
        peer = int(peer)
        if open_view:
            if window_peer is None:
                self.open_revision += 1
                revision = self.open_revision
            elif window_peer == peer and window_peer in self.window_peers:
                revision = self.window_revisions[window_peer] = object()
            else:
                raise ValueError('The chat window is no longer open.')
        result = await self.forum_call('forum_topics', peer, query=str(query), cursor=cursor, account=account)
        if open_view:
            current = self.open_revision if window_peer is None else self.window_revisions.get(window_peer)
            if current != revision:
                raise ValueError('The active conversation changed.')
            if window_peer is None:
                self.open_peer = self.open_discussion = None
                self.discussion_messages = {}
            else:
                self.window_discussions[window_peer] = (None, {})
        self.__dict__.setdefault('forum_peers', {})[(self.account, peer)] = True
        return result

    async def api_forum_topic_info(self, peer, topic_id, account=None):
        from tg_ascii.forum_topics import ForumTopicUnavailable
        owner, backend = self.account, self.backend
        try:
            return await self.forum_call('forum_topic', int(peer), int(topic_id), account=account)
        except ForumTopicUnavailable:
            # Only a definitive server response means that this topic disappeared.
            if self.locked or self.account != owner or self.backend is not backend:
                raise ValueError('The active account changed.')
            return None

    async def api_forum_open(self, peer, topic_id, account=None, window_peer=None):
        self.check_active_account(account)
        peer, topic_id = int(peer), int(topic_id)
        selected, backend = self.account, self.backend
        if window_peer is None:
            self.open_revision += 1
            revision = self.open_revision
        else:
            if window_peer != peer or peer not in self.window_peers:
                raise ValueError('The chat window is no longer open.')
            revision = object()
            self.window_revisions[window_peer] = revision
        topic = await self.forum_call('forum_topic', peer, topic_id, account=selected)
        page = await self.forum_call('forum_history', peer, topic_id, account=selected)
        current = self.open_revision if window_peer is None else self.window_revisions.get(window_peer)
        if current != revision or backend is not self.backend:
            raise ValueError('The active conversation changed.')
        self.__dict__.setdefault('forum_peers', {})[(self.account, peer)] = True
        context = (selected, peer, topic_id)
        messages = {message.id: message for message in page}
        if window_peer is None:
            self.open_discussion, self.discussion_messages = context, messages
            self.open_peer = None
        else:
            self.window_discussions[window_peer] = (context, messages)
        self.loop.create_task(self._read_comments(backend, peer, topic_id, page))
        return {'peer': peer, 'topic': topic,
                'messages': [self.message_json(m) for m in page],
                'draft': self.draft_record(peer, topic_id),
                'outbox': [item for item in self.outbox_items(selected, peer)['items']
                           if item['thread_root'] == topic_id],
                'next': page.next_offset, 'more': page.more,
                **self.translation_state(peer, page, topic_id)}

    async def api_forum_older(self, peer, topic_id, before=0, account=None, window_peer=None):
        peer, topic_id = int(peer), int(topic_id)
        page = await self.forum_call('forum_history', peer, topic_id, before=int(before), account=account)
        context, messages = self.discussion_view(window_peer)
        if context == (self.account, peer, topic_id):
            messages.update((m.id, m) for m in page)
        return {'messages': [self.message_json(m) for m in page],
                'next': page.next_offset, 'more': page.more,
                **self.translation_state(peer, page, topic_id)}

    async def api_forum_manage(self, peer, action, topic_id=None, title=None, closed=None,
                               hidden=None, pinned=None, icon_emoji_id=None, account=None):
        peer = int(peer)
        if action == 'create':
            result = await self.forum_call('forum_create', peer, str(title or ''), account=account)
        elif action == 'edit':
            result = await self.forum_call('forum_edit', peer, int(topic_id), title=title,
                                           closed=closed, hidden=hidden,
                                           icon_emoji_id=int(icon_emoji_id) if icon_emoji_id else None,
                                           account=account)
        elif action == 'pin' and type(pinned) is bool:
            result = await self.forum_call('forum_pin', peer, int(topic_id), pinned, account=account)
        elif action == 'delete':
            result = await self.forum_call('forum_delete', peer, int(topic_id), account=account)
        else:
            raise ValueError('Unsupported topic action.')
        self.emit('forum_topics', {'peer': peer})
        return result

    async def api_linked_discussion(self, peer, account=None):
        return await self.forum_call('linked_discussion', int(peer), account=account)
