import asyncio
import errno
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from unittest.mock import patch

from tg_ascii_mobile.download_manager import DownloadManager, FOLDER, failure


class DownloadTests(IsolatedAsyncioTestCase):
    def test_fixed_rpc_categories_do_not_expose_the_server_message(self):
        from telethon.errors import FloodWaitError, FileReferenceExpiredError, RPCError
        self.assertEqual(failure(FloodWaitError(None, capture=30)), 'rate_limited')
        self.assertEqual(failure(FileReferenceExpiredError(None)), 'unavailable')
        self.assertEqual(failure(RPCError(None, 'PRIVATE_REQUEST_DETAILS', 400)), 'unexpected')

    async def asyncSetUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.media = NS()
        self.message = NS(media=self.media, file=NS(name='fixture.bin', size=8))
        self.backend = NS(checked_message=AsyncMock(return_value=self.message),
                          client=NS(get_entity=AsyncMock(return_value=NS())))
        self.events = []
        self.core = NS(root=self.root, account='a', backend=self.backend, locked=False, system='Android',
                       emit=lambda event, payload: self.events.append((event, payload)),
                       _media_index=AsyncMock(return_value={}),
                       open_file_with_system=AsyncMock(return_value={'opened': True}))
        self.core.accounts = NS(services={'a': NS(backend=self.backend)})

        async def transfer(media, path, *, progress, quality):
            self.assertEqual(quality, 'original')
            progress(4, 8)
            await asyncio.sleep(0)
            path.write_bytes(b'original')
            progress(8, 8)
            return path
        self.backend.download_media = AsyncMock(side_effect=transfer)
        self.manager = DownloadManager(self.core)
        self.addAsyncCleanup(self.manager.close)

    def start(self, ident=7):
        return self.manager.start(42, ident, 'a')

    async def done(self, value):
        job = self.manager.jobs[value['id']]
        await asyncio.wait_for(job.task, 2)
        return job

    async def test_job_returns_immediately_and_deduplicates_double_tap(self):
        first, second = self.start(), self.start()
        self.assertEqual(first['state'], 'queued')
        self.assertEqual(first['id'], second['id'])
        job = await self.done(first)
        self.assertEqual((job.state, job.current, job.total), ('ready', 8, 8))
        self.assertEqual(job.snapshot()['percent'], 100)
        self.assertEqual(job.path.read_bytes(), b'original')
        self.backend.download_media.assert_awaited_once()
        self.assertNotIn(str(self.root), repr(self.manager.snapshot('a')))

    async def test_percentage_never_reaches_complete_before_atomic_result(self):
        gate = asyncio.Event()
        async def transfer(media, path, *, progress, quality):
            progress(8, 8)
            await gate.wait()
            path.write_bytes(b'original')
            return path
        self.backend.download_media.side_effect = transfer
        result = self.start()
        await asyncio.sleep(.01)
        self.assertEqual(self.manager.get(result['id'], 'a').snapshot()['percent'], 99)
        gate.set()
        self.assertEqual((await self.done(result)).snapshot()['percent'], 100)

    async def test_unknown_total_remains_indeterminate_with_bytes(self):
        self.message.file.size = None
        gate = asyncio.Event()
        async def transfer(media, path, *, progress, quality):
            progress(5, 0)
            await gate.wait()
            path.write_bytes(b'bytes')
            return path
        self.backend.download_media.side_effect = transfer
        result = self.start()
        await asyncio.sleep(.01)
        snapshot = self.manager.get(result['id'], 'a').snapshot()
        self.assertEqual((snapshot['bytes'], snapshot['total'], snapshot['percent']), (5, None, None))
        gate.set()
        self.assertEqual((await self.done(result)).total, 5)

    async def test_two_slots_and_bounded_queue_with_cancellation_before_start(self):
        gate = asyncio.Event()
        active = peak = 0
        async def transfer(media, path, *, progress, quality):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await gate.wait()
                path.write_bytes(b'original')
                return path
            finally:
                active -= 1
        self.backend.download_media.side_effect = transfer
        items = [self.start(i) for i in range(12)]
        with self.assertRaisesRegex(ValueError, 'queue'):
            self.start(13)
        await asyncio.sleep(.01)
        self.assertEqual((active, peak), (2, 2))
        cancelled = await self.manager.cancel(items[-1]['id'], 'a')
        self.assertEqual(cancelled['state'], 'cancelled')
        gate.set()
        await asyncio.gather(*(self.manager.jobs[item['id']].task for item in items), return_exceptions=True)
        self.assertEqual(self.backend.download_media.await_count, 11)

    async def test_cancel_removes_only_owned_partial_and_retry_restarts_from_zero(self):
        started = asyncio.Event()
        async def transfer(media, path, *, progress, quality):
            path.with_suffix('.part').write_bytes(b'partial')
            progress(5, 8)
            started.set()
            await asyncio.Event().wait()
        self.backend.download_media.side_effect = transfer
        result = self.start()
        await started.wait()
        job = self.manager.jobs[result['id']]
        directory = job.directory
        await self.manager.cancel(job.id, 'a')
        self.assertFalse(directory.exists())
        async def complete(media, path, *, progress, quality):
            self.assertEqual(job.current, 0)
            progress(4, 8)
            path.write_bytes(b'original')
            return path
        self.backend.download_media.side_effect = complete
        self.manager.retry(job.id, 'a')
        await self.done(result)
        self.assertEqual((job.state, job.attempt), ('ready', 2))

    async def test_disk_full_is_visible_and_partial_is_removed(self):
        async def full(media, path, **kwargs):
            path.write_bytes(b'part')
            raise OSError(errno.ENOSPC, 'private directory path')
        self.backend.download_media.side_effect = full
        job = await self.done(self.start())
        self.assertEqual((job.state, job.error), ('failed', 'storage_full'))
        self.assertIsNone(job.path)
        self.assertFalse((self.root / FOLDER / job.id).exists())
        self.assertNotIn('private', repr(job.snapshot()))

    async def test_network_error_and_short_file_are_retryable(self):
        self.backend.download_media.side_effect = ConnectionResetError('private hostname')
        result = self.start()
        job = await self.done(result)
        self.assertEqual(job.error, 'network')
        async def short(media, path, **kwargs):
            path.write_bytes(b'bad')
            return path
        self.backend.download_media.side_effect = short
        self.manager.retry(job.id, 'a')
        await self.done(result)
        self.assertEqual((job.state, job.error), ('failed', 'network'))
        self.assertFalse((self.root / FOLDER / job.id).exists())

    async def test_switch_keeps_transfer_but_never_reports_or_opens_other_account(self):
        started, finish = asyncio.Event(), asyncio.Event()
        async def transfer(media, path, **kwargs):
            started.set()
            await finish.wait()
            path.write_bytes(b'original')
            return path
        self.backend.download_media.side_effect = transfer
        result = self.start()
        await started.wait()
        other = NS()
        self.core.accounts.services['b'] = NS(backend=other)
        self.core.account, self.core.backend = 'b', other
        self.events.clear()
        finish.set()
        job = await self.done(result)
        self.assertEqual(job.state, 'ready')
        self.assertEqual(self.events, [])
        self.assertEqual(self.manager.snapshot('b'), [])
        with self.assertRaises(PermissionError):
            await self.manager.open(job.id, 'file', 'a')
        self.core.account, self.core.backend = 'a', self.backend
        self.assertEqual(self.manager.snapshot('a')[0]['state'], 'ready')

    async def test_lock_cancels_all_and_cleans_owned_files(self):
        gate = asyncio.Event()
        async def transfer(media, path, **kwargs):
            path.write_bytes(b'part')
            gate.set()
            await asyncio.Event().wait()
        self.backend.download_media.side_effect = transfer
        self.start()
        await gate.wait()
        self.core.locked = True
        await self.manager.close()
        self.assertFalse(self.manager.jobs)
        self.assertEqual(list((self.root / FOLDER).iterdir()), [])

    async def test_logout_releases_only_its_account(self):
        first = await self.done(self.start())
        other = NS(checked_message=self.backend.checked_message, client=self.backend.client,
                   download_media=self.backend.download_media)
        self.core.accounts.services['b'] = NS(backend=other)
        self.core.account, self.core.backend = 'b', other
        second = await self.done(self.manager.start(42, 8, 'b'))
        await self.manager.release_account('a')
        self.assertNotIn(first.id, self.manager.jobs)
        self.assertIn(second.id, self.manager.jobs)
        self.assertTrue(second.path.exists())

    async def test_protection_or_ttl_prevents_transfer_and_open(self):
        self.message.ttl_period = 60
        job = await self.done(self.start())
        self.assertEqual((job.state, job.error), ('failed', 'permission'))
        self.backend.download_media.assert_not_awaited()
        self.message.ttl_period = 0
        self.manager.retry(job.id, 'a')
        await self.done(job.snapshot())
        directory = job.directory
        self.message.noforwards = True
        result = await self.manager.open(job.id, 'save', 'a')
        self.assertFalse(result['opened'])
        self.assertEqual(job.state, 'failed')
        self.assertFalse(directory.exists())
        self.core.open_file_with_system.assert_not_awaited()

    async def test_cache_reused_and_native_copy_has_original_name_without_deleting_cache(self):
        folder = self.root / 'mobile-media' / 'a'
        folder.mkdir(parents=True)
        cached = folder / '42-7.bin'
        cached.write_bytes(b'original')
        self.core._media_index.return_value = {'42-7': cached.name}
        job = await self.done(self.start())
        self.backend.download_media.assert_not_awaited()
        await self.manager.open(job.id, 'save', 'a')
        called_path = self.core.open_file_with_system.await_args.args[0]
        self.assertEqual(called_path.name, 'fixture.bin')
        self.assertEqual(called_path.read_bytes(), b'original')
        await self.manager.close()
        self.assertTrue(cached.exists())
        self.assertFalse(called_path.exists())

    async def test_ios_viewer_lease_survives_manager_cleanup_until_dismissal(self):
        self.core.system = 'iOS'
        releases = []
        async def native(path, action, *, release):
            releases.append(release)
            return {'opened': True}
        self.core.open_file_with_system.side_effect = native
        job = await self.done(self.start())
        path = job.path
        await self.manager.open(job.id, 'share', 'a')
        await self.manager.close()
        self.assertTrue(path.exists())
        releases[0]()
        releases[0]()
        self.assertFalse(path.exists())
        self.assertEqual(job.exports, 0)

    async def test_ios_account_switch_after_presentation_keeps_native_lease(self):
        self.core.system = 'iOS'
        releases = []
        async def native(path, action, *, release):
            releases.append(release)
            self.core.account = 'b'
            return {'opened': True}
        self.core.open_file_with_system.side_effect = native
        job = await self.done(self.start())
        path = job.path
        result = await self.manager.open(job.id, 'share', 'a')
        self.assertFalse(result['opened'])  # The old UI must discard its response.
        self.assertEqual((job.state, job.exports), ('ready', 1))
        self.assertTrue(path.exists())
        await self.manager.close()
        self.assertTrue(path.exists())
        releases[0]()
        self.assertFalse(path.exists())

    async def test_native_failure_keeps_result_for_another_action(self):
        self.core.open_file_with_system.return_value = {'opened': False}
        job = await self.done(self.start())
        result = await self.manager.open(job.id, 'file', 'a')
        self.assertFalse(result['opened'])
        self.assertEqual((job.state, job.error), ('ready', 'open_failed'))
        self.assertTrue(job.path.exists())
        self.assertEqual(job.exports, 0)

    async def test_retention_evicts_old_owned_result_but_keeps_large_newest(self):
        self.manager.retained_bytes = 10
        first = await self.done(self.start())
        first_path = first.path
        second = await self.done(self.start(8))
        self.assertNotIn(first.id, self.manager.jobs)
        self.assertFalse(first_path.exists())
        self.assertTrue(second.path.exists())

    async def test_large_sparse_result_uses_exact_integers_and_no_bytes_buffer(self):
        size = 3 * 1024 ** 3 + 17
        self.message.file.size = size
        async def transfer(media, path, *, progress, quality):
            progress(size - 1, size)
            self.assertEqual(self.manager.snapshot('a')[0]['bytes'], size - 1)
            with path.open('wb') as stream:
                stream.truncate(size)  # Sparse local fixture, not network throughput.
            return path
        self.backend.download_media.side_effect = transfer
        job = await self.done(self.start())
        self.assertEqual((job.current, job.total, job.snapshot()['percent']), (size, size, 100))

    async def test_unknown_filename_does_not_escape_owned_directory(self):
        self.message.file.name = '../../private\\fixture\x00.bin'
        job = await self.done(self.start())
        self.assertEqual(job.name, 'fixture.bin')
        self.assertEqual(job.path.parent, self.root / FOLDER / job.id)

    async def test_deleted_result_returns_to_retryable_state(self):
        job = await self.done(self.start())
        job.path.unlink()
        self.assertFalse((await self.manager.open(job.id, 'file', 'a'))['opened'])
        self.assertEqual((job.state, job.error), ('failed', 'unavailable'))

    async def test_progress_is_throttled_and_transport_restart_can_reduce_bytes(self):
        observed = []
        async def transfer(media, path, *, progress, quality):
            progress(7, 8)
            for _ in range(10000):
                progress(7, 8)
            progress(0, 8)
            observed.append(self.manager.snapshot('a')[0]['bytes'])
            path.write_bytes(b'original')
            return path
        self.backend.download_media.side_effect = transfer
        await self.done(self.start())
        self.assertEqual(observed, [0])
        self.assertLessEqual(len(self.events), 4)

    async def test_secret_non_ttl_export_preserved_but_ttl_is_rejected(self):
        from tg_ascii.secret_chats import secret_peer_id
        peer = secret_peer_id(45)
        record = {'id': 7, 'ttl': 0, 'expires_at': None}
        self.message.protected = True  # Secret means no forwarding, not no local export.
        manager = NS(message_context=lambda *args: [self.message],
                     session_for_peer=lambda peer: NS(messages=[record]))
        self.message.id = 7
        self.backend.secret_chats = manager
        result = self.manager.start(peer, 7, 'a')
        job = await self.done(result)
        self.assertEqual(job.state, 'ready')
        record['ttl'] = 10
        self.assertFalse((await self.manager.open(job.id, 'save', 'a'))['opened'])
        self.assertEqual((job.state, job.error), ('failed', 'permission'))

    async def test_attachment_replaced_during_download_never_becomes_ready(self):
        with patch('tg_ascii_mobile.download_manager.media_identity', side_effect=[('d', 1), ('d', 2)]):
            job = await self.done(self.start())
        self.assertEqual((job.state, job.error), ('failed', 'unavailable'))
        self.assertFalse((self.root / FOLDER / job.id).exists())

    async def test_attachment_replaced_after_download_cannot_be_exported(self):
        with patch('tg_ascii_mobile.download_manager.media_identity', return_value=('d', 1)):
            job = await self.done(self.start())
        with patch('tg_ascii_mobile.download_manager.media_identity', return_value=('d', 2)):
            result = await self.manager.open(job.id, 'share', 'a')
        self.assertFalse(result['opened'])
        self.assertEqual(job.state, 'failed')
        self.core.open_file_with_system.assert_not_awaited()

    async def test_late_cancel_does_not_cancel_the_new_attempt(self):
        result = self.start()
        await self.manager.cancel(result['id'], 'a', attempt=1)
        self.manager.retry(result['id'], 'a', attempt=1)
        late = await self.manager.cancel(result['id'], 'a', attempt=1)
        self.assertEqual((late['state'], late['attempt']), ('queued', 2))
        self.assertEqual((await self.done(result)).state, 'ready')

    async def test_repeated_cancel_and_lock_cannot_interrupt_backend_cleanup(self):
        started, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def transfer(media, path, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cleaning.set()
                await release.wait()  # Models waiting for an already-started disk writer.
                path.write_bytes(b'finished writer')
                raise
        self.backend.download_media.side_effect = transfer
        result = self.start()
        await started.wait()
        job = self.manager.jobs[result['id']]
        directory = job.directory
        cancelling = asyncio.create_task(self.manager.cancel(job.id, 'a'))
        await cleaning.wait()
        self.assertEqual((await self.manager.cancel(job.id, 'a'))['state'], 'cancelling')
        closing = asyncio.create_task(self.manager.close())
        await asyncio.sleep(0)
        self.assertEqual(job.task.cancelling(), 1)
        self.assertFalse(closing.done())
        release.set()
        await asyncio.gather(cancelling, closing)
        self.assertFalse(directory.exists())

    async def test_cancel_completion_does_not_overwrite_a_new_attempt(self):
        started = asyncio.Event()
        async def transfer(media, path, **kwargs):
            started.set()
            await asyncio.Event().wait()
        self.backend.download_media.side_effect = transfer
        result = self.start()
        await started.wait()
        job = self.manager.jobs[result['id']]
        async def complete(media, path, **kwargs):
            path.write_bytes(b'original')
            return path
        def retry_finished(task):
            self.backend.download_media.side_effect = complete
            self.manager.retry(job.id, 'a')
        job.task.add_done_callback(retry_finished)
        returned = await self.manager.cancel(job.id, 'a')
        self.assertEqual(returned['attempt'], 2)
        self.assertNotEqual(returned['state'], 'cancelled')
        self.assertEqual((await self.done(result)).state, 'ready')


class DownloadCoreIntegrationTests(IsolatedAsyncioTestCase):
    async def test_real_core_dispatch_start_status_and_lock_cleanup(self):
        from tg_ascii_mobile.core import Core
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        core = Core(Path(folder.name), 'Android')
        core.loop.close()
        core.loop = asyncio.get_running_loop()
        self.addAsyncCleanup(core.close_downloads)
        message = NS(media=NS(), file=NS(name='fixture.bin', size=8))
        async def transfer(media, path, *, progress, quality):
            path.write_bytes(b'original')
            progress(8, 8)
            return path
        backend = NS(client=NS(get_entity=AsyncMock(return_value=NS())),
                     checked_message=AsyncMock(return_value=message), download_media=transfer)
        core.accounts = NS(current='qa', services={'qa': NS(backend=backend)})
        core.emit = lambda *args: None
        result = await core.call('download_start', {'peer': 42, 'id': 7, 'account': 'qa'})
        manager = core.downloads()
        await manager.jobs[result['id']].task
        status = await core.call('download_status', {'account': 'qa'})
        self.assertEqual(status['items'][0]['state'], 'ready')
        directory = manager.jobs[result['id']].directory
        core.lock_record = lambda: {'enabled': True}
        core.lock()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        with self.assertRaises(PermissionError):
            await core.call('download_status', {'account': 'qa'})
        self.assertTrue(manager.closed)
        await manager.close()
        self.assertFalse(directory.exists())
