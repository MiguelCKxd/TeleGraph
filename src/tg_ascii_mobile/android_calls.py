"""NTgCalls Android AAR adapter for the shared Telegram call state machine."""
import asyncio
import base64
import io
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from types import SimpleNamespace

from tg_ascii.calls import CallManager
from .android_screen_share import ScreenShare

SDK = 'io.github.pytgcalls.'


def sdk_class(name):
    from java import jclass

    return jclass(SDK + name)


@lru_cache(maxsize=1)
def available():
    try:
        return bool(sdk_class('NTgCalls').getProtocol().library_versions.size())
    except Exception:
        return False


def device_list():
    devices = sdk_class('NTgCalls').getMediaDevices()
    return {kind: [{'id': device.metadata, 'name': device.name}
                   for device in getattr(devices, kind).toArray()]
            for kind in ('microphone', 'speaker', 'camera')}


class AndroidCallEngine:
    uses_hardware = True

    def __init__(self, on_state, on_signaling, on_frames, on_emojis):
        from java import jclass

        self.on_state = on_state
        self.on_signaling = on_signaling
        self.on_frames = on_frames
        self.on_emojis = on_emojis
        from .ntgcalls_android import acquire_engine
        self.binding = acquire_engine()  # pooled: see ntgcalls_android.release_engine
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='TeleGraphCall')
        self.callbacks = jclass('org.tgas.calls.CallCallbacks')(self)
        bind = self.binding
        for setter in (bind.onConnectionChange, bind.onSignalingData, bind.onUpdateEmojis,
                       bind.onRemoteSourceChange, bind.onFrames):
            setter(self.callbacks)

    def connection_changed(self, peer, info):
        self.on_state(peer, info.state.name())

    def signaling_received(self, peer, data):
        self.on_signaling(peer, bytes(data))

    def emojis_received(self, peer, emojis):
        self.on_emojis(peer, emojis)

    def remote_source_changed(self, peer, source):
        self.on_state(peer, 'REMOTE_' + source.device.name() + '_' + source.state.name())

    def frames_received(self, peer, mode, device, frames):
        if device.name() != 'CAMERA' or frames.isEmpty():
            return
        frame = frames.get(frames.size() - 1)
        info = frame.frame_data
        rotation = int(info.rotation.name().rsplit('_', 1)[-1])
        # The shared manager copies a bounded I420 frame if the UI needs it.
        self.on_frames(peer, mode.name(), 'CAMERA',
                       [SimpleNamespace(data=frame.data, frame_data=SimpleNamespace(
                           width=info.width, height=info.height, rotation=rotation))])

    async def run(self, method, *args):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.worker, method, *args)

    @staticmethod
    async def devices():
        from .android_screen_share import screen_devices

        devices = await asyncio.to_thread(device_list)
        devices['screen'] = screen_devices()
        return devices

    def protocol(self):
        from telethon.tl.types import PhoneCallProtocol

        protocol = self.binding.getProtocol()
        return PhoneCallProtocol(min_layer=protocol.min_layer, max_layer=protocol.max_layer,
                                 udp_p2p=protocol.udp_p2p, udp_reflector=protocol.udp_reflector,
                                 library_versions=list(protocol.library_versions.toArray()))

    async def create(self, peer, dh, ga_hash=None):
        config = sdk_class('p2p.DhConfig')(dh.g, bytes(dh.p), bytes(dh.random))

        def create_native():
            self.binding.createP2pCall(peer)
            return bytes(self.binding.initExchange(peer, config, ga_hash))

        return await self.run(create_native)

    async def exchange(self, peer, ga, fingerprint=0):
        exchanged = await self.run(self.binding.exchangeKeys, peer, ga, fingerprint)
        return SimpleNamespace(g_a_or_b=bytes(exchanged.g_a_or_b or b''), key_fingerprint=exchanged.key_fingerprint)

    async def connect(self, peer, call):
        from java.util import ArrayList

        protocol = call.protocol.library_versions
        if not set(protocol).intersection(self.protocol().library_versions):
            raise ValueError('No compatible call transport')
        servers, versions = ArrayList(), ArrayList()
        for version in protocol:
            versions.add(version)
        server = sdk_class('p2p.RTCServer')
        for item in call.connections:
            modern = type(item).__name__ == 'PhoneConnectionWebrtc'
            servers.add(server(item.id, item.ip, item.ipv6, item.port,
                               getattr(item, 'username', None), getattr(item, 'password', None),
                               bool(item.turn) if modern else True, bool(item.stun) if modern else False,
                               False if modern else bool(item.tcp), None if modern else item.peer_tag))
        if servers.isEmpty():
            raise ValueError('No compatible call transport')
        custom = getattr(getattr(call, 'custom_parameters', None), 'data', None)
        await self.run(self.binding.connectP2p, peer, servers, versions, bool(call.p2p_allowed), custom)

    async def media(self, peer, selected, video, muted=False):
        devices = await self.devices()
        media_source = sdk_class('media.MediaSource')
        audio = sdk_class('media.AudioDescription')
        video_description = sdk_class('media.VideoDescription')
        description = sdk_class('media.MediaDescription')
        mode = sdk_class('media.StreamMode')

        def chosen(kind):
            options = devices[kind]
            default = options[0]['id'] if options else ''
            return selected.get(kind) or default

        microphone = audio(media_source.DEVICE, 48000, 1, chosen('microphone'), False)
        speaker = audio(media_source.DEVICE, 48000, 1, chosen('speaker'), False)
        camera = None
        if selected.get('screen'):
            camera = video_description(media_source.DESKTOP, 1280, 720, 15, selected['screen'], False)
        elif video:
            camera = video_description(media_source.DEVICE, 640, 480, 24, chosen('camera'), False)
        remote_video = video_description(media_source.EXTERNAL, -1, -1, 0, '', False)

        def setup():
            self.binding.setStreamSources(peer, mode.PLAYBACK, description(speaker, None, remote_video, None))
            self.binding.setStreamSources(peer, mode.CAPTURE, description(microphone, None, camera, None))
            (self.binding.mute if muted else self.binding.unmute)(peer)

        await self.run(setup)

    async def mute(self, peer, value):
        await self.run(self.binding.mute if value else self.binding.unmute, peer)

    async def signal(self, peer, data):
        await self.run(self.binding.sendSignalingData, peer, data)

    async def stop(self, peer):
        clean = False
        try:
            await self.run(self.binding.stop, peer)
            clean = True
        except sdk_class('exceptions.ConnectionNotFoundException'):
            clean = True
        finally:
            from .ntgcalls_android import release_engine
            self.callbacks.close()
            binding, self.binding = self.binding, None
            self.worker.submit(release_engine, binding, clean)
            self.worker.shutdown(wait=False, cancel_futures=False)


def frame_jpeg_bytes(frame, size=480):
    from PIL import Image

    width, height, data = frame['width'], frame['height'], frame['data']
    chroma = (width + 1) // 2, (height + 1) // 2
    luma_size, chroma_size = width * height, chroma[0] * chroma[1]
    y = Image.frombytes('L', (width, height), data[:luma_size])
    cb = Image.frombytes('L', chroma, data[luma_size:luma_size + chroma_size]).resize(y.size)
    cr = Image.frombytes('L', chroma, data[luma_size + chroma_size:]).resize(y.size)
    image = Image.merge('YCbCr', (y, cb, cr)).convert('RGB')
    image.thumbnail((size, size))
    if frame['rotation']:
        image = image.rotate(-frame['rotation'], expand=True)
    output = io.BytesIO()
    image.save(output, 'JPEG', quality=72)
    return output.getvalue()


def frame_jpeg(frame, size=480):
    return base64.b64encode(frame_jpeg_bytes(frame, size)).decode('ascii')



class CallMedia:
    def __init__(self, *args, core, **kwargs):
        super().__init__(*args, **kwargs)
        self.core = core
        self._media_token = None
        self._media_mode_lock = asyncio.Lock()

    async def _start_call_media(self, token, *, microphone, phone_call=False, camera=False):
        if self.core.native_call_media_start is not None:
            self._media_token = token
            await self.core.native_call_media_start(token, microphone, phone_call, camera)

    async def _set_camera_service(self, token, enabled):
        if token == self._media_token and self.core.native_call_media_camera is not None:
            await self.core.native_call_media_camera(token, enabled)

    async def set_camera(self, value, *, token=None):
        async with self._media_mode_lock:
            call = self._check(token=token)
            token = call.token
            try:
                if value and not call.video:
                    await self._set_camera_service(token, True)
                await super().set_camera(value, token=token)
            finally:
                if not call.video:
                    await self._set_camera_service(token, False)

    async def set_screen(self, source='', *, token=None):
        async with self._media_mode_lock:
            call = self._check(token=token)
            was_video = call.video
            await super().set_screen(source, token=call.token)
            if was_video and not call.video:
                await self._set_camera_service(call.token, False)

    async def _finish(self, call, error='', *, discard=False):
        try:
            await super()._finish(call, error, discard=discard)
        finally:
            if self._media_token == call.token:
                self._media_token = None
                self.core.native_call_media_end(call.token)

class AndroidCallManager(CallMedia, ScreenShare, CallManager):
    async def _prepare(self, call):
        authorize = self.core.native_telecom_outgoing
        if not call.incoming and authorize is not None:
            token = call.token

            def disconnect():
                if self._call is call:
                    self._schedule(self.hangup(token=token))

            await authorize(token, disconnect)
            if self._call is not call or self.core.locked:
                from tg_ascii.i18n import tr
                raise ValueError(tr('This call is no longer active'))
        await self._start_call_media(call.token, microphone=True, phone_call=True, camera=call.video)
        return await super()._prepare(call)



def install(app, activity):
    from java import jclass
    from tg_ascii.i18n import tr

    jclass('org.webrtc.ContextUtils').initialize(activity.getApplicationContext())

    async def permission(video):
        required = ['android.permission.RECORD_AUDIO']
        if video:
            required.append('android.permission.CAMERA')
        missing = [name for name in required if activity.checkSelfPermission(name) != 0]
        if not missing:
            return
        app.loop.call_soon_threadsafe(lambda: activity.requestPermissions(missing, 7354))
        loop = asyncio.get_running_loop()
        started, dialog = loop.time(), False
        while loop.time() - started < 90:
            await asyncio.sleep(.2)
            if all(activity.checkSelfPermission(name) == 0 for name in missing):
                return
            if not activity.hasWindowFocus():
                dialog = True
            elif dialog or loop.time() - started > 5:
                break
        raise PermissionError(tr('Camera or microphone access was not granted.'))

    service = jclass('org.tgas.calls.CallMediaService')
    context = activity.getApplicationContext()

    async def start_media(token, microphone, phone_call, camera):
        loop = asyncio.get_running_loop()
        started = loop.create_future()

        def deliver(result=None, error=None):
            if started.done():
                return
            if error is not None:
                started.set_exception(error)
            else:
                started.set_result(result)

        def start():
            if started.done():
                return
            try:
                future = service.begin(context, token, tr('Call'), microphone, phone_call, camera)
            except Exception as error:
                loop.call_soon_threadsafe(deliver, None, error)
                return
            loop.call_soon_threadsafe(deliver, future)

        app.loop.call_soon_threadsafe(start)
        future = await asyncio.wait_for(started, 5)
        unit = jclass('java.util.concurrent.TimeUnit')
        if not await asyncio.to_thread(future.get, 6, unit.SECONDS):
            raise ValueError(tr('Calls are unavailable on this device.'))

    async def camera_media(token, enabled):
        loop = asyncio.get_running_loop()
        result = loop.create_future()

        def deliver(allowed, error):
            if result.done():
                return
            if error:
                result.set_exception(error)
            else:
                result.set_result(allowed)

        def update():
            if result.done():
                return
            try:
                allowed = service.setCamera(token, enabled)
            except Exception as error:
                loop.call_soon_threadsafe(deliver, False, error)
            else:
                loop.call_soon_threadsafe(deliver, allowed, None)

        app.loop.call_soon_threadsafe(update)
        if not await asyncio.wait_for(result, 5) and enabled:
            raise ValueError(tr('Calls are unavailable on this device.'))

    def end_media(token):
        app.loop.call_soon_threadsafe(service.end, context, token)

    app.core.native_call_media_start = start_media
    app.core.native_call_media_end = end_media
    app.core.native_call_media_camera = camera_media
    app.core.native_call_manager = lambda *args, **kwargs: AndroidCallManager(*args, core=app.core, **kwargs)
    app.core.native_call_engine = AndroidCallEngine
    app.core.native_call_available = available
    from .call_pip import install_android
    install_android(app, activity)
    app.core.native_call_permission = permission
    asyncio.run_coroutine_threadsafe(app.core.enable_call_manager(), app.core.loop)
