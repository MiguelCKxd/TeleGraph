"""Account-pinned group/conference lifecycle sharing the global capture lock."""
import asyncio
import secrets
import time
from functools import wraps
from telethon import types, functions, utils

from .calls import CallManager, CallError, _Call
from .calls_group_media import GroupMediaEngine


def group_action(method):
    """Bound remote work and cancel it before closing the shared media owner."""
    @wraps(method)
    async def run(self, *args, **kwargs):
        if self._closed:
            raise CallError('Call service is closed')
        task = asyncio.current_task()
        self._active_actions.add(task)
        try:
            async with asyncio.timeout(30):
                return await method(self, *args, **kwargs)
        except BaseException as error:
            c = self._call
            if c is not None and getattr(self._engine, 'media_changed_unconfirmed', False):
                await self._finish(c, self._error(error))
            raise
        finally:
            self._active_actions.discard(task)
    return run


class GroupCallManager(CallManager):
    group_call = True
    media_engine = None  # GroupMediaEngine unless a platform provides its own
    can_manage = False
    conference = False
    view_only = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._active_actions = set()
        self._invited = {}
        self._tiles = {}
        self._tile_seen = {}

    # ---- 1.4: several incoming cameras (one tile per SSRC) -----------------
    video_grid = False  # Set from Complex features before a call starts.

    def _receive_frame(self, token, peer, mode, device, frames):
        if not self.video_grid or mode != 'PLAYBACK' or device != 'CAMERA' or not frames:
            return super()._receive_frame(token, peer, mode, device, frames)
        c = self._call
        if not c or c.token != token or c.peer != peer:
            return
        now = time.monotonic()
        for frame in frames:
            ssrc = getattr(frame, 'ssrc', None)
            info, data = frame.frame_data, frame.data
            width, height = int(info.width), int(info.height)
            expected = width * height + 2 * ((width + 1) // 2) * ((height + 1) // 2)
            if not (0 < width <= 4096 and 0 < height <= 4096 and len(data) == expected):
                continue
            rotation = int(getattr(info.rotation, 'value', info.rotation))
            value = {'width': width, 'height': height, 'rotation': rotation, 'data': bytes(data),
                     'format': 'i420', 'token': token, 'ssrc': ssrc}
            with self._frame_lock:
                self._tiles[ssrc] = value
                self._tile_seen[ssrc] = now
                if len(self._tile_seen) > 16:  # Bounded even if SSRCs churn.
                    for old in sorted(self._tile_seen, key=self._tile_seen.get)[:-16]:
                        self._tile_seen.pop(old, None)
                        self._tiles.pop(old, None)
                # Single-picture consumers keep working: newest frame of any tile.
                self._frame, self._frame_time = value, now

    def take_frames(self):
        """Latest undisplayed frame per SSRC (consumed), for the tile grid."""
        with self._frame_lock:
            frames, self._tiles = self._tiles, {}
            self._frame = None
        return frames

    def active_tiles(self, horizon=3.0):
        """SSRCs that delivered video recently, in first-seen order."""
        now = time.monotonic()
        with self._frame_lock:
            return [ssrc for ssrc, seen in self._tile_seen.items() if now - seen <= horizon]

    @property
    def snapshot(self):
        return {**super().snapshot, 'view_only': self.view_only}

    async def close(self):
        self._closed = True
        pending = tuple(task for task in self._active_actions if task is not asyncio.current_task())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await super().close()

    @group_action
    async def set_screen(self, source, *, token):
        if source and self.view_only:
            raise CallError('This stream is view only')
        return await super().set_screen(source, token=token)

    @group_action
    async def set_camera(self, value, *, token):
        if value and self.view_only:
            raise CallError('This stream is view only')
        return await super().set_camera(value, token=token)

    @group_action
    async def mute(self, value, *, token):
        if not value and self.view_only:
            raise CallError('This stream is view only')
        return await super().mute(value, token=token)

    @group_action
    async def camera_effects(self, *, token):
        return await super().camera_effects(token=token)

    @group_action
    async def select_devices(self, microphone='', speaker='', camera='', *, token=None):
        return await super().select_devices(microphone, speaker, camera, token=token)

    async def enable(self):
        if self._closed:
            raise CallError('Call service is closed')
        self._loop = asyncio.get_running_loop()
        self._enabled = True

    async def _media_access(self, video):
        from .mac_media_access import ensure_media_access
        await ensure_media_access(video)

    async def start(self, peer, video=False, *, conference=False, create=False, view_only=False):
        async with self._lock:
            if self._closed or self._call:
                raise CallError('Another call is already active')
            self._starting_task = asyncio.current_task()
            c = None
            created_call = None
            try:
                if type(view_only) is not bool or (view_only and (video or conference or create)):
                    raise ValueError('Invalid view-only call option')
                entity = await asyncio.wait_for(self.client.get_entity(peer), 15)
                if self._closed:
                    raise CallError('Call service is closed')
                if conference:
                    if not isinstance(entity, types.User) or entity.bot or entity.deleted or entity.is_self:
                        raise CallError('Invalid conference participant')
                elif not isinstance(entity, (types.Channel, types.Chat)):
                    raise CallError('Select a group or channel')
                self._invited.clear()
                with self._frame_lock:
                    self._tiles.clear()
                    self._tile_seen.clear()
                self.view_only = view_only
                self.conference = bool(conference)
                self.can_manage = bool(conference is True or getattr(entity, 'creator', False)
                    or getattr(getattr(entity, 'admin_rights', None), 'manage_call', False))
                c = self._call = _Call(utils.get_peer_id(entity), False, bool(video))
                c.muted = view_only
                with self._capture_lock:
                    if CallManager._capture_owner not in (None, c.token):
                        self._call = None
                        raise CallError('Another account already has an active call')
                    CallManager._capture_owner = c.token
                self._emit()
                await self.enable()
                if create:
                    if conference or not self.can_manage:
                        raise CallError('Only call administrators can create a group call')
                    await self._media_access(video)
                    request = functions.channels.GetFullChannelRequest(utils.get_input_channel(entity)) if isinstance(entity, types.Channel) else functions.messages.GetFullChatRequest(entity.id)
                    full = await asyncio.wait_for(self.client(request), 15)
                    handle = getattr(full.full_chat, 'call', None)
                    if handle is not None:
                        # A call ended moments ago can still be referenced: a
                        # discarded call does not count as the active one.
                        try:
                            current = await asyncio.wait_for(self.client(functions.phone.GetGroupCallRequest(handle, 1)), 15)
                            if isinstance(getattr(current, 'call', None), types.GroupCallDiscarded):
                                handle = None
                        except Exception as error:
                            if 'DISCARDED' not in str(error).upper():
                                raise
                            handle = None
                    if handle is None:
                        input_peer = await asyncio.wait_for(self.client.get_input_entity(entity), 15)
                        created = await asyncio.wait_for(self.client(functions.phone.CreateGroupCallRequest(
                            input_peer, random_id=secrets.randbits(31))), 15)
                        # Join exactly this call: right after creation the group
                        # can still point at the previous, discarded one.
                        created_call = next((types.InputGroupCall(update.call.id, update.call.access_hash)
                                             for update in getattr(created, 'updates', None) or ()
                                             if isinstance(update, types.UpdateGroupCall)
                                             and isinstance(update.call, types.GroupCall)), None)
                def state(key, value):
                    self._schedule(self._native_state(c.token, key, value))
                def frame(key, mode, device, values):
                    if self._call is c and mode == 'PLAYBACK' and not c.remote_video:
                        c.remote_video = True
                        self._emit()
                    self._receive_frame(c.token, key, mode, device, values)
                self._engine = (self.media_engine or GroupMediaEngine)(self.client, c.peer, state, frame,
                    lambda key, value: self._set_emojis(c.token, key, value))
                if created_call is not None:
                    self._engine.known_call = created_call
                proxy = getattr(self._engine, 'proxy', None)
                if proxy is not None:
                    from .calls_group_native import MAX_INCOMING_VIDEOS
                    proxy.max_videos = MAX_INCOMING_VIDEOS if self.video_grid else 1
                c.native_created = True
                await asyncio.wait_for(self._engine.start(self._selected, c.video, conference=conference,
                    **({'view_only': True} if view_only else {})), 45)
                c.connected = True
                c.state, c.connected_at = 'active', time.monotonic()
                self._emit()
                return self.snapshot
            except BaseException as error:
                if c is not None and self._call is c:
                    await self._finish(c, str(error))
                raise
            finally:
                self._starting_task = None

    async def _finish(self, c, error='', *, discard=False):
        # The group adapter leaves its InputGroupCall. Never send the P2P
        # DiscardCall RPC inherited by the individual-call implementation.
        try:
            await super()._finish(c, error, discard=False)
        finally:
            if self._call is None or self._call is c:
                with self._frame_lock:
                    self._tiles.clear()
                    self._tile_seen.clear()

    async def _control_info(self):
        handle = await self._engine.input_call()
        result = await self.client(functions.phone.GetGroupCallRequest(handle, 0))
        call = result.call
        if isinstance(call, types.GroupCallDiscarded):
            return handle, dict(active=False)
        conference = bool(getattr(call, 'conference', False) or self._engine.conference)
        return handle, dict(active=True, title=getattr(call, 'title', '') or '',
            participants_count=call.participants_count, conference=conference,
            scheduled=getattr(call, 'schedule_date', None),
            recording=bool(getattr(call, 'record_start_date', None)),
            recording_video=bool(getattr(call, 'record_video_active', False)),
            join_muted=bool(getattr(call, 'join_muted', False)),
            can_edit_title=self.can_manage and not conference,
            can_record=self.can_manage and not conference,
            can_change_join_muted=self.can_manage and bool(getattr(call, 'can_change_join_muted', False)) and not conference)

    @group_action
    async def control_info(self, *, token):
        async with self._lock:
            self._check(token=token)
            return (await self._control_info())[1]

    @group_action
    async def edit_title(self, title, *, token):
        async with self._lock:
            self._check(token=token)
            if not isinstance(title, str):
                raise ValueError('Invalid call title')
            handle, info = await self._control_info()
            if not info.get('can_edit_title'):
                raise CallError('Call title cannot be changed')
            return await self.client(functions.phone.EditGroupCallTitleRequest(handle, title))

    @group_action
    async def set_join_muted(self, value, *, token):
        async with self._lock:
            self._check(token=token)
            if type(value) is not bool:
                raise ValueError('Invalid join setting')
            handle, info = await self._control_info()
            if not info.get('can_change_join_muted'):
                raise CallError('Join settings cannot be changed')
            return await self.client(functions.phone.ToggleGroupCallSettingsRequest(handle, join_muted=value))

    @group_action
    async def set_recording(self, enabled, *, token, title='', video=False, portrait=False):
        async with self._lock:
            self._check(token=token)
            if any(type(value) is not bool for value in (enabled, video, portrait)):
                raise ValueError('Invalid recording option')
            if not isinstance(title, str) or (portrait and not video):
                raise ValueError('Invalid recording layout')
            handle, info = await self._control_info()
            if not info.get('can_record'):
                raise CallError('Call recording is unavailable')
            return await self.client(functions.phone.ToggleGroupCallRecordRequest(handle,
                start=enabled, video=video if enabled else None,
                video_portrait=portrait if enabled and video else None, title=title if enabled else None))

    @group_action
    async def participants(self, *, token, offset=0):
        async with self._lock:
            self._check(token=token)
            if type(offset) is not int or offset < 0:
                raise ValueError('Invalid participant offset')
            participants = await asyncio.wait_for(self._engine.participants(), 15)
            result = []
            for participant in (participants or ())[offset:offset + 100]:
                result.append(dict(id=participant.user_id, muted=participant.muted,
                    name=getattr(self._engine, 'names', {}).get(participant.user_id, ''),
                    is_self=participant.user_id == getattr(self._engine, 'self_id', None),
                    raised_hand=bool(getattr(participant, 'raised_hand', False)),
                    muted_by_admin=bool(getattr(participant, 'muted_by_admin', False)),
                    volume=(self._engine.volumes.percent(participant.user_id)
                        if getattr(self._engine, 'supports_participant_volume', False)
                        else getattr(participant, 'volume', 100)),
                    can_raise_hand=not (self.view_only or bool(getattr(self._engine, 'conference', False))),
                    can_set_volume=bool(getattr(self._engine, 'supports_participant_volume', False)),
                    video=getattr(participant, 'video_camera', False),
                    screen=getattr(participant, 'screen_sharing', False)))
            joined={p.user_id for p in (participants or ())}
            for user_id in joined:self._invited.pop(user_id,None)
            pending=[dict(id=user_id,name=details['name'],muted=False,video=False,screen=False,
                          invitation=True,invitation_state='pending',can_set_volume=False,
                          can_raise_hand=False,is_self=False) for user_id,details in self._invited.items()]
            # Pending invitees are separate from the server's joined participant count.
            combined=[dict(id=p.user_id) for p in (participants or ())]+pending
            start=max(0,offset-len(participants or ()))
            if offset+100>len(participants or ()):result.extend(pending[start:start+100-len(result)])
            return dict(items=result,next=offset+100 if offset+100<len(combined) else None)


    @group_action
    async def invite(self, user, *, token):
        async with self._lock:
            self._check(token=token)
            entity = await self.client.get_entity(user)
            if not isinstance(entity, types.User) or entity.bot or entity.deleted:
                raise CallError('Invalid conference participant')
            call = await self._engine.input_call()
            if self._engine.conference:
                response=await self.client(functions.phone.InviteConferenceCallParticipantRequest(call, utils.get_input_user(entity)))
            else:
                response=await self.client(functions.phone.InviteToGroupCallRequest(call, [utils.get_input_user(entity)]))
            self._invited[entity.id]={'name':utils.get_display_name(entity),'time':time.monotonic()}
            while len(self._invited)>500:self._invited.pop(next(iter(self._invited)))
            return response


    @group_action
    async def local_participant_volume(self, user, *, token, volume):
        async with self._lock:
            self._check(token=token)
            await self._engine.set_participant_volume(user, volume)

    @group_action
    async def participant_action(self, user, *, token, volume=None, muted=None, raise_hand=None):
        async with self._lock:
            self._check(token=token)
            if any(value is not None and type(value) is not bool for value in (muted, raise_hand)):
                raise ValueError('Invalid participant flag')
            if volume is not None and (type(volume) is not int or not 1 <= volume <= 20000):
                raise ValueError('Invalid call volume')
            me = await self.client.get_me()
            if muted is not None and user != me.id and not self.can_manage:
                raise CallError('Only call administrators can mute other participants')
            if raise_hand is not None:
                if self._engine.conference:
                    raise CallError('Hands are unavailable in conference calls')
                if user != me.id and not (self.can_manage and raise_hand is False):
                    raise CallError('Only your own hand can be raised')
            call = await self._engine.input_call()
            return await self.client(functions.phone.EditGroupCallParticipantRequest(call,
                await self.client.get_input_entity(user), volume=volume, muted=muted, raise_hand=raise_hand))

    @group_action
    async def view_participant(self, user, *, token, screen=False):
        async with self._lock:
            self._check(token=token)
            participants = await self._engine.participants()
            participant = next((item for item in participants if item.user_id == user), None)
            if participant is None:
                return
            info = participant.presentation_info if screen else participant.video_info
            if info is None:
                return
            await self._engine.proxy.select_video(self._call.peer, user, info.endpoint)
            with self._frame_lock:
                self._frame = None

    @group_action
    async def end_for_everyone(self, *, token):
        async with self._lock:
            c = self._check(token=token)
            if not self.can_manage:
                raise CallError('Only call administrators can end this call for everyone')
            try:
                call = await asyncio.wait_for(self._engine.input_call(), 15)
                await asyncio.wait_for(self.client(functions.phone.DiscardGroupCallRequest(call)), 15)
            finally:
                await self._finish(c)
