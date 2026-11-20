"""Small entity-preserving text fields used only in explicitly opened dialogs."""
import tkinter as tk
from copy import copy
from tkinter import ttk

from telethon import types as t

from .app_dialogs import popup_menu, simpledialog
from .i18n import tr


class EntityField(ttk.Frame):
    def __init__(self, parent, app, value='', *, height=2):
        super().__init__(parent)
        self.app, self.entities = app, {}
        self.editor = tk.Text(self, height=height, wrap='word', undo=True)
        self.editor.pack(fill='both', expand=True)
        self.editor.bind('<Button-3>', self.menu)
        self.editor.bind('<Control-Button-1>', self.menu)
        for key, kind in (('b', t.MessageEntityBold), ('i', t.MessageEntityItalic), ('u', t.MessageEntityUnderline)):
            self.editor.bind('<Control-' + key + '>', lambda _, kind=kind: self.apply(kind))
        self.set(value)

    def _index(self, offset):
        text = self.editor.get('1.0', 'end-1c')
        return '1.0 + {} chars'.format(self.editor.tk.call('string', 'length', text[:offset]))

    def set(self, value):
        self.editor.delete('1.0', 'end')
        for tag in self.entities: self.editor.tag_delete(tag)
        self.entities.clear()
        text = value.text if isinstance(value, t.TextWithEntities) else str(value)
        self.editor.insert('1.0', text)
        positions, offset = {0: 0}, 0
        for index, char in enumerate(text):
            offset += 2 if ord(char) > 0xffff else 1
            positions[offset] = index + 1
        for entity in getattr(value, 'entities', ()):
            start, end = positions.get(entity.offset), positions.get(entity.offset + entity.length)
            if start is not None and end is not None:
                self._tag(self._index(start), self._index(end), entity)

    def _tag(self, start, end, entity):
        tag = 'entity_' + str(len(self.entities))
        self.entities[tag] = copy(entity)
        self.editor.tag_add(tag, start, end)
        options = {}
        if isinstance(entity, (t.MessageEntityUnderline, t.MessageEntityTextUrl, t.MessageEntityCustomEmoji)):
            options['underline'] = True
        if isinstance(entity, t.MessageEntityStrike): options['overstrike'] = True
        if isinstance(entity, t.MessageEntityBold): options['font'] = ('TkDefaultFont', 11, 'bold')
        if isinstance(entity, t.MessageEntityItalic): options['font'] = ('TkDefaultFont', 11, 'italic')
        if options: self.editor.tag_configure(tag, **options)

    def value(self):
        text, entities = self.editor.get('1.0', 'end-1c'), []
        for tag, original in self.entities.items():
            ranges = self.editor.tag_ranges(tag)
            for start, end in zip(ranges[::2], ranges[1::2]):
                content = self.editor.get(start, end)
                if not content: continue
                entity = copy(original)
                entity.offset = len(self.editor.get('1.0', start).encode('utf-16-le')) // 2
                entity.length = len(content.encode('utf-16-le')) // 2
                entities.append(entity)
        return t.TextWithEntities(text, sorted(entities, key=lambda item: (item.offset, -item.length)))

    def apply(self, cls, *, collapsed=False):
        ranges = self.editor.tag_ranges('sel')
        if len(ranges) != 2: return 'break'
        start, end = ranges
        if cls is None:
            for tag in self.entities: self.editor.tag_remove(tag, start, end)
            return 'break'
        if cls is t.MessageEntityTextUrl:
            url = simpledialog.askstring(tr('Link'), 'https://', parent=self.winfo_toplevel())
            if not url or not self.winfo_exists(): return 'break'
            from .links import link_target
            try: link_target(url)
            except ValueError as exc: self.app.show_error(exc); return 'break'
            entity = cls(0, 0, url)
        elif cls is t.MessageEntityBlockquote: entity = cls(0, 0, collapsed=collapsed)
        else: entity = cls(0, 0)
        self._tag(start, end, entity)
        return 'break'

    def custom_emoji(self):
        account = self.app.ui_account
        def selected(document):
            if not self.winfo_exists() or account != self.app.ui_account: return
            alt = next((attribute.alt for attribute in document.attributes
                        if isinstance(attribute, t.DocumentAttributeCustomEmoji)), None)
            if not alt: return
            start = self.editor.index('insert')
            self.editor.insert('insert', alt)
            end = self.editor.index('insert')
            self._tag(start, end, t.MessageEntityCustomEmoji(0, 0, document.id))
        self.app.telegram_picker(True, selected)

    def menu(self, event=None):
        entries = [(tr(label), lambda cls=cls: self.apply(cls)) for label, cls in (
            ('Bold', t.MessageEntityBold), ('Italic', t.MessageEntityItalic),
            ('Underline', t.MessageEntityUnderline), ('Strikethrough', t.MessageEntityStrike),
            ('Spoiler', t.MessageEntitySpoiler), ('Monospace', t.MessageEntityCode),
            ('Link', t.MessageEntityTextUrl), ('Clear formatting', None))]
        entries += [(tr('Cita'), lambda: self.apply(t.MessageEntityBlockquote)),
                    (tr('Texto desplegable'), lambda: self.apply(t.MessageEntityBlockquote, collapsed=True)),
                    None, (tr('Custom emoji'), self.custom_emoji)]
        popup_menu(self.winfo_toplevel(), entries, event=event, anchor=self.editor)
        return 'break'
