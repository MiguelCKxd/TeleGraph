import concurrent.futures
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from tg_ascii import native_open


class NativeCopyTests(unittest.TestCase):
    def test_failed_thread_start_releases_source_owner(self):
        done=[];errors=[]
        with patch.object(native_open.threading.Thread,'start',side_effect=RuntimeError('no thread')):
            native_open.open_with_system('source',on_error=errors.append,on_done=lambda:done.append(True))
        self.assertEqual(done,[True]);self.assertIsInstance(errors[0],RuntimeError)

    def test_completion_runs_after_success_or_failure_and_keeps_external_copy(self):
        for fail in (False,True):
            with self.subTest(fail=fail),tempfile.TemporaryDirectory() as directory:
                source=Path(directory)/'source.png';source.write_bytes(b'original')
                target=Path(directory)/'external.png'
                finished=threading.Event();errors=[];copied=[]
                def copy(*_):
                    if fail:raise OSError('disk full')
                    target.write_bytes(source.read_bytes());copied.append(target);return target
                def done():
                    source.unlink();finished.set()
                with patch.object(native_open,'viewable_copy',side_effect=copy),patch.object(native_open,'launch') as launch:
                    native_open.open_with_system(source,on_error=errors.append,on_done=done)
                    self.assertTrue(finished.wait(2))
                    self.assertEqual(bool(errors),fail)
                    if fail:launch.assert_not_called()
                    else:
                        launch.assert_called_once_with(target)
                        self.assertEqual(target.read_bytes(),b'original')
                self.assertFalse(source.exists())

    def test_simultaneous_viewers_and_editors_keep_separate_original_bytes(self):
        for edit in (False, True):
            with self.subTest(edit=edit), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                destination = root / 'copies'
                destination.mkdir()
                sources = []
                for index in range(8):
                    folder = root / str(index)
                    folder.mkdir()
                    source = folder / 'photo.png'
                    source.write_bytes(bytes([index]) * 65536)
                    sources.append(source)
                start = threading.Barrier(len(sources))
                def copy(source):
                    start.wait(timeout=5)
                    target = (native_open.editable_copy(source) if edit else
                              native_open.viewable_copy(source, 'photo'))
                    return target, source.read_bytes()
                with patch.object(native_open, '_private_folder', return_value=destination), \
                     concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                    copies = list(pool.map(copy, sources))
                self.assertEqual(len({path for path, _ in copies}), len(sources))
                for target, expected in copies:
                    self.assertEqual(target.read_bytes(), expected)
                    self.assertEqual(target.suffix, '.png')

    def test_failed_copy_leaves_no_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'original.png'
            source.write_bytes(b'original')
            target = root / 'copies'
            target.mkdir()
            with patch.object(native_open, '_private_folder', return_value=target), \
                 patch.object(native_open.shutil, 'copyfileobj', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    native_open.editable_copy(source)
            self.assertEqual(list(target.iterdir()), [])
            self.assertEqual(source.read_bytes(), b'original')
