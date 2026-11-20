import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from telethon import functions, types
from tg_ascii.accounts import Accounts
from tg_ascii.audio_engine import AudioJob
from tg_ascii.backend import TelegramBackend, Chat
from tg_ascii.desktop_tools import DesktopTools
from tg_ascii.message_tools import formatted_entities, entity_spans
from tg_ascii.preferences import Preferences
from test_features import FakeService


class FormattingTests(unittest.TestCase):
    def test_utf16_combines_styles_with_custom_emoji_and_roundtrips(self):
        text = 'Hi 😀 world'
        spans = [(0, 10, 'bold', ''), (5, 10, 'italic', '')]
        emojis = [(3, 4, 123, '😀')]
        entities = formatted_entities(text, spans, emojis)
        self.assertEqual([(e.offset, e.length) for e in entities], [(0, 11), (3, 2), (6, 5)])
        self.assertEqual(entity_spans(text, entities), (spans, emojis))

    def test_rejects_invalid_links_and_illegal_entity_intersections(self):
        for spans in [[(0, 3, 'link', 'javascript:alert(1)')], [(0, 3, 'code', ''), (1, 2, 'bold', '')],
                      [(0, 3, 'bold', ''), (2, 4, 'italic', '')], [(0, 9, 'bold', '')]]:
            with self.subTest(spans=spans), self.assertRaises(ValueError): formatted_entities('abcd', spans)
        self.assertIsInstance(formatted_entities('hi', [(0, 2, 'link', 'https://example.org')])[0], types.MessageEntityTextUrl)

    def test_code_cannot_enclose_custom_emoji(self):
        with self.assertRaises(ValueError): formatted_entities('😀', [(0, 1, 'code', '')], [(0, 1, 123, '😀')])

    def test_font_and_background_preferences_are_persistent_and_validated(self):
        with tempfile.TemporaryDirectory() as folder:
            prefs = Preferences(folder)
            prefs.save({'font_family': 'Example Font', 'background_notifications': False})
            loaded = Preferences(folder)
            self.assertEqual(loaded.values['font_family'], 'Example Font')
            self.assertFalse(loaded.values['background_notifications'])
            self.assertEqual(Preferences.validated({'font_family': 'bad\x00font'})['font_family'], '')


class MessageToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = AsyncMock()
        self.client.add_event_handler = Mock()
        self.client.get_input_entity.side_effect = lambda peer: types.InputPeerUser(peer, 5)
        self.backend = TelegramBackend(self.client)
        self.backend.message = lambda result: result

    async def test_formatted_caption_and_voice_keep_recipient_and_close_stream(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'voice.ogg'
            path.write_bytes(b'test-only audio')
            observed = []
            async def upload(peer, stream, **kwargs):
                self.assertEqual(peer, 42)
                self.assertEqual(stream.read(), b'test-only audio')
                observed.append((stream, kwargs))
                return 'sent'
            self.client.send_file.side_effect = upload
            await self.backend.send_formatted(42, '😀 bold', [(2, 6, 'bold', '')], path=path)
            await self.backend.send_audio(42, path, voice=True, duration=2.6)
            self.assertTrue(all(stream.closed for stream, _ in observed))
            self.assertEqual(observed[0][1]['caption'], '😀 bold')
            self.assertEqual(observed[0][1]['formatting_entities'][0].offset, 3)
            options = observed[1][1]
            self.assertTrue(options['voice_note'])
            self.assertFalse(options['force_document'])
            self.assertEqual(options['mime_type'], 'audio/ogg')
            self.assertEqual(options['attributes'][0].duration, 3)
            self.assertTrue(options['attributes'][0].voice)

    async def test_invalid_format_never_sends(self):
        with self.assertRaises(ValueError): await self.backend.send_formatted(42, 'hey', [(0, 9, 'bold', '')])
        self.client.send_message.assert_not_awaited()

    async def test_chat_translation_checks_premium_and_batches_exact_ids(self):
        self.client.get_me.return_value = types.User(10, premium=False)
        with self.assertRaises(ValueError): await self.backend.translate_messages(42, [1], 'es', premium=True)
        self.client.assert_not_awaited()
        self.client.get_me.return_value = types.User(10, premium=True)
        await self.backend.refresh_account()
        async def request(req):
            self.assertIsInstance(req, functions.messages.TranslateTextRequest)
            self.assertEqual(req.peer.user_id, 42)
            self.assertEqual(req.to_lang, 'uk')
            return SimpleNamespace(result=[types.TextWithEntities(str(i), []) for i in req.id])
        self.client.side_effect = request
        result = await self.backend.translate_messages(42, list(range(45)), 'uk', premium=True)
        self.assertEqual(list(result), list(range(45)))
        self.assertEqual([len(call.args[0].id) for call in self.client.await_args_list], [20, 20, 5])

    async def test_incomplete_translation_does_not_misassign_messages(self):
        self.client.return_value = SimpleNamespace(result=[types.TextWithEntities('only one', [])])
        with self.assertRaises(ValueError): await self.backend.translate_messages(42, [1, 2], 'pl')

    async def test_ai_uses_native_editor_entities_and_never_sends(self):
        self.client.return_value = SimpleNamespace(result_text=types.TextWithEntities('Hello', [types.MessageEntityBold(0, 5)]))
        result = await self.backend.compose_ai('Helo', [(0, 4, 'bold', '')])
        req = self.client.await_args.args[0]
        self.assertIsInstance(req, functions.messages.ComposeMessageWithAIRequest)
        self.assertTrue(req.proofread)
        self.assertEqual(req.text.text, 'Helo')
        self.assertEqual(result.text, 'Hello')
        self.client.send_message.assert_not_awaited()
        self.client.send_file.assert_not_awaited()

    async def test_late_translation_after_switch_stays_with_original_account(self):
        ui = object.__new__(DesktopTools)
        ui.demo, ui.active, ui.ui_account = False, 42, 'one'
        ui.preferences = SimpleNamespace(values={'advanced_features': {'chat_translation': True}})
        ui.chat_translations = {'one:42': 'es'}
        ui.translated, ui.translation_pending, ui.translation_failed = {}, set(), set()
        ui.messages = [SimpleNamespace(id=5, text='source')]
        self.backend.account_profile.remember(types.User(100, premium=True))
        ui.chats = [Chat(42, 'Synthetic', entity=types.User(42))]
        ui.service = SimpleNamespace(backend=self.backend, entries={'one': {'premium': True}, 'two': {}})
        ui.worker, ui.render_messages, ui.status = Mock(), Mock(), Mock()
        ui.schedule_translations()
        coroutine, done, _ = ui.worker.submit.call_args.args
        coroutine.close()
        ui.ui_account = 'two'
        done({5: types.TextWithEntities('traducido', [])})
        self.assertIn(('one', 42, 5, 'es', 'source'), ui.translated)
        ui.render_messages.assert_not_called()


class LogoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_revokes_only_selected_session_and_preserves_other_sqlite(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = Accounts(root=folder, factory=FakeService)
            await manager.connect()
            first = manager.service('account')
            await manager.add()
            second_key, second = manager.current, manager.service(manager.current)
            first.client.log_out = AsyncMock(return_value=True)
            second.client.log_out = AsyncMock(return_value=True)
            token = second.session.auth_key.key
            self.assertEqual(await manager.logout('account'), 'ready')
            first.client.log_out.assert_awaited_once()
            second.client.log_out.assert_not_awaited()
            self.assertFalse(second.closed)
            self.assertEqual(second.session.auth_key.key, token)
            saved = json.loads((Path(folder) / 'accounts.json').read_text(encoding='utf-8'))
            self.assertEqual(set(saved['accounts']), {second_key})
            await manager.close()

    async def test_failed_logout_keeps_registry_and_other_connections(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = Accounts(root=folder, factory=FakeService)
            await manager.connect()
            first = manager.service('account')
            first.client.log_out = AsyncMock(return_value=False)
            before = (Path(folder) / 'accounts.json').read_bytes()
            with self.assertRaises(ValueError): await manager.logout('account')
            self.assertEqual((Path(folder) / 'accounts.json').read_bytes(), before)
            self.assertFalse(first.closed)
            self.assertIn('account', manager.services)
            await manager.close()


class AudioTests(unittest.TestCase):
    def test_cancel_recording_closes_microphone_and_file_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'voice.ogg'
            entered = threading.Event()
            recorder = AudioJob()
            stream, output = Mock(), Mock()
            stream.__enter__ = Mock(return_value=stream)
            stream.__exit__ = Mock(return_value=False)
            output.__enter__ = Mock(return_value=output)
            output.__exit__ = Mock(return_value=False)
            def read(frames):
                entered.set()
                recorder.stop()
                return bytes(48000), False
            stream.read.side_effect = read
            check = Mock(frames=24000)
            check.__enter__ = Mock(return_value=check)
            check.__exit__ = Mock(return_value=False)
            def soundfile(filename, **kwargs):
                if kwargs: Path(filename).touch(); return output
                return check
            sd = SimpleNamespace(RawInputStream=Mock(return_value=stream))
            sf = SimpleNamespace(check_format=Mock(return_value=True), SoundFile=Mock(side_effect=soundfile))
            with patch('tg_ascii.audio_engine.libraries', return_value=(sd, sf)):
                recorder.record(path)
                self.assertTrue(recorder.done.wait(2))
            self.assertTrue(entered.is_set())
            self.assertIsNone(recorder.error)
            self.assertEqual(recorder.seconds, .5)
            stream.__exit__.assert_called_once()
            output.__exit__.assert_called_once()

    def test_missing_opus_never_opens_microphone(self):
        sd = Mock()
        sf = SimpleNamespace(check_format=Mock(return_value=False))
        with patch('tg_ascii.audio_engine.libraries', return_value=(sd, sf)):
            job = AudioJob().record('unused.ogg')
            self.assertTrue(job.done.wait(2))
        self.assertIsInstance(job.error, RuntimeError)
        sd.RawInputStream.assert_not_called()

    def test_playback_stop_closes_output_stream(self):
        job = AudioJob()
        source, speaker = Mock(samplerate=48000, channels=1), Mock()
        for obj in (source, speaker):
            obj.__enter__ = Mock(return_value=obj)
            obj.__exit__ = Mock(return_value=False)
        source.buffer_read.return_value = bytes(9600)
        speaker.write.side_effect = lambda block: job.stop()
        with patch('tg_ascii.audio_engine.libraries', return_value=(SimpleNamespace(RawOutputStream=Mock(return_value=speaker)), SimpleNamespace(SoundFile=Mock(return_value=source)))):
            job.play('fixture.ogg')
            self.assertTrue(job.done.wait(2))
        self.assertIsNone(job.error)
        self.assertEqual(speaker.write.call_count, 1)
        speaker.__exit__.assert_called_once()


class BackgroundTests(unittest.TestCase):
    def test_failed_tray_keeps_window_reachable(self):
        ui = SimpleNamespace(demo=True, closed=False, closing=False, background=SimpleNamespace(ready=False), root=Mock(), status=Mock())
        with patch('tg_ascii.desktop_tools.sys.platform', 'linux'):
            DesktopTools.hide_if_tray_ready(ui)
        ui.root.iconify.assert_called_once()
        ui.root.withdraw.assert_not_called()

    def test_mac_x_hides_without_a_tray_icon_or_disconnect(self):
        ui = SimpleNamespace(demo=True, closed=False, closing=False, background=None, root=Mock(), popups=[], service=Mock())
        with patch('tg_ascii.desktop_tools.sys.platform', 'darwin'):
            DesktopTools.hide_if_tray_ready(ui)
        ui.root.withdraw.assert_called_once()
        ui.service.close.assert_not_called()

    def test_ready_tray_hides_window_without_disconnect(self):
        ui = SimpleNamespace(demo=True, closed=False, closing=False, background=SimpleNamespace(ready=True), root=Mock(), popups=[], service=Mock())
        DesktopTools.hide_if_tray_ready(ui)
        ui.root.withdraw.assert_called_once()
        ui.service.close.assert_not_called()


class InstanceTests(unittest.TestCase):
    def test_second_process_lock_is_rejected_and_release_allows_reopen(self):
        from tg_ascii.instance import InstanceLock
        with tempfile.TemporaryDirectory() as folder:
            first = InstanceLock(folder)
            second = InstanceLock(folder)
            self.assertTrue(first.acquired)
            self.assertFalse(second.acquired)
            first.close()
            third = InstanceLock(folder)
            self.assertTrue(third.acquired)
            third.close()

    def test_mac_bundle_has_microphone_reason_and_is_resigned(self):
        from test_release import release
        import plistlib
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder) / 'TG-ASCII.app'
            (app / 'Contents').mkdir(parents=True)
            path = app / 'Contents' / 'Info.plist'
            with path.open('wb') as stream: plistlib.dump({'CFBundleName': 'TG-ASCII'}, stream)
            with patch.object(release.subprocess, 'run') as run:
                release.configure_mac_bundle(app)
            with path.open('rb') as stream: info = plistlib.load(stream)
            self.assertIn('Record', info['NSMicrophoneUsageDescription'])
            self.assertEqual(info['CFBundleName'], 'TeleGraph')
            self.assertEqual(info['CFBundleDisplayName'], 'TeleGraph')
            self.assertEqual(info['NSUserNotificationAlertStyle'], 'banner')
            self.assertEqual(info['CFBundleIdentifier'], 'org.tgas.desktop')
            self.assertEqual(run.call_args.args[0], ['/usr/bin/codesign', '--force', '--sign', '-', str(app)])

    def test_media_without_caption_is_not_sent_for_automatic_translation(self):
        ui = object.__new__(DesktopTools)
        ui.demo, ui.active, ui.ui_account = False, 42, 'one'
        ui.preferences = SimpleNamespace(values={'advanced_features': {'chat_translation': True}})
        ui.chat_translations = {'one:42': 'es'}
        ui.translated, ui.translation_pending, ui.translation_failed = {}, set(), set()
        ui.messages = [SimpleNamespace(id=5, text='[File] photo.jpg', raw_text='')]
        ui.service = SimpleNamespace(backend=Mock())
        ui.worker = Mock()
        ui.schedule_translations()
        ui.worker.submit.assert_not_called()

if __name__ == '__main__': unittest.main()
