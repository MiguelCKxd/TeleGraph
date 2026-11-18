"""Prevent two GUI processes from opening the same account databases."""
import os
from pathlib import Path


class InstanceLock:
    def __init__(self, root):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.stream = (root / 'desktop.lock').open('a+b')
        self.acquired = False
        try:
            self.stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                # Windows byte locks also cover bytes beyond EOF. Do not read
                # or initialize this byte: another instance's mandatory lock
                # would reject that I/O before we can attempt our own lock.
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.acquired = True
        except OSError:
            self.stream.close()

    def close(self):
        if self.acquired:
            self.acquired = False
            self.stream.close()  # OS releases the lock, including after a crash.
