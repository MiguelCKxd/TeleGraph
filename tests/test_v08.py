import asyncio
from datetime import datetime,timezone
from types import SimpleNamespace as NS
from unittest.mock import Mock,AsyncMock,patch
import tempfile
import unittest
from telethon import types as t,functions as f
from tg_ascii.backend import TelegramBackend,Message
from tg_ascii.bubbles import BubbleView,rich_runs
from tg_ascii.desktop_modern import DesktopModern
from tg_ascii.preferences import Preferences


class ServerFeatures(unittest.IsolatedAsyncioTestCase):
    def backend(self):
        client=AsyncMock(); client.add_event_handler=Mock()
        client.get_input_entity.return_value=t.InputPeerUser(42,123)
        backend=TelegramBackend(client); backend.message=lambda m:m
        backend.checked_message=AsyncMock(return_value=NS(reactions=None))
        return backend,client

    async def test_reaction_toggles_only_selected_and_keeps_others(self):
        backend,client=self.backend()
        backend.checked_message.return_value=NS(reactions=NS(results=[t.ReactionCount(t.ReactionEmoji('👍'),3,chosen_order=0),t.ReactionCount(t.ReactionCustomEmoji(99),1,chosen_order=1)]))
        await backend.react(42,7,'👍')
        request=client.call_args.args[0]
        self.assertIsInstance(request,f.messages.SendReactionRequest)
        self.assertEqual(request.msg_id,7)
        self.assertEqual(request.peer.user_id,42)
        self.assertEqual([r.document_id for r in request.reaction],[99])
        backend.reaction_policy=AsyncMock(return_value={'maximum':3,'premium':True,'custom':True,'allowed':None,'existing':set()})
        await backend.react(42,7,101)
        self.assertEqual(len(client.call_args.args[0].reaction),3)

    async def test_reaction_requires_original_peer(self):
        backend,client=self.backend(); backend.checked_message.side_effect=ValueError('wrong peer')
        with self.assertRaises(ValueError): await backend.react(99,7,'👍')
        client.assert_not_awaited()

    async def test_wallpaper_scope_and_remove(self):
        backend,client=self.backend()
        client.upload_file.return_value='upload'
        client.return_value=NS(id=4,access_hash=5)
        await backend.apply_wallpaper(42,'edited.jpg',False)
        self.assertFalse(client.call_args.args[0].for_both)
        await backend.apply_wallpaper(42,'edited.jpg',True)
        self.assertTrue(client.call_args.args[0].for_both)
        await backend.apply_wallpaper(42,None,False)
        self.assertIsNone(client.call_args.args[0].wallpaper)
        self.assertFalse(client.call_args.args[0].revert or False)
        client.get_input_entity.return_value=t.InputPeerChannel(5,6)
        with self.assertRaises(ValueError): await backend.apply_wallpaper(-1000000000005,'edited.jpg',True)

    async def test_privacy_keeps_unedited_exceptions_and_rejects_race(self):
        backend,client=self.backend()
        snapshot=NS(rules=[t.PrivacyValueDisallowChatParticipants([9]),t.PrivacyValueAllowUsers([42]),t.PrivacyValueAllowAll()])
        backend.privacy=AsyncMock(return_value=snapshot)
        await backend.save_privacy('Phone number','Contacts only',snapshot)
        request=client.call_args.args[0]
        self.assertIsInstance(request.rules[0],t.InputPrivacyValueDisallowChatParticipants)
        self.assertEqual(request.rules[0].chats,[9])
        self.assertEqual(request.rules[1].users[0].user_id,42)
        self.assertIsInstance(request.rules[-1],t.InputPrivacyValueAllowContacts)
        client.reset_mock()
        backend.privacy.return_value=NS(rules=[t.PrivacyValueDisallowAll()])
        with self.assertRaises(ValueError): await backend.save_privacy('Phone number','Everyone',snapshot)
        client.assert_not_awaited()

    async def test_global_privacy_merges_latest_untouched_fields(self):
        backend,client=self.backend()
        current=t.GlobalPrivacySettings(keep_archived_unmuted=True,hide_read_marks=False)
        backend.global_privacy=AsyncMock(return_value=current)
        await backend.save_global_privacy({'hide_read_marks':True})
        settings=client.call_args.args[0].settings
        self.assertTrue(settings.keep_archived_unmuted)
        self.assertTrue(settings.hide_read_marks)

    async def test_pins_scope_and_presence_typing_protocol(self):
        backend,client=self.backend()
        await backend.pin_message(42,8,False,False)
        request=client.call_args.args[0]; self.assertTrue(request.pm_oneside); self.assertEqual(request.id,8)
        await backend.pin_message(42,8,True,True)
        self.assertTrue(client.call_args.args[0].unpin); self.assertFalse(client.call_args.args[0].pm_oneside)
        await backend.presence(True); self.assertFalse(client.call_args.args[0].offline)
        await backend.presence(False); self.assertTrue(client.call_args.args[0].offline)
        await backend.typing(42); self.assertIsInstance(client.call_args.args[0].action,t.SendMessageTypingAction)
        await backend.typing(42,False); self.assertIsInstance(client.call_args.args[0].action,t.SendMessageCancelAction)

    async def test_global_search_returns_peer_bound_results_and_cursor(self):
        backend,client=self.backend()
        message=t.Message(id=8,peer_id=t.PeerUser(42),message='result',date=datetime.now(timezone.utc),from_id=t.PeerUser(42))
        client.return_value=NS(users=[t.User(id=42,first_name='Ada')],chats=[],messages=[message],next_rate=15)
        found,cursor=await backend.global_messages('result')
        self.assertEqual(found[0][:2],(42,'Ada')); self.assertEqual(cursor[0],15); self.assertEqual(cursor[2],8)
        self.assertEqual(client.call_args.args[0].q,'result')
        client.send_read_acknowledge.assert_not_awaited()

    async def test_live_activity_and_reactions_events_are_peer_scoped(self):
        backend,client=self.backend(); backend.on_change=Mock()
        await backend.state_event(t.UpdateUserTyping(42,t.SendMessageTypingAction()))
        self.assertEqual(backend.on_change.call_args.args[0],'activity')
        self.assertEqual(backend.on_change.call_args.args[1][0],42)
        await backend.state_event(t.UpdateMessageReactions(t.PeerUser(42),7,t.MessageReactions([])))
        backend.on_change.assert_called_with('reaction',(42,7))

    async def test_bot_controls_are_not_offered_for_people(self):
        backend,client=self.backend(); client.get_entity.return_value=t.User(id=42,first_name='Ada')
        header=await backend.chat_header(42)
        self.assertEqual(header['commands'],[]); self.assertFalse(header['mini']); client.assert_not_awaited()

    async def test_quote_palette_and_icon_come_from_actual_sender(self):
        backend,client=self.backend(); backend.message=TelegramBackend.message.__get__(backend)
        message=t.Message(id=8,peer_id=t.PeerUser(42),message='hello',date=datetime.now(timezone.utc),from_id=t.PeerUser(42))
        message._sender=t.User(id=42,first_name='Ada',color=t.PeerColor(color=9,background_emoji_id=1234))
        converted=backend.message(message)
        self.assertEqual(converted.sender_color,9); self.assertEqual(converted.reply_icon_id,1234)
        self.assertEqual(converted.sender_id,42)


class InteractionTests(unittest.TestCase):
    def test_plain_and_hidden_links_and_custom_emoji(self):
        message=Message(1,'Ada','', '',raw_text='😀 link https://example.com',entities=(t.MessageEntityCustomEmoji(0,2,99),t.MessageEntityTextUrl(3,4,'https://telegram.org')))
        runs=list(rich_runs(message))
        self.assertEqual(runs[0],('◇',None,99))
        self.assertIn(('link','https://telegram.org',None),runs)
        self.assertTrue(any(url=='https://example.com' for _,url,_ in runs))
        self.assertNotIn('😀',''.join(text for text,_,_ in runs))
        from tg_ascii.links import detected_links
        self.assertEqual([u for _,_,u in detected_links('example.com test@example.com')],['https://example.com'])

    def test_reaction_preference_persists_custom_document(self):
        with tempfile.TemporaryDirectory() as directory:
            prefs=Preferences(directory); prefs.save({'quick_reaction':123456})
            self.assertEqual(Preferences(directory).values['quick_reaction'],123456)
            self.assertFalse(prefs.values['bubbles'])

    def test_chat_preview_never_selects_or_acknowledges(self):
        backend=NS(history=AsyncMock(return_value=[]),mark_read=AsyncMock())
        app=NS(busy=False,demo=False,ui_account='one',active=99,service=NS(backend=backend),call=Mock())
        DesktopModern.preview_chat(app,42)
        coroutine=app.call.call_args.args[0]
        asyncio.run(coroutine)
        backend.history.assert_awaited_once_with(42)
        backend.mark_read.assert_not_called()
        self.assertEqual(app.active,99)

    def test_bubbles_use_content_width_square_corners_and_alignment(self):
        class FakeFont:
            def __init__(self,**kwargs): self.family=kwargs['family']
            def measure(self,text): return len(text)*7
            def metrics(self,key): return 17
            def cget(self,key): return 12
        class Canvas:
            def __init__(self): self.items={}; self.n=0; self.rectangles=[]; self.messages=[]; self.width=800; self.options={'bg':''};self._nodes={};self._job=None
            def create(self,kind,coords,options):
                self.n+=1; self.items[self.n]=(kind,coords,options); return self.n
            def create_rectangle(self,*coords,**options): self.rectangles.append(coords); return self.create('rect',coords,options)
            def create_text(self,*coords,**options): return self.create('text',coords,options)
            def create_image(self,*coords,**options): return self.create('image',coords,options)
            def configure(self,**options): self.options.update(options)
            def cget(self,key): return self.options[key]
            def yview(self): return (0,1)
            def yview_moveto(self,value): pass
            def winfo_width(self): return self.width
            def winfo_height(self): return 500
            def delete(self,item):
                if item=='all': self.items.clear()
                else: self.items.pop(item,None)
            def tag_lower(self,item): pass
            def bbox(self,item):
                _,(x,y),options=self.items[item]; return (x,y,x+len(options.get('text',''))*7,y+20)
            def addtag_withtag(self,*args): pass
            def tag_bind(self,*args): pass
            rounded=BubbleView.rounded
            interactive=BubbleView.interactive
        canvas=Canvas(); canvas.generation=0
        app=NS(text_display=lambda value,one_line=False:' '.join(value.split()) if one_line else value,font_family='Menlo',preferences=NS(values={'theme':'dark','font_family':'','font_size':12,'inline_media':True}),ui_account='one',active=42,reply_cache={},message_accent=lambda m:['#ffaaaa'],draw_bubble_wallpaper=Mock(),canvas_emoji=Mock())
        canvas.app=app
        messages=[Message(1,'Ada','Hi','12:00',raw_text='Hi'),Message(2,'You','This is a longer message','12:01',True,raw_text='This is a longer message',reply_to_id=1)]
        with patch('tg_ascii.bubbles.font.Font',FakeFont): BubbleView.render(canvas,messages)
        rects=[data[1] for data in canvas.items.values() if data[0]=='rect']
        self.assertTrue(any(x==16 for x,y,r,b in rects))
        incoming=next(coords for coords in rects if coords[0]==16)
        self.assertLess(incoming[2]-incoming[0],200)
        outgoing=max((r for r in rects if r[2]-r[0]>80),key=lambda coords:coords[0])
        self.assertEqual(outgoing[2],784)
        self.assertLess(outgoing[2]-outgoing[0],800*.8)
        self.assertEqual(len(canvas.locations),2)
        self.assertTrue(all(value.family == 'Menlo' for value in canvas._text_fonts))
        self.assertTrue(all('font' in options for kind,coords,options in canvas.items.values() if kind == 'text'))


if __name__=='__main__': unittest.main()
