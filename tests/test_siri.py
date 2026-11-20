from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from tg_ascii_mobile.siri import identifier, perform


class SiriMessagingTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.backend = NS(send=AsyncMock(), mark_read=AsyncMock())
        self.core = NS(locked=False, account='active', stage='ready', backend=self.backend,
                       chats=[NS(id=17, name='Ana'), NS(id=18, name='Ana')])

    async def test_resolution_disambiguates_and_sending_requires_active_recipient(self):
        results = await perform(self.core, {'op': 'resolve', 'name': 'ana'})
        self.assertEqual([item['id'] for item in results], [identifier('active', 17), identifier('active', 18)])
        for account in ['previous', 'active']:
            request = {'op': 'send', 'conversation': identifier(account, 17), 'text': 'hello'}
            if account == 'previous':
                with self.assertRaises(ValueError):
                    await perform(self.core, request)
            else:
                await perform(self.core, request)
        self.backend.send.assert_awaited_once_with(17, 'hello')

    async def test_mark_read_is_bounded_and_lock_prevents_sending_and_reading(self):
        request = {'op': 'read', 'ids': [identifier('active', 18, i) for i in (5, 3)]}
        await perform(self.core, request)
        self.backend.mark_read.assert_awaited_once_with(18, 5)
        self.core.locked = True
        for op in ('send', 'search', 'read', 'resolve'):
            with self.assertRaises(PermissionError):
                await perform(self.core, {'op': op})
