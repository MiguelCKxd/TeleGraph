from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock

from tg_ascii_mobile.ios_screen_share import BGRA, NV12_FULL, NV12_VIDEO, ScreenShare, i420


class ScreenPixelsTests(TestCase):
    def test_padded_nv12_rows_are_packed_as_i420(self):
        source = [(bytes([16, 17, 255, 18, 19, 255]), 3), (bytes([100, 155, 255]), 3)]
        self.assertEqual(i420(NV12_VIDEO, 2, 2, source), (bytes([16, 17, 18, 19, 100, 155]), 2, 2))

    def test_full_range_is_normalized(self):
        source = [(bytes([0, 255, 0, 255]), 2), (bytes([0, 255]), 2)]
        self.assertEqual(i420(NV12_FULL, 2, 2, source), (bytes([16, 235, 16, 235, 16, 240]), 2, 2))

    def test_bgra_black_keeps_neutral_chroma(self):
        source = [(b'\x00\x00\x00\xff' * 4, 8)]
        self.assertEqual(i420(BGRA, 2, 2, source), (bytes([16, 16, 16, 16, 128, 128]), 2, 2))


class ScreenLeaseTests(IsolatedAsyncioTestCase):
    async def test_late_capture_cannot_publish_to_replacement_call(self):
        engine = SimpleNamespace(send_screen_frame=AsyncMock())
        capture = SimpleNamespace(start=AsyncMock(return_value=True), stop=Mock())

        class Manager(ScreenShare):
            screen_capture = capture
            _engine = engine
            _call = SimpleNamespace(state='active', screen=False, peer=42)

            def _check(self, *, token):
                return self._call

            async def set_screen(self, source, *, token):
                self._call.screen = bool(source)

        manager = Manager()
        await manager.share_screen(True, token='original')
        lease, frame, _ = capture.start.call_args.args
        await frame(b'frame', 10, 0, 2, 2)
        engine.send_screen_frame.assert_awaited_once_with(42, b'frame', 10, 0, 2, 2)

        await manager.share_screen(False, token='original')
        capture.stop.assert_called_once_with(lease)
        await manager.share_screen(True, token='next')
        await frame(b'late', 20, 0, 2, 2)
        self.assertEqual(engine.send_screen_frame.await_count, 1)
