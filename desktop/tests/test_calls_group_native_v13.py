"""Native group IPC with actual cryptographic initialization, no accounts or devices."""
import unittest
import asyncio
from tg_ascii.calls_native import engine_available
from tg_ascii.calls_rpc_codec import encode, decode


class CodecBoundaryTests(unittest.TestCase):
    def test_unknown_types_and_forged_tags_are_rejected(self):
        for value in (object(), {'key': object()}):
            with self.assertRaises(ValueError): encode(value)
        for value in (('record', '__import__', ()), ('enum', 'os', 1),
                      ('record', 'MediaDescription', ()), {'type': 'Frame'}):
            with self.assertRaises(ValueError): decode(value)

    def test_depth_and_collections_are_bounded(self):
        value = 0
        for _ in range(22): value = [value]
        with self.assertRaises(ValueError): encode(value)
        with self.assertRaises(ValueError): encode([None] * 10001)


@unittest.skipUnless(engine_available(), 'Optional native group engine unavailable')
class NativeGroupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from tg_ascii.calls_group_native import GroupNativeProxy
        self.proxy = GroupNativeProxy()

    async def asyncTearDown(self):
        await self.proxy.close()

    async def test_fresh_conference_parameters_cross_real_child_without_keys_or_session(self):
        await self.proxy.create_p2p_call(900001)
        params = await self.proxy.init_conference(900001, 900002, None)
        self.assertIsInstance(params.payload, str)
        self.assertEqual(len(params.public_key), 32)
        self.assertGreater(len(params.block), 0)
        import ntgcalls as nt
        self.assertEqual(await self.proxy.get_call_type(900001), nt.CallType.CONFERENCE)
        await self.proxy.stop(900001)
        self.assertEqual(await self.proxy.calls(), {})
        await self.proxy.close()
        self.assertEqual(self.proxy.exit_code, 0)
        self.assertFalse(self.proxy._pending)

    async def test_wrong_seed_preserves_native_exception_and_cleanup(self):
        import ntgcalls as nt
        await self.proxy.create_call(900001)
        with self.assertRaises(nt.ConnectionError):
            await self.proxy.init_conference(900001, 900002, None)
        await self.proxy.stop(900001)

    async def test_call_state_and_media_descriptions_use_exact_native_types(self):
        import ntgcalls as nt
        media = nt.MediaDescription(nt.AudioDescription(nt.MediaSource.DEVICE, 48000, 1, 'test', False),
                                   None, nt.VideoDescription(nt.MediaSource.EXTERNAL, 640, 480, 0, '', False), None)
        restored = decode(encode(media))
        self.assertEqual(restored.microphone.sample_rate, 48000)
        self.assertEqual(restored.camera.media_source, nt.MediaSource.EXTERNAL)
        await self.proxy.create_call(900001)
        state = await self.proxy.get_state(900001)
        self.assertIsInstance(state, nt.MediaState)
        self.assertTrue(state.video_stopped)

    async def test_playback_is_configured_before_capture_and_not_restarted_on_camera_change(self):
        import ntgcalls as nt
        from unittest.mock import AsyncMock
        self.proxy.native_request = AsyncMock()
        playback = nt.MediaDescription(nt.AudioDescription(nt.MediaSource.DEVICE, 48000, 1, 'speaker', False), None, None, None)
        capture = nt.MediaDescription(nt.AudioDescription(nt.MediaSource.DEVICE, 48000, 1, 'mic', False), None, None, None)
        self.proxy.initial_playback = playback
        await self.proxy.set_stream_sources(7, nt.StreamMode.CAPTURE, capture)
        calls = self.proxy.native_request.call_args_list
        self.assertEqual([call.args[1][1] for call in calls], [nt.StreamMode.PLAYBACK, nt.StreamMode.CAPTURE])
        await self.proxy.set_stream_sources(7, nt.StreamMode.PLAYBACK, playback)
        self.assertEqual(self.proxy.native_request.await_count, 2)

    async def test_unlisted_operation_never_reaches_helper(self):
        self.assertIsNone(self.proxy._process)
        with self.assertRaises(AttributeError):
            self.proxy.execute_shell('untrusted')
        self.assertIsNone(self.proxy._process)

    async def test_video_subscriptions_are_bounded_and_selection_comes_first(self):
        # 1.4 opt-in "Expanded group video view": up to 30 cameras, chosen one first.
        from unittest.mock import AsyncMock
        from tg_ascii.calls_group_native import MAX_INCOMING_VIDEOS
        self.proxy.native_request = AsyncMock()
        self.proxy.max_videos = MAX_INCOMING_VIDEOS
        self.proxy.local_user_id = 7
        await self.proxy.add_incoming_video(41, 7, 'own-camera', [])
        for user in range(100, 1100):
            await self.proxy.add_incoming_video(41, user, f'camera-{user}', [])
        first = {f'camera-{user}' for user in range(100, 100 + MAX_INCOMING_VIDEOS)}
        self.assertEqual(self.proxy.native_request.await_count, MAX_INCOMING_VIDEOS)
        self.assertEqual(self.proxy._video_active, first)
        await self.proxy.select_video(41, 1099, 'camera-1099')
        self.assertEqual(self.proxy._video_active,
                         {'camera-1099'} | {f'camera-{user}' for user in range(100, 99 + MAX_INCOMING_VIDEOS)})
        self.assertEqual(self.proxy.primary_endpoint, 'camera-1099')
        self.assertEqual([call.args[0] for call in self.proxy.native_request.call_args_list][-2:],
                         ['remove_incoming_video', 'add_incoming_video'])
        await self.proxy.remove_incoming_video(41, 'camera-1099')
        self.assertEqual(self.proxy._video_active, first)

    async def test_video_decodes_only_one_visible_source_and_selection_replaces_it(self):
        # Default (feature off): exactly the 1.3 behaviour, one camera.
        from unittest.mock import AsyncMock
        self.proxy.native_request = AsyncMock()
        self.proxy.local_user_id = 7
        await self.proxy.add_incoming_video(41, 7, 'own-camera', [])
        for user in range(100, 1100):
            await self.proxy.add_incoming_video(41, user, f'camera-{user}', [])
        self.assertEqual(self.proxy.native_request.await_count, 1)
        self.assertEqual(self.proxy._video_active, {'camera-100'})
        await self.proxy.select_video(41, 1099, 'camera-1099')
        self.assertEqual(self.proxy._video_active, {'camera-1099'})
        self.assertEqual([call.args[0] for call in self.proxy.native_request.call_args_list],
                         ['add_incoming_video', 'remove_incoming_video', 'add_incoming_video'])
        await self.proxy.remove_incoming_video(41, 'camera-1099')
        self.assertEqual(self.proxy._video_active, {'camera-100'})

    async def test_active_endpoint_source_change_is_applied_and_duplicate_is_free(self):
        import ntgcalls as nt
        from unittest.mock import AsyncMock
        self.proxy.native_request = AsyncMock()
        self.proxy.local_user_id = 7
        await self.proxy.add_incoming_video(41, 8, 'remote', [nt.SsrcGroup('SIM', [1])])
        await self.proxy.add_incoming_video(41, 8, 'remote', [nt.SsrcGroup('SIM', [1])])
        self.assertEqual(self.proxy.native_request.await_count, 1)
        await self.proxy.add_incoming_video(41, 8, 'remote', [nt.SsrcGroup('SIM', [2])])
        self.assertEqual(self.proxy.native_request.await_count, 3)

    async def test_stop_serializes_with_pending_subscription_and_rejects_late_offers(self):
        from unittest.mock import AsyncMock
        entered, release = asyncio.Event(), asyncio.Event()
        async def blocked(name, args):
            if name == 'add_incoming_video':
                entered.set()
                await release.wait()
        self.proxy.native_request = AsyncMock(side_effect=blocked)
        self.proxy.local_user_id = 7
        adding = asyncio.create_task(self.proxy.add_incoming_video(41, 8, 'remote', []))
        await entered.wait()
        stopping = asyncio.create_task(self.proxy.stop(41))
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(adding, stopping)
        await self.proxy.add_incoming_video(41, 9, 'late', [])
        self.assertFalse(self.proxy._video_active)
        self.assertFalse(self.proxy._video_offers)
        self.assertEqual([call.args[0] for call in self.proxy.native_request.call_args_list], ['add_incoming_video', 'stop'])


if __name__ == '__main__': unittest.main()
