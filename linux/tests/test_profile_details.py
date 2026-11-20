import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,Mock
from datetime import datetime,timezone
from telethon import types as t,functions as f
from tg_ascii.backend import TelegramBackend
from tg_ascii.profile_details import profile_fields
from tg_ascii.desktop_profile import permission_enabled


def channel(**kwargs):
    return t.Channel(id=123,title='Team',photo=t.ChatPhotoEmpty(),date=datetime.now(timezone.utc),**kwargs)


class ProfileFieldsTests(unittest.TestCase):
    def test_channel_counts_description_permissions_and_links_are_preserved(self):
        entity=channel(megagroup=True,admin_rights=t.ChatAdminRights(ban_users=True,change_info=True),username='team')
        full=NS(participants_count=120,admins_count=3,online_count=4,linked_chat_id=456,can_view_participants=True,
            exported_invite=NS(link='https://t.me/+example'),ttl_period=86400)
        result=profile_fields(entity,full)
        self.assertEqual(result['kind'],'group');self.assertEqual(result['members_count'],120)
        self.assertEqual(result['linked_chat_id'],456);self.assertEqual(result['ttl_period'],86400)
        self.assertTrue(result['can_ban']);self.assertTrue(result['can_edit_info']);self.assertFalse(result['can_set_ttl'])

    def test_normal_members_cannot_administer_channel_or_change_reactions(self):
        for entity in (channel(broadcast=True),channel(megagroup=True)):
            result=profile_fields(entity,NS())
            for key in ('can_ban','can_invite','can_set_ttl','can_change_username','can_manage_reactions'):self.assertFalse(result[key],key)
        self.assertFalse(profile_fields(channel(broadcast=True),NS())['can_edit_info'])

    def test_contact_flags_and_basic_group_participant_count(self):
        result=profile_fields(t.User(9,first_name='Alice',contact=True,premium=True),NS(blocked=True,common_chats_count=2))
        self.assertTrue(result['blocked']);self.assertTrue(result['contact']);self.assertTrue(result['premium'])
        self.assertEqual(result['common_chats_count'],2)
        group=t.Chat(5,'Team',t.ChatPhotoEmpty(),2,datetime.now(timezone.utc),1)
        self.assertEqual(profile_fields(group,NS())['members_count'],2)
        self.assertTrue(profile_fields(group,NS())['can_view_members'])


class ProfileRequestTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client=AsyncMock();self.client.add_event_handler=Mock();self.backend=TelegramBackend(self.client)
        self.client.get_input_entity.return_value=t.InputPeerChannel(123,456)
        self.client.get_entity.return_value=channel(megagroup=True)

    async def test_full_channel_profile_keeps_full_data(self):
        self.client.return_value=NS(full_chat=NS(about='Description',participants_count=25,notify_settings=t.PeerNotifySettings(show_previews=False),ttl_period=86400))
        result=await self.backend.profile(-1000000000123)
        self.assertEqual(result['about'],'Description');self.assertEqual(result['members_count'],25)
        self.assertFalse(result['notify_settings'].show_previews);self.assertEqual(result['ttl_period'],86400)

    async def test_notification_changes_preserve_unrelated_fields_and_exact_peer(self):
        await self.backend.profile_notify(-1000000000123,{'show_previews':False})
        request=self.client.call_args.args[0]
        self.assertIsInstance(request,f.account.UpdateNotifySettingsRequest)
        self.assertEqual(request.peer.peer.channel_id,123)
        self.assertIsNone(request.settings.mute_until);self.assertIsNone(request.settings.sound)
        self.assertFalse(request.settings.show_previews)

    async def test_permission_merge_keeps_unknown_flags_and_does_not_mutate_snapshot(self):
        banned=t.ChatBannedRights(None,send_media=True,invite_users=True,edit_rank=True)
        self.backend.profile=AsyncMock(return_value=dict(id=-1000000000123,is_channel=True,kind='group',can_ban=True,default_banned_rights=banned))
        self.assertFalse(permission_enabled(banned,'send_photos'))
        await self.backend.profile_change(-1000000000123,'permissions',{'send_photos':True})
        request=self.client.call_args.args[0]
        self.assertIsInstance(request,f.messages.EditChatDefaultBannedRightsRequest)
        self.assertFalse(request.banned_rights.send_photos);self.assertTrue(request.banned_rights.send_videos)
        self.assertTrue(request.banned_rights.invite_users);self.assertTrue(request.banned_rights.edit_rank)
        self.assertTrue(banned.send_media);self.assertIsNone(banned.send_photos)

    async def test_lost_rights_and_invalid_settings_never_mutate(self):
        self.backend.profile=AsyncMock(return_value=dict(id=-1000000000123,kind='group',is_channel=True,can_ban=False))
        with self.assertRaises(ValueError):await self.backend.profile_change(-1000000000123,'slowmode',30)
        self.backend.profile.return_value['can_ban']=True
        with self.assertRaises(ValueError):await self.backend.profile_change(-1000000000123,'slowmode',7)
        with self.assertRaises(ValueError):await self.backend.profile_change(-1000000000123,'permissions',{'view_messages':False})
        self.client.assert_not_called()

    async def test_basic_group_edit_uses_bare_chat_id(self):
        self.backend.profile=AsyncMock(return_value=dict(id=-123,kind='group',is_channel=False,can_edit_info=True))
        await self.backend.profile_change(-123,'title','New title')
        request=self.client.call_args.args[0]
        self.assertIsInstance(request,f.messages.EditChatTitleRequest);self.assertEqual(request.chat_id,123)

    async def test_members_have_roles_and_next_page_offset(self):
        self.client.return_value=NS(users=[t.User(7,first_name='Alice')],participants=[t.ChannelParticipant(7,datetime.now(timezone.utc))],count=105)
        result=await self.backend.profile_members(-1000000000123,50,'Ali')
        self.assertEqual(result['next_offset'],51);self.assertTrue(result['more'])
        self.assertEqual(result['items'][0]['id'],7);self.assertEqual(result['items'][0]['role'],'Member')
        self.assertEqual(self.client.call_args.args[0].filter.q,'Ali')

    async def test_block_rejects_group_and_allows_specific_contact(self):
        with self.assertRaises(ValueError):await self.backend.profile_block(-1000000000123,True)
        self.client.assert_not_called()
        self.client.get_entity.return_value=t.User(7,access_hash=5)
        await self.backend.profile_block(7,True)
        self.assertIsInstance(self.client.call_args.args[0],f.contacts.BlockRequest)
