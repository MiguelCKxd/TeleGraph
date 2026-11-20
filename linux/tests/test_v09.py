"""Regression checks for hover scrolling, menus, reactions and destructive scopes."""
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,AsyncMock,patch
import importlib.util
import tempfile
import unittest
from telethon import types as t,functions as f
from tg_ascii.backend import TelegramBackend
from tg_ascii.messaging_features import reaction_allowed
from tg_ascii.image_tools import wheel_zoom_factor,zoom_at
from tg_ascii.scrolling import WheelRouter,Viewport


class ReactionAndHistoryTests(unittest.IsolatedAsyncioTestCase):
    def backend(self):
        client=AsyncMock();client.add_event_handler=Mock()
        client.get_input_entity.return_value=t.InputPeerUser(42,123)
        client.get_me.return_value=t.User(10,premium=True)
        backend=TelegramBackend(client);backend.message=lambda m:m
        return backend,client

    async def test_custom_reaction_uses_native_id_and_replaces_oldest_at_limit(self):
        backend,client=self.backend()
        backend.checked_message=AsyncMock(return_value=NS(reactions=NS(results=[
            t.ReactionCount(t.ReactionEmoji('👍'),5,chosen_order=2),
            t.ReactionCount(t.ReactionCustomEmoji(99),1,chosen_order=0)])))
        backend.reaction_policy=AsyncMock(return_value={'maximum':2,'allowed':None,'custom':True,'premium':True,'existing':set()})
        await backend.react(42,77,12345678901234)
        request=client.call_args.args[0]
        self.assertEqual(request.msg_id,77)
        self.assertEqual([r.to_dict() for r in request.reaction], [t.ReactionEmoji('👍').to_dict(),t.ReactionCustomEmoji(12345678901234).to_dict()])

    async def test_custom_reaction_restrictions_and_existing_toggle(self):
        backend,client=self.backend()
        backend.checked_message=AsyncMock(return_value=NS(reactions=NS(results=[t.ReactionCount(t.ReactionCustomEmoji(99),1,chosen_order=0)])))
        backend.reaction_policy=AsyncMock(return_value={'maximum':1,'allowed':set(),'custom':False,'premium':False,'existing':{99}})
        with self.assertRaises(ValueError): await backend.react(42,7,101)
        client.assert_not_awaited()
        await backend.react(42,7,99)
        self.assertEqual(client.call_args.args[0].reaction,[])

    async def test_policy_reads_server_limits_and_chat_whitelist(self):
        backend,client=self.backend()
        client.get_input_entity.return_value=t.InputPeerChannel(55,123)
        async def rpc(request):
            if isinstance(request,f.help.GetAppConfigRequest):
                return NS(config=t.JsonObject([t.JsonObjectValue('reactions_user_max_premium',t.JsonNumber(4))]))
            return NS(full_chat=NS(available_reactions=t.ChatReactionsSome([t.ReactionCustomEmoji(99)])))
        client.side_effect=rpc
        policy=await backend.reaction_policy(-1000000000055)
        self.assertEqual(policy['maximum'],4)
        self.assertTrue(reaction_allowed(99,policy));self.assertFalse(reaction_allowed(101,policy))

    async def test_image_thumbnail_skips_video_thumbnail(self):
        backend,client=self.backend()
        image=t.PhotoSize('m',100,100,2048)
        document=t.Document(99,123,b'',datetime.now(timezone.utc),'application/x-tgsticker',2048,2,[],thumbs=[image,t.PhotoPathSize('j',b'path')],video_thumbs=[t.VideoSize('v',100,100,4096)])
        with tempfile.TemporaryDirectory() as folder:
            client.download_media.return_value=str(Path(folder)/'preview.webp')
            await backend.download_media(document,Path(folder)/'preview',thumbnail=True)
        self.assertEqual(client.download_media.call_args.kwargs['thumb'],image.type)

    async def test_private_delete_scope(self):
        backend,client=self.backend();client.get_entity.return_value=t.User(42)
        await backend.delete_chat(42,False)
        client.delete_dialog.assert_awaited_with(42,revoke=False)
        await backend.delete_chat(42,True)
        self.assertTrue(client.delete_dialog.call_args.kwargs['revoke'])

    async def test_group_delete_all_requires_owner_and_never_leaves_instead(self):
        backend,client=self.backend()
        entity=t.Chat(55,'Group',t.ChatPhotoEmpty(),2,datetime.now(timezone.utc),1,creator=False)
        client.get_entity.return_value=entity
        with self.assertRaises(ValueError): await backend.delete_chat(-55,True)
        client.delete_dialog.assert_not_awaited();client.assert_not_awaited()
        entity.creator=True
        await backend.delete_chat(-55,True)
        self.assertIsInstance(client.call_args.args[0],f.messages.DeleteChatRequest)
        self.assertEqual(client.call_args.args[0].chat_id,55)

    async def test_clear_keeps_chat_and_uses_fixed_boundary_across_batches(self):
        backend,client=self.backend();client.get_entity.return_value=t.User(42)
        client.get_messages.return_value=[NS(id=70)]
        client.side_effect=[NS(offset=1),NS(offset=0)]
        self.assertEqual(await backend.clear_chat(42,True),70)
        for call in client.call_args_list:
            self.assertTrue(call.args[0].revoke);self.assertTrue(call.args[0].just_clear)
            self.assertEqual(call.args[0].max_id,70)
        client.delete_dialog.assert_not_awaited()

    async def test_supergroup_clear_self_does_not_delete_or_leave_group(self):
        backend,client=self.backend()
        entity=t.Channel(55,'Group',t.ChatPhotoEmpty(),datetime.now(timezone.utc),megagroup=True)
        client.get_entity.return_value=entity;client.get_messages.return_value=[NS(id=22)]
        await backend.clear_chat(-1000000000055,False)
        request=client.call_args.args[0]
        self.assertIsInstance(request,f.channels.DeleteHistoryRequest)
        self.assertFalse(request.for_everyone);self.assertEqual(request.max_id,22)
        client.delete_dialog.assert_not_awaited()
        client.reset_mock()
        with self.assertRaises(ValueError): await backend.clear_chat(-1000000000055,True)
        client.assert_not_awaited()

    async def test_silent_send_preserves_reply_and_formatting(self):
        backend,client=self.backend()
        await backend.send_formatted(42,'Hello',[(0,5,'bold','')],reply_to=8,silent=True)
        kw=client.send_message.call_args.kwargs
        self.assertTrue(kw['silent']);self.assertEqual(kw['reply_to'],8)
        self.assertIsInstance(kw['formatting_entities'][0],t.MessageEntityBold)


class InteractionTests(unittest.TestCase):
    def view(self):
        return NS(winfo_class=lambda:'Text',yview=lambda:(0,.5),yview_scroll=Mock(),master=None)
    def test_hover_routes_to_unfocused_view(self):
        focused,hovered=self.view(),self.view()
        root=NS(winfo_containing=lambda x,y:hovered)
        event=NS(widget=focused,x_root=8,y_root=9,state=0,delta=-120)
        router=object.__new__(WheelRouter);router.root=root;router.remainders={}
        with patch('tg_ascii.scrolling.sys.platform','win32'): router.wheel(event)
        focused.yview_scroll.assert_not_called();hovered.yview_scroll.assert_called_once_with(3,'units')
    def test_small_trackpad_deltas_accumulate_per_view(self):
        view=self.view();router=object.__new__(WheelRouter);router.remainders={}
        event=NS(state=0)
        for _ in range(4): router.route(view,event,.25)
        view.yview_scroll.assert_called_once_with(1,'units')
    def test_scrollbar_uses_its_command_without_focus(self):
        tk=NS(splitlist=lambda value:(value,),call=Mock())
        bar=NS(winfo_class=lambda:'TScrollbar',cget=lambda key:'view_command',tk=tk)
        router=object.__new__(WheelRouter);router.remainders={}
        router.route(bar,NS(state=0),2)
        tk.call.assert_called_once_with('view_command','scroll',2,'units')
    def test_chat_viewport_does_not_grow_to_requested_toolbar_height(self):
        canvas=NS(itemconfigure=Mock(),winfo_height=lambda:600,configure=Mock(),bbox=lambda _: (0,0,800,600))
        viewport=NS(canvas=canvas,item=1,minimum=(440,420),fit_to_window=True,content=NS(winfo_reqheight=lambda:1800),watch_request=Mock())
        Viewport.fit_content(viewport)
        # 1.4.1: a fitted layout may grow to stay reachable, but is capped.
        from tg_ascii.scrolling import FIT_LIMIT
        canvas.itemconfigure.assert_called_once_with(1,height=FIT_LIMIT)
    def test_zoom_is_continuous_anchored_and_zero_is_noop(self):
        self.assertEqual(wheel_zoom_factor(NS(delta=0),'darwin'),1)
        self.assertLess(wheel_zoom_factor(NS(delta=1),'darwin'),wheel_zoom_factor(NS(delta=8),'darwin'))
        scale,pan=zoom_at(1,[0,0],2,(600,400),(800,600))
        self.assertEqual((scale,pan),(2,[-200,-100]))
        scale,pan=zoom_at(12,[5,7],2,(600,400),(800,600))
        self.assertEqual((scale,pan),(12,[5,7]))
    def test_menu_event_is_consumed_before_opening_ui(self):
        from tg_ascii.app_dialogs import event_action
        pending=[]; callback=Mock()
        widget=NS(after_idle=lambda fn:pending.append(fn))
        self.assertEqual(event_action(widget,callback),'break')
        callback.assert_not_called()
        pending.pop()();callback.assert_called_once()


class LaunchTests(unittest.TestCase):
    def test_mac_launches_persistent_bundle_not_temporary_build(self):
        spec=importlib.util.spec_from_file_location('release09',Path(__file__).parents[1]/'tools/build_release.py')
        release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
        with tempfile.TemporaryDirectory() as directory:
            archive=Path(directory)/'release.zip';app=archive.with_suffix('')/'TG-ASCII.app';app.mkdir(parents=True)
            with patch.object(release.subprocess,'run') as run:
                self.assertEqual(release.launch_built_app(archive,'darwin'),app.resolve())
                run.assert_called_once_with(['/usr/bin/open',str(app.resolve())],check=True)
            with patch.object(release.subprocess,'run') as run:
                with self.assertRaises(FileNotFoundError):release.launch_built_app(Path(directory)/'missing.zip','darwin')
                run.assert_not_called()


class PhotoEditorTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('PIL'), 'Pillow is installed by requirements-build.txt')
    def test_draw_marker_text_scale_and_source_preservation(self):
        from PIL import Image,ImageChops
        from tg_ascii.image_tools import render_annotations,preview_point
        source=Image.new('RGB',(400,300),'white');before=source.tobytes()
        layers=[{'kind':'stroke','points':[(.1,.2),(.9,.2)],'width':.02,'color':'#ff0000'},
                {'kind':'stroke','points':[(.1,.5),(.9,.5)],'width':.05,'color':'#0000ff','opacity':.35},
                {'kind':'text','text':'Tg-As','x':.2,'y':.7,'size':.1,'color':'#00aa44'}]
        edited=render_annotations(source,layers)
        self.assertEqual(source.tobytes(),before)
        self.assertEqual(edited.getpixel((200,60)),(255,0,0))
        blue=edited.getpixel((200,150));self.assertGreater(blue[0],100);self.assertEqual(blue[2],255)
        self.assertIsNotNone(ImageChops.difference(source.crop((0,200,400,300)),edited.crop((0,200,400,300))).getbbox())
        self.assertEqual(render_annotations(source,[]).tobytes(),before)
        self.assertEqual(preview_point(150,100,(50,25,200,150)),(.5,.5))
        self.assertIsNone(preview_point(0,0,(50,25,200,150)))


class SchedulingTests(unittest.IsolatedAsyncioTestCase):
    async def test_scheduled_send_uses_server_schedule_and_preserves_entities(self):
        client=AsyncMock();client.add_event_handler=Mock();backend=TelegramBackend(client);backend.message=lambda m:m
        future=datetime(2030,1,1,tzinfo=timezone.utc)
        await backend.send_formatted(42,'Hello',[(0,5,'bold','')],schedule=future)
        client.send_message.assert_awaited_once()
        self.assertEqual(client.send_message.call_args.kwargs['schedule'],future)
        self.assertIsInstance(client.send_message.call_args.kwargs['formatting_entities'][0],t.MessageEntityBold)
    async def test_missing_scheduled_message_does_not_send_or_delete_another(self):
        client=AsyncMock();client.add_event_handler=Mock();backend=TelegramBackend(client)
        backend.scheduled_history=AsyncMock(return_value=[NS(id=22)])
        with self.assertRaises(ValueError):await backend.change_scheduled(42,99,True)
        client.assert_not_awaited()
        client.get_input_entity.return_value=t.InputPeerUser(42,123)
        await backend.change_scheduled(42,22,True)
        self.assertIsInstance(client.call_args.args[0],f.messages.SendScheduledMessagesRequest)
        self.assertEqual(client.call_args.args[0].id,[22])
        await backend.change_scheduled(42,22,False)
        self.assertIsInstance(client.call_args.args[0],f.messages.DeleteScheduledMessagesRequest)
    def test_schedule_rejects_past_and_malformed_values(self):
        from tg_ascii.messaging_features import parse_schedule
        for value in ('not a date','2000-01-01 10:00'):
            with self.assertRaises(ValueError):parse_schedule(value)
        self.assertIsNotNone(parse_schedule('2030-01-01 10:00').tzinfo)


class HistoryActionUITests(unittest.TestCase):
    def test_scope_confirmation_and_cancel_never_fall_back_to_another_action(self):
        from tg_ascii.desktop_modern import DesktopModern
        for clear in (False,True):
            backend=NS(history_permissions=Mock(return_value='read-only permissions'),clear_chat=Mock(return_value='clear operation'),delete_chat=Mock(return_value='delete operation'))
            app=NS(busy=False,demo=False,ui_account='account-a',service=NS(backend=backend),
                   chats=[NS(id=42,name='Original chat')],root=Mock(),call=Mock())
            entries=[]
            with patch('tg_ascii.app_dialogs.popup_menu',side_effect=lambda parent,items:entries.extend(items)),patch('tg_ascii.desktop_modern.messagebox.askyesno',return_value=False) as ask:
                DesktopModern.chat_history_action(app,42,clear)
                loaded=app.call.call_args.args[1]
                loaded({'person':True,'clear_self':True,'clear_all':True,'delete_all':True})
                entries[1][1]()
                backend.clear_chat.assert_not_called();backend.delete_chat.assert_not_called()
                ask.return_value=True
                entries[1][1]()
                (backend.clear_chat if clear else backend.delete_chat).assert_called_once_with(42,True)
                (backend.delete_chat if clear else backend.clear_chat).assert_not_called()
                app.ui_account='account-b';entries[0][1]()
                self.assertEqual(backend.clear_chat.call_count+backend.delete_chat.call_count,1)
