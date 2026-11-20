"""Display-direction rules: geometry changes must not change Telegram strings."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from tg_ascii import rtl_ui


class RtlTests(unittest.TestCase):
    def test_direction_and_mirrored_geometry(self):
        self.assertTrue(all(rtl_ui.rtl_language(code) for code in ('ar', 'he', 'ur')))
        self.assertFalse(any(rtl_ui.rtl_language(code) for code in ('en', 'es', 'hi', 'nb')))
        self.assertEqual(rtl_ui.mirrored_anchor('nw'), 'ne')
        self.assertEqual(rtl_ui.mirrored_anchor('center'), 'center')
        with patch.object(rtl_ui, 'rtl_language', return_value=True):
            self.assertEqual(rtl_ui.pane_order('sidebar', 'chat'), ['chat', 'sidebar'])
            self.assertEqual(rtl_ui.flow_position((20, 30, 70, 25), 300), (210, 30, 70, 25))

    def test_font_keeps_custom_choice_and_caches_installed_default(self):
        root = SimpleNamespace()
        with patch.object(rtl_ui.tkfont, 'families', return_value=('Arial', 'Geeza Pro')) as scan, \
                patch.object(rtl_ui.sys, 'platform', 'darwin'):
            self.assertEqual(rtl_ui.ui_font_family(root, 'Menlo', 'ar'), 'Menlo')
            scan.assert_not_called()
            self.assertEqual(rtl_ui.ui_font_family(root, '', 'ar'), 'Geeza Pro')
            self.assertEqual(rtl_ui.ui_font_family(root, '', 'ar'), 'Geeza Pro')
            scan.assert_called_once()

    def test_text_alignment_never_reads_or_rewrites_data(self):
        widget = Mock(spec=['tag_configure', 'tag_add', 'tag_remove', 'tag_lower'])
        with patch.object(rtl_ui, 'rtl_language', return_value=True):
            rtl_ui.align_text(widget)
        widget.tag_configure.assert_called_once_with(rtl_ui.TEXT_TAG, justify='right')
        widget.tag_add.assert_called_once_with(rtl_ui.TEXT_TAG, '1.0', 'end')
        with patch.object(rtl_ui, 'rtl_language', return_value=False):
            rtl_ui.align_text(widget)
        widget.tag_remove.assert_called_once_with(rtl_ui.TEXT_TAG, '1.0', 'end')

    def test_map_hook_installed_only_once_without_polling(self):
        root = SimpleNamespace(bind_all=Mock())
        rtl_ui.install(root)
        rtl_ui.install(root)
        root.bind_all.assert_called_once()
        self.assertEqual(root.bind_all.call_args.args[0], '<Map>')


if __name__ == '__main__':
    unittest.main()
