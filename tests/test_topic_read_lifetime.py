"""Topic browsing owns its read jobs and Tk timers; mutations stay separate."""
from concurrent.futures import Future
import tkinter as tk
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

from tg_ascii.desktop_forums import TopicBrowser, TopicPicker


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


class TopicReadLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.worker = DeferredWorker()
        async def topics(*args):
            return {'topics': [], 'next_cursor': None}
        backend = NS(forum_topics=topics)
        self.app = NS(root=self.root, ui_account='a', service=NS(backend=backend), worker=self.worker,
                      demo=False, show_error=Mock(), _chat_windows=[], preferences=NS(values={}))
        def dialog(*_):
            window = tk.Toplevel(self.root)
            frame = tk.Frame(window)
            frame.pack()
            return window, frame
        self.app.dialog = dialog

    def tearDown(self):
        self.root.destroy()
        self.worker.close()

    def views(self):
        return (TopicBrowser(self.app, 'a', -100, 'Prueba'),
                TopicPicker(self.app, 'a', -100, 'Prueba', lambda _: None))

    def test_destroy_cancels_pending_reads_and_scheduled_searches(self):
        for view in self.views():
            with self.subTest(view=type(view).__name__):
                future = self.worker.jobs[-1 if isinstance(view, TopicPicker) else -2][0]
                view.query.set('tema')
                timer = view._search_job
                self.assertIn(timer, self.root.tk.call('after', 'info'))
                view.window.destroy()
                self.assertNotIn(timer, self.root.tk.call('after', 'info'))
                self.assertTrue(future.cancelled())

    def test_destroy_cancels_change_reload(self):
        view = TopicBrowser(self.app, 'a', -100, 'Prueba')
        view.change('a', 'forum_topics', (-100, None))
        timer = view._change_job
        self.assertIsNotNone(timer)
        view.window.destroy()
        self.assertNotIn(timer, self.root.tk.call('after', 'info'))
        self.assertEqual(self.app._topic_browsers, [])

    def test_refresh_replaces_read_and_consumes_queued_search(self):
        for view in self.views():
            with self.subTest(view=type(view).__name__):
                previous = view.requests.jobs['topics']
                view.query.set('otra búsqueda')
                timer = view._search_job
                view.load()
                self.assertTrue(previous.cancelled())
                self.assertNotIn(timer, self.root.tk.call('after', 'info'))
                self.assertEqual(len(view.requests.jobs), 1)
                view.window.destroy()


if __name__ == '__main__':
    unittest.main()
