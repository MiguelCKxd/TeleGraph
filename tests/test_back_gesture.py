import tkinter as tk
import unittest

from tg_ascii.back_gesture import BackTracker, THRESHOLD, install, overscroll


class Clock:
    def __init__(self): self.now = 100.0
    def __call__(self): return self.now


class BackGestureTests(unittest.TestCase):
    def test_threshold_window_and_cooldown(self):
        clock = Clock(); tracker = BackTracker(clock)
        self.assertFalse(tracker.feed(-THRESHOLD / 2))
        self.assertTrue(tracker.feed(-THRESHOLD / 2))
        self.assertFalse(tracker.feed(-THRESHOLD))  # cooldown
        clock.now += 1
        self.assertFalse(tracker.feed(-THRESHOLD / 2))
        clock.now += 1  # too slow: travel restarts
        self.assertFalse(tracker.feed(-THRESHOLD / 2))
        self.assertFalse(tracker.feed(30))  # reversing cancels
        self.assertFalse(tracker.feed(-THRESHOLD / 2))

    def test_overscroll_runs_the_window_action(self):
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest('no display')
        root.withdraw()
        try:
            top = tk.Toplevel(root); label = tk.Label(top); label.pack()
            calls = []
            install(top, lambda: calls.append('back'))
            overscroll(label, -THRESHOLD - 1)
            self.assertEqual(calls, ['back'])
            self.assertFalse(overscroll(tk.Label(root), -THRESHOLD - 1))  # no action registered
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()


class RouterOverscrollTests(unittest.TestCase):
    def test_router_reports_when_nothing_can_scroll_sideways(self):
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest('no display')
        root.withdraw()
        try:
            from types import SimpleNamespace as NS
            from tg_ascii.scrolling import WheelRouter
            router = WheelRouter(root)
            label = tk.Label(root, text='x'); label.pack()
            router.route(label, NS(state=0), -40, axis='x', pixels=True)
            self.assertFalse(router.moved)
            text = tk.Text(root, wrap='none', width=5); text.insert('1.0', 'y' * 400); text.pack(); root.update()
            text.xview_moveto(.5)
            router.route(text, NS(state=0), -40, axis='x', pixels=True)
            self.assertTrue(router.moved)
        finally:
            root.destroy()
