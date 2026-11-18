import asyncio
import io
from pathlib import Path
import struct
import tempfile
import tkinter as tk
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

from tg_ascii.animation import AnimationPlayer, decode_frames, frame_duration
from tg_ascii.image_tools import edited_image, editor_preview, render_annotations
from tg_ascii.media_viewer import ImageFrames, show_image
from tg_ascii.rich_preview import fit_text
from tg_ascii.sticker_picker import StickerGrid
from tg_ascii.video_metadata import boxes, mp4_metadata


class AnimationTests(TestCase):
    def test_large_animation_has_a_cumulative_decode_budget(self):
        source=Mock(width=6000,height=5000,n_frames=90,info={'duration':None})
        source.__enter__=Mock(return_value=source)
        source.__exit__=Mock(return_value=False)
        source.convert.side_effect=lambda mode:Image.new(mode,(32,32))
        with patch('PIL.Image.open',return_value=source):
            frames,durations=decode_frames('large.gif',(64,64))
        self.assertEqual(len(frames),2)
        self.assertEqual(source.seek.call_count,2)
        self.assertEqual(durations,[100,100])

    def test_invalid_frame_duration_is_safe_and_bounded(self):
        for value in (None,'broken',float('nan'),float('inf')):
            self.assertEqual(frame_duration(value),100)
        self.assertEqual(frame_duration(-100),33)
        self.assertEqual(frame_duration(10_000),1000)

    def test_cache_evicts_by_bytes_and_oversize_images_are_not_retained(self):
        class Photo:
            def __init__(self,*args,**kwargs):pass
        player=AnimationPlayer(Mock())
        with patch('PIL.ImageTk.PhotoImage',Photo),patch('tg_ascii.animation.MAX_CACHE_BYTES',800):
            frames=([Image.new('RGB',(10,10))],[100])
            first=player.photo(__file__,(10,10),prepared=frames)
            second=player.photo(__file__,(11,11),prepared=frames)
            self.assertEqual(player.cache_bytes,800)
            third=player.photo(__file__,(12,12),prepared=frames)
            self.assertEqual(len(player.cache),2)
            self.assertEqual(player.cache_bytes,800)
            huge=player.photo(__file__,(20,20),prepared=([Image.new('RGB',(20,20))],[100]))
            self.assertEqual(len(player.cache),2)
            self.assertEqual(player.cache_bytes,800)
            self.assertTrue(all(photo is not None for photo in (first,second,third,huge)))
        player.stop()
        self.assertEqual(player.cache_bytes,0)

    def test_shutdown_tolerates_an_already_destroyed_root(self):
        root=Mock();root.after_cancel.side_effect=tk.TclError('destroyed')
        player=AnimationPlayer(root);player.job='timer'
        player.stop();player.stop()
        self.assertTrue(player.stopped)
        self.assertIsNone(player.job)


class ImageTests(TestCase):
    def test_editor_preview_is_bounded_and_original_remains_full_resolution(self):
        original=Image.new('RGB',(3000,2000),'red')
        original.getexif()[274]=6
        preview=editor_preview(original)
        self.assertLessEqual(max(preview.size),1280)
        self.assertLess(preview.width,preview.height)
        self.assertEqual(original.size,(3000,2000))
        exported=edited_image(original,brightness=.5)
        self.assertEqual(exported.size,(2000,3000))
        self.assertEqual(exported.getpixel((0,0)),(127,0,0))

    def test_neutral_adjustments_do_not_build_three_enhancement_images(self):
        original=Image.new('RGB',(10,10),'red')
        with patch('PIL.ImageEnhance.Brightness') as brightness,patch('PIL.ImageEnhance.Contrast') as contrast,patch('PIL.ImageEnhance.Color') as saturation:
            result=edited_image(original)
        self.assertEqual(result.tobytes(),original.tobytes())
        brightness.assert_not_called();contrast.assert_not_called();saturation.assert_not_called()

    def test_annotations_preserve_opaque_and_translucent_compositing(self):
        original=Image.new('RGB',(100,100),'white')
        stroke={'kind':'stroke','points':[(.1,.5),(.9,.5)],'width':.1,'color':'#ff0000'}
        with patch('PIL.Image.alpha_composite',wraps=Image.alpha_composite) as composite:
            opaque=render_annotations(original,[stroke])
            composite.assert_not_called()
            translucent=render_annotations(original,[dict(stroke,opacity=.5)])
            composite.assert_called_once()
        self.assertEqual(opaque.getpixel((50,50)),(255,0,0))
        self.assertEqual(translucent.getpixel((50,50)),(255,127,127))
        self.assertEqual(original.getpixel((50,50)),(255,255,255))

    def test_viewer_reuses_current_frame_and_closes_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'motion.gif'
            Image.new('RGB',(10,10),'red').save(path,save_all=True,
                append_images=[Image.new('RGB',(10,10),'blue')],duration=100)
            source=ImageFrames(path)
            first=source.get(0)
            for _ in range(100):self.assertIs(source.get(0),first)
            second=source.get(1)
            self.assertEqual(second.getpixel((0,0)),(0,0,255,255))
            with self.assertRaises(ValueError):first.getpixel((0,0))
            source.close();source.close()
            self.assertIsNone(source.image.fp)
            with self.assertRaises(ValueError):second.getpixel((0,0))

    def test_viewer_rejects_oversized_images_without_leaking_descriptor(self):
        image=Mock(width=10000,height=10000)
        with patch('PIL.Image.open',return_value=image):
            with self.assertRaises(ValueError):ImageFrames('huge.png')
        image.close.assert_called_once()

    def test_static_viewer_releases_decoder_after_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'still.png';Image.new('RGB',(20,20),'red').save(path)
            source=ImageFrames(path);frame=source.get(0)
            self.assertIsNone(source.image.fp)
            self.assertIs(source.get(0),frame)
            self.assertEqual(frame.getpixel((0,0)),(255,0,0,255))
            source.close()

    def test_viewer_pauses_hidden_animation_and_parent_destruction_cleans_up(self):
        window=Mock();window.winfo_exists.return_value=True;window.winfo_viewable.return_value=True
        window.after.return_value='timer'
        canvas=Mock();canvas.winfo_width.return_value=200;canvas.winfo_height.return_value=150
        source=Mock(count=2);source.get.return_value=Image.new('RGBA',(20,20),'red')
        source.image.info={'duration':100}
        renderer=Mock(count=2);renderer.poll.return_value=(Image.new('RGBA',(200,150),'red'),[0,0],100)
        renderer.close.side_effect=source.close
        with patch('tg_ascii.media_viewer.ImageFrames',return_value=source),\
                patch('tg_ascii.media_viewer.FrameRenderer',return_value=renderer),\
                patch('tg_ascii.media_viewer.tk.Toplevel',return_value=window),\
                patch('tg_ascii.media_viewer.tk.Canvas',return_value=canvas),\
                patch('tg_ascii.media_viewer.ttk.Frame'),patch('tg_ascii.media_viewer.ttk.Label'),\
                patch('tg_ascii.media_viewer.ttk.Button'),patch('PIL.ImageTk.PhotoImage'),\
                patch('tg_ascii.image_gestures.ImageGestures'),patch('tg_ascii.themes.apply_widget'):
            self.assertIs(show_image(Mock(),'ignored.gif'),window)
            window.after.call_args.args[1]()  # Initial coalesced paint.
            renderer.request.assert_called_once_with(0,(200,150),1.,[0,0])
            window.after.call_args.args[1]()  # Receive decoded pixels on Tk.
            advance=window.after.call_args.args[1]
            window.winfo_viewable.return_value=False;advance()
            self.assertEqual(window.after.call_args.args[0],250)
            renderer.request.assert_called_once()
            cleanup=next(call.args[1] for call in window.bind.call_args_list if call.args[0]=='<Destroy>')
            cleanup(NS(widget=canvas));source.close.assert_not_called()
            cleanup(NS(widget=window));cleanup(NS(widget=window))
            source.close.assert_called_once();window.after_cancel.assert_called_with('timer')


class TextAndMetadataTests(TestCase):
    def test_exact_fit_has_no_unnecessary_ellipsis_and_long_text_uses_bisection(self):
        self.assertEqual(fit_text('hello',5,len),('hello',False))
        measure=Mock(side_effect=len)
        result,truncated=fit_text('a'*10000,100,measure)
        self.assertEqual(result,'a'*99+'…');self.assertTrue(truncated)
        self.assertLess(measure.call_count,20)
        self.assertEqual(fit_text('hello',0,len),('',True))

    def test_truncated_box_is_a_validation_error(self):
        with self.assertRaises(ValueError):list(boxes(io.BytesIO(b'123'),0,8))
        with self.assertRaises(ValueError):list(boxes(io.BytesIO(struct.pack('>I4s',1,b'moov')),0,16))

    def test_box_budget_stops_pathological_metadata(self):
        data=struct.pack('>I4s',8,b'free')*10
        with self.assertRaisesRegex(ValueError,'Too many'):
            list(boxes(io.BytesIO(data),0,len(data),budget=[3]))

    def test_mp4_version_one_dimensions_and_duration(self):
        def box(kind,payload):return struct.pack('>I4s',len(payload)+8,kind)+payload
        duration=bytearray(32);duration[0]=1;struct.pack_into('>IQ',duration,20,1000,30_000)
        track=bytearray(96);track[0]=1;struct.pack_into('>II',track,88,720<<16,1280<<16)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'clip.mp4'
            path.write_bytes(box(b'moov',box(b'mvhd',duration)+box(b'trak',box(b'tkhd',track))))
            self.assertEqual(mp4_metadata(path),(30,720,1280))
            track=track[:90]
            path.write_bytes(box(b'moov',box(b'mvhd',duration)+box(b'trak',box(b'tkhd',track))))
            with self.assertRaises(ValueError):mp4_metadata(path)


class StickerWorkTests(IsolatedAsyncioTestCase):
    def grid(self):
        return NS(version=0,pending=set(),failed=set(),_wanted={1},account='a',backend=Mock(),cell=64,
            app=NS(ui_account='a',worker=Mock(),preview_slots=asyncio.Semaphore(1)),
            winfo_exists=lambda:True,repaint=Mock())

    async def test_scrolled_offscreen_request_does_not_download_or_decode(self):
        grid=self.grid()
        StickerGrid.load(grid,NS(id=1))
        coroutine,ready,_=grid.app.worker.submit.call_args.args
        grid._wanted=set()
        with patch('tg_ascii.animation.emoji_file',new_callable=AsyncMock) as download:
            result=await coroutine
        ready(result)
        download.assert_not_awaited()
        self.assertFalse(grid.pending);self.assertFalse(grid.failed)

    async def test_fast_scrolling_has_a_bounded_queue(self):
        grid=self.grid()
        try:
            for ident in range(1000):StickerGrid.load(grid,NS(id=ident))
            self.assertEqual(len(grid.pending),16)
            self.assertEqual(grid.app.worker.submit.call_count,16)
        finally:
            for call in grid.app.worker.submit.call_args_list:call.args[0].close()
