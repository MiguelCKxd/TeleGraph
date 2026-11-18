import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from telethon import types as t,functions as f
from telethon.errors import GroupcallForbiddenError
from tg_ascii.conference_invitations import invitation

class InvitationsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.backend=NS(client=AsyncMock(),checked_message=AsyncMock(return_value=NS(action=t.MessageActionConferenceCall(33,active=True,video=True))))
    async def test_fresh_server_state_supplies_title_count_and_people(self):
        self.backend.client.return_value=NS(call=t.GroupCall(33,44,7,20,1,title='Public fixture'),users=[t.User(5,first_name='Fixture')],participants=[NS(peer=t.PeerUser(5))])
        result=await invitation(self.backend,4,90)
        self.assertTrue(result['joinable']);self.assertEqual(result['title'],'Public fixture');self.assertEqual(result['count'],7)
        self.assertEqual(result['participants'],['Fixture']);self.assertTrue(result['video'])
        request=self.backend.client.call_args.args[0];self.assertIsInstance(request,f.phone.GetGroupCallRequest)
        self.assertEqual(request.call.msg_id,90);self.backend.checked_message.assert_awaited_once_with(4,90)
    async def test_inaccessible_invitation_does_not_invent_an_expulsion(self):
        self.backend.client.side_effect=GroupcallForbiddenError(None)
        result=await invitation(self.backend,4,90)
        self.assertFalse(result['joinable']);self.assertEqual(result['state'],'unavailable')
    async def test_ended_message_skips_extra_metadata_request(self):
        self.backend.checked_message.return_value.action=t.MessageActionConferenceCall(33,missed=True)
        result=await invitation(self.backend,4,90);self.assertFalse(result['joinable']);self.assertEqual(result['state'],'missed');self.backend.client.assert_not_called()
    async def test_discarded_or_changed_call_cannot_join(self):
        self.backend.client.return_value=NS(call=t.GroupCallDiscarded(33,44,0))
        self.assertFalse((await invitation(self.backend,4,90))['joinable'])
        self.backend.client.return_value=NS(call=t.GroupCall(34,44,7,20,1))
        with self.assertRaises(ValueError):await invitation(self.backend,4,90)

    async def test_pending_invite_without_active_flag_still_resolves(self):
        self.backend.checked_message.return_value.action=t.MessageActionConferenceCall(33)
        self.backend.client.return_value=NS(call=t.GroupCall(33,44,2,20,1),users=[],participants=[])
        result=await invitation(self.backend,4,90)
        self.assertTrue(result['joinable']);self.backend.client.assert_awaited_once()
