"""Font resolution checks without a native display or account access."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from tg_ascii import typography


class TypographyTests(unittest.TestCase):
    def environment(self, available, proportional=()):
        named = {}
        def name_font(name, **kwargs):
            return named.setdefault(name, Mock(actual=Mock(return_value='Fixed Fallback')))
        def font(**kwargs):
            family = kwargs['family']
            return Mock(actual=Mock(return_value=family), metrics=Mock(return_value=1),
                        measure=lambda text: (4 if text == 'i' else 9) if family in proportional else 8)
        return patch.multiple(typography.tkfont, families=Mock(return_value=available),
                              nametofont=Mock(side_effect=name_font), Font=Mock(side_effect=font)), named

    def test_platform_defaults_are_installed_terminal_fonts(self):
        env, _ = self.environment(['Menlo', 'Consolas', 'Fixed Fallback'])
        with env:
            for platform, expected in [('darwin', 'Menlo'), ('win32', 'Consolas')]:
                with self.subTest(platform=platform), patch.object(typography.sys, 'platform', platform):
                    self.assertEqual(typography.terminal_family(None), expected)

    def test_rejects_proportional_substitution_and_absent_fonts(self):
        env, _ = self.environment(['Menlo', 'Courier New', 'Fixed Fallback'], proportional=['Menlo'])
        with env, patch.object(typography.sys, 'platform', 'darwin'):
            self.assertEqual(typography.terminal_family(None), 'Courier New')

    def test_missing_saved_font_uses_verified_default_and_named_fonts(self):
        env, named = self.environment(['Consolas', 'Fixed Fallback'])
        root = Mock()
        with env, patch.object(typography.sys, 'platform', 'win32'):
            self.assertEqual(typography.configure_fonts(root, 'Not installed', 14), 'Consolas')
        for value in named.values():
            value.configure.assert_called_with(family='Consolas', size=14)
        root.option_add.assert_any_call('*TCombobox*Listbox.font', 'TkDefaultFont')

    def test_explicit_custom_font_survives_and_code_stays_fixed(self):
        env, named = self.environment(['Consolas', 'Arial', 'Fixed Fallback'])
        with env, patch.object(typography.sys, 'platform', 'win32'):
            self.assertEqual(typography.configure_fonts(Mock(), 'arial', 12), 'Arial')
        named['TkTextFont'].configure.assert_called_with(family='Arial', size=12)
        named['TkFixedFont'].configure.assert_called_with(family='Consolas', size=12)

    def test_repeated_layout_rebuilds_do_not_rescan_fonts_or_reconfigure_named_fonts(self):
        env, named = self.environment(['Consolas', 'Arial', 'Fixed Fallback'])
        root = Mock()
        with env, patch.object(typography.sys, 'platform', 'win32'):
            for _ in range(25):
                self.assertEqual(typography.configure_fonts(root, 'arial', 12), 'Arial')
            typography.tkfont.families.assert_called_once_with(root)
            for value in named.values():
                value.configure.assert_called_once()
            typography.configure_fonts(root, 'arial', 14)
            self.assertEqual(typography.tkfont.families.call_count, 2)
        named['TkTextFont'].configure.assert_called_with(family='Arial', size=14)

    def test_fresh_font_picker_invalidation_and_other_roots_do_not_reuse_old_configuration(self):
        env, named = self.environment(['Consolas', 'Arial', 'Fixed Fallback'])
        root = Mock()
        with env, patch.object(typography.sys, 'platform', 'win32'):
            typography.configure_fonts(root, 'New font', 12)
            typography.tkfont.families.return_value += ['New font']
            root._font_configuration = None  # The selector refreshes the installed catalogue.
            self.assertEqual(typography.configure_fonts(root, 'New font', 12), 'New font')
            self.assertEqual(typography.configure_fonts(Mock(), 'New font', 12), 'New font')
            self.assertEqual(typography.tkfont.families.call_count, 3)
        named['TkTextFont'].configure.assert_called_with(family='New font', size=12)

    def test_opening_selector_fetches_newly_installed_fonts_and_invalidates_cached_resolution(self):
        from tg_ascii.desktop_tools import DesktopTools
        env, _ = self.environment(['Consolas', 'New font'])
        root = Mock()
        root._font_configuration = ('', 12, 'Consolas')
        app = SimpleNamespace(root=root, preferences=SimpleNamespace(values={'font_family': 'New font'}))
        with env, patch.object(typography.sys, 'platform', 'win32'), \
                patch('tg_ascii.desktop_tools.ttk.Label'), patch('tg_ascii.desktop_tools.Choice') as choice:
            picker, families = DesktopTools.font_picker(app, Mock())
            typography.tkfont.families.assert_called_once_with(root)
            self.assertEqual(families, ['Consolas', 'New font'])
            self.assertIn('New font', choice.call_args.kwargs['values'])
            picker.current.assert_called_once_with(2)
            self.assertIsNone(root._font_configuration)


if __name__ == '__main__':
    unittest.main()
