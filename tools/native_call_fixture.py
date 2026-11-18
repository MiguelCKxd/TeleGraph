"""Opt-in test fixture: generated media, never a microphone, speaker or camera.

No credentials, account selection, session files, or network access at import.
The caller supplies two explicitly authorized connected Telegram clients and IDs.
Do not use this fixture with ordinary contacts or the excluded primary account.
"""
import asyncio
from array import array
import math
import time

from tg_ascii.calls import CallManager
from tg_ascii.calls_native import NativeEngine
from tg_ascii.calls_process import ProcessNativeEngine


def synthetic_factory(stats):
    class SyntheticEngine(NativeEngine):
        uses_hardware = False

        def __init__(self, state, signal, frames, emojis):
            stats.setdefault('audio_signal_frames', 0)
            def counted(peer, mode, device, batch):
                if mode == 'PLAYBACK':
                    key = 'audio' if device == 'MICROPHONE' else 'video' if device == 'CAMERA' else None
                    if key:
                        stats[key + '_frames'] += len(batch)
                        stats[key + '_bytes'] += sum(len(frame.data) for frame in batch)
                        if key == 'audio':
                            stats['audio_signal_frames'] += sum(bool(any(frame.data)) for frame in batch)
                frames(peer, mode, device, batch)
            super().__init__(state, signal, counted, emojis)
            self.feeder = None

        async def media(self, peer, selected, video, muted=False):
            nt = self.nt
            audio = nt.AudioDescription(nt.MediaSource.EXTERNAL, 48000, 1, '', False)
            camera = nt.VideoDescription(nt.MediaSource.EXTERNAL, 320, 180, 15, '', False)
            capture = nt.MediaDescription(audio, None, camera if video else None, None)
            # Like production: receive video even when our own camera is off.
            playback = nt.MediaDescription(audio, None, camera, None)
            await self.binding.set_stream_sources(peer, nt.StreamMode.PLAYBACK, playback)
            await self.binding.set_stream_sources(peer, nt.StreamMode.CAPTURE, capture)
            if self.feeder:
                self.feeder.cancel()
                await asyncio.gather(self.feeder, return_exceptions=True)
            self.feeder = asyncio.create_task(self.feed(peer, video))
            await self.mute(peer, muted)

        async def feed(self, peer, video):
            nt = self.nt
            samples = array('h', (int(1600 * math.sin(2 * math.pi * 400 * sample / 48000)) for sample in range(480)))
            import sys
            if sys.byteorder != 'little':
                samples.byteswap()
            pcm = samples.tobytes()
            pictures = [bytes([luma]) * (320 * 180) + bytes([128]) * (320 * 180 // 2) for luma in (60, 120, 180)]
            tick = 0
            while True:
                timestamp = int(time.time() * 1000)
                await self.binding.send_external_frame(peer, nt.StreamDevice.MICROPHONE, pcm,
                    nt.FrameData(timestamp, nt.VideoRotation.VIDEO_ROTATION_0, 0, 0))
                if video and tick % 7 == 0:
                    await self.binding.send_external_frame(peer, nt.StreamDevice.CAMERA,
                        pictures[(tick // 7) % len(pictures)],
                        nt.FrameData(timestamp, nt.VideoRotation.VIDEO_ROTATION_0, 320, 180))
                tick += 1
                await asyncio.sleep(0.01)

        async def stop(self, peer):
            if self.feeder:
                self.feeder.cancel()
                await asyncio.gather(self.feeder, return_exceptions=True)
                self.feeder = None
            await super().stop(peer)

    return SyntheticEngine


def synthetic_process_factory(stats):
    class SyntheticProcessEngine(ProcessNativeEngine):
        uses_hardware = False
        synthetic = True

        def __init__(self, state, signal, frames, emojis):
            stats.setdefault('audio_signal_frames', 0)
            def counted(peer, mode, device, batch):
                if mode == 'PLAYBACK':
                    key = 'audio' if device == 'MICROPHONE' else 'video' if device == 'CAMERA' else None
                    if key:
                        stats[key + '_frames'] += len(batch)
                        stats[key + '_bytes'] += sum(len(frame.data) for frame in batch)
                        if key == 'audio':
                            stats['audio_signal_frames'] += sum(bool(any(frame.data)) for frame in batch)
                frames(peer, mode, device, batch)
            super().__init__(state, signal, counted, emojis)
    return SyntheticProcessEngine


async def _cleanup(managers, previous_engines=()):
    engines = list(previous_engines) + [manager._engine for manager in managers]
    closed = await asyncio.gather(*(manager.close() for manager in managers), return_exceptions=True)
    complete = all(not isinstance(item, BaseException) for item in closed)
    complete &= all(engine is None or (engine.exit_code == 0 and not engine._pending)
                    for engine in engines)
    return bool(complete and all(not manager._tasks and not manager._updates for manager in managers))


async def _until(predicate, managers, timeout=20):
    async with asyncio.timeout(timeout):
        while not predicate():
            for manager in managers:
                if manager.snapshot['state'] == 'ended' and manager.snapshot['error']:
                    raise RuntimeError(manager.snapshot['error'])
            await asyncio.sleep(0.05)


async def verify_pair(client_a, client_b, user_a, user_b, *, video=True, duration=4):
    """Place one bounded synthetic call and always hang up both local endpoints."""
    counters = [dict(audio_frames=0, video_frames=0, audio_bytes=0, video_bytes=0) for _ in range(2)]
    managers = [CallManager(client, engine_factory=synthetic_process_factory(counter), timeout=40)
                for client, counter in zip((client_a, client_b), counters)]
    a, b = managers
    began = time.monotonic()
    result = None
    try:
        await a.enable()
        await b.enable()
        await a.start(user_b, video=video)
        async with asyncio.timeout(45):
            while b.snapshot['state'] != 'incoming' or b.snapshot['peer'] != user_a:
                if a.snapshot['state'] == 'ended':
                    raise RuntimeError(a.snapshot['error'] or 'Outgoing test call ended')
                await asyncio.sleep(0.05)
            await b.accept(user_a, video=video, token=b.snapshot['token'])
            while any(manager.snapshot['state'] != 'active' for manager in managers):
                for manager in managers:
                    if manager.snapshot['state'] == 'ended':
                        raise RuntimeError(manager.snapshot['error'] or 'Test call ended')
                await asyncio.sleep(0.05)
        connected_seconds = time.monotonic() - began
        await asyncio.sleep(duration)
        emojis_match = bool(a.snapshot['emojis']) and a.snapshot['emojis'] == b.snapshot['emojis']
        result = {'connected_seconds': round(connected_seconds, 3), 'emojis_match': emojis_match,
                'received': counters,
                'bidirectional_audio': all(counter['audio_signal_frames'] > 0 for counter in counters),
                'bidirectional_video': all(counter['video_frames'] > 0 for counter in counters) if video else None}
    finally:
        cleanup = await _cleanup(managers)
    result['cleanup_complete'] = cleanup
    result['success'] = bool(result['emojis_match'] and result['bidirectional_audio'] and
                             (result['bidirectional_video'] or not video) and cleanup)
    return result


async def verify_lifecycle(client_a, client_b, user_a, user_b):
    """Two authorized synthetic calls: reject, then voice/mute/camera controls."""
    counters = [dict(audio_frames=0, video_frames=0, audio_bytes=0, video_bytes=0) for _ in range(2)]
    managers = [CallManager(client, engine_factory=synthetic_process_factory(counter), timeout=40)
                for client, counter in zip((client_a, client_b), counters)]
    a, b = managers
    engines = []
    result = {}
    try:
        await asyncio.gather(a.enable(), b.enable())
        async with asyncio.timeout(120):
            await a.start(user_b, video=True)
            engines.append(a._engine)
            await _until(lambda: b.snapshot['state'] == 'incoming' and
                         b.snapshot['peer'] == user_a, managers)
            result['decline_without_receiver_capture'] = b._engine is None
            await b.decline(user_a, token=b.snapshot['token'])
            await _until(lambda: a.snapshot['state'] == 'ended', managers)
            result['decline_closed_caller'] = a._engine is None

            await a.start(user_b, video=False)
            await _until(lambda: b.snapshot['state'] == 'incoming', managers)
            await b.accept(user_a, video=False, token=b.snapshot['token'])
            await _until(lambda: all(manager.snapshot['state'] == 'active' for manager in managers),
                         managers, timeout=45)
            await _until(lambda: all(counter['audio_signal_frames'] > 0 for counter in counters), managers)
            result['voice_without_camera'] = (all(not manager.snapshot['video'] for manager in managers)
                and all(counter['video_frames'] == 0 for counter in counters))
            result['emojis_match'] = bool(a.snapshot['emojis']) and a.snapshot['emojis'] == b.snapshot['emojis']

            await a.mute(True, token=a.snapshot['token'])
            await _until(lambda: b.snapshot['remote_muted'], managers)
            await a.mute(False, token=a.snapshot['token'])
            await _until(lambda: not b.snapshot['remote_muted'], managers)
            result['mute_unmute'] = True

            for sender, receiver, counter in ((a, b, counters[1]), (b, a, counters[0])):
                previous = counter['video_frames']
                await sender.set_camera(True, token=sender.snapshot['token'])
                await _until(lambda: receiver.snapshot['remote_video'] and counter['video_frames'] > previous, managers)
                await sender.set_camera(False, token=sender.snapshot['token'])
                await _until(lambda: not receiver.snapshot['remote_video'], managers)
            result['camera_toggle_both_directions'] = True
            result['received'] = counters
    finally:
        result['cleanup_complete'] = await _cleanup(managers, engines)
    result['success'] = all(result[key] for key in ('decline_without_receiver_capture',
        'decline_closed_caller', 'voice_without_camera', 'emojis_match', 'mute_unmute',
        'camera_toggle_both_directions', 'cleanup_complete'))
    return result
