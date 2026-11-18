"""Photo carousel for articles (1.4), as in the official apps' Instant View.

Slideshow and collage blocks become a horizontal carousel: ‹ › buttons, a
dot indicator, the caption, horizontal drag/arrow keys to move and a click to
open the photo in the viewer. A single photo block is shown inline. Pictures
load only when their slide is shown (preview size) and share the persistent
preview cache.
"""
import tkinter as tk
from tkinter import ttk

from telethon import types as t

from .i18n import tr
from .rich_articles import rich_text

HEIGHT = 260


def slide_items(block, photos):
    """(photo or None, caption, kind) for every slide of a block."""
    if isinstance(block, (t.PageBlockSlideshow, t.PageBlockCollage)):
        children = list(block.items or ())[:100]
    else:
        children = [block]
    result = []
    for child in children:
        caption = getattr(child, 'caption', None)
        text = rich_text(getattr(caption, 'text', caption)) if caption is not None else ''
        if isinstance(child, t.PageBlockPhoto):
            result.append((photos.get(child.photo_id), text, 'photo'))
        elif isinstance(child, t.PageBlockVideo):
            result.append((None, text or tr('[Video]'), 'video'))
    return result


class PhotoCarousel(ttk.Frame):
    def __init__(self, parent, app, backend, items, caption=''):
        super().__init__(parent)
        self.app, self.backend, self.items, self.index = app, backend, items, 0
        self.account = app.ui_account
        self.photos, self.paths, self.drag = {}, {}, None
        self.canvas = tk.Canvas(self, height=HEIGHT, highlightthickness=0, bg='#0b130e', cursor='hand2')
        self.canvas.pack(fill='x', expand=True)
        controls = ttk.Frame(self)
        controls.pack(fill='x')
        self.previous = ttk.Button(controls, text='‹', width=3, command=lambda: self.show(self.index - 1))
        self.previous.pack(side='left')
        self.dots = ttk.Label(controls, anchor='center')
        self.dots.pack(side='left', fill='x', expand=True)
        self.next = ttk.Button(controls, text='›', width=3, command=lambda: self.show(self.index + 1))
        self.next.pack(side='right')
        self.caption = ttk.Label(self, wraplength=520, style='Muted.TLabel')
        self.caption.pack(fill='x', pady=(2, 0))
        self.block_caption = caption
        if len(items) <= 1:
            self.previous.pack_forget()
            self.next.pack_forget()
        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<ButtonRelease-1>', self.release)
        self.canvas.bind('<Configure>', lambda _: self.paint())
        for widget in (self, self.canvas):
            widget.bind('<Left>', lambda _: self.show(self.index - 1))
            widget.bind('<Right>', lambda _: self.show(self.index + 1))
        self.canvas.configure(takefocus=True)
        self.show(0)

    def alive(self):
        try:
            return bool(self.winfo_exists()) and self.account == self.app.ui_account
        except tk.TclError:
            return False

    def show(self, index):
        if not self.items:
            return
        self.index = max(0, min(len(self.items) - 1, index))
        count = len(self.items)
        self.dots.configure(text=' '.join('●' if i == self.index else '○' for i in range(min(count, 15)))
                            + (f'  {self.index + 1}/{count}' if count > 1 else ''))
        photo, text, kind = self.items[self.index]
        self.caption.configure(text=text or self.block_caption)
        self.previous.configure(state='normal' if self.index > 0 else 'disabled')
        self.next.configure(state='normal' if self.index < count - 1 else 'disabled')
        self.paint()
        for neighbour in (self.index, self.index + 1):  # Prefetch the next slide.
            if 0 <= neighbour < count:
                self.load(neighbour)

    def paint(self):
        if not self.alive():
            return
        self.canvas.delete('all')
        width = max(1, self.canvas.winfo_width())
        image = self.photos.get(self.index)
        photo, text, kind = self.items[self.index]
        if image is not None:
            self.canvas.create_image(width / 2, HEIGHT / 2, image=image, anchor='center')
        else:
            label = '▶ ' + tr('Video') if kind == 'video' else tr('Loading...') if photo is not None else '◇'
            self.canvas.create_text(width / 2, HEIGHT / 2, text=label, fill='#80a98c')

    def load(self, index):
        photo, _, kind = self.items[index]
        if photo is None or index in self.paths or getattr(self.app, 'demo', False):
            return
        self.paths[index] = None
        target = self.app.preview_dir / f'{self.account}-article-{photo.id}-carousel.jpg'

        def loaded(path):
            if not path or not self.alive():
                return
            self.paths[index] = path

            def painted(image):
                if self.alive():
                    self.photos[index] = image
                    if index == self.index:
                        self.paint()
            self.app.request_photo(path, (900, HEIGHT), painted, owner=self.canvas, valid=self.alive)
        self.app.worker.submit(self.backend.download_media(t.MessageMediaPhoto(photo), target, thumbnail=True),
                               loaded, lambda _: None)

    def press(self, event):
        self.drag = event.x
        self.canvas.focus_set()

    def release(self, event):
        start, self.drag = self.drag, None
        if start is None:
            return
        moved = event.x - start
        if abs(moved) >= 50:
            self.show(self.index + (1 if moved < 0 else -1))
        else:
            self.open_current()

    def open_current(self):
        photo, text, kind = self.items[self.index]
        if photo is None:
            return
        full = self.app.preview_dir / f'{self.account}-article-{photo.id}-full'
        items = self.items

        def loaded(path):
            if not path or not self.alive():
                return
            from .media_viewer import show_image
            state = {'index': self.index}

            def navigate(direction):
                target = state['index'] + direction
                if not 0 <= target < len(items) or items[target][0] is None:
                    return
                state['index'] = target
                image = items[target][0]
                destination = self.app.preview_dir / f'{self.account}-article-{image.id}-full'
                self.app.worker.submit(self.backend.download_media(t.MessageMediaPhoto(image), destination),
                                       lambda result: viewer._set_media(result, items[target][1]) if viewer.winfo_exists() else None,
                                       lambda _: None)
            viewer = show_image(self.app.root, path, text, navigate=navigate if len(items) > 1 else None)
            if hasattr(self.app, 'popups'):
                self.app.popups.append(viewer)
        self.app.worker.submit(self.backend.download_media(t.MessageMediaPhoto(photo), full), loaded,
                               lambda error: self.app.show_error(error))
