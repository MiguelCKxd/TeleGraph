import unittest
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,Mock
from telethon import types as t,functions as f
from tg_ascii.channel_calls import ChannelCalls


class ChannelCallTests(unittest.IsolatedAsyncioTestCase):
    def setup_client(self,creator=True,call=None):
        entity=t.Channel(41,'QA',t.ChatPhotoEmpty(),datetime.now(timezone.utc),access_hash=99,megagroup=True,creator=creator)
        self.full=NS(chats=[entity],full_chat=NS(call=t.InputGroupCall(12,34) if call else None))
        self.live=NS(call=call)
        async def rpc(request):
            if isinstance(request,f.channels.GetFullChannelRequest):return self.full
            if isinstance(request,f.phone.GetGroupCallRequest):return self.live
            return True
        self.rpc=AsyncMock(side_effect=rpc)
        self.client=Mock(side_effect=self.rpc)
        self.client.get_entity=AsyncMock(return_value=entity)
        self.client.get_input_entity=AsyncMock(return_value=t.InputPeerChannel(41,99))
        return ChannelCalls(self.client)

    async def test_create_schedule_and_rtmp_does_not_start_native_capture(self):
        service=self.setup_client()
        date=datetime.now(timezone.utc)+timedelta(hours=1)
        await service.create(-1000000000041,title='QA',schedule=date,rtmp=True)
        request=self.rpc.call_args.args[0]
        self.assertIsInstance(request,f.phone.CreateGroupCallRequest)
        self.assertEqual(request.schedule_date,date)
        self.assertTrue(request.rtmp_stream)
        self.assertEqual(request.title,'QA')

    async def test_existing_call_cannot_be_overwritten_by_stale_creation(self):
        service=self.setup_client(call=NS(participants_count=2))
        with self.assertRaises(ValueError):await service.create(-1000000000041)
        self.assertFalse(any(isinstance(c.args[0],f.phone.CreateGroupCallRequest) for c in self.rpc.call_args_list))

    async def test_replaced_call_never_receives_old_actions(self):
        service=self.setup_client(call=NS(participants_count=2))
        for action in ('start','cancel','invite','rtmp'):
            with self.assertRaises(ValueError):await service.change(-1000000000041,999,action)
        self.assertTrue(all(isinstance(c.args[0],(f.channels.GetFullChannelRequest,f.phone.GetGroupCallRequest)) for c in self.rpc.call_args_list))

    async def test_revoked_admin_rights_are_reloaded_before_write(self):
        service=self.setup_client(creator=True,call=NS(participants_count=2,rtmp_stream=True))
        fresh=t.Channel(41,'QA',t.ChatPhotoEmpty(),datetime.now(timezone.utc),access_hash=99,megagroup=True)
        self.full.chats=[fresh]
        with self.assertRaises(PermissionError):await service.change(-1000000000041,12,'rotate_rtmp')
        self.assertFalse(any(isinstance(c.args[0],f.phone.GetGroupCallStreamRtmpUrlRequest) for c in self.rpc.call_args_list))

    async def test_non_admin_can_subscribe_but_cannot_publish_or_cancel(self):
        service=self.setup_client(creator=False,call=NS(participants_count=2,schedule_date=datetime.now(timezone.utc)))
        await service.change(-1000000000041,12,'subscribe',enabled=True)
        self.assertIsInstance(self.rpc.call_args.args[0],f.phone.ToggleGroupCallStartSubscriptionRequest)
        for action in ('start','cancel','speaker_invite','rtmp'):
            with self.assertRaises(PermissionError):await service.change(-1000000000041,12,action)

    async def test_rtmp_lookup_never_rotates_the_key_implicitly(self):
        service=self.setup_client(call=NS(participants_count=2,rtmp_stream=True))
        await service.change(-1000000000041,12,'rtmp')
        self.assertFalse(self.rpc.call_args.args[0].revoke)
        await service.change(-1000000000041,12,'rotate_rtmp')
        self.assertTrue(self.rpc.call_args.args[0].revoke)

    async def test_cancel_scheduled_call_cannot_terminate_call_that_started(self):
        service=self.setup_client(call=NS(participants_count=2))
        with self.assertRaises(ValueError):await service.change(41,12,'cancel')
        self.assertFalse(any(isinstance(c.args[0],f.phone.DiscardGroupCallRequest) for c in self.rpc.call_args_list))

    async def test_flood_wait_prevents_repeat_network_calls(self):
        from telethon.errors import FloodWaitError
        service=self.setup_client()
        self.rpc.side_effect=FloodWaitError(request=None,capture=60)
        with self.assertRaises(FloodWaitError):await service.info(41)
        count=self.rpc.await_count
        with self.assertRaises(FloodWaitError):await service.info(41)
        self.assertEqual(self.rpc.await_count,count)

    async def test_repeated_read_is_cached_but_mutation_refreshes_permissions(self):
        service=self.setup_client(call=NS(participants_count=2,rtmp_stream=True))
        await service.info(41)
        count=self.rpc.await_count
        await service.info(41)
        self.assertEqual(self.rpc.await_count,count)
        await service.change(41,12,'rtmp')
        self.assertGreater(self.rpc.await_count,count)

    async def test_invalid_schedule_and_flags_are_rejected_before_rpc(self):
        service=self.setup_client()
        for value in (datetime.now(),datetime.now(timezone.utc)-timedelta(hours=1),'tomorrow'):
            with self.assertRaises(ValueError):await service.create(41,schedule=value)
        with self.assertRaises(ValueError):await service.create(41,rtmp=1)
        self.rpc.assert_not_awaited()
