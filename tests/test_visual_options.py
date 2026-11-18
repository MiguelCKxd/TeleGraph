import gc
import gzip
import json
from pathlib import Path
from types import SimpleNamespace as NS
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch
from PIL import Image
from telethon import types,functions
from tg_ascii.animation import decode_frames,render_animation,emoji_file,AnimationPlayer
from tg_ascii.preferences import Preferences
from tg_ascii.interface_background import save_image,chat_backdrop,InterfaceBackground
from tg_ascii.telegram_wallpapers import fill_image,render_wallpaper,selected_default,catalog
from tg_ascii.custom_icon import icon_image,reset_icon
from tg_ascii.animated_emojis import candidate,animated_content,ensure_pack
from tg_ascii.backend import Message


class VisualFilesTests(unittest.TestCase):
    def test_optional_backgrounds_keep_defaults_and_choices_persist_independently(self):
        with tempfile.TemporaryDirectory() as folder:
            prefs=Preferences(folder)
            self.assertFalse(prefs.values['telegram_backgrounds'])
            self.assertEqual(prefs.values['interface_background'],'')
            self.assertEqual(prefs.values['custom_icon'],'')
            prefs.save({'interface_background':'/local/interface.jpg','custom_icon':'/local/icon.png','telegram_backgrounds':True})
            saved=Preferences(folder).values
            self.assertEqual(saved['background_color'],'')
            self.assertEqual(saved['theme'],'dark')
            self.assertEqual(saved['custom_icon'],'/local/icon.png')
            self.assertTrue(saved['telegram_backgrounds'])
            invalid=Preferences.validated({'interface_background':'bad\npath','animated_emoji':'yes','telegram_backgrounds':1})
            self.assertEqual(invalid['interface_background'],'')
            self.assertFalse(invalid['telegram_backgrounds'])

    def test_owned_interface_copy_survives_moving_original_and_chat_has_priority(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.png';Image.new('RGB',(40,20),'red').save(source)
            owned=save_image(source,Path(folder)/'owned');source.unlink()
            app=NS(preferences=NS(values={'interface_background':str(owned)}),wallpaper_path=None)
            self.assertEqual(chat_backdrop(app),str(owned))
            chat=Path(folder)/'chat.png';Image.new('RGB',(20,20),'blue').save(chat);app.wallpaper_path=chat
            self.assertEqual(chat_backdrop(app),chat)
            chat.unlink();self.assertEqual(chat_backdrop(app),str(owned))
            app.preferences.values['interface_background']='';self.assertIsNone(chat_backdrop(app))

    def test_custom_icon_is_square_rounded_and_can_restore_without_changing_background(self):
        image=Image.new('RGB',(100,40),'red');icon=icon_image(image,size=64)
        self.assertEqual(icon.size,(64,64));self.assertEqual(icon.getpixel((0,0))[3],0)
        self.assertEqual(icon.getpixel((32,32)),(255,0,0,255))
        with tempfile.TemporaryDirectory() as folder:
            prefs=Preferences(folder);prefs.save({'custom_icon':'chosen.png','interface_background':'wall.jpg'})
            app=NS(preferences=prefs,refresh_logo=Mock(),update_logo_selection=Mock())
            reset_icon(app)
            self.assertEqual(prefs.values['custom_icon'],'');self.assertEqual(prefs.values['interface_background'],'wall.jpg')
            app.refresh_logo.assert_called_once()

    def test_telegram_choice_disabled_does_not_override_private_defaults(self):
        app=NS(preferences=NS(values={'telegram_backgrounds':False}),wallpapers={'a:default':'own.jpg','a:telegram-default':'tg.jpg','b:telegram-default':'other.jpg'})
        self.assertEqual(selected_default(app,'a'),'own.jpg')
        app.preferences.values['telegram_backgrounds']=True
        self.assertEqual(selected_default(app,'a'),'tg.jpg');self.assertEqual(selected_default(app,'b'),'other.jpg')
        self.assertIsNone(selected_default(app,'c'))

    def test_wallpaper_solid_gradient_and_pattern_intensity(self):
        solid=fill_image(NS(background_color=0x336699),(20,30));self.assertEqual(solid.getpixel((5,6)),(51,102,153))
        gradient=fill_image(NS(background_color=0xff0000,second_background_color=0x0000ff,rotation=0),(128,128))
        self.assertEqual(gradient.getpixel((0,0)),(255,0,0));self.assertEqual(gradient.getpixel((0,127)),(0,0,255))
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'pattern.png';output=Path(folder)/'result.jpg'
            pattern=Image.new('RGBA',(10,10),(0,0,0,0));pattern.putpixel((5,5),(0,0,0,255));pattern.save(source)
            paper=NS(document=NS(mime_type='image/png'),pattern=True,settings=NS(background_color=0xffffff,intensity=100))
            render_wallpaper(paper,source,output,(10,10))
            with Image.open(output) as result:
                self.assertLess(sum(result.getpixel((5,5))),60);self.assertGreater(sum(result.getpixel((0,0))),700)
            paper.settings.intensity=0;render_wallpaper(paper,source,output,(10,10))
            with Image.open(output) as result:self.assertGreater(sum(result.getpixel((5,5))),700)

    def test_gif_and_webp_animation_keep_distinct_frames_and_timing(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'emoji.gif';output=Path(folder)/'emoji.webp'
            first=Image.new('RGBA',(32,32),'red');second=Image.new('RGBA',(32,32),'blue')
            first.save(source,save_all=True,append_images=[second],duration=[80,160],loop=0)
            render_animation(source,output,'image/gif')
            frames,durations=decode_frames(output,(24,24))
            self.assertEqual(len(frames),2);self.assertEqual(frames[0].size,(24,24))
            self.assertNotEqual(frames[0].getpixel((8,8)),frames[1].getpixel((8,8)))
            self.assertEqual(durations,[80,160])

    def test_tgs_adapter_samples_framerate_and_rejects_external_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'emoji.tgs';output=Path(folder)/'emoji.webp'
            with gzip.open(source,'wt',encoding='utf-8') as file:json.dump({'fr':60,'ip':0,'op':6},file)
            engine=Mock();engine.__enter__=Mock(return_value=engine);engine.__exit__=Mock(return_value=False)
            engine.lottie_animation_get_totalframe.return_value=6;engine.lottie_animation_get_framerate.return_value=60
            engine.render_pillow_frame.side_effect=lambda **kw:Image.new('RGBA',(128,128),(kw['frame_num']*30,0,0,255))
            cls=NS(from_data=Mock(return_value=engine))
            with patch.dict('sys.modules',{'rlottie_python':NS(LottieAnimation=cls)}):
                render_animation(source,output,'application/x-tgsticker')
                self.assertEqual([call.kwargs['frame_num'] for call in engine.render_pillow_frame.call_args_list],[0,2,4])
                with gzip.open(source,'wt',encoding='utf-8') as file:json.dump({'fr':60,'ip':0,'op':6,'assets':[{'p':'external.png'}]},file)
                with self.assertRaises(ValueError):render_animation(source,output,'application/x-tgsticker')

    def test_player_single_clock_weak_references_pause_and_shutdown(self):
        class Photo:
            def __init__(self,*args,**kwargs):self.frames=[]
            def paste(self,frame):self.frames.append(frame)
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'emoji.gif';a=Image.new('RGB',(10,10),'red');b=Image.new('RGB',(10,10),'blue')
            a.save(source,save_all=True,append_images=[b],duration=100,loop=0)
            root=Mock();root.winfo_viewable.return_value=False
            player=AnimationPlayer(root)
            with patch('PIL.ImageTk.PhotoImage',Photo):photo=player.photo(source,(10,10))
            root.after.assert_called_once();player.entries[0][4]=0;player.tick();self.assertEqual(photo.frames,[])
            root.winfo_viewable.return_value=True;player.tick();self.assertEqual(len(photo.frames),1)
            del photo;gc.collect();player.tick();self.assertEqual(player.entries,[])
            player.stop();self.assertTrue(player.stopped)

    def test_standard_emoji_uses_local_entity_without_altering_message(self):
        message=Message(1,'Ada','❤️','12:00',raw_text='❤️')
        self.assertEqual(candidate(message),'❤');self.assertEqual(candidate(Message(2,'Ada','hello ❤️','12:00')),'')
        document=NS(id=123)
        app=NS(ui_account='a',preferences=NS(values={'animated_emoji':True}),_standard_emoji_packs={'a':{'❤':document}})
        view=animated_content(app,message)
        self.assertEqual(view.entities[0].document_id,123);self.assertEqual(message.entities,())
        app.preferences.values['animated_emoji']=False;self.assertIs(animated_content(app,message),message)

    def test_background_frame_image_never_claims_layout_space_and_restores_style(self):
        class Frame:
            def __init__(self):self.style='TFrame'
            def winfo_children(self):return []
            def winfo_exists(self):return True
            def winfo_rootx(self):return 0
            def winfo_rooty(self):return 0
            def winfo_width(self):return 200
            def winfo_height(self):return 160
            def cget(self,key):return self.style
            def configure(self,**kwargs):self.style=kwargs['style']
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'wall.png';Image.new('RGB',(30,30),'blue').save(path)
            frame=Frame();root=Mock();root.winfo_width.return_value=200;root.winfo_height.return_value=160
            root.winfo_rootx.return_value=root.winfo_rooty.return_value=0
            app=NS(root=root,container=frame,preferences=NS(values={'interface_background':str(path),'theme':'dark'}),worker=Mock())
            painter=InterfaceBackground(app)
            with patch('tg_ascii.interface_background.ttk.Style') as style,patch('tg_ascii.interface_background.tk.PhotoImage'):
                import asyncio
                painter.paint()
                operation,loaded,_=app.worker.submit.call_args.args
                loaded(asyncio.run(operation))
                painter.paint()
                options=style.return_value.element_create.call_args.kwargs
                self.assertEqual((options['width'],options['height']),(0,0))
                self.assertNotEqual(frame.style,'TFrame')
                app.preferences.values['interface_background']='';painter.paint()
                self.assertEqual(frame.style,'TFrame')

    def test_scroll_and_jump_follow_image_canvas_when_bubbles_are_disabled(self):
        from tg_ascii.desktop_modern import DesktopModern
        app=NS(preferences=NS(values={'bubbles':False}),_canvas_chat_view=True,bubble_view=Mock(),history=Mock(),demo=True)
        DesktopModern.scroll_messages(app,'scroll',1,'units')
        app.bubble_view.yview.assert_called_once_with('scroll',1,'units')
        app.history.yview.assert_not_called()
        DesktopModern.latest_messages(app);app.bubble_view.yview_moveto.assert_called_once_with(1)
        DesktopModern.jump_loaded(app,7);app.bubble_view.jump.assert_called_once_with(7)


class VisualServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_unavailable_or_disabled_animation_downloads_only_thumbnail(self):
        with tempfile.TemporaryDirectory() as folder:
            app=NS(preview_dir=Path(folder),preferences=NS(values={'animated_emoji':False}))
            backend=NS(download_media=AsyncMock(return_value='thumb.jpg'));document=NS(id=4,mime_type='application/x-tgsticker',size=100)
            self.assertEqual(await emoji_file(app,document,'a',backend),'thumb.jpg')
            self.assertTrue(backend.download_media.call_args.kwargs['thumbnail'])
            app.preferences.values['animated_emoji']=True;backend.download_media.reset_mock()
            with patch('tg_ascii.animation.renderer_available',return_value=False):await emoji_file(app,document,'a',backend)
            self.assertTrue(backend.download_media.call_args.kwargs['thumbnail'])

    async def test_decoder_error_falls_back_to_thumbnail(self):
        with tempfile.TemporaryDirectory() as folder:
            app=NS(preview_dir=Path(folder),preferences=NS(values={'animated_emoji':True}))
            backend=NS(download_media=AsyncMock(side_effect=['full.tgs','thumb.jpg']))
            with patch('tg_ascii.animation.renderer_available',return_value=True),patch('tg_ascii.animation.render_animation',side_effect=ValueError('broken')):
                result=await emoji_file(app,NS(id=1,mime_type='application/x-tgsticker',size=100),'a',backend)
            self.assertEqual(result,'thumb.jpg');self.assertEqual(backend.download_media.await_count,2)

    async def test_catalog_is_read_only_and_default_wallpapers_first(self):
        backend=NS(client=AsyncMock(return_value=NS(wallpapers=[NS(id=1,default=False),NS(id=2,default=True)])))
        result=await catalog(backend)
        self.assertEqual([v.id for v in result],[2,1]);backend.client.assert_awaited_once()
        self.assertIsInstance(backend.client.call_args.args[0],functions.account.GetWallPapersRequest)

    async def test_standard_pack_single_request_and_original_message_is_preserved(self):
        document=NS(id=123)
        backend=NS(client=AsyncMock(return_value=NS(documents=[document],packs=[NS(emoticon='❤️',documents=[123])])))
        app=NS(demo=False,active=42,ui_account='a',preferences=NS(values={'animated_emoji':True}),messages=[Message(1,'Ada','❤️','12:00')],service=NS(backend=backend,entries={'a':1}),worker=Mock(),render_messages=Mock())
        with patch('tg_ascii.animation.renderer_available',return_value=True):ensure_pack(app);ensure_pack(app)
        app.worker.submit.assert_called_once();coroutine,done,_=app.worker.submit.call_args.args
        done(await coroutine)
        self.assertEqual(app._standard_emoji_packs['a']['❤'].id,123)
        self.assertEqual(app.messages[0].entities,())
        self.assertIsInstance(backend.client.call_args.args[0].stickerset,types.InputStickerSetAnimatedEmoji)


if __name__=='__main__':unittest.main()
