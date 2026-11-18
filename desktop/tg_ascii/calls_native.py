"""Small, version-pinned NTgCalls adapter; no camera/audio capture on import."""
import asyncio
import importlib.metadata
import importlib.util
import sys
from functools import lru_cache

ENGINE_VERSION = '3.0.7' if sys.platform.startswith('linux') else '3.0.5'
ENGINE_VERSIONS = {'3.0.5', '3.0.5+tgascii.volume1', ENGINE_VERSION}


@lru_cache(maxsize=1)
def engine_available():
    try:
        return (importlib.util.find_spec('ntgcalls') is not None and
                importlib.metadata.version('ntgcalls') in ENGINE_VERSIONS)
    except (ImportError, ValueError, importlib.metadata.PackageNotFoundError):
        return False


def frame_image(frame, fit=None):
    """Convert one bounded I420 frame outside the UI thread, including odd sizes.

    With ``fit`` (w, h) the frame is scaled by libswscale straight to the largest
    size that fits (aspect kept, rotation applied): ~10x cheaper than a
    full-resolution RGB conversion followed by a PIL thumbnail (1.4).
    """
    import av
    width, height = frame['width'], frame['height']
    data = frame['data']
    if not (0 < width <= 4096 and 0 < height <= 4096):
        raise ValueError('Invalid video dimensions')
    chroma_width, chroma_height = (width + 1) // 2, (height + 1) // 2
    if len(data) != width * height + 2 * chroma_width * chroma_height:
        raise ValueError('Invalid video frame size')
    video = av.VideoFrame(width, height, 'yuv420p')
    offset = 0
    for plane, columns, rows in zip(video.planes, (width, chroma_width, chroma_width),
                                    (height, chroma_height, chroma_height)):
        size = columns * rows
        source = memoryview(data)[offset:offset + size]
        if plane.line_size == columns and plane.buffer_size == size:
            plane.update(source)
        else:
            padded = bytearray(plane.buffer_size)
            for row in range(rows):
                padded[row * plane.line_size:row * plane.line_size + columns] = source[row * columns:(row + 1) * columns]
            plane.update(padded)
        offset += size
    rotation = frame.get('rotation', 0)
    if fit is not None:
        box_w, box_h = (fit[1], fit[0]) if rotation in (90, 270) else (fit[0], fit[1])
        ratio = min(box_w / width, box_h / height, 1)
        target = (max(1, int(width * ratio)), max(1, int(height * ratio)))
        image = video.reformat(width=target[0], height=target[1], format='rgb24',
                               interpolation='BILINEAR').to_image()
    else:
        image = video.to_image()
    if rotation in (90, 180, 270):
        image = image.rotate(-rotation, expand=True)
    return image


class NativeEngine:
    uses_hardware = True

    def __init__(self, on_state, on_signaling, on_frames, on_emojis):
        import ntgcalls as nt
        if nt.__version__ not in ENGINE_VERSIONS:
            raise RuntimeError('Install ntgcalls==' + ENGINE_VERSION)
        self.nt = nt
        self.binding = nt.NTgCalls()
        self.binding.on_connection_change(lambda peer, info: on_state(peer, info.state.name))
        self.binding.on_signaling_data(on_signaling)
        self.binding.on_update_emojis(on_emojis)
        self.binding.on_frames(lambda peer, mode, device, frames: on_frames(peer, mode.name, device.name, frames))
        self.binding.on_remote_source_change(lambda peer, source:
            on_state(peer, 'REMOTE_' + source.device.name + '_' + source.state.name))

    @staticmethod
    async def devices():
        import ntgcalls as nt
        media = await asyncio.to_thread(nt.NTgCalls.get_media_devices)
        return {kind: [{'id': item.metadata, 'name': item.name} for item in getattr(media, kind)]
                for kind in ('microphone', 'speaker', 'camera', 'screen')}

    def protocol(self):
        from telethon.tl.types import PhoneCallProtocol
        p = self.binding.get_protocol()
        return PhoneCallProtocol(min_layer=65, max_layer=92, udp_p2p=True,
                                 udp_reflector=True, library_versions=p.library_versions)

    async def create(self, peer, dh, ga_hash=None):
        await self.binding.create_p2p_call(peer)
        return await self.binding.init_exchange(peer, self.nt.DhConfig(dh.g, dh.p, dh.random), ga_hash)

    async def exchange(self, peer, ga, fingerprint=0):
        return await self.binding.exchange_keys(peer, ga, fingerprint)

    async def connect(self, peer, call):
        nt = self.nt
        servers = []
        for item in call.connections:
            modern = type(item).__name__ == 'PhoneConnectionWebrtc'
            servers.append(nt.RTCServer(item.id, item.ip, item.ipv6, item.port,
                getattr(item, 'username', None), getattr(item, 'password', None),
                bool(item.turn) if modern else True, bool(item.stun) if modern else False,
                False if modern else bool(item.tcp), None if modern else item.peer_tag))
        if not servers or not set(call.protocol.library_versions).intersection(self.protocol().library_versions):
            raise ValueError('No compatible call transport')
        await self.binding.connect_p2p(peer, servers, call.protocol.library_versions,
                                      bool(call.p2p_allowed),
                                      getattr(getattr(call, 'custom_parameters', None), 'data', None))

    async def media(self, peer, selected, video, muted=False):
        nt = self.nt
        devices = await self.devices()
        def chosen(kind, required=True):
            options = devices[kind]
            desired = selected.get(kind, '')
            if desired:
                if not any(item['id'] == desired for item in options):
                    raise ValueError('Selected ' + kind + ' is unavailable')
                return desired
            if options:
                return options[0]['id']
            if required:
                raise ValueError('No ' + kind + ' device is available')
            return None
        mic, speaker = chosen('microphone'), chosen('speaker')
        screen = chosen('screen') if selected.get('screen') else None
        camera = chosen('camera') if video and screen is None else None
        from .mac_camera import camera_format
        width, height, fps = await asyncio.to_thread(camera_format, camera) if camera is not None else (640, 480, 24)
        audio = lambda device: nt.AudioDescription(nt.MediaSource.DEVICE, 48000, 1, device, False)
        capture = nt.MediaDescription(audio(mic), None,
            (nt.VideoDescription(nt.MediaSource.DESKTOP, 1280, 720, 15, screen, False) if screen is not None else
             nt.VideoDescription(nt.MediaSource.DEVICE, width, height, fps, camera, False) if camera is not None else None), None)
        # Received voice is routed directly by the native engine to the speaker.
        # Only video crosses Python, with a single latest-frame slot in CallManager.
        playback = nt.MediaDescription(audio(speaker), None,
            nt.VideoDescription(nt.MediaSource.EXTERNAL, -1, -1, 0, '', False), None)
        await self.binding.set_stream_sources(peer, nt.StreamMode.PLAYBACK, playback)
        await self.binding.set_stream_sources(peer, nt.StreamMode.CAPTURE, capture)
        await self.mute(peer, muted)

    async def mute(self, peer, value):
        await (self.binding.mute(peer) if value else self.binding.unmute(peer))

    async def camera_effects(self, peer):
        from .mac_camera import show_effects
        return show_effects()

    async def signal(self, peer, data):
        await self.binding.send_signaling_data(peer, data)

    async def stop(self, peer):
        try:
            await self.binding.stop(peer)
        except self.nt.ConnectionNotFound:
            pass
