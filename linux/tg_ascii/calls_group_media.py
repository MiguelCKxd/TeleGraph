"""Pinned PyTgCalls signaling with a native-only disposable binding.

No second Telegram client or session is created. This adapter is deliberately
version-specific: the upstream constructor has no binding injection parameter.
"""
import asyncio
import importlib
import importlib.metadata
import logging

from .calls_group_native import GroupNativeProxy
from .calls_process import ProcessNativeEngine


log = logging.getLogger(__name__)


class GroupMediaEngine:
    uses_hardware = True
    frames_throttled = True
    # Mobile ports replace the native binding (in-process instead of a helper
    # process), the device access prompt and the camera format.
    proxy_factory = None
    required_version = '3.0.0'
    @property
    def supports_participant_volume(self):
        import ntgcalls as nt
        return nt.__version__ == '3.0.5+tgascii.volume1' and hasattr(nt.NTgCalls, 'set_source_volume')

    def __init__(self, client, peer, on_state, on_frames, on_emojis):
        if self.required_version and importlib.metadata.version('py-tgcalls') != self.required_version:
            raise RuntimeError('Install py-tgcalls==' + self.required_version)
        self.client, self.peer = client, peer
        self.on_state, self.on_frames, self.on_emojis = on_state, on_frames, on_emojis
        self.proxy = (self.proxy_factory or GroupNativeProxy)(on_state)
        from .calls_source_volume import SourceVolumes
        self.volumes = SourceVolumes(self.proxy, peer)
        self._volume_lock = asyncio.Lock()
        self.library = None
        self.handlers = []
        self.conference = False
        self.view_only = False
        self._played = False
        self.names = {}
        self._participants_seeded = False
        self.self_id = None
        self._presentation_pending = False
        self.media_changed_unconfirmed = False
        self.known_call = None
        self._starting_conference = None

    @staticmethod
    async def devices():
        return await ProcessNativeEngine.devices()

    @staticmethod
    async def media_access(video):
        from .mac_media_access import ensure_media_access
        await ensure_media_access(video)

    @staticmethod
    async def camera_format(ident):
        from .mac_camera import camera_format
        return await asyncio.to_thread(camera_format, ident)

    async def initialize(self):
        # No await in this injection window; constructors run only on the app's
        # one Telegram loop. Avoid constructing any native call instance here.
        module = importlib.import_module('pytgcalls.pytgcalls')
        before = {callback for callback, _ in self.client.list_event_handlers()}
        original = module.NTgCalls
        module.NTgCalls = lambda: self.proxy
        try:
            self.library = module.PyTgCalls(self.client, workers=1)
        finally:
            module.NTgCalls = original
            self.handlers = [callback for callback, _ in self.client.list_event_handlers() if callback not in before]
        lib = self.library
        adapter = lib._app.mtproto_client
        original_invoke = adapter._invoke
        async def safe_invoke(request, dc_id=None, chat_id=None, sleep_threshold=None):
            from telethon import errors, functions, types, utils
            conference_creation = isinstance(request, functions.phone.CreateConferenceCallRequest)
            direct_request = isinstance(request, (
                functions.phone.JoinGroupCallRequest,
                functions.phone.CreateConferenceCallRequest,
                functions.phone.GetGroupCallChainBlocksRequest,
                functions.phone.SendConferenceCallBroadcastRequest,
            ))
            if not direct_request:
                return await original_invoke(request, dc_id=dc_id, chat_id=chat_id, sleep_threshold=sleep_threshold)
            app = adapter._app
            if chat_id is not None:
                dc_id = adapter._cache.get_dc_call(chat_id)
            borrowed = dc_id is not None and getattr(app.session, 'dc_id', None) != dc_id
            sender = await app._borrow_exported_sender(dc_id) if borrowed else app._sender
            try:
                if not hasattr(sender, 'send') or not hasattr(sender, '_pending_state'):
                    return await original_invoke(request, dc_id=dc_id, chat_id=chat_id, sleep_threshold=sleep_threshold)
                await request.resolve(app, utils)
                future = sender.send(request)
                try:
                    try:
                        result = await future
                    except errors.TimedOutError:
                        if not conference_creation:
                            raise
                        # Telegram deduplicates creation by random_id. Reuse
                        # this request once after an explicit server timeout.
                        log.debug('Retrying conference creation after Telegram timeout')
                        await asyncio.sleep(1)
                        future = sender.send(request)
                        result = await future
                    if conference_creation:
                        # Keep the exact call returned by this creation, even if
                        # invitation or media setup fails before PyTgCalls is ready.
                        self._starting_conference = next((
                            types.InputGroupCall(update.call.id, update.call.access_hash)
                            for update in getattr(result, 'updates', ())
                            if isinstance(update, types.UpdateGroupCall)
                            and isinstance(update.call, types.GroupCall)
                        ), None)
                    if getattr(app, 'session', None) is not None and hasattr(app.session, 'process_entities'):
                        await utils.maybe_async(app.session.process_entities(result))
                    return result
                except BaseException:
                    if not future.done():
                        future.cancel()
                    pending = getattr(sender, '_pending_state', None)
                    if isinstance(pending, dict):
                        for msg_id, state in list(pending.items()):
                            if getattr(state, 'request', None) is request or getattr(state, 'future', None) is future:
                                pending.pop(msg_id, None)
                    queue = getattr(getattr(sender, '_send_queue', None), '_deque', None)
                    if queue is not None:
                        for state in list(queue):
                            if getattr(state, 'request', None) is request or getattr(state, 'future', None) is future:
                                try:
                                    queue.remove(state)
                                except ValueError:
                                    pass
                    raise
            finally:
                if borrowed:
                    await app._return_exported_sender(sender)
        adapter._invoke = safe_invoke
        async def participants_from_server(call):
            from telethon import functions, utils
            rows, cursor, seen, seen_users = [], '', {''}, set()
            while True:
                page = await self.client(functions.phone.GetGroupParticipantsRequest(call, [], [], cursor, 100))
                for entity in [*getattr(page, 'users', ()), *getattr(page, 'chats', ())]:
                    self.names[utils.get_peer_id(entity)] = utils.get_display_name(entity)
                for row in page.participants:
                    parsed = adapter.parse_participant(row)
                    uid = getattr(parsed, 'user_id', None)
                    if uid is not None:
                        if uid in seen_users:
                            continue
                        seen_users.add(uid)
                    rows.append(parsed)
                following = page.next_offset
                if not following:
                    return rows
                if following in seen:
                    raise RuntimeError('Group participant cursor did not advance')
                seen.add(following)
                cursor = following
        original_timestamp = adapter.get_stream_timestamp
        async def stream_timestamp(peer):
            if peer != self.peer or not self.proxy.rtmp:
                return await original_timestamp(peer)
            from telethon import functions
            from ntgcalls import SsrcGroup
            call = await adapter.get_input_call(peer)
            result = await adapter._invoke(functions.phone.GetGroupCallStreamChannelsRequest(call), chat_id=peer)
            channels = result.channels
            if channels:
                # RTMP carries muxed audio/video in the native unified source.
                # Without subscribing it, the timestamp loop runs but no parts load.
                sources = sorted({row.channel for row in channels if row.channel > 0})
                if sources:
                    await self.proxy.add_incoming_video(peer, 0, 'unified', [SsrcGroup('SIM', sources)])
                return channels[0].last_timestamp_ms
            return 0
        adapter.get_stream_timestamp = stream_timestamp
        # Upstream 3.0.0 requests limit=0, which yields an empty participant
        # list on the current API. Preserve its cache/update flow with pages.
        adapter.get_participants = participants_from_server
        self._server_participants = participants_from_server
        cached_participants = adapter.get_group_call_participants
        async def seeded_participants(peer):
            # set_cache() creates an empty ParticipantList before any update;
            # an empty cache therefore does not mean the server has no members.
            if peer == self.peer and not self._participants_seeded:
                call = await adapter._cache.get_input_call(peer)
                if call is not None:
                    await self._refresh_participants(call)
            return await cached_participants(peer)
        adapter.get_group_call_participants = seeded_participants
        original_update = lib._handle_mtproto_updates
        async def scoped_update(update):
            from pytgcalls.types import RawCallUpdate
            if update.chat_id == self.peer and not isinstance(update, RawCallUpdate):
                from pytgcalls.types import ChatUpdate
                # Ended for everyone, removed, or the group left: PyTgCalls
                # drops its call; the manager must close ours too, even if
                # releasing the native call fails.
                left = isinstance(update, ChatUpdate) and bool(update.status & ChatUpdate.Status.LEFT_CALL)
                if left:
                    try:
                        await original_update(update)
                    except Exception as error:
                        # Server discard and local teardown can arrive together.
                        log.debug('Group cleanup during server close: %s', type(error).__name__)
                    finally:
                        self.on_state(self.peer, 'CLOSED')
                    return
                await original_update(update)
                from pytgcalls.types import UpdatedGroupCallParticipant
                if isinstance(update, UpdatedGroupCallParticipant) and self.volumes.gains:
                    rows = await cached_participants(self.peer)
                    async with self._volume_lock:
                        await self.volumes.sync(rows or ())
        lib._handle_mtproto_updates = scoped_update
        original_connection = lib._handle_connection_changed
        async def connection(key, info):
            expected = 'PRESENTATION' if self._presentation_pending else 'NORMAL'
            if key in lib._wait_connect and info.kind.name == expected:
                await original_connection(key, info)
            if key == self.peer and info.kind.name == 'NORMAL':
                if info.state.name == 'CONNECTED' and self.volumes.gains:
                    await self.participants()
                self.on_state(key, info.state.name)
        lib._handle_connection_changed = connection
        async def frames(key, mode, device, batch):
            if key != self.peer or not batch:
                return
            if mode.name == 'PLAYBACK':
                if len(batch) > 1:
                    by_ssrc = {}
                    for item in batch:
                        by_ssrc[getattr(item, 'ssrc', None)] = item
                    batch = list(by_ssrc.values())
                else:
                    batch = batch[-1:]
            if batch:
                self.on_frames(key, mode.name, 'CAMERA' if device.name == 'SCREEN' else device.name, batch)
        lib._handle_stream_frame = frames
        async def emojis(key, value):
            if key == self.peer:
                self.on_emojis(key, value)
        lib._handle_emojis_update = emojis
        # Disable upstream's optional version lookup on call startup. Updates
        # belong to the application updater, never a media connection attempt.
        from pytgcalls.pytgcalls_session import PyTgCallsSession
        PyTgCallsSession.notice_displayed = True
        await lib.start()
        if self.known_call is not None:
            # The call this account just created (see GroupCallManager.start).
            lib._app.mtproto_client._cache.set_cache(self.peer, self.known_call)
        from telethon import utils
        self.proxy.local_user_id = utils.get_peer_id(lib._cache_local_peer)
        self.self_id = self.proxy.local_user_id
        # 3.0.5 adds ParticipantsRequest to this callback; 3.0.0's handler only
        # needs the key and already builds its mapping from server participants.
        self.proxy.on_request_participants(lambda key, request:
            asyncio.run_coroutine_threadsafe(lib._handle_request_participants(key), lib.loop))

    async def stream(self, selected, video):
        from ntgcalls import MediaSource
        from pytgcalls.types.raw import Stream, AudioStream, VideoStream, AudioParameters, VideoParameters
        devices = await self.devices()
        def chosen(kind):
            options = devices.get(kind, ())
            ident = selected.get(kind)
            if ident and any(item['id'] == ident for item in options):
                return ident
            if ident or not options:
                raise ValueError('Selected device is unavailable')
            return options[0]['id']
        audio = AudioStream(MediaSource.DEVICE, chosen('microphone'), AudioParameters(48000, 1))
        screen = VideoStream(MediaSource.DESKTOP, chosen('screen'), VideoParameters(1280, 720, 15)) if selected.get('screen') else None
        camera = None
        if video:
            ident = chosen('camera')
            width, height, fps = await self.camera_format(ident)
            camera = VideoStream(MediaSource.DEVICE, ident, VideoParameters(width, height, fps))
        return Stream(microphone=audio, camera=camera, screen=screen), chosen('speaker')

    async def view_stream(self, selected):
        from ntgcalls import MediaSource
        from pytgcalls.types.raw import Stream, AudioStream, AudioParameters
        devices = await self.devices()
        options = devices.get('speaker', ())
        ident = selected.get('speaker')
        if not options or (ident and not any(row['id'] == ident for row in options)):
            raise ValueError('Selected speaker is unavailable')
        return Stream(microphone=AudioStream(MediaSource.EXTERNAL, '', AudioParameters(48000, 1))), ident or options[0]['id']

    async def start(self, selected, video, *, conference=False, listen_only=False, view_only=False):
        self.view_only = view_only
        if not (listen_only or view_only):
            await self.media_access(video)
        await self.initialize()
        from pytgcalls.types import CallConfig, GroupCallConfig, RecordStream
        from pytgcalls.media_devices import SpeakerDevice
        self.conference = conference
        if listen_only:
            from ntgcalls import MediaSource
            from pytgcalls.types.raw import Stream, AudioStream, AudioParameters
            stream, speaker = Stream(microphone=AudioStream(MediaSource.EXTERNAL, '', AudioParameters(48000, 1))), None
        elif view_only:
            stream, speaker = await self.view_stream(selected)
        else:
            stream, speaker = await self.stream(selected, video)
        config = CallConfig(conference=conference, timeout=30) if conference else GroupCallConfig(auto_start=False)
        from pytgcalls.methods.utilities.stream_params import StreamParams
        self.proxy.initial_playback = await StreamParams.get_record_params(
            RecordStream(audio=True if listen_only else SpeakerDevice('Speaker', speaker), camera=True, screen=True))
        self._played = True
        try:
            await self.library.play(self.peer, stream, config=config)
            if conference and selected.get('screen'):
                await self.presentation(True)
        except BaseException:
            if self._starting_conference is not None:
                from telethon import functions
                try:
                    await asyncio.wait_for(self.client(functions.phone.DiscardGroupCallRequest(
                        self._starting_conference)), 5)
                except Exception as error:
                    log.warning('Could not discard incomplete conference: %s', type(error).__name__)
            raise
        finally:
            self._starting_conference = None

    async def media(self, peer, selected, video, muted=False):
        if peer not in await self.proxy.calls():
            raise RuntimeError('The group call is no longer active')
        if self.view_only:
            if video or selected.get('screen'):
                raise ValueError('This stream is view only')
            stream, speaker = await self.view_stream(selected)
        else:
            stream, speaker = await self.stream(selected, video)
        from pytgcalls.types import RecordStream, CallConfig, GroupCallConfig
        from pytgcalls.methods.utilities.stream_params import StreamParams
        from pytgcalls.media_devices import SpeakerDevice
        from ntgcalls import StreamMode
        playback = await StreamParams.get_record_params(RecordStream(audio=SpeakerDevice('Speaker', speaker), camera=True, screen=True))
        # A failed negotiation must not leave a live capture that the UI still
        # represents as disabled. The manager closes an unconfirmed media change.
        self.media_changed_unconfirmed = True
        await self.proxy.set_stream_sources(peer, StreamMode.PLAYBACK, playback)
        config = CallConfig(conference=True, timeout=30) if self.conference else GroupCallConfig(auto_start=False)
        await self.library.play(peer, stream, config=config)
        if self.conference:
            # Upstream play() negotiates presentation only for GroupCallConfig;
            # conferences use CallConfig and need the same separate transport.
            await self.presentation(bool(selected.get('screen')))
        await self.mute(peer, muted)
        self.media_changed_unconfirmed = False

    async def presentation(self, enabled):
        self._presentation_pending = True
        try:
            await self.library._join_presentation(self.peer, enabled)
        finally:
            self._presentation_pending = False

    async def mute(self, peer, value):
        await (self.library.mute(peer) if value else self.library.unmute(peer))

    async def camera_effects(self, peer):
        return await self.proxy.camera_effects(peer)

    async def set_participant_volume(self, user, gain):
        if not self.supports_participant_volume:
            raise RuntimeError('Native local volume is unavailable')
        rows = await self.participants()
        if user == self.self_id:
            raise ValueError('Use the microphone control for yourself')
        async with self._volume_lock:
            await self.volumes.set(user, gain, rows)

    async def participants(self):
        return await self._refresh_participants(await self.input_call())

    async def _refresh_participants(self, call):
        if call is None:
            return []
        rows = await self._server_participants(call)
        from pytgcalls.types import GroupCallParticipant
        cache = self.library._app.mtproto_client._cache
        for row in rows:
            cache.set_participants_cache(self.peer, GroupCallParticipant.Action.UPDATED, row)
        self._participants_seeded = True
        if self.volumes.gains or self.volumes.applied:
            async with self._volume_lock:
                await self.volumes.sync(rows)
        return rows

    async def input_call(self):
        return await self.library._app.get_input_call(self.peer)

    async def stop(self, peer):
        try:
            if self._played and self.library and self.library._is_running:
                try:
                    await asyncio.wait_for(self.library.leave_call(peer), 2)
                except Exception:
                    pass
        finally:
            for callback in self.handlers:
                self.client.remove_event_handler(callback)
            self.handlers.clear()
            if self.library:
                self.library._is_running = False
                self.library.executor.shutdown(wait=False, cancel_futures=True)
            await self.proxy.close()
