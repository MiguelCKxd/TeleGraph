"""Disposable media helper. Launched only by calls_process, never on app startup."""
import asyncio
import os
import pickle
import struct
import sys
import threading
import time
from types import SimpleNamespace

from .calls_process import MAX_PACKET

# Some native builds also block in the binding's instance destructor, before
# Python reaches process exit. Retain it until the disposable helper's os._exit;
# its explicit stop still releases streams/devices beforehand.
_retained_engine = None


def exit_helper(code):
    """Exit this disposable process without broken native DLL destructors."""
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateProcess.restype = wintypes.BOOL
        # Windows' CRT _exit still runs DLL detach, where WebRTC can hang.
        # All orderly shutdown work has already finished before reaching here.
        kernel.TerminateProcess(kernel.GetCurrentProcess(), code)
    os._exit(code)


def restore_standard_pipes():
    """PyInstaller --windowed sets Python stdio to None on Windows."""
    if sys.platform != 'win32' or (sys.stdin is not None and sys.stdout is not None):
        return
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.GetFileType.argtypes = [wintypes.HANDLE]
    kernel.GetFileType.restype = wintypes.DWORD
    for name, selector, flags, mode in (
            ('stdin', -10, os.O_RDONLY | os.O_BINARY, 'r'),
            ('stdout', -11, os.O_WRONLY | os.O_BINARY, 'w')):
        if getattr(sys, name) is not None:
            continue
        handle = kernel.GetStdHandle(selector & 0xffffffff)
        if not handle or handle == ctypes.c_void_p(-1).value or kernel.GetFileType(handle) != 3:
            raise OSError('Media helper requires an inherited anonymous pipe')
        fd = msvcrt.open_osfhandle(handle, flags)
        setattr(sys, name, os.fdopen(fd, mode, encoding='utf-8'))


def read_packet():
    stream = sys.stdin.buffer
    header = stream.read(4)
    if not header:
        return None
    if len(header) != 4:
        raise ValueError('Incomplete IPC header')
    size, = struct.unpack('!I', header)
    if size > MAX_PACKET:
        raise ValueError('Oversized IPC packet')
    body = stream.read(size)
    if len(body) != size:
        raise ValueError('Incomplete IPC packet')
    return pickle.loads(body)


def write_packet(value):
    data = pickle.dumps(value, protocol=5)
    if len(data) > MAX_PACKET:
        raise ValueError('Oversized IPC packet')
    sys.stdout.buffer.write(struct.pack('!I', len(data)) + data)
    sys.stdout.buffer.flush()


async def run(synthetic=False):
    global _retained_engine
    from .calls_native import NativeEngine
    if synthetic:
        from tools.native_call_fixture import synthetic_factory
        Engine = synthetic_factory(dict(audio_frames=0, video_frames=0, audio_bytes=0, video_bytes=0))
    else:
        Engine = NativeEngine
    loop = asyncio.get_running_loop()
    output = asyncio.Queue(maxsize=128)
    latest = {}
    frame_lock = threading.Lock()
    local_frame_time = [0.0]
    closed = False
    engine = None
    peer = None
    engine_stopped = False

    def event(kind, *args):
        if closed:
            return
        try:
            output.put_nowait({'event': kind, 'args': args})
        except asyncio.QueueFull:
            # Backpressure is a failed transport, not an unbounded event backlog.
            exit_helper(2)

    def dispatch(kind, *args):
        if not closed:
            try:
                loop.call_soon_threadsafe(event, kind, *args)
            except RuntimeError:
                pass

    def frame_event(who, mode, device, frames):
        if closed or mode not in ('PLAYBACK', 'CAPTURE') or not frames:
            return
        if mode == 'CAPTURE' and device != 'CAMERA':
            return
        if mode == 'CAPTURE':
            now = time.monotonic()
            with frame_lock:
                if now - local_frame_time[0] < .1:
                    return
                local_frame_time[0] = now
        frame = frames[-1]
        info, data = frame.frame_data, frame.data
        if len(data) > MAX_PACKET - 4096:
            return
        row = dict(data=bytes(data), info=dict(width=int(info.width), height=int(info.height),
            rotation=int(getattr(info.rotation, 'value', info.rotation))))
        with frame_lock:
            latest[(mode, device)] = (who, mode, device, [row])

    async def writer():
        while True:
            value = await output.get()
            await asyncio.to_thread(write_packet, value)
            output.task_done()

    async def video_pump():
        while True:
            await asyncio.sleep(0.05)
            if output.qsize() > 1:
                continue
            with frame_lock:
                frames = tuple(latest.values())
                latest.clear()
            for args in frames:
                event('frames', *args)

    sender = asyncio.create_task(writer())
    pump = asyncio.create_task(video_pump())
    try:
        while True:
            request = await asyncio.to_thread(read_packet)
            if request is None:
                break
            ident, method, args = request['id'], request['method'], request.get('args', ())
            result = None
            try:
                if method == 'shutdown':
                    await output.put({'id': ident, 'result': None})
                    await asyncio.wait_for(output.join(), 1)
                    break
                if method == 'devices':
                    result = await Engine.devices()
                elif method == 'create':
                    if engine is not None:
                        raise ValueError('Only one call per helper is supported')
                    peer, dh, ga_hash = args
                    engine = Engine(lambda *a: dispatch('state', *a), lambda *a: dispatch('signaling', *a),
                        frame_event, lambda *a: dispatch('emojis', *a))
                    _retained_engine = engine
                    ga = await engine.create(peer, SimpleNamespace(**dh), ga_hash)
                    proto = engine.protocol()
                    result = dict(ga=ga, protocol={name: getattr(proto, name) for name in
                        ('min_layer', 'max_layer', 'udp_p2p', 'udp_reflector', 'library_versions')})
                elif method == 'stop':
                    if engine is not None and not engine_stopped:
                        await engine.stop(args[0])
                        engine_stopped = True
                elif method in ('exchange', 'connect', 'media', 'mute', 'signal', 'camera_effects'):
                    if engine is None:
                        raise ValueError('No call engine')
                    result = await getattr(engine, method)(*args)
                    if method == 'exchange':
                        result = dict(g_a_or_b=result.g_a_or_b, key_fingerprint=result.key_fingerprint)
                else:
                    raise ValueError('Unknown media operation')
                await output.put({'id': ident, 'result': result})
            except Exception as error:
                await output.put({'id': ident, 'error': type(error).__name__})
    finally:
        closed = True
        if engine is not None and peer is not None and not engine_stopped:
            try:
                await asyncio.wait_for(engine.stop(peer), 2)
            except Exception:
                pass
        latest.clear()
        pump.cancel()
        sender.cancel()
        await asyncio.gather(pump, sender, return_exceptions=True)


def main():
    code = 0
    try:
        restore_standard_pipes()
        asyncio.run(run('--synthetic' in sys.argv))
    except BaseException:
        code = 1
    # NTgCalls 3.0.5's global WebRTC factory aborts during C++ static destruction
    # after an actual connection on macOS. This disposable helper has already
    # stopped its devices and flushed IPC. Exit without those faulty destructors;
    # NEVER apply this to the application process, which owns user data/sessions.
    exit_helper(code)


if __name__ == '__main__':
    main()
