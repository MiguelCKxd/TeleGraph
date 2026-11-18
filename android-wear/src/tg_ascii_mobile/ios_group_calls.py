"""iOS group and conference calls on the embedded NTgCalls Python binding."""
import asyncio
from functools import partial
from importlib import machinery, util
import inspect
import sys
from threading import Lock
import time
import weakref

from tg_ascii.calls_group import GroupCallManager
from tg_ascii.calls_group_media import GroupMediaEngine
from tg_ascii.calls_group_native import GroupNativeProxy
from tg_ascii.calls_rpc_codec import EVENTS, encode

from .ios_calls import devices, load_library
from .pytgcalls_dependencies import install_pytgcalls_dependencies


def load_binding(path):
    """Load the signed framework under the module name expected by PyTgCalls."""
    name = 'ntgcalls'
    module = sys.modules.get(name)
    if module is None:
        loader = machinery.ExtensionFileLoader(name, str(path))
        spec = util.spec_from_loader(name, loader)
        module = util.module_from_spec(spec)
        loader.exec_module(module)
        sys.modules[name] = module
    if module.__version__ != '3.0.5+tgascii.volume1':
        raise ValueError('Incompatible native group engine')
    return module


class IOSGroupProxy(GroupNativeProxy):
    def __init__(self, failed, *, binding):
        super().__init__(failed)
        self._module = binding
        self._binding = binding.NTgCalls()
        self._loop = asyncio.get_running_loop()
        self._last_frame = {}
        self._frame_lock = Lock()
        self._requests = set()
        self._cleanup = None
        proxy = weakref.ref(self)

        def receive(name, *values):
            target = proxy()
            if target is not None:
                target._from_native(name, *values)

        for name in EVENTS:
            getattr(self._binding, name)(partial(receive, name))

    def _from_native(self, name, *values):
        if self._closing:
            return
        if name == 'on_frames':
            peer, mode, device, batch = values
            nt = self._module
            if device not in (nt.StreamDevice.CAMERA, nt.StreamDevice.SCREEN) or not batch:
                return
            latest = {frame.ssrc: frame for frame in batch}
            now = time.monotonic()
            selected = []
            with self._frame_lock:
                for ssrc, frame in latest.items():
                    slot = (peer, mode.value, device.value, ssrc)
                    if now - self._last_frame.get(slot, float('-inf')) < .15:
                        continue
                    if len(self._last_frame) >= 64 and slot not in self._last_frame:
                        self._last_frame.pop(next(iter(self._last_frame)))
                    self._last_frame[slot] = now
                    selected.append(frame)
            if not selected:
                return
            values = (peer, mode, device, selected)
        try:
            self._loop.call_soon_threadsafe(self._deliver, name, values)
        except RuntimeError:
            pass  # The loop is closing.

    def _deliver(self, name, values):
        if not self._closing:
            self._native_event(name, encode(values))

    async def native_request(self, name, args):
        if self._closing:
            raise self._module.ConnectionNotFound('Call engine is closed')
        binding = self._binding
        result = getattr(binding, name)(*args)
        if not inspect.isawaitable(result):
            return result
        future = asyncio.ensure_future(result)
        self._requests.add(future)

        # The generated native executor borrows the engine until the method returns.
        def completed(task, keep_alive=binding):
            self._requests.discard(task)
            if not task.cancelled():
                task.exception()
        future.add_done_callback(completed)
        return await asyncio.shield(future)

    async def close(self):
        if self._cleanup is None:
            self._closing = True
            for task in tuple(self._native_tasks):
                task.cancel()
            self._native_tasks.clear()
            binding, self._binding = self._binding, None
            self._cleanup = asyncio.create_task(self._close_binding(binding))
            self._cleanup.add_done_callback(
                lambda task: task.exception() if not task.cancelled() else None)
        await asyncio.shield(self._cleanup)

    async def _close_binding(self, binding):
        if self._requests:
            await asyncio.gather(*tuple(self._requests), return_exceptions=True)
        for peer in await binding.calls():
            try:
                await binding.stop(peer)
            except self._module.ConnectionNotFound:
                pass


def install(app, path, permission, audio_session, capture_screen=None):
    from .ios_screen_share import FPS, SCREEN, ScreenShare

    binding = load_binding(path)
    install_pytgcalls_dependencies()

    class Engine(GroupMediaEngine):
        proxy_factory = staticmethod(partial(IOSGroupProxy, binding=binding))
        required_version = None
        supports_participant_volume = True

        def __init__(self, *args):
            super().__init__(*args)
            self.audio_active = False

        async def initialize(self):
            # The shared initializer imports PyTgCalls on the Telegram loop.
            # Its sync wrappers bind to the event loop present at import time.
            audio_session(True)
            self.audio_active = True
            await super().initialize()

        @staticmethod
        async def devices():
            result = await asyncio.to_thread(devices, load_library(path))
            for kind in ('microphone', 'speaker'):
                if not result[kind]:
                    result[kind] = [{'id': '', 'name': kind}]
            result['screen'] = [SCREEN] if capture_screen is not None else []
            return result

        @staticmethod
        async def media_access(video):
            await permission(bool(video))

        async def stream(self, selected, video):
            native_selection = {key: value for key, value in selected.items() if key != 'screen'}
            stream, speaker = await super().stream(native_selection, video)
            if selected.get('screen'):
                from pytgcalls.types.raw import VideoParameters, VideoStream
                stream.screen = VideoStream(binding.MediaSource.EXTERNAL, '', VideoParameters(1280, 720, FPS))
            return stream, speaker

        async def send_screen_frame(self, peer, data, timestamp, rotation, width, height):
            frame = binding.FrameData(timestamp, binding.VideoRotation(rotation), width, height)
            await self.proxy.native_request('send_external_frame', (peer, binding.StreamDevice.SCREEN, data, frame))

        @staticmethod
        async def camera_format(_ident):
            return 640, 480, 24

        async def stop(self, peer):
            try:
                await super().stop(peer)
            finally:
                if self.audio_active:
                    self.audio_active = False
                    await asyncio.to_thread(audio_session, False)

    class Manager(GroupCallManager):
        media_engine = Engine
        video_grid = True

        async def _media_access(self, video):
            await permission(bool(video))

    if capture_screen is not None:
        class ScreenManager(ScreenShare, Manager):
            screen_capture = capture_screen

        Manager = ScreenManager
    app.core.native_group_call_manager = Manager
