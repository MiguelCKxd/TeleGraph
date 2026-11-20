"""1.5.5: GPU video in group calls (complex feature, off by default)."""
import os
import unittest
from unittest.mock import Mock, patch

from tg_ascii import gpu_video
from tg_ascii.advanced_features import validated_features


class GpuVideoLogicTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop(gpu_video.ENVIRONMENT, None)

    def test_off_by_default_and_needs_the_expanded_view(self):
        features = validated_features({})
        self.assertFalse(features['gpu_video'] or features['group_video_grid'])
        self.assertFalse(gpu_video.configure({}))
        self.assertNotIn(gpu_video.ENVIRONMENT, os.environ)
        both = {'advanced_features': {'gpu_video': True, 'group_video_grid': True}}
        self.assertTrue(gpu_video.configure(both))
        self.assertEqual(os.environ.get(gpu_video.ENVIRONMENT), '1')
        self.assertFalse(gpu_video.configure({'advanced_features': {'gpu_video': True, 'group_video_grid': False}}))
        self.assertNotIn(gpu_video.ENVIRONMENT, os.environ)
        self.assertFalse(gpu_video.configure({'advanced_features': {'gpu_video': 'yes', 'group_video_grid': True}}))

    def test_bigger_and_smoother_budget_than_the_cpu_grid(self):
        from tg_ascii.calls_group_worker import slot_budget
        for cameras in (1, 4, 9, 16, 30):
            gpu, cpu = gpu_video.gpu_budget(cameras), slot_budget(cameras)
            self.assertLessEqual(gpu[0], cpu[0])
            if cpu[1] is not None:
                self.assertGreaterEqual(gpu[1][0], cpu[1][0])

    def test_grid_cells_and_aspect_fit(self):
        self.assertEqual(len(gpu_video.cells(30, 1200, 600)), 30)
        x, y, w, h = gpu_video.fit((320, 180), (0, 0, 400, 400))
        self.assertEqual((w, h), (400, 225))
        self.assertEqual(y, (400 - 225) // 2)
        self.assertEqual(gpu_video.fit((320, 180), (0, 0, 400, 400), 90)[2:], (225, 400))

    def test_without_sdl_the_normal_grid_is_kept(self):
        with patch.dict('sys.modules', {'sdl2': None}):
            self.assertIsNone(gpu_video.GpuVideoWindow.open())


@unittest.skipUnless(os.environ.get('TG_ASCII_GPU_TESTS') == '1', 'opens a real GPU window')
class GpuWindowTests(unittest.TestCase):
    def test_real_window_draws_i420_frames(self):
        window = gpu_video.GpuVideoWindow.open('TG-ASCII test')
        self.assertIsNotNone(window)
        try:
            frame = {'width': 33, 'height': 17, 'data': bytes(33 * 17 + 2 * 17 * 9), 'rotation': 90}
            self.assertTrue(window.show([1, 2], {1: frame, 2: dict(frame, rotation=0)}))
            self.assertEqual(set(window.textures), {1, 2})
            self.assertTrue(window.show([2], {}))
            self.assertEqual(set(window.textures), {2})
        finally:
            window.close()
        self.assertFalse(window.alive())


if __name__ == '__main__':
    unittest.main()
