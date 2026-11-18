"""On-demand channel call management; no media capture or additional session."""
import asyncio
from datetime import datetime, timezone, timedelta
import secrets
import time
from contextlib import asynccontextmanager
from telethon.errors import FloodWaitError
from telethon import functions as f, types as t, utils


class ChannelCalls:
    def __init__(self, client):
        self.client = client
        self._lock = asyncio.Lock()
        self._retry_at = 0.0
        self._read_cache = None
        self._read_until = 0.0

    @asynccontextmanager
    async def _operation(self):
        async with asyncio.timeout(20), self._lock:
            remaining = self._retry_at - time.monotonic()
            if remaining > 0:
                raise FloodWaitError(request=None, capture=max(1, int(remaining + 0.999)))
            try:
                yield
            except FloodWaitError as error:
                self._retry_at = time.monotonic() + max(0, error.seconds)
                raise

    def _invalidate(self):
        self._read_cache = None
        self._read_until = 0.0

    async def _load(self, peer):
        entity = await self.client.get_entity(peer)
        if isinstance(entity, t.Channel):
            full = await self.client(f.channels.GetFullChannelRequest(utils.get_input_channel(entity)))
        elif isinstance(entity, t.Chat):
            full = await self.client(f.messages.GetFullChatRequest(entity.id))
        else:
            raise ValueError('Select a group or channel')
        actual = next((c for c in full.chats if utils.get_peer_id(c) == utils.get_peer_id(entity)), entity)
        admin = bool(getattr(actual, 'creator', False) or getattr(getattr(actual, 'admin_rights', None), 'manage_call', False))
        handle = getattr(full.full_chat, 'call', None)
        call = (await self.client(f.phone.GetGroupCallRequest(handle, 3))).call if handle else None
        if isinstance(call, t.GroupCallDiscarded):
            handle, call = None, None
        self._group_invite = getattr(full.full_chat, 'exported_invite', None)
        return actual, admin, handle, call

    @staticmethod
    def _info(entity, admin, handle, call):
        public=bool(getattr(entity, 'username', None) or any(getattr(u, 'active', False) for u in (getattr(entity, 'usernames', None) or ())))
        return dict(public=public, can_invite=public or admin, call_id=handle.id if handle else None, admin=admin,
            active=bool(call), title=getattr(call, 'title', '') or '',
            participants_count=getattr(call, 'participants_count', 0),
            scheduled=getattr(call, 'schedule_date', None),
            subscribed=bool(getattr(call, 'schedule_start_subscribed', False)),
            rtmp=bool(getattr(call, 'rtmp_stream', False)))

    async def info(self, peer):
        async with self._operation():
            if self._read_cache is not None and self._read_cache[0] == peer and time.monotonic() < self._read_until:
                return dict(self._read_cache[1])
            entity, admin, handle, call = await self._load(peer)
            value = self._info(entity, admin, handle, call)
            self._read_cache, self._read_until = (peer, value), time.monotonic() + 2
            return dict(value)

    async def create(self, peer, *, title='', schedule=None, rtmp=False):
        if not isinstance(title, str) or type(rtmp) is not bool:
            raise ValueError('Invalid call option')
        if schedule is not None:
            if not isinstance(schedule, datetime) or schedule.tzinfo is None:
                raise ValueError('Use a date with a time zone')
            # Telegram validates its current scheduling range authoritatively.
            if schedule <= datetime.now(timezone.utc):
                raise ValueError('Choose a future date')
        async with self._operation():
            entity, admin, handle, _ = await self._load(peer)
            if not admin:
                raise PermissionError('Only call administrators can create a group call')
            if handle is not None:
                raise ValueError('Another call is already active')
            if schedule is not None and not timedelta(seconds=10) <= schedule - datetime.now(timezone.utc) <= timedelta(days=8):
                raise ValueError('Schedule between 10 seconds and 8 days from now')
            self._invalidate()
            if rtmp:
                # Telegram's RTMP flow provisions the peer endpoint before call creation.
                await self.client(f.phone.GetGroupCallStreamRtmpUrlRequest(await self.client.get_input_entity(entity), revoke=False))
            return await self.client(f.phone.CreateGroupCallRequest(
                await self.client.get_input_entity(entity), rtmp_stream=rtmp,
                random_id=secrets.randbits(31), title=title, schedule_date=schedule))

    async def change(self, peer, expected_call, action, *, enabled=None):
        if type(expected_call) is not int or action not in ('start', 'cancel', 'end', 'subscribe', 'invite', 'speaker_invite', 'rtmp', 'rotate_rtmp'):
            raise ValueError('Invalid call action')
        if action == 'subscribe' and type(enabled) is not bool:
            raise ValueError('Invalid subscription')
        async with self._operation():
            self._invalidate()
            entity, admin, handle, call = await self._load(peer)
            if handle is None or handle.id != expected_call:
                raise ValueError('This call is no longer available')
            scheduled = bool(getattr(call, 'schedule_date', None))
            if action in ('start', 'cancel', 'end', 'speaker_invite', 'rtmp', 'rotate_rtmp') and not admin:
                raise PermissionError('Only call administrators can change this setting')
            if action in ('start', 'subscribe', 'cancel') and not scheduled:
                raise ValueError('This call is not scheduled')
            if action in ('rtmp', 'rotate_rtmp') and not getattr(call, 'rtmp_stream', False):
                raise ValueError('This call does not use RTMP')
            if action == 'end' and scheduled:
                raise ValueError('This call has not started')
            public = self._info(entity, admin, handle, call)['public']
            if action == 'speaker_invite' and (not public or getattr(call, 'rtmp_stream', False)):
                raise ValueError('Speaker links require a public group or channel')
            if action == 'invite' and not public:
                if not admin:
                    raise PermissionError('Only administrators can export a private invite')
                invite = self._group_invite
                if (isinstance(invite, t.ChatInviteExported) and not invite.revoked
                        and (invite.usage_limit is None or (invite.usage or 0) < invite.usage_limit)
                        and (invite.expire_date is None or invite.expire_date > datetime.now(timezone.utc))):
                    return invite
                return await self.client(f.messages.ExportChatInviteRequest(await self.client.get_input_entity(entity),
                    request_needed=bool(getattr(invite, 'request_needed', False))))
            if action == 'start':
                request = f.phone.StartScheduledGroupCallRequest(handle)
            elif action in ('cancel', 'end'):
                request = f.phone.DiscardGroupCallRequest(handle)
            elif action == 'subscribe':
                request = f.phone.ToggleGroupCallStartSubscriptionRequest(handle, enabled)
            elif action in ('invite', 'speaker_invite'):
                request = f.phone.ExportGroupCallInviteRequest(handle, can_self_unmute=action == 'speaker_invite')
            else:
                request = f.phone.GetGroupCallStreamRtmpUrlRequest(await self.client.get_input_entity(entity), revoke=action == 'rotate_rtmp')
            return await self.client(request)
