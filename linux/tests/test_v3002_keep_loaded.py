"""3.0.0.2: Complex features › Keep more loaded (off by default)."""
import unittest

from tg_ascii import offline_store, resources
from tg_ascii.advanced_features import FEATURES, validated_features


class KeepLoadedTests(unittest.TestCase):
    def tearDown(self):
        resources.configure({})

    def test_off_by_default_and_listed_in_complex_features(self):
        self.assertIn('keep_loaded', FEATURES)
        self.assertFalse(validated_features({})['keep_loaded'])
        resources.configure({})
        self.assertFalse(resources.keep_loaded())
        self.assertEqual(resources.cache_entries(100), 100)
        self.assertEqual(offline_store.chat_limit(), offline_store.MAX_CHATS_WITH_HISTORY)

    def test_on_keeps_more_in_memory_and_offline_unless_memory_is_limited(self):
        resources.configure({'advanced_features': {'keep_loaded': True}})
        self.assertTrue(resources.keep_loaded())
        self.assertEqual(resources.cache_entries(100), 400)
        self.assertGreater(offline_store.chat_limit(), offline_store.MAX_CHATS_WITH_HISTORY)
        self.assertGreater(offline_store.message_limit(), offline_store.MAX_MESSAGES)
        resources.configure({'advanced_features': {'keep_loaded': True}, 'resource_ram': 'limited'})
        self.assertEqual(resources.cache_entries(100), 64)


if __name__ == '__main__':
    unittest.main()
