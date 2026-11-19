"""3.0.0.2: Personalization › Disable all animations (off by default)."""
from types import SimpleNamespace
import unittest

from tg_ascii.i18n import set_language, tr
from tg_ascii.preferences import DEFAULTS, animated_emoji_enabled, animations_allowed
from tg_ascii.motion import motion_event


class DisableAnimationsTests(unittest.TestCase):
    def test_off_by_default_and_overrides_animated_emoji(self):
        self.assertIs(DEFAULTS['reduce_animations'], False)
        self.assertTrue(animated_emoji_enabled({}))
        self.assertTrue(animated_emoji_enabled({'animated_emoji': True, 'reduce_animations': False}))
        self.assertFalse(animated_emoji_enabled({'animated_emoji': True, 'reduce_animations': True}))
        self.assertFalse(animated_emoji_enabled({'animated_emoji': False}))
        self.assertFalse(animations_allowed({'reduce_animations': True}))

    def test_swipe_motion_follows_the_switch(self):
        app = SimpleNamespace(_motion_settings={'schema': 1, 'enabled': True,
                                                'events': {'swipe_reply': {'enabled': True}}},
                              preferences=SimpleNamespace(values={'reduce_animations': True}))
        self.assertFalse(motion_event(app)['enabled'])
        app.preferences.values['reduce_animations'] = False
        self.assertTrue(motion_event(app)['enabled'])

    def test_label_is_translated(self):
        try:
            for code in ('es', 'fr', 'ja', 'ar', 'es-419'):
                set_language(code)
                self.assertNotEqual(tr('Disable all animations'), 'Disable all animations', code)
        finally:
            set_language('en')


if __name__ == '__main__':
    unittest.main()
