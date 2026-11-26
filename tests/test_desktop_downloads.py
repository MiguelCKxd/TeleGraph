import asyncio
from pathlib import Path
import queue
import tempfile
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from telethon.errors import FileReferenceExpiredError
from telethon import types
from tg_ascii.desktop_downloads import DownloadCenter, DownloadQueue, enqueue, stop_account, MAX_JOBS


class Worker:
    def __init__(self):
        self.loop = asyncio.get_running_loop()
        self.events = queue.SimpleQueue()
        self.tasks = []

    def submit(self, coroutine, success, failed):
        task = self.loop.create_task(coroutine)
        self.tasks.append(task)
        return task

    def drain(self):
        while not self.events.empty():
            callback, value = self.events.get_nowait()
            callback(value)


class DownloadFixture(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / 'result'
        self.worker = Worker()
        self.manager = DownloadQueue(self.worker)

    async def asyncTearDown(self):
        self.manager.close()
        await asyncio.gather(*self.worker.tasks, return_exceptions=True)
        self.folder.cleanup()

    async def settle(self):
        for _ in range(8):
            await asyncio.sleep(0)
            self.worker.drain()


class DownloadQueueTests(DownloadFixture):
    async def test_progress_stores_only_latest_state_and_completes_once(self):
        release = asyncio.Event()
        async def operation(progress, retry):
            for value in range(10_000):
                progress(value, 20_000)
            await release.wait()
            self.path.write_bytes(b'ok')
            return self.path
        done = Mock()
        job = self.manager.add(('a',), 'file', operation, lambda: True, done)
        await self.settle()
        self.assertEqual((job.current, job.total), (9999, 20000))
        self.assertTrue(self.worker.events.empty())
        release.set(); await self.settle()
        self.assertEqual(job.state, 'done')
        done.assert_called_once_with(self.path)

    async def test_cancel_retains_slot_until_actual_cleanup_and_retry_starts_zero(self):
        entered, cleanup = asyncio.Event(), asyncio.Event()
        attempts = []
        async def operation(progress, retry):
            attempts.append(retry)
            progress(50, 100)
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                await cleanup.wait()
        jobs = [self.manager.add((n,), str(n), operation, lambda: True) for n in range(3)]
        await entered.wait()
        self.manager.cancel(jobs[0])
        await asyncio.sleep(0); await asyncio.sleep(0)
        self.assertEqual([j.state for j in jobs], ['cancelling', 'running', 'queued'])
        for _ in range(20):
            self.manager.cancel(jobs[0])
        await asyncio.sleep(0)
        self.assertEqual(jobs[0].state, 'cancelling')
        cleanup.set(); await self.settle()
        self.assertEqual(jobs[0].state, 'cancelled')
        self.assertEqual(jobs[2].state, 'running')
        self.manager.retry(jobs[0])
        self.assertEqual((jobs[0].current, jobs[0].total, jobs[0].generation), (0, 0, 1))

    async def test_cancel_before_worker_starts_is_completed_and_does_not_stall_queue(self):
        operation = AsyncMock(return_value=self.path)
        job = self.manager.add((1,), 'file', operation, lambda: True)
        self.manager.cancel(job)
        await self.settle()
        self.assertEqual(job.state, 'cancelled')
        operation.assert_not_awaited()

    async def test_queue_bound_and_duplicate_requests(self):
        blocked = asyncio.Event()
        async def operation(progress, retry):
            await blocked.wait()
        jobs = [self.manager.add((n,), str(n), operation, lambda: True) for n in range(MAX_JOBS)]
        self.assertIs(self.manager.add((0,), 'same', operation, lambda: True), jobs[0])
        with self.assertRaises(ValueError):
            self.manager.add(('extra',), 'extra', operation, lambda: True)
        self.assertEqual(len(self.worker.tasks), 2)
        self.manager.cancel(jobs[-1])
        self.manager.add(('extra',), 'extra', operation, lambda: True)
        self.assertEqual(len(self.manager.jobs), MAX_JOBS)

    async def test_logout_closes_only_downloads_of_that_account(self):
        first=NS(ui_account='a',_download_center=NS(close=Mock(),window=None))
        other=NS(ui_account='b',_download_center=NS(close=Mock(),window=None))
        owner=NS(ui_account='b',_app_windows=[first,other],_chat_windows=[])
        stop_account(owner,'a')
        first._download_center.close.assert_called_once_with()
        other._download_center.close.assert_not_called()

    async def test_account_change_discards_late_success_and_closes_pending(self):
        valid = [True]
        release = asyncio.Event()
        async def operation(progress, retry):
            await release.wait()
            self.path.write_bytes(b'completed just before switch')
            return self.path
        done = Mock()
        job = self.manager.add((1,), 'file', operation, lambda: valid[0], done)
        await self.settle(); valid[0] = False; release.set(); await self.settle()
        self.assertEqual(job.state, 'cancelled')
        done.assert_not_called()
        self.manager.retry(job)
        self.assertEqual(job.state, 'cancelled')

    async def test_failed_retry_gets_new_attempt_without_automatic_loop(self):
        attempts = []
        async def operation(progress, retry):
            attempts.append(retry)
            if not retry:
                raise OSError('disk full')
            self.path.write_bytes(b'recovered')
            return self.path
        job = self.manager.add((1,), 'file', operation, lambda: True)
        await self.settle()
        self.assertEqual(job.state, 'failed')
        self.assertEqual(attempts, [False])
        self.manager.retry(job); await self.settle()
        self.assertEqual((job.state, attempts), ('done', [False, True]))


class DownloadUiTests(DownloadFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.root = tk.Tk(); self.root.withdraw()
        self.backend = NS(download_media=AsyncMock())
        self.app = NS(root=self.root, ui_account='a', service=NS(backend=self.backend), worker=self.worker,
                      show_error=Mock(), closed=False, closing=False)
        def dialog(title, size):
            window = tk.Toplevel(self.root)
            frame = ttk.Frame(window); frame.pack()
            return window, frame
        self.app.dialog = dialog
        self.center = DownloadCenter(self.app)
        self.app._download_center = self.center
        self.manager.close(); self.manager = self.center.queue

    async def asyncTearDown(self):
        self.center.close()
        self.root.destroy()
        await super().asyncTearDown()

    async def test_ui_uses_one_timer_even_after_reopening(self):
        async def operation(progress, retry):
            await asyncio.Event().wait()
        self.manager.add((1,), 'file', operation, lambda: True)
        self.center.show(); self.center.refresh(); self.center.refresh()
        self.assertEqual(len(self.root.tk.call('after', 'info')), 1)
        self.center.window.destroy()
        self.center.show()
        self.assertEqual(len(self.root.tk.call('after', 'info')), 1)
        self.assertEqual(len(self.center.tree.get_children()), 1)

    async def test_arrow_navigation_selects_the_job_to_cancel(self):
        async def operation(progress, retry):
            await asyncio.Event().wait()
        first = self.manager.add((1,), 'first', operation, lambda: True)
        second = self.manager.add((2,), 'second', operation, lambda: True)
        self.center.show()
        self.assertIs(self.center.selected(), second)
        self.center.tree.tk.call('ttk::treeview::Keynav', self.center.tree, 'up')
        self.center.refresh()
        self.assertIs(self.center.selected(), first)
        self.center.action(self.manager.cancel)
        await self.settle()
        self.assertEqual(first.state, 'cancelled')
        self.assertEqual(second.state, 'running')

    async def test_expired_reference_refreshes_policy_before_downloading(self):
        async def download(media, target, progress):
            raise FileReferenceExpiredError(request=None)
        self.backend.download_media.side_effect = download
        message = NS(id=3, media=object(), filename='photo.jpg', protected=False)
        with patch('tg_ascii.desktop_media_lifetime.source_message', new=AsyncMock(return_value=NS(protected=True))):
            job = enqueue(self.app, message, 42, self.path)
            await self.settle()
        self.assertEqual(job.state, 'failed')
        self.assertIsInstance(job.error, PermissionError)
        self.assertEqual(self.backend.download_media.await_count, 1)

    async def test_retry_fetches_fresh_source_and_keeps_original_scope(self):
        sources = []
        async def download(media, target, progress):
            sources.append(media)
            if len(sources) == 1:
                raise ConnectionError('offline')
            Path(target).write_bytes(b'ok')
            return target
        self.backend.download_media.side_effect = download
        old, fresh = object(), object()
        message = NS(id=3, media=old, filename='file', protected=False)
        with patch('tg_ascii.desktop_media_lifetime.source_message', new=AsyncMock(return_value=fresh)) as fetch:
            job = enqueue(self.app, message, 42, self.path)
            await self.settle()
            self.manager.retry(job); await self.settle()
        self.assertEqual(sources, [old, fresh])
        self.assertEqual(fetch.await_count, 2)  # retry source + final export permission
        fetch.assert_awaited_with(self.backend, 42, 3)
        self.assertEqual(job.state, 'done')

    async def test_protection_changed_during_download_keeps_existing_destination(self):
        self.path.write_bytes(b'previous file')
        async def download(media, target, progress):
            Path(target).write_bytes(b'new protected file')
            return target
        self.backend.download_media.side_effect = download
        message = NS(id=3, media=object(), filename='file', protected=False)
        with patch('tg_ascii.desktop_media_lifetime.source_message', new=AsyncMock(return_value=NS(protected=True))):
            job = enqueue(self.app, message, 42, self.path)
            await self.settle()
        self.assertEqual(job.state, 'failed')
        self.assertIsInstance(job.error, PermissionError)
        self.assertEqual(self.path.read_bytes(), b'previous file')
        self.assertFalse(list(self.path.parent.glob('.tg-export-*')))

    async def test_media_replaced_during_download_never_publishes_old_attachment(self):
        def document(ident):
            return types.Document(id=ident,access_hash=0,file_reference=b'',date=None,
                                  mime_type='application/octet-stream',size=3,dc_id=1,attributes=[])
        async def download(media,target,progress):
            Path(target).write_bytes(b'old')
            return target
        self.backend.download_media.side_effect=download
        message=NS(id=3,media=document(1),filename='file',protected=False)
        with patch('tg_ascii.desktop_media_lifetime.source_message',new=AsyncMock(return_value=NS(media=document(2)))):
            job=enqueue(self.app,message,42,self.path)
            await self.settle()
        self.assertEqual(job.state,'failed')
        self.assertIsInstance(job.error,ValueError)
        self.assertFalse(self.path.exists())
        self.assertFalse(list(self.path.parent.glob('.tg-export-*')))
