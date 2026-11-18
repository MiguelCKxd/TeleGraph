import unittest
from datetime import datetime,timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from telethon import functions as f,types as t
from tg_ascii.peer_tools import PeerTools,HistoryPage,mute_deadline
from tg_ascii.shared_media import MediaPages
from tg_ascii.profile_customization import validate,status_object,set_native,overlay_profile
from tg_ascii.advanced_features import feature_enabled,validated_features


class PeerPaginationTests(unittest.TestCase):
    def test_empty_filtered_page_keeps_raw_cursor_and_more(self):
        pages=MediaPages(['polls'])
        ticket,offset=pages.begin('polls','')
        self.assertEqual(offset,0)
        self.assertTrue(pages.finish(ticket,HistoryPage([],next_offset=901,more=True)))
        ticket,offset=pages.begin('polls','',True)
        self.assertEqual(offset,901)
        self.assertTrue(pages.finish(ticket,HistoryPage([NS(id=900)],next_offset=802,more=True)))
        ticket,offset=pages.begin('polls','',True)
        self.assertEqual(offset,802)
        pages.finish(ticket,HistoryPage([],next_offset=802,more=True))
        self.assertFalse(pages.more['polls'])

    def test_refresh_owns_cursor_and_deduplicates_one_page(self):
        pages=MediaPages(['photos'])
        stale,_=pages.begin('photos','old')
        current,_=pages.begin('photos','new')
        self.assertFalse(pages.finish(stale,[NS(id=500)]))
        pages.finish(current,[NS(id=10),NS(id=10),NS(id=9)])
        self.assertEqual([m.id for m in pages.rows['photos']],[10,9])
        self.assertFalse(pages.more['photos'])

    def test_mute_deadline_special_values_and_bounds(self):
        now=datetime(2026,1,1,tzinfo=timezone.utc)
        self.assertEqual(mute_deadline(0,now).timestamp(),0)
        self.assertEqual(mute_deadline(-1,now).timestamp(),2147483647)
        self.assertEqual(mute_deadline(3600,now).timestamp(),now.timestamp()+3600)
        self.assertEqual(mute_deadline(10**50,now).timestamp(),2147483647)
        for bad in (True,-2,1.5,None):
            with self.assertRaises(ValueError):mute_deadline(bad)

    def test_advanced_features_are_explicit_booleans(self):
        from tg_ascii.advanced_features import DEFAULT_ON
        self.assertFalse(any(value for key, value in validated_features({}).items() if key not in DEFAULT_ON))
        for bad in ('yes',1,{},None):self.assertFalse(feature_enabled({'advanced_features':{'polls':bad}},'polls'))
        self.assertTrue(feature_enabled({'advanced_features':{'polls':True}},'polls'))
        self.assertFalse(feature_enabled({'advanced_features':{'unknown':True}},'unknown'))


class PeerRPCTests(unittest.IsolatedAsyncioTestCase):
    def backend(self):
        backend=PeerTools();backend.client=AsyncMock();backend.names={}
        backend.cache_name=lambda ident,name:backend.names.__setitem__(ident,name)
        backend.resolve_missing_senders=AsyncMock();backend.message=lambda m:NS(id=m.id)
        return backend

    async def test_poll_search_is_one_bounded_page_even_if_empty(self):
        backend=self.backend()
        backend.client.get_messages.return_value=[NS(id=1000-i,media=None) for i in range(100)]
        page=await backend.poll_messages(42,'q',1200)
        self.assertEqual(page,[]);self.assertTrue(page.more);self.assertEqual(page.next_offset,901)
        backend.client.get_messages.assert_awaited_once_with(42,search='q',limit=100,offset_id=1200)

    async def test_leave_group_does_not_revoke_history(self):
        backend=self.backend();backend.client.get_entity.return_value=t.Chat(8,'Group',t.ChatPhotoEmpty(),2,datetime.now(timezone.utc),1)
        await backend.leave_chat(-8)
        request=backend.client.call_args.args[0]
        self.assertIsInstance(request,f.messages.DeleteChatUserRequest)
        self.assertFalse(request.revoke_history);bytes(request)

    async def test_call_history_serializes_filter_and_skips_other_actions(self):
        backend=self.backend();backend.client.return_value=NS(messages=[],users=[],chats=[])
        result=await backend.call_history(missed=True)
        request=backend.client.call_args.args[0]
        self.assertIsInstance(request,f.messages.SearchRequest)
        self.assertIsInstance(request.peer,t.InputPeerEmpty)
        self.assertTrue(request.filter.missed);bytes(request)
        self.assertFalse(result['more'])

    async def test_profile_music_paginates_by_document_count(self):
        backend=self.backend();backend.client.get_input_entity.return_value=t.InputPeerUser(7,9)
        backend.client.return_value=NS(documents=[NS(id=i) for i in range(30)],count=61)
        result=await backend.profile_music(7,30)
        self.assertTrue(result['more']);self.assertEqual(result['next'],60)
        bytes(backend.client.call_args.args[0])

    async def test_final_call_page_does_not_resolve_old_contact(self):
        backend = self.backend()
        backend.client.get_input_entity.side_effect = ValueError('Contact unavailable')
        backend.client.return_value = NS(messages=[NS(id=9, peer_id=t.PeerUser(7),
            action=t.MessageActionPhoneCall(123, duration=12),
            date=datetime.now(timezone.utc), out=False)], users=[], chats=[])
        result = await backend.call_history()
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['duration'], 12)
        self.assertFalse(result['more'])
        self.assertIsNone(result['next'])
        backend.client.get_input_entity.assert_not_awaited()

    async def test_call_history_uses_message_id_cursor_without_resolving_peers(self):
        backend = self.backend()
        backend.client.return_value = NS(messages=[NS(id=100-i, peer_id=t.PeerUser(7),
            action=t.MessageActionPhoneCall(123), date=datetime.now(timezone.utc), out=False)
            for i in range(50)], users=[], chats=[])
        result = await backend.call_history(offset=101)
        self.assertEqual(backend.client.call_args.args[0].offset_id, 101)
        self.assertEqual(result['next'], 51)
        self.assertTrue(result['more'])
        backend.client.get_input_entity.assert_not_awaited()

    async def test_profile_main_tab_and_expiring_status_use_native_requests(self):
        backend=NS(client=AsyncMock())
        await set_native(backend,'main_tab','gifts')
        request=backend.client.call_args.args[0]
        self.assertIsInstance(request.tab,t.ProfileTabGifts);bytes(request)
        await set_native(backend,'emoji_status',{'document_id':123,'until':2147480000})
        request=backend.client.call_args.args[0]
        self.assertEqual(request.emoji_status.document_id,123);bytes(request)
        self.assertIsInstance(status_object({'document_id':123,'until':1}),t.EmojiStatusEmpty)
        for invalid in ({'document_id':1,'until':True},{'document_id':None,'until':10}):
            with self.assertRaises(ValueError):validate('emoji_status',invalid)

    def test_local_main_tab_never_changes_other_profiles(self):
        backend=NS(account_profile=NS(user_id=7),local_profile_design={'main_tab':'music'})
        own=overlay_profile(backend,{'id':7})
        self.assertIsInstance(own['main_tab'],t.ProfileTabMusic)
        other={'id':8};self.assertIs(overlay_profile(backend,other),other)


if __name__=='__main__':unittest.main()
