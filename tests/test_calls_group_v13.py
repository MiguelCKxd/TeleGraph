"""Group lifecycle regression: no transport, real native devices or account files."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch
from telethon import types, functions

from tg_ascii.calls import CallManager, CallError
from tg_ascii.calls_group import GroupCallManager


class FakeGroupMedia:
    self_id = 7
    instances = []
    fail = False
    wait = None
    def __init__(self, *args):
        self.args = args
        self.stopped = False
        self.conference = False
        self.instances.append(self)
    async def start(self, selected, video, *, conference=False):
        self.conference = conference
        if self.wait is not None: await self.wait.wait()
        if self.fail: raise RuntimeError('Server join denied')
    async def stop(self, peer):
        await asyncio.sleep(.001)
        self.stopped = True
    async def participants(self): return []
    async def input_call(self): return types.InputGroupCall(123, 456)


class GroupLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertIsNone(CallManager._capture_owner)
        FakeGroupMedia.instances, FakeGroupMedia.fail, FakeGroupMedia.wait = [], False, None
        self.rpc = AsyncMock()
        self.client = Mock(side_effect=self.rpc)
        self.client.get_entity = AsyncMock(return_value=types.Channel(41, 'Synthetic group', types.ChatPhotoEmpty(), datetime.now(timezone.utc), megagroup=True))
        self.client.get_me = AsyncMock(return_value=types.User(7, is_self=True))
        self.client.get_input_entity = AsyncMock(return_value=types.InputPeerUser(8, 9))
        self.events = []
        self.manager = GroupCallManager(self.client, self.events.append, available=lambda: True)
        self.engine_patch = patch('tg_ascii.calls_group.GroupMediaEngine', FakeGroupMedia)
        self.engine_patch.start()
        self.permission_patch = patch('tg_ascii.mac_media_access.ensure_media_access', new_callable=AsyncMock)
        self.permission_check = self.permission_patch.start()

    async def asyncTearDown(self):
        await self.manager.close()
        self.engine_patch.stop()
        self.permission_patch.stop()
        self.assertIsNone(CallManager._capture_owner)

    async def test_hangup_closes_media_before_releasing_capture_without_p2p_discard(self):
        snapshot = await self.manager.start(-1000000000041)
        self.assertEqual(snapshot['state'], 'active')
        engine = FakeGroupMedia.instances[-1]
        await self.manager.hangup(token=snapshot['token'])
        self.assertTrue(engine.stopped)
        self.assertIsNone(CallManager._capture_owner)
        self.client.assert_not_called()

    async def test_server_join_failure_still_releases_native_resources(self):
        FakeGroupMedia.fail = True
        with self.assertRaisesRegex(RuntimeError, 'Server join denied'):
            await self.manager.start(-1000000000041)
        self.assertTrue(FakeGroupMedia.instances[-1].stopped)
        self.assertIsNone(CallManager._capture_owner)

    async def test_cancelled_join_does_not_leave_capture_owned(self):
        FakeGroupMedia.wait = asyncio.Event()
        task = asyncio.create_task(self.manager.start(-1000000000041))
        while not FakeGroupMedia.instances: await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(FakeGroupMedia.instances[-1].stopped)
        self.assertIsNone(CallManager._capture_owner)

    async def test_existing_individual_call_cannot_lose_hardware_to_group(self):
        CallManager._capture_owner = 'existing-individual-call'
        try:
            with self.assertRaises(CallError): await self.manager.start(-1000000000041)
            self.assertEqual(CallManager._capture_owner, 'existing-individual-call')
            self.assertFalse(FakeGroupMedia.instances)
        finally:
            CallManager._capture_owner = None

    async def test_app_shutdown_cancels_group_join_instead_of_waiting_for_remote_timeout(self):
        FakeGroupMedia.wait = asyncio.Event()
        task = asyncio.create_task(self.manager.start(-1000000000041))
        while not FakeGroupMedia.instances: await asyncio.sleep(0)
        await asyncio.wait_for(self.manager.close(), .5)
        self.assertTrue(task.cancelled())
        self.assertTrue(FakeGroupMedia.instances[-1].stopped)
        self.assertIsNone(CallManager._capture_owner)

    async def test_stale_invite_and_moderation_never_reach_server(self):
        snapshot = await self.manager.start(-1000000000041)
        self.client.get_entity.reset_mock()
        with self.assertRaises(CallError): await self.manager.invite('@synthetic', token='stale')
        self.client.get_entity.assert_not_awaited()
        with self.assertRaises(CallError):
            await self.manager.participant_action(8, token=snapshot['token'], muted=True)
        self.client.assert_not_called()

    async def test_local_volume_uses_native_engine_only_and_rejects_stale_call(self):
        snapshot = await self.manager.start(-1000000000041)
        engine = self.manager._engine
        engine.set_participant_volume = AsyncMock()
        await self.manager.local_participant_volume(8, token=snapshot['token'], volume=0)
        engine.set_participant_volume.assert_awaited_once_with(8, 0)
        self.client.assert_not_called()
        with self.assertRaises(CallError):
            await self.manager.local_participant_volume(8, token='expired', volume=5000)
        engine.set_participant_volume.assert_awaited_once()

    async def test_livestream_admin_controls_use_server_handle_and_preserve_recording_layout(self):
        self.client.get_entity.return_value.creator = True
        snapshot = await self.manager.start(-1000000000041)
        self.rpc.return_value = NS(call=NS(participants_count=2, title='Live', can_change_join_muted=True))
        info = await self.manager.control_info(token=snapshot['token'])
        self.assertTrue(info['can_edit_title'])
        await self.manager.edit_title('New title', token=snapshot['token'])
        self.assertIsInstance(self.rpc.call_args.args[0], functions.phone.EditGroupCallTitleRequest)
        self.assertEqual(self.rpc.call_args.args[0].title, 'New title')
        await self.manager.set_join_muted(True, token=snapshot['token'])
        self.assertTrue(self.rpc.call_args.args[0].join_muted)
        await self.manager.set_recording(True, token=snapshot['token'], video=True, portrait=True, title='Recording')
        request = self.rpc.call_args.args[0]
        self.assertIsInstance(request, functions.phone.ToggleGroupCallRecordRequest)
        self.assertTrue(request.start and request.video and request.video_portrait)
        await self.manager.set_recording(False, token=snapshot['token'])
        request = self.rpc.call_args.args[0]
        self.assertFalse(request.start)
        self.assertIsNone(request.video)
        self.assertIsNone(request.video_portrait)

    async def test_livestream_controls_are_hidden_for_conferences_and_non_admins(self):
        self.client.get_entity.return_value = types.User(8, access_hash=9)
        snapshot = await self.manager.start(8, conference=True)
        self.rpc.return_value = NS(call=NS(participants_count=2, can_change_join_muted=True))
        info = await self.manager.control_info(token=snapshot['token'])
        self.assertFalse(info['can_edit_title'])
        self.assertFalse(info['can_record'])
        self.assertFalse(info['can_change_join_muted'])
        with self.assertRaises(CallError):
            await self.manager.set_recording(True, token=snapshot['token'])
        self.assertTrue(all(isinstance(c.args[0], functions.phone.GetGroupCallRequest) for c in self.rpc.call_args_list))

    async def test_stale_livestream_action_cannot_query_or_modify_another_call(self):
        await self.manager.start(-1000000000041)
        with self.assertRaises(CallError):
            await self.manager.edit_title('Wrong call', token='expired')
        self.rpc.assert_not_awaited()

    async def test_view_only_blocks_capture_controls_before_native_requests(self):
        original=FakeGroupMedia.start
        async def start(engine,selected,video,*,conference=False,view_only=False):
            engine.view_only=view_only
            await original(engine,selected,video,conference=conference)
        with patch.object(FakeGroupMedia,'start',start):
            snapshot=await self.manager.start(-1000000000041,view_only=True)
        self.assertTrue(snapshot['muted'])
        self.assertTrue(snapshot['view_only'])
        for coroutine in (self.manager.mute(False,token=snapshot['token']),
                          self.manager.set_camera(True,token=snapshot['token']),
                          self.manager.set_screen('screen',token=snapshot['token'])):
            with self.assertRaises(CallError):await coroutine
        self.assertTrue(FakeGroupMedia.instances[-1].view_only)

    async def test_create_never_replaces_existing_group_call(self):
        entity = self.client.get_entity.return_value
        entity.creator, entity.access_hash = True, 88
        self.rpc.return_value = NS(full_chat=NS(call=types.InputGroupCall(123, 456)))
        await self.manager.start(-1000000000041, create=True)
        requests = [call.args[0] for call in self.rpc.await_args_list]
        self.assertIsInstance(requests[0], functions.channels.GetFullChannelRequest)
        self.assertFalse(any(isinstance(request, functions.phone.CreateGroupCallRequest) for request in requests))

    async def test_create_starts_a_voice_chat_not_an_rtmp_stream(self):
        entity = self.client.get_entity.return_value
        entity.creator, entity.access_hash = True, 88
        self.rpc.side_effect = lambda request: NS(full_chat=NS(call=None)) if isinstance(
            request, functions.channels.GetFullChannelRequest) else NS()
        await self.manager.start(-1000000000041, create=True)
        created = [call.args[0] for call in self.rpc.await_args_list
                   if isinstance(call.args[0], functions.phone.CreateGroupCallRequest)]
        self.assertEqual(len(created), 1)
        self.assertFalse(created[0].rtmp_stream)
        self.assertIsInstance(created[0].random_id, int)

    async def test_create_replaces_a_call_that_was_just_discarded(self):
        entity = self.client.get_entity.return_value
        entity.creator, entity.access_hash = True, 88
        def rpc(request):
            if isinstance(request, functions.channels.GetFullChannelRequest):
                return NS(full_chat=NS(call=types.InputGroupCall(123, 456)))
            if isinstance(request, functions.phone.GetGroupCallRequest):
                return NS(call=types.GroupCallDiscarded(123, 456, 0))
            return NS()
        self.rpc.side_effect = rpc
        await self.manager.start(-1000000000041, create=True)
        self.assertTrue(any(isinstance(call.args[0], functions.phone.CreateGroupCallRequest)
                            for call in self.rpc.await_args_list))

    async def test_native_closed_state_ends_the_group_call(self):
        self.rpc.return_value = NS(full_chat=NS(call=types.InputGroupCall(123, 456)))
        started = await self.manager.start(-1000000000041)
        self.assertEqual(started['state'], 'active')
        on_state = FakeGroupMedia.instances[-1].args[2]
        on_state(-1000000000041, 'CLOSED')
        for _ in range(20):
            await asyncio.sleep(.01)
            if self.manager.snapshot['state'] == 'ended':
                break
        self.assertEqual(self.manager.snapshot['state'], 'ended')
        self.assertTrue(FakeGroupMedia.instances[-1].stopped)

    async def test_engine_joins_the_call_it_just_created(self):
        entity = self.client.get_entity.return_value
        entity.creator, entity.access_hash = True, 88
        new_call = types.GroupCall(321, 654, 1, 0, 1)
        def rpc(request):
            if isinstance(request, functions.channels.GetFullChannelRequest):
                return NS(full_chat=NS(call=None))
            if isinstance(request, functions.phone.CreateGroupCallRequest):
                return NS(updates=[types.UpdateGroupCall(new_call, peer=types.PeerChannel(41))])
            return NS()
        self.rpc.side_effect = rpc
        await self.manager.start(-1000000000041, create=True)
        self.assertEqual(FakeGroupMedia.instances[-1].known_call, types.InputGroupCall(321, 654))

    async def test_permission_denial_never_creates_group_call(self):
        entity = self.client.get_entity.return_value
        entity.creator = True
        self.permission_check.side_effect = PermissionError('Denied')
        with self.assertRaises(PermissionError):
            await self.manager.start(-1000000000041, create=True)
        self.rpc.assert_not_awaited()
        self.assertFalse(FakeGroupMedia.instances)

    async def test_receiver_of_conference_invitation_is_not_assumed_to_be_creator(self):
        self.client.get_entity.return_value = types.User(8, access_hash=9)
        snapshot = await self.manager.start(8, conference=123)
        self.assertFalse(self.manager.can_manage)
        with self.assertRaises(CallError):
            await self.manager.end_for_everyone(token=snapshot['token'])
        self.rpc.assert_not_awaited()

    async def test_conference_creator_can_end_server_call_without_p2p_discard(self):
        self.client.get_entity.return_value = types.User(8, access_hash=9)
        snapshot = await self.manager.start(8, conference=True)
        await self.manager.end_for_everyone(token=snapshot['token'])
        request = self.rpc.call_args.args[0]
        self.assertIsInstance(request, functions.phone.DiscardGroupCallRequest)
        self.assertEqual(request.call.id, 123)
        self.assertTrue(FakeGroupMedia.instances[-1].stopped)

    async def test_failed_server_end_still_reaps_media_and_releases_hardware(self):
        self.client.get_entity.return_value = types.User(8, access_hash=9)
        snapshot = await self.manager.start(8, conference=True)
        self.rpc.side_effect = RuntimeError('Server unreachable')
        with self.assertRaisesRegex(RuntimeError, 'Server unreachable'):
            await self.manager.end_for_everyone(token=snapshot['token'])
        self.assertTrue(FakeGroupMedia.instances[-1].stopped)
        self.assertIsNone(CallManager._capture_owner)

    async def test_shutdown_during_failure_cleanup_does_not_abort_reaping(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original_stop = FakeGroupMedia.stop
        async def slow_stop(engine, peer):
            entered.set()
            await release.wait()
            await original_stop(engine, peer)
        FakeGroupMedia.fail = True
        with patch.object(FakeGroupMedia, 'stop', slow_stop):
            task = asyncio.create_task(self.manager.start(-1000000000041))
            await entered.wait()
            closing = asyncio.create_task(self.manager.close())
            await asyncio.sleep(.01)
            release.set()
            await asyncio.wait_for(closing, .5)
            await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(FakeGroupMedia.instances[-1].stopped)
        self.assertIsNone(CallManager._capture_owner)

    async def test_shutdown_cancels_remote_action_and_queued_actions_before_reaping_media(self):
        snapshot = await self.manager.start(-1000000000041)
        entered = asyncio.Event()
        async def blocked(*args):
            entered.set()
            await asyncio.Event().wait()
        self.rpc.side_effect = blocked
        first = asyncio.create_task(self.manager.participant_action(8, token=snapshot['token'], volume=10000))
        await entered.wait()
        second = asyncio.create_task(self.manager.participants(token=snapshot['token']))
        await asyncio.sleep(0)
        await asyncio.wait_for(self.manager.close(), .5)
        self.assertTrue(first.cancelled())
        self.assertTrue(second.cancelled())
        self.assertTrue(FakeGroupMedia.instances[-1].stopped)
        self.assertFalse(self.manager._active_actions)
        self.assertIsNone(CallManager._capture_owner)
        with self.assertRaises(CallError):
            await self.manager.participants(token=snapshot['token'])

    async def test_volume_zero_and_invalid_types_are_never_sent_to_server(self):
        snapshot = await self.manager.start(-1000000000041)
        for value in (0, -1, 20001, True, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                await self.manager.participant_action(8, token=snapshot['token'], volume=value)
        self.rpc.assert_not_awaited()
        self.client.get_me.assert_not_awaited()
        for value in (1, 20000):
            await self.manager.participant_action(8, token=snapshot['token'], volume=value)
            self.assertEqual(self.rpc.call_args.args[0].volume, value)

    async def test_own_hand_and_admin_lowering_follow_group_call_permissions(self):
        snapshot = await self.manager.start(-1000000000041)
        for value in (True, False):
            await self.manager.participant_action(7, token=snapshot['token'], raise_hand=value)
            self.assertIs(self.rpc.call_args.args[0].raise_hand, value)
        with self.assertRaises(CallError):
            await self.manager.participant_action(8, token=snapshot['token'], raise_hand=False)
        self.manager.can_manage = True
        await self.manager.participant_action(8, token=snapshot['token'], raise_hand=False)
        with self.assertRaises(CallError):
            await self.manager.participant_action(8, token=snapshot['token'], raise_hand=True)

    async def test_hand_controls_are_rejected_in_conference_without_rpc(self):
        self.client.get_entity.return_value = types.User(8, access_hash=9)
        snapshot = await self.manager.start(8, conference=True)
        with self.assertRaises(CallError):
            await self.manager.participant_action(7, token=snapshot['token'], raise_hand=True)
        self.rpc.assert_not_awaited()

    async def test_participant_capabilities_and_percent_volume_are_available_without_extra_identity_rpc(self):
        snapshot = await self.manager.start(-1000000000041)
        self.manager._engine.participants = AsyncMock(return_value=[NS(user_id=7, muted=True,
            raised_hand=True, muted_by_admin=False, volume=125)])
        page = await self.manager.participants(token=snapshot['token'])
        self.assertTrue(page['items'][0]['is_self'])
        self.assertTrue(page['items'][0]['can_raise_hand'])
        self.assertEqual(page['items'][0]['volume'], 125)
        self.client.get_me.assert_not_awaited()

    async def test_failed_partial_media_change_closes_capture_instead_of_showing_screen_off(self):
        snapshot = await self.manager.start(-1000000000041)
        engine = self.manager._engine
        self.manager.devices = AsyncMock(return_value={'screen': [{'id': 'screen'}]})
        async def failed(*args):
            engine.media_changed_unconfirmed = True
            raise RuntimeError('Presentation failed after capture started')
        engine.media = failed
        with self.assertRaisesRegex(RuntimeError, 'Presentation failed'):
            await self.manager.set_screen('screen', token=snapshot['token'])
        self.assertTrue(engine.stopped)
        self.assertIsNone(CallManager._capture_owner)
        self.assertIsNone(self.manager._call)


    async def test_pending_invite_is_separate_then_disappears_when_joined(self):
        snapshot=await self.manager.start(-1000000000041)
        self.client.get_entity.return_value=types.User(8,first_name='Public fixture')
        await self.manager.invite(8,token=snapshot['token'])
        page=await self.manager.participants(token=snapshot['token'])
        self.assertTrue(page['items'][0]['invitation']);self.assertEqual(page['items'][0]['name'],'Public fixture')
        self.manager._engine.participants=AsyncMock(return_value=[NS(user_id=8,muted=False)])
        page=await self.manager.participants(token=snapshot['token'])
        self.assertEqual(len(page['items']),1);self.assertFalse(page['items'][0].get('invitation',False));self.assertFalse(self.manager._invited)

    async def test_failed_invite_is_not_marked_delivered(self):
        snapshot=await self.manager.start(-1000000000041)
        self.client.get_entity.return_value=types.User(8,first_name='Public fixture')
        self.rpc.side_effect=RuntimeError('Denied')
        with self.assertRaises(RuntimeError):await self.manager.invite(8,token=snapshot['token'])
        self.assertFalse(self.manager._invited)


if __name__ == '__main__': unittest.main()
