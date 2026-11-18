import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock

from tg_ascii_mobile import ntgcalls_android as nt
from tg_ascii_mobile.core import Core

SRC = Path(__file__).resolve().parent.parent / 'src'


class NtgcallsShimTests(TestCase):
    def test_records_take_positional_and_keyword_values(self):
        audio = nt.AudioDescription(nt.MediaSource.DEVICE, 48000, 1, 'mic', False)
        same = nt.AudioDescription(media_source=nt.MediaSource.DEVICE, sample_rate=48000, channel_count=1,
                                   input='mic', keep_open=False)
        self.assertEqual(audio, same)
        self.assertIsNone(nt.MediaDescription(microphone=audio).camera)
        with self.assertRaises(TypeError):
            nt.SsrcGroup('SIM', [1], 'extra')
        with self.assertRaises(TypeError):
            nt.SsrcGroup(unknown=1)

    def test_values_pass_the_shared_engine_codec(self):
        from tg_ascii.calls_rpc_codec import encode
        description = nt.MediaDescription(nt.AudioDescription(nt.MediaSource.DEVICE, 48000, 1, '', False), None,
                                          nt.VideoDescription(nt.MediaSource.EXTERNAL, -1, -1, 0, '', False), None)
        self.assertEqual(encode(description)[0:2], ('record', 'MediaDescription'))
        self.assertEqual(encode(nt.StreamMode.PLAYBACK), ('enum', 'StreamMode', 1))

    def test_enums_match_the_native_extension(self):
        self.assertEqual(nt.CallType.P2P, nt.CallType.OUTGOING | nt.CallType.INCOMING)
        self.assertEqual(nt.MediaSource.EXTERNAL.value, 32)
        self.assertEqual(nt.ConnectionState.CLOSED.name, 'CLOSED')
        self.assertEqual(nt.VideoRotation.VIDEO_ROTATION_270.value, 270)

    def test_java_exceptions_map_to_ntgcalls_names(self):
        def java(name):
            return SimpleNamespace(getClass=lambda: SimpleNamespace(getSimpleName=lambda: name))
        self.assertIsInstance(nt._python_error(java('ConnectionNotFoundException')), nt.ConnectionNotFound)
        self.assertIsInstance(nt._python_error(java('SdpParseException')), nt.SdpParseException)
        self.assertIsInstance(nt._python_error(java('TelegramServerErrorException')), nt.TelegramServerError)
        other = java('IllegalStateException')
        self.assertIs(nt._python_error(other), other)

    def test_pytgcalls_imports_on_the_android_layer(self):
        if not (SRC / 'pytgcalls').exists():
            self.skipTest('tools/sync_core.sh has not copied PyTgCalls')
        script = ('import sys\nsys.modules.pop("ntgcalls", None)\n'
                  'from tg_ascii_mobile import ntgcalls_android as n\nn.install()\n'
                  'import ntgcalls, pytgcalls\nassert ntgcalls is n\n'
                  'from pytgcalls.types.raw import Stream, AudioStream, AudioParameters\n'
                  's = Stream(microphone=AudioStream(n.MediaSource.DEVICE, "", AudioParameters(48000, 1)))\n'
                  'print(type(s).__name__)')
        result = subprocess.run([sys.executable, '-c', script], cwd=SRC, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])


    def test_group_audio_service_uses_playback_only_for_viewers(self):
        script = """
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from tg_ascii_mobile.android_group_calls import AndroidGroupCallManager, AndroidGroupMediaEngine, GroupMediaEngine

async def verify():
    core = SimpleNamespace(native_call_media_start=AsyncMock(), native_call_media_end=Mock())
    manager = AndroidGroupCallManager(None, core=core)
    manager._call = SimpleNamespace(token='group', video=True)
    with patch.object(AndroidGroupMediaEngine, 'proxy_factory', Mock()):
        engine = manager.media_engine(None, 1, None, None, None)
    with patch.object(GroupMediaEngine, 'initialize', new_callable=AsyncMock) as initialize:
        for view_only in (True, False):
            engine.view_only = view_only
            await engine.initialize()
            core.native_call_media_start.assert_awaited_with('group', not view_only, False, not view_only)
        assert initialize.await_count == 2

asyncio.run(verify())
"""
        result = subprocess.run([sys.executable, '-c', script], cwd=SRC, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])


class MobileGroupCallTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.core = Core(Path(folder.name), 'Android')
        self.addCleanup(self.core.loop.close)

    async def test_outdated_group_control_is_rejected(self):
        manager = SimpleNamespace(snapshot={'token': 'new', 'peer': -100, 'state': 'active'}, mute=AsyncMock(),
                                  conference=False, can_manage=False)
        self.core.group_call_manager = manager
        self.core.enable_group_call_manager = AsyncMock(return_value=manager)
        with self.assertRaises(ValueError):
            await self.core.api_group_call_action('mute', token='old', value=True)
        manager.mute.assert_not_called()
        await self.core.api_group_call_action('mute', token='new', value=True)
        manager.mute.assert_awaited_once_with(True, token='new')

    async def test_group_call_waits_for_an_individual_call_to_end(self):
        manager = SimpleNamespace(snapshot={'token': '', 'state': 'idle'}, start=AsyncMock(),
                                  conference=False, can_manage=False)
        self.core.enable_group_call_manager = AsyncMock(return_value=manager)
        self.core.call_manager = SimpleNamespace(snapshot={'state': 'active'})
        with self.assertRaises(ValueError):
            await self.core.api_group_call_action('join', peer=-100)
        manager.start.assert_not_called()


class EnginePoolTests(TestCase):
    def setUp(self):
        self.addCleanup(lambda: (nt._idle.clear(), nt._kept.clear()))
        nt._idle.clear(); nt._kept.clear()

    def test_stopped_engines_are_reused_and_failed_ones_kept_alive(self):
        first, broken = object(), object()
        nt.release_engine(first)
        nt.release_engine(first)
        nt.release_engine(broken, clean=False)
        self.assertEqual(nt._idle, [first])
        self.assertEqual(nt._kept, [broken])
        self.assertIs(nt.acquire_engine(), first)
        self.assertEqual(nt._kept, [broken])
