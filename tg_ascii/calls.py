"""Account-scoped individual Telegram calls, with lazy native media resources.

All async methods and state events belong to the client's asyncio thread.
Only take_frame() is intended for another thread (the UI). Call tokens prevent
old windows from answering or hanging up a newer call to the same person.
"""
import asyncio
from collections import deque
import logging
from dataclasses import dataclass, field
import secrets
import threading
import time
import uuid

from .calls_native import ENGINE_VERSION, engine_available
from .calls_process import ProcessNativeEngine

# Step names and timings only: never peers, tokens, keys or payloads.
log = logging.getLogger(__name__)


class CallError(RuntimeError):
    pass


@dataclass
class _Call:
    peer: int
    incoming: bool
    video: bool
    token: str = field(default_factory=lambda: uuid.uuid4().hex)
    remote: object = None
    state: str = 'preparing'
    muted: bool = False
    emojis: str = ''
    connected_at: float = 0
    accepted: bool = False
    native_created: bool = False
    exchanged: bool = False
    connected: bool = False
    ever_video: bool = False
    remote_video: bool = False
    remote_muted: bool = False
    screen: bool = False
    outcome: str = ''
    stage_seen: set = field(default_factory=set)


class CallManager:
    _capture_lock = threading.Lock()
    _capture_owner = None

    def __init__(self, client, on_event=None, *, engine_factory=ProcessNativeEngine,
                 available=engine_available, timeout=45):
        self.client, self.on_event = client, on_event
        self._factory, self._available = engine_factory, available
        self._timeout = timeout
        self._lock = asyncio.Lock()
        self._call = self._engine = self._loop = None
        self._closed = self._enabled = False
        self._timer = None
        self._tasks = set()
        self._updates = set()
        self._selected = {'microphone': '', 'speaker': '', 'camera': ''}
        self._frame_lock = threading.Lock()
        self._frame = None
        self._frame_time = 0.0
        self._local_frame = None
        self._local_frame_time = 0.0
        self._seen_ids = deque(maxlen=64)
        self._last = {'state': 'idle', 'peer': None, 'token': '', 'incoming': False,
                      'video': False, 'muted': False, 'emojis': '', 'error': ''}
        self._signal_queue = None
        self._signal_worker = None
        self._signal_error_pending = False
        self._starting_task = None

    @property
    def snapshot(self):
        if not self._call:
            return dict(self._last)
        c = self._call
        return {'state': c.state, 'peer': c.peer, 'token': c.token,
                'incoming': c.incoming, 'video': c.video, 'muted': c.muted,
                'emojis': c.emojis, 'error': '', 'connected_at': c.connected_at,
                'requested_video': c.ever_video, 'remote_video': c.remote_video,
                'remote_muted': c.remote_muted, 'screen': c.screen, 'outcome':c.outcome}

    async def enable(self):
        if self._closed:
            raise CallError('Call service is closed')
        if self._enabled:
            return
        if not self._available():
            raise CallError(f'Install the compatible calls component (ntgcalls=={ENGINE_VERSION})')
        from telethon import events
        self._loop = asyncio.get_running_loop()
        self.client.add_event_handler(self._on_update, events.Raw())
        self._enabled = True

    def _emit(self):
        self._last = self.snapshot
        if self.on_event:
            try:
                self.on_event(dict(self._last))
            except Exception:
                # A closed UI must not interrupt an encryption/state transition.
                pass

    def _check(self, peer=None, token=None):
        c = self._call
        if c is None or (peer is not None and int(peer) != c.peer) or (token is not None and token != c.token):
            raise CallError('This call is no longer active')
        return c

    def _schedule(self, coroutine):
        if self._closed:
            coroutine.close()
            return
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        def done(future):
            self._tasks.discard(future)
            if not future.cancelled():
                future.exception()
        task.add_done_callback(done)

    def _from_native(self, callback, *args):
        if self._loop is not None and not self._closed:
            try:
                self._loop.call_soon_threadsafe(callback, *args)
            except RuntimeError:
                pass

    async def _prepare(self, c):
        from telethon.tl.functions.messages import GetDhConfigRequest
        from .calls_crypto import validate_dh
        if getattr(self._factory, 'uses_hardware', True):
            from .mac_media_access import ensure_media_access
            await ensure_media_access(c.video)
            with self._capture_lock:
                if CallManager._capture_owner not in (None, c.token):
                    raise CallError('Another account already has an active call')
                CallManager._capture_owner = c.token
        # Fresh server entropy for every call, even when parameter checks are cached.
        dh = await asyncio.wait_for(self.client(GetDhConfigRequest(version=0, random_length=256)), 20)
        if len(getattr(dh, 'random', b'')) != 256 or not hasattr(dh, 'p'):
            raise CallError('Invalid call encryption parameters')
        await asyncio.wait_for(asyncio.to_thread(validate_dh, dh.g, bytes(dh.p)), 20)
        token = c.token
        self._engine = self._factory(
            lambda peer, state: self._from_native(self._state_event, token, peer, state),
            lambda peer, data: self._from_native(self._queue_signal, token, peer, data),
            lambda peer, mode, device, frames: self._receive_frame(token, peer, mode, device, frames),
            lambda peer, emojis: self._from_native(self._set_emojis, token, peer, emojis))
        self._signal_queue = asyncio.Queue(maxsize=64)
        self._signal_error_pending = False
        self._signal_worker = asyncio.create_task(self._send_signals(c))
        c.native_created = True  # stop() also handles a partially failed create.
        return await asyncio.wait_for(self._engine.create(c.peer, dh,
            c.remote.g_a_hash if c.incoming else None), 15)

    def _state_event(self, token, peer, state):
        self._schedule(self._native_state(token, peer, state))

    def _deadline(self, c):
        if self._timer:
            self._timer.cancel()
        async def expired():
            await asyncio.sleep(self._timeout)
            async with self._lock:
                if self._call is c and c.state != 'active':
                    await self._finish(c, 'Call timed out', discard=True)
        self._timer = asyncio.create_task(expired())

    async def start(self, peer, video=False):
        await self.enable()
        async with self._lock:
            if self._call:
                raise CallError('Another call is already active')
            from telethon.tl import types
            from telethon.tl.functions.phone import RequestCallRequest
            entity = await asyncio.wait_for(self.client.get_entity(peer), 15)
            if not isinstance(entity, types.User) or entity.bot or entity.is_self or entity.deleted:
                raise CallError('Calls require another user account')
            c = self._call = _Call(int(entity.id), False, bool(video), ever_video=bool(video))
            self._starting_task = asyncio.current_task()
            self._emit()
            try:
                ga_hash = await self._prepare(c)
                user = types.InputUser(entity.id, entity.access_hash)
                result = await asyncio.wait_for(self.client(RequestCallRequest(
                    user_id=user, random_id=secrets.randbits(31), g_a_hash=ga_hash,
                    protocol=self._engine.protocol(), video=c.video)), 20)
                c.remote = result.phone_call
                if not isinstance(c.remote, types.PhoneCallWaiting):
                    raise CallError('Unexpected call response')
                c.state = 'ringing'
                self._deadline(c)
                self._emit()
                return self.snapshot
            except BaseException as error:
                await self._finish(c, self._error(error), discard=True)
                raise
            finally:
                self._starting_task = None

    async def accept(self, peer=None, video=False, *, token=None):
        async with self._lock:
            c = self._check(peer, token)
            if not c.incoming or c.state != 'incoming':
                raise CallError('This call cannot be answered again')
            from telethon.tl.functions.phone import AcceptCallRequest
            c.state, c.accepted, c.video = 'connecting', True, bool(video)
            c.ever_video |= c.video
            self._starting_task = asyncio.current_task()
            self._emit()
            try:
                gb = await self._prepare(c)
                await asyncio.wait_for(self.client(AcceptCallRequest(
                    peer=self._input(c), g_b=gb, protocol=self._engine.protocol())), 20)
                self._deadline(c)
            except BaseException as error:
                await self._finish(c, self._error(error), discard=True)
                raise
            finally:
                self._starting_task = None
            return self.snapshot

    async def decline(self, peer=None, *, token=None):
        c=self._check(peer,token)
        if c.incoming and not c.accepted:c.outcome='declined'
        return await self.hangup(peer, token=token)

    async def hangup(self, peer=None, *, token=None):
        c = self._check(peer, token)
        log.info('hangup requested (state %s)', c.state)
        task = self._starting_task
        if task and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if self._call is not c:
                return self.snapshot
        started = time.monotonic()
        async with self._lock:
            log.info('hangup lock after %.2fs', time.monotonic() - started)
            c = self._check(peer, token)
            await self._finish(c, discard=True)
            return self.snapshot

    async def mute(self, value, *, token=None):
        async with self._lock:
            c = self._check(token=token)
            if c.state != 'active':
                raise CallError('The call is not connected')
            await asyncio.wait_for(self._engine.mute(c.peer, bool(value)), 10)
            c.muted = bool(value)
            self._emit()

    async def set_camera(self, value, *, token=None):
        async with self._lock:
            c = self._check(token=token)
            if c.state != 'active':
                raise CallError('The call is not connected')
            if value and getattr(self._factory, 'uses_hardware', True):
                from .mac_media_access import ensure_media_access
                await ensure_media_access(True)
            selected = {key: item for key, item in self._selected.items() if key != 'screen'} if value else self._selected
            await asyncio.wait_for(self._engine.media(c.peer, selected, bool(value), c.muted), 15)
            self._selected = selected
            if value:
                c.screen = False
            c.video = bool(value)
            if not c.video:
                with self._frame_lock:
                    self._local_frame = None
            c.ever_video |= c.video
            self._emit()

    async def set_screen(self, source='', *, token=None):
        """Explicitly selected desktop source uses the P2P video stream."""
        async with self._lock:
            c = self._check(token=token)
            if c.state != 'active':
                raise CallError('The call is not connected')
            if not isinstance(source, str):
                raise CallError('Selected device is unavailable')
            if source:
                devices = await self.devices()
                if not any(item['id'] == source for item in devices.get('screen', ())):
                    raise CallError('Selected device is unavailable')
            selected = {key: value for key, value in self._selected.items() if key != 'screen'}
            if source:
                selected['screen'] = source
            await asyncio.wait_for(self._engine.media(c.peer, selected, False, c.muted), 15)
            self._selected = selected
            c.video, c.screen = False, bool(source)
            c.ever_video |= c.screen
            with self._frame_lock:
                self._local_frame = None
            self._emit()

    async def camera_effects(self, *, token=None):
        async with self._lock:
            c = self._check(token=token)
            if c.state != 'active' or not c.video:
                raise CallError('The camera is not active')
            return await asyncio.wait_for(self._engine.camera_effects(c.peer), 10)

    async def devices(self):
        if not self._available():
            raise CallError(f'Install the compatible calls component (ntgcalls=={ENGINE_VERSION})')
        return await asyncio.wait_for(self._factory.devices(), 10)

    async def select_devices(self, microphone='', speaker='', camera='', *, token=None):
        async with self._lock:
            selected = dict(microphone=microphone, speaker=speaker, camera=camera)
            devices = await self.devices()
            for kind, ident in selected.items():
                if ident and not any(item['id'] == ident for item in devices[kind]):
                    raise CallError('Selected device is unavailable')
            if self._call:
                c = self._check(token=token)
                if c.screen:
                    selected['screen'] = self._selected['screen']
                if c.state == 'active':
                    await asyncio.wait_for(self._engine.media(c.peer, selected, c.video, c.muted), 15)
            self._selected = selected

    @staticmethod
    def _input(c):
        from telethon.tl.types import InputPhoneCall
        return InputPhoneCall(c.remote.id, c.remote.access_hash)

    @staticmethod
    def _error(error):
        if isinstance(error, asyncio.CancelledError):
            return 'Call cancelled'
        if isinstance(error, (CallError, ValueError)):
            return str(error)
        if isinstance(error, TimeoutError):
            return 'Call timed out'
        # Native and transport exception messages may contain sensitive parameters.
        return 'Call failed: ' + type(error).__name__

    async def _on_update(self, update):
        if self._closed or not self._enabled:
            return
        from telethon.tl import types
        if not isinstance(update, (types.UpdatePhoneCall, types.UpdatePhoneCallSignalingData)):
            return
        if len(self._updates) >= 128:
            if self._call:
                self._signal_error(self._call.token)
            return
        # The manager owns negotiation tasks, so shutdown cancels its RPC waits
        # without cancelling Telethon's shared update dispatcher.
        task = asyncio.create_task(self._process_update(update))
        self._updates.add(task)
        try:
            await task
        except asyncio.CancelledError:
            if not self._closed:
                raise
        finally:
            self._updates.discard(task)

    async def _process_update(self, update):
        from telethon.tl import types
        async with self._lock:
            c = self._call
            try:
                if isinstance(update, types.UpdatePhoneCallSignalingData):
                    if c and c.connected and c.remote.id == update.phone_call_id and len(update.data) <= 262144:
                        await asyncio.wait_for(self._engine.signal(c.peer, update.data), 10)
                    return
                remote = update.phone_call
                if isinstance(remote, types.PhoneCallRequested):
                    if remote.id in self._seen_ids or (c and c.remote and c.remote.id == remote.id):
                        return
                    if c:
                        from telethon.tl.functions.phone import DiscardCallRequest
                        self._seen_ids.append(remote.id)
                        try:
                            await asyncio.wait_for(self.client(DiscardCallRequest(
                                peer=types.InputPhoneCall(remote.id, remote.access_hash), duration=0,
                                reason=types.PhoneCallDiscardReasonBusy(), connection_id=0,
                                video=bool(remote.video))), 10)
                        except Exception:
                            # Failure to reject a different call must never end
                            # the call that currently owns the media engine.
                            pass
                        return
                    if len(remote.g_a_hash) != 32 or remote.admin_id <= 0:
                        return
                    self._call = c = _Call(remote.admin_id, True, False, remote=remote,
                                         state='incoming', ever_video=bool(remote.video))
                    self._deadline(c)
                    self._emit()
                    return
                if not c or c.remote is None or remote.id != c.remote.id:
                    return
                if isinstance(remote, types.PhoneCallDiscarded):
                    log.info('remote discarded the call')
                    from .call_outcomes import discard_outcome
                    c.outcome=discard_outcome(remote.reason)
                    await self._finish(c)
                    return
                stage = type(remote).__name__
                if stage in c.stage_seen:
                    return
                if isinstance(remote, types.PhoneCallAccepted) and not c.incoming and not c.exchanged:
                    c.stage_seen.add(stage)
                    c.state = 'connecting'
                    self._emit()
                    auth = await asyncio.wait_for(self._engine.exchange(c.peer, remote.g_b, 0), 15)
                    c.exchanged = True
                    from telethon.tl.functions.phone import ConfirmCallRequest
                    result = await asyncio.wait_for(self.client(ConfirmCallRequest(
                        peer=self._input(c), g_a=auth.g_a_or_b,
                        key_fingerprint=auth.key_fingerprint, protocol=self._engine.protocol())), 20)
                    final = result.phone_call
                    if not isinstance(final, types.PhoneCall) or final.id != c.remote.id or final.key_fingerprint != auth.key_fingerprint:
                        raise CallError('Invalid call confirmation')
                    await self._connect(c, final)
                elif isinstance(remote, types.PhoneCall) and c.incoming and c.accepted and not c.exchanged:
                    c.stage_seen.add(stage)
                    # NTgCalls verifies the committed ga hash, public-key range,
                    # and fingerprint before it accepts the key.
                    await asyncio.wait_for(self._engine.exchange(c.peer, remote.g_a_or_b, remote.key_fingerprint), 15)
                    c.exchanged = True
                    await self._connect(c, remote)
            except Exception as error:
                log.info('call update failed: %s', type(error).__name__)
                if c is not None and self._call is c:
                    await self._finish(c, self._error(error), discard=True)

    async def _connect(self, c, remote):
        if c.connected:
            return
        c.remote = remote
        c.connected = True
        await asyncio.wait_for(self._engine.media(c.peer, self._selected, c.video, c.muted), 15)
        await asyncio.wait_for(self._engine.connect(c.peer, remote), 15)
        self._deadline(c)

    async def _native_state(self, token, peer, state):
        log.info('native state %s', state if state.isupper() and len(state) < 48 else '?')
        async with self._lock:
            c = self._call
            if not c or c.token != token or c.peer != peer:
                return
            if state == 'CONNECTED':
                c.state = 'active'
                c.connected_at = c.connected_at or time.monotonic()
                if self._timer:
                    self._timer.cancel()
                    self._timer = None
                self._emit()
            elif state == 'CONNECTING':
                c.state = 'connecting'
                self._deadline(c)
                self._emit()
            elif state in ('FAILED', 'TIMEOUT', 'CLOSED'):
                await self._finish(c, '' if state == 'CLOSED' else 'Call connection lost', discard=True)
            elif state.startswith('REMOTE_CAMERA_'):
                c.remote_video = state == 'REMOTE_CAMERA_ACTIVE'
                if not c.remote_video:
                    with self._frame_lock:
                        self._frame = None
                self._emit()
            elif state.startswith('REMOTE_MICROPHONE_'):
                c.remote_muted = state != 'REMOTE_MICROPHONE_ACTIVE'
                self._emit()

    def _set_emojis(self, token, peer, emojis):
        c = self._call
        if c and c.token == token and c.peer == peer:
            c.emojis = str(emojis)[:128]
            self._emit()

    def _queue_signal(self, token, peer, data):
        c = self._call
        if not c or c.token != token or c.peer != peer or not self._signal_queue:
            return
        if len(data) > 262144:
            self._signal_error(token)
            return
        try:
            self._signal_queue.put_nowait(data)
        except asyncio.QueueFull:
            self._signal_error(token)

    def _signal_error(self, token):
        if not self._signal_error_pending:
            self._signal_error_pending = True
            self._schedule(self._signal_failed(token))

    async def _signal_failed(self, token):
        async with self._lock:
            c = self._call
            if c and c.token == token:
                await self._finish(c, 'Call signaling failed', discard=True)

    async def _send_signals(self, c):
        from telethon.tl.functions.phone import SendSignalingDataRequest
        queue = self._signal_queue
        try:
            while self._call is c:
                data = await queue.get()
                if self._call is not c or c.remote is None:
                    return
                await asyncio.wait_for(self.client(SendSignalingDataRequest(peer=self._input(c), data=data)), 10)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._signal_error(c.token)

    def _receive_frame(self, token, peer, mode, device, frames):
        c = self._call
        if not c or c.token != token or c.peer != peer or mode not in ('PLAYBACK', 'CAPTURE') or device != 'CAMERA' or not frames:
            return
        local = mode == 'CAPTURE'
        if local and not c.video:
            return
        now = time.monotonic()
        # The process transport already coalesces at 20 fps. Applying the same
        # clock again would discard good frames whenever pipe delivery jitters.
        last_time = self._local_frame_time if local else self._frame_time
        if not getattr(self._factory, 'frames_throttled', False) and now - last_time < (1 / 10 if local else 1 / 20):
            return
        frame = frames[-1]
        info = frame.frame_data
        data = frame.data
        width, height = int(info.width), int(info.height)
        expected = width * height + 2 * ((width + 1) // 2) * ((height + 1) // 2)
        if not (0 < width <= 4096 and 0 < height <= 4096 and len(data) == expected):
            return
        rotation = int(getattr(info.rotation, 'value', info.rotation))
        with self._frame_lock:
            value = {'width': width, 'height': height, 'rotation': rotation,
                     'data': bytes(data), 'format': 'i420', 'token': token}
            if local:
                self._local_frame, self._local_frame_time = value, now
            else:
                self._frame, self._frame_time = value, now

    def take_frame(self):
        with self._frame_lock:
            frame, self._frame = self._frame, None
            return frame

    def take_local_frame(self):
        with self._frame_lock:
            frame, self._local_frame = self._local_frame, None
            return frame

    async def _finish(self, c, error='', *, discard=False):
        # Shutdown cancels account updates. Once cleanup has claimed a call it
        # must still reap its media child and release the capture slot, even if
        # the update or UI action that requested it is cancelled concurrently.
        cleanup = asyncio.create_task(self._finish_resources(c, error, discard=discard))
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            await cleanup
            raise

    async def _finish_resources(self, c, error='', *, discard=False):
        if self._call is not c:
            return
        c.state = 'ended'
        final = self.snapshot
        final['error'] = error
        self._call = None  # Reject all late native callbacks before stopping resources.
        self._selected.pop('screen', None)  # A later call must never inherit screen sharing.
        if c.remote:
            self._seen_ids.append(c.remote.id)
        if self._timer and self._timer is not asyncio.current_task():
            self._timer.cancel()
        self._timer = None
        if self._signal_worker:
            self._signal_worker.cancel()
            await asyncio.gather(self._signal_worker, return_exceptions=True)
        self._signal_worker = self._signal_queue = None
        engine, self._engine = self._engine, None
        cleanup_ok = True
        with self._frame_lock:
            self._frame = None
            self._local_frame = None
        if engine and c.native_created:
            started = time.monotonic()
            try:
                await asyncio.wait_for(engine.stop(c.peer), 5)
                log.info('media stopped in %.2fs', time.monotonic() - started)
            except Exception as error:
                log.info('media stop failed after %.2fs: %s', time.monotonic() - started, type(error).__name__)
                cleanup_ok = False
                final['error'] = final['error'] or 'Media cleanup failed'
        with self._capture_lock:
            if cleanup_ok and CallManager._capture_owner == c.token:
                CallManager._capture_owner = None
        if discard and c.remote:
            from telethon.tl import types
            from telethon.tl.functions.phone import DiscardCallRequest
            duration = int(time.monotonic() - c.connected_at) if c.connected_at else 0
            reason = (types.PhoneCallDiscardReasonBusy() if c.outcome=='declined' else
                      types.PhoneCallDiscardReasonHangup() if c.connected_at or c.accepted else types.PhoneCallDiscardReasonMissed())
            started = time.monotonic()
            try:
                await asyncio.wait_for(self.client(DiscardCallRequest(peer=self._input(c), duration=duration,
                    reason=reason, connection_id=0, video=c.ever_video)), 5)
                log.info('discard sent in %.2fs', time.monotonic() - started)
            except Exception as error:
                log.info('discard failed after %.2fs: %s', time.monotonic() - started, type(error).__name__)
                final['error'] = final['error'] or 'Call closed locally; Telegram is unreachable'
        self._last = final
        self._emit()

    async def close(self):
        self._closed = True
        if self._enabled:
            self.client.remove_event_handler(self._on_update)
            self._enabled = False
        task = self._starting_task
        if task and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        updates = tuple(self._updates)
        for task in updates:
            task.cancel()
        if updates:
            await asyncio.gather(*updates, return_exceptions=True)
        async with self._lock:
            if self._call:
                await self._finish(self._call, discard=True)
        for task in tuple(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        self._tasks.clear()
