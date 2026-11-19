"""TG-ASCII on Apple Watch with its own Telegram connection (complex feature).

The watch runs Telethon itself, so it keeps working with the iPhone off. Its
session is its own. The login token can be approved by the companion app or
scanned from the watch in another signed-in Telegram app.

watchOS only allows URLSession networking, so MTProto goes over Telegram's
HTTP transport (POST http://<dc>:80/api) through URLSession (rubicon).

Swift calls start(folder) once and request(json) -> json from a background
queue (PythonBridge.c).
"""
import asyncio
import json
import os
import re
import threading
import time

_loop = _client = _qr = _secret_mgr = None
_root = ''
_personal_credentials = None


def _bundled_credentials():
    try:
        import _app_credentials as app
    except ModuleNotFoundError as exc:
        if exc.name != '_app_credentials':
            raise
        return None
    keys = getattr(app, 'API_ID', None), getattr(app, 'API_HASH', None)
    return keys if any(keys) else None


def start(root):
    global _loop, _root
    if _loop is None:
        _root = root
        os.makedirs(root, exist_ok=True)
        loop = asyncio.new_event_loop()
        try:
            threading.Thread(target=loop.run_forever, name='tgwatch', daemon=True).start()
        except RuntimeError:
            loop.close()
            raise
        _loop = loop
    return 'ok'


def request(text):
    future = None
    try:
        body = json.loads(text)
        timeout = float(body.get('timeout', 60))
        if body.get('op') == 'login_wait':
            timeout += 15  # Allow the last Telegram request to complete.
        future = asyncio.run_coroutine_threadsafe(_handle(body), _loop)
        result = future.result(timeout=timeout)
    except Exception as exc:  # The watch shows the message.
        if future is not None and not future.done():
            future.cancel()
        result = {'error': _describe(exc)}
    return json.dumps(result, ensure_ascii=False, default=str)


def _describe(exc):
    text = str(exc) or type(exc).__name__
    return text if len(text) < 200 else text[:200]


# -- MTProto over URLSession -----------------------------------------------------------
PATH = os.environ.get('TGW_HTTP_PATH', 'apiw1')


def _url_session_connection():
    from telethon.network.connection.connection import Connection

    class ConnectionURLSession(Connection):
        """Telegram's HTTP transport, one POST per packet, sent with URLSession."""
        packet_codec = None

        def __init__(self, ip, port, dc_id, **kwargs):
            super().__init__(ip, 80, dc_id, **kwargs)  # HTTP transport: port 80
            self._pending = set()

        async def _connect(self, timeout=None, ssl=None):
            self._answers = asyncio.Queue()
            self._loop_ref = asyncio.get_running_loop()

            class Writer:
                def write(self, data): pass
                async def drain(self): pass
                def close(self): pass
                async def wait_closed(self): pass
            self._writer = Writer()

        def _send(self, data):
            from rubicon.objc import Block, ObjCClass, ObjCInstance, objc_id
            import ctypes
            # HTTPS to Telegram Web's HTTP endpoint (watchOS allows only URLSession,
            # and App Transport Security only TLS).
            name = {1: 'pluto', 2: 'venus', 3: 'aurora', 4: 'vesta', 5: 'flora'}.get(self._dc_id, 'venus')
            request = ObjCClass('NSMutableURLRequest').requestWithURL_(
                ObjCClass('NSURL').URLWithString_(f'https://{name}.web.telegram.org/{PATH}'))
            request.HTTPMethod = 'POST'
            request.HTTPBody = ObjCClass('NSData').dataWithBytes_length_(data, len(data))
            request.setValue_forHTTPHeaderField_('application/x-www-form-urlencoded', 'Content-Type')
            request.timeoutInterval = 30.0
            loop, answers = self._loop_ref, self._answers

            def done(body, response, error):
                if error:
                    result = ConnectionError(str(ObjCInstance(error).localizedDescription))
                elif body:
                    payload = ObjCInstance(body)
                    result = ctypes.string_at(payload.bytes, payload.length) if payload.length else b''
                else:
                    result = b''
                loop.call_soon_threadsafe(answers.put_nowait, result)
                self._pending.discard(block)
            block = Block(done, None, objc_id, objc_id, objc_id)
            self._pending.add(block)
            ObjCClass('NSURLSession').sharedSession.dataTaskWithRequest_completionHandler_(request, block).resume()

        async def _recv(self):
            while True:
                answer = await self._answers.get()
                if isinstance(answer, Exception):
                    raise IOError(str(answer))
                if answer:  # An empty body carries nothing.
                    return answer

    return ConnectionURLSession


def _websocket_connection():
    """Telegram Web's transport: obfuscated MTProto over wss://<dc>.web.telegram.org/apiws,
    with URLSessionWebSocketTask (allowed on watchOS, full duplex like TCP)."""
    import ctypes
    from rubicon.objc import Block, ObjCClass, ObjCInstance, objc_id
    from telethon.network.connection.tcpobfuscated import ConnectionTcpObfuscated
    NAMES = {1: 'pluto', 2: 'venus', 3: 'aurora', 4: 'vesta', 5: 'flora'}

    def nsdata(data):
        return ObjCClass('NSData').dataWithBytes_length_(bytes(data), len(data))

    def pybytes(data):
        return ctypes.string_at(data.bytes, data.length) if data is not None and data.length else b''

    class Writer:
        def __init__(self, task, loop):
            self.task, self.loop, self.buffer, self.blocks = task, loop, bytearray(), set()

        def write(self, data):
            self.buffer += data

        async def drain(self):
            if not self.buffer:
                return
            data, self.buffer = bytes(self.buffer), bytearray()
            future = self.loop.create_future()

            def sent(error):
                result = None if not error else ConnectionError(str(ObjCInstance(error).localizedDescription))
                self.loop.call_soon_threadsafe(lambda: future.done() or (future.set_exception(result) if result else future.set_result(True)))
                self.blocks.discard(block)
            block = Block(sent, None, objc_id)
            self.blocks.add(block)
            message = ObjCClass('NSURLSessionWebSocketMessage').alloc().initWithData_(nsdata(data))
            self.task.sendMessage_completionHandler_(message, block)
            await asyncio.wait_for(future, 30)

        def close(self):
            try:
                self.task.cancelWithCloseCode_reason_(1000, None)
            except Exception:
                pass

        async def wait_closed(self):
            pass

    class ConnectionWebSocket(ConnectionTcpObfuscated):
        async def _connect(self, timeout=None, ssl=None):
            loop = asyncio.get_running_loop()
            self._reader = asyncio.StreamReader()
            reader = self._reader
            url = ObjCClass('NSURL').URLWithString_(f'wss://{NAMES.get(self._dc_id, "venus")}.web.telegram.org/apiws')
            task = ObjCClass('NSURLSession').sharedSession.webSocketTaskWithURL_protocols_(
                url, ObjCClass('NSArray').arrayWithObject_('binary'))
            self._writer = Writer(task, loop)
            holder = {}

            def received(message, error):
                if error or not message:
                    loop.call_soon_threadsafe(reader.feed_eof)
                    return
                data = pybytes(ObjCInstance(message).data)
                if data:
                    loop.call_soon_threadsafe(reader.feed_data, data)
                task.receiveMessageWithCompletionHandler_(holder['block'])
            holder['block'] = Block(received, None, objc_id, objc_id)
            self._receive_block = holder['block']
            task.resume()
            task.receiveMessageWithCompletionHandler_(holder['block'])
            self._codec = self.packet_codec(self)
            self._init_conn()
            await self._writer.drain()

    return ConnectionWebSocket


_link_lock = None


async def _login_wait(client, timeout):
    global _link_lock
    if _link_lock is None:
        _link_lock = asyncio.Lock()
    async with _link_lock:
        if await client.is_user_authorized():
            return {'state': 'ready'}
        return await _login_wait_locked(client, timeout)


async def _login_wait_locked(client, timeout):
    """Wait until the phone accepts the login token. Over the HTTP transport the
    'token accepted' update can arrive late or never, so also ask Telegram
    every few seconds (exporting the token again returns success once accepted)."""
    from telethon import errors, functions, types
    deadline = time.monotonic() + timeout
    while True:
        try:
            await _qr.wait(timeout=3)
            return {'state': 'ready'}
        except errors.SessionPasswordNeededError:
            return {'state': 'password'}
        except asyncio.TimeoutError:
            pass
        try:
            result = await client(functions.auth.ExportLoginTokenRequest(client.api_id, client.api_hash, except_ids=[]))
            if isinstance(result, types.auth.LoginTokenMigrateTo):
                await client._switch_dc(result.dc_id)
                result = await client(functions.auth.ImportLoginTokenRequest(result.token))
            if isinstance(result, types.auth.LoginTokenSuccess):
                await client._on_login(result.authorization.user)
                return {'state': 'ready'}
        except errors.SessionPasswordNeededError:
            return {'state': 'password'}
        if time.monotonic() > deadline:
            return {'state': 'expired'}


async def _ensure_client():
    global _client, _secret_mgr
    if _client is None:
        from telethon import TelegramClient
        credentials = _bundled_credentials() or _personal_credentials
        if credentials is None:
            raise ValueError('API credentials required')
        options = {}
        transport = os.environ.get('TGW_TRANSPORT', '')
        if transport == 'websocket':
            options['connection'] = _websocket_connection()
        elif transport == 'http':
            options['connection'] = _url_session_connection()
        _client = TelegramClient(os.path.join(_root, 'watch'), *credentials, device_model='TG-ASCII Apple Watch',
                                 system_version='watchOS', app_version='3.0.0', **options)
    if not _client.is_connected():
        await asyncio.wait_for(_client.connect(), 40)
    if _secret_mgr is None:
        try:
            from tg_ascii.secret_chats import SecretChatManager
            _secret_mgr = SecretChatManager(_client, account='watch', root=_root)
        except Exception:
            _secret_mgr = False
    return _client


def _clock(date):
    if date is None:
        return ''
    return time.strftime('%H:%M', time.localtime(date.timestamp()))


def _text(message):
    text = message.message or ''
    if message.media is not None:
        kind = type(message.media).__name__.replace('MessageMedia', '')
        text = f'[{kind}] {text}'.strip()
    return text


async def _handle(body):
    global _client, _qr, _secret_mgr, _personal_credentials
    op = body.get('op')
    if op == 'uses_personal_api':
        return _bundled_credentials() is None
    if op == 'configure_api':
        if _bundled_credentials() is not None:
            return False
        number, secret = body.get('api_id'), body.get('api_hash')
        if (type(number) is not int or not 0 < number < 2**31 or not isinstance(secret, str)
                or not re.fullmatch(r'[0-9a-fA-F]{32}', secret)):
            raise ValueError('Invalid API credentials')
        if _personal_credentials != (number, secret):
            if _client is not None:
                await _client.disconnect()
                _client = _qr = _secret_mgr = None
            _personal_credentials = number, secret
        return True
    from telethon import errors
    client = await _ensure_client()
    if op == 'status':
        authorized = await client.is_user_authorized()
        name = ''
        if authorized:
            me = await client.get_me()
            name = ' '.join(part for part in (me.first_name, me.last_name) if part)
        return {'authorized': authorized, 'name': name}
    if op == 'login_start':
        if await client.is_user_authorized():
            return {'url': '', 'authorized': True}
        _qr = await client.qr_login()
        result = {'url': _qr.url}
        if body.get('matrix'):
            from qrcode import QRCode

            code = QRCode(border=4)
            code.add_data(_qr.url)
            result['matrix'] = code.get_matrix()
        return result
    if op == 'login_wait':
        return await _login_wait(client, float(body.get('timeout', body.get('wait', 60))))
    if op == 'password':
        await client.sign_in(password=str(body.get('password', '')))
        return {'state': 'ready'}
    if op == 'logout':
        if not await client.log_out():
            return {'ok': False}
        if _secret_mgr:
            _secret_mgr.purge_all()
        _client = _qr = _secret_mgr = None
        return {'ok': True}
    if op == 'move_pin':
        from .pin_order import move_pinned
        await move_pinned(client, int(body['peer']), int(body['direction']))
        return {'ok': True}
    if op == 'chats':
        dialogs = await client.get_dialogs(limit=40, folder=0)
        items = []
        if _secret_mgr:
            for sc in _secret_mgr.list_chats():
                hist = _secret_mgr.history(sc.id)
                items.append({'id': sc.id, 'name': sc.name, 'unread': sc.unread,
                              'preview': hist[-1].text if hist else '', 'kind': 'secret'})
        for dialog in dialogs:
            kind = 'channel' if dialog.is_channel and not dialog.is_group else ('group' if dialog.is_group else 'user')
            items.append({'pinned': bool(dialog.pinned), 'id': dialog.id, 'name': dialog.name or '', 'unread': dialog.unread_count or 0,
                          'preview': _text(dialog.message) if dialog.message else '', 'kind': kind})
        return sorted(items, key=lambda chat: not chat.get('pinned', False))
    if op == 'messages':
        peer = int(body['peer'])
        if _secret_mgr and peer < -2_000_000_000_000:
            await _secret_mgr.mark_read(peer)
            return [{'id': m.id, 'sender': m.sender, 'text': m.text, 'time': m.time,
                     'out': bool(m.outgoing), 'translatable': False} for m in _secret_mgr.history(peer)[-25:]]
        messages = await client.get_messages(peer, limit=25)
        try:
            await client.send_read_acknowledge(peer)
        except Exception:
            pass
        result = []
        for message in reversed(messages):
            if message.action is not None:
                continue
            sender = ''
            if not message.out:
                who = await message.get_sender()
                sender = getattr(who, 'first_name', None) or getattr(who, 'title', None) or ''
            result.append({'id': message.id, 'sender': sender or ('Tú' if message.out else ''), 'text': _text(message),
                           'time': _clock(message.date), 'out': bool(message.out),
                           'translatable': bool((message.message or '').strip())})
        return result
    if op == 'translate':
        from .message_translation import translate_rows, watch_language
        language = watch_language(body.get('language') or 'en')
        peer_id = int(body['peer'])
        ids = body.get('ids')
        if (peer_id < -2_000_000_000_000 or not isinstance(ids, list)
                or not 1 <= len(ids) <= 25 or any(type(ident) is not int or ident <= 0 for ident in ids)):
            raise ValueError('Invalid translation request.')
        if body.get('chat') is True and not getattr(await client.get_me(), 'premium', False):
            raise ValueError('Automatic chat translation requires Telegram Premium.')
        peer = await client.get_input_entity(peer_id)
        result = await asyncio.wait_for(translate_rows(client, peer, ids, language), 40)
        return {str(ident): row.text for ident, row in result.items() if row.text}
    if op == 'send':
        peer = int(body['peer'])
        text = str(body.get('text', ''))[:4096]
        if _secret_mgr and peer < -2_000_000_000_000:
            await _secret_mgr.send_text(peer, text)
            return {'ok': True}
        await client.send_message(peer, text)
        return {'ok': True}
    if op == 'secret_info' and _secret_mgr:
        return _secret_mgr.session_info(int(body['peer'])) or {'error': 'not_found'}
    if op == 'secret_ttl' and _secret_mgr:
        await _secret_mgr.set_ttl(int(body['peer']), int(body.get('seconds', 0)))
        return _secret_mgr.session_info(int(body['peer'])) or {'error': 'not_found'}
    if op == 'secret_start' and _secret_mgr:
        sc = await _secret_mgr.start_secret_chat(int(body['peer']))
        return {'id': sc.id, 'name': sc.name, 'unread': 0, 'preview': '', 'kind': 'secret'}
    return {'error': 'op'}
