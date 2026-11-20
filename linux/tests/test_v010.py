import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,Mock,patch
from telethon import types as t,functions as f
from tg_ascii.backend import TelegramBackend,Chat
from tg_ascii.folder_features import folder_title,folder_slug,shift_title_entities,MemoryFolders
from tg_ascii.telegram_features import matches_folder
from tg_ascii.rich_preview import preview_runs
from tg_ascii.image_gestures import wheel_motion,bounded_pan
from tg_ascii.image_tools import zoom_at


def folder(number=2,**kw):
    return t.DialogFilter(number,t.TextWithEntities('Work',[]),[],[t.InputPeerUser(1,0)],[],**kw)


class FolderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client=AsyncMock();self.client.add_event_handler=Mock()
        self.backend=TelegramBackend(self.client)
        self.current=folder(groups=True)
        async def rpc(request):
            if isinstance(request,f.messages.GetDialogFiltersRequest):return NS(filters=[t.DialogFilterDefault(),self.current],tags_enabled=False)
            return True
        self.client.side_effect=rpc
        self.client.get_input_entity.side_effect=lambda p:t.InputPeerUser(p,0)

    async def test_patch_fresh_folder_preserves_new_server_changes_and_title_entities(self):
        old=folder();self.current.title=t.TextWithEntities('😀 Work',[t.MessageEntityCustomEmoji(0,2,99)])
        self.current.include_peers.append(t.InputPeerUser(7,0));self.current.color=4
        saved=await self.backend.save_folder(None,existing=old,options={'exclude_muted':True})
        self.assertEqual([p.user_id for p in saved.include_peers],[1,7])
        self.assertEqual(saved.title.entities[0].document_id,99)
        self.assertEqual(saved.color,4);self.assertTrue(saved.exclude_muted);self.assertIsNone(self.current.exclude_muted)

    async def test_member_edit_detects_concurrent_changes_instead_of_erasing_them(self):
        old=folder(groups=True)
        self.current.include_peers.append(t.InputPeerUser(9,0))
        with self.assertRaises(ValueError):await self.backend.save_folder(None,[1,2],old)
        self.assertFalse(any(isinstance(c.args[0],f.messages.UpdateDialogFilterRequest) for c in self.client.call_args_list))

    async def test_new_folder_can_contain_rules_without_explicit_chat(self):
        created=await self.backend.save_folder('Groups',[],options={'groups':True,'exclude_read':True})
        self.assertEqual(created.id,3);self.assertTrue(created.groups)
        with self.assertRaises(ValueError):await self.backend.save_folder('Empty',[])

    async def test_deleted_folder_not_resurrected(self):
        with self.assertRaises(ValueError):await self.backend.save_folder('Lost',existing=folder(9))
        self.assertFalse(any(isinstance(c.args[0],f.messages.UpdateDialogFilterRequest) for c in self.client.call_args_list))

    async def test_shared_folder_rejects_rules_and_exclusions(self):
        self.current=t.DialogFilterChatlist(2,t.TextWithEntities('Team',[]),[],[t.InputPeerChannel(7,0)])
        with self.assertRaises(ValueError):await self.backend.save_folder('Team',existing=self.current,options={'groups':True})
        with self.assertRaises(ValueError):await self.backend.save_folder('Team',existing=self.current,excluded=[1])

    async def test_folder_pin_does_not_change_global_pins_or_drop_members(self):
        await self.backend.pin_in_folder(self.current,7,True)
        request=self.client.call_args.args[0]
        self.assertIsInstance(request,f.messages.UpdateDialogFilterRequest)
        self.assertEqual([p.user_id for p in request.filter.pinned_peers],[7])
        self.assertEqual([p.user_id for p in request.filter.include_peers],[1])
        self.assertTrue(request.filter.groups)

    async def test_reorder_rejects_stale_missing_folder_and_keeps_all_chats(self):
        with self.assertRaises(ValueError):await self.backend.reorder_folders([2])
        await self.backend.reorder_folders([2,0])
        self.assertEqual(self.client.call_args.args[0].order,[2,0])

    async def test_share_rejects_users_and_non_members(self):
        with self.assertRaises(ValueError):await self.backend.export_folder_invite(self.current,'People',[1])
        self.client.get_input_entity.side_effect=lambda p:t.InputPeerChannel(p,0)
        with self.assertRaises(ValueError):await self.backend.export_folder_invite(self.current,'Other',[8])

    async def test_update_poll_obeys_server_interval_even_after_accept(self):
        result=NS(missing_peers=[t.PeerChannel(4)],chats=[],users=[])
        async def rpc(req):
            if isinstance(req,f.help.GetAppConfigRequest):return NS(config=NS(value=[NS(key='chatlist_update_period',value=NS(value=900))]))
            if isinstance(req,f.chatlists.GetChatlistUpdatesRequest):return result
            return True
        self.client.side_effect=rpc
        with patch('tg_ascii.folder_features.time.monotonic',return_value=100):
            first=await self.backend.folder_updates(self.current)
            await self.backend.accept_folder_updates(self.current,[1])
            again=await self.backend.folder_updates(self.current)
        self.assertIs(first,again);self.assertFalse(again.missing_peers)
        calls=[c for c in self.client.call_args_list if isinstance(c.args[0],f.chatlists.GetChatlistUpdatesRequest)]
        self.assertEqual(len(calls),1)

    async def test_memory_demo_uses_same_rules_and_preserves_peer_kind(self):
        owner=NS(demo_folders=[]);api=MemoryFolders(owner)
        created=await api.save_folder('Demo',[-1000000000007],options={'bots':True})
        self.assertIsInstance(created.include_peers[0],t.InputPeerChannel)
        changed=await api.save_folder(None,existing=created,options={'exclude_muted':True})
        self.assertTrue(changed.bots and changed.exclude_muted)
        await api.reorder_folders([created.id,0]);self.assertEqual(api.folder_order,[created.id,0])


class RichAndGestureTests(unittest.TestCase):
    def test_previews_consume_whole_utf16_custom_emoji_and_never_repeat_fallback(self):
        text='A 😀 ok';entities=[t.MessageEntityCustomEmoji(2,2,42)]
        self.assertEqual(list(preview_runs(text,entities)),[('A ',None),('',42),(' ok',None)])
        self.assertEqual(list(preview_runs(text,entities,3)),[('A ',None),('',42),('…',None)])

    def test_folder_title_validation_and_entity_movement(self):
        value=t.TextWithEntities('😀 X',[t.MessageEntityCustomEmoji(0,2,5)])
        self.assertEqual(folder_title(value).entities[0].document_id,5)
        self.assertEqual(folder_title(value.text,value).entities[0].document_id,5)
        shifted=shift_title_entities('😀 X','A😀 X',value.entities)
        self.assertEqual(shifted[0].offset,1)
        self.assertEqual(shift_title_entities('😀 X','Z X',value.entities),[])
        with self.assertRaises(ValueError):folder_title('😀'*7)
        with self.assertRaises(ValueError):folder_title(t.TextWithEntities('😀',[t.MessageEntityCustomEmoji(1,1,5)]))

    def test_invite_urls_are_restricted_to_folder_links(self):
        self.assertEqual(folder_slug('https://t.me/addlist/Ab_cd-1'),'Ab_cd-1')
        self.assertEqual(folder_slug('tg://addlist?slug=Ab_cd-1'),'Ab_cd-1')
        for bad in ('https://evil.example/addlist/abc','https://t.me/addlist/abc/extra','file:///tmp/x','https://t.me/user'):
            with self.assertRaises(ValueError):folder_slug(bad)

    def test_manual_unread_matches_unread_filter(self):
        filt=folder(contacts=True,exclude_read=True)
        self.assertTrue(matches_folder(Chat(7,'A',contact=True,unread_mark=True),filt))
        self.assertFalse(matches_folder(Chat(7,'A',contact=True),filt))

    def test_zoom_pan_horizontal_and_fractional_trackpad(self):
        event=NS(delta=1,state=0,num=None)
        kind,value=wheel_motion(event,'zoom','darwin');self.assertEqual(kind,'zoom');self.assertLess(value,1)
        self.assertEqual(wheel_motion(event,'pan','darwin'),('y',3))
        event.state=1;self.assertEqual(wheel_motion(event,'zoom','darwin'),('x',3))
        event.state=4;self.assertEqual(wheel_motion(event,'pan','darwin')[0],'zoom')
        event.delta=-120;event.state=0;self.assertEqual(wheel_motion(event,'pan','win32'),('y',-40))
        self.assertEqual(bounded_pan([999,-999],(800,600),(400,400),1),[200,-100])
        self.assertEqual(bounded_pan([999,-999],(80,60),(400,400),1),[0,0])
        scale,pan=zoom_at(1,[0,0],2,(300,200),(400,400));self.assertEqual((scale,pan),(2,[-100,0]))


class StickerTests(unittest.IsolatedAsyncioTestCase):
    async def test_open_custom_pack_and_install_use_correct_telegram_identity(self):
        client=AsyncMock();client.add_event_handler=Mock();backend=TelegramBackend(client)
        ref=t.InputStickerSetID(8,9)
        doc=NS(id=42,attributes=[t.DocumentAttributeCustomEmoji('😀',ref)])
        result=NS(set=NS(id=8,access_hash=9))
        async def rpc(req):return [doc] if isinstance(req,f.messages.GetCustomEmojiDocumentsRequest) else result
        client.side_effect=rpc
        await backend.document_pack(42)
        self.assertIsInstance(client.call_args.args[0],f.messages.GetStickerSetRequest)
        self.assertEqual(client.call_args.args[0].stickerset.id,8)
        await backend.install_pack(result.set)
        req=client.call_args.args[0];self.assertIsInstance(req,f.messages.InstallStickerSetRequest);self.assertFalse(req.archived)
        with self.assertRaises(ValueError):await backend.document_pack(NS(attributes=[]))


class GestureWidget:
    def __init__(self):self.bindings={};self.timers={};self.next=0
    def bind(self,seq,fn,add=None):self.bindings[seq]=fn
    def after(self,delay,fn):self.next+=1;self.timers[self.next]=fn;return self.next
    def after_cancel(self,key):self.timers.pop(key,None)
    def winfo_exists(self):return True


class GestureTests(unittest.TestCase):
    def make(self,**kwargs):
        from tg_ascii.interactions import ContextGesture
        widget=GestureWidget();menu=Mock();single=Mock();reply=Mock();animate=Mock()
        gesture=ContextGesture(widget,lambda e:42,menu,single=single,reply=reply,animate=animate,**kwargs)
        return widget,gesture,menu,single,reply,animate
    def test_single_does_not_open_message_tools_hold_and_right_do(self):
        w,g,menu,single,reply,animate=self.make(double=True)
        event=NS(x=10,y=20)
        g.press(event);g.release(event)
        menu.assert_not_called();single.assert_called_once_with(42)
        single.reset_mock();g.press(event);g.hold();g.release(event)
        menu.assert_called_once_with(42);single.assert_not_called()
        g.right(event);self.assertEqual(menu.call_count,2)
    def test_chat_hold_does_not_open_or_read_chat_and_no_double_menu_binding(self):
        w,g,menu,open_chat,reply,animate=self.make(consume=True)
        self.assertEqual(g.press(NS(x=10,y=20)),'break')
        g.hold();g.release(NS(x=10,y=20))
        open_chat.assert_not_called();menu.assert_called_once()
        self.assertNotIn('<Double-Button-1>',w.bindings)
    def test_double_menu_and_left_swipe_do_not_trigger_single_or_reaction(self):
        w,g,menu,single,reply,animate=self.make(double=True)
        g.press(NS(x=10,y=20));g.double(NS(x=10,y=20));g.release(NS(x=10,y=20))
        menu.assert_called_once();single.assert_not_called()
        g.press(NS(x=10,y=20));g.motion(NS(x=-70,y=25));g.release(NS(x=-70,y=25))
        reply.assert_called_once_with(42);animate.assert_any_call(42,-80,False);animate.assert_any_call(42,0,True)
    def test_drag_or_account_switch_cancels_hold(self):
        scope=['one'];w,g,menu,single,reply,animate=self.make(scope=lambda:scope[0])
        g.press(NS(x=10,y=20));g.motion(NS(x=10,y=70));self.assertFalse(w.timers)
        g.release(NS(x=10,y=70));menu.assert_not_called();reply.assert_not_called()
        g.press(NS(x=10,y=20));scope[0]='two';g.hold();g.release(NS(x=10,y=20))
        menu.assert_not_called();single.assert_not_called()
    def test_checkboxes_are_hidden_until_select_and_hidden_again_on_cancel(self):
        from tg_ascii.interactions import DesktopInteractions
        class App(DesktopInteractions):pass
        app=App();app.ui_account='a';app.active=42;app.selection_kind=None;app.selection_scope=None
        app.selected_chats=set();app.selected_messages=set();app.refresh_selection=Mock();app.render_chats=Mock();app.render_messages=Mock()
        self.assertEqual(app.chat_selection_prefix(7),'')
        self.assertFalse(app.message_selected(9))
        app.toggle_chat_selection(7)
        self.assertEqual(app.chat_selection_prefix(7),'☑ ');self.assertEqual(app.chat_selection_prefix(8),'☐ ')
        app.clear_selection();self.assertEqual(app.chat_selection_prefix(7),'')
        app.toggle_message_selection(NS(id=9));self.assertTrue(app.message_selected(9));self.assertFalse(app.message_selected(8))
        app.clear_selection();self.assertFalse(app.message_selected(9))

    def test_selection_clears_on_account_or_peer_change(self):
        from tg_ascii.interactions import DesktopInteractions
        app=NS(ui_account='b',active=9,selection_kind='messages',selection_scope=('a',9),selected_chats=set(),selected_messages={1,2})
        self.assertFalse(DesktopInteractions.selection_valid(app));self.assertFalse(app.selected_messages)


class BulkPermissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client=AsyncMock();self.client.add_event_handler=Mock();self.backend=TelegramBackend(self.client)
        self.backend.checked_message=AsyncMock(side_effect=lambda peer,ident:t.Message(ident,peer_id=t.PeerUser(peer),message='hello',out=True))
        async def selected(peer,*,ids):
            return [await self.backend.checked_message(peer,ident) for ident in ids]
        self.client.get_messages.side_effect=selected
        self.client.get_entity.return_value=t.User(42)
    async def test_forward_deduplicates_and_keeps_original_peer(self):
        await self.backend.forward_selected_messages(42,[3,3,7],99)
        self.client.forward_messages.assert_awaited_once_with(99,[3,7],from_peer=42)
    async def test_protected_messages_are_not_copied_or_forwarded_by_selection(self):
        self.backend.checked_message.return_value=None
        self.backend.checked_message.side_effect=lambda peer,ident:t.Message(ident,peer_id=t.PeerUser(peer),message='secret',noforwards=True)
        policy=await self.backend.selected_message_policy(42,[3])
        self.assertFalse(policy['copy']);self.assertFalse(policy['forward'])
        with self.assertRaises(ValueError):await self.backend.forward_selected_messages(42,[3],99)
        self.client.forward_messages.assert_not_called()
    async def test_channel_delete_for_me_never_becomes_delete_for_everyone(self):
        self.client.get_entity.return_value=t.Channel(7,'Channel',t.ChatPhotoEmpty(),None,megagroup=True)
        with self.assertRaises(ValueError):await self.backend.delete_selected_messages(42,[3],False)
        self.client.delete_messages.assert_not_called()
    async def test_one_unavailable_message_prevents_whole_bulk_mutation(self):
        async def checked(peer,ident):
            if ident==7:raise ValueError('Unavailable')
            return t.Message(ident,peer_id=t.PeerUser(peer),message='text',out=True)
        self.backend.checked_message.side_effect=checked
        with self.assertRaises(ValueError):await self.backend.delete_selected_messages(42,[3,7],True)
        self.client.delete_messages.assert_not_called()
