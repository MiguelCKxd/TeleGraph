"""Individual calls on iOS using the NTgCalls 3.0.5 C ABI."""
import asyncio
import ctypes as C
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

from telethon.tl.types import PhoneCallProtocol, PhoneConnectionWebrtc


class DhConfig(C.Structure):
    _fields_ = [('g', C.c_int32), ('p', C.c_char_p), ('p_len', C.c_size_t),
                ('random', C.c_char_p), ('random_len', C.c_size_t)]


class Auth(C.Structure):
    _fields_ = [('key_fingerprint', C.c_int64), ('g_a_or_b', C.c_void_p), ('length', C.c_size_t)]


class Protocol(C.Structure):
    _fields_ = [('min_layer', C.c_int32), ('max_layer', C.c_int32), ('udp_p2p', C.c_bool),
                ('udp_reflector', C.c_bool), ('versions', C.POINTER(C.c_char_p)), ('length', C.c_size_t)]


class Server(C.Structure):
    _fields_ = [('id', C.c_uint64), ('ipv4', C.c_char_p), ('ipv6', C.c_char_p), ('port', C.c_uint16),
                ('username', C.c_char_p), ('password', C.c_char_p), ('turn', C.c_bool), ('stun', C.c_bool),
                ('tcp', C.c_bool), ('peer_tag', C.c_char_p), ('peer_tag_len', C.c_size_t)]


class Device(C.Structure):
    _fields_ = [('name', C.c_char_p), ('metadata', C.c_char_p)]


DEVICE_KINDS = ('microphone', 'speaker', 'camera', 'screen')


class Devices(C.Structure):
    _fields_ = [entry for name in DEVICE_KINDS
                for entry in ((name, C.POINTER(Device)), (name + '_len', C.c_size_t))]


class Audio(C.Structure):
    _fields_ = [('source', C.c_int), ('rate', C.c_uint32), ('channels', C.c_uint8),
                ('input', C.c_char_p), ('keep_open', C.c_bool)]


class Video(C.Structure):
    _fields_ = [('source', C.c_int), ('width', C.c_int16), ('height', C.c_int16),
                ('fps', C.c_uint8), ('input', C.c_char_p), ('keep_open', C.c_bool)]


class Media(C.Structure):
    _fields_ = [('microphone', C.POINTER(Audio)), ('speaker', C.POINTER(Audio)),
                ('camera', C.POINTER(Video)), ('screen', C.POINTER(Video))]


class Connection(C.Structure):
    _fields_ = [('state', C.c_int), ('kind', C.c_int)]


class RemoteSource(C.Structure):
    _fields_ = [('ssrc', C.c_uint32), ('state', C.c_int), ('device', C.c_int)]


class FrameData(C.Structure):
    _fields_ = [('timestamp', C.c_int64), ('rotation', C.c_int), ('width', C.c_uint16), ('height', C.c_uint16)]


class Frame(C.Structure):
    _fields_ = [('ssrc', C.c_int64), ('data', C.c_void_p), ('length', C.c_size_t), ('info', FrameData)]


H = C.c_void_p
ID = C.c_int64
SIZE = C.c_size_t
CONNECTION = C.CFUNCTYPE(None, H, ID, Connection, H)
SIGNAL = C.CFUNCTYPE(None, H, ID, H, SIZE, H)
REMOTE = C.CFUNCTYPE(None, H, ID, RemoteSource, H)
FRAMES = C.CFUNCTYPE(None, H, ID, C.c_int, C.c_int, C.POINTER(Frame), SIZE, H)
EMOJIS = C.CFUNCTYPE(None, H, ID, C.c_char_p, H)

STATE_NAMES = ('CONNECTING', 'CONNECTED', 'FAILED', 'TIMEOUT', 'CLOSED')
SOURCE_STATES = ('ACTIVE', 'PAUSED', 'IDLING')
DEVICE_SOURCE, EXTERNAL_SOURCE = 4, 6  # C enums use ordinals, unlike the Python extension.
CAPTURE, PLAYBACK, CAMERA = 0, 1, 2
CONNECTION_NOT_FOUND = -201


@lru_cache(maxsize=1)
def load_library(path):
    lib = C.CDLL(str(path))
    signatures = {
        'instance_create': (H, ()),
        'instance_destroy': (None, (H,)),
        'get_version': (C.c_char_p, ()),
        'get_protocol': (C.c_int, (C.POINTER(Protocol),)),
        'protocol_free': (None, (C.POINTER(Protocol),)),
        'get_media_devices': (C.c_int, (C.POINTER(Devices),)),
        'media_devices_free': (None, (C.POINTER(Devices),)),
        'create_p2p_call': (C.c_int, (H, ID)),
        'init_exchange': (C.c_int, (H, ID, DhConfig, C.c_char_p, SIZE, C.POINTER(H), C.POINTER(SIZE))),
        'bytes_free': (None, (H,)),
        'exchange_keys': (C.c_int, (H, ID, C.c_char_p, SIZE, ID, C.POINTER(Auth))),
        'auth_params_free': (None, (C.POINTER(Auth),)),
        'connect_p2p': (C.c_int, (H, ID, C.POINTER(Server), SIZE, C.POINTER(C.c_char_p), SIZE,
                                 C.c_bool, C.c_char_p)),
        'set_stream_sources': (C.c_int, (H, ID, C.c_int, Media)),
        'mute': (C.c_int, (H, ID, C.POINTER(C.c_bool))),
        'unmute': (C.c_int, (H, ID, C.POINTER(C.c_bool))),
        'send_external_frame': (C.c_int, (H, ID, C.c_int, C.c_char_p, SIZE, FrameData)),
        'send_signaling_data': (C.c_int, (H, ID, C.c_char_p, SIZE)),
        'stop': (C.c_int, (H, ID)),
        'on_connection_change_callback': (C.c_int, (H, CONNECTION, H)),
        'on_signaling_data_callback': (C.c_int, (H, SIGNAL, H)),
        'on_remote_source_change_callback': (C.c_int, (H, REMOTE, H)),
        'on_frames_callback': (C.c_int, (H, FRAMES, H)),
        'on_update_emojis_callback': (C.c_int, (H, EMOJIS, H)),
    }
    for name, (result, arguments) in signatures.items():
        function = getattr(lib, 'ntg_' + name)
        function.restype, function.argtypes = result, arguments
    if not (lib.ntg_get_version() or b'').startswith(b'3.0.5'):
        raise ValueError('Incompatible NTgCalls C ABI')
    return lib


def checked(result):
    if result:
        raise RuntimeError(f'NTgCalls ({result})')


def text(value):
    return (value or b'').decode('utf-8', 'replace')


def protocol(lib):
    result = Protocol()
    try:
        checked(lib.ntg_get_protocol(C.byref(result)))
        return PhoneCallProtocol(min_layer=result.min_layer, max_layer=result.max_layer,
                                 udp_p2p=result.udp_p2p, udp_reflector=result.udp_reflector,
                                 library_versions=[text(result.versions[i]) for i in range(result.length)])
    finally:
        lib.ntg_protocol_free(C.byref(result))


def devices(lib):
    result = Devices()
    try:
        checked(lib.ntg_get_media_devices(C.byref(result)))
        return {name: [{'id': text(device.metadata), 'name': text(device.name)}
                       for device in getattr(result, name)[:getattr(result, name + '_len')]]
                if getattr(result, name + '_len') else [] for name in DEVICE_KINDS}
    finally:
        lib.ntg_media_devices_free(C.byref(result))


class IOSCallEngine:
    uses_hardware = True

    def __init__(self, on_state, on_signaling, on_frames, on_emojis, *, lib, audio_session):
        self.lib, self.audio_session = lib, audio_session
        self.audio_active = False
        self.handle = lib.ntg_instance_create()
        if not self.handle:
            raise RuntimeError('NTgCalls instance could not be created')

        def connected(_handle, peer, info, _data):
            if info.kind == 0 and 0 <= info.state < len(STATE_NAMES):
                on_state(peer, STATE_NAMES[info.state])

        def signal(_handle, peer, payload, length, _data):
            if 0 < length <= 262144 and payload:
                on_signaling(peer, C.string_at(payload, length))

        def remote(_handle, peer, info, _data):
            if info.device in (0, CAMERA) and 0 <= info.state < len(SOURCE_STATES):
                on_state(peer, 'REMOTE_' + DEVICE_KINDS[info.device].upper() + '_' + SOURCE_STATES[info.state])

        def frames(_handle, peer, mode, device, items, length, _data):
            if device != CAMERA or mode not in (CAPTURE, PLAYBACK) or not items or not length:
                return
            last = items[length - 1]
            info = last.info
            w, h = info.width, info.height
            expected = w * h + 2 * ((w + 1) // 2) * ((h + 1) // 2)
            if not last.data or not (0 < w <= 4096 and 0 < h <= 4096 and last.length == expected):
                return
            value = SimpleNamespace(width=w, height=h, rotation=info.rotation * 90)
            on_frames(peer, 'CAPTURE' if mode == CAPTURE else 'PLAYBACK', 'CAMERA',
                      [SimpleNamespace(data=C.string_at(last.data, expected), frame_data=value)])

        self.callbacks = (CONNECTION(connected), SIGNAL(signal), REMOTE(remote), FRAMES(frames),
                          EMOJIS(lambda _, peer, value, data: on_emojis(peer, text(value))))
        try:
            for register, callback in zip((lib.ntg_on_connection_change_callback, lib.ntg_on_signaling_data_callback,
                                           lib.ntg_on_remote_source_change_callback, lib.ntg_on_frames_callback,
                                           lib.ntg_on_update_emojis_callback), self.callbacks):
                checked(register(self.handle, callback, None))
        except Exception:
            lib.ntg_instance_destroy(self.handle)
            raise
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='TeleGraphCall')

    async def run(self, method, *args):
        return await asyncio.get_running_loop().run_in_executor(self.worker, method, *args)

    def protocol(self):
        return protocol(self.lib)

    async def create(self, peer, dh, ga_hash=None):
        def native():
            checked(self.lib.ntg_create_p2p_call(self.handle, peer))
            config = DhConfig(dh.g, bytes(dh.p), len(dh.p), bytes(dh.random), len(dh.random))
            data, length = H(), SIZE()
            try:
                checked(self.lib.ntg_init_exchange(self.handle, peer, config, ga_hash, len(ga_hash or b''),
                                                   C.byref(data), C.byref(length)))
                return C.string_at(data, length.value)
            finally:
                self.lib.ntg_bytes_free(data)
        return await self.run(native)

    async def exchange(self, peer, ga, fingerprint=0):
        def native():
            result = Auth()
            try:
                checked(self.lib.ntg_exchange_keys(self.handle, peer, ga, len(ga), fingerprint, C.byref(result)))
                return SimpleNamespace(g_a_or_b=C.string_at(result.g_a_or_b, result.length),
                                       key_fingerprint=result.key_fingerprint)
            finally:
                self.lib.ntg_auth_params_free(C.byref(result))
        return await self.run(native)

    async def connect(self, peer, call):
        versions = call.protocol.library_versions
        if not call.connections or not set(versions).intersection(self.protocol().library_versions):
            raise ValueError('No compatible call transport')
        rows = []
        for item in call.connections:
            modern = isinstance(item, PhoneConnectionWebrtc)
            tag = b'' if modern else bytes(item.peer_tag or b'')
            rows.append(Server(item.id, item.ip.encode(), item.ipv6.encode(), item.port,
                               item.username.encode() if modern else None, item.password.encode() if modern else None,
                               bool(item.turn) if modern else True, bool(item.stun) if modern else False,
                               False if modern else bool(item.tcp), tag or None, len(tag)))
        servers = (Server * len(rows))(*rows)
        offered = (C.c_char_p * len(versions))(*(version.encode() for version in versions))
        custom = getattr(getattr(call, 'custom_parameters', None), 'data', None)
        checked(await self.run(self.lib.ntg_connect_p2p, self.handle, peer, servers, len(rows),
                               offered, len(versions), bool(call.p2p_allowed), custom.encode() if custom else None))

    async def media(self, peer, selected, video, muted=False):
        def native():
            if not self.audio_active:
                self.audio_session(True)
                self.audio_active = True
            listing = devices(self.lib)

            def device(name):
                options = listing[name]
                return (selected.get(name) or (options[0]['id'] if options else '')).encode()

            mic = Audio(DEVICE_SOURCE, 48000, 1, device('microphone'), False)
            speaker = Audio(DEVICE_SOURCE, 48000, 1, device('speaker'), False)
            remote_video = Video(EXTERNAL_SOURCE, -1, -1, 0, b'', False)
            if selected.get('screen'):
                camera = Video(EXTERNAL_SOURCE, 1280, 720, 12, b'', False)
            else:
                camera = Video(DEVICE_SOURCE, 640, 480, 24, device('camera'), False) if video else None
            checked(self.lib.ntg_set_stream_sources(self.handle, peer, PLAYBACK,
                                                    Media(None, C.pointer(speaker), C.pointer(remote_video), None)))
            checked(self.lib.ntg_set_stream_sources(self.handle, peer, CAPTURE,
                                                    Media(C.pointer(mic), None, C.pointer(camera) if camera else None, None)))
            self.apply_mute(peer, muted)
        await self.run(native)

    def apply_mute(self, peer, value):
        method = self.lib.ntg_mute if value else self.lib.ntg_unmute
        checked(method(self.handle, peer, C.byref(C.c_bool())))

    async def mute(self, peer, value):
        await self.run(self.apply_mute, peer, value)

    async def send_screen_frame(self, peer, data, timestamp, rotation, width, height):
        frame = FrameData(timestamp, rotation // 90, width, height)
        checked(await self.run(self.lib.ntg_send_external_frame, self.handle, peer, CAMERA, data, len(data), frame))

    async def signal(self, peer, data):
        checked(await self.run(self.lib.ntg_send_signaling_data, self.handle, peer, data, len(data)))

    async def stop(self, peer):
        def native():
            try:
                result = self.lib.ntg_stop(self.handle, peer)
                if result != CONNECTION_NOT_FOUND:
                    checked(result)
            finally:
                self.lib.ntg_instance_destroy(self.handle)
                self.handle = None
                if self.audio_active:
                    self.audio_session(False)
                    self.audio_active = False
        try:
            await asyncio.shield(self.run(native))
        finally:
            self.worker.shutdown(wait=False, cancel_futures=False)


def install(app):
    from rubicon.objc import Block, ObjCClass
    from rubicon.objc.runtime import load_library as load_apple
    from tg_ascii.i18n import tr

    directory = ObjCClass('NSBundle').mainBundle.privateFrameworksPath
    path = Path(str(directory)) / 'TeleGraphCalls.framework' / 'TeleGraphCalls'

    def available():
        if not path.is_file():
            return False
        try:
            return bool(protocol(load_library(path)).library_versions)
        except (OSError, AttributeError, ValueError, RuntimeError):
            return False

    load_apple('AVFoundation')
    AVAudioSession = ObjCClass('AVAudioSession')
    capture = ObjCClass('AVCaptureDevice')

    def configure_audio():
        session = AVAudioSession.sharedInstance()
        if not session.setCategory_mode_options_error_(
                'AVAudioSessionCategoryPlayAndRecord', 'AVAudioSessionModeVoiceChat', 0x8 | 0x4, None):
            raise RuntimeError('Could not configure iOS call audio')
        return session

    def audio_session(active):
        if active:
            if not configure_audio().setActive_error_(True, None):
                raise RuntimeError('Could not activate iOS call audio')
        else:
            session = AVAudioSession.sharedInstance()
            session.setActive_withOptions_error_(False, 1, None)
            session.setCategory_error_('AVAudioSessionCategoryPlayback', None)

    wait_for_callkit_audio = None
    try:
        from . import ios_callkit
        wait_for_callkit_audio = ios_callkit.install(app, configure_audio)
    except (OSError, AttributeError, ValueError, RuntimeError):
        import logging
        logging.getLogger(__name__).warning('CallKit is unavailable', exc_info=True)

    capture_screen = None
    try:
        from . import ios_screen_share
        capture_screen = ios_screen_share.install(app)
    except (ImportError, OSError, AttributeError, ValueError, RuntimeError):
        import logging
        logging.getLogger(__name__).warning('ReplayKit is unavailable', exc_info=True)

    class Engine(IOSCallEngine):
        def __init__(self, *callbacks):
            self.system_audio = False
            super().__init__(*callbacks, lib=load_library(path), audio_session=self.set_audio)

        def set_audio(self, active):
            if not self.system_audio:
                audio_session(active)

        async def media(self, peer, selected, video, muted=False):
            if wait_for_callkit_audio is not None and not self.audio_active:
                manager = app.core.call_manager
                if manager is not None:
                    self.system_audio = await wait_for_callkit_audio(manager.snapshot['token'])
            await super().media(peer, selected, video, muted)

        @staticmethod
        async def devices():
            result = await asyncio.to_thread(devices, load_library(path))
            result['screen'] = [ios_screen_share.SCREEN] if capture_screen is not None else []
            return result

    pending = set()

    async def permission(video):
        loop = asyncio.get_running_loop()
        for media_type in ('soun', 'vide') if video else ('soun',):
            if capture.authorizationStatusForMediaType_(media_type) == 3:
                continue
            if app.core.in_background:
                raise ValueError(tr('Camera permission denied.') if media_type == 'vide'
                                 else tr('Microphone permission denied.'))
            result = loop.create_future()

            def answer(granted):
                pending.discard(reply)
                loop.call_soon_threadsafe(lambda: result.done() or result.set_result(bool(granted)))

            def ask():
                try:
                    capture.requestAccessForMediaType_completionHandler_(media_type, reply)
                except Exception:
                    answer(False)

            reply = Block(answer, None, C.c_bool)
            pending.add(reply)
            app.on_main_thread(ask)
            if not await result:
                raise ValueError(tr('Camera permission denied.') if media_type == 'vide'
                                 else tr('Microphone permission denied.'))

    app.core.native_call_available = available
    app.core.native_call_engine = Engine
    app.core.native_call_permission = permission

    if capture_screen is not None:
        from tg_ascii.calls import CallManager

        class Manager(ios_screen_share.ScreenShare, CallManager):
            screen_capture = capture_screen

        app.core.native_call_manager = Manager

    if path.is_file():
        try:
            # Older engine builds have the individual-call C ABI only.
            if hasattr(load_library(path), 'PyInit_ntgcalls'):
                from . import ios_group_calls
                ios_group_calls.install(app, path, permission, audio_session, capture_screen)
        except (ImportError, OSError, AttributeError, ValueError, RuntimeError):
            import logging
            logging.getLogger(__name__).warning('iOS group calls are unavailable', exc_info=True)
