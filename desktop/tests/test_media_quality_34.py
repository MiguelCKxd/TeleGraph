import asyncio
import hashlib
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

from PIL import Image
from telethon import types
from tg_ascii.media_quality import photo_paths, photo_variant
from tg_ascii.message_tools import MessageTools
from tg_ascii.telegram_actions import TelegramActions


class UploadQualityTests(unittest.IsolatedAsyncioTestCase):
    async def test_mixed_album_prepares_only_photo_and_preserves_video_order(self):
        from tg_ascii.backend import TelegramBackend
        from tests.test_forum_topics_33 import Telegram, PEER
        import io
        with tempfile.TemporaryDirectory() as folder:
            photo=Path(folder)/'photo.jpg';video=Path(folder)/'clip.mp4'
            Image.new('RGB',(3200,1800),'red').save(photo)
            video.write_bytes(b'unchanged video')
            captured=[]
            async def send(peer,streams,**options):
                captured.append(([stream.read() for stream in streams],options));return []
            backend=MessageTools();backend.client=NS(send_file=AsyncMock(side_effect=send));backend.message=lambda m:m
            for quality in ('sd','original'):
                await backend.send_batch(42,[video,photo],'caption',photo_quality=quality)
            self.assertFalse(captured[0][1]['force_document'])
            self.assertEqual(captured[0][0][0],video.read_bytes())
            with Image.open(io.BytesIO(captured[0][0][1])) as image:self.assertEqual(image.size,(1280,720))
            self.assertTrue(captured[1][1]['force_document'])
            self.assertEqual(captured[1][0],[video.read_bytes(),photo.read_bytes()])
            api=Telegram();backend=TelegramBackend(api)
            await backend.forum_send(PEER,10,paths=[video,photo],photo_quality='sd')
            self.assertEqual([options['force_document'] for options in api.upload_opts],[False,False])

    async def test_sd_hd_keep_orientation_and_original_is_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'camera.jpg'
            image = Image.new('RGB', (4000, 3000), 'red')
            exif = Image.Exif(); exif[274] = 6
            image.save(source, exif=exif); image.close()
            original = hashlib.sha256(source.read_bytes()).hexdigest()
            for quality, expected in [('sd', (960, 1280)), ('hd', (1920, 2560))]:
                async with photo_paths([source], quality) as files:
                    generated = files[0]
                    self.assertNotEqual(generated, source)
                    with Image.open(generated) as result:
                        self.assertEqual(result.size, expected)
                        self.assertNotEqual(result.getexif().get(274), 6)
                self.assertFalse(generated.exists())
            async with photo_paths([source], 'original') as files:
                self.assertEqual(files, [source])
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original)

    async def test_original_sends_bytes_as_document_hd_as_photo(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'camera.png'
            Image.new('RGB', (3200, 1800), 'blue').save(source)
            captured = []
            async def send(peer, stream, **kwargs):
                captured.append((stream.read(), kwargs))
                return 'message'
            backend = MessageTools()
            backend.client = NS(send_file=AsyncMock(side_effect=send))
            backend.message = lambda message: message
            for quality in ('original', 'hd'):
                await backend.send_formatted(1, 'caption', [], path=source, as_photo=True,
                                             reply_to=7, photo_quality=quality)
            self.assertEqual(captured[0][0], source.read_bytes())
            self.assertTrue(captured[0][1]['force_document'])
            self.assertFalse(captured[1][1]['force_document'])
            self.assertEqual(captured[1][1]['reply_to'], 7)
            self.assertEqual(captured[1][1]['caption'], 'caption')
            import io
            with Image.open(io.BytesIO(captured[1][0])) as image:
                self.assertEqual(image.size, (2560, 1440))

    async def test_cancelled_worker_cannot_recreate_deleted_temporary(self):
        entered = threading.Event(); release = threading.Event(); targets = []
        def prepare(source, target, quality):
            targets.append(target); entered.set(); release.wait(2); target.write_bytes(b'finished')
        async def prepare_and_use():
            async with photo_paths(['source.jpg'], 'sd'):
                self.fail('Cancelled upload must never start')
        with patch('tg_ascii.media_quality._prepare_photo', prepare):
            task = asyncio.create_task(prepare_and_use())
            await asyncio.to_thread(entered.wait, 1)
            task.cancel(); await asyncio.sleep(0); task.cancel(); await asyncio.sleep(0)
            self.assertTrue(targets[0].parent.exists())
            release.set()
            with self.assertRaises(asyncio.CancelledError): await task
        self.assertFalse(targets[0].exists())


class DisplayQualityTests(unittest.TestCase):
    def test_quality_survives_local_draft_restart_without_dirtying_cloud_content(self):
        from tg_ascii.drafts import DraftStore, draft_content, valid_record
        with tempfile.TemporaryDirectory() as folder:
            store=DraftStore(folder)
            base={'text':'caption','files':['photo.jpg']}
            store.put('a',42,base,pending=False)
            store.put('a',42,{**base,'photo_quality':'hd'})
            self.assertFalse(store.get('a',42)['pending'])
            self.assertEqual(draft_content(store.get('a',42)),draft_content(valid_record(base)))
            store.flush();restored=DraftStore(folder)
            self.assertIsNone(restored.load_error)
            self.assertEqual(restored.get('a',42)['photo_quality'],'hd')
        self.assertNotIn('photo_quality',valid_record(base))
        self.assertNotIn('photo_quality',valid_record({**base,'photo_quality':'bad'}))

    def test_uses_server_variant_without_reencoding_and_ignores_video(self):
        photo = types.Photo(10, 11, b'ref', None, [
            types.PhotoSize('m', 320, 240, 100), types.PhotoSize('x', 1280, 960, 900),
            types.PhotoSize('y', 2560, 1920, 1600)], 2)
        self.assertEqual(photo_variant(types.MessageMediaPhoto(photo=photo)), 'x')
        self.assertEqual(photo_variant(photo, 3000), 'y')
        self.assertIsNone(photo_variant(NS(document=NS(sizes=photo.sizes))))

    def test_video_retains_only_viewport_bitmap_and_zoom_uses_original_frame(self):
        import av
        from tg_ascii.video_frames import VideoFrames
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'clip.mp4'
            with av.open(str(path),'w') as output:
                stream=output.add_stream('mpeg4',rate=25)
                stream.width=640;stream.height=360;stream.pix_fmt='yuv420p'
                frame=av.VideoFrame.from_image(Image.new('RGB',(640,360),'blue'))
                for packet in stream.encode(frame):output.mux(packet)
                for packet in stream.encode():output.mux(packet)
            source=VideoFrames(path)
            try:
                source.viewport((80,60));small=source.get(0)
                self.assertEqual(small.size,(80,45))
                decoded=source.decoded
                source.viewport((80,60),8);full=source.get(0)
                self.assertEqual(full.size,(640,360))
                self.assertEqual(source.decoded,decoded)
                self.assertGreater(full.getpixel((200,200))[2],230)
                with self.assertRaises(ValueError):small.getpixel((0,0))
            finally:source.close()


class SearchFilterTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_filter_goes_to_server_with_its_own_cursor(self):
        backend = TelegramActions()
        backend.client = NS(get_messages=AsyncMock(return_value=[]))
        backend.resolve_missing_senders = AsyncMock()
        expected = {'media': types.InputMessagesFilterPhotoVideo,
                    'photos': types.InputMessagesFilterPhotos, 'videos': types.InputMessagesFilterVideo}
        for key, kind in expected.items():
            await backend.search_messages(42, 'caption', key, 81)
            options = backend.client.get_messages.call_args.kwargs
            self.assertIsInstance(options['filter'], kind)
            self.assertEqual(options['offset_id'], 81)
            self.assertEqual(options['search'], 'caption')

    async def test_viewer_keeps_filter_and_query_and_batches_adjacent_metadata(self):
        from tg_ascii.media_gallery import ChatSource, GalleryItem
        rows = [NS(id=i, media=f'video-{i}', media_kind='video', text='holiday', filename=f'{i}.mp4')
                for i in range(100, 0, -1)]
        async def search(peer, **options):
            selected = [row for row in rows if row.id < options['max_id']]
            return selected[:options['limit']]
        backend = NS(client=NS(get_messages=AsyncMock(side_effect=search)), message=lambda value:value)
        source = ChatSource(backend, 42, 'videos', 'holiday')
        selected = GalleryItem(101, None)
        for expected in range(100, 60, -1):
            selected = await source.neighbor(selected, 1)
            self.assertEqual(selected.ident, expected)
        self.assertEqual(backend.client.get_messages.await_count, 2)
        for call in backend.client.get_messages.call_args_list:
            self.assertIsInstance(call.kwargs['filter'], types.InputMessagesFilterVideo)
            self.assertEqual(call.kwargs['search'], 'holiday')
        self.assertEqual((await source.neighbor(selected, -1)).ident, 62)
        self.assertEqual(backend.client.get_messages.await_count, 2)
        self.assertLessEqual(len(source.neighbors), 120)

    async def test_saved_outbox_quality_reaches_albums_and_forum_without_changing_reply(self):
        from dataclasses import asdict
        from tg_ascii.outbox import Pending, build_operation
        backend = NS(send_batch=AsyncMock(), forum_send=AsyncMock())
        item = Pending('account', 42, paths=['a.jpg', 'b.png'], reply_to=18, photo_quality='hd')
        restored = Pending(**asdict(item))
        await build_operation(backend, restored)
        self.assertEqual(backend.send_batch.call_args.kwargs['photo_quality'], 'hd')
        self.assertEqual(backend.send_batch.call_args.kwargs['reply_to'], 18)
        restored.topic_id = 10
        await build_operation(backend, restored)
        self.assertEqual(backend.forum_send.call_args.args[:2], (42, 10))
        self.assertEqual(backend.forum_send.call_args.kwargs['photo_quality'], 'hd')
        self.assertEqual(backend.forum_send.call_args.kwargs['reply_to'], 18)


if __name__ == '__main__': unittest.main()
