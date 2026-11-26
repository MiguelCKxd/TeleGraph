"""Telegram group forums. A topic ID is meaningful only within its account and peer."""
from contextlib import ExitStack
from datetime import datetime, timezone
from secrets import token_hex

from telethon import functions as f, types as t, utils

from .i18n import tr
from .peer_tools import HistoryPage
from .sticker_search import cached
from .transfers import tracked_transfer, transfer_timeout

GENERAL = 1
TOPIC_COLORS = (0x6FB9F0, 0xFFD67E, 0xCB86DB, 0x8EEE98, 0xFF93B2, 0xFB6F5F)


def _id(value):
    if type(value) is not int or not 0 < value <= 0x7fffffff:
        raise ValueError(tr('Mensaje no válido.'))
    return value


class ForumTopicUnavailable(ValueError):
    """Telegram returned a deleted marker or omitted this exact topic ID."""


def _denied():
    return ValueError(tr('Telegram does not allow this action for your account.'))


def _title(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 128:
        raise ValueError(tr('Invalid chat title.'))
    return value.strip()


def _emoji(value):
    if value is not None and (type(value) is not int or not 0 <= value < 2**63):
        raise ValueError(tr('Invalid emoji.'))
    return value


def input_reply(value):
    """Keep the top_msg_id when a structured composer passes a forum reply."""
    if value is None or isinstance(value, t.InputReplyToMessage):
        return value
    return t.InputReplyToMessage(_id(value))


def _peer_id(raw):
    peer = getattr(raw, 'peer_id', None)
    return utils.get_peer_id(peer) if peer is not None else None


def message_topic(raw, forum=False):
    if isinstance(getattr(raw, 'action', None), t.MessageActionTopicCreate):
        return raw.id
    reply = getattr(raw, 'reply_to', None)
    if getattr(reply, 'forum_topic', False):
        return getattr(reply, 'reply_to_top_id', None) or getattr(reply, 'reply_to_msg_id', None) or GENERAL
    return GENERAL if forum else None


def _member(entity):
    return not any(getattr(entity, key, False) for key in ('left', 'kicked', 'deactivated'))


def _allowed(entity, *fields):
    if not _member(entity):
        return False
    if entity.creator or entity.admin_rights:
        return True
    return not any(getattr(rights, field, False) for rights in
                   (entity.banned_rights, entity.default_banned_rights) for field in fields)


def _create_allowed(entity):
    return bool(entity.creator or getattr(entity.admin_rights, 'manage_topics', False)) or _allowed(entity, 'view_messages', 'manage_topics')


def _remember_result(backend, result):
    for item in [*getattr(result, 'chats', ()), *getattr(result, 'users', ())]:
        backend.cache_name(utils.get_peer_id(item), utils.get_display_name(item))


def _topic_row(entity, topic, own_deletable=False):
    manage = _member(entity) and bool(entity.creator or getattr(entity.admin_rights, 'manage_topics', False))
    edit = _member(entity) and (manage or bool(topic.my))
    general = topic.id == GENERAL
    delete = _member(entity) and bool(entity.creator or getattr(entity.admin_rights, 'delete_messages', False)
                                     or topic.my and (topic.top_message == topic.id or own_deletable))
    return dict(id=topic.id, title=topic.title, icon_color=topic.icon_color, icon_emoji_id=topic.icon_emoji_id,
                closed=bool(topic.closed), hidden=bool(topic.hidden), pinned=bool(topic.pinned),
                unread_count=topic.unread_count, top_message=topic.top_message, general=general,
                read_inbox_max_id=topic.read_inbox_max_id, read_outbox_max_id=topic.read_outbox_max_id,
                can_edit=edit, can_hide=general and manage, can_delete=not general and delete,
                can_pin=manage, can_send=_allowed(entity, 'view_messages', 'send_messages')
                and (not topic.closed or edit) and (not topic.hidden or manage))


class ForumTopics:
    def _known_forum(self, peer):
        entities = getattr(self, '_capability_entities', {})
        if peer in entities:
            return bool(getattr(entities[peer], 'forum', False))
        return peer in getattr(self, '_forum_epochs', {})

    def forum_message_topic(self, raw):
        return message_topic(raw, getattr(getattr(raw, 'chat', None), 'forum', False)
                             or self._known_forum(_peer_id(raw)))

    def _forum_changed(self, peer, topic_id=None):
        epochs = self.__dict__.setdefault('_forum_epochs', {})
        epochs[peer] = epochs.get(peer, 0) + 1
        if getattr(self, 'on_change', None):
            self.on_change('forum_topics', (peer, topic_id))

    def forum_update(self, update):
        message = getattr(update, 'message', None)
        if isinstance(update, (t.UpdateNewChannelMessage, t.UpdateEditChannelMessage)):
            peer = _peer_id(message)
            topic = self.forum_message_topic(message)
            if topic is not None:
                self._forum_changed(peer, topic)
        elif isinstance(update, (t.UpdatePinnedForumTopic, t.UpdatePinnedForumTopics)):
            self._forum_changed(utils.get_peer_id(update.peer), getattr(update, 'topic_id', None))
        elif isinstance(update, (t.UpdateReadChannelDiscussionInbox, t.UpdateReadChannelDiscussionOutbox,
                                 t.UpdateDeleteChannelMessages, t.UpdateChannel)):
            peer = utils.get_peer_id(t.PeerChannel(update.channel_id))
            if self._known_forum(peer):
                self._forum_changed(peer, getattr(update, 'top_msg_id', None))
        elif isinstance(update, t.UpdateMessageReactions):
            peer = utils.get_peer_id(update.peer)
            if self._known_forum(peer):
                self._forum_changed(peer, getattr(update, 'top_msg_id', None) or GENERAL)
        elif isinstance(update, t.UpdateChatDefaultBannedRights):
            peer = utils.get_peer_id(update.peer)
            if self._known_forum(peer):
                self._forum_changed(peer)

    async def _forum_entity(self, peer, fresh=False):
        entity = getattr(self, '_capability_entities', {}).get(peer) if isinstance(peer, int) else None
        if fresh or not isinstance(entity, t.Channel) or entity.min or not entity.forum:
            # getEntity resolves the current Channel and its permissions. FullChannel also
            # fetches all profile details, and is rate-limited during consecutive sends.
            entity = await self.client.get_entity(peer)
        if not isinstance(entity, t.Channel) or not entity.megagroup or not entity.forum:
            raise ValueError(tr('Choose a forum group.'))
        from .capability_cache import remember
        remember(self, entity, notify=False)
        peer_id = utils.get_peer_id(entity)
        self.__dict__.setdefault('_forum_epochs', {}).setdefault(peer_id, 0)
        return entity

    async def linked_discussion(self, peer):
        entity, full = await self.community_info(peer, allow_left=True)
        link = getattr(full, 'linked_chat_id', None)
        if not isinstance(entity, t.Channel) or not link:
            return None
        other = await self.client.get_entity(t.PeerChannel(link))
        if not isinstance(other, t.Channel) or other.id != link:
            return None
        return dict(peer=utils.get_peer_id(other), title=other.title, forum=bool(other.forum),
                    kind='group' if other.megagroup else 'channel')

    async def forum_topics(self, peer, query='', cursor=None, limit=50):
        if not isinstance(query, str) or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError(tr('Invalid search.'))
        query = query.strip()
        entity = await self._forum_entity(peer)
        peer_id = utils.get_peer_id(entity)
        if not hasattr(self, '_forum_cursor_owner'):
            self._forum_cursor_owner = token_hex(12)
        offset_date = offset_id = offset_topic = seen = 0
        pinned_ids = set()
        if cursor is not None:
            if (not isinstance(cursor, dict) or cursor.get('peer') != peer_id or cursor.get('query') != query
                    or cursor.get('owner') != self._forum_cursor_owner):
                raise ValueError(tr('Invalid search.'))
            pinned = cursor.get('pinned', ())
            if not isinstance(pinned, (tuple, list)) or len(pinned) > 1024:
                raise ValueError(tr('Invalid search.'))
            pinned_ids.update(_id(i) for i in pinned)
            seen = cursor.get('seen', 0)
            offset_date, offset_id, offset_topic = (cursor.get(k) for k in ('offset_date', 'offset_id', 'offset_topic'))
            if any(type(v) is not int or not 0 <= v <= 0x7fffffff for v in (offset_date, offset_id, offset_topic, seen)):
                raise ValueError(tr('Invalid search.'))

        async def load():
            when = datetime.fromtimestamp(offset_date, timezone.utc) if offset_date else None
            result = await self.client(f.messages.GetForumTopicsRequest(entity, when, offset_id, offset_topic,
                                                                        limit, q=query or None))
            _remember_result(self, result)
            return result

        result = await self._forum_cached(peer_id, ('list', query, offset_date, offset_id, offset_topic, limit), load)
        topics = [x for x in result.topics if isinstance(x, t.ForumTopic) and utils.get_peer_id(x.peer) == peer_id]
        entity = next((x for x in result.chats if isinstance(x, t.Channel) and x.id == entity.id), entity)
        new_topics = [x for x in topics if x.id not in pinned_ids]
        rows = [_topic_row(entity, x) for x in new_topics]
        cursor_out = None
        # Telegram may append pinned rows beyond limit, repeat them on later pages
        # and exclude General from count. The raw page and advancing anchor control exhaustion.
        if new_topics and (len(result.topics) >= limit or seen + len(rows) < result.count):
            ordinary = [x for x in new_topics if not x.pinned]
            last = ordinary[-1] if ordinary else new_topics[-1]
            top = next((m for m in result.messages if m.id == last.top_message and _peer_id(m) == peer_id), None)
            date = last.date if result.order_by_create_date or top is None else top.date
            next_values = (int(date.timestamp()), last.top_message or 0, last.id)
            if next_values != (offset_date, offset_id, offset_topic):
                pinned_ids.update(x.id for x in topics if x.pinned)
                cursor_out = dict(peer=peer_id, query=query, owner=self._forum_cursor_owner,
                                  offset_date=next_values[0], offset_id=next_values[1], offset_topic=last.id,
                                  seen=seen + len(rows), pinned=sorted(pinned_ids))
        return dict(topics=rows, next_cursor=cursor_out, can_create=_create_allowed(entity))

    async def _forum_cached(self, peer_id, key, load):
        # An update while an RPC is in flight invalidates its snapshot for every open view.
        for attempt in range(2):
            epoch = self._forum_epochs[peer_id]
            result = await cached(self, ('forums', peer_id, epoch, *key), load, ttl=20)
            if self._forum_epochs[peer_id] == epoch:
                return result
        return await load()

    async def _forum_detail(self, peer, topic_id, *, fresh=False, check_delete=False):
        topic_id = _id(topic_id)
        entity = await self._forum_entity(peer, fresh)
        peer_id = utils.get_peer_id(entity)
        async def load():
            result = await self.client(f.messages.GetForumTopicsByIDRequest(entity, [topic_id]))
            _remember_result(self, result)
            current = next((c for c in result.chats if isinstance(c, t.Channel) and c.id == entity.id
                            and not c.min), entity)
            topic = next((x for x in result.topics if isinstance(x, t.ForumTopic) and x.id == topic_id
                          and utils.get_peer_id(x.peer) == peer_id), None)
            return current, topic
        entity, topic = await load() if fresh else await self._forum_cached(peer_id, ('detail', topic_id), load)
        if topic is None:
            raise ForumTopicUnavailable(tr('This topic is no longer available.'))
        own_deletable = False
        if check_delete and topic.my and topic_id != GENERAL and topic.top_message != topic_id and not (
                entity.creator or getattr(entity.admin_rights, 'delete_messages', False)):
            reply = await self.client(f.messages.GetRepliesRequest(entity, topic_id, 0, None, 0, 12, 0, 0, 0))
            messages = [x for x in reply.messages if not isinstance(x, t.MessageEmpty) and x.id != topic_id]
            own_deletable = len(reply.messages) < 12 and len(messages) <= 10 and all(
                _peer_id(x) == peer_id and x.out and message_topic(x, True) == topic_id for x in messages)
        return entity, _topic_row(entity, topic, own_deletable)

    async def forum_topic(self, peer, topic_id):
        return (await self._forum_detail(peer, topic_id, check_delete=True))[1]

    async def forum_history(self, peer, topic_id, before=0, limit=80, *, around=None):
        entity, row = await self._forum_detail(peer, topic_id)
        return await self._thread_page(entity, topic_id, before, limit, around, forum=True,
                                       read_max=row['read_outbox_max_id'])

    async def discussion_around(self, peer, root_id, message_id, limit=80):
        return await self._thread_page(await self.client.get_input_entity(peer), _id(root_id), 0, limit,
                                       _id(message_id), forum=False)

    async def _thread_page(self, entity, root_id, before, limit, around, *, forum, read_max=0):
        if type(before) is not int or before < 0 or type(limit) is not int or not 1 <= limit <= 100 or before and around:
            raise ValueError(tr('Mensaje no válido.'))
        peer = utils.get_peer_id(entity)
        def belongs(m):
            if not m or isinstance(m, t.MessageEmpty) or _peer_id(m) != peer:
                return False
            if forum:
                return message_topic(m, True) == root_id
            header = getattr(m, 'reply_to', None)
            return m.id == root_id or (getattr(header, 'reply_to_top_id', None)
                                       or getattr(header, 'reply_to_msg_id', None)) == root_id

        target = None
        if around is not None:
            target = await self.client.get_messages(entity, ids=_id(around))
            if not belongs(target):
                return HistoryPage()
        async def load():
            return await self.client(f.messages.GetRepliesRequest(entity, root_id, around or before, None,
                                      -(limit // 2) if around else 0, limit, 0, 0, 0))
        result = await self._forum_cached(peer, ('history', root_id, before, limit, around), load) if forum else await load()
        _remember_result(self, result)
        by_id = {m.id: m for m in result.messages if belongs(m) and (not before or m.id < before)}
        if target is not None:
            by_id[target.id] = target
        raw = sorted(by_id.values(), key=lambda m: m.id)
        await self.resolve_missing_senders(raw)
        items = [self.message(m) for m in raw]
        if forum:
            for m in items:
                m.topic_id = root_id
                m.read = m.outgoing and m.id <= read_max
        next_offset = min((m.id for m in result.messages if m.id > 0), default=before)
        return HistoryPage(items, next_offset=next_offset,
                           more=len(result.messages) >= limit and (not before or next_offset < before))

    async def forum_mark_read(self, peer, topic_id, max_id):
        entity, row = await self._forum_detail(peer, topic_id)
        read_to = min(_id(max_id), row['top_message'])
        peer_id = utils.get_peer_id(entity)
        confirmed = self.__dict__.setdefault('_forum_read_inbox', {})
        key = (peer_id, topic_id)
        if not read_to or read_to <= max(confirmed.get(key, 0), row['read_inbox_max_id']):
            return True
        result = await self.read_discussion(peer_id, topic_id, read_to)
        if result:
            confirmed[key] = max(read_to, confirmed.get(key, 0))
            self._forum_changed(peer_id, topic_id)
        return result

    async def forum_search(self, peer, topic_id, query='', pinned=False, limit=50):
        entity, _ = await self._forum_detail(peer, topic_id)
        if not isinstance(query, str) or type(pinned) is not bool or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError(tr('Invalid search.'))
        result = await self.client(f.messages.SearchRequest(
            entity, query, t.InputMessagesFilterPinned() if pinned else t.InputMessagesFilterEmpty(),
            None, None, 0, 0, limit, 0, 0, 0, top_msg_id=topic_id))
        _remember_result(self, result)
        raw = [m for m in result.messages if not isinstance(m, t.MessageEmpty) and
               _peer_id(m) == utils.get_peer_id(entity) and message_topic(m, True) == topic_id]
        await self.resolve_missing_senders(raw)
        return [self.message(m) for m in raw]

    async def forum_scheduled(self, peer, topic_id):
        entity, _ = await self._forum_detail(peer, topic_id)
        # Scheduled history has no topic argument. Filter its server rows before exposing them.
        return [m for m in await self.scheduled_history(utils.get_peer_id(entity))
                if _peer_id(m) == utils.get_peer_id(entity) and message_topic(m, True) == topic_id]

    async def forum_toggle(self, peer, enabled, migrate=False):
        from .backend import Chat
        if type(enabled) is not bool or type(migrate) is not bool:
            raise _denied()
        entity, _ = await self.community_info(peer)
        if not getattr(entity, 'creator', False):
            raise _denied()
        if isinstance(entity, t.Chat):
            if getattr(entity, 'migrated_to', None):
                entity, _ = await self.community_info(entity.migrated_to)
            elif enabled and migrate:
                result = await self.client(f.messages.MigrateChatRequest(entity.id))
                entity = next((c for c in result.chats if isinstance(c, t.Channel) and c.megagroup), None)
                if entity is None:
                    raise ValueError(tr('This group must be upgraded before linking.'))
            else:
                raise ValueError(tr('This group must be upgraded to enable topics.'))
        if not isinstance(entity, t.Channel) or not entity.megagroup or not entity.creator:
            raise _denied()
        peer_id = utils.get_peer_id(entity)
        if bool(entity.forum) != enabled:
            result = await self.client(f.channels.ToggleForumRequest(entity, enabled, bool(entity.forum_tabs)))
            confirmed = next((c for c in getattr(result, 'chats', ()) if isinstance(c, t.Channel)
                              and c.id == entity.id and bool(c.forum) == enabled), None)
            if confirmed is None:
                confirmed, _ = await self.community_info(peer_id)
            if bool(confirmed.forum) != enabled:
                raise ValueError(tr('Reopen this group to check its topic settings.'))
            entity = confirmed
        from .capability_cache import remember
        remember(self, entity)
        self._forum_changed(peer_id)
        return Chat(peer_id, entity.title, kind='group', member=_member(entity), entity=entity,
                    forum=bool(entity.forum), has_link=bool(entity.has_link))

    async def forum_create(self, peer, title, *, icon_color=None, icon_emoji_id=None):
        title = _title(title)
        if icon_color is not None and (type(icon_color) is not int or icon_color not in TOPIC_COLORS):
            raise ValueError(tr('Invalid topic color.'))
        entity = await self._forum_entity(peer, fresh=True)
        if not _create_allowed(entity):
            raise _denied()
        req = f.messages.CreateForumTopicRequest(entity, title, icon_color=icon_color, icon_emoji_id=_emoji(icon_emoji_id))
        result = await self.client(req)
        peer_id = utils.get_peer_id(entity)
        updates = getattr(result, 'updates', ())
        ident = next((u.id for u in updates if isinstance(u, t.UpdateMessageID) and u.random_id == req.random_id), None)
        if not ident:
            ident = next((u.message.id for u in updates if isinstance(u, t.UpdateNewChannelMessage)
                          and _peer_id(u.message) == peer_id and isinstance(getattr(u.message, 'action', None),
                                                                            t.MessageActionTopicCreate)), None)
        self._forum_changed(peer_id, ident)
        if not ident:
            raise ValueError(tr('Telegram did not return the new topic. Refresh the topic list.'))
        return await self.forum_topic(peer_id, ident)

    async def forum_edit(self, peer, topic_id, *, title=None, icon_emoji_id=None, closed=None, hidden=None):
        if all(v is None for v in (title, icon_emoji_id, closed, hidden)) or any(
                v is not None and type(v) is not bool for v in (closed, hidden)):
            raise ValueError(tr('Invalid topic settings.'))
        entity, row = await self._forum_detail(peer, topic_id, fresh=True)
        if not row['can_edit'] or hidden is not None and not row['can_hide'] or topic_id == GENERAL and icon_emoji_id is not None:
            raise _denied()
        title = _title(title) if title is not None else None
        icon = _emoji(icon_emoji_id)
        appearance = {}
        if title is not None and row['title'] != title:
            appearance['title'] = title
        if icon is not None and (row['icon_emoji_id'] or 0) != icon:
            appearance['icon_emoji_id'] = icon
        changes = [appearance] if appearance else []
        if hidden is False and row['hidden']:
            changes.append({'hidden': False})
        if closed is not None and closed != row['closed']:
            changes.append({'closed': closed})
        if hidden is True and not row['hidden']:
            changes.append({'hidden': True})
        if not changes:
            return row
        # Telegram requires close/open to be sent separately from edits to title or icon.
        # Invalidate after a partial success too; an explicit retry reads the new state first.
        try:
            for fields in changes:
                await self.client(f.messages.EditForumTopicRequest(entity, topic_id, **fields))
        finally:
            self._forum_changed(utils.get_peer_id(entity), topic_id)
        return await self.forum_topic(utils.get_peer_id(entity), topic_id)

    async def forum_pin(self, peer, topic_id, pinned):
        entity, row = await self._forum_detail(peer, topic_id, fresh=True)
        if not row['can_pin'] or type(pinned) is not bool:
            raise _denied()
        if row['pinned'] == pinned:
            return row
        await self.client(f.messages.UpdatePinnedForumTopicRequest(entity, topic_id, pinned))
        self._forum_changed(utils.get_peer_id(entity), topic_id)
        return await self.forum_topic(utils.get_peer_id(entity), topic_id)

    async def forum_delete(self, peer, topic_id):
        entity, row = await self._forum_detail(peer, topic_id, fresh=True, check_delete=True)
        if not row['can_delete']:
            raise _denied()
        while True:
            result = await self.client(f.messages.DeleteTopicHistoryRequest(entity, topic_id))
            if not result.offset:
                break
        self._forum_changed(utils.get_peer_id(entity), topic_id)
        return True

    async def _forum_destination(self, peer, topic_id, reply_to):
        entity, row = await self._forum_detail(peer, topic_id)
        if not row['can_send']:
            raise _denied()
        if reply_to is not None and _id(reply_to) != topic_id:
            original = await self.client.get_messages(entity, ids=reply_to)
            if (not original or isinstance(original, t.MessageEmpty) or _peer_id(original) != utils.get_peer_id(entity)
                    or message_topic(original, True) != topic_id):
                raise ValueError(tr('This message is no longer available in this chat.'))
            return entity, t.InputReplyToMessage(reply_to, top_msg_id=topic_id if topic_id != GENERAL else None)
        return entity, t.InputReplyToMessage(topic_id) if topic_id != GENERAL else None

    async def forum_reply(self, peer, topic_id, reply_to=None):
        return (await self._forum_destination(peer, topic_id, reply_to))[1]

    async def forum_forward(self, peer, topic_id, source, ids):
        from .secret_chats import is_secret_peer
        if is_secret_peer(source):
            raise ValueError(tr('Los mensajes de chats secretos no se pueden reenviar.'))
        ids = list(dict.fromkeys(_id(x) for x in ids))
        if not 1 <= len(ids) <= 100:
            raise ValueError(tr('Mensaje no válido.'))
        entity, _ = await self._forum_destination(peer, topic_id, None)
        policy = await self.selected_message_policy(source, ids)
        if not policy['forward']:
            raise _denied()
        return await self.client(f.messages.ForwardMessagesRequest(await self.client.get_input_entity(source),
                                 ids, entity, top_msg_id=topic_id if topic_id != GENERAL else None))

    @tracked_transfer
    async def forum_send(self, peer, topic_id, text='', spans=(), emojis=(), *, paths=(), reply_to=None,
                         progress=None, silent=False, schedule=None, as_photo=False, voice=False, duration=0):
        from .backend import attachment_path
        from .emoji_usage import note
        from .message_tools import formatted_entities
        paths = [attachment_path(p) for p in paths]
        if len(paths) > 10 or voice and len(paths) != 1 or not paths and not text:
            raise ValueError(tr('Choose up to 10 files for one album.'))
        entity, reply = await self._forum_destination(peer, topic_id, reply_to)
        entities = formatted_entities(text, spans, emojis)
        note(self, emojis, text)
        opt = dict(reply_to=reply, silent=silent, schedule_date=schedule)
        if not paths:
            if not _allowed(entity, 'send_plain'):
                raise _denied()
            request = f.messages.SendMessageRequest(entity, text, entities=entities, **opt)
            item = await self._structured_sent(request)
            return [item] if item else []
        album = len(paths) > 1
        photos = all(utils.is_image(str(p)) for p in paths) and (album or as_photo)
        for path in paths:
            media_right = ('send_voices' if voice else 'send_photos' if photos else
                           'send_videos' if utils.is_video(str(path)) else
                           'send_audios' if utils.is_audio(str(path)) else 'send_docs')
            if not _allowed(entity, 'send_media', media_right):
                raise _denied()
        with ExitStack() as stack:
            streams = [stack.enter_context(path.open('rb')) for path in paths]
            async with transfer_timeout(progress) as report:
                media = []
                total = sum(p.stat().st_size for p in paths)
                transferred = 0
                for stream, path in zip(streams, paths):
                    async def on_progress(done, size):
                        await report(transferred + done, total)
                    attributes = [t.DocumentAttributeAudio(duration=max(1, round(duration)), voice=True)] if voice else None
                    _, prepared, _ = await self.client._file_to_media(stream, force_document=not photos and not voice,
                        attributes=attributes, mime_type='audio/ogg' if voice else None, voice_note=voice,
                        progress_callback=on_progress, nosound_video=True if album else None)
                    if album:
                        uploaded = await self.client(f.messages.UploadMediaRequest(entity, prepared))
                        prepared = utils.get_input_media(uploaded.photo if isinstance(uploaded, t.MessageMediaPhoto) else uploaded.document)
                    media.append(prepared)
                    transferred += path.stat().st_size
                if not album:
                    request = f.messages.SendMediaRequest(entity, media[0], text, entities=entities, **opt)
                    item = await self._structured_sent(request)
                    return [item] if item else []
                single = [t.InputSingleMedia(m, message=text if i == 0 else '', entities=entities if i == 0 else None)
                          for i, m in enumerate(media)]
                request = f.messages.SendMultiMediaRequest(entity, single, **opt)
                result = await self.client(request)
                input_peer = await self.client.get_input_entity(entity)
                sent = self.client._get_response_message([m.random_id for m in single], result, input_peer)
                return [self.message(m) for m in sent or () if m is not None]
