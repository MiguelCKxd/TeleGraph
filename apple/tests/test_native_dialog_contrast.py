"""Native dialog actions stay legible without overriding a readable system tint."""
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tg_ascii_mobile.native_dialogs import _android_button_contrast, _contrast_ratio


class DialogContrastTests(unittest.TestCase):
    def apply(self, background, foreground, primary, *, enabled=True):
        calls = []
        colors = SimpleNamespace(getColorForState=lambda *_: primary, getDefaultColor=lambda: primary)
        button = SimpleNamespace(isEnabled=lambda: enabled,
                                 getCurrentTextColor=lambda: foreground,
                                 getDrawableState=lambda: [16842910],
                                 setTextColor=calls.append)
        resources = SimpleNamespace(getColor=lambda *_: background,
                                    getColorStateList=lambda _: colors,
                                    recycle=lambda: calls.append('recycled'))
        attrs = SimpleNamespace(colorBackgroundFloating=1, textColorPrimary=2)
        context = SimpleNamespace(obtainStyledAttributes=lambda keys: resources)
        dialog = SimpleNamespace(getContext=lambda: context,
                                 getButton=lambda which: button if which == -2 else None)
        module = SimpleNamespace(jarray=lambda _: list, jclass=lambda _: attrs)
        with patch.dict(sys.modules, {'java': module}):
            _android_button_contrast(dialog)
        return calls, colors

    def test_dark_dialog_reproduced_accent_uses_native_foreground_state_list(self):
        # Pixel colors from the actual API36 dialog, not the web-view background.
        calls, colors = self.apply(0xFF424242, 0xFF0A190F, 0xFFFFFFFF)
        self.assertEqual(calls, ['recycled', colors])
        self.assertLess(_contrast_ratio(0xFF0A190F, 0xFF424242), 4.5)
        self.assertGreater(_contrast_ratio(0xFFFFFFFF, 0xFF424242), 4.5)

    def test_light_dialog_preserves_readable_accent(self):
        calls, _ = self.apply(0xFFFFFFFF, 0xFF006000, 0xFF000000)
        self.assertEqual(calls, ['recycled'])

    def test_light_dialog_bad_light_accent_uses_native_dark_foreground(self):
        calls, colors = self.apply(0xFFFFFFFF, 0xFFEEEEEE, 0xFF121212)
        self.assertEqual(calls, ['recycled', colors])

    def test_native_disabled_and_unknown_translucent_surfaces_are_untouched(self):
        for background, enabled in ((0xFF424242, False), (0x00424242, True)):
            with self.subTest(background=background, enabled=enabled):
                calls, _ = self.apply(background, 0xFF0A190F, 0xFFFFFFFF, enabled=enabled)
                self.assertEqual(calls, ['recycled'])

    def test_unreadable_theme_foreground_is_not_an_improvement(self):
        calls, _ = self.apply(0xFF424242, 0xFF0A190F, 0xFF202020)
        self.assertEqual(calls, ['recycled'])

    def test_argb_signed_values_and_alpha_are_handled(self):
        self.assertAlmostEqual(_contrast_ratio(-1, -16777216), 21)
        self.assertAlmostEqual(_contrast_ratio(0x00FFFFFF, 0xFF000000), 1)
        self.assertLess(_contrast_ratio(0x10FFFFFF, 0xFF424242), 4.5)


if __name__ == '__main__':
    unittest.main()
