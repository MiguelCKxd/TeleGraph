"""Group voice/video chats and conferences on Android.

The desktop's group call manager (tg_ascii.calls_group) and media engine
(tg_ascii.calls_group_media, on PyTgCalls 3.0.0) run unchanged; only the
native layer differs. The desktop runs NTgCalls in a helper process and talks
to it through GroupNativeProxy; here the same proxy calls the NTgCalls Android
library in process, through the ntgcalls API of ntgcalls_android.
"""
import asyncio
import json
import logging

from . import ntgcalls_android
from .android_calls import CallMedia
from .android_screen_share import ScreenShare, screen_devices

# Method names, error types and connection modes only: never keys or payloads.
log = logging.getLogger('tg_ascii.calls')

ntgcalls_android.install()

from tg_ascii.calls_group import GroupCallManager  # noqa: E402
from tg_ascii.calls_group_media import GroupMediaEngine  # noqa: E402
from tg_ascii.calls_group_native import GroupNativeProxy  # noqa: E402
from tg_ascii.calls_rpc_codec import EVENTS  # noqa: E402

_permission = None


class AndroidGroupProxy(GroupNativeProxy):
    def __init__(self, failed=lambda *_: None):
        super().__init__(failed)
        self._loop = asyncio.get_running_loop()
        self._binding = ntgcalls_android.NTgCalls()
        for name in EVENTS:
            getattr(self._binding, name)(lambda *values, name=name: self._from_native(name, values))

    def _from_native(self, name, values):
        try:
            self._loop.call_soon_threadsafe(self._deliver, name, values)
        except RuntimeError:
            pass  # The loop is closing.

    def _deliver(self, name, values):
        if self._closing:
            return
        callback = self._native_callbacks.get(name)
        if callback is None:
            return
        result = callback(*values)
        if hasattr(result, 'add_done_callback'):
            self._native_tasks.add(result)

            def completed(future):
                self._native_tasks.discard(future)
                if not future.cancelled():
                    future.exception()
            result.add_done_callback(completed)

    async def native_request(self, name, args):
        if self._closing and name != 'stop':
            raise ntgcalls_android.ConnectionNotFound('Call engine is closed')
        if name == 'connect':
            try:
                payload = json.loads(args[1])
                log.info('group connect: presentation=%s keys=%s', bool(args[2]) if len(args) > 2 else False,
                         sorted(payload)[:12] if isinstance(payload, dict) else type(payload).__name__)
            except Exception:
                log.info('group connect: params are not JSON')
        try:
            return await getattr(self._binding, name)(*args)
        except Exception as error:
            log.info('group native %s failed: %s', name, type(error).__name__)
            raise

    async def close(self):
        if self._closing and self._binding is None:
            return
        self._closing = True
        for future in tuple(self._native_tasks):
            future.cancel()
        self._native_tasks.clear()
        binding, self._binding = self._binding, None
        if binding is None:
            return
        clean = True
        try:
            # Like the desktop helper's shutdown: no native call outlives the proxy.
            for key in list(await asyncio.wait_for(binding.calls(), 3)):
                try:
                    await asyncio.wait_for(binding.stop(key), 3)
                except ntgcalls_android.ConnectionNotFound:
                    pass
                except Exception:
                    clean = False
        except Exception:
            clean = False
        finally:
            binding.close(clean)


class AndroidGroupMediaEngine(GroupMediaEngine):
    proxy_factory = AndroidGroupProxy
    required_version = None  # PyTgCalls is bundled from the desktop build, not installed by pip.
    @property
    def supports_participant_volume(self):
        return self.proxy._binding.supports_source_volume

    def __init__(self, *args, prepare_media=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.prepare_media = prepare_media

    async def initialize(self):
        if self.prepare_media is not None:
            await self.prepare_media(microphone=not self.view_only)
        await super().initialize()

    @staticmethod
    async def devices():
        from .android_calls import device_list
        devices = await asyncio.to_thread(device_list)
        # The system picks the route when no device is named (as for 1:1 calls).
        for kind in ('microphone', 'speaker'):
            if not devices.get(kind):
                devices[kind] = [{'id': '', 'name': kind}]
        devices['screen'] = screen_devices()
        return devices

    @staticmethod
    async def media_access(video):
        if _permission is not None:
            await _permission(bool(video))

    @staticmethod
    async def camera_format(ident):
        return 640, 480, 24


class AndroidGroupCallManager(CallMedia, ScreenShare, GroupCallManager):
    video_grid = True

    def media_engine(self, *args):
        call = self._call

        async def prepare_media(*, microphone):
            await self._start_call_media(call.token, microphone=microphone, camera=microphone and call.video)

        return AndroidGroupMediaEngine(*args, prepare_media=prepare_media)

    async def _finish(self, call, error='', *, discard=False):
        if self._call is call:
            with self._frame_lock:
                self._tiles.clear()
                self._tile_seen.clear()
        await super()._finish(call, error, discard=discard)

    async def _media_access(self, video):
        await AndroidGroupMediaEngine.media_access(video)


def install(permission):
    global _permission
    _permission = permission
