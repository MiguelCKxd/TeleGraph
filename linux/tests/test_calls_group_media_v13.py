"""Pinned upstream integration with an unconnected memory-only test client."""
import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace as NS
from telethon import TelegramClient, functions, types
from telethon.sessions import MemorySession

from tg_ascii.calls_group_media import GroupMediaEngine


class GroupMediaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = TelegramClient(MemorySession(), 12345, 'a' * 32)
        self.client.is_connected = lambda: True
        self.client.get_me = AsyncMock(return_value=types.User(123, is_self=True))
        self.client.get_input_entity = AsyncMock(return_value=types.InputPeerUser(123, 456))
        self.engine = GroupMediaEngine(self.client, -1000000000041, lambda *_: None, lambda *_: None, lambda *_: None)

    async def asyncTearDown(self):
        await self.engine.stop(-1000000000041)

    async def test_initialization_reuses_client_and_cleans_only_owned_handler(self):
        async def other_handler(_): pass
        self.client.add_event_handler(other_handler)
        before = len(self.client.list_event_handlers())
        await self.engine.initialize()
        self.assertEqual(len(self.client.list_event_handlers()), before + 1)
        self.assertIs(self.engine.library._binding, self.engine.proxy)
        self.assertIs(self.engine.library.mtproto_client, self.client)
        self.assertIsNone(self.engine.proxy._process)
        await self.engine.stop(-1000000000041)
        self.assertEqual(len(self.client.list_event_handlers()), before)

    async def test_group_request_returns_borrowed_sender_on_timeout(self):
        await self.engine.initialize()
        adapter = self.engine.library._app.mtproto_client
        request = functions.phone.GetGroupCallChainBlocksRequest(types.InputGroupCall(1, 2), 0, 0, 1)
        future = asyncio.get_running_loop().create_future()
        future.set_exception(TimeoutError())
        pending = NS(request=request, future=future)
        sender = NS(send=Mock(return_value=future), _pending_state={1: pending},
                    _send_queue=NS(_deque=[pending]))
        with patch.object(self.client, '_borrow_exported_sender', AsyncMock(return_value=sender)) as borrow:
            with patch.object(self.client, '_return_exported_sender', AsyncMock()) as release:
                with self.assertRaises(TimeoutError):
                    await adapter._invoke(request, dc_id=4)
                borrow.assert_awaited_once_with(4)
                release.assert_awaited_once_with(sender)
        sender.send.assert_called_once_with(request)
        self.assertEqual(sender._pending_state, {})
        self.assertEqual(sender._send_queue._deque, [])

    async def test_server_timeout_retries_conference_with_the_original_random_id(self):
        from telethon import errors

        await self.engine.initialize()
        adapter = self.engine.library._app.mtproto_client
        request = functions.phone.CreateConferenceCallRequest(random_id=42)
        loop = asyncio.get_running_loop()
        timed_out = loop.create_future()
        timed_out.set_exception(errors.TimeoutError(request))
        created = loop.create_future()
        response = NS(updates=[])
        created.set_result(response)
        with (
            patch.object(self.client._sender, 'send', side_effect=[timed_out, created]) as send,
            patch('tg_ascii.calls_group_media.asyncio.sleep', new_callable=AsyncMock),
        ):
            self.assertIs(await adapter._invoke(request), response)
        self.assertEqual([call.args[0] for call in send.call_args_list], [request, request])

    async def test_failed_conference_start_discards_only_the_call_it_created(self):
        await self.engine.initialize()
        adapter = self.engine.library._app.mtproto_client
        response = NS(updates=[types.UpdateGroupCall(
            call=types.GroupCall(id=123, access_hash=456, participants_count=1,
                                 unmuted_video_limit=10, version=1))])
        future = asyncio.get_running_loop().create_future()
        future.set_result(response)
        request = functions.phone.CreateConferenceCallRequest(random_id=42)

        async def fail_invitation(*args, **kwargs):
            await adapter._invoke(request)
            raise RuntimeError('Invitation failed')

        with patch.object(self.engine, 'initialize', AsyncMock()):
            with patch.object(self.engine.library, 'play', side_effect=fail_invitation):
                with patch.object(self.client._sender, 'send', return_value=future):
                    with patch.object(type(self.client), '__call__', new_callable=AsyncMock) as rpc:
                        with self.assertRaisesRegex(RuntimeError, 'Invitation failed'):
                            await self.engine.start({}, False, conference=True, listen_only=True)
                        discard = rpc.await_args.args[0]
                        self.assertIsInstance(discard, functions.phone.DiscardGroupCallRequest)
                        self.assertEqual((discard.call.id, discard.call.access_hash), (123, 456))
        self.assertIsNone(self.engine._starting_conference)

    async def test_raw_devices_do_not_launch_ffmpeg_or_capture(self):
        self.engine.devices = AsyncMock(return_value={kind: [{'id': kind}] for kind in ('microphone', 'speaker', 'camera', 'screen')})
        stream, speaker = await self.engine.stream({'screen': 'screen'}, False)
        from ntgcalls import MediaSource
        self.assertEqual(stream.microphone.media_source, MediaSource.DEVICE)
        self.assertEqual(stream.screen.media_source, MediaSource.DESKTOP)
        self.assertIsNone(stream.camera)
        self.assertEqual(speaker, 'speaker')
        self.assertIsNone(self.engine.proxy._process)

    async def test_viewer_uses_native_speaker_but_never_a_capture_device(self):
        self.engine.devices=AsyncMock(return_value={'speaker':[{'id':'speaker'}], 'microphone':[], 'camera':[]})
        stream, speaker=await self.engine.view_stream({})
        from ntgcalls import MediaSource
        self.assertEqual(stream.microphone.media_source,MediaSource.EXTERNAL)
        self.assertIsNone(stream.camera)
        self.assertIsNone(stream.screen)
        self.assertEqual(speaker,'speaker')
        self.assertIsNone(self.engine.proxy._process)

    async def test_rtmp_timestamp_subscribes_muxed_channel_before_chunk_download(self):
        await self.engine.initialize()
        adapter=self.engine.library._app.mtproto_client
        adapter.get_input_call=AsyncMock(return_value=types.InputGroupCall(1,2))
        adapter._invoke=AsyncMock(return_value=NS(channels=[NS(channel=1,last_timestamp_ms=12000)]))
        self.engine.proxy.rtmp=True
        self.engine.proxy.add_incoming_video=AsyncMock()
        stamp=await adapter.get_stream_timestamp(self.engine.peer)
        self.assertEqual(stamp,12000)
        args=self.engine.proxy.add_incoming_video.await_args.args
        self.assertEqual(args[:3],(self.engine.peer,0,'unified'))
        self.assertEqual(args[3][0].ssrcs,[1])
        adapter._invoke.return_value=NS(channels=[])
        self.assertEqual(await adapter.get_stream_timestamp(self.engine.peer),0)
        self.assertEqual(self.engine.proxy.add_incoming_video.await_count,1)

    async def test_missing_source_is_rejected_before_media_start(self):
        self.engine.devices = AsyncMock(return_value={'microphone': [], 'speaker': []})
        with self.assertRaises(ValueError):
            await self.engine.stream({}, False)
        self.assertIsNone(self.engine.proxy._process)

    async def test_server_members_bootstrap_even_when_upstream_seeded_an_empty_cache(self):
        await self.engine.initialize()
        adapter = self.engine.library._app.mtproto_client
        adapter._cache.set_cache(self.engine.peer, types.InputGroupCall(1, 2))
        participant = types.GroupCallParticipant(types.PeerUser(123), None, 42, is_self=True)
        pages = [NS(participants=[participant], users=[types.User(123, first_name='Synthetic')], chats=[], next_offset='')]
        with patch.object(self.client, '_call', new=AsyncMock(side_effect=pages)) as rpc:
            rows = await self.engine.library._app.get_group_call_participants(self.engine.peer)
            self.assertEqual([row.user_id for row in rows], [123])
            self.assertEqual(self.engine.names[123], 'Synthetic')
            self.assertEqual(rpc.call_args.args[1].limit, 100)
            await self.engine.library._app.get_group_call_participants(self.engine.peer)
            self.assertEqual(rpc.await_count, 1)

    async def test_repeated_server_page_cursor_is_rejected(self):
        await self.engine.initialize()
        adapter = self.engine.library._app.mtproto_client
        adapter._cache.set_cache(self.engine.peer, types.InputGroupCall(1, 2))
        page = NS(participants=[], users=[], chats=[], next_offset='same')
        with patch.object(self.client, '_call', new=AsyncMock(return_value=page)) as rpc:
            with self.assertRaisesRegex(RuntimeError, 'cursor did not advance'):
                await self.engine.participants()
            self.assertEqual(rpc.await_count, 2)

    async def test_conference_screen_change_negotiates_and_leaves_presentation(self):
        await self.engine.initialize()
        self.engine.conference = True
        self.engine.proxy.calls = AsyncMock(return_value=[self.engine.peer])
        self.engine.proxy.set_stream_sources = AsyncMock()
        self.engine.stream = AsyncMock(return_value=(NS(), 'speaker'))
        self.engine.library.play = AsyncMock()
        self.engine.library._join_presentation = AsyncMock()
        self.engine.mute = AsyncMock()
        await self.engine.media(self.engine.peer, {'screen': 'synthetic'}, False)
        self.engine.library._join_presentation.assert_awaited_once_with(self.engine.peer, True)
        self.assertFalse(self.engine._presentation_pending)
        await self.engine.media(self.engine.peer, {}, False)
        self.assertEqual(self.engine.library._join_presentation.call_args.args, (self.engine.peer, False))

    async def test_main_connection_event_cannot_complete_pending_presentation(self):
        await self.engine.initialize()
        import ntgcalls as nt
        lib = self.engine.library
        future = lib.loop.create_future()
        lib._wait_connect[self.engine.peer] = future
        self.engine._presentation_pending = True
        try:
            await lib._handle_connection_changed(self.engine.peer,
                nt.ConnectionInfo(nt.ConnectionState.CONNECTED, nt.ConnectionKind.NORMAL))
            self.assertFalse(future.done())
            await lib._handle_connection_changed(self.engine.peer,
                nt.ConnectionInfo(nt.ConnectionState.CONNECTED, nt.ConnectionKind.PRESENTATION))
            self.assertTrue(future.done())
        finally:
            lib._wait_connect.pop(self.engine.peer, None)
            if not future.done(): future.cancel()

    async def test_call_ended_for_everyone_closes_the_local_call(self):
        states = []
        self.engine.on_state = lambda key, value: states.append((key, value))
        await self.engine.initialize()
        from pytgcalls.types import ChatUpdate
        self.engine.proxy.native_request = AsyncMock(side_effect=RuntimeError("Native call already stopped"))
        await self.engine.library._handle_mtproto_updates(
            ChatUpdate(self.engine.peer, ChatUpdate.Status.CLOSED_VOICE_CHAT))
        self.assertEqual(states, [(self.engine.peer, 'CLOSED')])
        await self.engine.library._handle_mtproto_updates(
            ChatUpdate(-1000000000099, ChatUpdate.Status.CLOSED_VOICE_CHAT))
        self.assertEqual(len(states), 1)
