import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from tg_ascii_mobile.core import Core
from tg_ascii_mobile.server import Server


class ServerSecurityTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.files = TemporaryDirectory()
        self.addCleanup(self.files.cleanup)
        file = Path(self.files.name) / 'attachment.html'
        file.write_text('<script>throw new Error("attachment script")</script>')
        self.core = SimpleNamespace(token='test-token', locked=False, account='first', call=AsyncMock(return_value=True),
                                    staged=lambda key: file)
        self.bridge = Server(self.core)
        self.port = await self.bridge.start()
        self.addAsyncCleanup(self.close_server)

    async def close_server(self):
        self.bridge.server.close()
        await self.bridge.server.wait_closed()

    async def request(self, request):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.port)
        try:
            # This client reads until the end: it asks the server to close.
            line, rest = request.split('\r\n', 1)
            request = line + '\r\nConnection: close\r\n' + rest
            writer.write(request.replace('{port}', str(self.port)).encode())
            await writer.drain()
            return (await reader.read()).decode()
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_ui_and_uploaded_document_have_different_content_policies(self):
        ui = await self.request('GET / HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n')
        self.assertIn("Content-Security-Policy: default-src 'none'; script-src 'self'", ui)
        self.assertIn("connect-src 'self'", ui)
        valid = 'Host: 127.0.0.1:{port}\r\nX-TG-Token: test-token\r\n'
        for byte_range, status in (('', '200'), ('Range: bytes=0-8\r\n', '206')):
            with self.subTest(status=status):
                media = await self.request(f'GET /staged HTTP/1.1\r\n{valid}{byte_range}\r\n')
                self.assertTrue(media.startswith(f'HTTP/1.1 {status} '))
                self.assertIn("Content-Security-Policy: sandbox; default-src 'none'", media)

    async def test_connection_carries_several_requests(self):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.port)
        try:
            request = (f'POST /api/state HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nX-TG-Token: test-token\r\n'
                       'Content-Length: 2\r\n\r\n{}').encode()
            for _ in range(2):
                writer.write(request)
                await writer.drain()
                head = (await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 5)).decode()
                self.assertTrue(head.startswith('HTTP/1.1 200 '))
                self.assertIn('Connection: keep-alive', head)
                length = int(head.split('Content-Length: ')[1].split('\r\n')[0])
                self.assertEqual(json.loads(await reader.readexactly(length)), {'ok': True, 'result': True})
            # A request refused before its body is read is answered and the connection closes.
            writer.write(f'POST /api/state HTTP/1.1\r\nHost: attacker.invalid:{self.port}\r\nContent-Length: 2\r\n\r\n{{}}'.encode())
            await writer.drain()
            rejected = (await asyncio.wait_for(reader.read(), 5)).decode()
            self.assertTrue(rejected.startswith('HTTP/1.1 403 '))
            self.assertIn('Connection: close', rejected)
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_api_rejects_rebinding_foreign_origin_and_missing_token(self):
        cases = (
            ('Host: attacker.invalid:{port}\r\nX-TG-Token: test-token', 'host'),
            ('Host: 127.0.0.1:{port}\r\nOrigin: https://attacker.invalid\r\nX-TG-Token: test-token', 'origin'),
            ('Host: 127.0.0.1:{port}', 'token'),
        )
        for headers, reason in cases:
            with self.subTest(reason=reason):
                response = await self.request(f'POST /api/state HTTP/1.1\r\n{headers}\r\n\r\n')
                self.assertTrue(response.startswith('HTTP/1.1 403 '))
                self.assertTrue(response.endswith('\r\n\r\n' + reason))
        self.core.call.assert_not_awaited()

    async def test_inactive_account_window_cannot_read_media_or_send_requests(self):
        self.core.account = 'active'
        host = 'Host: 127.0.0.1:{port}\r\nX-TG-Token: test-token\r\n'
        response = await self.request(f'POST /api/send HTTP/1.1\r\n{host}X-TG-Window-Account: other\r\n\r\n')
        self.assertTrue(response.startswith('HTTP/1.1 403 '))
        response = await self.request(f'GET /staged?window_account=other HTTP/1.1\r\n{host}\r\n')
        self.assertTrue(response.startswith('HTTP/1.1 403 '))
        self.core.call.assert_not_awaited()
        response = await self.request(f'POST /api/state HTTP/1.1\r\n{host}X-TG-Window-Account: other\r\n\r\n')
        self.assertTrue(response.startswith('HTTP/1.1 200 '))
        self.core.call.assert_awaited_once_with('state', {'window_account': 'other'})

    async def test_inactive_window_receives_only_account_neutral_stage_and_lock_events(self):
        core = Core(Path(self.files.name), 'iOS')
        self.addCleanup(core.loop.close)
        queue = asyncio.Queue()
        queue.window_account = 'inactive'
        core.subscribers.add(queue)
        queue.put_nowait('old event')
        core.emit('message', {'text': 'another account'})
        core.emit('stage', {'accounts': [{'label': 'another account'}]})
        core.emit('lock', False)
        self.assertEqual(queue.qsize(), 2)
        stage = json.loads(queue.get_nowait())
        self.assertEqual(stage['data'], await core.api_state(window_account='inactive'))
        self.assertIsNone(stage['data']['account'])
        self.assertEqual(stage['data']['accounts'], [])
        self.assertEqual(stage['data']['appearance'], {})
        self.assertEqual(json.loads(queue.get_nowait()), {'type': 'lock', 'data': False, 'account': None})
        queue.window_account = core.account
        core.emit('message', {'text': 'own account'})
        self.assertEqual(json.loads(queue.get_nowait())['data'], {'text': 'own account'})

    async def test_private_media_is_not_cached_or_served_after_account_switch(self):
        self.core.account = 'first'
        attachment = self.core.staged('')
        attachment.write_bytes(b'private-data')
        self.core.media_file = AsyncMock(return_value=attachment)
        request = ('GET /media?peer=10&id=20 HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n'
                   'X-TG-Token: test-token\r\n\r\n')
        response = await self.request(request)
        self.assertTrue(response.startswith('HTTP/1.1 200 '))
        self.assertIn('Cache-Control: no-store', response)
        self.assertTrue(response.endswith('private-data'))

        async def switch_account(*_):
            self.core.account = 'second'
            return attachment

        self.core.media_file.side_effect = switch_account
        response = await self.request(request)
        self.assertTrue(response.startswith('HTTP/1.1 403 '))
        self.assertNotIn('private-data', response)

    async def test_foreign_origin_cannot_open_media_or_event_stream(self):
        for path in ('/events', '/media?peer=10&id=20'):
            response = await self.request(
                f'GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{{port}}\r\n'
                'Origin: https://attacker.invalid\r\nX-TG-Token: test-token\r\n\r\n')
            self.assertTrue(response.startswith('HTTP/1.1 403 '))
            self.assertTrue(response.endswith('origin'))

    async def test_overflow_reconnects_and_lock_drops_queued_chat_events(self):
        core = Core(Path(self.files.name), 'Android')
        self.addCleanup(core.loop.close)
        slow, current = asyncio.Queue(), asyncio.Queue()
        core.subscribers.update((slow, current))
        for _ in range(500):
            slow.put_nowait('backlog')
        core.emit('message', {'text': 'private-data'})
        self.assertIsNone(slow.get_nowait())
        self.assertTrue(slow.empty())
        self.assertNotIn(slow, core.subscribers)
        core.locked = True
        core.emit('lock', True)
        self.assertEqual(current.qsize(), 1)
        self.assertIn('"type": "lock"', current.get_nowait())

    async def test_locked_snapshot_omits_account_identity_and_profile_metadata(self):
        core = Core(Path(self.files.name), 'Android')
        self.addCleanup(core.loop.close)
        core.account_list = Mock(return_value=[{'key': 'fixture', 'label': 'Private account'}])
        core.appearance = Mock(return_value={'brand_photo': 'private.jpg'})
        core.error = 'private error'
        core.locked = True
        snapshot = await core.call('state', {})
        self.assertIsNone(snapshot['account'])
        self.assertEqual(snapshot['accounts'], [])
        self.assertEqual(snapshot['appearance'], {})
        self.assertEqual(snapshot['error'], '')
        core.account_list.assert_not_called()
        core.appearance.assert_not_called()

    async def test_parallel_pin_attempts_cannot_bypass_delay(self):
        core = Core(Path(self.files.name), 'Android')
        self.addCleanup(core.loop.close)
        core.locked = True
        core.pin_ok = Mock(return_value=False)
        first = asyncio.create_task(core.api_unlock('first'))
        await asyncio.sleep(0)
        with self.assertRaises(ValueError):
            await core.api_unlock('second')
        core.pin_ok.assert_not_called()
        with self.assertRaises(ValueError):
            await first
        core.pin_ok.assert_called_once_with('first')
        self.assertTrue(core.locked)
        self.assertFalse(core.pin_verifying)

    async def test_file_stream_preserves_full_and_suffix_responses(self):
        payload = b'0123456789' * 30000 + b'end'
        self.core.staged('').write_bytes(payload)
        valid = 'Host: 127.0.0.1:{port}\r\nX-TG-Token: test-token\r\n'
        full = await self.request(f'GET /staged HTTP/1.1\r\n{valid}\r\n')
        head, body = full.split('\r\n\r\n', 1)
        self.assertIn(f'Content-Length: {len(payload)}', head)
        self.assertEqual(body.encode(), payload)
        suffix = await self.request(f'GET /staged HTTP/1.1\r\n{valid}Range: bytes=-3\r\n\r\n')
        head, body = suffix.split('\r\n\r\n', 1)
        self.assertIn(f'Content-Range: bytes {len(payload) - 3}-{len(payload) - 1}/{len(payload)}', head)
        self.assertEqual(body, 'end')

    async def test_cached_extensionless_voice_plays_offline_on_ios_and_android(self):
        from tg_ascii_mobile.opus_mux import write_ogg

        core = Core(Path(self.files.name), 'iOS')
        self.addCleanup(core.loop.close)
        folder = core.media_folder()
        folder.mkdir(parents=True)
        original = folder / '42-8'
        original.write_bytes(write_ogg([bytes.fromhex('f8fffe')] * 30))
        self.core.media_file = core.media_file
        for playback, mime, magic in [('&play=caf', 'audio/x-caf', 'caff'), ('', 'audio/ogg', 'OggS')]:
            response = await self.request(
                f'GET /media?peer=42&id=8&thumb=0{playback} HTTP/1.1\r\n'
                'Host: 127.0.0.1:{port}\r\nX-TG-Token: test-token\r\nRange: bytes=0-3\r\n\r\n')
            head, body = response.split('\r\n\r\n')
            self.assertIn('206 Partial Content', head)
            self.assertIn('Content-Type: ' + mime, head)
            self.assertEqual(body, magic)
        self.assertEqual(await core.media_file(42, 8, False), original)

    async def test_inline_player_range_does_not_call_sendfile(self):
        payload = b'0123456789' * 18000
        path = Path(self.files.name) / 'voice.caf'
        path.write_bytes(payload)
        self.core.media_file = AsyncMock(return_value=path)
        with patch.object(asyncio.get_running_loop(), 'sendfile') as forbidden:
            response = await self.request(
                'GET /media?peer=42&id=8&thumb=0&play=caf HTTP/1.1\r\n'
                'Host: 127.0.0.1:{port}\r\nX-TG-Token: test-token\r\nRange: bytes=1700-140000\r\n\r\n')
            forbidden.assert_not_called()
        head, body = response.split('\r\n\r\n', 1)
        self.assertIn('206', head)
        self.assertIn('Content-Type: audio/x-caf', head)
        self.assertEqual(body.encode(), payload[1700:140001])

    async def test_secret_preview_has_no_cache_and_its_temporary_file_is_removed(self):
        from tg_ascii.secret_chats import secret_peer_id

        self.core.root = Path(self.files.name)
        self.core.media_file = AsyncMock()
        paths = []

        async def preview(peer, ident, thumbnail, directory):
            path = directory / 'secret.png'
            paths.append(path)
            path.write_bytes(b'private-preview')
            return path

        self.core.secret_preview_file = AsyncMock(side_effect=preview)
        response = await self.request(
            f'GET /media?peer={secret_peer_id(42)}&id=8 HTTP/1.1\r\n'
            'Host: 127.0.0.1:{port}\r\nX-TG-Token: test-token\r\nRange: bytes=0-6\r\n\r\n'
        )
        self.assertTrue(response.startswith('HTTP/1.1 206 '))
        self.assertIn('Cache-Control: no-store', response)
        self.assertTrue(response.endswith('\r\n\r\nprivate'))
        self.assertEqual(len(paths), 1)
        self.assertFalse(paths[0].exists())
        self.core.media_file.assert_not_awaited()

    async def test_secret_export_uses_a_separate_file_and_releases_android_source(self):
        from tg_ascii.secret_chats import secret_peer_id

        core = Core(Path(self.files.name), 'Android')
        core.loop.close()
        core.loop = asyncio.get_running_loop()
        core.media_file = AsyncMock()
        received = []

        async def preview(peer, ident, thumbnail, directory, *, original_name):
            self.assertTrue(original_name)
            path = directory / 'private.png'
            path.write_bytes(b'secret')
            return path

        def opener(action, name, done):
            path = Path(name)
            received.append(path)
            self.assertEqual(action, 'share')
            self.assertEqual(path.read_bytes(), b'secret')
            done(True)

        core.secret_preview_file = AsyncMock(side_effect=preview)
        core.native_open = opener
        response = await core.api_open_file(secret_peer_id(42), 8, action='share')
        self.assertEqual(response, {'opened': True, 'name': 'private.png'})
        self.assertEqual(received[0].parent.parent, core.root / 'secret-exports')
        self.assertFalse(received[0].exists())
        core.media_file.assert_not_awaited()

    async def test_secret_ios_export_keeps_source_until_native_activity_finishes(self):
        from tg_ascii.secret_chats import secret_peer_id

        core = Core(Path(self.files.name), 'iOS')
        core.loop.close()
        core.loop = asyncio.get_running_loop()
        received = []

        async def preview(peer, ident, thumbnail, directory, *, original_name):
            path = directory / 'private.png'
            path.write_bytes(b'secret')
            return path

        def opener(action, name, done, *, release):
            received.append((Path(name), release))
            done(True)

        core.secret_preview_file = AsyncMock(side_effect=preview)
        core.native_open = opener
        await core.api_open_file(secret_peer_id(42), 8, action='file')
        path, release = received[0]
        self.assertTrue(path.exists())
        release()
        await asyncio.sleep(0)
        self.assertFalse(path.exists())
