import asyncio
from collections import OrderedDict
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase,TestCase
from unittest.mock import Mock,AsyncMock,patch
from telethon import functions,types
from tg_ascii.ui_work import CanvasCorners
from tg_ascii.sticker_search import search,cached,matching_packs,matching_documents,PickerRequests
from tg_ascii.sticker_picker import StickerGrid


class Canvas:
    def __init__(self):
        self.jobs={};self.options={'yscrollcommand':'gallery','xscrollcommand':''};self.serial=0;self.items=set();self.y=0
        self.create_image=Mock(side_effect=self.create);self.coords=Mock();self.itemconfigure=Mock();self.tag_raise=Mock()
        self.tk=NS(call=Mock(),splitlist=lambda s:(s,))
    def create(self,*a,**k):
        self.serial+=1;self.items.add(self.serial)
        self.options['yscrollcommand']('0.0','0.5')
        return self.serial
    def cget(self,key):return self.options[key]
    def configure(self,**kw):self.options.update(kw)
    def delete(self,*tags):self.items.clear()
    def bind(self,*a,**kw):pass
    def _root(self):return self
    def winfo_exists(self):return True
    def winfo_width(self):return 300
    def winfo_height(self):return 200
    def canvasx(self,x):return x
    def canvasy(self,y):return y+self.y
    def after(self,delay,callback):
        ident=object();self.jobs[ident]=callback;return ident
    def after_cancel(self,ident):self.jobs.pop(ident,None)
    def flush(self):
        passes=0
        while self.jobs:
            passes+=1
            if passes>10:raise AssertionError('drawing did not settle')
            callbacks=list(self.jobs.values());self.jobs.clear()
            for callback in callbacks:callback()


class RenderingTests(TestCase):
    def test_rounding_feedback_settles_and_scroll_reuses_four_items(self):
        canvas=Canvas();manager=CanvasCorners(canvas)
        with patch('PIL.ImageTk.PhotoImage',side_effect=lambda *a,**k:object()):
            manager.configure(28,'#000000');canvas.flush()
            self.assertEqual(canvas.create_image.call_count,4)
            self.assertEqual(canvas.tk.call.call_count,1)
            for _ in range(100):canvas.options['yscrollcommand']('0.0','0.5')
            self.assertEqual(len(canvas.jobs),1);canvas.flush()
            self.assertEqual(canvas.create_image.call_count,4);canvas.coords.assert_not_called()
            canvas.y=600;canvas.options['yscrollcommand']('0.3','0.8');canvas.flush()
            self.assertEqual(canvas.coords.call_count,4);self.assertEqual(canvas.create_image.call_count,4)
            canvas.delete('all');canvas.flush();self.assertEqual(canvas.create_image.call_count,8)
            manager.configure(0,'#000000');canvas.flush();self.assertFalse(canvas.items)
            canvas.options['yscrollcommand']('0.4','0.9');self.assertFalse(canvas.jobs)

    def test_gallery_only_paints_visible_cells_that_changed(self):
        canvas=Mock();canvas.canvasy.side_effect=lambda y:y;canvas.winfo_height.return_value=200
        docs=[NS(id=i) for i in range(5000)]
        grid=NS(winfo_exists=lambda:True,winfo_viewable=lambda:True,canvas=canvas,columns=3,cell=100,documents=docs,
                photos=OrderedDict(),selected=None,_cells={},load=Mock())
        StickerGrid.paint(grid);self.assertEqual(canvas.create_rectangle.call_count,12)
        canvas.reset_mock()
        for _ in range(100):StickerGrid.paint(grid)
        canvas.create_rectangle.assert_not_called();canvas.delete.assert_not_called()
        grid.photos[0]=object();StickerGrid.paint(grid)
        self.assertEqual(canvas.create_rectangle.call_count,1);self.assertEqual(canvas.create_image.call_count,1)
        canvas.reset_mock();canvas.canvasy.side_effect=lambda y:y+200
        StickerGrid.paint(grid)
        self.assertEqual(canvas.create_rectangle.call_count,6);self.assertEqual(len(grid._cells),12)
        self.assertNotIn(('all',),[c.args for c in canvas.delete.call_args_list])

    def test_wallpaper_reuses_photo_and_only_moves_on_scroll(self):
        from tg_ascii.interface_background import reuse_canvas_background
        canvas=Mock();canvas._wallpaper_key=('x',);canvas.wallpaper=object();canvas._wallpaper_origin=(0,0)
        canvas.canvasx.return_value=0;canvas.canvasy.return_value=0;canvas.find_withtag.return_value=(1,)
        for _ in range(100):self.assertTrue(reuse_canvas_background(canvas,('x',)))
        canvas.create_image.assert_not_called();canvas.coords.assert_not_called()
        canvas.canvasy.return_value=50;reuse_canvas_background(canvas,('x',));canvas.coords.assert_called_once_with('wallpaper',0,50)
        self.assertFalse(reuse_canvas_background(canvas,('changed',)))
        canvas.find_withtag.return_value=();reuse_canvas_background(canvas,('x',));canvas.create_image.assert_called_once()

    def test_same_emoji_shares_one_photo_and_one_animation_clock(self):
        from tg_ascii.animation import AnimationPlayer
        from PIL import Image
        class Photo:
            def __init__(self,*a,**kw):pass
        frames=([Image.new('RGB',(20,20)),Image.new('RGB',(20,20))],[100,100])
        root=Mock();player=AnimationPlayer(root)
        with patch('PIL.ImageTk.PhotoImage',Photo):
            first=player.photo(__file__,(20,20),prepared=frames)
            for _ in range(100):self.assertIs(player.photo(__file__,(20,20)),first)
            self.assertEqual(len(player.entries),1);root.after.assert_called_once()
            self.assertIsNot(player.photo(__file__,(20,20),False),first)
        player.stop();self.assertFalse(player.photos)

    def test_long_text_wrap_uses_fewer_font_measurements_and_preserves_text(self):
        from tg_ascii.bubbles import layout_text_run
        measure=Mock(side_effect=len)
        chunks,x,y=layout_text_run('a'*1000,0,0,0,80,10,measure)
        self.assertEqual(''.join(chunk for _,_,chunk in chunks),'a'*1000)
        self.assertEqual((x,y),(40,120));self.assertLess(measure.call_count,180)
        chunks,x,y=layout_text_run('Hi\n\nWorld!',78,0,0,80,10,len)
        self.assertEqual(chunks,[(78,0,'Hi'),(0,20,'World!')]);self.assertEqual((x,y),(6,20))
        chunks,x,y=layout_text_run('abc',80,0,0,80,10,len)
        self.assertEqual(chunks,[(0,10,'abc')])

    def test_theme_os_read_is_cached(self):
        from tg_ascii.themes import system_theme
        with patch('tg_ascii.themes._read_system_theme',return_value='light') as read:
            self.assertEqual(system_theme(True),'light')
            for _ in range(100):self.assertEqual(system_theme(),'light')
            read.assert_called_once()
        with patch('tg_ascii.themes._read_system_theme',return_value='dark'):system_theme(True)

    def test_bubble_render_does_not_build_hidden_classic_history(self):
        from tg_ascii.desktop import Desktop
        app=NS(bubble_view=object(),preferences=NS(values={'bubbles':True}),history=Mock(),
               preview_generation=0,schedule_translations=Mock(),update_modern_view=Mock())
        with patch('tg_ascii.translated_view.clear_buttons'),patch('tg_ascii.animated_emojis.ensure_pack'):
            Desktop.render_messages(app,False)
        app.history.insert.assert_not_called();app.schedule_translations.assert_called_once()
        app.update_modern_view.assert_called_once_with(False)


class SearchTests(IsolatedAsyncioTestCase):
    async def test_custom_keywords_packs_pagination_and_cache(self):
        doc=NS(id=1);pack=NS(id=3,title='Cats',short_name='cats')
        async def rpc(request):
            if isinstance(request,functions.messages.SearchStickersRequest):return NS(stickers=[doc,doc],next_offset=request.offset+60)
            return NS(sets=[NS(set=pack)])
        backend=NS(client=AsyncMock(side_effect=rpc))
        result=await search(backend,'cat',True,'ca-valencia')
        self.assertEqual(result,{'documents':[doc],'packs':[pack],'next':60})
        req=backend.client.call_args_list[0].args[0]
        self.assertTrue(req.emojis);self.assertEqual((req.q,req.emoticon,req.lang_code),('cat','',['ca']))
        self.assertIsInstance(backend.client.call_args_list[1].args[0],functions.messages.SearchEmojiStickerSetsRequest)
        await search(backend,'cat',True,'ca-valencia');self.assertEqual(backend.client.call_count,2)
        await search(backend,'cat',True,'ca-valencia',60);self.assertEqual(backend.client.call_count,3)
        self.assertEqual(backend.client.call_args.args[0].offset,60)

    async def test_equivalent_emoji_and_partial_search_failure(self):
        backend=NS(client=AsyncMock(return_value=NS(stickers=[NS(id=9)],next_offset=0)))
        result=await search(backend,'❤️');req=backend.client.call_args.args[0]
        self.assertEqual((req.q,req.emoticon),('','❤️'));self.assertIsNone(result['next'])
        backend.client=AsyncMock(side_effect=[RuntimeError('network'),NS(sets=[NS(set=NS(id=8))])])
        result=await search(backend,'kitten');self.assertEqual(result['documents'],[]);self.assertEqual(result['packs'][0].id,8)

    async def test_failure_not_cached_and_caches_are_bounded_and_separate(self):
        a,b=NS(),NS();loader=AsyncMock(side_effect=RuntimeError())
        with self.assertRaises(RuntimeError):await cached(a,1,loader)
        loader.side_effect=None;loader.return_value='ok'
        self.assertEqual(await cached(a,1,loader),'ok')
        await cached(b,1,loader);self.assertEqual(loader.call_count,3)
        for i in range(100):await cached(a,i,loader)
        self.assertEqual(len(a._sticker_catalogue),64)
        before=loader.call_count
        await cached(a,99,loader,ttl=0);self.assertEqual(loader.call_count,before+1)

    def test_local_matching_accents_pack_shortname_and_emoji_variant(self):
        packs=[NS(title='Gatós felices',short_name='HappyCats'),NS(title='Dogs',short_name='dogs')]
        self.assertEqual(matching_packs(packs,'gatos'),packs[:1]);self.assertEqual(matching_packs(packs,'happycats'),packs[:1])
        doc=NS(attributes=[types.DocumentAttributeSticker(alt='❤️',stickerset=types.InputStickerSetEmpty())])
        self.assertEqual(matching_documents([doc],'❤'),[doc])

    def test_debounce_cancellation_and_stale_results(self):
        window=Canvas();app=NS(worker=Mock());current=[True];requests=PickerRequests(app,window,lambda:current[0])
        first,second=Mock(return_value='first'),Mock(return_value='second');done=Mock();failed=Mock()
        requests.load(first,done,failed,300);requests.load(second,done,failed,300)
        self.assertEqual(len(window.jobs),1);window.flush();first.assert_not_called();second.assert_called_once()
        future=app.worker.submit.return_value;stale=app.worker.submit.call_args.args[1]
        requests.load(first,done,failed);future.cancel.assert_called_once();stale('old');done.assert_not_called()
        current[0]=False;app.worker.submit.call_args.args[1]('wrong account');done.assert_not_called()

    async def test_emoji_download_deduplicates_and_finishes_after_caller_cancel(self):
        from tg_ascii.animation import emoji_file
        app=NS(preferences=NS(values={'animated_emoji':True}));started=asyncio.Event();release=asyncio.Event()
        async def fetch(*args):started.set();await release.wait();return __file__
        with patch('tg_ascii.animation._emoji_file',side_effect=fetch) as loader:
            first=asyncio.create_task(emoji_file(app,NS(id=4),'a',None));await started.wait()
            second=asyncio.create_task(emoji_file(app,NS(id=4),'a',None));await asyncio.sleep(0)
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):await first
            release.set();self.assertEqual(await second,__file__)
            self.assertFalse(app._emoji_jobs)
            self.assertEqual(await emoji_file(app,NS(id=4),'a',None),__file__);self.assertEqual(loader.call_count,1)


class RoundedLayoutTests(TestCase):
    def test_large_control_fill_is_not_tiled_in_two_pixel_patches(self):
        import math
        from tg_ascii.appearance import _surface_image
        for narrow, border in ((False, 40), (True, 12)):
            for radius in (1, 8, 24):
                image = _surface_image(radius, '#123456', '#789abc', '#000000', border_width=1, narrow=narrow)
                centre = image.width - 2 * border
                self.assertEqual(centre, 128)
                self.assertEqual(image.getpixel((image.width // 2, image.height // 2)), (18, 52, 86))
                calls = math.ceil((1000 - 2 * border) / centre) * math.ceil((700 - 2 * border) / centre)
                self.assertLessEqual(calls, 48)

    def test_style_art_is_shared_and_does_not_set_giant_minimum_widget_sizes(self):
        from tg_ascii.appearance import configure_shapes
        from tg_ascii.themes import DARK
        from tg_ascii.preferences import DEFAULTS
        root=NS();style=Mock();style.layout.return_value=[]
        with patch('tg_ascii.appearance.ImageTk.PhotoImage',side_effect=lambda *a,**k:object()) as photo:
            configure_shapes(root,style,{**DEFAULTS,'button_radius':24,'menu_radius':24},DARK)
            self.assertLess(photo.call_count,20)
            for call in style.element_create.call_args_list:
                if 'Checkbutton' not in call.args[0]:
                    self.assertIn(call.kwargs['width'],(0,12,14));self.assertIn(call.kwargs['height'],(0,12,14))
            count=photo.call_count
            configure_shapes(root,style,{**DEFAULTS,'button_radius':24,'menu_radius':24},DARK)
            self.assertEqual(photo.call_count,count)

    def test_square_defaults_allocate_no_rounded_control_images(self):
        from tg_ascii.appearance import configure_shapes
        from tg_ascii.themes import DARK
        from tg_ascii.preferences import DEFAULTS
        root=NS();style=Mock();style.layout.return_value=[]
        with patch('tg_ascii.appearance.ImageTk.PhotoImage') as photo:
            configure_shapes(root,style,DEFAULTS,DARK)
            photo.assert_not_called();style.element_create.assert_not_called()

    def test_scroll_extent_excludes_decorative_corners_and_avoids_feedback(self):
        from tg_ascii.ui_work import content_scrollregion,content_width
        canvas=Mock();canvas.bbox.side_effect=lambda tag:(0,0,800,600) if tag==7 else (0,0,80000,60000)
        for _ in range(100):content_scrollregion(canvas,7);content_width(canvas,7,800)
        canvas.configure.assert_called_once_with(scrollregion=(0,0,800,600))
        canvas.itemconfigure.assert_called_once_with(7,width=800)
        self.assertTrue(all(call.args==(7,) for call in canvas.bbox.call_args_list))

    def test_flow_layout_does_not_replace_every_button_after_unchanged_resize(self):
        from tg_ascii.scrolling import FlowFrame
        children=[]
        for _ in range(10):
            child=NS(winfo_reqwidth=lambda:70,winfo_reqheight=lambda:30,winfo_manager=Mock(return_value='pack'),pack_forget=Mock(),place=Mock())
            def place(child=child,**kw):child.winfo_manager.return_value='place'
            child.place.side_effect=place;children.append(child)
        frame=NS(_arranging=False,winfo_exists=lambda:True,winfo_width=lambda:400,winfo_children=lambda:children,configure=Mock())
        for _ in range(100):FlowFrame.arrange(frame)
        for child in children:child.place.assert_called_once();child.pack_forget.assert_called_once()
        frame.configure.assert_called_once()
