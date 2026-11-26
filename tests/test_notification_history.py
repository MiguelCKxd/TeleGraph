import tempfile,unittest
from pathlib import Path
from tg_ascii.notification_history import NotificationHistory,LIMIT,RETENTION

class HistoryTests(unittest.TestCase):
    def test_bound_persistence_retention_and_no_private_payload(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'history.sqlite';now=[1000000];journal=NotificationHistory(path,clock=lambda:now[0])
            for i in range(LIMIT+9):journal.record('received','live',('private-account',42,i))
            self.assertEqual(len(journal.rows()),LIMIT);journal.close()
            self.assertNotIn(b'private-account',path.read_bytes())
            journal=NotificationHistory(path,clock=lambda:now[0]);self.assertEqual(len(journal.rows()),LIMIT)
            now[0]+=RETENTION+1;self.assertEqual(journal.rows(),[]);journal.record('failed');self.assertEqual(len(journal.rows()),1);journal.close()
    def test_bad_store_falls_back_without_preventing_notifications(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'broken';path.write_text('not a database',encoding='utf-8')
            journal=NotificationHistory(path);journal.record('submitted','push','opaque')
            self.assertEqual(journal.rows()[0][1:3],('submitted','push'));journal.close()
    def test_schema_rejects_arbitrary_content(self):
        journal=NotificationHistory()
        with self.assertRaises(ValueError):journal.record('private message content')
        with self.assertRaises(ValueError):journal.record('received','private account name')
        journal.close();journal.record('received');self.assertEqual(journal.rows(),[])

    def test_content_stored_truncated_and_retrieved(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'history.sqlite'
            journal = NotificationHistory(path)
            long_text = 'A' * 300
            journal.record('in_app', 'live', 'event_id', long_text)
            journal.record('submitted', 'push', 'event_id2', 'Short text')
            rows = journal.rows()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0][4], 'Short text')
            self.assertEqual(rows[1][4], 'A' * 256)
            journal.close()

            # Reopen and check persistence
            reopened = NotificationHistory(path)
            rows2 = reopened.rows()
            self.assertEqual(len(rows2), 2)
            self.assertEqual(rows2[0][4], 'Short text')
            self.assertEqual(rows2[1][4], 'A' * 256)
            reopened.close()

    def test_memory_fallback_retains_content(self):
        journal = NotificationHistory(None)
        journal.record('in_app', 'system', 'event1', 'Fallback message')
        rows = journal.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][4], 'Fallback message')
        journal.close()

    def test_pre_policy_diagnostics_never_keep_text_and_legacy_rows_are_redacted(self):
        import sqlite3
        from contextlib import closing
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'history.sqlite'
            journal = NotificationHistory(path)
            for phase in ('received', 'duplicate', 'suppressed', 'failed'):
                journal.record(phase, 'live', 'opaque', 'private before policy')
            self.assertTrue(all(row[4] == '' for row in journal.rows()))
            journal.close()
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("UPDATE history SET content='legacy private' WHERE phase='received'")
            journal = NotificationHistory(path)
            self.assertTrue(all(row[4] == '' for row in journal.rows()))
            self.assertEqual(len(journal.rows()), 4)
            journal.close()

    def test_history_ui_displays_seconds(self):
        import asyncio
        import tkinter as tk
        from types import SimpleNamespace as NS
        from tg_ascii.notification_history import open_history
        root = tk.Tk()
        root.withdraw()
        journal = NotificationHistory(None)
        journal.record('received', 'system', 'event1', 'Test msg')
        app = NS(
            dialog=lambda title, geom: (root, tk.Frame(root)),
            preferences=NS(values={'show_seconds': False}),
            notification_history=journal,
            worker=NS(submit=lambda fn, done, fail: done(asyncio.run(fn))),
            closing=False,
        )
        try:
            open_history(app)
            # Find the treeview in root
            for child in root.winfo_children():
                if isinstance(child, tk.Frame):
                    for sub in child.winfo_children():
                        from tkinter import ttk
                        if isinstance(sub, ttk.Treeview):
                            children = sub.get_children()
                            self.assertEqual(len(children), 1)
                            row_vals = sub.item(children[0], 'values')
                            # First value is the timestamp: check format includes seconds (e.g. DD/MM/YYYY HH:MM:SS)
                            time_str = row_vals[0]
                            parts = time_str.split(' ')
                            self.assertEqual(len(parts), 2)
                            hms = parts[1].split(':')
                            self.assertEqual(len(hms), 3, f"Expected HH:MM:SS, got {parts[1]}")
        finally:
            journal.close()
            root.destroy()


