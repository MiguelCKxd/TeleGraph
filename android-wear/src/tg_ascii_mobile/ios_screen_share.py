"""ReplayKit video capture for a live call, with bounded frame delivery."""
import asyncio
import ctypes as C
import logging
import time

from PIL import Image

SCREEN = {'id': 'replaykit', 'name': 'Screen'}
FPS = 12
log = logging.getLogger(__name__)

NV12_VIDEO = int.from_bytes(b'420v', 'big')
NV12_FULL = int.from_bytes(b'420f', 'big')
NV12 = {NV12_VIDEO, NV12_FULL}
BGRA = int.from_bytes(b'BGRA', 'big')
VIDEO_LUMA = [16 + round(level * 219 / 255) for level in range(256)]
VIDEO_CHROMA = [16 + round(level * 224 / 255) for level in range(256)]


def i420(convert, width, height, planes):
    # Use even dimensions for 4:2:0 and preserve aspect ratio when rotating.
    scale = min(1.0, 1280 / max(width, height))
    size = tuple(max(2, int(value * scale) & ~1) for value in (width, height))

    def plane(mode, dimensions, source, raw_mode):
        raw, stride = source
        return Image.frombytes(mode, dimensions, raw, 'raw', raw_mode, stride, 1)

    if convert in NV12:
        chroma = ((width + 1) // 2, (height + 1) // 2)
        y = plane('L', (width, height), planes[0], 'L')
        u, v = plane('LA', chroma, planes[1], 'LA').split()
        # ReplayKit may provide full-range NV12. WebRTC's I420 defaults to
        # video range, so convert the range without re-encoding RGB.
        if convert == NV12_FULL:
            y, u, v = y.point(VIDEO_LUMA), u.point(VIDEO_CHROMA), v.point(VIDEO_CHROMA)
    elif convert == BGRA:
        y, u, v = plane('RGB', (width, height), planes[0], 'BGRX').convert('YCbCr').split()
        y, u, v = y.point(VIDEO_LUMA), u.point(VIDEO_CHROMA), v.point(VIDEO_CHROMA)
    else:
        raise ValueError('Unsupported screen pixel format')
    chroma = tuple(value // 2 for value in size)
    dimensions = (size, chroma, chroma)
    data = b''.join(channel.resize(target, Image.Resampling.BILINEAR).tobytes()
                    for channel, target in zip((y, u, v), dimensions))
    return data, *size


class ScreenShare:
    screen_capture = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._screen_lock = asyncio.Lock()
        self._screen_lease = None

    async def share_screen(self, enabled, *, token):
        async with self._screen_lock:
            call = self._check(token=token)
            if call.state != 'active' or getattr(self, 'view_only', False):
                raise ValueError('The call is not connected')
            if call.screen == enabled:
                return
            if not enabled:
                try:
                    await self.set_screen('', token=token)
                finally:
                    self._release_screen(token)
                return
            lease = self._screen_lease = (token, object())
            engine = self._engine

            async def frame(data, timestamp, rotation, width, height):
                if self._screen_lease is lease and self._call is call and call.screen:
                    await engine.send_screen_frame(call.peer, data, timestamp, rotation, width, height)

            def stopped():
                self._schedule(self._screen_stopped(lease))

            try:
                if not await self.screen_capture.start(lease, frame, stopped):
                    return
                if self._screen_lease is lease and self._call is call:
                    await self.set_screen(SCREEN['id'], token=token)
            finally:
                if self._call is not call or not call.screen:
                    self._release_screen(token)

    async def _screen_stopped(self, lease):
        async with self._screen_lock:
            if self._screen_lease is not lease:
                return
            try:
                if self._call is not None and self._call.screen:
                    await self.set_screen('', token=lease[0])
            finally:
                self._release_screen(lease[0])

    def _release_screen(self, token):
        lease = self._screen_lease
        if lease is not None and token == lease[0]:
            self._screen_lease = None
            self.screen_capture.stop(lease)

    async def _finish(self, call, error='', *, discard=False):
        self._release_screen(call.token)
        await super()._finish(call, error, discard=discard)


def install(app):
    from rubicon.objc import Block, ObjCClass, ObjCInstance, objc_id
    from rubicon.objc.runtime import load_library

    replay = load_library('ReplayKit')
    core_media = load_library('CoreMedia')
    core_video = load_library('CoreVideo')
    recorder = ObjCClass('RPScreenRecorder').sharedRecorder
    display = None
    system_version = str(ObjCClass('UIDevice').currentDevice.systemVersion)
    if int(system_version.split('.', 1)[0]) >= 27:
        try:
            from . import ios_display_capture
            display = ios_display_capture.install(app)
        except (ImportError, OSError, AttributeError, ValueError, RuntimeError):
            log.warning('The iOS screen-sharing picker is unavailable', exc_info=True)
    pointer, size = C.c_void_p, C.c_size_t

    def bind(lib, name, result, *args):
        native = getattr(lib, name)
        native.restype, native.argtypes = result, args
        return native

    get_image = bind(core_media, 'CMSampleBufferGetImageBuffer', pointer, pointer)
    get_attachment = bind(core_media, 'CMGetAttachment', pointer, pointer, pointer, pointer)
    orientation = C.c_void_p.in_dll(replay, 'RPVideoSampleOrientationKey')
    format_type = bind(core_video, 'CVPixelBufferGetPixelFormatType', C.c_uint32, pointer)
    width_of = bind(core_video, 'CVPixelBufferGetWidth', size, pointer)
    height_of = bind(core_video, 'CVPixelBufferGetHeight', size, pointer)
    lock = bind(core_video, 'CVPixelBufferLockBaseAddress', C.c_int32, pointer, C.c_uint64)
    unlock = bind(core_video, 'CVPixelBufferUnlockBaseAddress', C.c_int32, pointer, C.c_uint64)
    data_of = bind(core_video, 'CVPixelBufferGetBaseAddress', pointer, pointer)
    stride_of = bind(core_video, 'CVPixelBufferGetBytesPerRow', size, pointer)
    plane_of = bind(core_video, 'CVPixelBufferGetBaseAddressOfPlane', pointer, pointer, size)
    plane_stride = bind(core_video, 'CVPixelBufferGetBytesPerRowOfPlane', size, pointer, size)

    def copy_frame(sample):
        image = get_image(sample)
        if not image:
            return None
        width, height = width_of(image), height_of(image)
        kind = format_type(image)
        if not 2 <= width <= 4096 or not 2 <= height <= 4096 or kind not in NV12 | {BGRA}:
            return None
        if lock(image, 1):
            return None
        try:
            if kind == BGRA:
                address, stride = data_of(image), stride_of(image)
                planes = ((C.string_at(address, stride * height), stride),) if address else ()
            else:
                planes = []
                for index, rows in enumerate((height, (height + 1) // 2)):
                    address, stride = plane_of(image, index), plane_stride(image, index)
                    if not address:
                        return None
                    planes.append((C.string_at(address, stride * rows), stride))
        finally:
            unlock(image, 1)
        if not planes:
            return None
        attachment = get_attachment(sample, orientation, None)
        rotation = {3: 180, 6: 90, 8: 270}.get(int(ObjCInstance(attachment).intValue), 0) if attachment else 0
        return kind, width, height, planes, rotation

    class Capture:
        def __init__(self):
            self.lease = None
            self.blocks = {}
            self.stopping = False
            self.preparing = False

        async def start(self, lease, consumer, stopped):
            if self.lease is not None or self.blocks:
                return False
            self.lease = lease
            loop = asyncio.get_running_loop()
            approved = loop.create_future()
            busy, last = False, 0.0

            def settle(accepted):
                if not approved.done():
                    approved.set_result(accepted)

            async def deliver(args, timestamp):
                nonlocal busy
                try:
                    kind, width, height, planes, rotation = args
                    data, width, height = await asyncio.to_thread(i420, kind, width, height, planes)
                    await consumer(data, timestamp, rotation, width, height)
                except Exception:
                    log.warning('ReplayKit frame delivery failed', exc_info=True)
                    stopped()
                finally:
                    busy = False

            def sample(buffer, kind, error):
                nonlocal busy, last
                if self.lease is not lease:
                    return
                if error:
                    loop.call_soon_threadsafe(stopped)
                    return
                now = time.monotonic()
                if kind != 1 or busy or now - last < 1 / FPS:
                    return
                busy, last = True, now
                try:
                    copied = copy_frame(buffer)
                    if copied is not None:
                        timestamp = time.time_ns() // 1_000_000
                        loop.call_soon_threadsafe(lambda: loop.create_task(deliver(copied, timestamp)))
                        return
                except Exception:
                    log.warning('ReplayKit frame copy failed', exc_info=True)
                    loop.call_soon_threadsafe(stopped)
                busy = False

            def completed(error):
                accepted = not error

                def finish():
                    self.preparing = False
                    if not accepted:
                        self.blocks.pop(lease, None)
                    elif self.lease is not lease:
                        self._stop_native(lease)
                    loop.call_soon_threadsafe(settle, accepted)

                app.on_main_thread(finish)

            handler = Block(sample, None, pointer, C.c_long, objc_id)
            completion = Block(completed, None, objc_id)
            self.blocks[lease] = (handler, completion)

            def begin():
                if self.lease is not lease or (display is None and not recorder.isAvailable()):
                    self.blocks.pop(lease, None)
                    loop.call_soon_threadsafe(settle, False)
                    return
                self.preparing = True
                try:
                    if display is not None:
                        display.start(sample, completed)
                    else:
                        recorder.setMicrophoneEnabled_(False)
                        recorder.startCaptureWithHandler_completionHandler_(handler, completion)
                except Exception:
                    completed(True)

            prior = app.core.external_until
            app.core.expect_external(65)
            deadline = app.core.external_until
            app.on_main_thread(begin)
            try:
                return await asyncio.wait_for(approved, 60) and not app.core.locked
            finally:
                if app.core.external_until == deadline:
                    app.core.external_until = prior

        def stop(self, lease):
            if self.lease is lease:
                self.lease = None
                app.on_main_thread(lambda: self._stop_native(lease))

        def _stop_native(self, lease):
            if lease not in self.blocks or self.stopping:
                return
            if display is None and self.preparing:
                return
            if display is None and not recorder.isRecording():
                self.blocks.pop(lease, None)
                return
            self.stopping = True

            def stopped(_error):
                self.blocks.pop(lease, None)
                self.stopping = False

            reply = Block(stopped, None, objc_id)
            self.blocks[lease] += (reply,)
            try:
                if display is not None:
                    display.stop(stopped)
                else:
                    recorder.stopCaptureWithHandler_(reply)
            except Exception:
                stopped(True)

    return Capture()
