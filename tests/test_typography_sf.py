import tkinter as tk
import unittest

from tg_ascii import typography


class SystemFontTests(unittest.TestCase):
    def test_sf_faces_only_on_apple(self):
        self.assertIn('.AppleSystemUIFont', typography.apple_system_families('darwin'))
        self.assertEqual(typography.apple_system_families('linux'), {})

    def test_sf_choice_survives_font_configuration(self):
        if typography.sys.platform != 'darwin':
            self.skipTest('macOS only')
        root = tk.Tk(); root.withdraw()
        try:
            self.assertEqual(typography.configure_fonts(root, '.AppleSystemUIFontRounded', 14), '.AppleSystemUIFontRounded')
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
