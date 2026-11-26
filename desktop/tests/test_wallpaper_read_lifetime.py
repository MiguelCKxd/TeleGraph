"""Abandoned wallpaper pages release their pending catalogue/thumbnail reads."""
from concurrent.futures import Future
from pathlib import Path
import tkinter as tk
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

from tg_ascii.telegram_wallpapers import open_gallery


class DeferredWorker:
    def __init__(self):
        self.jobs = []

    def submit(self, operation, loaded, failed):
        future = Future()
        future.add_done_callback(lambda _: operation.close())
        self.jobs.append((future, loaded, failed))
        return future

    def close(self):
        for future, _, _ in self.jobs:
            future.cancel()


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class WallpaperReadLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.worker = DeferredWorker()
        self.windows = []
        self.on_choose = Mock()
        self.app = NS(root=self.root, ui_account='a', service=NS(backend=NS()),
                      demo=False, worker=self.worker, preview_dir=Path('/unused'),
                      preferences=NS(values={'telegram_backgrounds': True}, save=Mock()),
                      load_photo=Mock(return_value=None))
        def dialog(*_):
            window = tk.Toplevel(self.root)
            frame = tk.Frame(window)
            frame.pack()
            self.windows.append(window)
            return window, frame
        self.app.dialog = dialog

    def tearDown(self):
        self.root.destroy()
        self.worker.close()

    def open_catalog(self, count=36):
        open_gallery(self.app, on_choose=self.on_choose)
        # Deliver the same immutable catalogue to the UI without network I/O.
        self.worker.jobs[0][1]([NS(id=index) for index in range(count)])
        return self.windows[0]

    def test_next_page_cancels_previous_downloads_and_ignores_late_results(self):
        window = self.open_catalog()
        following = next(child for child in descendants(window)
                         if child.winfo_class() == 'TButton' and child.cget('text') == '›')
        first_page = self.worker.jobs[1:13]
        self.assertEqual(len(first_page), 12)
        following.invoke()
        self.assertTrue(all(future.cancelled() for future, _, _ in first_page))
        self.assertEqual(sum(not future.done() for future, _, _ in self.worker.jobs[1:]), 12)
        first_page[0][1](Path('/late.jpg'))
        self.app.load_photo.assert_not_called()
        following.invoke()
        self.assertTrue(all(future.cancelled() for future, _, _ in self.worker.jobs[1:25]))
        self.assertEqual(sum(not future.done() for future, _, _ in self.worker.jobs[1:]), 12)
        self.assertEqual(str(following.cget('state')), 'disabled')
        self.on_choose.assert_not_called()
        self.app.preferences.save.assert_not_called()
        window.destroy()
        self.assertTrue(all(future.cancelled() for future, _, _ in self.worker.jobs[1:]))

    def test_close_cancels_catalog_and_discards_late_delivery(self):
        open_gallery(self.app, on_choose=self.on_choose)
        future, loaded, _ = self.worker.jobs[0]
        self.windows[0].destroy()
        self.assertTrue(future.cancelled())
        loaded([NS(id=1)])
        self.assertEqual(len(self.worker.jobs), 1)

    def test_account_change_rejects_thumbnail_callback(self):
        self.open_catalog(1)
        self.app.ui_account = 'b'
        self.worker.jobs[-1][1](Path('/previous-account.jpg'))
        self.app.load_photo.assert_not_called()
        self.on_choose.assert_not_called()


if __name__ == '__main__':
    unittest.main()
