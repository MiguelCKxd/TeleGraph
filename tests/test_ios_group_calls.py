from threading import Lock
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from tg_ascii_mobile.ios_group_calls import IOSGroupProxy


class IOSGroupFramesTests(TestCase):
    def test_batch_preserves_latest_frame_per_camera_with_independent_throttling(self):
        proxy = IOSGroupProxy.__new__(IOSGroupProxy)
        camera = SimpleNamespace(value=1)
        screen = SimpleNamespace(value=2)
        mode = SimpleNamespace(value=3)
        proxy._module = SimpleNamespace(StreamDevice=SimpleNamespace(CAMERA=camera, SCREEN=screen))
        proxy._closing = False
        proxy._loop = Mock()
        proxy._last_frame = {}
        proxy._frame_lock = Lock()
        first = SimpleNamespace(ssrc=11)
        latest = SimpleNamespace(ssrc=11)
        second = SimpleNamespace(ssrc=22)
        third = SimpleNamespace(ssrc=33)

        with patch('tg_ascii_mobile.ios_group_calls.time.monotonic', side_effect=[5, 5.05, 5.2]):
            proxy._from_native('on_frames', 9, mode, camera, [first, second, latest])
            proxy._from_native('on_frames', 9, mode, camera, [latest, third])
            proxy._from_native('on_frames', 9, mode, camera, [latest, second, third])

        batches = [call.args[2][3] for call in proxy._loop.call_soon_threadsafe.call_args_list]
        self.assertEqual(batches, [[latest, second], [third], [latest, second, third]])
