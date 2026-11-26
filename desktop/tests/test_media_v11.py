"""Real decoder fixtures and network/lifecycle regressions for media in 1.1."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock,Mock,patch

from PIL import Image
from telethon import types
from telethon.errors import FileReferenceExpiredError

from tg_ascii.animation import decode_frames,emoji_file,render_animation
from tg_ascii.desktop_modern import DesktopModern
from tg_ascii.emoji_documents import catalogue
from tg_ascii.media_formats import download_name,is_animation,preview_available,thumbnail_preview
from tg_ascii.media_gallery import ChatSource,GalleryItem,MediaGallery,ProfileSource
from tg_ascii.media_retry import failed_recently,remember_failure,grid_failed_recently,remember_grid_failure,retry_visible_art,clear_art_retry
from tg_ascii.media_viewer import ImageFrames
from tg_ascii.profile_media import compose_profile,photo_markup,prepare_profile_photo,profile_history


def photo(ident=7,markup=None,sizes=()):
    return types.Photo(ident,0,b'',None,list(sizes),1,video_sizes=[markup] if markup else [])


def tgs_fixture(path):
    data={'v':'5.7.4','fr':30,'ip':0,'op':30,'w':512,'h':512,'assets':[],
          'layers':[{'ty':4,'ind':1,'ip':0,'op':30,'st':0,'ks':{'o':{'a':0,'k':100},
              'r':{'a':0,'k':0},'p':{'a':0,'k':[256,256,0]},'a':{'a':0,'k':[0,0,0]},'s':{'a':0,'k':[100,100,100]}},
              'shapes':[{'ty':'el','p':{'a':0,'k':[0,0]},'s':{'a':0,'k':[300,300]}},
                        {'ty':'fl','c':{'a':0,'k':[1,0,0,1]},'o':{'a':0,'k':100}}]}]}
    with gzip.open(path,'wb') as target:target.write(json.dumps(data).encode())
    return path


def video_fixture(path,frames=12,rate=25):
    import av
    with av.open(str(path),'w',format='mp4') as output:
        stream=output.add_stream('mpeg4',rate=rate);stream.width=32;stream.height=24;stream.pix_fmt='yuv420p'
        for index in range(frames):
            image=Image.new('RGB',(32,24),'red' if index%2==0 else 'blue')
            try:frame=av.VideoFrame.from_image(image)
            finally:image.close()
            for packet in stream.encode(frame):output.mux(packet)
        for packet in stream.encode():output.mux(packet)
    return path


class FormatTests(unittest.TestCase):
    def test_corrupt_later_animation_frame_releases_previously_decoded_bitmaps(self):
        frame=Image.new('RGBA',(8,8),'red')
        source=Mock(width=8,height=8,n_frames=2,info={})
        source.seek.side_effect=[None,OSError('corrupt second frame')]
        source.convert.return_value=frame
        with patch('PIL.Image.open',return_value=source),patch.object(type(source),'__enter__',lambda self:self,create=True),patch.object(type(source),'__exit__',lambda *args:None,create=True):
            with self.assertRaises(OSError):decode_frames('corrupt.gif',(8,8))
        with self.assertRaises(ValueError):frame.getpixel((0,0))

    def test_telegram_mp4_gif_is_full_animation_but_regular_video_uses_preview(self):
        animated=NS(document=NS(mime_type='video/mp4',attributes=[types.DocumentAttributeAnimated()]))
        video=NS(document=NS(mime_type='video/mp4',attributes=[]))
        self.assertTrue(is_animation(animated));self.assertFalse(thumbnail_preview(animated,'video'))
        self.assertTrue(thumbnail_preview(video,'video'))
        self.assertTrue(preview_available(NS(),'file','image.HEIC'))
        self.assertFalse(preview_available(NS(),'file','program.exe'))

    def test_download_filename_preserves_extension_without_cache_account_information(self):
        self.assertEqual(download_name(types.MessageMediaPhoto(photo=photo())),'photo.jpg')
        self.assertEqual(download_name(NS(),'../../private\\avatar.avif'),'avatar.avif')
        self.assertEqual(download_name(NS(),''),'attachment.bin')

    def test_raster_formats_preserve_orientation_and_original_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            for suffix,format in (('webp','WEBP'),('avif','AVIF'),('tiff','TIFF'),('gif','GIF')):
                with self.subTest(format=format):
                    path=Path(directory)/('art.'+suffix)
                    image=Image.new('RGB',(24,16),'red');image.save(path,format=format);image.close()
                    before=hashlib.sha256(path.read_bytes()).digest()
                    source=ImageFrames(path)
                    try:self.assertEqual(source.get(0).size,(24,16));self.assertIs(source.get(0),source.get(0))
                    finally:source.close()
                    self.assertEqual(hashlib.sha256(path.read_bytes()).digest(),before)

    @unittest.skipUnless(importlib.util.find_spec('av'),'Optional PyAV renderer is unavailable')
    def test_mp4_gif_real_decoder_retains_one_frame_loops_and_releases_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path=video_fixture(Path(directory)/'telegram-gif.media')
            source=ImageFrames(path)
            try:
                self.assertEqual(source.count,12)
                first=source.get(0);self.assertGreater(first.getpixel((8,8))[0],230)
                self.assertIs(source.get(0),first)
                second=source.get(1);self.assertGreater(second.getpixel((8,8))[2],230)
                with self.assertRaises(ValueError):first.getpixel((0,0))
                for index in range(2,12):source.get(index)
                self.assertGreater(source.get(0).getpixel((8,8))[0],230)
            finally:source.close();source.close()
            path.unlink()

    @unittest.skipUnless(importlib.util.find_spec('av'),'Optional PyAV renderer is unavailable')
    def test_video_downsamples_playback_without_changing_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            source=ImageFrames(video_fixture(Path(directory)/'fast.mp4',frames=60,rate=60))
            try:
                self.assertEqual(source.count,20)
                self.assertEqual(source.image.info['duration'],50)
                for index in range(source.count):source.get(index)
            finally:source.close()

    @unittest.skipUnless(importlib.util.find_spec('av'),'Optional PyAV renderer is unavailable')
    def test_unknown_video_count_is_corrected_at_eof(self):
        with tempfile.TemporaryDirectory() as directory:
            source=ImageFrames(video_fixture(Path(directory)/'loop.mp4',frames=3))
            try:
                source.video.count=1_000_000
                for index in range(4):source.get(index)
                self.assertEqual(source.count,3);self.assertEqual(source.video.index,0)
            finally:source.close()

    @unittest.skipUnless(importlib.util.find_spec('av'),'Optional PyAV renderer is unavailable')
    def test_inline_mp4_gif_decodes_bounded_frames_and_static_setting_is_respected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=video_fixture(Path(directory)/'gif.jpg',frames=12)
            frames,durations=decode_frames(path,(320,240))
            try:
                self.assertEqual(len(frames),12);self.assertEqual(durations,[40]*12)
                self.assertTrue(all(max(frame.size)<=128 for frame in frames))
            finally:
                for frame in frames:frame.close()
            frames,_=decode_frames(path,(320,240),animated=False)
            try:self.assertEqual(len(frames),1)
            finally:frames[0].close()


class PreviewRetryTests(unittest.TestCase):
    def test_visible_art_recovery_coalesces_new_views_and_discards_stale_listeners(self):
        app=NS(root=Mock(),preview_failed=set(),fetch_art=Mock())
        old=Mock();old.media_valid=Mock(return_value=True)
        new=Mock();new.media_valid=Mock(return_value=True)
        operation=Mock()
        retry_visible_art(app,'emoji',operation,[old])
        old.media_valid.return_value=False
        retry_visible_art(app,'emoji',operation,[new])
        app.root.after.assert_called_once()
        app.root.after.call_args.args[1]()
        app.fetch_art.assert_called_once_with('emoji',operation,new,valid=new.media_valid)
        # 1.4.1: a few spaced retries (15/30/60/120 s), never a perpetual timer.
        from tg_ascii.media_retry import RETRY_DELAYS
        for _ in range(len(RETRY_DELAYS)+3):
            retry_visible_art(app,'emoji',operation,[new])
            if app.root.after.call_args.args[1] is not None:app.root.after.call_args.args[1]()
        self.assertEqual(app.root.after.call_count,len(RETRY_DELAYS))
        self.assertEqual([call.args[0] for call in app.root.after.call_args_list],list(RETRY_DELAYS))

    def test_success_cancels_retry_and_retry_timer_retention_is_bounded(self):
        app=NS(root=Mock(),preview_failed=set(),fetch_art=Mock())
        listener=Mock();listener.media_valid=lambda:True
        for key in range(140):retry_visible_art(app,key,Mock(),[listener])
        self.assertEqual(len(app._art_retries),128)
        self.assertEqual(app.root.after_cancel.call_count,12)
        clear_art_retry(app,139)
        self.assertNotIn(139,app._art_retries);self.assertNotIn(139,app._art_retry_used)
        self.assertEqual(app.root.after_cancel.call_count,13)

    def test_fetch_art_failed_request_retries_current_view_then_cancels_pending_timer(self):
        app=NS(root=Mock(),worker=Mock(),preview_failed=set(),preview_cache={},media_requests={})
        app.fetch_art=lambda *args,**kwargs:DesktopModern.fetch_art(app,*args,**kwargs)
        callback=Mock();operation=Mock(return_value=object())
        app.fetch_art('a',operation,callback,valid=lambda:True)
        app.worker.submit.call_args.args[2](OSError('temporary outage'))
        callback.assert_called_once_with(None)
        retry=app.root.after.call_args.args[1]
        retry()
        self.assertEqual(app.worker.submit.call_count,2)
        app.worker.submit.call_args.args[1]('cached.webp')
        self.assertEqual(app.preview_cache['a'],'cached.webp')
        self.assertNotIn('a',app._art_retry_used)
        callback.assert_called_with('cached.webp')

    def test_failed_preview_recovers_after_backoff_without_unbounded_negative_cache(self):
        app=NS(preview_failed=set())
        with patch('tg_ascii.media_retry.time.monotonic',return_value=100):
            remember_failure(app,'a');self.assertTrue(failed_recently(app,'a'))
        with patch('tg_ascii.media_retry.time.monotonic',return_value=116):self.assertFalse(failed_recently(app,'a'))
        for ident in range(1100):remember_failure(app,ident)
        self.assertEqual(len(app.preview_failed),1024)
        self.assertEqual(len(app._preview_failure_times),1024)

    def test_visible_grid_retries_once_and_hidden_grid_does_not_repaint(self):
        grid=NS(failed=set(),after=Mock(return_value='timer'),winfo_exists=lambda:True,winfo_viewable=lambda:True,repaint=Mock())
        with patch('tg_ascii.media_retry.time.monotonic',return_value=100):
            remember_grid_failure(grid,4);self.assertTrue(grid_failed_recently(grid,4))
            callback=grid.after.call_args.args[1]
        with patch('tg_ascii.media_retry.time.monotonic',return_value=116):
            callback();grid.repaint.request.assert_called_once();self.assertFalse(grid_failed_recently(grid,4))
            remember_grid_failure(grid,4);grid.after.assert_called_once()
        grid.winfo_viewable=lambda:False;callback();grid.repaint.request.assert_called_once()

    def test_status_click_works_before_art_and_old_status_cannot_open_other_account_pack(self):
        widget=Mock();app=NS(ui_account='a',busy=False,emoji_art=Mock(),show_document_pack=Mock())
        DesktopModern.label_emoji(app,widget,7,'a',None)
        callbacks={call.args[0]:call.args[1] for call in widget.bind.call_args_list}
        callbacks['<ButtonRelease-1>']();app.show_document_pack.assert_called_once_with(7)
        app.ui_account='b';callbacks['<Return>']();app.show_document_pack.assert_called_once()


class EmojiReadTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(importlib.util.find_spec('rlottie_python'),'Optional TGS renderer is unavailable')
    async def test_animation_disabled_still_shows_tgs_without_thumbnail(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);source=tgs_fixture(folder/'input.tgs')
            document=NS(id=9,mime_type='application/x-tgsticker',size=source.stat().st_size)
            async def download(document,target,thumbnail=False):
                if thumbnail:raise ValueError('No raster thumbnail')
                shutil.copyfile(source,target);return target
            backend=NS(download_media=AsyncMock(side_effect=download))
            app=NS(preview_dir=folder,preferences=NS(values={'animated_emoji':False}))
            output=await emoji_file(app,document,'a',backend)
            with Image.open(output) as image:
                self.assertEqual(image.size,(128,128));self.assertEqual(image.n_frames,1)
                self.assertGreater(image.getpixel((64,64))[0],230)
            await emoji_file(app,document,'a',backend)
            self.assertEqual(backend.download_media.await_count,2)

    async def test_expired_emoji_reference_refreshes_metadata_once(self):
        old=NS(id=5,attributes=[types.DocumentAttributeCustomEmoji('x',types.InputStickerSetEmpty())])
        fresh=NS(id=5,attributes=old.attributes)
        backend=NS(client=AsyncMock(return_value=[fresh]))
        catalogue(backend).remember([old])
        app=NS(preferences=NS(values={'animated_emoji':True}))
        with patch('tg_ascii.animation._emoji_file',new_callable=AsyncMock,side_effect=[FileReferenceExpiredError(None),__file__]) as loader:
            result=await emoji_file(app,old,'a',backend)
        self.assertEqual(result,__file__);self.assertIs(loader.call_args.args[1],fresh)
        backend.client.assert_awaited_once()

    async def test_expired_reference_is_never_retried_without_bound(self):
        document=NS(id=5,attributes=[types.DocumentAttributeCustomEmoji('x',types.InputStickerSetEmpty())])
        backend=NS(client=AsyncMock(return_value=[document]));app=NS(preferences=NS(values={'animated_emoji':True}))
        with patch('tg_ascii.animation._emoji_file',new_callable=AsyncMock,side_effect=FileReferenceExpiredError(None)) as loader:
            with self.assertRaises(FileReferenceExpiredError):await emoji_file(app,document,'a',backend)
        self.assertEqual(loader.await_count,2);backend.client.assert_awaited_once()


class ProfileMediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_raster_is_preferred_and_markup_is_not_passed_to_file_downloader(self):
        with tempfile.TemporaryDirectory() as directory:
            value=photo(markup=types.VideoSizeEmojiMarkup(6,[0xff0000]),sizes=[types.PhotoSize('x',800,800,12)])
            backend=NS(download_media=AsyncMock(return_value=Path(directory)/'native.jpg'),custom_emoji_documents=AsyncMock())
            result=await prepare_profile_photo(NS(preview_dir=Path(directory)),backend,'a',42,value)
            self.assertEqual(result.suffix,'.jpg');backend.custom_emoji_documents.assert_not_awaited()
            sent=backend.download_media.call_args.args[0]
            self.assertFalse(sent.video_sizes);self.assertTrue(value.video_sizes)

    @unittest.skipUnless(importlib.util.find_spec('rlottie_python'),'Optional TGS renderer is unavailable')
    async def test_markup_only_avatar_renders_transparent_emoji_on_native_background(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);source=tgs_fixture(folder/'art.tgs')
            value=photo(markup=types.VideoSizeEmojiMarkup(6,[0x123456]))
            document=NS(id=6,mime_type='application/x-tgsticker',size=source.stat().st_size)
            async def download(document,target):shutil.copyfile(source,target);return target
            backend=NS(download_media=AsyncMock(side_effect=download),custom_emoji_documents=AsyncMock(return_value=[document]))
            app=NS(preview_dir=folder)
            output=await prepare_profile_photo(app,backend,'a',42,value,thumbnail=True)
            with Image.open(output) as image:
                self.assertEqual(image.size,(160,160));self.assertEqual(image.getpixel((0,0)),(18,52,86,255))
                self.assertEqual(image.getpixel((80,80)),(255,0,0,255))
            self.assertEqual(await prepare_profile_photo(app,backend,'a',42,value,thumbnail=True),output)
            backend.custom_emoji_documents.assert_awaited_once();backend.download_media.assert_awaited_once()

    async def test_sticker_markup_resolves_exact_document_in_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);symbol=folder/'source.webp';Image.new('RGBA',(20,20),'red').save(symbol)
            markup=types.VideoSizeStickerMarkup(types.InputStickerSetID(1,2),8,[0,0xffffff])
            doc=NS(id=8,mime_type='image/webp',size=symbol.stat().st_size)
            async def download(document,target):shutil.copyfile(symbol,target);return target
            backend=NS(client=AsyncMock(return_value=NS(documents=[NS(id=3),doc])),download_media=AsyncMock(side_effect=download))
            target=await prepare_profile_photo(NS(preview_dir=folder),backend,'a',42,photo(markup=markup))
            self.assertEqual(target.suffix,'.png');self.assertIs(backend.download_media.call_args.args[0],doc)
            self.assertIs(photo_markup(photo(markup=markup)),markup)

    async def test_photo_history_has_bounded_page_and_filters_empty_photos(self):
        result=[photo(1),types.PhotoEmpty(2)]
        backend=NS(client=NS(get_profile_photos=AsyncMock(return_value=result)))
        found,total=await profile_history(backend,42,-8,500)
        self.assertEqual([item.id for item in found],[1]);self.assertIsNone(total)
        backend.client.get_profile_photos.assert_awaited_once_with(42,offset=0,limit=40)

    async def test_native_video_profile_uses_video_extension_but_thumbnail_remains_jpeg(self):
        with tempfile.TemporaryDirectory() as directory:
            value=photo(markup=types.VideoSize('u',800,800,50))
            backend=NS(download_media=AsyncMock(side_effect=lambda photo,path,thumbnail=False:path))
            app=NS(preview_dir=Path(directory))
            self.assertEqual((await prepare_profile_photo(app,backend,'a',42,value)).suffix,'.mp4')
            self.assertEqual((await prepare_profile_photo(app,backend,'a',42,value,True)).suffix,'.jpg')


class OriginalThumbnailTests(unittest.IsolatedAsyncioTestCase):
    async def test_small_gif_and_avif_without_thumbnail_are_downloaded_atomically(self):
        from tg_ascii.telegram_features import TelegramFeatures
        async def download(media,file,**kwargs):file.write(b'data');return file
        owner=NS(client=NS(download_media=AsyncMock(side_effect=download)))
        with tempfile.TemporaryDirectory() as directory:
            for mime,attributes in (('image/gif',[]),('image/avif',[]),('video/mp4',[types.DocumentAttributeAnimated()])):
                document=types.Document(1,0,b'',None,mime,4,1,attributes)
                target=Path(directory)/'preview'
                result=await TelegramFeatures.download_media(owner,document,target,thumbnail=True)
                self.assertEqual(Path(result).read_bytes(),b'data')
            self.assertEqual(owner.client.download_media.await_count,3)

    async def test_automatic_original_fallback_stays_limited_to_four_mib(self):
        from tg_ascii.telegram_features import TelegramFeatures
        owner=NS(client=NS(download_media=AsyncMock()))
        with tempfile.TemporaryDirectory() as directory:
            for mime,attributes in (('image/gif',[]),('video/mp4',[types.DocumentAttributeAnimated()]),('image/svg+xml',[])):
                document=types.Document(1,0,b'',None,mime,4*1024*1024+1,1,attributes)
                with self.assertRaises(ValueError):
                    await TelegramFeatures.download_media(owner,document,Path(directory)/'preview.jpg',thumbnail=True)
            owner.client.download_media.assert_not_awaited()


class GalleryTests(unittest.IsolatedAsyncioTestCase):
    async def test_profile_history_navigates_all_pages_with_three_retained_pages(self):
        async def records(peer,offset,limit):return [photo(i) for i in range(offset,min(offset+limit,101))]
        backend=NS(client=NS(get_profile_photos=AsyncMock(side_effect=records)))
        source=ProfileSource(backend,42,photo(0),'Example')
        for index in (0,20,40,60,80,100):self.assertEqual((await source.at(index)).ident,index)
        self.assertEqual(len(source.pages),3)
        self.assertIsNone(await source.at(101));self.assertIsNone(await source.at(-1))
        self.assertEqual((await source.at(0)).ident,0)

    async def test_personal_override_precedes_public_photos_without_duplicates(self):
        backend=NS(client=NS(get_profile_photos=AsyncMock(return_value=[photo(3),photo(2)])))
        source=ProfileSource(backend,42,photo(9),'Example')
        self.assertEqual([(await source.at(index)).ident for index in range(3)],[9,3,2])
        self.assertIsNone(await source.at(3));backend.client.get_profile_photos.assert_awaited_once()

    async def test_chat_navigation_requests_bounded_metadata_without_loading_entire_chat(self):
        message=NS(id=4,media='photo',text='caption',filename='')
        backend=NS(client=NS(get_messages=AsyncMock(return_value=[message])),message=lambda value:value)
        source=ChatSource(backend,42);item=GalleryItem(5,None)
        self.assertEqual((await source.neighbor(item,1)).ident,4)
        self.assertEqual(backend.client.get_messages.call_args.kwargs['max_id'],5)
        self.assertEqual(backend.client.get_messages.call_args.kwargs['limit'],20)
        await source.neighbor(item,-1)
        self.assertEqual(backend.client.get_messages.call_args.kwargs['min_id'],5)
        self.assertTrue(backend.client.get_messages.call_args.kwargs['reverse'])

    async def test_gallery_cancels_owner_on_close_and_rejects_old_download_result(self):
        requests=Mock();window=Mock();item=GalleryItem(1,None)
        gallery=NS(window=window,requests=requests,item=GalleryItem(2,None),valid=lambda:True)
        MediaGallery.closed(gallery,NS(widget=window));requests.close.assert_called_once()
        MediaGallery.loaded(gallery,'private-cache.media',item);window._set_media.assert_not_called()

    async def test_gallery_download_does_not_take_global_busy_and_refreshes_expired_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            backend=NS(download_media=AsyncMock(side_effect=[FileReferenceExpiredError(None),Path(directory)/'fresh.jpg']),
                       media_message=AsyncMock(return_value='fresh media'))
            gallery=NS(valid=lambda:True,profile=False,app=NS(preview_dir=Path(directory),busy=False,ui_account='a',service=NS(backend=backend)),account='a',peer=42,
                       window=Mock(),expired=Mock(),backend=backend,path=None,requests=Mock(),save_button=Mock(),status=Mock(),loaded=Mock(),failed=Mock())
            gallery.download=lambda *args,**kwargs:MediaGallery.download(gallery,*args,**kwargs)
            item=GalleryItem(7,'old media');MediaGallery.load(gallery,item)
            _,operation,done,_=gallery.requests.submit.call_args.args
            done(await operation)
            self.assertFalse(gallery.app.busy);self.assertEqual(backend.download_media.await_count,2)
            backend.media_message.assert_awaited_once_with(42,7)
            self.assertEqual(backend.download_media.call_args.args[0],'fresh media')
            gallery.lease.close()


class CompositionTests(unittest.TestCase):
    def test_composition_bounds_sticker_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'emoji.png';Image.new('RGBA',(100,100),'red').save(source)
            before=source.read_bytes();target=Path(directory)/'avatar.png'
            compose_profile(source,target,[0x123456],100)
            with Image.open(target) as image:
                self.assertEqual(image.getpixel((16,16)),(255,0,0,255))
                self.assertEqual(image.getpixel((15,15)),(18,52,86,255))
            self.assertEqual(source.read_bytes(),before)

    def test_failed_animation_render_closes_already_decoded_frames(self):
        frames=[]
        def failed(path,target,mime,animated,side,retained):
            frame=Image.new('RGBA',(8,8));retained.append(frame);frames.append(frame)
            raise ValueError('bad second frame')
        with patch('tg_ascii.animation._render_animation',side_effect=failed):
            with self.assertRaises(ValueError):render_animation('x','y','image/gif')
        with self.assertRaises(ValueError):frames[0].getpixel((0,0))
