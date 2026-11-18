import asyncio
import base64
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

from tg_ascii.calls import CallManager
from tg_ascii_mobile.android_calls import AndroidCallManager, frame_jpeg
from tg_ascii_mobile.core import Core


class MobileCallTests(IsolatedAsyncioTestCase):
    async def test_ios_bridge_copies_frames_and_releases_the_handle(self):
        import ctypes as C
        from tg_ascii_mobile import ios_calls

        lib = SimpleNamespace(ntg_instance_create=Mock(return_value=7),
                              ntg_stop=Mock(return_value=0), ntg_instance_destroy=Mock(),
                              ntg_send_external_frame=Mock(return_value=0))
        for event in ('connection_change', 'signaling_data', 'remote_source_change', 'frames', 'update_emojis'):
            setattr(lib, f'ntg_on_{event}_callback', Mock(return_value=0))
        state, signal, frames, emojis, audio = (Mock() for _ in range(5))
        engine = ios_calls.IOSCallEngine(state, signal, frames, emojis, lib=lib, audio_session=audio)
        engine.audio_active = True
        try:
            callback = lib.ntg_on_frames_callback.call_args.args[1]
            payload = C.create_string_buffer(b'123456')
            values = (ios_calls.Frame * 1)(ios_calls.Frame(1, C.addressof(payload), 6,
                                                          ios_calls.FrameData(0, 1, 2, 2)))
            callback(7, 42, ios_calls.PLAYBACK, ios_calls.CAMERA, values, 1, None)
            payload[0] = b'X'
            peer, mode, device, received = frames.call_args.args
            self.assertEqual((peer, mode, device), (42, 'PLAYBACK', 'CAMERA'))
            self.assertEqual((received[0].data, received[0].frame_data.rotation), (b'123456', 90))
            await engine.send_screen_frame(42, b'123456', 10, 270, 2, 2)
            *arguments, frame = lib.ntg_send_external_frame.call_args.args
            self.assertEqual(arguments, [7, 42, ios_calls.CAMERA, b'123456', 6])
            self.assertEqual((frame.timestamp, frame.rotation, frame.width, frame.height), (10, 3, 2, 2))
        finally:
            await engine.stop(42)
        lib.ntg_stop.assert_called_once_with(7, 42)
        lib.ntg_instance_destroy.assert_called_once_with(7)
        audio.assert_called_once_with(False)

    async def asyncSetUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.core = Core(Path(folder.name), 'Android')
        self.addCleanup(self.core.loop.close)

    async def test_group_volume_is_local_and_validated(self):
        manager = SimpleNamespace(snapshot={'token': 'group', 'state': 'active', 'peer': 12},
                                  conference=False, can_manage=False, local_participant_volume=AsyncMock())
        self.core.group_call_manager = manager
        with patch.object(self.core, 'enable_group_call_manager', AsyncMock(return_value=manager)):
            for invalid in (-1, 201, True, 25.5):
                with self.assertRaises(ValueError):
                    await self.core.api_group_call_action('participant_volume', token='group', user=42, value=invalid)
            with self.assertRaises(ValueError):
                await self.core.api_group_call_action('participant_volume', token='stale', user=42, value=150)
            manager.local_participant_volume.assert_not_awaited()
            await self.core.api_group_call_action('participant_volume', token='group', user=42, value=150)
            manager.local_participant_volume.assert_awaited_once_with(42, token='group', volume=15000)

    async def test_outdated_call_control_cannot_mute_current_call(self):
        manager = SimpleNamespace(snapshot={'token': 'new'}, mute=AsyncMock())
        self.core.call_manager = manager
        with self.assertRaises(ValueError):
            await self.core.api_call_action('mute', token='old', value=True)
        manager.mute.assert_not_called()
        await self.core.api_call_action('mute', token='new', value=True)
        manager.mute.assert_awaited_once_with(True, token='new')

    async def test_background_call_notification_tracks_incoming_token(self):
        notify = Mock()
        self.core.native_incoming_call = notify
        manager = SimpleNamespace(snapshot={'token': 'call', 'state': 'incoming'})
        self.core.call_manager = manager
        self.core.sync_incoming_call_notification()
        notify.assert_not_called()

        self.core.in_background = True
        self.core.sync_incoming_call_notification()
        self.core.sync_incoming_call_notification()
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[0], 'call')
        self.assertTrue(callable(notify.call_args.args[1]))

        manager.snapshot = {'token': 'call', 'state': 'active'}
        self.core.sync_incoming_call_notification()
        notify.assert_called_with(None, None)

    async def test_telecom_cannot_disconnect_a_replacement_call(self):
        android = Mock()
        self.core.native_telecom = android
        manager = SimpleNamespace(snapshot={'token': 'original', 'state': 'incoming'}, decline=AsyncMock())
        self.core.call_manager = manager
        self.core.on_native_call(manager.snapshot)
        disconnect = android.call_args.args[2]
        manager.snapshot = {'token': 'replacement', 'state': 'incoming'}
        with patch.object(self.core, 'loop', asyncio.get_running_loop()):
            disconnect()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        manager.decline.assert_not_awaited()

        self.core.on_native_call(manager.snapshot)
        with patch.object(self.core, 'loop', asyncio.get_running_loop()):
            android.call_args.args[2]()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        manager.decline.assert_awaited_once_with(token='replacement')

    async def test_outgoing_call_waits_for_telecom_before_negotiating(self):
        call = SimpleNamespace(incoming=False, token='outgoing', video=False)
        manager = AndroidCallManager(None, core=self.core)
        manager._call = call
        self.core.native_telecom_outgoing = AsyncMock(side_effect=ValueError('Telecom denied'))
        with patch.object(CallManager, '_prepare', new_callable=AsyncMock) as prepare:
            with self.assertRaisesRegex(ValueError, 'Telecom denied'):
                await manager._prepare(call)
            prepare.assert_not_awaited()

            self.core.native_telecom_outgoing.side_effect = None
            await manager._prepare(call)
            self.assertEqual(self.core.native_telecom_outgoing.await_args.args[0], 'outgoing')
            prepare.assert_awaited_once_with(call)

    async def test_failed_audio_service_releases_only_its_call_token(self):
        call = SimpleNamespace(incoming=True, token='audio', video=False)
        manager = AndroidCallManager(None, core=self.core)
        manager._call = call
        self.core.native_call_media_start = AsyncMock(side_effect=ValueError('microphone'))
        self.core.native_call_media_end = Mock()
        with patch.object(CallManager, '_prepare', new_callable=AsyncMock) as prepare:
            with self.assertRaisesRegex(ValueError, 'microphone'):
                await manager._prepare(call)
            prepare.assert_not_awaited()
        with patch.object(CallManager, '_finish', new_callable=AsyncMock):
            await manager._finish(SimpleNamespace(token='old'))
            self.core.native_call_media_end.assert_not_called()
            await manager._finish(call)
            await manager._finish(call)
        self.core.native_call_media_end.assert_called_once_with('audio')

    async def test_failed_camera_start_reverts_foreground_camera_type(self):
        manager = AndroidCallManager(None, core=self.core)
        manager._call = SimpleNamespace(token='camera', video=False)
        manager._media_token = 'camera'
        self.core.native_call_media_camera = AsyncMock()
        with patch.object(CallManager, 'set_camera', new_callable=AsyncMock) as capture:
            capture.side_effect = RuntimeError('Camera unavailable')
            with self.assertRaisesRegex(RuntimeError, 'Camera unavailable'):
                await manager.set_camera(True, token='camera')
        self.assertEqual([call.args for call in self.core.native_call_media_camera.await_args_list],
                         [('camera', True), ('camera', False)])

    async def test_odd_size_i420_frame_keeps_camera_rotation(self):
        frame = {'width': 3, 'height': 5, 'rotation': 90, 'data': bytes([128]) * (15 + 2 * 6)}
        with Image.open(io.BytesIO(base64.b64decode(frame_jpeg(frame)))) as preview:
            self.assertEqual(preview.format, 'JPEG')
            self.assertEqual(preview.size, (5, 3))

    async def test_group_frames_keep_each_camera_and_filter_old_call_frames(self):
        frame = {'width': 2, 'height': 2, 'rotation': 0, 'data': bytes([128]) * 6, 'token': 'current'}
        self.core.group_call_manager = SimpleNamespace(
            snapshot={'token': 'current'}, video_grid=True,
            take_local_frame=lambda: frame,
            take_frames=lambda: {11: frame, 12: frame, 13: {**frame, 'token': 'old'}},
            active_tiles=lambda: [11, 12],
        )
        result = await self.core.api_group_call_frames('current')
        self.assertEqual(result['tiles'], ['11', '12'])
        self.assertEqual(set(result['cameras']), {'11', '12'})
        self.assertTrue(result['local'])
        self.assertEqual(await self.core.api_group_call_frames('old'), {})

    async def test_hangup_during_projection_prompt_prevents_late_capture(self):
        from tg_ascii_mobile import android_screen_share

        class Manager:
            def __init__(self):
                self._call = SimpleNamespace(state='active', screen=False, token='active')
                self.set_screen = AsyncMock()

            def _check(self, *, token):
                return self._call

            async def _finish(self, call, error='', *, discard=False):
                self._call = None

        class ScreenManager(android_screen_share.ScreenShare, Manager):
            pass

        ready = asyncio.Event()
        accepted = asyncio.Event()

        async def request(still_current, on_stopped):
            ready.set()
            await accepted.wait()
            self.assertFalse(still_current())
            return True

        manager = ScreenManager()
        stop = Mock()
        with patch.object(android_screen_share, '_request_projection', request), \
                patch.object(android_screen_share, '_end_projection', stop):
            task = asyncio.create_task(manager.share_screen(True, token='active'))
            await ready.wait()
            await manager._finish(manager._call)
            accepted.set()
            await task
        manager.set_screen.assert_not_awaited()
        stop.assert_called_once_with()


    async def test_projection_stop_ignores_callbacks_from_previous_capture(self):
        import json
        from tg_ascii_mobile import android_screen_share
        test = self

        class Manager:
            def __init__(self):
                self._call = SimpleNamespace(state='active', screen=False, token='call')
                self.tasks = []

            def _check(self, *, token):
                return self._call

            async def set_screen(self, source, *, token):
                if source:
                    test.assertEqual(json.loads(source), {'id': 'screen'})
                self._call.screen = bool(source)

            def _schedule(self, coroutine):
                self.tasks.append(asyncio.create_task(coroutine))

        class ScreenManager(android_screen_share.ScreenShare, Manager):
            pass

        callbacks = []

        async def request(still_current, on_stopped):
            callbacks.append(on_stopped)
            return True

        manager = ScreenManager()
        stop = Mock()
        with patch.object(android_screen_share, '_request_projection', request), \
                patch.object(android_screen_share, '_end_projection', stop):
            await manager.share_screen(True, token='call')
            await manager.share_screen(False, token='call')
            await manager.share_screen(True, token='call')
            callbacks[0]()
            await manager.tasks[-1]
            self.assertTrue(manager._call.screen)
            callbacks[1]()
            await manager.tasks[-1]
            self.assertFalse(manager._call.screen)
        self.assertEqual(stop.call_count, 2)
