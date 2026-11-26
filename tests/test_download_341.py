"""Download progress, ownership and bounded secret-memory regression tests."""
import asyncio
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from telethon import errors
from tg_ascii.backend import TelegramBackend
from tg_ascii.secret_chats import SecretMedia
from tg_ascii.transfers import DownloadProgress, owned_thread


class Downloads341(IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'result.bin'
        self.client = AsyncMock()
        self.client.add_event_handler = Mock()
        self.backend = TelegramBackend(self.client)

    async def test_progress_uses_written_bytes_and_deduplicates_callbacks(self):
        reports = []
        async def download(media, *, file, progress_callback, **options):
            file.write(b'abc')
            for _ in range(10_000):
                await progress_callback(999, 6)
            file.write(b'def')
            await progress_callback(3, 6)
            return file
        self.client.download_media.side_effect = download
        await self.backend.download_media(object(), self.path, lambda *args: reports.append(args))
        self.assertEqual(reports, [(3, 6), (6, 6)])
        self.assertEqual(self.path.read_bytes(), b'abcdef')

    async def test_progress_without_network_callbacks_finishes_with_actual_size(self):
        progress = AsyncMock()
        async def download(media, *, file, **options):
            file.write(b'cached photo bytes')
            return file
        self.client.download_media.side_effect = download
        await self.backend.download_media(object(), self.path, progress)
        progress.assert_awaited_once_with(18, 18)

    async def test_progress_accepts_files_larger_than_four_gibibytes_without_buffering_them(self):
        reports = []
        large = 5 * 1024**3 + 7
        async def download(media, *, file, progress_callback, **options):
            file.seek(large - 1)
            file.write(b'x')
            await progress_callback(large, large)
            return file
        self.client.download_media.side_effect = download
        await self.backend.download_media(object(), self.path, lambda *args: reports.append(args))
        self.assertEqual(self.path.stat().st_size, large)
        self.assertEqual(reports, [(large, large)])

    async def test_unknown_and_large_totals_are_safe(self):
        reports = []
        progress = DownloadProgress(lambda *args: reports.append(args))
        for total in (None, float('nan'), float('inf'), -1, 2):
            await progress.report(3, total)
        await progress.report(3, 10**1000)
        self.assertEqual(reports, [(3, 0), (3, 10**1000)])

    async def test_flood_retry_resets_progress_instead_of_accumulating_bytes(self):
        reports, attempts = [], 0
        async def download(media, *, file, progress_callback, **options):
            nonlocal attempts
            attempts += 1
            file.write(b'abc')
            await progress_callback(3, 6)
            if attempts == 1:
                raise errors.FloodWaitError(request=None, capture=1)
            file.write(b'def')
            await progress_callback(6, 6)
            return file
        self.client.download_media.side_effect = download
        with patch('tg_ascii.flood_control.FloodGate.passage', new=AsyncMock()):
            await self.backend.download_media(object(), self.path, lambda *args: reports.append(args))
        self.assertEqual(reports, [(3, 6), (0, 6), (3, 6), (6, 6)])
        self.assertEqual(self.path.read_bytes(), b'abcdef')
        self.assertFalse(list(self.path.parent.glob('.tg-download-*')))

    async def test_secret_failure_preserves_destination_and_removes_partial(self):
        self.path.write_bytes(b'previous')
        async def download(media, destination, **options):
            Path(destination).write_bytes(b'partial')
            raise OSError('disk full')
        self.backend.secret_chats = NS(download_media=download)
        with self.assertRaises(OSError):
            await self.backend.download_media(SecretMedia(1, 2, 3, 'file'), self.path)
        self.assertEqual(self.path.read_bytes(), b'previous')
        self.assertFalse(list(self.path.parent.glob('.tg-download-*')))

    async def test_secret_concurrency_is_one_and_queued_cancel_creates_no_partial(self):
        entered, release = asyncio.Event(), asyncio.Event()
        active, peak = 0, 0
        async def download(media, destination, **options):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                entered.set()
                await release.wait()
                Path(destination).write_bytes(b'ok')
                return destination
            finally:
                active -= 1
        self.backend.secret_chats = NS(download_media=download)
        tasks = [asyncio.create_task(self.backend.download_media(SecretMedia(1, n, n, 'file'),
                 self.path.with_name(f'{n}.bin'))) for n in range(12)]
        await entered.wait()
        await asyncio.sleep(0)
        self.assertEqual(active, 1)
        self.assertEqual(len(list(self.path.parent.glob('.tg-download-*'))), 1)
        for task in tasks[1:]:
            task.cancel()
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.assertEqual(peak, 1)
        self.assertEqual(len(list(self.path.parent.glob('*.bin'))), 1)

    async def test_cancel_waits_for_inflight_file_write_before_cleanup(self):
        entered, release = threading.Event(), threading.Event()
        def write():
            entered.set()
            release.wait(2)
            self.path.write_bytes(b'late bytes')
        async def operation():
            try:
                await owned_thread(write)
            finally:
                self.path.unlink(missing_ok=True)
        task = asyncio.create_task(operation())
        await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.path.exists())

