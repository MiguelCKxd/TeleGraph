"""Native-only group binding proxy. MTProto and account state never enter the child."""
import asyncio
from concurrent.futures import Future as ThreadFuture
from .calls_process import ProcessNativeEngine, NativeWorkerError
from .calls_rpc_codec import METHODS, EVENTS, encode, decode

# 1.4 opt-in "Expanded group video view": as many cameras as Telegram lets a
# group call broadcast (30). The helper adapts size/rate per camera count.
MAX_INCOMING_VIDEOS = 30


class GroupNativeProxy(ProcessNativeEngine):
    worker_module = 'tg_ascii.calls_group_worker'
    worker_flag = '--group-calls-worker'

    def __init__(self, failed=lambda *_: None):
        super().__init__(failed, lambda *_: None, lambda *_: None, lambda *_: None)
        self._native_callbacks = {}
        self._native_tasks = set()
        self._callbacks['native'] = self._native_event
        self.initial_playback = None
        self.volume_generation = 0
        self.rtmp = False
        self._playback = {}
        self.local_user_id = None
        self._video_offers = {}
        self._video_active = set()
        self._video_signatures = {}
        self._video_stopped = False
        self._video_user = None
        self._video_endpoint = None
        self._video_lock = asyncio.Lock()
        # One camera unless Complex features › Expanded group video view is on.
        self.max_videos = 1
        self.primary_endpoint = None

    async def _sync_video(self, key):
        others = [(endpoint, value) for endpoint, value in self._video_offers.items()
                  if self.local_user_id is not None and value[0] != self.local_user_id]
        # The participant chosen with "View" stays first; the rest of the
        # grid is filled with other cameras, oldest offers first.
        chosen = [(endpoint, value) for endpoint, value in others
                  if (self._video_user is None or value[0] == self._video_user)
                  and (self._video_endpoint is None or endpoint == self._video_endpoint)]
        ordered = chosen[:1] + [item for item in others if item not in chosen[:1]]
        limit = max(1, int(getattr(self, 'max_videos', MAX_INCOMING_VIDEOS)))
        desired = {endpoint for endpoint, _ in ordered[:limit]}
        self.primary_endpoint = ordered[0][0] if ordered else None
        changed = {endpoint for endpoint in desired & self._video_active
                   if self._video_signatures.get(endpoint) != encode(self._video_offers[endpoint])}
        for endpoint in (self._video_active - desired) | changed:
            try:
                await self.native_request('remove_incoming_video', (key, endpoint))
            except Exception as error:
                import ntgcalls as nt
                if not isinstance(error, nt.ConnectionNotFound):
                    raise
            self._video_active.discard(endpoint)
            self._video_signatures.pop(endpoint, None)
        for endpoint in desired - self._video_active:
            user, sources = self._video_offers[endpoint]
            await self.native_request('add_incoming_video', (key, user, endpoint, sources))
            self._video_active.add(endpoint)
            self._video_signatures[endpoint] = encode((user, sources))

    async def add_incoming_video(self, key, user, endpoint, sources):
        async with self._video_lock:
            if self._video_stopped or self._closing:
                return
            self._video_offers[endpoint] = (user, sources)
            await self._sync_video(key)

    async def remove_incoming_video(self, key, endpoint):
        async with self._video_lock:
            if self._video_stopped or self._closing:
                return
            self._video_offers.pop(endpoint, None)
            if endpoint == self._video_endpoint:
                self._video_user = self._video_endpoint = None
            await self._sync_video(key)

    async def select_video(self, key, user, endpoint):
        async with self._video_lock:
            if self._video_stopped or self._closing:
                return
            self._video_user, self._video_endpoint = user, endpoint
            await self._sync_video(key)

    def _native_event(self, name, values):
        callback = self._native_callbacks.get(name)
        if callback is not None:
            result = callback(*decode(values))
            if hasattr(result, 'add_done_callback'):
                self._native_tasks.add(result)
                def completed(future):
                    self._native_tasks.discard(future)
                    if not future.cancelled():
                        future.exception()
                result.add_done_callback(completed)

    async def native_request(self, name, args):
        try:
            return decode(await self._request('rpc', name, encode(args)))
        except NativeWorkerError as error:
            import ntgcalls as nt
            allowed = ('ConnectionNotFound', 'ConnectionError', 'TelegramServerError',
                       'MediaDeviceError', 'InvalidParams', 'FileError')
            if str(error) in allowed:
                raise getattr(nt, str(error))(str(error)) from None
            raise

    def __getattr__(self, name):
        if name in EVENTS:
            def register(callback):
                if not callable(callback):
                    raise ValueError('Native callback must be callable')
                self._native_callbacks[name] = callback
            return register
        if name in METHODS:
            async def invoke(*args):
                if name in ('create_call', 'create_p2p_call'):
                    self._peer = args[0]
                    self.volume_generation += 1
                return await self.native_request(name, args)
            return invoke
        raise AttributeError(name)

    async def mute(self, key):
        return await self.native_request('mute', (key,))

    async def stop(self, key):
        self._video_stopped = True
        async with self._video_lock:
            try:
                return await self.native_request('stop', (key,))
            finally:
                self._playback.pop(key, None)
                self._video_offers.clear()
                self._video_active.clear()
                self._video_signatures.clear()

    async def connect(self, key, params, presentation=False):
        if not presentation:
            import json
            try:
                payload = json.loads(params)
                self.rtmp = payload.get('stream') is True and payload.get('rtmp') is True
            except (ValueError, TypeError, AttributeError):
                self.rtmp = False  # The native engine still validates the original payload.
            if self.rtmp:
                self._video_user, self._video_endpoint = 0, 'unified'
        return await self.native_request('connect', (key, params, presentation))

    async def set_stream_sources(self, key, mode, description):
        from ntgcalls import StreamMode
        if mode == StreamMode.CAPTURE and key not in self._playback and self.initial_playback is not None:
            await self.set_stream_sources(key, StreamMode.PLAYBACK, self.initial_playback)
        if mode == StreamMode.PLAYBACK:
            signature = encode(description)
            if self._playback.get(key) == signature:
                return
            result = await self.native_request('set_stream_sources', (key, mode, description))
            self._playback[key] = signature
            return result
        return await self.native_request('set_stream_sources', (key, mode, description))

    @staticmethod
    def get_protocol():
        import ntgcalls as nt
        return nt.NTgCalls.get_protocol()

    async def close(self):
        self._closing = True
        tasks = tuple(task for task in self._native_tasks if task is not asyncio.current_task())
        for future in tasks:
            future.cancel()
        if tasks:
            await asyncio.gather(*(asyncio.wrap_future(task) if isinstance(task, ThreadFuture) else task
                                   for task in tasks), return_exceptions=True)
        self._native_tasks.clear()
        self._native_callbacks.clear()
        if self._process is None:
            return
        try:
            if self._process.returncode is None:
                await asyncio.wait_for(self._request('shutdown'), 3)
                await asyncio.wait_for(self._process.wait(), 3)
        except (Exception, asyncio.CancelledError):
            if self._process.returncode is None:
                self._process.kill()
                await self._process.wait()
        finally:
            self.exit_code = self._process.returncode
            from .app_lifecycle import unregister_child
            unregister_child(self._process.pid)
            if self._reader:
                await asyncio.gather(self._reader, return_exceptions=True)
            if self._process.stdin:
                self._process.stdin.close()
