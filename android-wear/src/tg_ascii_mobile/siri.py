"""Account-scoped Telegram conversations for the in-app SiriKit delegate."""
import asyncio
import json

from tg_ascii.secret_chats import is_secret_peer


def identifier(account, peer, message=None):
    parts = [account, int(peer)]
    if message is not None:
        parts.append(int(message))
    return json.dumps(parts, separators=(',', ':'))


async def perform(core, request):
    """Run on the core loop. Incoming message searches never mark anything read."""
    while core.stage == 'loading' and not core.locked:
        await asyncio.sleep(.1)
    account, backend = core.account, core.backend

    def check():
        if core.locked or core.account != account or core.backend is not backend or core.stage != 'ready':
            raise PermissionError('Open and unlock TeleGraph.')

    check()
    op = request['op']
    peers = {chat.id: chat for chat in core.chats if not is_secret_peer(chat.id)}
    if op == 'resolve':
        name = request.get('name', '').strip().casefold()
        candidates = [{'id': identifier(account, key), 'name': chat.name} for key, chat in peers.items()]
        if request.get('id'):
            return [item for item in candidates if item['id'] == request['id']]
        return [item for item in candidates if name and item['name'].casefold() == name]

    def decode(value, length):
        parts = json.loads(value)
        if (not isinstance(parts, list) or len(parts) != length or parts[0] != account
                or type(parts[1]) is not int or parts[1] not in peers
                or (length == 3 and (type(parts[2]) is not int or parts[2] <= 0))):
            raise ValueError('The conversation is unavailable.')
        return parts

    if backend is None:
        raise ConnectionError('Connect to Telegram.')
    if op == 'send':
        _, peer = decode(request['conversation'], 2)
        content = request['text']
        if not isinstance(content, str) or not content.strip() or len(content) > 4096:
            raise ValueError('Invalid message.')
        # Use the bound client: Siri must report success only after Telegram accepts it.
        await backend.send(peer, content)
        return {}
    if op == 'read':
        maximum = {}
        for token in request['ids']:
            _, peer, msg = decode(token, 3)
            maximum[peer] = max(msg, maximum.get(peer, 0))
        if not maximum:
            raise ValueError('Select a message.')
        for peer, msg in maximum.items():
            check()
            await backend.mark_read(peer, msg)
        return {}
    if op != 'search':
        raise ValueError('Unsupported action.')
    requested = {decode(token, 2)[1] for token in request.get('conversations', [])}
    ids = {tuple(decode(token, 3)[1:]) for token in request.get('ids', [])}
    terms = [term.casefold() for term in request.get('terms', [])]
    records = []
    async for dialog in backend.client.iter_dialogs(limit=100):
        check()
        if dialog.id not in peers or (requested and dialog.id not in requested):
            continue
        if ids and not any(peer == dialog.id for peer, _ in ids):
            continue
        if request.get('unread') and not dialog.unread_count:
            continue
        async for raw in backend.client.iter_messages(dialog.id, limit=20):
            check()
            if request.get('unread') and raw.id <= dialog.dialog.read_inbox_max_id:
                break
            if raw.out or not raw.raw_text or (ids and (dialog.id, raw.id) not in ids):
                continue
            if any(term not in raw.raw_text.casefold() for term in terms):
                continue
            message = backend.message(raw)
            records.append({'id': identifier(account, dialog.id, raw.id), 'chat': identifier(account, dialog.id),
                            'name': message.sender or dialog.name, 'text': raw.raw_text, 'date': raw.date.timestamp(),
                            'sender': identifier(account, raw.sender_id or dialog.id)})
            if len(records) == 20:
                return records
    return records


def install(app):
    from rubicon.objc import Block, ObjCClass, ObjCInstance, objc_id
    from toga_iOS.app import PythonAppDelegate  # register the native class before adding selectors

    def dispatch(pointer):
        native = ObjCInstance(pointer)
        try:
            request = json.loads(str(native.payloadJSON))
            future = asyncio.run_coroutine_threadsafe(
                asyncio.wait_for(perform(app.core, request), timeout=20), app.core.loop)
        except Exception:
            native.finishJSON_(None)
            return

        def completed(future):
            try:
                reply = json.dumps(future.result())
            except Exception:
                reply = None
            app.on_main_thread(lambda: native.finishJSON_(reply))

        future.add_done_callback(completed)

    try:
        handler = ObjCClass('TGVoiceHandler')
    except NameError:
        # A source-only Briefcase update can precede rebuilding the native target.
        print('SiriKit requires rebuilding the iOS project.')
        return
    app._siri_dispatch = Block(dispatch, None, objc_id)
    handler.install_(app._siri_dispatch)
