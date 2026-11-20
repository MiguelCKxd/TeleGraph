"""Windows mandatory-lock regression and real cross-process exclusion."""
import io
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tg_ascii import instance


class MandatoryLockFile(io.BytesIO):
    """Model Windows denying reads through any handle except the lock owner."""

    def __init__(self, backend):
        super().__init__(b'0')
        self.backend = backend
        self.fd = len(backend.streams)
        backend.streams.append(self)

    def fileno(self):
        return self.fd

    def read(self, size=-1):
        if self.backend.owner not in (None, self):
            raise PermissionError('The byte is locked through another handle')
        return super().read(size)

    def close(self):
        if self.backend.owner is self:
            self.backend.owner = None
        super().close()


class WindowsLockBackend:
    LK_NBLCK = 2

    def __init__(self):
        self.streams = []
        self.owner = None

    def open(self, *args, **kwargs):
        return MandatoryLockFile(self)

    def locking(self, fd, mode, size):
        stream = self.streams[fd]
        if stream.tell() != 0 or mode != self.LK_NBLCK or size != 1:
            raise AssertionError('Expected a nonblocking lock of byte zero')
        if self.owner is not None:
            raise PermissionError('The byte is already locked')
        self.owner = stream


class WindowsLockTests(unittest.TestCase):
    def test_mandatory_lock_rejects_second_handle_and_releases_on_close(self):
        backend = WindowsLockBackend()
        with tempfile.TemporaryDirectory() as folder:
            with (patch.object(instance, 'os', SimpleNamespace(name='nt')),
                  patch.dict(sys.modules, {'msvcrt': backend}),
                  patch.object(Path, 'open', side_effect=backend.open)):
                first = instance.InstanceLock(folder)
                try:
                    self.assertTrue(first.acquired)
                    second = instance.InstanceLock(folder)
                    self.assertFalse(second.acquired)
                    self.assertTrue(second.stream.closed)
                    self.assertFalse(first.stream.closed)
                    second.close()
                finally:
                    first.close()
                self.assertTrue(first.stream.closed)
                first.close()
                third = instance.InstanceLock(folder)
                try:
                    self.assertTrue(third.acquired)
                finally:
                    third.close()
        self.assertTrue(all(stream.closed for stream in backend.streams))

    def test_seek_failure_closes_unacquired_handle(self):
        backend = WindowsLockBackend()
        stream = backend.open()
        with tempfile.TemporaryDirectory() as folder:
            with (patch.object(Path, 'open', return_value=stream),
                  patch.object(stream, 'seek', side_effect=OSError('seek failed'))):
                lock = instance.InstanceLock(folder)
        self.assertFalse(lock.acquired)
        self.assertTrue(stream.closed)
        lock.close()

    def test_other_process_is_rejected_and_process_exit_releases_lock(self):
        project = str(Path(__file__).resolve().parents[1])
        child_code = (
            'import sys; '
            'from tg_ascii.instance import InstanceLock; '
            'lock = InstanceLock(sys.argv[1]); '
            'print(int(lock.acquired), int(lock.stream.closed))'
        )

        def child_attempt(folder):
            result = subprocess.run(
                [sys.executable, '-c', child_code, folder], cwd=project,
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.strip()

        with tempfile.TemporaryDirectory() as folder:
            # Start with an empty file, exercising locking beyond EOF on Windows.
            (Path(folder) / 'desktop.lock').touch()
            first = instance.InstanceLock(folder)
            try:
                self.assertTrue(first.acquired)
                self.assertEqual(child_attempt(folder), '0 1')
            finally:
                first.close()
            self.assertEqual(child_attempt(folder), '1 0')
            # The child deliberately did not call close(); process exit releases it.
            reopened = instance.InstanceLock(folder)
            try:
                self.assertTrue(reopened.acquired)
            finally:
                reopened.close()

    def test_instance_server_and_wake(self):
        from tg_ascii.desktop import _start_instance_server, _wake_existing_instance
        reopened = Event()
        root = SimpleNamespace(after=lambda delay, cb: cb(),
                               _app_instance=SimpleNamespace(reopen_window=reopened.set))

        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(_wake_existing_instance(folder))
            cleanup = _start_instance_server(root, folder)
            try:
                self.assertTrue(_wake_existing_instance(folder))
                self.assertTrue(reopened.wait(2), "The requested window did not reopen")
            finally:
                cleanup()
            self.assertFalse((Path(folder) / 'desktop.port').exists())
            self.assertFalse(_wake_existing_instance(folder))


if __name__ == '__main__':
    unittest.main()
