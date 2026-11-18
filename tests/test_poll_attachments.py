"""Poll upload contracts, cancellation and slow-link deadlines; no accounts."""
import asyncio
import struct
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image
from telethon import functions as f
from telethon import types as t

from tg_ascii.advanced_messaging import AdvancedMessagingMixin, poll_media
from tg_ascii.poll_attachments import (
    inspect_poll_file,
    inspect_poll_files,
    upload_poll_files,
)
from tg_ascii.video_metadata import mp4_metadata


def movie(path, seconds=125):
    def box(kind, data): return struct.pack('>I4s', len(data)+8, kind)+data
    mvhd = b'\0'*12 + struct.pack('>II', 1000, seconds*1000) + b'\0'*12
    tkhd = b'\0'*76 + struct.pack('>II', 720<<16, 1280<<16)
    path.write_bytes(box(b'moov', box(b'mvhd', mvhd) + box(b'trak', box(b'tkhd', tkhd))))


class Backend(AdvancedMessagingMixin):
    def __init__(self):
        self.client = AsyncMock()
        self.client.get_input_entity.return_value = t.InputPeerChat(12)
        self.client.upload_file.return_value = t.InputFile(123, 1, 'synthetic', '')
        self.app_config = AsyncMock(return_value=t.help.AppConfig(0, t.JsonObject([])))
        self.client.side_effect = self.register

    async def register(self, request):
        assert isinstance(request, f.messages.UploadMediaRequest), 'Preparing a poll must never send a message'
        if isinstance(request.media, t.InputMediaUploadedPhoto):
            return t.MessageMediaPhoto(photo=t.Photo(1, 2, b'reference', datetime.now(UTC), [], 1))
        return t.MessageMediaDocument(document=t.Document(3, 4, b'reference', datetime.now(UTC),
            'video/mp4', 10, 1, request.media.attributes))


class PollFiles(unittest.TestCase):
    def test_real_photo_header_and_original_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'photo.png'
            with Image.new('RGB', (32, 24), 'red') as image: image.save(path)
            original = path.read_bytes()
            item = inspect_poll_file(path)
            self.assertIsNone(item.video)
            self.assertEqual(path.read_bytes(), original)

    def test_extension_is_not_evidence_of_valid_media(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, content in [('fake.png', b'not an image'), ('empty.jpg', b''),
                                  ('document.txt', b'text'), ('movie.mp4', b'broken')]:
                path = Path(directory)/name; path.write_bytes(content)
                with self.subTest(name=name), self.assertRaises((ValueError, OSError)):
                    inspect_poll_file(path)
            with self.assertRaises(ValueError): inspect_poll_file(directory)

    def test_header_must_match_image_format(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'wrong.jpg'
            with Image.new('RGB', (4, 4)) as image: image.save(path, 'PNG')
            with self.assertRaises(ValueError): inspect_poll_file(path)

    def test_poll_video_does_not_inherit_story_60_second_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'long.mp4'; movie(path)
            self.assertEqual(inspect_poll_file(path).video, (125, 720, 1280))
            with self.assertRaises(ValueError): mp4_metadata(path)


class PollUploads(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.photo = Path(self.temporary.name)/'photo.png'
        with Image.new('RGB', (32, 24), 'red') as image: image.save(self.photo)
        self.backend = Backend()

    async def test_upload_photo_and_video_nested_fields_without_sending(self):
        video = self.photo.with_name('movie.mp4'); movie(video)
        progress = []
        async def upload(stream, progress_callback):
            self.assertFalse(stream.closed)
            await progress_callback(5, 10)
            return t.InputFile(1, 1, 'synthetic', '')
        self.backend.client.upload_file.side_effect = upload
        options = await self.backend.prepare_poll_attachments(12, 'Q', ['A', 'B'],
            {'attached_media': self.photo, 'solution_media': video}, quiz=True, correct=[0],
            progress=lambda *args: progress.append(args))
        self.assertIsInstance(options['attached_media'], t.InputMediaPhoto)
        self.assertIsInstance(options['solution_media'], t.InputMediaDocument)
        built = poll_media('Q', ['A', 'B'], quiz=True, correct=[0], **options)
        self.assertTrue(bytes(built))
        self.assertEqual(len(progress), 2)
        self.assertEqual(self.backend._transfer_tasks, {})
        requests = [call.args[0] for call in self.backend.client.await_args_list]
        self.assertEqual(len(requests), 2)
        self.assertTrue(all(isinstance(request, f.messages.UploadMediaRequest) for request in requests))
        attr = requests[1].media.attributes[0]
        self.assertEqual((attr.duration, attr.w, attr.h), (125, 720, 1280))

    async def test_same_file_for_question_and_solution_uploads_once(self):
        result = await self.backend.prepare_poll_attachments(12, 'Q', ['A', 'B'],
            {'attached_media': self.photo, 'solution_media': self.photo}, quiz=True, correct=[0])
        self.backend.client.upload_file.assert_awaited_once()
        self.assertIs(result['attached_media'], result['solution_media'])

    async def test_invalid_quiz_prevents_upload(self):
        with self.assertRaises(ValueError):
            await self.backend.prepare_poll_attachments(12, 'Q', ['A', 'B'], {'solution_media': self.photo})
        self.backend.client.upload_file.assert_not_awaited()
        self.backend.client.assert_not_awaited()

    async def test_private_person_prevents_any_upload(self):
        self.backend.client.get_input_entity.return_value = t.InputPeerUser(12, 34)
        self.backend.client.get_entity.return_value = t.User(12, first_name='Synthetic')
        with self.assertRaises(ValueError):
            await self.backend.prepare_poll_attachments(12, 'Q', ['A', 'B'], {'attached_media': self.photo})
        self.backend.client.upload_file.assert_not_awaited()
        self.backend.app_config.assert_not_awaited()

    async def test_all_files_checked_before_first_upload(self):
        bad = self.photo.with_name('invalid.png'); bad.write_bytes(b'not a photo')
        with self.assertRaises(ValueError):
            await self.backend.prepare_poll_attachments(12, 'Q', ['A', 'B'],
                {'attached_media': self.photo, 'solution_media': bad}, quiz=True, correct=[0])
        self.backend.client.upload_file.assert_not_awaited()

    async def test_unknown_slot_rejected(self):
        with self.assertRaises(ValueError): await inspect_poll_files({'unrelated': self.photo})

    async def test_cancel_closes_stream_without_registering_or_publishing(self):
        started = asyncio.Event(); streams = []
        async def stalled(stream, progress_callback):
            streams.append(stream); started.set(); await asyncio.Event().wait()
        self.backend.client.upload_file.side_effect = stalled
        task = asyncio.create_task(self.backend.prepare_poll_attachments(12, 'Q', ['A', 'B'], {'attached_media': self.photo}))
        await started.wait(); task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(streams[0].closed)
        self.backend.client.assert_not_awaited()
        self.assertEqual(self.backend._transfer_tasks, {})

    async def test_stalled_upload_times_out_without_retry_and_closes_file(self):
        streams = []
        async def stalled(stream, progress_callback):
            streams.append(stream); await asyncio.Event().wait()
        self.backend.client.upload_file.side_effect = stalled
        with patch('tg_ascii.transfers.UPLOAD_IDLE_TIMEOUT', .02), self.assertRaises(TimeoutError):
            await self.backend.prepare_poll_attachments(12, 'Q', ['A', 'B'], {'attached_media': self.photo})
        self.assertTrue(streams[0].closed)
        self.backend.client.upload_file.assert_awaited_once()
        self.backend.client.assert_not_awaited()

    async def test_progressing_slow_upload_can_exceed_idle_deadline(self):
        async def slowly(stream, progress_callback):
            # Total 0.30 s exceeds the 0.20 s idle deadline; each gap (0.05 s)
            # stays well below it even with Windows' ~15.6 ms timer and VM load.
            # (1.3.1 used .01/.04 and failed ~5/8 runs in the Parallels VM.)
            for part in range(1, 7):
                await asyncio.sleep(.05); await progress_callback(part, 6)
            return t.InputFile(1, 1, 'synthetic', '')
        self.backend.client.upload_file.side_effect = slowly
        with patch('tg_ascii.transfers.UPLOAD_IDLE_TIMEOUT', .2):
            result = await self.backend.prepare_poll_attachments(12, 'Q', ['A', 'B'], {'attached_media': self.photo})
        self.assertIsInstance(result['attached_media'], t.InputMediaPhoto)

    async def test_file_replaced_after_inspection_never_uploads(self):
        item = inspect_poll_file(self.photo)
        self.photo.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            await upload_poll_files(self.backend, t.InputPeerChat(12), {'attached_media': item})
        self.backend.client.upload_file.assert_not_awaited()

    async def test_backend_close_cancels_and_releases_current_upload(self):
        from tg_ascii.transfers import cancel_transfers
        started = asyncio.Event(); streams = []
        async def stalled(stream, progress_callback):
            streams.append(stream); started.set(); await asyncio.Event().wait()
        self.backend.client.upload_file.side_effect = stalled
        task = asyncio.create_task(self.backend.prepare_poll_attachments(12, 'Q', ['A', 'B'], {'attached_media': self.photo}))
        await started.wait(); await cancel_transfers(self.backend)
        self.assertTrue(task.cancelled() and streams[0].closed)
        self.assertEqual(self.backend._transfer_tasks, {})


if __name__ == '__main__': unittest.main()
