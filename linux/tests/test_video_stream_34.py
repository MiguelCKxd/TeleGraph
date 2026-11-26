import asyncio
from datetime import datetime, timezone
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock

from telethon import errors, types
from tg_ascii.video_stream import BLOCK_SIZE, CACHE_BLOCKS, StreamDescriptor, TelegramVideoReader, StreamingFrames, describe


def document(size, ref=b'one'):
    return types.Document(123, 456, ref, datetime.now(timezone.utc), 'video/mp4', size, 2, [])


class Iterator:
    def __init__(self, payload=None, error=None, entered=None):
        self.payload, self.error, self.entered = payload, error, entered
        self.closed = False
    async def __anext__(self):
        if self.entered:
            self.entered.set()
            await asyncio.Event().wait()
        if self.error: raise self.error
        return self.payload
    async def close(self): self.closed = True


class VideoStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_only_requested_blocks_supports_seek_and_bounds_cache(self):
        payload = bytes(range(256)) * (BLOCK_SIZE // 256 * 7)
        calls = []
        def iterator(doc, *, offset, **kwargs):
            calls.append(offset)
            return Iterator(payload[offset:offset + BLOCK_SIZE])
        backend = NS(client=NS(iter_download=iterator))
        reader = TelegramVideoReader(StreamDescriptor(backend, asyncio.get_running_loop(), 1, 2, document(len(payload))))
        def run():
            self.assertEqual(reader.read(16), payload[:16])
            self.assertEqual(reader.seek(-13, io.SEEK_END), len(payload)-13)
            self.assertEqual(reader.read(100), payload[-13:])
            reader.seek(0)
            self.assertEqual(reader.read(10), payload[:10])
            self.assertEqual(calls, [0, BLOCK_SIZE * 6])
            for index in range(7):
                reader.seek(index * BLOCK_SIZE)
                reader.read(1)
            self.assertLessEqual(len(reader.blocks), CACHE_BLOCKS)
            self.assertLessEqual(sum(map(len, reader.blocks.values())), CACHE_BLOCKS * BLOCK_SIZE)
            reader.close()
        await asyncio.to_thread(run)

    async def test_close_interrupts_download_and_closes_iterator(self):
        entered = asyncio.Event()
        iterator = Iterator(entered=entered)
        backend = NS(client=NS(iter_download=lambda *a, **kw: iterator))
        reader = TelegramVideoReader(StreamDescriptor(backend, asyncio.get_running_loop(), 1, 2, document(BLOCK_SIZE)))
        task = asyncio.create_task(asyncio.to_thread(reader.read, 1))
        await entered.wait()
        reader.abort()
        with self.assertRaises(OSError): await task
        await asyncio.sleep(0)
        self.assertTrue(iterator.closed)
        self.assertFalse(backend._transfer_tasks)
        reader.close()

    async def test_reference_refresh_keeps_identity_and_rejects_short_blocks(self):
        original = document(3)
        backend = NS(client=NS(), media_message=AsyncMock(return_value=NS(media=NS(document=document(3, b'two')))))
        calls = []
        def iterator(doc, **kwargs):
            calls.append(doc.file_reference)
            return Iterator(error=errors.FileReferenceExpiredError(None)) if len(calls)==1 else Iterator(b'abc')
        backend.client.iter_download = iterator
        reader = TelegramVideoReader(StreamDescriptor(backend, asyncio.get_running_loop(), 1, 2, original))
        self.assertEqual(await asyncio.to_thread(reader.read, 3), b'abc')
        self.assertEqual(calls, [b'one', b'two'])
        reader.close()
        backend.client.iter_download = lambda *a, **kw: Iterator(b'a')
        reader = TelegramVideoReader(StreamDescriptor(backend, asyncio.get_running_loop(), 1, 2, original))
        with self.assertRaises(OSError): await asyncio.to_thread(reader.read, 3)
        reader.close()

    async def test_descriptor_rejects_temporary_media_and_marks_protected_video(self):
        raw = NS(media=types.MessageMediaDocument(document=document(20), ttl_seconds=1))
        backend = NS(media_message=AsyncMock(return_value=raw))
        self.assertIsNone(await describe(backend, 1, 2, raw))
        raw.media.ttl_seconds = None
        raw.noforwards = True
        result = await describe(backend, 1, 2, raw, refresh=True)
        self.assertFalse(result.cacheable)

    async def test_account_switch_rejects_even_cached_bytes_without_closing_other_backend(self):
        selected = ['a']
        backend = NS(client=NS(iter_download=lambda *a, **kw: Iterator(b'abc')))
        reader = TelegramVideoReader(StreamDescriptor(backend, asyncio.get_running_loop(), 1, 2,
                                      document(3), current=lambda:selected[0]=='a'))
        self.assertEqual(await asyncio.to_thread(reader.read, 1), b'a')
        selected[0] = 'b'
        with self.assertRaises(OSError): await asyncio.to_thread(reader.read, 1)
        self.assertFalse(getattr(backend, '_transfers_closed', False))
        reader.close()

    async def test_real_pyav_first_frame_matches_original_before_full_file_is_read(self):
        import av
        from PIL import Image
        from tg_ascii.video_frames import VideoFrames
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'original.mp4'
            def create():
                with av.open(str(path), 'w') as output:
                    stream = output.add_stream('mpeg4', rate=25)
                    stream.width=512; stream.height=512; stream.pix_fmt='yuv420p'; stream.bit_rate=20_000_000
                    for index in range(60):
                        image = Image.frombytes('RGB', (512, 512), os.urandom(512*512*3))
                        frame = av.VideoFrame.from_image(image)
                        image.close()
                        for packet in stream.encode(frame): output.mux(packet)
                    for packet in stream.encode(): output.mux(packet)
            await asyncio.to_thread(create)
            calls = []
            def iterator(doc, *, offset, **kwargs):
                with path.open('rb') as stream:
                    stream.seek(offset)
                    payload = stream.read(BLOCK_SIZE)
                calls.append((offset, len(payload)))
                return Iterator(payload)
            backend = NS(client=NS(iter_download=iterator))
            descriptor = StreamDescriptor(backend, asyncio.get_running_loop(), 1, 2, document(path.stat().st_size))
            def compare():
                streamed, local = StreamingFrames(descriptor), VideoFrames(path)
                try:
                    streamed.viewport((128,128)); local.viewport((128,128))
                    self.assertEqual(streamed.get(0).tobytes(), local.get(0).tobytes())
                    self.assertLess(sum(size for _, size in calls), path.stat().st_size)
                    self.assertLessEqual(sum(map(len, streamed.reader.blocks.values())), BLOCK_SIZE * CACHE_BLOCKS)
                finally:
                    streamed.close(); local.close()
            await asyncio.to_thread(compare)
