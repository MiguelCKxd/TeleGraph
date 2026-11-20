"""Share only the text of a conversation explicitly selected on the unlocked phone."""
import json


async def share_chat(core, peer, account):
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
    messages = []
    async for message in backend.client.iter_messages(entity, limit=50):
        if (message.raw_text and not getattr(message, 'action', None) and not getattr(message, 'noforwards', False)
                and not message.ttl_period and not getattr(message.media, 'ttl_seconds', None)):
            messages.append(message.raw_text[:1000])
    if not available():
        raise ValueError('La cuenta o el bloqueo ha cambiado.')
    payload = json.dumps({'id': peer, 'title': core.text(chat.name), 'messages': messages[::-1]}, ensure_ascii=False)
    if not link.share_connection_(payload, str(connection)):
        raise ValueError('El Apple TV se ha desconectado.')
    return True
