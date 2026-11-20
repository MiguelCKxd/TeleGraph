import unittest
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,Mock
from telethon import types as t,functions as f
from tg_ascii.backend import TelegramBackend
from tg_ascii.community_management import merge_restrictions,admin_fields
from tg_ascii.telegram_actions import activity_text,peer_activity
from tg_ascii.i18n import set_language

def channel(ident=11,**kwargs):
    return t.Channel(ident,'QA',t.ChatPhotoEmpty(),datetime.now(timezone.utc),**kwargs)

class PresenceTests(unittest.TestCase):
    def setUp(self):set_language('en')
    def test_privacy_buckets_never_disclose_seconds(self):
        for status,label in ((t.UserStatusRecently(),'Last seen recently'),(t.UserStatusLastWeek(),'Last seen within a week'),(t.UserStatusLastMonth(),'Last seen within a month'),(t.UserStatusEmpty(),'Last seen a long time ago'),(None,'Last seen a long time ago')):
            self.assertEqual(activity_text(status),label);self.assertEqual(activity_text(status,True),label)
    def test_exact_seconds_opt_in(self):
        status=t.UserStatusOffline(datetime(2026,10,29,12,34,56,tzinfo=timezone.utc))
        self.assertFalse(activity_text(status).endswith(':56'));self.assertTrue(activity_text(status,True).endswith(':56'))
    def test_non_people_have_no_user_presence(self):
        self.assertEqual(peer_activity(channel(broadcast=True)),'Channel')
        self.assertEqual(peer_activity(channel(megagroup=True)),'Group')
        self.assertEqual(peer_activity(t.User(1,bot=True)),'Bot')

class CommunityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client=AsyncMock();self.client.add_event_handler=Mock();self.backend=TelegramBackend(self.client)
        self.owner=channel(creator=True,megagroup=True)
        self.client.get_entity.return_value=self.owner
        self.client.return_value=NS(chats=[self.owner],full_chat=NS())
    def member(self):
        return dict(entity=self.owner,person=t.User(5),participant=t.ChannelParticipant(5,datetime.now(timezone.utc)),role='Member',can_admin=True,can_ban=True,rights=None,banned=None,fields=admin_fields(self.owner))
    async def test_channel_creation_and_validation(self):
        self.client.return_value=NS(chats=[channel(broadcast=True)])
        result=await self.backend.create_community(' News ','About',True)
        req=self.client.call_args.args[0]
        self.assertIsInstance(req,f.channels.CreateChannelRequest);self.assertTrue(req.broadcast);self.assertFalse(req.megagroup)
        self.assertEqual(req.title,'News');self.assertEqual(result.kind,'channel');self.client.reset_mock()
        for title,about in (('',''),('x'*129,''),('Title','x'*256)):
            with self.assertRaises(ValueError):await self.backend.create_community(title,about)
        self.client.assert_not_called()
    async def test_fresh_full_entity_revokes_cached_rights(self):
        fresh=channel(megagroup=True,default_banned_rights=t.ChatBannedRights(None,invite_users=True))
        self.client.return_value=NS(chats=[fresh],full_chat=NS())
        with self.assertRaises(ValueError):await self.backend.community_add(11,[5])
        self.assertEqual(self.client.call_count,1)
    async def test_link_change_aborts_and_unlink_is_explicit_empty_channel(self):
        broadcast=channel(creator=True,broadcast=True);self.client.get_entity.return_value=broadcast
        self.client.return_value=NS(chats=[broadcast],full_chat=NS(linked_chat_id=99))
        with self.assertRaises(ValueError):await self.backend.set_discussion_group(11,None,expected_link=88)
        self.assertEqual(self.client.call_count,1)
        self.client.side_effect=[NS(chats=[broadcast],full_chat=NS(linked_chat_id=99)),True]
        await self.backend.set_discussion_group(11,None,expected_link=99)
        self.assertIsInstance(self.client.call_args.args[0].group,t.InputChannelEmpty)
    async def test_history_exposure_requires_consent_and_existing_link_is_protected(self):
        for full in (NS(hidden_prehistory=True),NS(linked_chat_id=88)):
            broadcast=channel(creator=True,broadcast=True);group=channel(22,creator=True,megagroup=True)
            self.client.reset_mock();self.client.get_entity.side_effect=[broadcast,group]
            self.client.side_effect=[NS(chats=[broadcast],full_chat=NS()),NS(chats=[group],full_chat=full)]
            with self.assertRaises(ValueError):await self.backend.set_discussion_group(11,22)
            self.assertEqual(self.client.call_count,2)
    async def test_permissions_preserve_unknown_flags_and_expand_aggregate_bans(self):
        before=t.ChatBannedRights(None,send_messages=True,edit_rank=True)
        after=merge_restrictions(before,{'send_photos':True})
        self.assertTrue(before.send_messages);self.assertFalse(after.send_photos)
        self.assertTrue(after.send_videos);self.assertTrue(after.send_plain);self.assertTrue(after.edit_rank)
    async def test_admin_cannot_grant_right_they_do_not_have(self):
        self.owner=channel(megagroup=True,admin_rights=t.ChatAdminRights(add_admins=True,invite_users=True))
        self.backend.community_member=AsyncMock(return_value=self.member())
        with self.assertRaises(ValueError):await self.backend.community_admin(11,5,{'ban_users':True})
        self.client.assert_not_called()
    async def test_admin_edit_preserves_existing_rights_and_rank(self):
        member=self.member();member['rights']=t.ChatAdminRights(manage_linked_peers=True);member['participant'].rank='Editor'
        self.backend.community_member=AsyncMock(return_value=member)
        await self.backend.community_admin(11,5,{'invite_users':True})
        req=self.client.call_args.args[0];self.assertTrue(req.admin_rights.manage_linked_peers)
        self.assertTrue(req.admin_rights.invite_users);self.assertEqual(req.rank,'Editor')
    async def test_lost_authorization_never_writes(self):
        member=self.member();member['can_admin']=member['can_ban']=False;self.backend.community_member=AsyncMock(return_value=member)
        with self.assertRaises(ValueError):await self.backend.community_admin(11,5,{'invite_users':True})
        with self.assertRaises(ValueError):await self.backend.community_restrict(11,5,action='ban')
        self.client.assert_not_called()
    async def test_ban_until_and_kick_have_distinct_semantics(self):
        self.backend.community_member=AsyncMock(return_value=self.member());until=datetime.now(timezone.utc)+timedelta(hours=1)
        await self.backend.community_restrict(11,5,action='ban',until=until)
        self.assertTrue(self.client.call_args.args[0].banned_rights.view_messages)
        self.assertEqual(self.client.call_args.args[0].banned_rights.until_date,until)
        self.client.reset_mock();await self.backend.community_restrict(11,5,action='remove')
        self.assertEqual(self.client.call_count,2);self.assertTrue(self.client.call_args_list[0].args[0].banned_rights.view_messages)
        self.assertFalse(self.client.call_args_list[1].args[0].banned_rights.view_messages)
    async def test_short_expiry_cannot_silently_become_permanent(self):
        self.backend.community_member=AsyncMock(return_value=self.member())
        with self.assertRaises(ValueError):await self.backend.community_restrict(11,5,action='ban',until=datetime.now(timezone.utc)+timedelta(seconds=10))
        self.client.assert_not_called()
    async def test_owner_and_self_are_protected(self):
        for person,part in ((t.User(5),t.ChannelParticipantCreator(5,t.ChatAdminRights())),(t.User(5,is_self=True),t.ChannelParticipant(5,datetime.now(timezone.utc)))):
            self.client.get_entity.side_effect=[self.owner,person]
            self.client.side_effect=[NS(chats=[self.owner],full_chat=NS()),NS(participant=part)]
            result=await self.backend.community_member(11,5)
            self.assertFalse(result['can_ban']);self.assertFalse(result['can_admin'])

    async def test_member_entities_are_deduplicated_by_resolved_peer(self):
        self.client.get_input_entity.return_value=t.InputPeerUser(5,66)
        await self.backend.community_add(11,[t.User(5),t.User(5)])
        req=self.client.call_args.args[0]
        self.assertIsInstance(req,f.channels.InviteToChannelRequest)
        self.assertEqual(len(req.users),1)
