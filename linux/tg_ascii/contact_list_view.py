"""Detailed contact list (Complex features › Contact list details, off by default).

Each row shows the profile photo, the name, the activity status and, for
Telegram Premium users, their emoji status as a badge on the photo. Photos are
loaded only for rows that become visible, four at a time, reusing the
persistent avatar cache; nothing is fetched while the list stays closed.
"""
import asyncio
import tkinter as tk
from tkinter import ttk

from telethon import utils

SIDE = 32
CONCURRENCY = 4


class DetailedContacts(ttk.Frame):
    def __init__(self, parent, app, contacts):
        super().__init__(parent)
        self.app, self.contacts = app, contacts
        self.account, self.backend = app.ui_account, app.service.backend
        self.tree = ttk.Treeview(self, show='tree', selectmode='extended')
        self.tree.column('#0', stretch=True)
        bar = ttk.Scrollbar(self, command=self.tree.yview)
        self.tree.configure(yscrollcommand=lambda first, last: (bar.set(first, last), self.request()))
        self.tree.pack(side='left', fill='both', expand=True)
        bar.pack(side='right', fill='y')
        self.pack(fill='both', expand=True)
        style = ttk.Style(self)
        style.configure('Contacts.Treeview', rowheight=SIDE + 8)
        self.tree.configure(style='Contacts.Treeview')
        from .telegram_actions import peer_activity
        seconds = app.preferences.values.get('show_seconds', False)
        for index, person in enumerate(contacts):
            name = app.text_display(utils.get_display_name(person) or str(person.id), True)
            try:
                activity = peer_activity(person, seconds)
            except Exception:
                activity = ''
            self.tree.insert('', 'end', iid=str(index), text=f'  {name}' + (f'  ·  {activity}' if activity else ''))
        self.images, self.pending, self.done = {}, set(), set()
        self.tree.bind('<Configure>', lambda _: self.request())
        self.after_idle(self.request)

    def set_filter(self, indices):
        """Show only these contact indices (search); selection is kept."""
        wanted = set(indices)
        for index in range(len(self.contacts)):
            item = str(index)
            if index in wanted:
                self.tree.move(item, '', 'end')
            else:
                self.tree.detach(item)
        self.after_idle(self.request)

    # CheckList-compatible surface used by the contacts dialog.
    def curselection(self):
        return [int(item) for item in self.tree.selection()]

    def bind(self, sequence=None, func=None, add=None):
        return self.tree.bind(sequence, func, add)

    def alive(self):
        try:
            return bool(self.winfo_exists()) and self.account == self.app.ui_account
        except tk.TclError:
            return False

    def visible(self):
        from .ui_work import visible_tree_rows
        try:
            return [int(item) for item in visible_tree_rows(self.tree)]
        except Exception:
            return list(range(min(len(self.contacts), 20)))

    def request(self):
        if not self.alive():
            return
        for index in self.visible():
            if len(self.pending) >= CONCURRENCY:
                break
            if index in self.done or index in self.pending:
                continue
            self.pending.add(index)
            self.app.worker.submit(self.prepare(index), lambda image, index=index: self.loaded(index, image),
                                   lambda _, index=index: self.loaded(index, None))

    async def prepare(self, index):
        person = self.contacts[index]
        path = self.app.preview_dir / f'{self.account}-{person.id}-contact.jpg'
        avatar = await self.backend.avatar(person.id, path, entity=person)
        emoji = None
        status = getattr(person, 'emoji_status', None)
        document_id = getattr(status, 'document_id', None)
        if document_id:
            try:
                documents = await self.backend.custom_emoji_documents([document_id])
                if documents:
                    from .animation import emoji_file
                    emoji = await emoji_file(self.app, documents[0], self.account, self.backend)
            except Exception:
                emoji = None
        return await asyncio.to_thread(compose, avatar, emoji)

    def loaded(self, index, image):
        self.pending.discard(index)
        self.done.add(index)
        if not self.alive():
            return
        if image is not None:
            from PIL import ImageTk
            photo = ImageTk.PhotoImage(image, master=self)
            self.images[index] = photo
            if self.tree.exists(str(index)):
                self.tree.item(str(index), image=photo)
        self.request()


def compose(avatar, emoji):
    """Round-cornered photo with the emoji status as a badge (first frame)."""
    from PIL import Image, ImageDraw
    canvas = Image.new('RGBA', (SIDE, SIDE), (0, 0, 0, 0))
    if avatar:
        try:
            with Image.open(avatar) as source:
                picture = source.convert('RGBA')
            picture.thumbnail((SIDE, SIDE))
            mask = Image.new('L', picture.size, 0)
            ImageDraw.Draw(mask).ellipse((0, 0, picture.size[0] - 1, picture.size[1] - 1), fill=255)
            canvas.paste(picture, ((SIDE - picture.size[0]) // 2, (SIDE - picture.size[1]) // 2), mask)
        except Exception:
            pass
    if emoji:
        try:
            with Image.open(emoji) as source:
                badge = source.convert('RGBA')
            badge.thumbnail((16, 16))
            canvas.alpha_composite(badge, (SIDE - badge.size[0], SIDE - badge.size[1]))
        except Exception:
            pass
    return canvas if (avatar or emoji) else None
