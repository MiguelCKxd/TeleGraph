import json
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from tg_ascii_mobile.tv import share_chat


class AppleTVSharingTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.entity = NS(noforwards=False)
        self.client = NS(get_entity=AsyncMock(return_value=self.entity), iter_messages=self.history)
        self.link = NS(connectionID=Mock(return_value='paired'), share_connection_=Mock(return_value=True))
        self.core = NS(backend=NS(client=self.client), account='a', tv_link=self.link, stage='ready',
                       chats=[NS(id=12, name='QA')], text=str, locked=False, in_background=False)

    async def history(self, entity, limit):
        self.assertIs(entity, self.entity)
        self.assertEqual(limit, 50)
        for text, protected, ttl in [('latest', False, None), ('private', True, None),
                                     ('temporary', False, 10), ('first', False, None)]:
            yield NS(raw_text=text, noforwards=protected, media=None, ttl_period=ttl)

    async def test_only_selected_chat_and_nonexpiring_shareable_text(self):
        self.assertTrue(await share_chat(self.core, 12, 'a'))
        payload, connection = self.link.share_connection_.call_args.args
        self.link.connectionID.assert_called_once_with()
        self.assertEqual(connection, 'paired')
        self.assertEqual(json.loads(payload), {'id': 12, 'title': 'QA', 'messages': ['first', 'latest']})

    async def test_disconnected_phone_does_not_fetch_chat(self):
        self.link.connectionID.return_value = None
        with self.assertRaisesRegex(ValueError, 'Conecta primero'):
            await share_chat(self.core, 12, 'a')
        self.client.get_entity.assert_not_awaited()
        self.link.share_connection_.assert_not_called()

    async def test_account_or_chat_protection_denies_transfer(self):
        with self.assertRaises(ValueError):
            await share_chat(self.core, 12, 'other')
        self.client.get_entity.assert_not_awaited()
        self.entity.noforwards = True
        with self.assertRaises(ValueError):
            await share_chat(self.core, 12, 'a')
        self.link.share_connection_.assert_not_called()

    async def test_phone_locked_while_loading_denies_transfer(self):
        async def interrupted(entity, limit):
            self.core.locked = True
            async for row in self.history(entity, limit):
                yield row
        self.client.iter_messages = interrupted
        with self.assertRaises(ValueError):
            await share_chat(self.core, 12, 'a')
        self.link.share_connection_.assert_not_called()
