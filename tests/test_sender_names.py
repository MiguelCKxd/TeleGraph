import unittest
from types import SimpleNamespace as NS
from datetime import datetime,timezone
from unittest.mock import Mock,AsyncMock
from telethon import types as t
from tg_ascii.backend import TelegramBackend
from tg_ascii.i18n import tr


def message(**kwargs):
    values=dict(id=1,out=False,sender_id=7,sender=None,raw_text='hello',date=datetime.now(timezone.utc))
    values.update(kwargs);return NS(**values)


class SenderNamesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client=AsyncMock();self.client.add_event_handler=Mock();self.backend=TelegramBackend(self.client)
    async def test_outgoing_channel_is_not_labelled_as_personal_you(self):
        sender=t.Channel(12,'News',t.ChatPhotoEmpty(),datetime.now(timezone.utc),broadcast=True)
        result=self.backend.message(message(out=True,sender_id=-1000000000012,sender=sender,post=True,post_author='Editor'))
        self.assertEqual(result.sender,'News · Editor');self.assertEqual(result.sender_id,-1000000000012)
    async def test_sender_id_is_recovered_from_attached_author(self):
        result=self.backend.message(message(sender_id=None,sender=t.User(7,first_name='Alice',last_name='Smith')))
        self.assertEqual(result.sender_id,7);self.assertEqual(result.sender,'Alice Smith')
    async def test_unknown_author_does_not_impersonate_telegram(self):
        result=self.backend.message(message(sender_id=555))
        self.assertEqual(result.sender,tr('Usuario')+' #555');self.assertEqual(result.sender_id,555)
    async def test_missing_names_are_fetched_once_per_unique_author_and_cached(self):
        self.client.get_entity.return_value=[t.User(7,first_name='Alice')]
        messages=[message(),message(id=2)]
        await self.backend.resolve_missing_senders(messages)
        self.client.get_entity.assert_awaited_once_with([7])
        self.assertEqual(self.backend.message(messages[0]).sender,'Alice')
        await self.backend.resolve_missing_senders(messages)
        self.client.get_entity.assert_awaited_once()
    async def test_attached_names_do_not_cause_network_requests(self):
        await self.backend.resolve_missing_senders([message(sender=t.User(7,first_name='Alice'))])
        self.client.get_entity.assert_not_called()
    async def test_forwarded_origin_is_not_mistaken_for_current_sender(self):
        result=self.backend.message(message(out=True,sender_id=7,fwd_from=NS(from_id=t.PeerUser(99),from_name='Other')))
        self.assertEqual(result.sender,tr('Tu'));self.assertEqual(result.sender_id,7)
    async def test_unavailable_names_do_not_break_history(self):
        self.client.get_entity.side_effect=ValueError('unknown entity')
        self.client.get_messages.return_value=[message()]
        result=await self.backend.history(42)
        self.assertEqual(result[0].sender_id,7)

    async def test_one_missing_entity_does_not_break_other_senders(self):
        async def entity(ids):
            if isinstance(ids,list) or ids==99:raise ValueError('missing')
            return t.User(ids,first_name='Alice')
        self.client.get_entity.side_effect=entity
        messages=[message(sender_id=99),message(sender_id=7)]
        await self.backend.resolve_missing_senders(messages)
        self.assertEqual(self.backend.message(messages[1]).sender,'Alice')
        self.assertEqual(self.backend.message(messages[0]).sender,tr('Usuario')+' #99')

    async def test_message_context_recovers_sender_when_raw_id_lookup_fails(self):
        self.client.get_entity.side_effect=ValueError('access hash unavailable')
        msg=message(get_sender=AsyncMock(return_value=t.User(7,first_name='Alice')))
        await self.backend.resolve_missing_senders([msg])
        self.assertEqual(self.backend.message(msg).sender,'Alice');msg.get_sender.assert_awaited_once()

    async def test_wrong_attached_telegram_entity_cannot_replace_author(self):
        msg=message(from_id=t.PeerUser(7),sender_id=777000,sender=t.User(777000,first_name='Telegram'))
        self.client.get_entity.return_value=[t.User(7,first_name='Alice')]
        await self.backend.resolve_missing_senders([msg])
        result=self.backend.message(msg)
        self.assertEqual((result.sender_id,result.sender),(7,'Alice'))

    async def test_empty_minimal_user_does_not_block_resolution(self):
        self.client.get_entity.return_value=[t.User(7,first_name='Alice')]
        msg=message(sender=t.User(7,min=True))
        await self.backend.resolve_missing_senders([msg])
        self.assertEqual(self.backend.message(msg).sender,'Alice')

    async def test_incoming_private_sender_can_use_attached_chat(self):
        msg=message(sender_id=None,peer_id=t.PeerUser(7),chat=t.User(7,first_name='Alice'))
        await self.backend.resolve_missing_senders([msg])
        self.assertEqual(self.backend.message(msg).sender,'Alice');self.client.get_entity.assert_not_called()

    async def test_channel_post_without_from_id_uses_channel_identity(self):
        channel=t.Channel(12,'News',t.ChatPhotoEmpty(),datetime.now(timezone.utc),broadcast=True)
        msg=message(sender_id=None,peer_id=t.PeerChannel(12),post=True,chat=channel)
        await self.backend.resolve_missing_senders([msg])
        self.assertEqual(self.backend.message(msg).sender,'News');self.client.get_entity.assert_not_called()
