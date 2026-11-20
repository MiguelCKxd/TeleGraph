"""Regression tests for the 1.3.2 network/stability optimisations."""
import asyncio
import gc
import os
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from telethon import errors, types

from tg_ascii import flood_control, media_cache, tk_safety
from tg_ascii.recovery import record_failure, _bursts


def flood(seconds):
    return errors.FloodWaitError(request=None, capture=seconds)


class FloodControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_short_wait_is_absorbed_and_operation_repeated(self):
        owner = SimpleNamespace()
        calls = []

        async def operation():
            calls.append(time.monotonic())
            if len(calls) == 1:
                raise flood(1)
            return 'ok'

        with patch('tg_ascii.flood_control.asyncio.sleep', new=AsyncMock()) as sleep:
            self.assertEqual(await flood_control.read_with_flood_wait(owner, 'download', operation), 'ok')
        self.assertEqual(len(calls), 2)
        sleep.assert_awaited()
        self.assertGreaterEqual(sleep.await_args.args[0], 1)

    async def test_long_wait_is_raised_unchanged(self):
        owner = SimpleNamespace()
        operation = AsyncMock(side_effect=flood(120))
        with self.assertRaises(errors.FloodWaitError):
            await flood_control.read_with_flood_wait(owner, 'download', operation)
        operation.assert_awaited_once()

    async def test_gate_is_shared_by_category_and_isolated_per_owner(self):
        first, second = SimpleNamespace(), SimpleNamespace()
        flood_control.gate(first, 'download').hold(20)
        self.assertGreater(flood_control.gate(first, 'download').remaining(), 19)
        self.assertEqual(flood_control.gate(first, 'history').remaining(), 0)
        self.assertEqual(flood_control.gate(second, 'download').remaining(), 0)

    async def test_waiting_callers_pass_after_hold_without_extra_requests(self):
        owner = SimpleNamespace()
        flood_control.gate(owner, 'download').hold(1)
        operation = AsyncMock(return_value='done')
        with patch('tg_ascii.flood_control.asyncio.sleep', new=AsyncMock()) as sleep:
            results = await asyncio.gather(*(flood_control.read_with_flood_wait(owner, 'download', operation)
                                             for _ in range(5)))
        self.assertEqual(results, ['done'] * 5)
        self.assertEqual(operation.await_count, 5)
        self.assertEqual(sleep.await_count, 5)

    async def test_attempts_are_bounded(self):
        owner = SimpleNamespace()
        operation = AsyncMock(side_effect=flood(1))
        with patch('tg_ascii.flood_control.asyncio.sleep', new=AsyncMock()):
            with self.assertRaises(errors.FloodWaitError):
                await flood_control.read_with_flood_wait(owner, 'download', operation, attempts=2)
        self.assertEqual(operation.await_count, 3)


class MediaCacheTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.backend = SimpleNamespace()
        media_cache.configure(self.backend, self.root, 'abc')

    def tearDown(self):
        self.folder.cleanup()

    def photo(self, ident=7):
        return types.Photo(id=ident, access_hash=1, file_reference=b'', date=None, sizes=[], dc_id=2)

    def test_entry_is_keyed_by_immutable_media_id_and_thumb(self):
        message_media = types.MessageMediaPhoto(photo=self.photo(99))
        entry = media_cache.preview_entry(self.backend, message_media, 'm', '.jpg')
        self.assertEqual(entry.name, 'p99-m.jpg')
        self.assertIn('abc', entry.parts)
        self.assertIsNone(media_cache.preview_entry(SimpleNamespace(), message_media, 'm', '.jpg'))
        self.assertIsNone(media_cache.preview_entry(self.backend, SimpleNamespace(), 'm', '.jpg'))
        self.assertIsNone(media_cache.preview_entry(self.backend, message_media, 'm', '.exe'))

    def test_store_fetch_round_trip_copies_to_requested_target(self):
        entry = media_cache.preview_entry(self.backend, self.photo(), 'x', '.jpg')
        source = self.root / 'downloaded.jpg'
        source.write_bytes(b'jpeg-bytes')
        media_cache.store(entry, source)
        target = self.root / 'session' / 'view-thumb.jpg'
        self.assertTrue(media_cache.fetch(entry, target))
        self.assertEqual(target.read_bytes(), b'jpeg-bytes')
        self.assertFalse(media_cache.fetch(media_cache.preview_entry(self.backend, self.photo(8), 'x', '.jpg'), target))

    def test_empty_files_are_never_cached_or_served(self):
        entry = media_cache.preview_entry(self.backend, self.photo(), 'x', '.jpg')
        empty = self.root / 'empty.jpg'
        empty.write_bytes(b'')
        media_cache.store(entry, empty)
        self.assertFalse(entry.exists())

    def test_prune_evicts_oldest_until_target(self):
        folder = self.root / 'prune'
        folder.mkdir()
        for index in range(10):
            path = folder / f'{index}.bin'
            path.write_bytes(b'x' * 100)
            os.utime(path, (1000 + index, 1000 + index))
        removed = media_cache.prune(folder, max_bytes=500, target_bytes=300)
        self.assertEqual(removed, 7)
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ['7.bin', '8.bin', '9.bin'])

    def test_purge_removes_only_that_account(self):
        for account in ('abc', 'other'):
            folder = media_cache.cache_directory(self.root, account)
            folder.mkdir(parents=True)
            (folder / 'f').write_bytes(b'1')
        media_cache.purge(self.root, 'abc')
        self.assertFalse(media_cache.account_directory(self.root, 'abc').exists())
        self.assertTrue((media_cache.cache_directory(self.root, 'other') / 'f').exists())


class DownloadMediaCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_cached_thumbnail_skips_network_and_flood_waits_are_retried(self):
        from tg_ascii.backend import TelegramBackend
        client = AsyncMock()
        client.add_event_handler = Mock()
        backend = TelegramBackend(client)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            media_cache.configure(backend, root, 'acc')
            size = types.PhotoSize(type='m', w=320, h=320, size=10)
            photo = types.Photo(id=5, access_hash=1, file_reference=b'', date=None, sizes=[size], dc_id=2)
            calls = []

            async def download(media, file, progress_callback, thumb):
                calls.append(thumb)
                if len(calls) == 1:
                    raise flood(1)
                file.write(b'thumb')
                return file

            client.download_media.side_effect = download
            with patch('tg_ascii.flood_control.asyncio.sleep', new=AsyncMock()):
                first = await backend.download_media(photo, root / 'a-thumb.jpg', thumbnail=True)
            self.assertEqual(first.read_bytes(), b'thumb')
            self.assertEqual(calls, ['m', 'm'])
            second = await backend.download_media(photo, root / 'other-view.jpg', thumbnail=True)
            self.assertEqual(second.read_bytes(), b'thumb')
            self.assertEqual(len(calls), 2)  # Served from the persistent cache.


class TkImageGuardTests(unittest.TestCase):
    def test_worker_thread_finalizer_is_deferred_to_tk_thread(self):
        tk_safety.install()
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest('No display')
        try:
            root.withdraw()
            image = tk.PhotoImage(master=root, width=2, height=2)
            name = image.name
            holder = [image]
            del image

            def drop():
                holder.clear()
                gc.collect()

            thread = threading.Thread(target=drop)
            thread.start()
            thread.join()
            self.assertIn(name, root.tk.splitlist(root.tk.call('image', 'names')))
            self.assertGreaterEqual(tk_safety.pending(), 1)
            tk_safety.drain()
            self.assertNotIn(name, root.tk.splitlist(root.tk.call('image', 'names')))
            # Main-thread destruction keeps the original immediate behaviour.
            direct = tk.PhotoImage(master=root, width=2, height=2)
            direct_name = direct.name
            del direct
            gc.collect()
            self.assertNotIn(direct_name, root.tk.splitlist(root.tk.call('image', 'names')))
        finally:
            tk_safety.drain()
            root.destroy()


class DraftRejectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_permanent_refusal_does_not_block_other_chats_or_repeat(self):
        from tg_ascii.drafts import DraftManager
        record = lambda text: {'text': text, 'formats': [], 'custom': [], 'reply': None, 'pending': True, 'unsupported': False}
        records = {'acc': {'1': record('channel'), '2': record('friend')}}
        synced = []
        store = SimpleNamespace(pending_records=lambda account=None: {k: dict(v) for k, v in records.items()},
                                mark_synced=lambda owner, peer, rec: synced.append(peer), flush=lambda: None)
        backend = SimpleNamespace(save_draft=AsyncMock(side_effect=lambda peer, *a: (_ for _ in ()).throw(
            errors.ChatAdminRequiredError(request=None)) if peer == 1 else True))
        app = SimpleNamespace(demo=False, service=SimpleNamespace(entries={'acc': {}}, services={'acc': SimpleNamespace(backend=backend)}))
        manager = object.__new__(DraftManager)
        manager.app, manager.store, manager.sync_lock = app, store, None
        await manager.sync_pending()
        self.assertEqual(synced, ['2'])
        backend.save_draft.reset_mock()
        await manager.sync_pending()
        self.assertEqual([call.args[0] for call in backend.save_draft.await_args_list], [2])
        records['acc']['1']['text'] = 'edited'
        backend.save_draft.reset_mock()
        await manager.sync_pending()
        self.assertIn(1, [call.args[0] for call in backend.save_draft.await_args_list])

    async def test_transient_failure_keeps_original_stop_and_raise(self):
        from tg_ascii.drafts import DraftManager
        record = {'text': 'x', 'formats': [], 'custom': [], 'reply': None, 'pending': True, 'unsupported': False}
        store = SimpleNamespace(pending_records=lambda account=None: {'acc': {'1': dict(record), '2': dict(record)}},
                                mark_synced=Mock(), flush=lambda: None)
        backend = SimpleNamespace(save_draft=AsyncMock(side_effect=ConnectionError()))
        app = SimpleNamespace(demo=False, service=SimpleNamespace(entries={'acc': {}}, services={'acc': SimpleNamespace(backend=backend)}))
        manager = object.__new__(DraftManager)
        manager.app, manager.store, manager.sync_lock = app, store, None
        with self.assertRaises(ConnectionError):
            await manager.sync_pending()
        self.assertEqual(backend.save_draft.await_count, 1)


class DiagnosticsBurstTests(unittest.TestCase):
    def test_identical_bursts_are_summarised(self):
        _bursts.clear()
        with tempfile.TemporaryDirectory() as folder:
            for _ in range(200):
                record_failure(folder, 'request', flood(3))
            text = (Path(folder) / 'diagnostics.log').read_text(encoding='utf-8')
            self.assertEqual(text.count('request FloodWaitError'), 5)
            with patch('tg_ascii.recovery.time.monotonic', return_value=time.monotonic() + 60):
                record_failure(folder, 'request', flood(3))
            text = (Path(folder) / 'diagnostics.log').read_text(encoding='utf-8')
            self.assertIn('(+195 repeated)', text)
        _bursts.clear()


class EmojiDocumentGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_document_is_not_an_error(self):
        from tg_ascii.animation import emoji_file
        self.assertIsNone(await emoji_file(SimpleNamespace(), None, 'acc', None))


class PumpBackoffTests(unittest.TestCase):
    def test_idle_pump_backs_off_and_activity_resets(self):
        import queue
        from tg_ascii.desktop import Desktop
        delays = []
        events = queue.SimpleQueue()
        root = SimpleNamespace(after=lambda delay, callback: delays.append(delay))
        app = SimpleNamespace(closed=False, closing=False, root=root, worker=SimpleNamespace(events=events),
                              show_error=Mock(), pump=Mock(), finish_close=None)
        for _ in range(40):
            Desktop.pump(app)
        self.assertEqual(delays[0], 30)
        self.assertEqual(delays[-1], 50)
        events.put((Mock(), 1))
        Desktop.pump(app)
        self.assertEqual(delays[-1], 8)
        Desktop.pump(app)
        self.assertEqual(delays[-1], 30)


class MacThemeTests(unittest.TestCase):
    @unittest.skipUnless(__import__('sys').platform == 'darwin', 'macOS only')
    def test_native_reader_matches_defaults_command(self):
        import subprocess
        from tg_ascii.themes import _mac_native_theme
        native = _mac_native_theme()
        output = subprocess.run(['/usr/bin/defaults', 'read', '-g', 'AppleInterfaceStyle'],
                                capture_output=True, text=True).stdout.strip().lower()
        self.assertEqual(native, 'dark' if output == 'dark' else 'light')


if __name__ == '__main__':
    unittest.main()
