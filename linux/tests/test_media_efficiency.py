"""Bounded media work, worker-only pixel transforms and lifecycle regressions."""
import asyncio
from collections import OrderedDict
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

from tg_ascii.animation import AnimationPlayer
from tg_ascii.emoji_documents import EmojiDocuments
from tg_ascii.media_viewer import FrameRenderer
from tg_ascii.image_tools import ImageWork, load_editor_image, rendered_edit, release_variables
from tg_ascii.rich_preview import preview_runs
from tg_ascii.shared_media import SharedMediaBrowser, SharedPhotoGrid
from tg_ascii.sticker_picker import StickerGrid
from tg_ascii.text_layout import cluster_ends, iter_cluster_ends


class PreparationTests(unittest.TestCase):
    def test_worker_prepares_once_and_tk_delivery_does_not_decode_again(self):
        from concurrent.futures import ThreadPoolExecutor
        player=AnimationPlayer(Mock())
        main=threading.get_ident();threads=[]
        def decode(*args,**kwargs):
            threads.append(threading.get_ident())
            return [Image.new('RGBA',(8,8),'red')],[100]
        with patch('tg_ascii.animation.decode_frames',side_effect=decode), \
             patch('PIL.ImageTk.PhotoImage') as photo:
            with ThreadPoolExecutor(max_workers=1) as worker:
                first=worker.submit(player.prepare,__file__,(8,8)).result()
                for _ in range(100):self.assertIs(worker.submit(player.prepare,__file__,(8,8)).result()[0],first[0])
            photo.assert_not_called()
            player.photo(__file__,(8,8))
            photo.assert_called_once()
        self.assertEqual(len(threads),1)
        self.assertNotEqual(threads[0],main)
        self.assertEqual(player.cache_bytes,8*8*4)
        player.stop()

    def test_shutdown_during_preparation_does_not_repopulate_cache(self):
        from concurrent.futures import ThreadPoolExecutor
        entered=threading.Event();release=threading.Event()
        player=AnimationPlayer(Mock())
        def decode(*args,**kwargs):
            entered.set();release.wait(2)
            return [Image.new('RGBA',(8,8))],[100]
        with patch('tg_ascii.animation.decode_frames',side_effect=decode),ThreadPoolExecutor(max_workers=1) as worker:
            work=worker.submit(player.prepare,__file__,(8,8))
            self.assertTrue(entered.wait(1))
            player.stop();release.set();work.result()
        self.assertFalse(player.cache)
        self.assertEqual(player.cache_bytes,0)

    def test_hidden_owner_pauses_shared_photo_but_visible_second_owner_resumes(self):
        class Photo:
            def __init__(self,*args,**kwargs):self.paste=Mock()
        root=Mock();root.winfo_viewable.return_value=True
        first,second=Mock(),Mock()
        first.winfo_viewable.return_value=second.winfo_viewable.return_value=False
        player=AnimationPlayer(root)
        prepared=([Image.new('RGBA',(8,8)),Image.new('RGBA',(8,8))],[500,500])
        with patch('PIL.ImageTk.PhotoImage',Photo):
            photo=player.photo(__file__,(8,8),prepared=prepared,owner=first)
            self.assertIs(photo,player.photo(__file__,(8,8),owner=second))
        player.entries[0][4]=0;player.tick()
        photo.paste.assert_not_called()
        self.assertEqual(root.after.call_args.args[0],250)
        second.winfo_viewable.return_value=True;player.tick()
        photo.paste.assert_called_once()
        self.assertGreater(root.after.call_args.args[0],33)
        player.stop()


class RendererTests(unittest.TestCase):
    def test_viewer_opens_and_inspects_animation_only_on_worker(self):
        main=threading.get_ident();threads=[]
        image=Image.new('RGBA',(8,8))
        source=NS(count=2,get=Mock(return_value=image),image=NS(info={'duration':100}),close=Mock())
        def open_source(path):threads.append(threading.get_ident());return source
        with patch('tg_ascii.media_viewer.ImageFrames',side_effect=open_source) as opened:
            renderer=FrameRenderer('animation.gif');opened.assert_not_called()
            renderer.request(0,(8,8),1,(0,0));renderer.future.result(timeout=2)
            shown,_,_=renderer.poll();shown.close();renderer.close()
        self.assertEqual(renderer.count,2);self.assertNotEqual(threads,[main])
        source.close.assert_called_once();image.close()

    def test_viewport_burst_keeps_only_running_and_latest_request(self):
        source=Mock();renderer=FrameRenderer(source)
        entered=threading.Event();release=threading.Event();indices=[];images=[]
        def render(index,*args):
            indices.append(index)
            if index==0:entered.set();release.wait(2)
            image=Image.new('RGBA',(8,8));images.append(image)
            return image,[index,0],100
        renderer.render=render
        renderer.request(0,(8,8),1,(0,0));self.assertTrue(entered.wait(1))
        for index in range(1,1000):renderer.request(index,(8,8),1,(index,0))
        release.set();renderer.future.result(timeout=2)
        self.assertIsNone(renderer.poll())  # The first viewport was superseded.
        renderer.future.result(timeout=2)
        result=renderer.poll()
        self.assertEqual(indices,[0,999])
        self.assertEqual(result[1],[999,0])
        with self.assertRaises(ValueError):images[0].getpixel((0,0))
        result[0].close();renderer.close();source.close.assert_called_once()

    def test_close_during_decode_is_nonblocking_and_releases_result_and_source(self):
        source=Mock();closed=threading.Event();source.close.side_effect=closed.set
        renderer=FrameRenderer(source);entered=threading.Event();release=threading.Event();image=Image.new('RGBA',(8,8))
        def render(*args):entered.set();release.wait(2);return image,[0,0],100
        renderer.render=render
        renderer.request(0,(8,8),1,(0,0));self.assertTrue(entered.wait(1))
        renderer.close();renderer.close()
        self.assertFalse(release.is_set());self.assertFalse(closed.is_set())
        renderer.request(1,(8,8),1,(0,0));self.assertIsNone(renderer.pending)
        release.set();self.assertTrue(closed.wait(1))
        with self.assertRaises(ValueError):image.getpixel((0,0))
        source.close.assert_called_once()

    def test_real_transform_runs_off_caller_and_keeps_viewport_sized_output(self):
        main=threading.get_ident();threads=[]
        frame=Image.new('RGBA',(800,600),'red')
        def get(index):threads.append(threading.get_ident());return frame
        source=NS(get=get,image=NS(info={'duration':80}),close=Mock())
        renderer=FrameRenderer(source)
        renderer.request(0,(160,120),12,(1000,2000));renderer.future.result(timeout=2)
        shown,pan,duration=renderer.poll()
        self.assertEqual(shown.size,(160,120));self.assertEqual(duration,80)
        self.assertEqual(len(threads),1);self.assertNotEqual(threads[0],main)
        shown.close();renderer.close();frame.close()


class EditorWorkerTests(unittest.TestCase):
    def test_closed_editor_variables_never_access_tk_when_later_collected_by_worker(self):
        import tkinter as tk
        from concurrent.futures import ThreadPoolExecutor
        main=threading.get_ident();calls=[]
        interpreter=Mock();interpreter.call.side_effect=lambda *args:calls.append(threading.get_ident()) or False
        interpreter.getboolean.side_effect=bool
        variable=tk.StringVar.__new__(tk.StringVar);variable._tk=interpreter;variable._name='editor_value';variable._tclCommands=None
        release_variables([variable])
        with ThreadPoolExecutor(max_workers=1) as worker:worker.submit(variable.__del__).result()
        self.assertEqual(calls,[main]);self.assertIsNone(variable._tk)

    def test_worker_operation_delivers_on_ui_and_rejects_a_second_operation(self):
        main=threading.get_ident();threads=[];window=Mock()
        window.after.side_effect=lambda *args:self.assertEqual(threading.get_ident(),main)
        failed=Mock();work=ImageWork(window,failed);entered=threading.Event();release=threading.Event()
        def calculate():threads.append(threading.get_ident());entered.set();release.wait(2);return 'image'
        received=[]
        self.assertTrue(work.submit(calculate,lambda result:received.append((result,threading.get_ident()))))
        self.assertTrue(entered.wait(1))
        self.assertFalse(work.submit(lambda:'second',Mock()))
        self.assertEqual(received,[])
        release.set();work.future.result(timeout=2)
        window.after.call_args.args[1]()
        self.assertEqual(received,[('image',main)])
        self.assertNotEqual(threads[0],main)
        self.assertIsNone(work.future);failed.assert_not_called();work.close()

    def test_closed_editor_defers_source_release_and_discards_pending_result(self):
        window=Mock();done=Mock();failed=Mock();work=ImageWork(window,failed)
        entered=threading.Event();release=threading.Event();released=threading.Event()
        image=Image.new('RGB',(8,8))
        def calculate():entered.set();release.wait(2);return image
        work.submit(calculate,done);self.assertTrue(entered.wait(1))
        work.close(released.set)
        self.assertFalse(released.is_set())
        release.set();self.assertTrue(released.wait(1))
        with self.assertRaises(ValueError):image.getpixel((0,0))
        window.after.call_args.args[1]();done.assert_not_called();failed.assert_not_called()

    def test_failed_editor_operation_releases_busy_slot_for_retry(self):
        window=Mock();failed=Mock();work=ImageWork(window,failed)
        def broken():raise OSError('bad image')
        work.submit(broken,Mock())
        with self.assertRaises(OSError):work.future.result(timeout=2)
        window.after.call_args.args[1]()
        failed.assert_called_once();self.assertIsNone(work.future)
        done=Mock();self.assertTrue(work.submit(lambda:'retry',done))
        work.future.result(timeout=2);window.after.call_args.args[1]()
        done.assert_called_once_with('retry');work.close()

    def test_full_resolution_edit_keeps_original_and_preview_independent(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'original.png'
            Image.new('RGB',(3000,2000),'red').save(path)
            original=path.read_bytes();source,preview=load_editor_image(path)
            self.assertEqual(source.size,(3000,2000));self.assertLessEqual(max(preview.size),1280)
            result=rendered_edit(source,{'rotation':90,'mirror':False},'1:1',
                                 {'brightness':.5,'contrast':1,'saturation':1},[])
            self.assertEqual(result.size,(2000,2000));self.assertEqual(result.getpixel((0,0)),(127,0,0))
            self.assertEqual(source.size,(3000,2000));self.assertEqual(path.read_bytes(),original)
            result.close();source.close();preview.close()


class GalleryTests(unittest.TestCase):
    def test_thousands_of_shared_photos_only_create_visible_tiles(self):
        canvas=Mock();canvas.canvasy.side_effect=lambda y:y;canvas.winfo_height.return_value=400
        grid=NS(winfo_exists=lambda:True,winfo_viewable=lambda:True,canvas=canvas,columns=4,cell=164,
            documents=[NS(id=i) for i in range(5000)],photos=OrderedDict(),selected=None,_cells={},load=Mock())
        StickerGrid.paint(grid)
        self.assertEqual(len(grid._cells),16)
        self.assertEqual(canvas.create_rectangle.call_count,16)
        canvas.reset_mock()
        for _ in range(100):StickerGrid.paint(grid)
        canvas.create_rectangle.assert_not_called();canvas.delete.assert_not_called()
        grid.winfo_viewable=lambda:False;grid.load.reset_mock();StickerGrid.paint(grid)
        grid.load.assert_not_called()

    def test_more_preserves_existing_tiles_and_does_not_restart_thumbnail_work(self):
        grid=NS(documents=[NS(id=i) for i in range(50)],layout=Mock(),set_documents=Mock())
        for total in range(100,501,50):SharedPhotoGrid.set_messages(grid,[NS(id=i) for i in range(total)])
        self.assertEqual(len(grid.documents),500)
        self.assertEqual(grid.layout.call_count,9)
        grid.set_documents.assert_not_called()
        SharedPhotoGrid.set_messages(grid,[NS(id=999)])
        grid.set_documents.assert_called_once()

    def test_closed_picker_cancels_owned_requests_and_releases_visible_art(self):
        jobs=[Mock(),Mock()]
        grid=NS(_loads=dict(enumerate(jobs)),pending={1,2},version=0,_wanted={1},repaint=Mock(),
                photos={1:object()},_cells={1:object()})
        grid.cancel_loads=lambda:StickerGrid.cancel_loads(grid)
        StickerGrid.closed(grid,NS(widget=grid))
        self.assertFalse(grid.pending);self.assertFalse(grid.photos);self.assertFalse(grid._loads)
        for job in jobs:job.cancel.assert_called_once()

    def test_shared_browser_closure_cancels_searches_across_categories(self):
        jobs={'photos':Mock(),'files':Mock()}
        browser=NS(window=object(),_requests=jobs.copy(),pages=NS(pending={'photos':1,'files':2}))
        SharedMediaBrowser.close(browser,NS(widget=object()))
        self.assertEqual(len(browser._requests),2)
        SharedMediaBrowser.close(browser,NS(widget=browser.window))
        self.assertFalse(browser._requests);self.assertFalse(browser.pages.pending)
        for job in jobs.values():job.cancel.assert_called_once()


class GalleryDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_embedded_metadata_cache_is_bounded_by_bytes_and_large_result_still_delivered(self):
        documents=[NS(id=index,attributes=[],thumbs=[NS(bytes=bytes(600))]) for index in range(8)]
        backend=NS(client=AsyncMock(return_value=documents))
        catalogue=EmojiDocuments(backend)
        with patch('tg_ascii.emoji_documents.MAX_DOCUMENT_CACHE_BYTES',4000):
            self.assertEqual(await catalogue.get(range(8)),documents)
            self.assertLessEqual(catalogue.cache_bytes,4000)
            self.assertLess(len(catalogue.cache),8)
            huge=NS(id=99,attributes=[],thumbs=[NS(bytes=bytes(8000))])
            backend.client.return_value=[huge]
            self.assertEqual(await catalogue.get([99]),[huge])
            self.assertNotIn(99,catalogue.cache)
        await catalogue.cancel()
        self.assertEqual(catalogue.cache_bytes,0)
        self.assertFalse(catalogue._costs)

    async def test_existing_thumbnail_is_prepared_in_worker_without_redownload(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'a-42-1-mosaic.jpg';path.write_bytes(b'cached thumbnail')
            player=NS(prepare=Mock(return_value=('frames','durations')),photo=Mock(return_value=object()))
            backend=NS(download_media=AsyncMock())
            app=NS(ui_account='a',preview_slots=asyncio.Semaphore(2),preview_cache={},preview_dir=root,
                   animation_player=player,worker=Mock())
            grid=NS(version=0,pending=set(),failed=set(),account='a',peer=42,app=app,backend=backend,
                    _wanted={1},_loads={},winfo_exists=lambda:True,repaint=Mock(),photos={})
            SharedPhotoGrid.load(grid,NS(id=1,media=object()))
            coroutine,ready,_=app.worker.submit.call_args.args
            result=await coroutine;ready(result)
            backend.download_media.assert_not_awaited()
            player.prepare.assert_called_once_with(path,(150,150),False)
            self.assertIn(1,grid.photos);self.assertFalse(grid.pending)
            self.assertEqual(app.preview_cache[('a',42,1,'mosaic')],path)


class PreviewWorkTests(unittest.TestCase):
    def test_short_preview_only_consumes_required_clusters(self):
        class CountedText(str):
            scanned=0
            def __iter__(self):
                for value in super().__iter__():self.scanned+=1;yield value
        text=CountedText('a'*100000)
        self.assertEqual(list(preview_runs(text,limit=120)),[('a'*120+'…',None)])
        self.assertLessEqual(text.scanned,121)

    def test_lazy_and_list_boundaries_keep_joined_emoji_and_combining_sequences(self):
        text='👨‍👩‍👧‍👦🇪🇸á\r\n👍🏽'
        expected=[7,9,11,13,15]
        self.assertEqual(cluster_ends(text),expected)
        self.assertEqual(list(iter_cluster_ends(text)),expected)
        self.assertEqual(list(preview_runs(text,limit=2)),[(text[:9]+'…',None)])


if __name__=='__main__':unittest.main()
