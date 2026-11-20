"""Custom emoji inside chat-list rows (1.5.0.1).

A Tk Treeview draws one picture per row (the avatar) and plain text. Folder
names may contain Telegram custom emoji, so the row text keeps a gap of the
right width (PLACEHOLDER) where each one goes and a small picture with the
real custom emoji is placed over that gap. Overlays follow scrolling (both
directions), resizing, wrapped rows (compact list) and selection colours, and
are only created for rows on screen. Clicks on an overlay go to the row.
"""
import tkinter as tk
from tkinter import ttk

PLACEHOLDER = '  '  # Two figure spaces: never split by word wrapping.


class RowEmoji:
    def __init__(self, app, tree):
        self.app, self.tree = app, tree
        self.docs = {}          # row id -> [document ids, in text order]
        self.labels = {}        # (row, index) -> tk.Label
        self.photos = {}        # (account, document, size) -> PhotoImage
        self.pending = set()
        self.offsets = {}
        self.job = None
        tree._row_overlay = self

    # -- data --------------------------------------------------------------
    def set_rows(self, docs):
        self.docs = {row: list(ids) for row, ids in docs.items() if ids}
        self.refresh()

    # -- layout ------------------------------------------------------------
    def refresh(self, _=None):
        if self.job is not None:
            return
        try:
            self.job = self.tree.after_idle(self.place)
        except tk.TclError:
            self.job = None

    def text_offset(self, row, bbox):
        """Pixels from the cell's left edge to where the row text starts."""
        key = bool(self.tree.item(row, 'image'))
        if key in self.offsets:
            return self.offsets[key]
        y = bbox[1] + bbox[3] // 2
        offset = None
        for dx in range(0, min(bbox[2], 200), 2):
            element = str(self.tree.identify_element(bbox[0] + dx, y))
            if element.endswith('text'):
                offset = dx
                break
        if offset is None:
            return 40 if key else 24
        self.offsets[key] = offset
        return offset

    def colors(self):
        from .appearance import app_palette
        colors = app_palette(self.app.preferences.values)
        return colors['panel'], colors['selected']

    def place(self):
        self.job = None
        tree = self.tree
        try:
            if not tree.winfo_exists():
                return
        except tk.TclError:
            return
        from .tree_fit import _measure
        from .ui_work import visible_tree_rows
        face = _measure(tree)['font']
        gap = face.measure(PLACEHOLDER)
        line = face.metrics('linespace')
        size = max(10, min(gap, line) - 1)
        background, selected = self.colors()
        chosen = set(tree.selection())
        width = tree.winfo_width()
        used = set()
        for row in visible_tree_rows(tree, overscan=0):
            docs = self.docs.get(row)
            if not docs or not tree.exists(row):
                continue
            bbox = tree.bbox(row, '#0')
            if not bbox:
                continue
            text = tree.item(row, 'text')
            lines = text.split('\n')
            left = bbox[0] + self.text_offset(row, bbox)
            top = bbox[1] + (bbox[3] - len(lines) * line) // 2
            index = 0
            for number, part in enumerate(lines):
                start = 0
                while index < len(docs):
                    found = part.find(PLACEHOLDER, start)
                    if found < 0:
                        break
                    x = left + face.measure(part[:found]) + (gap - size) // 2
                    y = top + number * line + (line - size) // 2
                    start = found + len(PLACEHOLDER)
                    key = (row, index)
                    document = docs[index]
                    index += 1
                    if x + size < 0 or x > width:
                        continue
                    label = self.labels.get(key)
                    if label is None or not label.winfo_exists():
                        label = tk.Label(tree, bd=0, highlightthickness=0, padx=0, pady=0)
                        for sequence in ('<Button-1>', '<Button-2>', '<Button-3>', '<Double-Button-1>'):
                            label.bind(sequence, lambda event, row=row, sequence=sequence: self.forward(event, row, sequence))
                        self.labels[key] = label
                    label.configure(bg=selected if row in chosen else background)
                    label._document = document
                    self.paint(label, document, size)
                    label.place(x=x, y=y, width=size, height=size)
                    used.add(key)
        for key, label in list(self.labels.items()):
            if key not in used:
                try:
                    label.destroy()
                except tk.TclError:
                    pass
                self.labels.pop(key, None)

    def paint(self, label, document, size):
        photo = self.photos.get((self.app.ui_account, document, size))
        if photo is not None:
            if label.cget('image') != str(photo):
                label.configure(image=photo)
            label.image = photo
            return
        self.load(document, size)

    def load(self, document, size, ready_callback=None):
        """Fetch one custom emoji picture; ready_callback(photo) when it exists."""
        app = self.app
        account = app.ui_account
        cache_key = (account, document, size)
        if ready_callback is not None:
            self.__dict__.setdefault('waiters', {}).setdefault(cache_key, []).append(ready_callback)
        if cache_key in self.pending or app.demo:
            return
        self.pending.add(cache_key)
        backend = app.service.backend

        def valid():
            try:
                return account == app.ui_account and self.tree.winfo_exists()
            except tk.TclError:
                return False

        def ready(path):
            if not path or not valid():
                self.pending.discard(cache_key)
                return

            def painted(picture):
                self.pending.discard(cache_key)
                if picture is None or not valid():
                    return
                self.photos[cache_key] = picture
                while len(self.photos) > 256:
                    self.photos.pop(next(iter(self.photos)))
                for waiter in self.__dict__.get('waiters', {}).pop(cache_key, []):
                    try:
                        waiter(picture)
                    except tk.TclError:
                        pass
                self.refresh()
            app.request_photo(path, (size, size), painted, owner=self.tree,
                              tint=app.emoji_tint(document, account), valid=valid)
        app.emoji_art(document, account, backend, ready, valid=valid)

    def forward(self, event, row, sequence):
        """An overlay is part of its row: select it / open its menu."""
        tree = self.tree
        x = event.widget.winfo_x() + event.x
        y = event.widget.winfo_y() + event.y
        try:
            tree.focus_set()
            tree.event_generate(sequence, x=x, y=y)
        except tk.TclError:
            pass
        return 'break'


def photo_for(overlay, document, size):
    """An already loaded custom emoji picture, or None."""
    if overlay is None or document is None:
        return None
    return overlay.photos.get((overlay.app.ui_account, document, size))
