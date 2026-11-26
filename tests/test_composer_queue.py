import asyncio
import io
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock,patch
from PIL import Image
from telethon import types
from tg_ascii.backend import Chat
from tg_ascii.composer import Composer,custom_spans,decoded_runs
from tg_ascii.message_tools import formatted_entities
from tg_ascii.translation_queue import schedule,request
from tg_ascii.appearance import replace_elements,corner_masks,configure_shapes
from tg_ascii.preferences import DEFAULTS
from tg_ascii.themes import DARK


class ComposerTests(unittest.TestCase):
    def setUp(self):
        self.records={'one':{'document':123,'alt':'❤️'},'two':{'document':456,'alt':'👨‍💻'}}
        self.events=[('text','Hi 😀 ','1.0'),('image','one','1.6'),('text',' + ','1.7'),('image','two','1.10'),('text','!','1.11')]

    def test_visible_images_serialize_original_alts_and_utf16_entities(self):
        text=''.join(value for _,value,_ in decoded_runs(self.events,self.records))
        self.assertEqual(text,'Hi 😀 ❤️ + 👨‍💻!')
        spans=custom_spans(self.events,self.records)
        self.assertEqual(spans,[(5,7,123,'❤️'),(10,13,456,'👨‍💻')])
        entities=formatted_entities(text,[(0,len(text),'bold','')],spans)
        emojis=[e for e in entities if hasattr(e,'document_id')]
        self.assertEqual([(e.offset,e.length,e.document_id) for e in emojis],[(6,2,123),(11,5,456)])

    def test_deleted_image_never_leaves_invisible_emoji_in_payload(self):
        remaining=[e for e in self.events if e[1]!='one']
        text=''.join(value for _,value,_ in decoded_runs(remaining,self.records))
        self.assertEqual(text,'Hi 😀  + 👨‍💻!')
        self.assertEqual(custom_spans(remaining,self.records),[(8,11,456,'👨‍💻')])

    def test_image_offsets_are_atomic_and_subsequent_text_uses_real_tk_positions(self):
        editor=NS(events=lambda:self.events,emoji_records=self.records,
                  tk=NS(call=lambda *a:len(a[-1].encode('utf-16-le'))//2),index=lambda value:value)
        self.assertEqual(Composer.logical_index(editor,5),'1.6')
        self.assertEqual(Composer.logical_index(editor,6),'1.6')
        self.assertEqual(Composer.logical_index(editor,7),'1.7 + 0 indices')
        self.assertEqual(Composer.logical_index(editor,10),'1.10')
        self.assertEqual(Composer.logical_index(editor,13),'1.11 + 0 indices')

    def test_selected_image_copy_keeps_custom_identity_for_internal_paste(self):
        root=NS();editor=NS(tag_ranges=lambda _:('1.6','1.7'),events=lambda *a:[self.events[1]],
                           emoji_records=self.records,clipboard_clear=Mock(),clipboard_append=Mock(),_root=lambda:root)
        self.assertEqual(Composer.copy(editor),'break')
        editor.clipboard_append.assert_called_once_with('❤️')
        self.assertEqual(root._composer_clipboard,('❤️',[(0,2,123,'❤️')]))

    def test_restore_replaces_from_end_and_never_replaces_mismatched_text(self):
        text='A❤️B👨‍💻C';calls=[]
        editor=NS(get=lambda *a:text,logical_index=lambda value:value,delete=lambda a,b:calls.append(('delete',a,b)),
                  insert_custom=lambda doc,alt,index:calls.append(('emoji',doc,alt,index)))
        Composer.restore_custom(editor,[(1,3,123,'❤️'),(4,7,456,'👨‍💻'),(0,1,789,'X')])
        self.assertEqual(calls,[('delete',4,7),('emoji',456,'👨‍💻',4),('delete',1,3),('emoji',123,'❤️',1)])

    def test_custom_emoji_loading_delegates_to_parent_window_without_attribute_error(self):
        parent_app = NS(request_photo=Mock(), emoji_tint=Mock(return_value=None))
        sub_window = NS(ui_account='a', demo=False, emoji_art=Mock(), service=NS(backend=Mock()), app=parent_app)
        loaded_cb = None
        def fake_emoji_art(doc, acc, backend, cb, valid=None):
            nonlocal loaded_cb
            loaded_cb = cb
        sub_window.emoji_art.side_effect = fake_emoji_art

        editor = NS(
            app=sub_window, emoji_records={}, serial=0,
            prune=Mock(), winfo_exists=lambda: True, cget=lambda key: 'TkTextFont' if key=='font' else '#ffffff',
            winfo_rgb=lambda color: (65535, 65535, 65535), image_create=lambda *a, **k: 'img1',
            event_generate=Mock(), image_configure=Mock()
        )
        with patch('tkinter.font.Font') as mock_font, patch('tkinter.PhotoImage'):
            mock_font.return_value.metrics.return_value = 20
            Composer.insert_custom(editor, 999, '⭐')
            self.assertIsNotNone(loaded_cb)
            # Trigger loaded callback: should resolve requester from sub_window.app without raising AttributeError!
            loaded_cb('/path/to/art.png')
            parent_app.request_photo.assert_called_once()


class QueueTests(unittest.IsolatedAsyncioTestCase):
    def app(self,count=50):
        app=NS(ui_account='a',active=5,demo=False,chat_translations={'a:5':'es'}, preferences=NS(values={'advanced_features': {'chat_translation': True}}),
               messages=[NS(id=i,text='Hello '+str(i),raw_text=None) for i in range(count)],
               translated={},translation_pending=set(),translation_failed=set(),
               service=NS(entries={'a':{'premium':True}},backend=Mock()),chats=[Chat(5,'Synthetic',entity=types.User(5))],worker=Mock(),root=Mock(),status=Mock(),render_messages=Mock(),busy=False)
        app.schedule_translations=lambda:schedule(app)
        return app

    def take(self,app):
        coroutine,done,failed=app.worker.submit.call_args.args;coroutine.close();return done,failed

    def test_one_small_batch_does_not_lock_ui_or_overlap(self):
        app=self.app();schedule(app);self.assertEqual(len(app.translation_pending),20)
        self.assertFalse(app.busy);schedule(app);app.worker.submit.assert_called_once()
        done,_=self.take(app);done({key[2]:NS(text='hola') for key in app.translation_pending})
        self.assertFalse(app.translation_pending);self.assertEqual(len(app.translated),20)
        schedule(app);app.worker.submit.assert_called_once();app.root.after.assert_called_once()

    def test_switch_or_disable_cancels_job_and_discards_old_callback(self):
        app=self.app();schedule(app);job=app._translation_job;done,_=self.take(app)
        app.chat_translations.clear();schedule(app)
        job.cancel.assert_called_once();done({49:NS(text='late')})
        self.assertFalse(app.translated);self.assertFalse(app.translation_pending)
        self.assertIsNone(app._translation_job);self.assertFalse(app.busy)

    def test_error_only_pauses_translations_and_settings_retry_without_restart(self):
        app=self.app();schedule(app);_,failed=self.take(app)
        failed(TimeoutError());self.assertFalse(app.translation_pending);self.assertFalse(app.busy)
        schedule(app);app.worker.submit.assert_called_once()
        app._translation_scope=None;app.translation_failed.clear();schedule(app)
        self.assertEqual(app.worker.submit.call_count,2);self.take(app)

    def test_missing_results_do_not_create_render_retry_loop(self):
        app=self.app(1);schedule(app);done,_=self.take(app);done({})
        app._translation_after=0;schedule(app)
        app.worker.submit.assert_called_once();self.assertEqual(len(app.translation_failed),1)

    async def test_hanging_translation_times_out_without_blocking_other_coroutines(self):
        cancelled=[]
        async def hang(*a,**kw):
            try:await asyncio.Event().wait()
            finally:cancelled.append(True)
        backend=NS(translate_messages=hang)
        with patch('tg_ascii.translation_queue.REQUEST_TIMEOUT',.02):
            task=asyncio.create_task(request(backend,5,[1],'es'))
            marker=[]
            async def unrelated():marker.append('connected')
            await unrelated()
            with self.assertRaises(TimeoutError):await task
        self.assertEqual(marker,['connected']);self.assertEqual(cancelled,[True])


class ControlShapesTests(unittest.TestCase):
    def test_canvas_masks_follow_scroll_and_disable_without_changing_content(self):
        import tkinter as tk
        from tg_ascii.appearance import shape_widget
        root=NS(_shape_values={'menu_radius':12});canvas=Mock(spec=tk.Canvas)
        canvas._root.return_value=root;canvas.winfo_width.return_value=200;canvas.winfo_height.return_value=100
        canvas.winfo_exists.return_value=True;canvas.canvasx.return_value=0;canvas.canvasy.return_value=500
        canvas.cget.return_value='';canvas.bind.return_value='binding';callbacks={}
        canvas.configure.side_effect=lambda **kw:callbacks.update(kw)
        with patch('tg_ascii.appearance.ImageTk.PhotoImage',return_value=object()):
            shape_widget(canvas);canvas._canvas_corners.job.run()
            self.assertEqual(canvas.create_image.call_count,4)
            self.assertEqual(canvas.create_image.call_args_list[0].args,(0,500))
            canvas.canvasy.return_value=900;callbacks['yscrollcommand'](.4,.6);canvas._canvas_corners.job.run()
            self.assertEqual(canvas.coords.call_args_list[-4].args[1:],(0,900))
            self.assertEqual(canvas.create_image.call_count,4)
            canvas.create_image.reset_mock();root._shape_values={'menu_radius':0};shape_widget(canvas)
            callbacks['yscrollcommand'](.6,.8);canvas.create_image.assert_not_called()
            self.assertEqual(canvas._canvas_corners.radius,0)

    def test_layout_keeps_input_and_arrow_children_and_zero_restores_all(self):
        layout=[('Combobox.field',{'children':[('Combobox.downarrow',{'side':'right'}),('Combobox.textarea',{'sticky':'nswe'})]})]
        updated=replace_elements(layout,{'Combobox.field':'Rounded.field'})
        self.assertEqual(updated[0][1],layout[0][1]);self.assertEqual(layout[0][0],'Combobox.field')
        root=NS();style=Mock();style.layout.side_effect=lambda name,*args:layout if not args else None
        with patch('tg_ascii.appearance.ImageTk.PhotoImage',return_value=object()):
            configure_shapes(root,style,{**DEFAULTS,'menu_radius':14,'button_radius':12},DARK)
            configure_shapes(root,style,DEFAULTS,DARK)
        for name in ('TEntry','TCombobox','Treeview','Horizontal.TProgressbar','Vertical.TScrollbar','TNotebook.Tab'):
            self.assertIn(unittest.mock.call(name,layout),style.layout.call_args_list)
        self.assertEqual(root._shape_values['menu_radius'],0)

    def test_corner_masks_cover_only_outside_of_curve(self):
        masks=corner_masks(20,'#08100c');self.assertEqual(len(masks),4)
        self.assertEqual(masks[0].getpixel((0,0))[3],255)
        self.assertEqual(masks[0].getpixel((19,19))[3],0)


if __name__=='__main__':unittest.main()
