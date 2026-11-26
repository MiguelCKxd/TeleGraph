"""Share only the text of a conversation explicitly selected on the unlocked phone."""
import base64
import json


async def share_chat(core, peer, account, topic_id=None):
    from tg_ascii.secret_chats import is_secret_peer
    peer = int(peer)
    link = getattr(core, 'tv_link', None)
    connection = link.connectionID() if link is not None else None
    if connection is None:
        raise ValueError('Conecta primero este teléfono desde TeleGraph en el Apple TV.')
    backend = core.backend
    def available():
        return (core.stage == 'ready' and core.account == account and core.backend is backend
                and backend is not None and not core.locked and not core.in_background)
    if not available() or is_secret_peer(peer):
        raise ValueError('Este chat no está disponible para compartir.')
    chat = next((item for item in core.chats if item.id == peer), None)
    if chat is None:
        raise ValueError('El chat ya no está disponible.')
    entity = await backend.client.get_entity(peer)
    if getattr(entity, 'noforwards', False):
        raise ValueError('Este chat protege su contenido.')
    is_forum = bool(getattr(entity, 'forum', False))
    title = core.text(chat.name)
    stream = {'limit': 50}
    if topic_id is not None:
        if not is_forum or type(topic_id) is not int or not 0 < topic_id <= 0x7fffffff:
            raise ValueError('Selecciona un tema del foro.')
        selected = await backend.forum_topic(peer, topic_id)
        title += ' · ' + core.text(selected['title'])
        # Resolve General and named topics through the same validated history as
        # the chat. Fetch the raw rows by those IDs to inspect Telegram's TTL and
        # content-protection flags, including deletions since the history load.
        history = await backend.forum_history(peer, topic_id, limit=50)
        stream = {'ids': [row.id for row in reversed(history)]}
    messages = []
    labels = {}
    if is_forum:
        from tg_ascii.forum_topics import message_topic
    async for message in backend.client.iter_messages(entity, **stream):
        if (message is not None and message.raw_text and not getattr(message, 'action', None) and not getattr(message, 'noforwards', False)
                and not message.ttl_period and not getattr(message.media, 'ttl_seconds', None)):
            topic = message_topic(message, True) if is_forum else None
            if topic_id is None or topic == topic_id:
                messages.append((topic, message.raw_text[:1000]))
    if is_forum and topic_id is None and messages:
        from telethon import functions, types, utils
        roots = sorted({topic for topic, _ in messages})
        result = await backend.client(functions.messages.GetForumTopicsByIDRequest(entity, roots))
        labels = {row.id: core.text(row.title) for row in result.topics if isinstance(row, types.ForumTopic)
                  and utils.get_peer_id(row.peer) == peer}
    lines = [text if topic is None or topic_id is not None else f"{labels.get(topic) or '#' + str(topic)} · {text}"
             for topic, text in reversed(messages)]
    if not available():
        raise ValueError('La cuenta o el bloqueo ha cambiado.')
    look = core.watch_appearance()
    from tg_ascii.logos import png_bytes
    mark = look['brand_logo']
    image = png_bytes(mark['variant'], mark['theme'], 128, color=mark['color'])
    appearance = {key: look[key] for key in ('name', 'bg', 'text', 'strong', 'font', 'scale')}
    appearance['logo'] = base64.b64encode(image).decode('ascii')
    packet = {'id': peer, 'title': title, 'messages': lines, 'appearance': appearance}
    if topic_id is not None:
        packet['topic_id'] = topic_id
    payload = json.dumps(packet, ensure_ascii=False)
    if not link.share_connection_(payload, str(connection)):
        raise ValueError('El Apple TV se ha desconectado.')
    return True
