import json
from unittest import TestCase
from unittest.mock import Mock, patch

from tg_ascii_mobile import runtime


class AndroidPushDispatchTests(TestCase):
    def dispatch(self, hint):
        self.core = Mock()
        with patch.object(runtime, '_android_root'), patch.object(runtime, '_android_core', return_value=self.core), \
                patch('asyncio.run_coroutine_threadsafe') as self.schedule:
            return runtime.android_push(None, json.dumps(hint))

    def test_scoped_badge_and_unscoped_badge(self):
        for hint, recipient in (({'user_id': 23, 'badge_sent_at': 123}, 23), ({'badge_sent_at': 123}, None)):
            with self.subTest(hint=hint):
                self.dispatch(hint)
                self.core.sync_android_badge.assert_called_once_with(123, user_id=recipient)
                self.schedule.return_value.result.assert_called_once_with(timeout=90)

    def test_complete_route_takes_precedence(self):
        hint = {'user_id': 23, 'custom': {'from_id': 42, 'msg_id': 6}, 'badge_sent_at': 123}
        self.dispatch(hint)
        self.core.receive_push_payload.assert_called_once_with(json.dumps(hint))
        self.core.sync_android_badge.assert_not_called()

    def test_unusable_or_maintenance_hint_cannot_scan(self):
        for hint in ({'user_id': 23}, {'badge_sent_at': 123, 'user_id': None},
                     {'badge_sent_at': 123, 'user_id': -1},
                     {'user_id': 23, 'loc_key': 'READ_MESSAGES', 'custom': {'from_id': 42, 'msg_id': 6}},
                     {'badge_sent_at': 123, 'user_id': 23, 'loc_key': 'READ_HISTORY'}):
            with self.subTest(hint=hint):
                self.assertEqual(self.dispatch(hint), 1)
                self.core.sync_android_badge.assert_not_called()
                self.core.receive_push_payload.assert_not_called()
