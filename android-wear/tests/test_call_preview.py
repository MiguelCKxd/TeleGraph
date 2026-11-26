import io
import unittest

from PIL import Image

from tg_ascii_mobile.android_calls import frame_jpeg_bytes


class CallPreviewTests(unittest.TestCase):
    def test_preview_retains_colour_position_and_rotation_after_downscaling(self):
        # Four non-clipped YCbCr regions make orientation/colour loss visible.
        width, height = 1920, 1080
        values = ((65, 112, 140), (115, 145, 105), (170, 100, 145), (210, 145, 110))
        planes = []
        for channel, (w, h) in enumerate(((width, height), (width // 2, height // 2), (width // 2, height // 2))):
            planes.append(b''.join(bytes([values[(y >= h // 2) * 2][channel]]) * (w // 2) +
                                   bytes([values[(y >= h // 2) * 2 + 1][channel]]) * (w - w // 2)
                                   for y in range(h)))
        frame = {'width': width, 'height': height, 'rotation': 90, 'data': b''.join(planes)}
        with Image.open(io.BytesIO(frame_jpeg_bytes(frame))) as result:
            self.assertEqual(result.size, (270, 480))
            # Clockwise: original bottom-left becomes top-left.
            for point, colour in zip(((35, 60), (235, 60), (35, 420), (235, 420)),
                                     (values[2], values[0], values[3], values[1])):
                expected = Image.new('YCbCr', (1, 1), colour).convert('RGB').getpixel((0, 0))
                self.assertLessEqual(max(abs(a - b) for a, b in zip(result.getpixel(point), expected)), 4)

    def test_small_odd_frames_keep_dimensions_without_upscaling(self):
        for width, height, rotation in ((1, 1, 0), (3, 5, 0), (3, 5, 270), (11, 2, 180)):
            with self.subTest(width=width, height=height, rotation=rotation):
                size = width * height + 2 * ((width + 1) // 2) * ((height + 1) // 2)
                frame = {'width': width, 'height': height, 'rotation': rotation, 'data': bytes([128]) * size}
                with Image.open(io.BytesIO(frame_jpeg_bytes(frame))) as result:
                    self.assertEqual(result.size, (height, width) if rotation in (90, 270) else (width, height))

    def test_invalid_frame_or_target_is_rejected_before_allocating_preview(self):
        valid = {'width': 2, 'height': 2, 'rotation': 0, 'data': bytes(6)}
        for frame, target in (({**valid, 'width': 0}, 480), ({**valid, 'width': 4097}, 480),
                              ({**valid, 'data': bytes(5)}, 480), ({**valid, 'data': bytes(7)}, 480),
                              (valid, 0), (valid, 4097)):
            with self.subTest(frame=frame, target=target), self.assertRaises(ValueError):
                frame_jpeg_bytes(frame, target)
