"""Decoration must be optional, bounded and preserve message interactions."""
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from tg_ascii.appearance import configure_shapes, _surface_image
from tg_ascii.preferences import DEFAULTS, Preferences
from tg_ascii.themes import DARK, LIGHT
from tg_ascii.visual_effects import (
    EFFECT_DEFAULTS, EFFECT_LIMITS, canvas_text, bind_text, validated_effects,
    text_effects_enabled, _wrapped_lines,
)


class EffectTests(unittest.TestCase):
    def test_default_effects_allocate_no_images_or_extra_canvas_items(self):
        self.assertFalse(text_effects_enabled(DEFAULTS))
        self.assertTrue(all(DEFAULTS[key] == value for key, value in EFFECT_DEFAULTS.items()))
        canvas = Mock()
        canvas._root.return_value = NS(_shape_values=DEFAULTS)
        canvas.create_text.return_value = 23
        self.assertEqual(canvas_text(canvas, 3, 4, text='Hello', tags=('message:2',)), 23)
        canvas.create_text.assert_called_once_with(3, 4, text='Hello', tags=('message:2',))
        canvas.addtag_withtag.assert_not_called()
        canvas.create_line.assert_not_called()

    def test_effect_settings_validate_limits_types_and_colours(self):
        for key, maximum in EFFECT_LIMITS.items():
            for invalid in (-1, maximum + 1, True, str(maximum), float(maximum)):
                self.assertEqual(validated_effects({key: invalid})[key], 0)
            self.assertEqual(validated_effects({key: maximum})[key], maximum)
        self.assertEqual(validated_effects({'text_shadow_color': '#ABC123'})['text_shadow_color'], '#abc123')
        self.assertEqual(validated_effects({'text_shadow_color': 'red;bad'})['text_shadow_color'], '')

    def test_effects_persist_and_can_return_to_exact_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            prefs = Preferences(directory)
            prefs.save({'button_border_width': 4, 'text_shadow_size': 3, 'text_shadow_color': '#123456'})
            self.assertEqual(Preferences(directory).values['text_shadow_color'], '#123456')
            prefs.save(EFFECT_DEFAULTS)
            self.assertEqual(prefs.values, DEFAULTS)

    def test_canvas_decorations_keep_message_tags_and_bounded_work(self):
        canvas = Mock()
        canvas._root.return_value = NS(_shape_values={**DEFAULTS, 'text_border_width': 4, 'text_shadow_size': 8})
        canvas.create_text.side_effect = range(1, 20)
        item = canvas_text(canvas, 10, 20, text='link 👋', tags=('message:4', 'link'))
        self.assertEqual(item, 10)
        self.assertEqual(canvas.create_text.call_count, 10)
        for call in canvas.create_text.call_args_list:
            self.assertEqual(call.kwargs['tags'], ('message:4', 'link'))
        self.assertEqual(canvas.addtag_withtag.call_count, 10)
        canvas.gettags.return_value = ('message:4', '_effect_text:10')
        action = Mock()
        bind_text(canvas, item, '<Button-1>', action)
        canvas.tag_bind.assert_called_once_with('_effect_text:10', '<Button-1>', action, None)

    def test_underline_lines_wrap_without_spanning_newlines(self):
        self.assertEqual(_wrapped_lines('one two\n\nend', len, 4), ['one', 'two', '', 'end'])
        self.assertEqual(_wrapped_lines('abcdef', len, 2), ['ab', 'cd', 'ef'])

    def test_canvas_underline_colour_width_and_clickable_parts(self):
        canvas = Mock()
        canvas._root.return_value = NS(_shape_values={**DEFAULTS, 'text_underline_size': 3, 'text_underline_color': '#ff0000'})
        canvas.create_text.return_value = 1
        canvas.create_line.side_effect = (2, 3)
        canvas.bbox.return_value = (5, 10, 36, 50)
        face = NS(measure=lambda text: len(text) * 10, metrics=lambda key: {'linespace': 20, 'ascent': 15}[key])
        with patch('tkinter.font.Font', return_value=face):
            canvas_text(canvas, 5, 10, text='one\ntwo', tags='message:9')
        self.assertEqual(canvas.create_line.call_count, 2)
        self.assertEqual(canvas.create_line.call_args.kwargs, {'fill': '#ff0000', 'width': 3, 'tags': 'message:9'})
        self.assertEqual(canvas.addtag_withtag.call_count, 3)

    def test_repeated_theme_radius_and_effect_changes_reuse_native_elements(self):
        class Photo:
            def __init__(self, image, **kwargs): self.size = image.size
            def paste(self, image): self.assert_size = image.size == self.size
        root = NS()
        style = Mock()
        style.layout.return_value = [('Button.border', {'children': [('Button.label', {})]})]
        values = {**DEFAULTS, 'button_radius': 8, 'menu_radius': 8}
        with patch('tg_ascii.appearance.ImageTk.PhotoImage', side_effect=Photo) as images:
            configure_shapes(root, style, values, DARK)
            element_count = style.element_create.call_count
            photo_count = images.call_count
            for call in style.element_create.call_args_list:
                if '.indicator' not in call.args[0]:
                    self.assertEqual(call.kwargs['padding'], 0)
            for index in range(30):
                configure_shapes(root, style, {**values, 'button_radius': index % 25,
                    'button_border_width': index % 13, 'menu_shadow_size': index % 13}, LIGHT if index % 2 else DARK)
            self.assertEqual(style.element_create.call_count, element_count)
            self.assertEqual(images.call_count, photo_count)
            self.assertLess(photo_count, 20)
            self.assertTrue(all(getattr(image, 'assert_size', True) for image in root._shape_images))
            configure_shapes(root, style, DEFAULTS, DARK)
            style.layout.assert_any_call('TButton', root._original_button_layout)

    def test_surface_shadow_and_border_do_not_change_photo_geometry(self):
        plain = _surface_image(0, '#ffffff', '#ff0000', '#000000')
        custom = _surface_image(24, '#ffffff', '#ff0000', '#000000', 12, 12, '#00ff00')
        self.assertEqual(plain.size, custom.size)
        self.assertEqual(custom.getpixel((100, 100)), (255, 255, 255))
        self.assertGreater(custom.getpixel((5, 100))[0], 240)
        self.assertLess(custom.getpixel((5, 100))[1], 30)
        self.assertGreater(custom.getpixel((205, 100))[1], 30)


if __name__ == '__main__':
    unittest.main()
