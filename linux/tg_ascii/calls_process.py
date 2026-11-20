"""Isolate the optional native call engine from the application process.

IPC uses inherited anonymous stdin/stdout pipes, never a network listener. Pickle
is restricted to this trusted child process; no file or remote peer is unpickled.
The disposable helper owns no Telegram session or application state.
"""
import asyncio
import os
from pathlib import Path
import pickle
import struct
import sys
from types import SimpleNamespace

MAX_PACKET = 32 * 1024 * 1024


class NativeWorkerError(RuntimeError):
    pass


class ProcessNativeEngine:
    worker_module = 'tg_ascii.calls_worker'
    worker_flag = '--calls-worker'
    uses_hardware = True
    synthetic = False
    frames_throttled = True

    def __init__(self, on_state, on_signaling, on_frames, on_emojis):
        self._callbacks = dict(state=on_state, signaling=on_signaling,
                               frames=on_frames, emojis=on_emojis)
        self._process = self._reader = None
        self._write_lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()
        self._pending = {}
        self._sequence = 0
        self._protocol = None
        self._peer = None
        self._closing = False
        self.exit_code = None

    async def _start(self):
        async with self._start_lock:
            if self._process is not None:
                return
            if self._closing:
                raise NativeWorkerError('Call engine is closed')
            command = ([sys.executable, self.worker_flag] if getattr(sys, 'frozen', False)
                       else [sys.executable, '-m', self.worker_module])
            if self.synthetic:
                command.append('--synthetic')
            env = os.environ.copy()
            root = str(Path(__file__).resolve().parent.parent)
            env['PYTHONPATH'] = root + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
            options = {'creationflags': 0x08000000} if sys.platform == 'win32' else {}
            self._process = await asyncio.create_subprocess_exec(*command,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, env=env, **options)
            from .app_lifecycle import register_child
            register_child(self._process.pid)  # 'Quit completely' can end it if stuck.
            self._reader = asyncio.create_task(self._read())

    async def _read(self):
        try:
            while True:
                header = await self._process.stdout.readexactly(4)
                size, = struct.unpack('!I', header)
                if size > MAX_PACKET:
                    raise NativeWorkerError('Invalid call engine packet')
                value = pickle.loads(await self._process.stdout.readexactly(size))
                if 'id' in value:
                    future = self._pending.get(value['id'])
                    if future and not future.done():
                        if 'error' in value:
                            future.set_exception(NativeWorkerError(value['error']))
                        else:
                            future.set_result(value.get('result'))
                elif value.get('event') in self._callbacks:
                    args = value['args']
                    if value['event'] == 'frames':
                        peer, mode, device, rows = args
                        args = (peer, mode, device, [SimpleNamespace(data=row['data'],
                            frame_data=SimpleNamespace(**row['info'])) for row in rows])
                    self._callbacks[value['event']](*args)
        except (asyncio.IncompleteReadError, OSError, ValueError, pickle.UnpicklingError, NativeWorkerError):
            pass
        except asyncio.CancelledError:
            return
        finally:
            for future in tuple(self._pending.values()):
                if not future.done():
                    future.set_exception(NativeWorkerError('Call engine disconnected'))
            if not self._closing and self._peer is not None:
                self._callbacks['state'](self._peer, 'FAILED')

    async def _request(self, method, *args):
        await self._start()
        if len(self._pending) >= 32:
            raise NativeWorkerError('Call engine is busy')
        self._sequence += 1
        ident = self._sequence
        future = asyncio.get_running_loop().create_future()
        self._pending[ident] = future
        data = pickle.dumps({'id': ident, 'method': method, 'args': args}, protocol=5)
        try:
            async with self._write_lock:
                self._process.stdin.write(struct.pack('!I', len(data)) + data)
                await self._process.stdin.drain()
            return await asyncio.wait_for(future, 20)
        finally:
            self._pending.pop(ident, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()

    async def create(self, peer, dh, ga_hash=None):
        self._peer = peer
        result = await self._request('create', peer, dict(g=dh.g, p=dh.p, random=dh.random), ga_hash)
        self._protocol = result['protocol']
        return result['ga']

    def protocol(self):
        from telethon.tl.types import PhoneCallProtocol
        if not self._protocol:
            raise NativeWorkerError('Call engine has not been initialized')
        return PhoneCallProtocol(**self._protocol)

    async def exchange(self, peer, ga, fingerprint=0):
        return SimpleNamespace(**await self._request('exchange', peer, ga, fingerprint))

    async def connect(self, peer, call):
        await self._request('connect', peer, call)

    async def media(self, peer, selected, video, muted=False):
        await self._request('media', peer, selected, video, muted)

    async def mute(self, peer, value):
        await self._request('mute', peer, value)

    async def camera_effects(self, peer):
        return await self._request('camera_effects', peer)

    async def signal(self, peer, data):
        await self._request('signal', peer, data)

    async def stop(self, peer):
        if self._process is None:
            return
        self._closing = True
        try:
            if self._process.returncode is None:
                await asyncio.wait_for(self._request('stop', peer), 3)
                await asyncio.wait_for(self._request('shutdown'), 1)
        except (Exception, asyncio.CancelledError):
            # Terminating a disposable media helper releases all device handles;
            # the application and its accounts remain in the parent process.
            pass
        finally:
            if self._process.returncode is None:
                try:
                    await asyncio.wait_for(self._process.wait(), 0.5)
                except TimeoutError:
                    self._process.kill()
                    await self._process.wait()
            self.exit_code = self._process.returncode
            from .app_lifecycle import unregister_child
            unregister_child(self._process.pid)
            if self._reader:
                await asyncio.gather(self._reader, return_exceptions=True)
            if self._process.stdin:
                self._process.stdin.close()

    @classmethod
    async def devices(cls):
        engine = cls(lambda *args: None, lambda *args: None, lambda *args: None, lambda *args: None)
        try:
            return await engine._request('devices')
        finally:
            await engine.stop(0)
