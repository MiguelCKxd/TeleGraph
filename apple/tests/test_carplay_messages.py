from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from tg_ascii_mobile.siri import identifier, perform


class NotificationSearchTests(IsolatedAsyncioTestCase):
    def setUp(self):
        async def dialogs(limit):
            yield NS(id=17, name='QA', unread_count=1, dialog=NS(read_inbox_max_id=3))

        async def messages(peer, ids):
            self.assertEqual((peer, ids), (17, [9]))
            yield NS(id=9, date=datetime.now(timezone.utc), raw_text='QA', sender_id=17, out=False)

        self.backend = NS(client=NS(iter_dialogs=dialogs, iter_messages=messages),
                          notification_policy=AsyncMock(return_value={'enabled': True, 'preview': True}),
                          message=lambda raw: NS(sender='QA'))
        self.core = NS(locked=False, account='a', stage='ready', backend=self.backend, chats=[NS(id=17)],
                       accounts=NS(identities={'a': 70}), prefs=NS(values={}), lock_record=Mock(return_value=None))

    async def query(self, routes, **extra):
        return await perform(self.core, dict(op='search', notificationRoutes=routes, **extra), lambda: True)

    async def test_only_requested_incoming_message_is_returned(self):
        response = await self.query([[70, 17, 9]], unread=True)
        self.assertEqual([r['id'] for r in response], [identifier('a', 17, 9)])
        self.assertEqual(await self.query([[70, 17, 9]], ids=[identifier('a', 17, 10)]), [])
        self.assertEqual(await self.query([[70, 17, 9]], terms=['does not match']), [])

    async def test_other_account_unrecognized_chat_or_absent_route_cannot_widen_search(self):
        for routes in ([], [[71, 17, 9]], [[70, 19, 9]], [[70, 17]], [['70', 17, 9]]):
            with self.subTest(routes=routes):
                self.assertEqual(await self.query(routes), [])
        self.backend.notification_policy.assert_not_awaited()

    async def test_preview_is_checked_again_before_reading(self):
        self.core.prefs.values['notify_preview'] = False
        self.assertEqual(await self.query([[70, 17, 9]]), [])
        self.core.prefs.values.clear()
        self.core.lock_record.return_value = {'hash': 'protected'}
        self.assertEqual(await self.query([[70, 17, 9]]), [])
        self.core.lock_record.return_value = None
        self.backend.notification_policy.return_value = {'enabled': True, 'preview': False}
        self.assertEqual(await self.query([[70, 17, 9]]), [])
