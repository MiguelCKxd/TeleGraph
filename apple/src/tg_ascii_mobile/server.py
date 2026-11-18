"""Tiny local HTTP server between the WebView and the core.

* Listens on 127.0.0.1 only, on a random port chosen at start-up.
* Every API call, the event stream and media need the per-launch secret
  token (``X-TG-Token`` header or ``t`` query value). Other apps on the
  device can reach a loopback port, but they never see the token.
* The Host header must be the loopback address (blocks DNS rebinding) and
  requests with a foreign Origin are refused.
* Static files are the UI itself (no user data).
"""
import asyncio
import hmac
import json
import mimetypes
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, unquote, urlsplit

WEB = Path(__file__).resolve().parent / 'web'
ASSETS = Path(__file__).resolve().parents[1] / 'tg_ascii' / 'assets'
MAX_BODY = 1024 * 1024
MAX_MEDIA = 80 * 1024 * 1024
MAX_UPLOAD = 1536 * 1024 * 1024
HEARTBEAT = 15
REQUEST_READ_TIMEOUT = 30
UI_CONTENT_POLICY = (
    "Content-Security-Policy: default-src 'none'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "font-src 'self'; media-src 'self' blob:; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
FILE_CONTENT_POLICY = "Content-Security-Policy: sandbox; default-src 'none'; frame-ancestors 'none'"
AUDIO_TYPES = {'.webm': 'video/webm', '.ogg': 'audio/ogg', '.oga': 'audio/ogg', '.opus': 'audio/ogg', '.caf': 'audio/x-caf',
               '.m4a': 'audio/mp4'}


def is_ogg(path):
    if path.suffix:
        return path.suffix.lower() in ('.ogg', '.oga', '.opus')
    # Telegram voice documents can be cached under a bare peer-message ID.
    with path.open('rb') as stream:
        return stream.read(4) == b'OggS'


def playable_caf(path):
    """The CAF twin of an Ogg/Opus file (made once), or the file itself."""
    target = path.with_name(path.name + '-play-v2.caf')
    try:
        if target.is_file():
            cached = target.stat()
            if cached.st_size and cached.st_mtime_ns >= path.stat().st_mtime_ns:
                return target
        from .opus_mux import ogg_to_caf
        with TemporaryDirectory(dir=path.parent) as directory:
            preview = Path(directory) / 'preview.caf'
            ogg_to_caf(path, preview)
            os.chmod(preview, 0o600)
            preview.replace(target)
        return target
    except Exception:
        return path


REASONS = {200: 'OK', 206: 'Partial Content', 416: 'Range Not Satisfiable', 204: 'No Content', 400: 'Bad Request', 403: 'Forbidden', 404: 'Not Found',
           405: 'Method Not Allowed', 413: 'Payload Too Large', 500: 'Internal Server Error'}


class Server:
    def __init__(self, core):
        self.core = core
        self.port = None

    async def start(self, port=0):
        server = await asyncio.start_server(self.handle, '127.0.0.1', port, limit=MAX_BODY + 65536)
        self.server = server
        self.port = server.sockets[0].getsockname()[1]
        return self.port

    async def alive(self):
        """Whether the listening socket still accepts connections."""
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection('127.0.0.1', self.port), 2)
        except (OSError, asyncio.TimeoutError):
            return False
        writer.close()
        return True

    async def ensure(self):
        """iOS reclaims the listening sockets of a suspended app: after a while in
        the background every request of the interface fails. Listen again (same
        port when possible, so the page keeps its address) and return the port."""
        if await self.alive():
            return self.port
        old = self.server
        try:
            old.close()
        except Exception:
            pass
        try:
            return await self.start(self.port)
        except OSError:
            return await self.start(0)

    # -- HTTP ------------------------------------------------------------------
    async def handle(self, reader, writer):
        try:
            head = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), REQUEST_READ_TIMEOUT)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, ConnectionError):
            writer.close()
            return
        try:
            lines = head.decode('latin-1').split('\r\n')
            method, target, _version = lines[0].split(' ', 2)
            headers = {}
            for line in lines[1:]:
                if ':' in line:
                    name, value = line.split(':', 1)
                    headers[name.strip().lower()] = value.strip()
            url = urlsplit(target)
            query = {key: values[0] for key, values in parse_qs(url.query).items()}
            path = unquote(url.path)
            if headers.get('host') not in (f'127.0.0.1:{self.port}', f'localhost:{self.port}'):
                return await self.respond(writer, 403, b'host')
            origin = headers.get('origin')
            if origin and origin not in (f'http://127.0.0.1:{self.port}', f'http://localhost:{self.port}'):
                return await self.respond(writer, 403, b'origin')
            window_account = headers.get('x-tg-window-account', query.get('window_account'))
            if window_account is not None and window_account != self.core.account:
                if path not in ('/events', '/api/state', '/api/strings', '/api/unlock', '/api/unlock_biometric', '/api/app_visible'):
                    return await self.respond(writer, 403, b'account')
            try:
                length = int(headers.get('content-length', '0'))
            except ValueError:
                return await self.respond(writer, 400, b'')
            if length < 0:
                return await self.respond(writer, 400, b'')
            if path == '/upload' and method == 'POST':
                return await self.upload(reader, writer, headers, query, length)
            if length > MAX_BODY:
                return await self.respond(writer, 413, b'')
            body = b''
            if length:
                body = await asyncio.wait_for(reader.readexactly(length), REQUEST_READ_TIMEOUT)
            if path == '/events' and method == 'GET':
                return await self.events(writer, headers, query)
            if path == '/media' and method == 'GET':
                return await self.media(writer, headers, query)
            if path == '/staged' and method == 'GET':
                return await self.staged(writer, headers, query)
            if path == '/sticker' and method == 'GET':
                return await self.sticker(writer, headers, query)
            if path == '/avatar' and method == 'GET':
                return await self.avatar(writer, headers, query)
            if path == '/background' and method == 'GET':
                return await self.background(writer, headers, query)
            if path == '/logo' and method == 'GET':
                content_type = 'image/png'
                if 'photo' in query or 'official' in query:
                    if not self.authorised(headers, query) or self.core.locked:
                        return await self.respond(writer, 403, b'token')
                    if 'photo' in query:
                        logo = self.core.logo_photo_file(query['photo'])
                        content_type = 'image/jpeg'
                    else:
                        logo = self.core.official_logo_file(query['official'])
                else:
                    logo = await self.core.brand_logo_file(query.get('variant'), query.get('theme'), query.get('color'))
                if logo is None:
                    return await self.respond(writer, 404, b'')
                data = await asyncio.to_thread(logo.read_bytes)
                if 'photo' in query and self.core.locked:
                    return await self.respond(writer, 403, b'token')
                return await self.respond(writer, 200, data, content_type,
                                          ('Cache-Control: no-store' if 'photo' in query else
                                           'Cache-Control: private, max-age=86400',))
            if path.startswith('/api/'):
                return await self.api(writer, method, path[5:], headers, query, body)
            if method != 'GET':
                return await self.respond(writer, 405, b'')
            return await self.static(writer, path)
        except (ConnectionError, asyncio.IncompleteReadError, asyncio.TimeoutError):
            pass
        except Exception:
            try:
                await self.respond(writer, 500, b'')
            except Exception:
                pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    def authorised(self, headers, query):
        token = headers.get('x-tg-token') or query.get('t') or ''
        return hmac.compare_digest(token.encode(), self.core.token.encode())

    def response_head(self, status, length, content_type, extra):
        caching = [] if any(item.startswith('Cache-Control') for item in extra) else ['Cache-Control: no-store']
        head = [f'HTTP/1.1 {status} {REASONS.get(status, "OK")}', f'Content-Type: {content_type}',
                f'Content-Length: {length}', 'Connection: close', *caching,
                'X-Content-Type-Options: nosniff', 'Referrer-Policy: no-referrer', *extra]
        return ('\r\n'.join(head) + '\r\n\r\n').encode('latin-1')

    async def respond(self, writer, status, body, content_type='text/plain; charset=utf-8', extra=()):
        writer.write(self.response_head(status, len(body), content_type, extra))
        writer.write(body)
        await writer.drain()

    async def static(self, writer, path):
        if path in ('', '/'):
            path = '/index.html'
        if path.startswith('/assets/'):
            base, name = ASSETS, path[len('/assets/'):]
        else:
            base, name = WEB, path.lstrip('/')
        target = (base / name).resolve()
        if base.resolve() not in target.parents or not target.is_file():
            return await self.respond(writer, 404, b'')
        kind = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        if kind.startswith('text/') or kind in ('application/javascript', 'image/svg+xml'):
            kind += '; charset=utf-8'
        data = await asyncio.to_thread(target.read_bytes)
        return await self.respond(writer, 200, data, kind, (UI_CONTENT_POLICY,))

    async def api(self, writer, method, name, headers, query, body):
        if method != 'POST':
            return await self.respond(writer, 405, b'')
        if not self.authorised(headers, query):
            return await self.respond(writer, 403, b'token')
        try:
            params = json.loads(body.decode('utf-8')) if body else {}
            if not isinstance(params, dict):
                raise ValueError
        except ValueError:
            return await self.respond(writer, 400, b'')
        try:
            window_account = headers.get('x-tg-window-account', query.get('window_account'))
            if name == 'state' and window_account is not None:
                params['window_account'] = window_account
            result = {'ok': True, 'result': await self.core.call(name, params)}
        except LookupError:
            return await self.respond(writer, 404, b'')
        except TypeError as exc:
            result = {'ok': False, 'error': f'bad call: {exc}'}
        except Exception as exc:
            from tg_ascii.auth import error_message
            result = {'ok': False, 'error': error_message(exc)}
        data = json.dumps(result, ensure_ascii=False, default=str).encode('utf-8')
        return await self.respond(writer, 200, data, 'application/json; charset=utf-8')

    async def upload(self, reader, writer, headers, query, length):
        """An attachment chosen in the page, streamed to the staging folder."""
        if not self.authorised(headers, query) or self.core.locked:
            return await self.respond(writer, 403, b'token')
        if length <= 0 or length > MAX_UPLOAD:
            return await self.respond(writer, 413, b'')
        target = self.core.staging_path(query.get('name') or 'file')
        try:
            with target.open('wb') as stream:
                remaining = length
                while remaining:
                    chunk = await asyncio.wait_for(reader.read(min(remaining, 1 << 20)), REQUEST_READ_TIMEOUT)
                    if not chunk:
                        raise ConnectionError('upload interrupted')
                    stream.write(chunk)
                    remaining -= len(chunk)
            os.chmod(target, 0o600)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        data = json.dumps({'ok': True, 'result': {'key': target.name, 'name': query.get('name') or target.name,
                                                  'size': length}}).encode('utf-8')
        return await self.respond(writer, 200, data, 'application/json; charset=utf-8')

    async def media(self, writer, headers, query):
        """A message's photo/sticker/video preview (thumb=1) or full file."""
        from tg_ascii.secret_chats import is_secret_peer

        if not self.authorised(headers, query) or self.core.locked:
            return await self.respond(writer, 403, b'token')
        try:
            peer, ident = int(query['peer']), int(query['id'])
            thumbnail = query.get('thumb', '1') != '0'
            if is_secret_peer(peer):
                return await self.secret_media(writer, headers, query, peer, ident, thumbnail)
            account = self.core.account
            if 'poll' in query:
                path = await asyncio.wait_for(self.core.poll_attachment(peer, ident, query['poll'], thumbnail), 120)
            elif 'photo' in query:  # a photo of an article (carousel)
                path = await asyncio.wait_for(self.core.article_photo(peer, ident, int(query['photo'])), 120)
            else:
                path = await asyncio.wait_for(self.core.media_file(peer, ident, thumbnail), 120)
        except (KeyError, ValueError):
            return await self.respond(writer, 400, b'')
        except Exception:
            return await self.respond(writer, 404, b'')
        if path is None or not path.is_file() or path.stat().st_size > MAX_MEDIA:
            return await self.respond(writer, 404, b'')
        if query.get('play') == 'caf' and is_ogg(path):
            # iOS: Safari plays Opus from CAF, not always from Ogg (same audio, other box).
            path = await asyncio.to_thread(playable_caf, path)
        if self.core.locked or self.core.account != account:
            return await self.respond(writer, 403, b'token')
        return await self.send_file(writer, headers, path, 'Cache-Control: no-store')

    async def secret_media(self, writer, headers, query, peer, ident, thumbnail):
        account = self.core.account
        folder = self.core.root / 'secret-previews'
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        with TemporaryDirectory(dir=folder) as directory:
            path = await asyncio.wait_for(self.core.secret_preview_file(peer, ident, thumbnail, Path(directory)), 120)
            if path is None or not path.is_file() or path.stat().st_size > MAX_MEDIA:
                return await self.respond(writer, 404, b'')
            if query.get('play') == 'caf' and is_ogg(path):
                path = await asyncio.to_thread(playable_caf, path)
            if self.core.locked or self.core.account != account:
                return await self.respond(writer, 403, b'token')
            return await self.send_file(writer, headers, path, 'Cache-Control: no-store')

    async def staged(self, writer, headers, query):
        """A file waiting to be sent (the voice message just recorded, to listen to it)."""
        if not self.authorised(headers, query) or self.core.locked:
            return await self.respond(writer, 403, b'token')
        try:
            path = self.core.staged(query.get('key', ''))
        except ValueError:
            return await self.respond(writer, 404, b'')
        return await self.send_file(writer, headers, path, 'Cache-Control: no-store')

    async def send_file(self, writer, headers, path, cache):
        kind = AUDIO_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0]
        if not kind:
            kind = 'audio/ogg' if is_ogg(path) else 'application/octet-stream'
        extra = (cache, 'Accept-Ranges: bytes', FILE_CONTENT_POLICY)
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', headers.get('range', '').strip())
        with path.open('rb') as stream:
            size = os.fstat(stream.fileno()).st_size
            status, start, end = 200, 0, size - 1
            if match and (match.group(1) or match.group(2)):
                # Video players (WebKit's above all) read in byte ranges.
                if match.group(1):
                    start = int(match.group(1))
                    if match.group(2):
                        end = min(int(match.group(2)), end)
                else:
                    start = max(0, size - int(match.group(2)))
                if start > end:
                    return await self.respond(writer, 416, b'', extra=(f'Content-Range: bytes */{size}',))
                status = 206
                extra += (f'Content-Range: bytes {start}-{end}/{size}',)
            length = end - start + 1
            writer.write(self.response_head(status, length, kind, extra))
            await writer.drain()
            # iOS terminates the process if it calls sendfile(2), even on loopback.
            stream.seek(start)
            remaining = length
            while remaining:
                chunk = stream.read(min(remaining, 64 * 1024))
                if not chunk:
                    raise ConnectionError('media file truncated during playback')
                writer.write(chunk)
                await writer.drain()
                remaining -= len(chunk)

    async def sticker(self, writer, headers, query):
        """A sticker or custom emoji image (picker cells, custom emoji in messages)."""
        if not self.authorised(headers, query) or self.core.locked:
            return await self.respond(writer, 403, b'token')
        if query.get('anim') == '1':  # the moving version (Lottie JSON / WebM), 204 if it is still
            try:
                path = await asyncio.wait_for(self.core.sticker_animation(int(query['id'])), 180)
            except (KeyError, ValueError):
                return await self.respond(writer, 400, b'')
            except Exception:
                return await self.respond(writer, 404, b'')
            if path is None:
                return await self.respond(writer, 204, b'', extra=('Cache-Control: private, max-age=604800',))
            if path.suffix == '.json':
                data = await asyncio.to_thread(path.read_bytes)
                return await self.respond(writer, 200, data, 'application/json', ('Cache-Control: private, max-age=604800',))
            return await self.send_file(writer, headers, path, 'Cache-Control: private, max-age=604800')
        try:
            path = await asyncio.wait_for(self.core.sticker_file(int(query['id'])), 180)
        except (KeyError, ValueError):
            return await self.respond(writer, 400, b'')
        except Exception:
            return await self.respond(writer, 404, b'')
        if path is None or not path.is_file() or path.stat().st_size > MAX_MEDIA:
            return await self.respond(writer, 404, b'')
        data = await asyncio.to_thread(path.read_bytes)
        kind = 'image/webp' if data[:4] == b'RIFF' and data[8:12] == b'WEBP' else 'image/jpeg' if data[:2] == b'\xff\xd8' else 'image/png'
        return await self.respond(writer, 200, data, kind, ('Cache-Control: private, max-age=604800',))

    async def avatar(self, writer, headers, query):
        """Small profile photo of a chat or person (404 when it has none)."""
        if not self.authorised(headers, query) or self.core.locked:
            return await self.respond(writer, 403, b'token')
        account = self.core.account
        try:
            path = await asyncio.wait_for(self.core.avatar_file(int(query['peer']), query.get('big') == '1'), 90)
        except (KeyError, ValueError):
            return await self.respond(writer, 400, b'')
        except Exception:
            path = None
        if path is None or not path.is_file() or path.stat().st_size > MAX_MEDIA:
            return await self.respond(writer, 404, b'')
        data = await asyncio.to_thread(path.read_bytes)
        if self.core.locked or self.core.account != account:
            return await self.respond(writer, 403, b'token')
        return await self.respond(writer, 200, data, 'image/jpeg')

    async def background(self, writer, headers, query):
        """A background picture chosen on this device."""
        if not self.authorised(headers, query) or self.core.locked:
            return await self.respond(writer, 403, b'token')
        path = self.core.background_file(query.get('name', ''))
        if path is None:
            return await self.respond(writer, 404, b'')
        data = await asyncio.to_thread(path.read_bytes)
        if self.core.locked:
            return await self.respond(writer, 403, b'token')
        return await self.respond(writer, 200, data, 'image/jpeg')

    async def events(self, writer, headers, query):
        if not self.authorised(headers, query):
            return await self.respond(writer, 403, b'token')
        writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-store\r\n'
                     b'Connection: keep-alive\r\nX-Accel-Buffering: no\r\n\r\n: hello\n\n')
        await writer.drain()
        queue = asyncio.Queue()
        queue.window_account = headers.get('x-tg-window-account', query.get('window_account'))
        self.core.subscribers.add(queue)
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), HEARTBEAT)
                    if data is None:
                        return  # Overflow. The page resynchronizes on reconnect.
                    writer.write(b'data: ' + data.encode('utf-8') + b'\n\n')
                except asyncio.TimeoutError:
                    writer.write(b': ping\n\n')
                await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            self.core.subscribers.discard(queue)
