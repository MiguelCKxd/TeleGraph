"""1.5.5: decoding in separate processes (complex feature, off by default)."""
import asyncio
import glob
import os
import signal
import subprocess
import sys
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PIL import Image

from tg_ascii import decode_pool
from tg_ascii.advanced_features import validated_features
from tg_ascii.preferences import Preferences


def animated_webp(folder):
    path = Path(folder) / 'a.webp'
    frames = [Image.new('RGBA', (96, 96), (i * 40, 80, 120, 255)) for i in range(4)]
    frames[0].save(path, format='WEBP', save_all=True, append_images=frames[1:], duration=50, loop=0, lossless=True)
    return path


class ProcessDecodingTests(unittest.TestCase):
    def setUp(self):
        decode_pool.configure({'advanced_features': {'process_decoding': True}})

    def tearDown(self):
        decode_pool.shutdown()
        decode_pool._broken = False
        decode_pool.configure({})

    def test_off_by_default_and_switchable(self):
        self.assertFalse(validated_features({})['process_decoding'])
        self.assertFalse(Preferences.validated({})['advanced_features']['process_decoding'])
        decode_pool.configure({})
        self.assertFalse(decode_pool.active())
        self.assertEqual(decode_pool.parallelism(2), 2)
        decode_pool.configure({'advanced_features': {'process_decoding': True}})
        self.assertTrue(decode_pool.active())
        self.assertGreaterEqual(decode_pool.parallelism(2), 1)
        decode_pool.configure({'advanced_features': {'process_decoding': 'yes'}})
        self.assertFalse(decode_pool.active())

    def test_frames_decoded_in_another_process_match_the_thread_result(self):
        from tg_ascii.animation import decode_frames
        with tempfile.TemporaryDirectory() as folder:
            path = animated_webp(folder)
            expected, durations = decode_frames(path, (48, 48), True)
            frames, got_durations = asyncio.run(decode_pool.decode_frames(path, (48, 48), True))
            self.assertEqual(got_durations, durations)
            self.assertEqual([frame.tobytes() for frame in frames], [frame.tobytes() for frame in expected])

    def test_shutdown_reaps_a_running_decoder(self):
        pool = decode_pool._get_pool()
        # The first result proves the spawned worker is ready for the next job.
        pool.submit(os.getpid).result(timeout=10)
        future = pool.submit(time.sleep, 30)
        worker = next(iter(pool._processes.values()))
        pid = worker.pid
        deadline = time.monotonic() + 5
        while not future.running() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(future.running())
        started = time.monotonic()
        decode_pool.shutdown()
        self.assertLess(time.monotonic() - started, 5)
        self.assertNotIn(pid, [child.pid for child in decode_pool.multiprocessing.active_children()])

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS worker lifetime')
    def test_worker_exits_when_gui_dies_before_shutdown(self):
        owner = (
            "import os, sys, time; from pathlib import Path; "
            "from tg_ascii.decode_pool import _get_pool; pool = _get_pool(); "
            "pid = pool.submit(os.getpid).result(timeout=15); "
            "pool.submit(time.sleep, 30); Path(sys.argv[1]).write_text(str(pid), encoding='ascii'); os._exit(0)"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'worker'
            subprocess.run([sys.executable, '-c', owner, str(path)], check=True, timeout=20,
                           cwd=Path(__file__).resolve().parents[1], stderr=subprocess.DEVNULL)
            worker = int(path.read_text(encoding='ascii'))
            for _ in range(50):
                try:
                    os.kill(worker, 0)
                except ProcessLookupError:
                    return
                time.sleep(.1)
            os.kill(worker, signal.SIGKILL)
            self.fail('Decoder survived the GUI process')

    def test_falls_back_to_threads_when_the_pool_breaks(self):
        from concurrent.futures.process import BrokenProcessPool
        with tempfile.TemporaryDirectory() as folder:
            path = animated_webp(folder)
            with patch('tg_ascii.decode_pool._get_pool', side_effect=BrokenProcessPool('gone')):
                frames, _ = asyncio.run(decode_pool.decode_frames(path, (32, 32), True))
            self.assertTrue(frames)
            self.assertFalse(decode_pool.active())


if __name__ == '__main__':
    unittest.main()
