import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from telethon.tl import types, functions
from telethon.tl.types.messages import DhConfig

from tg_ascii.calls import CallManager, CallError
from tg_ascii.calls_crypto import validate_dh, _probable_prime, TELEGRAM_SAFE_PRIME


def protocol():
    return types.PhoneCallProtocol(65, 92, udp_p2p=True, udp_reflector=True,
                                   library_versions=['test'])


def remote(kind, call_id=123, peer=2, **extra):
    common = dict(id=call_id, access_hash=456, date=None, admin_id=1,
                  participant_id=peer, protocol=protocol())
    if kind is types.PhoneCallRequested:
        common.update(admin_id=peer, participant_id=1, g_a_hash=b'h' * 32)
    if kind is types.PhoneCallAccepted:
        common['g_b'] = b'b' * 256
    if kind is types.PhoneCall:
        common.update(g_a_or_b=b'a' * 256, key_fingerprint=789,
                      connections=[], start_date=None)
    common.update(extra)
    return kind(**common)


class FakeClient:
    def __init__(self):
        self.handlers = []
        self.requests = []
        self.entity = types.User(2, access_hash=4)
        self.stall = None
        self.confirm_fingerprint = 789

    def add_event_handler(self, handler, event):
        self.handlers.append(handler)

    def remove_event_handler(self, handler):
        self.handlers.remove(handler)

    async def get_entity(self, peer):
        return self.entity

    async def __call__(self, request):
        self.requests.append(request)
        if isinstance(request, functions.messages.GetDhConfigRequest):
            if self.stall:
                await self.stall.wait()
            return DhConfig(3, b'p' * 256, 0, b'r' * 256)
        if isinstance(request, functions.phone.RequestCallRequest):
            return SimpleNamespace(phone_call=remote(types.PhoneCallWaiting))
        if isinstance(request, functions.phone.ConfirmCallRequest):
            return SimpleNamespace(phone_call=remote(types.PhoneCall, key_fingerprint=self.confirm_fingerprint))
        return True


class FakeEngine:
    instances = []
    def __init__(self, state, signal, frames, emojis):
        self.callbacks = state, signal, frames, emojis
        self.stopped = []
        self.exchange_count = 0
        self.media_count = 0
        self.connected = []
        self.signals = []
        self.mutes = []
        self.fail_exchange = False
        self.__class__.instances.append(self)

    @staticmethod
    async def devices():
        return {key: [{'id': key, 'name': key}] for key in ('microphone', 'speaker', 'camera')}

    def protocol(self):
        return protocol()

    async def create(self, peer, dh, ga_hash=None):
        return b'local'

    async def exchange(self, peer, ga, fingerprint=0):
        self.exchange_count += 1
        if self.fail_exchange:
            raise ValueError('Invalid key fingerprint')
        return SimpleNamespace(g_a_or_b=b'local', key_fingerprint=789)

    async def media(self, peer, selected, video, muted=False):
        self.media_count += 1

    async def connect(self, peer, call):
        self.connected.append(peer)

    async def mute(self, peer, value):
        self.mutes.append(value)

    async def signal(self, peer, data):
        self.signals.append(data)

    async def stop(self, peer):
        self.stopped.append(peer)


class CallLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        FakeEngine.instances.clear()
        self.client = FakeClient()
        self.events = []
        self.manager = CallManager(self.client, self.events.append,
            engine_factory=FakeEngine, available=lambda: True, timeout=5)
        self.validation = patch('tg_ascii.calls_crypto.validate_dh', return_value=True)
        self.validation.start()
        self.permissions = patch('tg_ascii.mac_media_access.ensure_media_access', new_callable=AsyncMock)
        self.permission_check = self.permissions.start()
        await self.manager.enable()

    async def asyncTearDown(self):
        await self.manager.close()
        self.validation.stop()
        self.permissions.stop()

    async def update(self, value):
        await self.manager._on_update(types.UpdatePhoneCall(value))

    async def connected(self):
        await self.manager.start(2)
        await self.update(remote(types.PhoneCallAccepted))
        token = self.manager.snapshot['token']
        await self.manager._native_state(token, 2, 'CONNECTED')
        return token

    async def test_enable_has_one_handler_and_no_engine_or_media(self):
        await self.manager.enable()
        self.assertEqual(len(self.client.handlers), 1)
        self.assertFalse(FakeEngine.instances)
        self.assertFalse(self.client.requests)

    async def test_permission_denial_never_dials_or_creates_native_capture(self):
        self.permission_check.side_effect = PermissionError('Microphone denied')
        with self.assertRaises(PermissionError):
            await self.manager.start(2)
        self.assertFalse(FakeEngine.instances)
        self.assertFalse(self.client.requests)
        self.assertIsNone(CallManager._capture_owner)

    async def test_outgoing_handshake_and_stop(self):
        token = await self.connected()
        native = FakeEngine.instances[-1]
        self.assertEqual(self.manager.snapshot['state'], 'active')
        self.assertEqual(native.exchange_count, 1)
        self.assertEqual(native.media_count, 1)
        await self.manager.mute(True, token=token)
        self.assertEqual(native.mutes, [True])
        await self.manager.hangup(2, token=token)
        self.assertEqual(native.stopped, [2])
        self.assertEqual(self.manager.snapshot['state'], 'ended')
        self.assertIsNone(self.manager._engine)

    async def test_incoming_waits_for_explicit_accept_and_crypto(self):
        requested = remote(types.PhoneCallRequested, video=True)
        await self.update(requested)
        token = self.manager.snapshot['token']
        self.assertEqual(self.manager.snapshot['state'], 'incoming')
        self.assertTrue(self.manager.snapshot['requested_video'])
        self.assertFalse(FakeEngine.instances)
        await self.manager.accept(2, token=token)
        native = FakeEngine.instances[-1]
        self.assertEqual(native.media_count, 0)
        await self.update(remote(types.PhoneCall, admin_id=2, participant_id=1))
        self.assertEqual(native.exchange_count, 1)
        self.assertEqual(native.media_count, 1)
        self.assertFalse(self.manager.snapshot['video'])

    async def test_key_failure_never_starts_media(self):
        await self.update(remote(types.PhoneCallRequested))
        await self.manager.accept(2)
        native = FakeEngine.instances[-1]
        native.fail_exchange = True
        await self.update(remote(types.PhoneCall, admin_id=2, participant_id=1))
        self.assertEqual(native.media_count, 0)
        self.assertEqual(native.stopped, [2])
        self.assertEqual(self.manager.snapshot['state'], 'ended')

    async def test_outgoing_confirmation_checks_fingerprint(self):
        await self.manager.start(2)
        self.client.confirm_fingerprint = 999
        await self.update(remote(types.PhoneCallAccepted))
        self.assertEqual(FakeEngine.instances[-1].media_count, 0)
        self.assertIn('Invalid call confirmation', self.manager.snapshot['error'])

    async def test_duplicate_handshake_updates_do_not_exchange_again(self):
        await self.connected()
        await self.update(remote(types.PhoneCallAccepted))
        await self.update(remote(types.PhoneCall))
        self.assertEqual(FakeEngine.instances[-1].exchange_count, 1)

    async def test_duplicate_request_and_replayed_finished_call(self):
        request = remote(types.PhoneCallRequested)
        await self.update(request)
        token = self.manager.snapshot['token']
        await self.update(request)
        self.assertEqual(self.manager.snapshot['token'], token)
        await self.manager.decline(2, token=token)
        await self.update(request)
        self.assertEqual(self.manager.snapshot['state'], 'ended')
        self.assertFalse(FakeEngine.instances)

    async def test_stale_window_cannot_end_new_call_to_same_person(self):
        await self.update(remote(types.PhoneCallRequested))
        old = self.manager.snapshot['token']
        await self.manager.decline(2)
        await self.update(remote(types.PhoneCallRequested, call_id=124))
        with self.assertRaises(CallError):
            await self.manager.hangup(2, token=old)
        self.assertEqual(self.manager.snapshot['state'], 'incoming')

    async def test_answer_on_another_device_discards_local_prompt(self):
        await self.update(remote(types.PhoneCallRequested))
        await self.update(types.PhoneCallDiscarded(123))
        self.assertEqual(self.manager.snapshot['state'], 'ended')
        self.assertFalse(FakeEngine.instances)

    async def test_other_call_cannot_change_current_state(self):
        token = await self.connected()
        await self.update(types.PhoneCallDiscarded(987))
        await self.manager._native_state('obsolete', 2, 'FAILED')
        await self.manager._native_state(token, 5, 'FAILED')
        self.assertEqual(self.manager.snapshot['state'], 'active')

    async def test_second_incoming_is_rejected_busy(self):
        await self.connected()
        await self.update(remote(types.PhoneCallRequested, call_id=987, peer=3))
        requests = [x for x in self.client.requests if isinstance(x, functions.phone.DiscardCallRequest)]
        self.assertEqual(requests[-1].peer.id, 987)
        self.assertIsInstance(requests[-1].reason, types.PhoneCallDiscardReasonBusy)
        self.assertEqual(self.manager.snapshot['peer'], 2)

    async def test_failed_busy_rejection_preserves_existing_call(self):
        token = await self.connected()
        native = FakeEngine.instances[-1]
        original = FakeClient.__call__
        async def fail_busy(client, request):
            if isinstance(request, functions.phone.DiscardCallRequest):
                client.requests.append(request)
                raise TimeoutError('network unavailable')
            return await original(client, request)
        with patch.object(FakeClient, '__call__', fail_busy):
            await self.update(remote(types.PhoneCallRequested, call_id=987, peer=3))
        self.assertEqual(self.manager.snapshot['state'], 'active')
        self.assertEqual(self.manager.snapshot['token'], token)
        self.assertFalse(native.stopped)
        discards = [r for r in self.client.requests if isinstance(r, functions.phone.DiscardCallRequest)]
        self.assertEqual([r.peer.id for r in discards], [987])

    async def test_self_and_bots_are_rejected_before_media(self):
        for flags in ({'is_self': True}, {'bot': True}, {'deleted': True}):
            self.client.entity = types.User(2, **flags)
            with self.assertRaises(CallError):
                await self.manager.start(2)
        self.assertFalse(FakeEngine.instances)

    async def test_hangup_cancels_pending_start_without_waiting_for_network_timeout(self):
        self.client.stall = asyncio.Event()
        start = asyncio.create_task(self.manager.start(2))
        while self.manager.snapshot['state'] != 'preparing':
            await asyncio.sleep(0)
        await asyncio.wait_for(self.manager.hangup(2), 0.5)
        self.assertTrue(start.cancelled())
        self.assertEqual(self.manager.snapshot['state'], 'ended')

    async def test_close_cancels_pending_start_and_unregisters_handler(self):
        self.client.stall = asyncio.Event()
        start = asyncio.create_task(self.manager.start(2))
        while self.manager.snapshot['state'] != 'preparing':
            await asyncio.sleep(0)
        await asyncio.wait_for(self.manager.close(), 0.5)
        self.assertTrue(start.cancelled())
        self.assertFalse(self.client.handlers)

    async def test_frame_buffer_is_bounded_and_rejects_wrong_token(self):
        token = await self.connected()
        info = SimpleNamespace(width=2, height=2, rotation=0)
        raw = bytearray(b'\x80' * 6)
        frame = SimpleNamespace(frame_data=info, data=raw)
        self.manager._receive_frame(token, 2, 'PLAYBACK', 'CAMERA', [frame])
        raw[0] = 1
        received = self.manager.take_frame()
        self.assertEqual(received['data'], b'\x80' * 6)
        self.assertIsNone(self.manager.take_frame())
        self.manager._frame_time = 0
        self.manager._receive_frame('old', 2, 'PLAYBACK', 'CAMERA', [frame])
        self.assertIsNone(self.manager.take_frame())

    async def test_local_preview_and_remote_frames_use_independent_slots(self):
        token = await self.connected()
        await self.manager.set_camera(True, token=token)
        info = SimpleNamespace(width=2, height=2, rotation=0)
        local = SimpleNamespace(frame_data=info, data=b'\x40' * 6)
        remote_frame = SimpleNamespace(frame_data=info, data=b'\x80' * 6)
        self.manager._receive_frame(token, 2, 'CAPTURE', 'CAMERA', [local])
        self.manager._receive_frame(token, 2, 'PLAYBACK', 'CAMERA', [remote_frame])
        self.assertEqual(self.manager.take_local_frame()['data'], b'\x40' * 6)
        self.assertEqual(self.manager.take_frame()['data'], b'\x80' * 6)
        self.assertIsNone(self.manager.take_local_frame())
        self.assertIsNone(self.manager.take_frame())

    async def test_stopping_camera_discards_local_preview_and_late_capture(self):
        token = await self.connected()
        await self.manager.set_camera(True, token=token)
        info = SimpleNamespace(width=2, height=2, rotation=0)
        frame = SimpleNamespace(frame_data=info, data=b'\x40' * 6)
        self.manager._receive_frame(token, 2, 'CAPTURE', 'CAMERA', [frame])
        await self.manager.set_camera(False, token=token)
        self.manager._receive_frame(token, 2, 'CAPTURE', 'CAMERA', [frame])
        self.assertIsNone(self.manager.take_local_frame())

    async def test_timeout_releases_call(self):
        self.manager._timeout = 0.01
        await self.update(remote(types.PhoneCallRequested))
        # Slow (emulated) machines may need more than one 30 ms tick.
        for _ in range(200):
            await asyncio.sleep(0.01)
            if self.manager.snapshot['state'] == 'ended':
                break
        self.assertEqual(self.manager.snapshot['state'], 'ended')
        self.assertIn('timed out', self.manager.snapshot['error'])

    async def test_process_frames_replace_latest_without_double_throttle(self):
        token = await self.connected()
        info = SimpleNamespace(width=2, height=2, rotation=0)
        with patch.object(FakeEngine, 'frames_throttled', True, create=True):
            for value in (100, 200):
                frame = SimpleNamespace(frame_data=info, data=bytes([value]) * 6)
                self.manager._receive_frame(token, 2, 'PLAYBACK', 'CAMERA', [frame])
        self.assertEqual(self.manager.take_frame()['data'], bytes([200]) * 6)
        self.assertIsNone(self.manager.take_frame())

    async def test_signals_are_scoped_to_matching_call(self):
        await self.connected()
        engine = FakeEngine.instances[-1]
        await self.manager._on_update(types.UpdatePhoneCallSignalingData(999, b'wrong'))
        await self.manager._on_update(types.UpdatePhoneCallSignalingData(123, b'right'))
        self.assertEqual(engine.signals, [b'right'])

    async def test_hardware_is_exclusive_between_accounts(self):
        await self.connected()
        other = CallManager(FakeClient(), engine_factory=FakeEngine, available=lambda: True)
        try:
            with self.assertRaisesRegex(CallError, 'Another account'):
                await other.start(2)
            self.assertEqual(self.manager.snapshot['state'], 'active')
            self.assertEqual(len(FakeEngine.instances), 1)
        finally:
            await other.close()

    async def test_remote_camera_off_clears_pending_frame(self):
        token = await self.connected()
        self.manager._frame = {'stale': True}
        await self.manager._native_state(token, 2, 'REMOTE_CAMERA_ACTIVE')
        self.assertTrue(self.manager.snapshot['remote_video'])
        await self.manager._native_state(token, 2, 'REMOTE_CAMERA_IDLING')
        self.assertFalse(self.manager.snapshot['remote_video'])
        self.assertIsNone(self.manager.take_frame())

    async def test_close_during_remote_cleanup_releases_capture_slot(self):
        await self.connected()
        engine = FakeEngine.instances[-1]
        cleaning, release = asyncio.Event(), asyncio.Event()
        async def slow_stop(peer):
            cleaning.set()
            await release.wait()
            engine.stopped.append(peer)
        engine.stop = slow_stop
        update = asyncio.create_task(self.update(types.PhoneCallDiscarded(123)))
        await cleaning.wait()
        closing = asyncio.create_task(self.manager.close())
        await asyncio.sleep(0)
        release.set()
        await asyncio.wait_for(asyncio.gather(update, closing), 0.5)
        self.assertEqual(engine.stopped, [2])
        self.assertIsNone(CallManager._capture_owner)
        self.assertEqual(self.manager.snapshot['state'], 'ended')
        self.assertFalse(self.client.handlers)


    async def test_server_discard_reasons_are_preserved(self):
        for index,(reason,outcome) in enumerate(((types.PhoneCallDiscardReasonBusy(),'declined_or_busy'),(types.PhoneCallDiscardReasonMissed(),'not_answered'),(types.PhoneCallDiscardReasonDisconnect(),'disconnected'),(types.PhoneCallDiscardReasonHangup(),'ended'))):
            await self.update(remote(types.PhoneCallRequested,call_id=700+index))
            await self.update(types.PhoneCallDiscarded(700+index,reason=reason))
            self.assertEqual(self.manager.snapshot['outcome'],outcome)
    async def test_explicit_decline_sends_busy_and_retains_local_decline(self):
        await self.update(remote(types.PhoneCallRequested))
        await self.manager.decline(token=self.manager.snapshot['token'])
        self.assertEqual(self.manager.snapshot['outcome'],'declined')
        request=next(r for r in reversed(self.client.requests) if isinstance(r,functions.phone.DiscardCallRequest))
        self.assertIsInstance(request.reason,types.PhoneCallDiscardReasonBusy)


class ScreenSharingTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = CallLifecycleTests.asyncSetUp
    asyncTearDown = CallLifecycleTests.asyncTearDown
    connected = CallLifecycleTests.connected
    update = CallLifecycleTests.update

    async def test_screen_requires_valid_explicit_source_and_current_token(self):
        token = await self.connected()
        self.manager.devices = AsyncMock(return_value={'screen': [{'id': 'desktop-1', 'name': 'Display'}]})
        native = FakeEngine.instances[-1]
        count = native.media_count
        with self.assertRaises(CallError):
            await self.manager.set_screen('unknown', token=token)
        with self.assertRaises(CallError):
            await self.manager.set_screen('desktop-1', token='stale')
        self.assertEqual(native.media_count, count)
        await self.manager.set_screen('desktop-1', token=token)
        self.assertTrue(self.manager.snapshot['screen'])
        self.assertFalse(self.manager.snapshot['video'])
        await self.manager.set_camera(True, token=token)
        self.assertFalse(self.manager.snapshot['screen'])
        self.assertNotIn('screen', self.manager._selected)
        await self.manager.set_screen('desktop-1', token=token)
        await self.manager.hangup(token=token)
        self.assertNotIn('screen', self.manager._selected)

    async def test_failed_native_start_does_not_mark_screen_as_shared(self):
        token = await self.connected()
        self.manager.devices = AsyncMock(return_value={'screen': [{'id': 'desktop-1'}]})
        native = FakeEngine.instances[-1]
        native.media = AsyncMock(side_effect=RuntimeError('capture denied'))
        with self.assertRaisesRegex(RuntimeError, 'capture denied'):
            await self.manager.set_screen('desktop-1', token=token)
        self.assertFalse(self.manager.snapshot['screen'])
        self.assertNotIn('screen', self.manager._selected)


class CryptoValidationTests(unittest.TestCase):
    def test_embedded_telegram_prime_is_safe_and_has_the_required_size(self):
        number = int.from_bytes(TELEGRAM_SAFE_PRIME, 'big')
        self.assertEqual(number.bit_length(), 2048)
        self.assertTrue(_probable_prime(number))
        self.assertTrue(_probable_prime((number - 1) // 2))

    def test_known_prime_fast_path_still_checks_generator_and_unknown_primes(self):
        validate_dh.cache_clear()
        with patch('tg_ascii.calls_crypto._probable_prime', return_value=False) as primality:
            self.assertTrue(validate_dh(3, TELEGRAM_SAFE_PRIME))
            primality.assert_not_called()
            with self.assertRaises(ValueError):
                validate_dh(8, TELEGRAM_SAFE_PRIME)
            changed = TELEGRAM_SAFE_PRIME[:-1] + bytes([TELEGRAM_SAFE_PRIME[-1] ^ 2])
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                validate_dh(4, changed)
            primality.assert_called_once()

    def test_rejects_bad_lengths_generators_composites(self):
        for generator, prime in [(3, b'x'), (9, b'\xff' * 256), (4, b'\xff' * 256), (2, b'\x80' + b'\x00' * 255)]:
            with self.assertRaises(ValueError):
                validate_dh(generator, prime)

    def test_miller_rabin_rejects_carmichael_and_strong_pseudoprimes(self):
        for value in (0, 1, 4, 561, 1105, 1729, 3215031751):
            self.assertFalse(_probable_prime(value))
        for value in (2, 3, 5, 13, 97, 65537):
            self.assertTrue(_probable_prime(value))
