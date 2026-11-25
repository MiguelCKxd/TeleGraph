import tempfile
import unittest
from pathlib import Path

from tg_ascii import default_avatar as d


class DefaultAvatarTests(unittest.TestCase):
    def test_initials_follow_telegram(self):
        self.assertEqual(d.initials('Ana María López'), 'AL')
        self.assertEqual(d.initials('carlos'), 'C')
        self.assertEqual(d.initials('  '), '?')
        self.assertEqual(d.initials('Équipe de test'), 'ÉT')

    def test_colour_uses_bare_id_and_server_colour(self):
        self.assertEqual(d.color_index(-1000000000012), 12 % 7)
        self.assertEqual(d.color_index(12), d.color_index(-1000000000012))
        self.assertEqual(d.color_index(12, 3), 3)
        self.assertEqual(d.color_index(12, 99), 12 % 7)

    def test_render_is_round_and_cached(self):
        image = d.render(7, 'Ana López', 40)
        self.assertEqual(image.size, (40, 40))
        self.assertEqual(image.getpixel((0, 0))[3], 0)
        self.assertEqual(image.getpixel((20, 4))[3], 255)
        with tempfile.TemporaryDirectory() as folder:
            first = d.path(folder, 7, 'Ana López', 40)
            stamp = Path(first).stat().st_mtime_ns
            self.assertEqual(d.path(folder, 7, 'Ana López', 40), first)
            self.assertEqual(Path(first).stat().st_mtime_ns, stamp)
            self.assertNotEqual(d.path(folder, 7, 'Otro', 40), first)


if __name__ == '__main__':
    unittest.main()
