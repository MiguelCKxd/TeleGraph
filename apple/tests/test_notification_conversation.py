from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock

from tg_ascii_mobile.core import Core


class AndroidNotificationConversationTests(IsolatedAsyncioTestCase):
    async def test_accept_only_a_saved_account_and_public_preview(self):
        core = object.__new__(Core)
        core.stage = 'ready'
        core.locked = False
        core.accounts = SimpleNamespace(identities={'account': 100})
        core.prefs = SimpleNamespace(values={})
        core.lock_record = Mock(return_value=None)
        core.native_take_notification_chat = Mock(return_value='account:-45')
        self.assertEqual(await core.api_take_notification_chat(), {'account': 'account', 'peer': -45})
        core.native_take_notification_chat.return_value = 'other:-45'
        self.assertIsNone(await core.api_take_notification_chat())
        core.native_take_notification_chat.return_value = 'account:-45'
        core.prefs.values['notify_preview'] = False
        self.assertIsNone(await core.api_take_notification_chat())
        core.prefs.values.clear()
        core.lock_record.return_value = {'hash': 'protected'}
        self.assertIsNone(await core.api_take_notification_chat())

    async def test_chooser_accepts_a_tap_and_loading_defers_it(self):
        core = object.__new__(Core)
        core.accounts = SimpleNamespace(identities={'other': 11})
        core.prefs = SimpleNamespace(values={})
        core.lock_record = Mock(return_value=None)
        core.native_take_notification_chat = Mock(return_value='other:77')
        core.stage = 'loading'
        core.locked = False
        self.assertIsNone(await core.api_take_notification_chat())
        core.native_take_notification_chat.assert_not_called()
        core.stage = 'choose_account'
        self.assertEqual(await core.api_take_notification_chat(), {'account': 'other', 'peer': 77})
