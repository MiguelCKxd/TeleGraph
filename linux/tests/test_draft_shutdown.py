"""Durable drafts must never block Tk or discard temporary attachments."""
import asyncio
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from tg_ascii.desktop import Desktop
from tg_ascii.drafts import DraftManager, DraftStore


class DraftShutdownTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(self.media.cleanup)
        self.source = Path(self.media.name) / 'recording.ogg'
        self.source.write_bytes(b'audio that must survive application exit')
        self.editor = Mock()
        self.editor.get.return_value = 'Unsent recording'
        self.app = SimpleNamespace(
            demo=False, preferences=SimpleNamespace(path=Path(self.folder.name) / 'preferences.json'),
            editor=self.editor, active=42, ui_account='account', stage='ready',
            attachment=self.source, media_temps=[self.media], snapshot_custom=Mock(return_value=[]),
            snapshot_formats=Mock(return_value=[]), root=Mock(), closed=False, closing=True,
            show_error=Mock(), worker=Mock(), status=Mock())
        self.manager = DraftManager(self.app)
        self.app.draft_manager = self.manager

    async def wait_started(self, event):
        async with asyncio.timeout(3):
            while not event.is_set():
                await asyncio.sleep(.001)

    async def test_capture_only_reads_composer_and_registers_attachment_without_copy_or_disk_write(self):
        with patch.object(self.manager.store, '_copy_asset') as copy, patch('tg_ascii.drafts.write_json') as write:
            self.manager.capture_close()
            copy.assert_not_called()
            write.assert_not_called()
        self.assertTrue(self.manager.close_pending)
        self.assertEqual(self.manager.store.get('account', 42)['files'], [str(self.source.resolve())])
        self.assertFalse((Path(self.folder.name) / 'draft-assets').exists())
        await self.manager.flush_close()

    async def test_slow_copy_runs_off_ui_and_keeps_temporary_media_alive_until_atomic_backup(self):
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        ui_thread = threading.get_ident()
        actual_copy = self.manager.store._copy_asset

        def copy(source, target):
            self.assertNotEqual(threading.get_ident(), ui_thread)
            started.set()
            if not release.wait(3):
                raise TimeoutError('test did not release attachment copy')
            actual_copy(source, target)

        self.manager.capture_close()
        with patch.object(self.manager.store, '_copy_asset', side_effect=copy):
            saving = asyncio.create_task(self.manager.flush_close())
            await self.wait_started(started)
            # This snapshot can take the store lock while disk work is blocked.
            self.editor.get.return_value = 'Edited while saving'
            self.manager.snapshot()
            Desktop.finish_close(self.app, None)
            self.app.root.destroy.assert_not_called()
            self.assertTrue(self.source.exists())
            release.set()
            await saving
        restored = DraftStore(self.folder.name).get('account', 42)
        self.assertEqual(restored['text'], 'Edited while saving')
        saved = Path(restored['files'][0])
        self.assertNotEqual(saved, self.source)
        self.assertEqual(saved.read_bytes(), self.source.read_bytes())
        Desktop.finish_close(self.app, None)
        self.assertFalse(self.source.exists())
        self.assertTrue(saved.exists())
        self.app.root.destroy.assert_called_once()

    async def test_copy_failure_retains_media_and_stale_close_timer_cannot_discard_it(self):
        error = OSError('disk full')
        self.manager.capture_close()
        with patch.object(self.manager.store, '_copy_asset', side_effect=error):
            with self.assertRaises(OSError):
                await self.manager.flush_close()
        Desktop.finish_close(self.app, error)
        self.assertFalse(self.app.closing)
        self.app.show_error.assert_called_once_with(error)
        Desktop.finish_close(self.app, None)  # Original three-second fallback.
        self.app.root.destroy.assert_not_called()
        self.assertTrue(self.source.exists())
        self.app.closing = True
        self.manager.capture_close()
        await self.manager.flush_close()
        saved = Path(DraftStore(self.folder.name).get('account', 42)['files'][0])
        Desktop.finish_close(self.app, None)
        self.assertTrue(saved.exists())
        self.assertFalse(self.source.exists())

    async def test_cancel_waits_for_running_copy_instead_of_allowing_temporary_cleanup(self):
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        actual_copy = self.manager.store._copy_asset

        def copy(source, target):
            started.set()
            if not release.wait(3):
                raise TimeoutError('test did not release attachment copy')
            actual_copy(source, target)

        self.manager.capture_close()
        with patch.object(self.manager.store, '_copy_asset', side_effect=copy):
            saving = asyncio.create_task(self.manager.flush_close())
            await self.wait_started(started)
            saving.cancel()
            await asyncio.sleep(.01)
            self.assertTrue(self.manager.close_pending)
            self.assertFalse(saving.done())
            Desktop.finish_close(self.app, None)
            self.app.root.destroy.assert_not_called()
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await saving
        self.assertFalse(self.manager.close_pending)
        saved = Path(DraftStore(self.folder.name).get('account', 42)['files'][0])
        self.assertEqual(saved.read_bytes(), self.source.read_bytes())

    async def test_telegram_failure_during_exit_still_closes_connection_after_local_backup(self):
        self.app.closing = False
        self.app.busy = False
        self.app.cancel_global_search = Mock()
        self.app.inline_notice = Mock()
        self.app.cancel_qr = Mock()
        self.app.stop_typing = Mock()
        self.app.service = SimpleNamespace(close=AsyncMock())
        self.app.finish_close = Mock()
        with patch('tg_ascii.interface_windows.close_chat_windows'), patch.object(
                self.manager, 'sync_pending', side_effect=ValueError('Telegram rejected draft')):
            Desktop.close(self.app)
            coroutine = self.app.worker.submit.call_args.args[0]
            await coroutine
        self.app.service.close.assert_awaited_once()
        self.assertIsNotNone(DraftStore(self.folder.name).get('account', 42))


if __name__ == '__main__':
    unittest.main()
