from datetime import datetime, timezone
from pathlib import Path
import queue
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from telethon import errors

from tg_ascii.backend import Chat, DemoBackend, TelegramBackend
from tg_ascii.desktop import AsyncWorker, Desktop
from tg_ascii.desktop_service import DesktopService


class DesktopLoginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.client = Mock()
        self.client.connect = AsyncMock()
        self.client.disconnect = AsyncMock()
        self.client.is_user_authorized = AsyncMock(return_value=False)
        self.client.send_code_request = AsyncMock(return_value=SimpleNamespace(phone_code_hash='test-hash'))
        self.client.sign_in = AsyncMock()
        self.service = DesktopService(root=self.directory.name, client_factory=lambda *a, **k: self.client)

    async def asyncTearDown(self):
        await self.service.close()
        self.directory.cleanup()

    async def test_saved_session_opens_chats_without_phone(self):
        self.client.is_user_authorized.return_value = True
        self.assertEqual(await self.service.connect((12345, 'a' * 32)), 'ready')
        self.assertIsInstance(self.service.backend, TelegramBackend)
        self.client.send_code_request.assert_not_called()

    async def test_phone_code_and_two_factor_are_separate_gui_steps(self):
        self.assertEqual(await self.service.connect((12345, 'a' * 32)), 'phone')
        self.assertEqual(await self.service.request_code('+56 (9) 1234-5678'), 'code')
        self.client.send_code_request.assert_awaited_once_with('+56912345678')
        self.client.sign_in.side_effect = [errors.PhoneCodeInvalidError(None), errors.SessionPasswordNeededError(None), None]
        with self.assertRaises(errors.PhoneCodeInvalidError):
            await self.service.verify_code('11111')
        self.assertEqual(await self.service.verify_code('22 222'), 'password')
        self.assertEqual(await self.service.verify_password('test-only'), 'ready')
        self.client.send_code_request.assert_awaited_once()
        self.assertFalse((Path(self.directory.name) / 'config.json').exists())

    async def test_number_requiring_signup_guides_user_to_official_app(self):
        self.assertEqual(await self.service.connect((12345, 'a' * 32)), 'phone')
        self.assertEqual(await self.service.request_code('+34612345678'), 'code')
        self.client.sign_in.side_effect = errors.PhoneNumberUnoccupiedError(None)
        self.assertEqual(await self.service.verify_code('11111'), 'signup')
        self.assertIsNone(self.service.code_hash)
        self.client.send_code_request.side_effect = errors.PhoneNumberAppSignupForbiddenError(None)
        self.assertEqual(await self.service.request_code('+34612345678'), 'signup')
        self.assertIsNone(self.service.phone)
        self.client.sign_up.assert_not_called()

    async def test_failed_connection_disconnects(self):
        self.client.connect.side_effect = ConnectionError('offline')
        with self.assertRaises(ConnectionError):
            await self.service.connect((12345, 'a' * 32))
        self.client.disconnect.assert_awaited_once()
        self.assertIsNone(self.service.client)

    async def test_corrupt_developer_config_returns_to_gui_setup(self):
        (Path(self.directory.name) / 'config.json').write_text('{broken', encoding='utf-8')
        with patch('tg_ascii.desktop_service.bundled_credentials', return_value=None), \
                patch.dict('os.environ', {}, clear=True):
            self.assertEqual(await self.service.connect(), 'credentials')
        self.client.connect.assert_not_called()

    async def test_demo_does_not_create_session_or_call_telegram(self):
        service = DesktopService(demo=True, root=Path(self.directory.name) / 'unused', client_factory=Mock())
        self.assertEqual(await service.connect(), 'ready')
        service.client_factory.assert_not_called()
        self.assertFalse(service.root.exists())


class AttachmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_preserves_filename_unicode_caption_and_recipient(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'prueba.txt'
            path.write_text('contenido de prueba', encoding='utf-8')
            client = Mock()
            stream_seen = []
            async def upload(peer, stream, **kwargs):
                self.assertEqual(peer, 42)
                self.assertEqual(stream.read(), b'contenido de prueba')
                self.assertEqual(kwargs['caption'], 'Qué tal 👋')
                self.assertTrue(kwargs['force_document'])
                self.assertIsNone(kwargs['parse_mode'])
                stream_seen.append(stream)
                return SimpleNamespace(id=8, out=True, raw_text=kwargs['caption'], date=datetime.now(timezone.utc), file=SimpleNamespace(name=path.name, size=path.stat().st_size))
            client.send_file = AsyncMock(side_effect=upload)
            backend = TelegramBackend(client)
            sent = await backend.send_attachment(42, path, caption='Qué tal 👋')
            self.assertTrue(stream_seen[0].closed)
            self.assertIn('prueba.txt', sent.text)
            self.assertIn('Qué tal 👋', sent.text)
            with self.assertRaises(ValueError):
                await backend.send_attachment(42, Path(folder))
            self.assertEqual(client.send_file.await_count, 1)

    async def test_demo_attachment_does_not_read_or_transmit_contents(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'example.txt'
            path.write_text('private fixture', encoding='utf-8')
            backend = DemoBackend()
            sent = await backend.send_attachment(1, path, caption='demo')
            self.assertIn('example.txt', sent.text)
            self.assertNotIn('private fixture', sent.text)

    async def test_gui_keeps_recipient_and_draft_on_upload_failure(self):
        ui = object.__new__(Desktop)
        ui.demo = False
        ui.chats = [Chat(42, 'Synthetic recipient')]
        ui.busy, ui.active, ui.attachment = False, 42, Path('test-file.txt')
        ui.editor, ui.status, ui.history = Mock(), Mock(), Mock()
        ui.editor.get.return_value = 'caption'
        ui.progress = {}
        class Progress(dict):
            def pack(self, **kwargs): pass
            def pack_forget(self): pass
        ui.progress = Progress()
        ui.worker = SimpleNamespace(events=queue.SimpleQueue())
        ui.service = SimpleNamespace(backend=SimpleNamespace(send_attachment=AsyncMock(side_effect=ConnectionError('offline'))))
        ui.drafts = {}
        pending = []
        def call(operation, done, status, failed, **kwargs):
            ui.busy = True
            pending.append((operation, failed))
        ui.call = call
        ui.send()
        ui.active = 99
        ui.send()  # busy: cannot start a second send
        self.assertEqual(len(pending), 1)
        try:
            await pending[0][0]
        except ConnectionError as exc:
            pending[0][1](exc)
        self.assertEqual(ui.service.backend.send_attachment.call_args.args[0], 42)
        ui.editor.delete.assert_not_called()
        self.assertEqual(ui.attachment, Path('test-file.txt'))

    async def test_cancelled_picker_does_not_attach_or_send(self):
        ui = object.__new__(Desktop)
        ui.demo = False
        ui.chats = [Chat(42, 'Synthetic recipient')]
        ui.busy, ui.active, ui.attachment, ui.root = False, 42, None, Mock()
        ui.ui_account = 'account'
        ui.update_attachment = Mock()
        with patch('tg_ascii.desktop.filedialog.askopenfilenames', return_value=()):
            ui.pick_attachment()
        self.assertIsNone(ui.attachment)
        ui.update_attachment.assert_not_called()


class NavigationTests(unittest.IsolatedAsyncioTestCase):
    def make_ui(self):
        ui = object.__new__(Desktop)
        ui.ui_account = 'account'
        ui.busy, ui.active, ui.attachment = False, 1, Path('draft.txt')
        ui.messages = [SimpleNamespace(id=10)]
        ui.drafts = {}
        ui.chat_list, ui.editor, ui.status = Mock(), Mock(), Mock()
        ui.chat_list.selection.return_value = ('2',)
        ui.editor.get.return_value = 'unfinished'
        for method in ('restore_draft', 'render_messages', 'render_chats', 'show_error'):
            setattr(ui, method, Mock())
        ui.service = SimpleNamespace(backend=SimpleNamespace(history=AsyncMock()))
        ui.pending = []
        def call(operation, done, status, failed, **kwargs):
            ui.busy = True
            ui.pending.append((operation, done, failed))
        ui.call = call
        return ui

    async def test_failed_chat_open_restores_previous_chat_and_draft(self):
        ui = self.make_ui()
        ui.service.backend.history.side_effect = ConnectionError('offline')
        ui.choose_chat()
        self.assertEqual(ui.active, 2)
        self.assertEqual(ui.drafts[1], ('unfinished', Path('draft.txt')))
        operation, done, failed = ui.pending[0]
        try:
            await operation
        except ConnectionError as exc:
            failed(exc)
        self.assertEqual(ui.active, 1)
        self.assertEqual([m.id for m in ui.messages], [10])
        ui.show_error.assert_called_once()

    async def test_live_event_during_history_load_is_kept_once_and_navigation_blocked(self):
        ui = self.make_ui()
        ui.service.backend.history.return_value = [SimpleNamespace(id=20), SimpleNamespace(id=21)]
        ui.choose_chat()
        ui.messages = [SimpleNamespace(id=21), SimpleNamespace(id=22)]
        ui.chat_list.selection.return_value = ('3',)
        ui.choose_chat()
        self.assertEqual(ui.active, 2)
        ui.chat_list.selection_set.assert_called_with('2')
        self.assertEqual(len(ui.pending), 1)
        operation, done, failed = ui.pending[0]
        done(await operation)
        self.assertEqual([m.id for m in ui.messages], [20, 21, 22])


class WorkerTests(unittest.TestCase):
    def test_callbacks_are_queued_for_the_ui_thread(self):
        worker = AsyncWorker()
        callback = Mock()
        try:
            async def result(): return 'ready'
            future = worker.submit(result(), callback, callback)
            self.assertEqual(future.result(timeout=3), 'ready')
            handler, value = worker.events.get(timeout=3)
            callback.assert_not_called()
            handler(value)
            callback.assert_called_once_with('ready')
        finally:
            worker.stop()
            worker.thread.join(timeout=3)
        self.assertFalse(worker.thread.is_alive())
