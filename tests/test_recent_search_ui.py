import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from tkinter import ttk

from tg_ascii.recent_search_ui import RecentStrip, remember, store


class RecentSearchStripTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest('no display')
        self.root.withdraw()
        self.folder = tempfile.TemporaryDirectory()
        self.app = NS(demo=False, ui_account='a', service=NS(root=Path(self.folder.name)))

    def tearDown(self):
        self.root.destroy(); self.folder.cleanup()

    def strip(self, scope='chats', suggestions=None):
        frame = ttk.Frame(self.root); frame.pack()
        variable = tk.StringVar(master=self.root)
        variable.entry = ttk.Entry(frame, textvariable=variable); variable.entry.pack()
        picked = []
        strip = RecentStrip(self.app, frame, variable, scope, pick=picked.append, suggestions=suggestions)
        return strip, variable, picked

    def test_queries_are_per_account_and_scope(self):
        remember(self.app, 'chats', '  hola   mundo ')
        remember(self.app, 'global', 'otra')
        self.assertEqual(store(self.app).list('a', 'chats'), ['hola mundo'])
        self.app.ui_account = 'b'
        self.assertEqual(store(self.app).list('b', 'chats'), [])

    def test_strip_shows_when_empty_and_hides_while_typing(self):
        remember(self.app, 'chats', 'hola')
        strip, variable, picked = self.strip()
        strip.refresh(force=True)
        self.assertTrue(strip.shown)
        variable.set('x')
        self.assertFalse(strip.shown)
        variable.set('')
        strip.choose('hola')
        self.assertEqual(variable.get(), 'hola')
        self.assertEqual(picked, ['hola'])

    def test_clear_and_demo(self):
        remember(self.app, 'chats', 'hola')
        strip, _, _ = self.strip()
        strip.clear()
        self.assertEqual(store(self.app).list('a', 'chats'), [])
        self.app.demo = True
        remember(self.app, 'chats', 'secreto')
        self.assertEqual(store(self.app).list('a', 'chats'), [])

    def test_server_suggestions_are_shown_without_recent_queries(self):
        strip, _, _ = self.strip('global', suggestions=lambda done: done([('Ana', lambda: None)]))
        strip.refresh(force=True)
        self.assertTrue(strip.shown)

    def test_destroy_cancels_hide_and_ignores_late_suggestions(self):
        strip, _, _ = self.strip('global')
        strip.suggested([('Ana', lambda: None)])
        strip.refresh(force=True)
        strip.hide_later()
        timer = strip._hide_job
        strip.frame.destroy()
        self.assertNotIn(timer, self.root.tk.call('after', 'info'))
        strip.suggested([('Llega tarde', lambda: None)])
        self.assertFalse(strip.shown)

    def test_repeated_focus_out_keeps_one_hide_timer(self):
        strip, _, _ = self.strip()
        strip.hide_later()
        first = strip._hide_job
        strip.hide_later()
        self.assertNotIn(first, self.root.tk.call('after', 'info'))
        self.assertIn(strip._hide_job, self.root.tk.call('after', 'info'))


if __name__ == '__main__':
    unittest.main()
