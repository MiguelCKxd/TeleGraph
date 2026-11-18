"""Regressions for diagnostic file handles that Windows refuses to delete."""
from concurrent.futures import ThreadPoolExecutor
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tg_ascii.recovery import record_failure


class DiagnosticTests(unittest.TestCase):
    def test_each_write_releases_its_stream_and_does_not_retain_a_logger(self):
        handlers = []
        def make_handler(*args, **kwargs):
            handler = RotatingFileHandler(*args, **kwargs)
            handlers.append(handler)
            return handler
        before = set(logging.Logger.manager.loggerDict)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'diagnostics.log'
            with patch('tg_ascii.recovery.RotatingFileHandler', side_effect=make_handler):
                for _ in range(3):
                    record_failure(folder, 'connection', OSError('private payload'))
                    self.assertTrue(all(handler.stream is None for handler in handlers))
            text = path.read_text(encoding='utf-8')
            self.assertEqual(text.count('connection OSError'), 3)
            self.assertNotIn('private payload', text)
            self.assertEqual(set(logging.Logger.manager.loggerDict), before)
            path.unlink()  # Also exercises the actual Windows filesystem on Windows.

    def test_concurrent_workers_keep_complete_records_and_no_open_streams(self):
        with tempfile.TemporaryDirectory() as folder:
            with ThreadPoolExecutor(max_workers=6) as pool:
                list(pool.map(lambda index: record_failure(folder, f'job_{index}', ValueError()), range(60)))
            path = Path(folder) / 'diagnostics.log'
            rows = path.read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(rows), 60)
            self.assertEqual({row.split()[-2] for row in rows}, {f'job_{i}' for i in range(60)})
            path.rename(Path(folder) / 'closed.log')

    def test_rotation_keeps_one_backup_without_leaking_file_handles(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'diagnostics.log'
            path.write_text('old\n' * (256 * 1024 // 4), encoding='utf-8')
            record_failure(folder, 'connection', TimeoutError())
            self.assertIn('connection TimeoutError', path.read_text(encoding='utf-8'))
            self.assertEqual({p.name for p in Path(folder).iterdir()}, {'diagnostics.log', 'diagnostics.log.1'})
            for item in Path(folder).iterdir():
                item.unlink()

    def test_write_failure_still_closes_handler_and_preserves_original_operation(self):
        with tempfile.TemporaryDirectory() as folder:
            handler = RotatingFileHandler(Path(folder) / 'diagnostics.log', encoding='utf-8')
            with patch('tg_ascii.recovery.RotatingFileHandler', return_value=handler), \
                    patch.object(handler, 'handle', side_effect=OSError('disk full')):
                record_failure(folder, 'connection', ConnectionError('original failure'))
            self.assertIsNone(handler.stream)


if __name__ == '__main__':
    unittest.main()
