"""Transfers and recovery stay owned by a session, including queued/cancelled work."""
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

from telethon import types
from tg_ascii.backend import TelegramBackend
from tg_ascii.recovery import Recovery


class TransferLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)
        self.client=AsyncMock();self.client.add_event_handler=Mock()
        self.backend=TelegramBackend(self.client)

    async def test_close_cancels_active_and_queued_downloads_before_they_create_more_files(self):
        started=asyncio.Event();streams=[]
        async def download(media,*,file,**kwargs):
            streams.append(file)
            if len(streams)==4:started.set()
            await asyncio.Event().wait()
        self.client.download_media.side_effect=download
        jobs=[asyncio.create_task(self.backend.download_media(object(),self.root/f'{i}.bin')) for i in range(20)]
        await started.wait()
        self.assertEqual(len(list(self.root.glob('.tg-download-*'))),4)
        await self.backend.close()
        results=await asyncio.gather(*jobs,return_exceptions=True)
        self.assertTrue(all(isinstance(value,asyncio.CancelledError) for value in results))
        self.assertEqual(len(streams),4)
        self.assertTrue(all(stream.closed for stream in streams))
        self.assertFalse(list(self.root.iterdir()))
        self.assertFalse(self.backend._transfer_tasks)
        with self.assertRaises(ConnectionError):
            await self.backend.download_media(object(),self.root/'late.bin')
        self.client.download_media.assert_awaited()
        self.assertEqual(self.client.download_media.await_count,4)

    async def test_full_document_size_is_checked_before_atomic_replacement(self):
        destination=self.root/'valid.bin';destination.write_bytes(b'keep me')
        document=types.Document(1,2,b'',datetime.now(timezone.utc),'application/octet-stream',100,1,[])
        async def truncated(media,*,file,**kwargs):file.write(b'partial');return file
        self.client.download_media.side_effect=truncated
        with self.assertRaisesRegex(OSError,'Incomplete'):
            await self.backend.download_media(types.MessageMediaDocument(document=document),destination)
        self.assertEqual(destination.read_bytes(),b'keep me')
        self.assertFalse(list(self.root.glob('.tg-download-*')))
        self.client.download_media.assert_awaited_once()

    async def test_photo_preview_selects_smallest_adequate_size_without_changing_full_download(self):
        sizes=[types.PhotoSize('s',90,90,100),types.PhotoSize('m',320,240,1000),
               types.PhotoSizeProgressive('x',1280,960,[2000,10000])]
        photo=types.Photo(1,2,b'',datetime.now(timezone.utc),sizes,1)
        async def download(media,*,file,**kwargs):file.write(b'fixture');return file
        self.client.download_media.side_effect=download
        # Both the raw photo used by profiles and message photos use previews.
        for media in (photo,types.MessageMediaPhoto(photo=photo)):
            await self.backend.download_media(media,self.root/'preview.jpg',thumbnail=True)
            self.assertEqual(self.client.download_media.call_args.kwargs['thumb'],'m')
            await self.backend.download_media(media,self.root/'full.jpg')
            self.assertIsNone(self.client.download_media.call_args.kwargs['thumb'])
        photo.sizes=[types.PhotoSize('s',90,90,100),types.PhotoSize('m',160,120,1000)]
        await self.backend.download_media(photo,self.root/'preview.jpg',thumbnail=True)
        self.assertEqual(self.client.download_media.call_args.kwargs['thumb'],'m')

    async def test_document_preview_retains_largest_thumbnail(self):
        document=types.Document(1,2,b'',datetime.now(timezone.utc),'image/webp',10000,1,[],thumbs=[
            types.PhotoSize('s',90,90,100),types.PhotoSize('m',320,240,1000),
            types.PhotoSizeProgressive('x',1280,960,[2000,10000])])
        async def download(media,*,file,**kwargs):file.write(b'thumb');return file
        self.client.download_media.side_effect=download
        await self.backend.download_media(types.MessageMediaDocument(document=document),self.root/'preview.jpg',thumbnail=True)
        self.assertEqual(self.client.download_media.call_args.kwargs['thumb'],'x')

    async def test_all_uploads_close_sources_and_cancel_when_backend_closes(self):
        source=self.root/'photo.jpg';source.write_bytes(b'fixture')
        for operation in (
            lambda:self.backend.send_attachment(42,source),
            lambda:self.backend.send_custom(42,'text',[],source),
            lambda:self.backend.send_batch(42,[source,source]),
            lambda:self.backend.send_formatted(42,'text',[],path=source),
            lambda:self.backend.send_audio(42,source),
            lambda:self.backend.update_photo(source),
            lambda:self.backend.set_wallpaper(42,source),
            lambda:self.backend.publish_story(source),
            lambda:self.backend.profile_change(-123,'photo',source),
        ):
            self.backend=TelegramBackend(self.client)
            self.backend.profile=AsyncMock(return_value={'id':-123,'kind':'group','is_channel':False,'can_edit_info':True})
            started=asyncio.Event();streams=[]
            async def hang(file,*args,**kwargs):
                streams.extend(file if isinstance(file,list) else [file]);started.set()
                await asyncio.Event().wait()
            async def send(peer,file,**kw):return await hang(file)
            self.client.send_file.side_effect=send;self.client.upload_file.side_effect=hang
            task=asyncio.create_task(operation());await started.wait()
            await self.backend.close()
            with self.assertRaises(asyncio.CancelledError):await task
            self.assertTrue(streams)
            self.assertTrue(all(stream.closed for stream in streams))
            self.assertFalse(self.backend._transfer_tasks)
        self.assertEqual(source.read_bytes(),b'fixture')

    async def test_profile_wallpaper_and_story_uploads_have_idle_deadlines_without_retries(self):
        source=self.root/'photo.jpg';source.write_bytes(b'fixture')
        streams=[]
        async def stalled(stream,**kwargs):streams.append(stream);await asyncio.Event().wait()
        self.client.upload_file.side_effect=stalled
        with patch('tg_ascii.transfers.UPLOAD_IDLE_TIMEOUT',.01):
            for operation in (lambda:self.backend.update_photo(source),lambda:self.backend.set_wallpaper(42,source),lambda:self.backend.publish_story(source)):
                self.client.upload_file.reset_mock()
                with self.assertRaises(TimeoutError):await operation()
                self.client.upload_file.assert_awaited_once()
                self.assertTrue(streams[-1].closed)
        self.assertFalse(self.backend._transfer_tasks)

    async def test_chat_photo_final_rpc_is_also_bounded_after_successful_upload(self):
        source=self.root/'photo.jpg';source.write_bytes(b'fixture');streams=[]
        self.backend.profile=AsyncMock(return_value={'id':-123,'kind':'group','is_channel':False,'can_edit_info':True})
        async def upload(stream,**kwargs):
            streams.append(stream);return types.InputFile(1,1,'photo.jpg','')
        async def stalled(request):await asyncio.Event().wait()
        self.client.upload_file.side_effect=upload;self.client.side_effect=stalled
        with patch('tg_ascii.transfers.UPLOAD_IDLE_TIMEOUT',.01):
            with self.assertRaises(TimeoutError):await self.backend.profile_change(-123,'photo',source)
        self.assertEqual(type(self.client.call_args.args[0]).__name__,'EditChatPhotoRequest')
        self.client.assert_awaited_once();self.client.upload_file.assert_awaited_once()
        self.assertTrue(streams[0].closed);self.assertFalse(self.backend._transfer_tasks)

    async def test_closing_one_account_does_not_cancel_another_accounts_transfer(self):
        other_client=AsyncMock();other_client.add_event_handler=Mock();other=TelegramBackend(other_client)
        started=asyncio.Event();release=asyncio.Event()
        async def download(media,*,file,**kwargs):
            started.set();await release.wait();file.write(b'other account');return file
        other_client.download_media.side_effect=download
        task=asyncio.create_task(other.download_media(object(),self.root/'other.bin'));await started.wait()
        await self.backend.close()
        self.assertFalse(task.done())
        other_client.disconnect.assert_not_awaited()
        release.set();target=await task
        self.assertEqual(target.read_bytes(),b'other account')
        await other.close()


class RecoveryFanoutTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.client=AsyncMock();self.client.is_connected=Mock(return_value=False);self.client._updates_error=None
        self.recovery=Recovery(NS(client=self.client,root=Path(self.directory.name),on_change=Mock()))
        self.addAsyncCleanup(self.recovery.stop)

    async def test_thirty_forced_recoveries_share_one_transport_reset_but_later_refresh_is_real(self):
        entered=asyncio.Event();release=asyncio.Event()
        async def connect():entered.set();await release.wait();self.client.is_connected.return_value=True
        self.client.connect.side_effect=connect
        tasks=[asyncio.create_task(self.recovery.ensure(force=True)) for _ in range(30)]
        await entered.wait();release.set();await asyncio.gather(*tasks)
        self.client.connect.assert_awaited_once();self.client.disconnect.assert_awaited_once()
        await self.recovery.ensure(force=True)
        self.assertEqual(self.client.connect.await_count,2)
        self.assertFalse(self.recovery.operations)

    async def test_failed_concurrent_recovery_does_not_repeat_connect_for_every_waiter(self):
        entered=asyncio.Event();release=asyncio.Event()
        async def connect():entered.set();await release.wait();raise OSError('offline')
        self.client.connect.side_effect=connect
        tasks=[asyncio.create_task(self.recovery.ensure(force=bool(i%2))) for i in range(30)]
        await entered.wait();release.set()
        results=await asyncio.gather(*tasks,return_exceptions=True)
        self.assertTrue(all(isinstance(result,OSError) for result in results))
        self.client.connect.assert_awaited_once();self.client.disconnect.assert_awaited_once()
        self.assertEqual(self.recovery.failures,1)

    async def test_cancelled_recovery_does_not_report_success_to_a_waiter(self):
        entered=asyncio.Event();release=asyncio.Event()
        async def connect():entered.set();await release.wait()
        self.client.connect.side_effect=connect
        first=asyncio.create_task(self.recovery.ensure(force=True));await entered.wait()
        second=asyncio.create_task(self.recovery.ensure(force=True));await asyncio.sleep(0)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):await first
        release.set();await second
        self.assertEqual(self.client.connect.await_count,2)
        self.assertEqual(self.recovery.state,'online')
