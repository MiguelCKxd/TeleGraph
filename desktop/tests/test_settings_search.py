import tkinter as tk
import unittest
from tkinter import ttk

from tg_ascii import settings_search as ss


class SettingsSearchTests(unittest.TestCase):
    def test_matching_ignores_case_and_accents(self):
        self.assertTrue(ss.matches('tamano letra', 'Tamaño del texto de la letra'))
        self.assertTrue(ss.matches('NOTIF', 'Notificaciones'))
        self.assertFalse(ss.matches('', 'x'))
        self.assertFalse(ss.matches('burbuja', 'Tema'))

    def test_index_search_and_category_switch(self):
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest('no display')
        root.withdraw()
        try:
            sections = {'Apariencia': ttk.Frame(root), 'Chats': ttk.Frame(root)}
            ttk.Label(sections['Apariencia'], text='Tamaño del texto').pack()
            box = ttk.Checkbutton(sections['Chats'], text='Mostrar burbujas'); box.pack()
            chosen = []
            frame = ss.build(root, sections, {'Apariencia': 'Apariencia', 'Chats': 'Chats'},
                             chosen.append, ['Apariencia', 'Chats'])
            frame.pack()
            frame.query.set('burbujas')
            self.assertEqual(frame.results.get(0), 'Chats › Mostrar burbujas')
            frame.results.selection_set(0)
            frame.open_selected()
            self.assertEqual(chosen, [1])
            frame.query.set('nada que exista')
            self.assertEqual(frame.results.size(), 1)
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()


class PhotoPreviewPreferenceTests(unittest.TestCase):
    def test_photo_previews_only_hide_photos(self):
        from tg_ascii.preferences import Preferences, shows_preview
        values = Preferences.validated({'photo_previews': False})
        self.assertFalse(values['photo_previews'])
        self.assertFalse(shows_preview(values, 'image'))
        self.assertTrue(shows_preview(values, 'video'))
        self.assertTrue(Preferences.validated({})['photo_previews'])
        self.assertFalse(shows_preview({'inline_media': False}, 'video'))
