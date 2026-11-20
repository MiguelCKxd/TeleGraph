"""Disposable native-only group helper: no client, session, credential or network API."""
import asyncio
import inspect
import threading
import time
from .calls_worker import read_packet, write_packet, restore_standard_pipes, exit_helper
from .calls_rpc_codec import METHODS, EVENTS, encode, decode

_binding = None
MAX_SLOTS = 32  # 1.3: 9. Telegram allows up to 30 broadcasting cameras.


def slot_budget(active):
    """(minimum seconds between frames, max (w, h) or None) per camera."""
    if active <= 1:
        return .1, None
    if active <= 4:
        return .1, (640, 360)
    if active <= 9:
        return .15, (426, 240)
    if active <= 16:
        return .2, (320, 180)
    return .25, (256, 144)


# gpu_video: the app draws the grid with the GPU, so each camera can be
# sent bigger and more often (see gpu_video.gpu_budget).
import os as _os
gpu_drawing = _os.environ.get('TG_ASCII_GPU_VIDEO') == '1'


def gpu_slot_budget(active):
    from .gpu_video import gpu_budget
    return gpu_budget(active)


def downscaled(nt, frame, bound):
    """Smaller I420 copy (libswscale via PyAV) before it crosses the IPC pipe."""
    try:
        import av
        info = frame.frame_data
        width, height = int(info.width), int(info.height)
        ratio = min(bound[0] / width, bound[1] / height)
        target = (max(2, int(width * ratio) // 2 * 2), max(2, int(height * ratio) // 2 * 2))
        source = av.VideoFrame(width, height, 'yuv420p')
        data, offset = memoryview(frame.data), 0
        for plane, columns, rows in zip(source.planes, (width, (width + 1) // 2, (width + 1) // 2),
                                        (height, (height + 1) // 2, (height + 1) // 2)):
            size = columns * rows
            chunk = data[offset:offset + size]
            if plane.line_size == columns:
                plane.update(chunk)
            else:
                padded = bytearray(plane.buffer_size)
                for row in range(rows):
                    padded[row * plane.line_size:row * plane.line_size + columns] = chunk[row * columns:(row + 1) * columns]
                plane.update(padded)
            offset += size
        small = source.reformat(width=target[0], height=target[1], format='yuv420p', interpolation='BILINEAR')
        packed = bytearray()
        for plane, columns, rows in zip(small.planes, (target[0], target[0] // 2, target[0] // 2),
                                        (target[1], target[1] // 2, target[1] // 2)):
            raw = bytes(plane)
            for row in range(rows):
                packed += raw[row * plane.line_size:row * plane.line_size + columns]
        return nt.Frame(frame.ssrc, bytes(packed), nt.FrameData(info.absolute_capture_timestamp_ms,
                                                                 info.rotation, target[0], target[1]))
    except Exception:
        return None


async def run():
    global _binding
    import ntgcalls as nt
    from .calls_native import ENGINE_VERSIONS
    if nt.__version__ not in ENGINE_VERSIONS:
        raise RuntimeError('Incompatible native group engine')
    _binding = binding = nt.NTgCalls()
    loop = asyncio.get_running_loop()
    output = asyncio.Queue(maxsize=128)
    wake = asyncio.Event()
    latest, frame_lock, keys, pending = {}, threading.Lock(), set(), set()
    last_frames = {}
    closed = False

    def enqueue(packet):
        if closed:
            return
        try:
            output.put_nowait(packet)
            wake.set()
        except asyncio.QueueFull:
            exit_helper(2)

    def event(name, *values):
        if closed:
            return
        if name == 'on_frames':
            key, mode, device, frames = values
            if device not in (nt.StreamDevice.CAMERA, nt.StreamDevice.SCREEN) or not frames:
                return  # Audio remains native, never traverses Python IPC.
            newest = {frame.ssrc: frame for frame in frames}
            now = time.monotonic()
            queued = False
            for ssrc, frame in newest.items():
                info = frame.frame_data
                if not (0 < info.width <= 4096 and 0 < info.height <= 4096):
                    continue
                slot = (key, mode.value, device.value, ssrc)
                with frame_lock:
                    if slot not in latest and len(latest) >= MAX_SLOTS:
                        continue
                    # Smaller, slower transfers when several sources are active.
                    recent = sum(1 for seen in last_frames.values() if now - seen < 2)
                    slots = max(1, recent, len(newest))
                    interval, bound = gpu_slot_budget(slots) if gpu_drawing else slot_budget(slots)
                    if now - last_frames.get(slot, float('-inf')) < interval:
                        continue
                    if len(last_frames) >= 48 and slot not in last_frames:
                        last_frames.pop(next(iter(last_frames)))
                    last_frames[slot] = now
                if bound is not None and (info.width > bound[0] or info.height > bound[1]):
                    frame = downscaled(nt, frame, bound) or frame
                with frame_lock:
                    if slot not in latest and len(latest) >= MAX_SLOTS:
                        continue
                    latest[slot] = ('on_frames', encode((key, mode, device, [frame])))
                    queued = True
            if queued:
                loop.call_soon_threadsafe(wake.set)
            return
        packet = {'event': 'native', 'args': (name, encode(values))}
        loop.call_soon_threadsafe(enqueue, packet)

    for name in EVENTS:
        getattr(binding, name)(lambda *args, name=name: event(name, *args))

    async def sender():
        while True:
            control = not output.empty()
            packet = output.get_nowait() if control else None
            if packet is None:
                with frame_lock:
                    if latest:
                        name, values = latest.pop(next(iter(latest)))
                        packet = {'event': 'native', 'args': (name, values)}
            if packet is None:
                wake.clear()
                await wake.wait()
                continue
            try:
                await asyncio.to_thread(write_packet, packet)
            finally:
                if control:
                    output.task_done()

    async def request(packet):
        ident = packet['id']
        try:
            method, args = packet['method'], packet.get('args', ())
            if method == 'stop':
                name, args = 'stop', list(args)
            elif method == 'rpc' and len(args) == 2 and args[0] in METHODS:
                name, args = args[0], decode(args[1])
            else:
                raise ValueError('Unsupported group native operation')
            if name in ('create_call', 'create_p2p_call'):
                if keys and args[0] not in keys:
                    raise ValueError('Only one group call per helper')
                keys.add(args[0])  # Cleanup includes partially initialized native calls.
            if args and name not in ('cpu_usage',) and args[0] not in keys:
                raise ValueError('Unknown group native call')
            if name == 'camera_effects':
                from .mac_camera import show_effects
                result = show_effects()
            else:
                result = getattr(binding, name)(*args)
            if inspect.isawaitable(result):
                result = await result
            if name == 'stop':
                keys.discard(args[0])
            await output.put({'id': ident, 'result': encode(result)})
            wake.set()
        except Exception as error:
            await output.put({'id': ident, 'error': type(error).__name__})
            wake.set()

    sender_task = asyncio.create_task(sender())
    try:
        while packet := await asyncio.to_thread(read_packet):
            if packet.get('method') == 'shutdown':
                await output.put({'id': packet['id'], 'result': None})
                wake.set()
                await output.join()
                break
            if len(pending) >= 32:
                raise ValueError('Group native queue limit exceeded')
            task = asyncio.create_task(request(packet))
            pending.add(task)
            task.add_done_callback(pending.discard)
    finally:
        closed = True
        for task in tuple(pending):
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for key in keys:
            try:
                await asyncio.wait_for(binding.stop(key), 2)
            except Exception:
                pass
        sender_task.cancel()
        await asyncio.gather(sender_task, return_exceptions=True)


def main():
    code = 0
    try:
        restore_standard_pipes()
        asyncio.run(run())
    except BaseException:
        code = 1
    exit_helper(code)


if __name__ == '__main__':
    main()
