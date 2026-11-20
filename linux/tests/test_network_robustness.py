"""Offline regression tests for transfer integrity and bounded network work."""
import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from telethon import errors, types

from tg_ascii.backend import TelegramBackend
from tg_ascii.recovery import Recovery
from tg_ascii.sticker_search import cached, invalidate


def backend():
    client=AsyncMock()
    client.add_event_handler=Mock()
    return TelegramBackend(client),client


class TransferClock:
    """Exercise deadline renewal without depending on VM scheduling latency.

    Stalled-transfer tests below still use real asyncio timeout cancellation.
    Progress tests advance this clock past the original deadline and fail if
    production stops renewing it, even when the build host is heavily loaded.
    """
    def __init__(self):
        self.now = 0.
        self.expires = None
        self.renewals = []
        self.asyncio = NS(timeout=self.timeout, get_running_loop=lambda:NS(time=lambda:self.now))

    def timeout(self, seconds):
        self.expires = self.now + seconds
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def reschedule(self, expires):
        self.expires = expires
        self.renewals.append(expires)

    def advance(self, seconds):
        self.now += seconds
        if self.now >= self.expires:
            raise TimeoutError('Simulated transfer inactivity')


class DownloadTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.backend,self.client=backend()
        self.folder=tempfile.TemporaryDirectory()
        self.root=Path(self.folder.name)
        self.target=self.root/'download.bin'

    def tearDown(self):
        self.folder.cleanup()

    def assert_no_partial_files(self):
        self.assertFalse(list(self.root.glob('.tg-download-*')))

    async def test_completed_transfer_atomically_replaces_previous_file(self):
        self.target.write_bytes(b'previous')
        progress=AsyncMock()
        async def download(media,*,file,progress_callback,thumb):
            file.write(b'new contents')
            self.assertEqual(self.target.read_bytes(),b'previous')
            await progress_callback(12,12)
            return file
        self.client.download_media.side_effect=download
        result=await self.backend.download_media(object(),self.target,progress)
        self.assertEqual(result,self.target)
        self.assertEqual(self.target.read_bytes(),b'new contents')
        progress.assert_awaited_once_with(12,12)
        self.assert_no_partial_files()

    async def test_failed_transfer_does_not_overwrite_destination_or_retry(self):
        self.target.write_bytes(b'previous')
        async def download(media,*,file,**kwargs):
            file.write(b'partial')
            raise ConnectionError('connection lost')
        self.client.download_media.side_effect=download
        with self.assertRaises(ConnectionError):
            await self.backend.download_media(object(),self.target)
        self.assertEqual(self.target.read_bytes(),b'previous')
        self.client.download_media.assert_awaited_once()
        self.assert_no_partial_files()

    async def test_cancellation_closes_file_and_removes_partial(self):
        started=asyncio.Event()
        streams=[]
        async def download(media,*,file,**kwargs):
            streams.append(file)
            file.write(b'partial')
            started.set()
            await asyncio.Event().wait()
        self.client.download_media.side_effect=download
        task=asyncio.create_task(self.backend.download_media(object(),self.target))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(streams[0].closed)
        self.assertFalse(self.target.exists())
        self.assert_no_partial_files()

    async def test_stalled_transfer_times_out_and_cleans_up(self):
        async def download(*args,**kwargs):await asyncio.Event().wait()
        self.client.download_media.side_effect=download
        with patch('tg_ascii.telegram_features.DOWNLOAD_IDLE_TIMEOUT',.01):
            with self.assertRaises(TimeoutError):
                await self.backend.download_media(object(),self.target)
        self.assertFalse(self.target.exists())
        self.assert_no_partial_files()

    async def test_progress_extends_idle_timeout_for_active_large_transfer(self):
        clock = TransferClock()
        async def download(media,*,file,progress_callback,**kwargs):
            for current in range(1,7):
                clock.advance(.02)
                file.write(b'x')
                await progress_callback(current,6)
            return file
        self.client.download_media.side_effect=download
        with patch('tg_ascii.telegram_features.DOWNLOAD_IDLE_TIMEOUT',.08), patch('tg_ascii.transfers.asyncio',clock.asyncio):
            await self.backend.download_media(object(),self.target)
        self.assertEqual(self.target.read_bytes(),b'x'*6)
        self.assertGreater(clock.now, .08)
        self.assertEqual(len(clock.renewals), 6)
        self.assertAlmostEqual(clock.expires, clock.now + .08)

    async def test_repeated_progress_without_new_bytes_does_not_hide_stall(self):
        clock = TransferClock()
        async def download(media,*,file,progress_callback,**kwargs):
            for _ in range(10):
                clock.advance(.005)
                await progress_callback(0,100)
            return file
        self.client.download_media.side_effect=download
        with patch('tg_ascii.telegram_features.DOWNLOAD_IDLE_TIMEOUT',.02), patch('tg_ascii.transfers.asyncio',clock.asyncio):
            with self.assertRaises(TimeoutError):
                await self.backend.download_media(object(),self.target)
        self.assertEqual(clock.renewals, [])
        self.assert_no_partial_files()

    async def test_download_concurrency_is_bounded_before_creating_temp_files(self):
        started=asyncio.Event()
        release=asyncio.Event()
        active=0
        peak=0
        async def download(media,*,file,**kwargs):
            nonlocal active,peak
            active+=1
            peak=max(peak,active)
            if active==4:started.set()
            try:
                await release.wait()
                file.write(b'ok')
                return file
            finally:active-=1
        self.client.download_media.side_effect=download
        tasks=[asyncio.create_task(self.backend.download_media(object(),self.root/f'{i}.bin')) for i in range(12)]
        await started.wait()
        self.assertEqual(len(list(self.root.glob('.tg-download-*'))),4)
        release.set()
        await asyncio.gather(*tasks)
        self.assertEqual(peak,4)
        self.assert_no_partial_files()

    async def test_photo_extension_is_preserved_for_stream_destination(self):
        async def download(media,*,file,**kwargs):
            file.write(b'photo')
            return file
        self.client.download_media.side_effect=download
        result=await self.backend.download_media(types.MessageMediaPhoto(photo=types.PhotoEmpty(1)),self.root/'preview')
        self.assertEqual(result.name,'preview.jpg')

    async def test_inferred_extension_does_not_overwrite_unselected_files(self):
        (self.root/'preview.jpg').write_bytes(b'original')
        (self.root/'preview (1).jpg').write_bytes(b'earlier download')
        async def download(media,*,file,**kwargs):
            file.write(b'new photo')
            return file
        self.client.download_media.side_effect=download
        result=await self.backend.download_media(types.MessageMediaPhoto(photo=types.PhotoEmpty(1)),self.root/'preview')
        self.assertEqual(result.name,'preview (2).jpg')
        self.assertEqual(result.read_bytes(),b'new photo')
        self.assertEqual((self.root/'preview.jpg').read_bytes(),b'original')
        self.assertEqual((self.root/'preview (1).jpg').read_bytes(),b'earlier download')
        self.assert_no_partial_files()

    async def test_concurrent_extensionless_saves_choose_distinct_completed_files(self):
        started=asyncio.Event()
        release=asyncio.Event()
        active=0
        async def download(media,*,file,**kwargs):
            nonlocal active
            active+=1
            if active==2:started.set()
            await release.wait()
            file.write(str(media.photo.id).encode())
            return file
        self.client.download_media.side_effect=download
        tasks=[asyncio.create_task(self.backend.download_media(
            types.MessageMediaPhoto(photo=types.PhotoEmpty(ident)),self.root/'preview')) for ident in (1,2)]
        await started.wait()
        self.assertFalse((self.root/'preview.jpg').exists())
        release.set()
        paths=await asyncio.gather(*tasks)
        self.assertEqual({path.name for path in paths},{'preview.jpg','preview (1).jpg'})
        self.assertEqual([path.read_bytes() for path in paths],[b'1',b'2'])
        self.assert_no_partial_files()

    async def test_explicit_existing_extensionless_file_is_replaced_in_place(self):
        target=self.root/'preview'
        target.write_bytes(b'previous')
        async def download(media,*,file,**kwargs):
            file.write(b'new photo')
            return file
        self.client.download_media.side_effect=download
        result=await self.backend.download_media(types.MessageMediaPhoto(photo=types.PhotoEmpty(1)),target)
        self.assertEqual(result,target)
        self.assertEqual(target.read_bytes(),b'new photo')
        self.assertFalse((self.root/'preview.jpg').exists())


class CatalogueTests(IsolatedAsyncioTestCase):
    async def test_concurrent_callers_share_one_rpc_and_one_can_cancel(self):
        owner=NS()
        started=asyncio.Event()
        release=asyncio.Event()
        async def fetch():
            started.set()
            await release.wait()
            return ['document']
        loader=AsyncMock(side_effect=fetch)
        first=asyncio.create_task(cached(owner,'pack',loader))
        await started.wait()
        second=asyncio.create_task(cached(owner,'pack',loader))
        await asyncio.sleep(0)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):await first
        release.set()
        self.assertEqual(await second,['document'])
        loader.assert_awaited_once()
        self.assertFalse(owner._sticker_jobs)

    async def test_cancel_last_view_cancels_unneeded_network_work(self):
        owner=NS()
        started=asyncio.Event()
        cancelled=asyncio.Event()
        async def fetch():
            started.set()
            try:await asyncio.Event().wait()
            finally:cancelled.set()
        task=asyncio.create_task(cached(owner,'pack',fetch))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(cancelled.is_set())
        self.assertFalse(owner._sticker_jobs)
        self.assertFalse(owner._sticker_catalogue)

    async def test_invalidated_inflight_response_cannot_replace_fresh_cache(self):
        owner=NS()
        started=asyncio.Event()
        release=asyncio.Event()
        async def old():
            started.set()
            await release.wait()
            return 'old catalogue'
        first=asyncio.create_task(cached(owner,'pack',old))
        await started.wait()
        invalidate(owner)
        fresh=AsyncMock(return_value='new catalogue')
        self.assertEqual(await cached(owner,'pack',fresh),'new catalogue')
        release.set()
        self.assertEqual(await first,'old catalogue')
        self.assertEqual(await cached(owner,'pack',fresh),'new catalogue')
        fresh.assert_awaited_once()

    async def test_backend_close_cancels_pending_catalogue_requests(self):
        owner,client=backend()
        started=asyncio.Event()
        async def fetch():
            started.set()
            await asyncio.Event().wait()
        task=asyncio.create_task(cached(owner,'pack',fetch))
        await started.wait()
        await owner.close()
        with self.assertRaises(asyncio.CancelledError):await task
        client.disconnect.assert_awaited_once()
        self.assertFalse(owner._sticker_jobs)


class UploadTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.backend,self.client=backend()
        self.backend.message=lambda value:value
        self.folder=tempfile.TemporaryDirectory()
        self.paths=[Path(self.folder.name)/name for name in ('first.bin','second.bin')]
        for path in self.paths:path.write_bytes(b'upload')

    def tearDown(self):
        self.folder.cleanup()

    async def test_all_upload_entrypoints_timeout_without_retry_and_close_sources(self):
        streams=[]
        async def stalled(peer,file,**kwargs):
            streams.extend(file if isinstance(file,list) else [file])
            await asyncio.Event().wait()
        self.client.send_file.side_effect=stalled
        operations=(
            lambda:self.backend.send_attachment(42,self.paths[0]),
            lambda:self.backend.send_custom(42,'text',[],self.paths[0]),
            lambda:self.backend.send_batch(42,self.paths),
            lambda:self.backend.send_formatted(42,'text',[],path=self.paths[0]),
            lambda:self.backend.send_audio(42,self.paths[0]),
        )
        with patch('tg_ascii.transfers.UPLOAD_IDLE_TIMEOUT',.01):
            for operation in operations:
                with self.assertRaises(TimeoutError):await operation()
                self.client.send_file.assert_awaited_once()
                self.assertTrue(all(stream.closed for stream in streams))
                self.client.send_file.reset_mock()

    async def test_progress_keeps_upload_active_and_preserves_sync_callback(self):
        clock = TransferClock()
        async def upload(peer,file,*,progress_callback,**kwargs):
            for current in range(1,7):
                clock.advance(.02)
                await progress_callback(current,6)
            return 'sent'
        self.client.send_file.side_effect=upload
        progress=Mock()
        with patch('tg_ascii.transfers.UPLOAD_IDLE_TIMEOUT',.08), patch('tg_ascii.transfers.asyncio',clock.asyncio):
            result=await self.backend.send_attachment(42,self.paths[0],progress)
        self.assertEqual(result,'sent')
        self.assertGreater(clock.now, .08)
        self.assertEqual(len(clock.renewals), 6)
        self.assertAlmostEqual(clock.expires, clock.now + .08)
        self.assertEqual(progress.call_count,6)
        progress.assert_called_with(6,6)
        self.client.send_file.assert_awaited_once()

    async def test_album_fractional_file_progress_extends_deadline(self):
        clock = TransferClock()
        async def upload(peer,files,*,progress_callback,**kwargs):
            for current in (.25,.5,.75,1,1.25,1.5,1.75,2):
                clock.advance(.015)
                await progress_callback(current,2)
            return ['first','second']
        self.client.send_file.side_effect=upload
        progress=AsyncMock()
        with patch('tg_ascii.transfers.UPLOAD_IDLE_TIMEOUT',.08), patch('tg_ascii.transfers.asyncio',clock.asyncio):
            result=await self.backend.send_batch(42,self.paths,progress=progress)
        self.assertEqual(result,['first','second'])
        self.assertGreater(clock.now, .08)
        self.assertEqual(len(clock.renewals), 8)
        self.assertAlmostEqual(clock.expires, clock.now + .08)
        progress.assert_awaited_with(2,2)
        self.client.send_file.assert_awaited_once()


class RecoveryAndBatchTests(IsolatedAsyncioTestCase):
    async def test_recent_successful_probe_serves_concurrent_refreshes(self):
        client=AsyncMock()
        client.is_connected=Mock(return_value=True)
        service=NS(client=client,on_change=Mock())
        recovery=Recovery(service)
        await asyncio.gather(*(recovery.ensure() for _ in range(30)))
        client.assert_awaited_once()
        client.disconnect.assert_not_called()
        recovery.last_check-=6
        await recovery.ensure()
        self.assertEqual(client.await_count,2)
        await recovery.stop()

    async def test_one_batch_validates_100_selected_messages_before_forwarding(self):
        owner,client=backend()
        client.get_entity.return_value=types.User(42)
        client.get_messages.return_value=[types.Message(i,peer_id=types.PeerUser(42),message='ok',out=True) for i in range(1,101)]
        await owner.forward_selected_messages(42,[*range(1,101),1],99)
        client.get_messages.assert_awaited_once_with(42,ids=list(range(1,101)))
        client.forward_messages.assert_awaited_once_with(99,list(range(1,101)),from_peer=42)

    async def test_missing_or_wrong_peer_message_rejects_entire_batch(self):
        for bad in (None,types.Message(2,peer_id=types.PeerUser(99),message='other chat')):
            owner,client=backend()
            client.get_messages.return_value=[types.Message(1,peer_id=types.PeerUser(42),message='ok'),bad]
            with self.assertRaises(ValueError):await owner.delete_selected_messages(42,[1,2],True)
            client.delete_messages.assert_not_called()


class SenderLookupTests(IsolatedAsyncioTestCase):
    async def test_unavailable_identity_is_cached_temporarily_then_retried(self):
        owner,client=backend()
        client.get_entity.side_effect=ValueError('unavailable')
        message=NS(sender_id=7,sender=None,out=False)
        await owner.resolve_missing_senders([message])
        calls=client.get_entity.await_count
        for _ in range(20):await owner.resolve_missing_senders([message])
        self.assertEqual(client.get_entity.await_count,calls)
        owner._sender_failures[7]-=31
        await owner.resolve_missing_senders([message])
        self.assertGreater(client.get_entity.await_count,calls)

    async def test_attached_entity_clears_negative_entry_without_network(self):
        owner,client=backend()
        client.get_entity.side_effect=ValueError('unavailable')
        message=NS(sender_id=7,sender=None,out=False)
        await owner.resolve_missing_senders([message])
        client.get_entity.reset_mock()
        message.sender=types.User(7,first_name='Alice')
        await owner.resolve_missing_senders([message])
        self.assertEqual(owner.names[7],'Alice')
        self.assertNotIn(7,owner._sender_failures)
        client.get_entity.assert_not_called()

    async def test_concurrent_messages_share_lookup_without_cancellation_cascade(self):
        owner,client=backend()
        started=asyncio.Event()
        release=asyncio.Event()
        async def entities(ids):
            started.set()
            await release.wait()
            return [types.User(7,first_name='Alice')]
        client.get_entity.side_effect=entities
        message=NS(sender_id=7,sender=None,out=False)
        first=asyncio.create_task(owner.resolve_missing_senders([message]))
        await started.wait()
        second=asyncio.create_task(owner.resolve_missing_senders([message]))
        await asyncio.sleep(0)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):await first
        release.set()
        await second
        client.get_entity.assert_awaited_once_with([7])
        self.assertFalse(owner._sender_jobs)

    async def test_flood_wait_does_not_trigger_fallback_or_repeated_requests(self):
        owner,client=backend()
        client.get_entity.side_effect=errors.FloodWaitError(None,capture=60)
        message=NS(sender_id=7,sender=None,out=False,get_sender=AsyncMock())
        await owner.resolve_missing_senders([message])
        await owner.resolve_missing_senders([NS(sender_id=8,sender=None,out=False)])
        client.get_entity.assert_awaited_once()
        message.get_sender.assert_not_called()

    async def test_negative_cache_has_fixed_bound(self):
        owner,client=backend()
        client.get_entity.return_value=[]
        with patch('tg_ascii.sender_identity.NEGATIVE_CACHE_LIMIT',8):
            for ident in range(20):
                await owner.resolve_missing_senders([NS(sender_id=ident,sender=None,out=False)])
        self.assertEqual(len(owner._sender_failures),8)
        self.assertFalse(owner._sender_jobs)

    async def test_backend_close_cancels_pending_sender_lookup(self):
        owner,client=backend()
        started=asyncio.Event()
        async def entities(ids):
            started.set()
            await asyncio.Event().wait()
        client.get_entity.side_effect=entities
        task=asyncio.create_task(owner.resolve_missing_senders([NS(sender_id=7,sender=None,out=False)]))
        await started.wait()
        await owner.close()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertFalse(owner._sender_jobs)
        self.assertFalse(owner._sender_failures)
