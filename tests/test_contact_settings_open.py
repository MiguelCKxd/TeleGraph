"""Every supported contact action can be opened in the appearance editor."""
import tkinter as tk
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

from tg_ascii.contact_settings import open_contact_settings
from tg_ascii.contact_appearance import ACTIONS


class ContactSettingsOpenTests(unittest.TestCase):
    def test_default_contact_editor_builds_all_action_choices(self):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        window = tk.Toplevel(root)
        body = tk.Frame(window)
        body.pack()
        app = NS(root=root, preferences=NS(values={}),
                 dialog=Mock(return_value=(window, body)), show_error=Mock())
        result = open_contact_settings(app)
        self.assertIs(result, window)
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        lists = [widget for widget in descendants(window) if isinstance(widget, tk.Listbox)]
        self.assertEqual(len(lists), 2)
        self.assertEqual(lists[1].size(), len(ACTIONS))
        self.assertTrue(any('Share' in value or 'Compartir' in value for value in lists[1].get(0, 'end')))
        app.show_error.assert_not_called()


if __name__ == '__main__':
    unittest.main()
