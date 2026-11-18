"""The Python API of ntgcalls 3.0.5 on top of its Android library.

PyTgCalls 3.0.0 and the shared group call code (tg_ascii.calls_group*) are
written against the ``ntgcalls`` Python extension, which has no Android build.
The same engine ships for Android as the io.github.pytgcalls AAR, with the same
methods in camelCase. install() registers this module as ``ntgcalls``: the
value types and enums are plain Python, NTgCalls runs each Java call on one
worker thread and returns awaitables, and native events arrive through the
concrete Java class org.tgas.calls.GroupCallCallbacks.
"""
import asyncio
import enum
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

__version__ = '3.0.5'
SDK = 'io.github.pytgcalls.'


# -- enums (same names and values as the extension) ---------------------------
class MediaSource(enum.IntEnum):
    UNKNOWN, FILE, SHELL, FFMPEG, DEVICE, DESKTOP, EXTERNAL = 0, 1, 2, 4, 8, 16, 32


class StreamMode(enum.IntEnum):
    CAPTURE, PLAYBACK = 0, 1


class StreamDevice(enum.IntEnum):
    MICROPHONE, SPEAKER, CAMERA, SCREEN = 0, 1, 2, 3


class StreamType(enum.IntEnum):
    AUDIO, VIDEO = 0, 1


class StreamStatus(enum.IntEnum):
    ACTIVE, PAUSED, IDLING = 0, 1, 2


class ConnectionState(enum.IntEnum):
    CONNECTING, CONNECTED, FAILED, TIMEOUT, CLOSED = 1, 2, 4, 8, 16


class ConnectionKind(enum.IntEnum):
    NORMAL, PRESENTATION = 0, 1


class ConnectionMode(enum.IntEnum):
    NONE, RTC, STREAM, RTMP = 0, 1, 2, 3


class CallType(enum.IntEnum):
    GROUP, OUTGOING, INCOMING, P2P, CONFERENCE = 1, 2, 4, 6, 8


class VideoRotation(enum.IntEnum):
    VIDEO_ROTATION_0, VIDEO_ROTATION_90, VIDEO_ROTATION_180, VIDEO_ROTATION_270 = 0, 90, 180, 270


class MediaSegmentQuality(enum.IntEnum):
    NONE, THUMBNAIL, MEDIUM, FULL = 0, 1, 2, 3


class MediaSegmentPartStatus(enum.IntEnum):
    NOT_READY, RESYNC_NEEDED, DOWNLOADING, SUCCESS = 0, 1, 2, 3


# Java package of each enum in the AAR.
_JAVA_ENUMS = {
    MediaSource: 'media.MediaSource', StreamMode: 'media.StreamMode', StreamDevice: 'media.StreamDevice',
    StreamType: 'media.StreamType', StreamStatus: 'media.StreamStatus', ConnectionState: 'ConnectionState',
    ConnectionKind: 'ConnectionKind', ConnectionMode: 'ConnectionMode', CallType: 'instances.CallType',
    VideoRotation: 'VideoRotation', MediaSegmentQuality: 'models.MediaSegmentQuality',
    MediaSegmentPartStatus: 'models.MediaSegmentPartStatus',
}


# -- value types ---------------------------------------------------------------
class _Record:
    __slots__ = ()
    fields = ()

    def __init__(self, *args, **kwargs):
        if len(args) > len(self.fields):
            raise TypeError(type(self).__name__ + ': too many arguments')
        values = dict(zip(self.fields, args))
        for key, value in kwargs.items():
            if key not in self.fields or key in values:
                raise TypeError(f'{type(self).__name__}: unexpected argument {key}')
            values[key] = value
        for key in self.fields:
            object.__setattr__(self, key, values.get(key))

    def __eq__(self, other):
        return type(other) is type(self) and all(getattr(self, key) == getattr(other, key) for key in self.fields)

    __hash__ = None

    def __repr__(self):
        return '%s(%s)' % (type(self).__name__, ', '.join(f'{key}={getattr(self, key)!r}' for key in self.fields))


def _record(name, *fields):
    return type(name, (_Record,), {'__slots__': fields, 'fields': fields, '__module__': __name__})


AudioDescription = _record('AudioDescription', 'media_source', 'sample_rate', 'channel_count', 'input', 'keep_open')
VideoDescription = _record('VideoDescription', 'media_source', 'width', 'height', 'fps', 'input', 'keep_open')
MediaDescription = _record('MediaDescription', 'microphone', 'speaker', 'camera', 'screen')
SsrcGroup = _record('SsrcGroup', 'semantics', 'ssrcs')
SsrcMapping = _record('SsrcMapping', 'user_id', 'ssrc')
MediaState = _record('MediaState', 'muted', 'video_paused', 'video_stopped', 'presentation_paused', 'presentation_stopped')
ConnectionInfo = _record('ConnectionInfo', 'state', 'kind')
CallInfo = _record('CallInfo', 'playback', 'capture')
SubchainRequest = _record('SubchainRequest', 'subchain', 'height', 'limit')
ParticipantsRequest = _record('ParticipantsRequest', 'ssrcs')
Protocol = _record('Protocol', 'min_layer', 'max_layer', 'udp_p2p', 'udp_reflector', 'library_versions')
ConferenceJoinParams = _record('ConferenceJoinParams', 'payload', 'public_key', 'block')
Frame = _record('Frame', 'ssrc', 'data', 'frame_data')
FrameData = _record('FrameData', 'absolute_capture_timestamp_ms', 'rotation', 'width', 'height')
SegmentPartRequest = _record('SegmentPartRequest', 'segment_id', 'part_id', 'limit', 'timestamp',
                             'quality_update', 'channel_id', 'quality')
DeviceInfo = _record('DeviceInfo', 'name', 'metadata')
MediaDevices = _record('MediaDevices', 'microphone', 'speaker', 'camera', 'screen')
DhConfig = _record('DhConfig', 'g', 'p', 'random')
AuthParams = _record('AuthParams', 'key_fingerprint', 'g_a_or_b')
RTCServer = _record('RTCServer', 'id', 'ipv4', 'ipv6', 'port', 'username', 'password', 'turn', 'stun', 'tcp', 'peer_tag')
RemoteSource = _record('RemoteSource', 'ssrc', 'state', 'device')


# -- exceptions ------------------------------------------------------------------
class BaseRTCException(Exception):
    pass


_EXCEPTIONS = ('ConnectionError', 'ConnectionException', 'ConnectionNotFound', 'CryptoError', 'FFmpegError',
               'FileError', 'InvalidParams', 'MediaDeviceError', 'MediaException', 'RTCConnectionNeeded',
               'RTCException', 'RTMPStreamingUnsupported', 'SdpParseException', 'ShellError', 'SignalingError',
               'SignalingException', 'SignalingUnsupported', 'TelegramServerError', 'TransportParseException')
for _name in _EXCEPTIONS:
    globals()[_name] = type(_name, (BaseRTCException,), {'__module__': __name__})
del _name


def _python_error(error):
    """The ntgcalls exception for a Java exception (its class name without the
    'Exception' suffix when the extension names it that way)."""
    try:
        name = str(error.getClass().getSimpleName())
    except Exception:
        return error
    for candidate in (name[:-len('Exception')] if name.endswith('Exception') else name, name):
        if candidate in _EXCEPTIONS:
            return globals()[candidate](candidate)
    return error


# -- conversion between the Java library and these types ----------------------------
def _java(name):
    from java import jclass
    return jclass(SDK + name)


def _to_java(value):
    from java.util import ArrayList
    if isinstance(value, enum.IntEnum):  # before int: these enums are ints too
        return _java(_JAVA_ENUMS[type(value)]).valueOf(value.name)
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return value
    if isinstance(value, (list, tuple)):
        from java import jarray, jbyte
        items = ArrayList()
        for item in value:
            # Inside a List, Python bytes must become byte[] explicitly
            # (applyBlocks takes List<byte[]>); otherwise they arrive as Object[].
            items.add(jarray(jbyte)(item) if isinstance(item, (bytes, bytearray)) else _to_java(item))
        return items
    if isinstance(value, AudioDescription):
        return _java('media.AudioDescription')(_to_java(value.media_source), int(value.sample_rate),
                                               int(value.channel_count), value.input or '', bool(value.keep_open))
    if isinstance(value, VideoDescription):
        return _java('media.VideoDescription')(_to_java(value.media_source), int(value.width), int(value.height),
                                               int(value.fps), value.input or '', bool(value.keep_open))
    if isinstance(value, MediaDescription):
        return _java('media.MediaDescription')(*(_to_java(getattr(value, key)) for key in MediaDescription.fields))
    if isinstance(value, SsrcGroup):
        from java.lang import Integer
        ssrcs = ArrayList()
        for ssrc in value.ssrcs:
            ssrcs.add(Integer(int(ssrc)))
        return _java('models.SsrcGroup')(value.semantics, ssrcs)
    if isinstance(value, SsrcMapping):
        return _java('models.SsrcMapping')(int(value.user_id), int(value.ssrc))
    if isinstance(value, FrameData):
        return _java('models.FrameData')(int(value.absolute_capture_timestamp_ms), _to_java(value.rotation),
                                         int(value.width), int(value.height))
    if isinstance(value, DhConfig):
        return _java('p2p.DhConfig')(int(value.g), bytes(value.p), bytes(value.random))
    if isinstance(value, RTCServer):
        return _java('p2p.RTCServer')(int(value.id), value.ipv4, value.ipv6, int(value.port), value.username,
                                      value.password, bool(value.turn), bool(value.stun), bool(value.tcp),
                                      None if value.peer_tag is None else bytes(value.peer_tag))
    raise TypeError('ntgcalls: unsupported argument ' + type(value).__name__)


def _from_java(value):
    """Java results and event values as the extension's Python values."""
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return value
    try:
        from java.lang import Enum
        from java.util import List, Map
    except ImportError:
        return value
    if isinstance(value, Enum):
        simple = str(value.getClass().getSimpleName())
        for kind, path in _JAVA_ENUMS.items():
            if path.rsplit('.', 1)[-1] == simple:
                return kind[str(value.name())]
        return str(value.name())
    if isinstance(value, Map):
        return {_from_java(key): _from_java(value.get(key)) for key in value.keySet().toArray()}
    if isinstance(value, List):
        return [_from_java(item) for item in value.toArray()]
    name = str(value.getClass().getSimpleName())
    if name in ('String',):
        return str(value)
    if name in ('Long', 'Integer', 'Short', 'Byte'):
        return int(value.longValue())
    if name in ('Double', 'Float'):
        return float(value.doubleValue())
    if name == 'Boolean':
        return bool(value.booleanValue())
    kind = {'ConnectionInfo': ConnectionInfo, 'MediaState': MediaState, 'CallInfo': CallInfo,
            'SubchainRequest': SubchainRequest, 'ParticipantsRequest': ParticipantsRequest, 'Protocol': Protocol,
            'ConferenceJoinParams': ConferenceJoinParams, 'SegmentPartRequest': SegmentPartRequest,
            'DeviceInfo': DeviceInfo, 'MediaDevices': MediaDevices, 'AuthParams': AuthParams,
            'RemoteSource': RemoteSource, 'FrameData': FrameData, 'SsrcMapping': SsrcMapping}.get(name)
    if kind is not None:
        values = []
        for key in kind.fields:
            item = getattr(value, key)
            values.append(bytes(item) if key in ('public_key', 'block', 'g_a_or_b') and item is not None
                          else _from_java(item))
        return kind(*values)
    if name == 'byte[]':
        return bytes(value)
    return value


def _frames(frames, budget):
    """Frames as Python values: the latest one per SSRC, at most every
    `budget` seconds per SSRC (copying I420 data is the costly part)."""
    result = []
    now = time.monotonic()
    latest = {}
    for frame in frames.toArray():
        latest[int(frame.ssrc)] = frame
    for ssrc, frame in latest.items():
        if now - budget.get(ssrc, 0.0) < 0.1:
            continue
        info = frame.frame_data
        if not (0 < info.width <= 4096 and 0 < info.height <= 4096):
            continue
        budget[ssrc] = now
        if len(budget) > 64:
            budget.pop(next(iter(budget)))
        result.append(Frame(ssrc, bytes(frame.data), FrameData(int(info.absolute_capture_timestamp_ms),
                                                               _from_java(info.rotation), int(info.width), int(info.height))))
    return result


# The shared code recognises engine values by their module (calls_rpc_codec).
for _value in list(globals().values()):
    if isinstance(_value, type) and _value.__module__ == __name__ and _value is not _Record:
        _value.__module__ = 'ntgcalls'
del _value


# -- engine instances --------------------------------------------------------------------
# The Android library frees an engine only in NTgCalls.finalize(), when the
# garbage collector reclaims the Java object; right after a call ends that can
# race the engine's own network threads (a native crash in ntg-net). Stopped
# engines are therefore never released: they wait here for the next call.
_idle = []
_kept = []  # engines whose stop failed: kept alive, never reused
_idle_lock = threading.Lock()


def acquire_engine():
    with _idle_lock:
        if _idle:
            return _idle.pop()
    return _java('NTgCalls')()


def release_engine(engine, clean=True):
    """Keep an engine alive: for reuse once all its calls stopped (clean),
    otherwise only so that it is never finalized."""
    if engine is None:
        return
    with _idle_lock:
        if any(item is engine for item in _idle + _kept):
            return
        (_idle if clean else _kept).append(engine)


# -- the binding -----------------------------------------------------------------------
_EVENTS = {
    'on_connection_change': 'onConnectionChange', 'on_frames': 'onFrames', 'on_outbound_block': 'onOutboundBlock',
    'on_remote_source_change': 'onRemoteSourceChange', 'on_request_broadcast_part': 'onRequestBroadcastPart',
    'on_request_broadcast_timestamp': 'onRequestBroadcastTimestamp',
    'on_request_participants': 'onRequestParticipants', 'on_signaling_data': 'onSignalingData',
    'on_stream_end': 'onStreamEnd', 'on_subchain_request': 'onSubchainRequest',
    'on_update_emojis': 'onUpdateEmojis', 'on_upgrade': 'onUpgrade',
}
_METHODS = {
    'create_p2p_call': 'createP2pCall', 'init_exchange': 'initExchange', 'exchange_keys': 'exchangeKeys',
    'skip_exchange': 'skipExchange', 'connect_p2p': 'connectP2p', 'create_call': 'createCall',
    'init_presentation': 'initPresentation', 'init_conference': 'initConference', 'connect': 'connect',
    'add_incoming_video': 'addIncomingVideo', 'remove_incoming_video': 'removeIncomingVideo',
    'set_stream_sources': 'setStreamSources', 'pause': 'pause', 'resume': 'resume', 'mute': 'mute',
    'unmute': 'unmute', 'stop': 'stop', 'stop_presentation': 'stopPresentation',
    'set_source_volume': 'setSourceVolume',
    'get_emojis_fingerprint': 'getEmojisFingerprint', 'time': 'time', 'get_state': 'getState',
    'get_call_type': 'getCallType', 'get_connection_mode': 'getConnectionMode', 'cpu_usage': 'cpuUsage',
    'send_broadcast_timestamp': 'sendBroadcastTimestamp', 'send_broadcast_part': 'sendBroadcastPart',
    'send_signaling_data': 'sendSignalingData', 'send_external_frame': 'sendExternalFrame',
    'update_audio_ssrc_mappings': 'updateAudioSsrcMappings', 'apply_blocks': 'applyBlocks',
    'finish_subchain_request': 'finishSubchainRequest', 'calls': 'calls',
}


class NTgCalls:
    def __init__(self):
        from java import jclass
        self._java = acquire_engine()
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='TeleGraphGroupCall')
        self._callbacks = {}
        self.supports_source_volume = hasattr(self._java, "setSourceVolume")
        self._frame_budget = {}
        self._lock = threading.Lock()
        self._closed = False
        self._bridge = jclass('org.tgas.calls.GroupCallCallbacks')(self)
        for setter in _EVENTS.values():
            getattr(self._java, setter)(self._bridge)

    # Events from the native threads (GroupCallCallbacks.dispatch).
    def native_event(self, name, *values):
        callback = self._callbacks.get(str(name))
        if callback is None or self._closed:
            return
        if name == 'on_frames':
            chat, mode, device, frames = values
            device = _from_java(device)
            if device not in (StreamDevice.CAMERA, StreamDevice.SCREEN) or frames.isEmpty():
                return  # Audio stays native.
            with self._lock:
                converted = _frames(frames, self._frame_budget)
            if converted:
                callback(int(chat), _from_java(mode), device, converted)
            return
        callback(*(int(value) if index == 0 else
                   bytes(value) if name in ('on_signaling_data', 'on_outbound_block') and index == 1 else
                   _from_java(value) for index, value in enumerate(values)))

    def __getattr__(self, name):
        if name in _EVENTS:
            def register(callback):
                self._callbacks[name] = callback
            return register
        if name in _METHODS:
            def invoke(*args):
                return self._call(name, args)
            return invoke
        raise AttributeError(name)

    def _call(self, name, args):
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def run():
            if name == 'set_source_volume':
                method = getattr(self._java, _METHODS[name], None)
                if method is None:
                    raise MediaException('Per-participant volume is not available on Android')
                peer, source, gain = args
                # Java uses int for the unsigned RTP SSRC bit pattern.
                source = (source + 0x80000000) % 0x100000000 - 0x80000000
                return method(peer, source, gain)
            method = getattr(self._java, _METHODS[name])
            try:
                return _from_java(method(*(_to_java(arg) for arg in args)))
            except Exception as error:
                converted = _python_error(error)
                if converted is error:
                    raise
                raise converted from None

        def done(task):
            if future.cancelled():
                return
            error = task.exception()
            if error is not None:
                loop.call_soon_threadsafe(_settle, future, None, error)
            else:
                loop.call_soon_threadsafe(_settle, future, task.result(), None)
        self._worker.submit(run).add_done_callback(done)
        return future

    def close(self, clean=True):
        """After every call was stopped (clean): the engine goes back to the pool."""
        if self._closed:
            return
        self._closed = True
        self._callbacks.clear()
        self._bridge.close()
        engine, self._java = self._java, None

        def retire():
            release_engine(engine, clean)  # after any pending native call of this binding
        self._worker.submit(retire)
        self._worker.shutdown(wait=False, cancel_futures=False)

    @staticmethod
    def get_protocol():
        return _from_java(_java('NTgCalls').getProtocol())

    @staticmethod
    def get_media_devices():
        return _from_java(_java('NTgCalls').getMediaDevices())

    @staticmethod
    def ping():
        return str(_java('NTgCalls').ping())

    @staticmethod
    def enable_glib_loop(enable):
        return None


def _settle(future, result, error):
    if future.done():
        return
    if error is not None:
        future.set_exception(error)
    else:
        future.set_result(result)


def install():
    """Register this module as ``ntgcalls`` (and aiohttp stubs when needed)."""
    from .pytgcalls_dependencies import install_pytgcalls_dependencies

    module = sys.modules[__name__]
    sys.modules.setdefault('ntgcalls', module)
    install_pytgcalls_dependencies()
    return sys.modules['ntgcalls']
