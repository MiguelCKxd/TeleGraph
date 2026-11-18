import unittest,tempfile
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,Mock,patch
from tg_ascii.preferences import Preferences,DEFAULTS
from tg_ascii.appearance import app_palette,rounded_points,configure_shapes
from tg_ascii.themes import DARK,LIGHT
from tg_ascii.attachments import merge_paths,paths_in
from tg_ascii.backend import TelegramBackend,DemoBackend
from tg_ascii.desktop import Desktop
from tg_ascii.scrolling import flow_positions


class AppearanceTests(unittest.TestCase):
    def test_existing_settings_keep_exact_original_palette_and_square_corners(self):
        values=Preferences.validated({'theme':'dark'})
        self.assertEqual(app_palette(values),DARK)
        self.assertEqual(app_palette({**values,'theme':'light'}),LIGHT)
        self.assertTrue(all(values[k]==0 for k in ('button_radius','menu_radius','bubble_radius')))
        self.assertFalse(values['bubbles'])

    def test_custom_colours_are_independent_persistent_and_resettable(self):
        with tempfile.TemporaryDirectory() as folder:
            prefs=Preferences(folder);prefs.save({'text_color':'#Ab1200','button_radius':12})
            self.assertEqual(app_palette(prefs.values)['bg'],DARK['bg'])
            prefs.save({'background_color':'#112233'})
            loaded=Preferences(folder);palette=app_palette(loaded.values)
            self.assertEqual((palette['text'],palette['bg']),('#ab1200','#112233'))
            self.assertEqual(loaded.values['button_radius'],12)
            loaded.save({'text_color':'','background_color':''})
            self.assertEqual(app_palette(loaded.values),DARK)
            self.assertEqual(loaded.values['logo_theme'],'dark')

    def test_invalid_customization_does_not_reach_tk(self):
        values=Preferences.validated({'text_color':'red;evil','background_color':'#xyz123','button_radius':100,'menu_radius':True,'bubble_radius':-1})
        for key in ('text_color','background_color','button_radius','menu_radius','bubble_radius'):self.assertEqual(values[key],DEFAULTS[key])

    def test_rounding_is_bounded_for_small_bubbles(self):
        self.assertEqual(rounded_points(10,20,80,30,0),[10,20,90,20,90,50,10,50])
        points=rounded_points(10,20,80,30,24)
        self.assertTrue(all(10<=x<=90 for x in points[::2]));self.assertTrue(all(20<=y<=50 for y in points[1::2]))

    def test_default_button_layout_is_restored_after_customization(self):
        root=NS();style=Mock();original=[('Button.border',{})]
        style.layout.side_effect=lambda name,*args:original if not args else None
        with patch('tg_ascii.appearance.ImageTk.PhotoImage',side_effect=lambda *a,**k:object()):
            configure_shapes(root,style,{**DEFAULTS,'button_radius':12},DARK)
            configure_shapes(root,style,DEFAULTS,DARK)
        self.assertIn(unittest.mock.call('TButton',original),style.layout.call_args_list)
        self.assertFalse(any(call.args and str(call.args[0]) in ('Menu','TMenu') for call in style.layout.call_args_list))

    def test_toolbars_wrap_without_colliding_at_multiple_widths(self):
        sizes=[(180,28),(140,32),(90,28),(170,44),(240,28)]
        for width in (220,440,900):
            boxes,height=flow_positions(sizes,width)
            for i,(x,y,w,h) in enumerate(boxes):
                self.assertGreaterEqual(x,0);self.assertLessEqual(x+w,width);self.assertLessEqual(y+h,height)
                for xx,yy,ww,hh in boxes[i+1:]:self.assertTrue(x+w<=xx or xx+ww<=x or y+h<=yy or yy+hh<=y)


class MultipleAttachmentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.paths=[]
        for name in ('one.jpg','two.jpg','notes.txt'):
            path=Path(self.folder.name)/name;path.write_bytes(b'data');self.paths.append(path)
        self.client=AsyncMock();self.client.add_event_handler=Mock();self.backend=TelegramBackend(self.client)
        self.backend.message=lambda value:value

    async def test_one_album_keeps_order_caption_entities_reply_and_send_options(self):
        seen={}
        async def send(peer,streams,**kwargs):
            seen.update(peer=peer,streams=streams,kwargs=kwargs,names=[Path(stream.name).name for stream in streams])
            self.assertTrue(all(not stream.closed for stream in streams));return ['first','second']
        self.client.send_file.side_effect=send
        result=await self.backend.send_batch(42,self.paths[:2],'Hi',[(0,2,'bold','')],reply_to=8,silent=True,schedule=123)
        self.assertEqual(result,['first','second']);self.assertEqual(seen['names'],['one.jpg','two.jpg'])
        self.assertTrue(all(stream.closed for stream in seen['streams']))
        kwargs=seen['kwargs'];self.assertEqual(kwargs['caption'],['Hi','']);self.assertEqual(kwargs['reply_to'],8)
        self.assertFalse(kwargs['force_document']);self.assertIsNone(kwargs['parse_mode']);self.assertEqual(len(kwargs['formatting_entities'][0]),1)
        self.assertEqual(kwargs['formatting_entities'][1],[]);self.assertTrue(kwargs['silent']);self.assertEqual(kwargs['schedule'],123)
        self.client.send_file.assert_awaited_once()

    async def test_mixed_files_are_documents_and_failure_is_not_retried(self):
        self.client.send_file.side_effect=ConnectionError('offline')
        with self.assertRaises(ConnectionError):await self.backend.send_batch(42,self.paths,'caption')
        self.assertTrue(self.client.send_file.call_args.kwargs['force_document'])
        self.client.send_file.assert_awaited_once()

    async def test_missing_source_or_too_many_files_sends_nothing(self):
        with self.assertRaises(OSError):await self.backend.send_batch(42,[self.paths[0],Path(self.folder.name)/'missing'])
        with self.assertRaises(ValueError):await self.backend.send_batch(42,[self.paths[0]]*11)
        self.client.send_file.assert_not_called()

    async def test_merge_is_immutable_deduplicated_and_rejects_overflow(self):
        before=(self.paths[0],);result=merge_paths(before,self.paths)
        self.assertEqual(paths_in(result),tuple(self.paths));self.assertEqual(before,(self.paths[0],))
        extra=[]
        for i in range(11):
            path=Path(self.folder.name)/str(i);path.touch();extra.append(path)
        with self.assertRaises(ValueError):merge_paths(before,extra)
        self.assertEqual(before,(self.paths[0],))

    async def test_drop_adds_files_without_sending_or_changing_other_account(self):
        ui=Desktop.__new__(Desktop);ui.active=42;ui.ui_account='a';ui.busy=False;ui.stage='ready';ui.attachment=None
        from tg_ascii.backend import Chat
        ui.demo=False;ui.chats=[Chat(42,'Synthetic recipient')]
        ui.attachment_manager=Mock();ui.update_attachment=Mock();ui.send=Mock();ui.show_error=Mock()
        ui.dropped_files(self.paths[:2]);self.assertEqual(paths_in(ui.attachment),tuple(self.paths[:2]));ui.send.assert_not_called()
        ui.attachment=None
        def preview(path,accepted):ui.ui_account='b';accepted(path)
        ui.preview_photo_attachment=preview;ui.prepare_attachments(self.paths[:1]);self.assertIsNone(ui.attachment)

    async def test_demo_batch_has_caption_only_once(self):
        backend=DemoBackend();messages=await backend.send_batch(1,self.paths[:2],'caption')
        self.assertEqual(len(messages),2);self.assertIn('caption',messages[0].text);self.assertNotIn('caption',messages[1].text)
