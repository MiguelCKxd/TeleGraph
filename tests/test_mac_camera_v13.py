import unittest
from tg_ascii.mac_camera import choose_format


class CameraFormatTests(unittest.TestCase):
    def test_only_real_supported_dimensions_are_selected_without_stretching(self):
        formats = [(640, 480, 24), (1280, 720, 24), (1920, 1080, 24)]
        self.assertEqual(choose_format(formats, (1920, 1080)), (1280, 720, 24))
        self.assertEqual(choose_format(formats, (1760, 1328)), (640, 480, 24))
        self.assertEqual(choose_format(formats, (16, 9), pixel_budget=640*480), (640, 480, 24))

    def test_unsupported_odd_huge_and_zero_dimensions_are_not_used(self):
        self.assertEqual(choose_format([(0, 0, 30), (9999, 9999, 30), (641, 481, 24)]), (640, 480, 24))

    def test_only_high_resolution_device_uses_smallest_actual_format(self):
        self.assertEqual(choose_format([(1920, 1080, 24), (3840, 2160, 30)]), (1920, 1080, 24))
