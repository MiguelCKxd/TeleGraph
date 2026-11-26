"""A real loopback socket owns its optional native modal, without user accounts."""
import asyncio
import json
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from tg_ascii_mobile.native_dialogs import CANCELLED, DialogService
from tg_ascii_mobile.server import Server


class NativeDialogHTTPTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.presented = asyncio.Event()
        self.dismissed = asyncio.Event()
        self.core = SimpleNamespace(account='qa', backend=object(), stage='ready', locked=False,
                                    token='fixture', appearance=lambda: {'native_dialogs': True})

        def present(data, completed):
            self.completed = completed
            self.presented.set()
            return self.dismissed.set

        self.core.native_dialogs = DialogService(self.core, present, timeout=2)

        async def call(name, params):
            self.assertEqual(name, 'native_dialog')
            return await self.core.native_dialogs.request(**params)

        self.core.call = call
        self.server = Server(self.core)
        self.port = await self.server.start()
        self.addAsyncCleanup(self.close_server)

    async def close_server(self):
        self.core.native_dialogs.cancel()
        self.server.server.close()
        await self.server.server.wait_closed()

    async def start_request(self):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.port)
        body = json.dumps({'account': 'qa', 'request': {
            'id': 'a' * 32, 'kind': 'prompt', 'title': 'Fixture', 'cancel': 'Cancelar',
            'actions': [{'label': 'Continuar'}]}}).encode()
        writer.write((f'POST /api/native_dialog HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n'
                      f'X-TG-Token: fixture\r\nConnection: close\r\nContent-Length: {len(body)}\r\n\r\n').encode() + body)
        await writer.drain()
        await asyncio.wait_for(self.presented.wait(), 1)
        return reader, writer

    async def test_disconnect_dismisses_pending_modal_and_discards_late_result(self):
        reader, writer = await self.start_request()
        writer.close()
        await writer.wait_closed()
        await asyncio.wait_for(self.dismissed.wait(), 1)
        self.assertIsNone(self.core.native_dialogs.pending)
        self.completed({'handled': True, 'cancelled': False, 'index': 0, 'text': 'late'})
        await asyncio.sleep(0)
        self.assertIsNone(self.core.native_dialogs.pending)

    async def test_user_may_take_longer_than_request_read_or_keep_alive_limits(self):
        with patch('tg_ascii_mobile.server.REQUEST_READ_TIMEOUT', .02), \
                patch('tg_ascii_mobile.server.KEEP_ALIVE_IDLE', .02):
            reader, writer = await self.start_request()
            try:
                await asyncio.sleep(.08)
                self.assertFalse(self.dismissed.is_set())
                self.completed({'handled': True, 'cancelled': False, 'index': 0, 'text': 'Fixture'})
                response = await asyncio.wait_for(reader.read(), 1)
                body = json.loads(response.split(b'\r\n\r\n', 1)[1])
                self.assertEqual(body['result']['text'], 'Fixture')
                self.assertTrue(self.dismissed.is_set())
            finally:
                writer.close()
                await writer.wait_closed()

    async def test_modal_timeout_returns_cancelled_over_the_same_connection(self):
        self.core.native_dialogs.timeout = .04
        reader, writer = await self.start_request()
        try:
            response = await asyncio.wait_for(reader.read(), 1)
            body = json.loads(response.split(b'\r\n\r\n', 1)[1])
            self.assertEqual(body, {'ok': True, 'result': CANCELLED})
            self.assertTrue(self.dismissed.is_set())
            self.assertIsNone(self.core.native_dialogs.pending)
        finally:
            writer.close()
            await writer.wait_closed()
