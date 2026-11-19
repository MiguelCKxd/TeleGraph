"""Prepare everything at startup (1.5, Settings › Customization, off by default).

Startup takes longer, in exchange for a smoother session afterwards: once the
chat list is loaded, TG-ASCII prepares in the background, in order,

1. the profile photo of *every* chat in the list (not only the visible rows),
   downloaded into the persistent cache and decoded at list size;
2. the latest messages of the first chats, kept in memory so opening them is
   instant (and works offline);
3. the custom emoji and stickers those messages use.

A progress bar with "Skip" is shown at the top. Requests are sequential and
spaced, a FLOOD_WAIT stops the step that caused it, and switching account or
closing the app cancels the rest. Nothing is sent or marked as read.
"""
import asyncio
import tkinter as tk
from tkinter import ttk

from telethon import errors

from .i18n import tr
from .preferences import animated_emoji_enabled

HISTORY_CHATS = 25
SPACING = 0.25


def enabled(app):
    return bool(app.preferences.values.get('preload_startup', False)) and not app.demo


def maybe_start(app):
    """Called once per account after its first chat list load."""
    if not enabled(app) or getattr(app, '_chat_only', False):
        return
    done = app.__dict__.setdefault('_preloaded_accounts', set())
    if app.ui_account in done:
        return
    done.add(app.ui_account)
    Preloader(app).start()


class Preloader:
    def __init__(self, app):
        self.app = app
        self.account = app.ui_account
        self.backend = app.service.backend
        self.cancelled = False
        self.frame = None
        self.total = self.done = 0

    # -- Tk side -----------------------------------------------------------
    def valid(self):
        app = self.app
        return (not self.cancelled and not app.closed and not app.closing
                and app.ui_account == self.account and app.service.backend is self.backend)

    def show(self):
        app = self.app
        frame = ttk.Frame(app.root, padding=(10, 4))
        try:
            frame.pack(fill='x', before=app.viewport)
        except tk.TclError:
            frame.pack(fill='x')
        self.label = ttk.Label(frame, text=tr('Preparing TG-ASCII for a smoother experience...'))
        self.label.pack(side='left')
        ttk.Button(frame, text=tr('Skip'), command=self.cancel).pack(side='right')
        self.bar = ttk.Progressbar(frame, length=180, mode='determinate', maximum=100)
        self.bar.pack(side='right', padx=8)
        self.frame = frame

    def progress(self, _=None):
        if self.frame is None or not self.frame.winfo_exists():
            return
        value = int(self.done * 100 / self.total) if self.total else 100
        self.bar['value'] = value
        self.label.configure(text=tr('Preparing TG-ASCII for a smoother experience...') + f' {value}%')

    def finish(self, _=None):
        if self.frame is not None and self.frame.winfo_exists():
            self.frame.destroy()
        self.frame = None
        if self.valid():
            self.app.status.set(tr('TG-ASCII is ready.'))
            try:
                self.app.request_avatars()
            except Exception:
                pass

    def cancel(self):
        self.cancelled = True
        self.finish()

    def start(self):
        app = self.app
        chats = list(app.chats)
        self.total = len(chats) + min(len(chats), HISTORY_CHATS) * 2
        if not self.total:
            return
        self.show()
        app.worker.submit(self.run(chats), self.finish, lambda _: self.finish())

    def tick(self):
        self.done += 1
        self.app.worker.events.put((self.progress, None))

    # -- worker side -------------------------------------------------------
    async def run(self, chats):
        app, account, backend = self.app, self.account, self.backend
        player = getattr(app, 'animation_player', None)
        enabled = animated_emoji_enabled(app.preferences.values)
        # 1. Avatars of every chat.
        for chat in chats:
            if self.cancelled:
                return
            key = (account, chat.id, 'avatar')
            path = app.preview_dir / f'{account}-{chat.id}-avatar.jpg'
            try:
                if key not in app.preview_cache or not path.is_file():
                    result = await asyncio.wait_for(backend.avatar(chat.id, path, entity=chat.entity), 20)
                else:
                    result = path
                if result and player is not None:
                    await asyncio.to_thread(player.prepare, result, (30, 30), enabled)
                if result:
                    app.worker.events.put((lambda value, key=key: app.preview_cache.__setitem__(key, value), result))
            except errors.FloodWaitError:
                break
            except Exception:
                pass
            self.tick()
            await asyncio.sleep(SPACING / 4)
        # 2. Recent messages of the first chats, 3. their custom emoji.
        emoji_ids = []
        for chat in chats[:HISTORY_CHATS]:
            if self.cancelled:
                return
            try:
                messages = await asyncio.wait_for(backend.history(chat.id), 20)
                app.worker.events.put((self.cache_history, (chat.id, messages)))
                for message in messages:
                    for document_id, _ in getattr(message, 'custom_emojis', ()) or ():
                        if document_id not in emoji_ids:
                            emoji_ids.append(document_id)
            except errors.FloodWaitError:
                break
            except Exception:
                pass
            self.tick()
            await asyncio.sleep(SPACING)
        if emoji_ids and not self.cancelled:
            app.worker.events.put((self.warm_emoji, emoji_ids[:200]))
        while self.done < self.total and not self.cancelled:
            self.tick()

    def cache_history(self, item):
        if not self.valid():
            return
        peer, messages = item
        if peer == self.app.active:
            return  # The open chat already has fresher state.
        cache = self.app.__dict__.setdefault('_history_cache', {})
        cache[(self.account, peer)] = list(messages)[-200:]

    def warm_emoji(self, ids):
        if not self.valid():
            return
        for document_id in ids:
            try:
                self.app.emoji_art(document_id, self.account, self.backend, lambda _path: None)
            except Exception:
                pass
