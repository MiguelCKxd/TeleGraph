"""Additional chat windows reuse the account connection and the app's worker.

No session database is opened twice. An explicitly independent app process has
its own data directory and login. Linked windows are event driven: hidden
windows retain incoming data without repainting or polling the server.
"""
import asyncio
import inspect
from pathlib import Path
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import uuid
import weakref

from . import APP_NAME
from .i18n import tr
from .desktop_tools import DesktopTools
from .desktop_advanced import DesktopAdvancedMixin
from .ui_work import FrameJob, bind_text_action, clear_text_actions
from .preferences import animated_emoji_enabled


def pinned_backend(app, account):
    service = getattr(app.service, 'services', {}).get(account)
    backend = getattr(service, 'backend', None)
    if backend is None:
        raise ValueError(tr('Inicia sesion de nuevo'))
    return backend


def independent_command(directory):
    command = [sys.executable]
    if not getattr(sys, 'frozen', False):
        command += ['-m', 'tg_ascii']
    return [*command, '--data-dir', str(Path(directory).resolve())]


def open_independent_window(app, ident=None):
    """1.5.4: saved or temporary, see saved_windows.py."""
    from .saved_windows import open_window
    return open_window(app, ident)


def open_chat_window(app):
    if app.active is None:
        raise ValueError(tr('Primero elige un chat.'))
    window = LinkedChatWindow(app, app.ui_account, app.active)
    if not hasattr(app, '_chat_windows'):
        app._chat_windows = []
    app._chat_windows.append(window)
    return window


def forward_chat_event(app, account, peer, message):
    if getattr(app, '_linked_owner', None) is None:
        for window in tuple(getattr(app, '_app_windows', ())):
            if (not window.closed and not window.closing
                    and (not getattr(window, '_chat_only', False) or (account, peer) == (window._pinned_account, window._pinned_peer))):
                window._forwarding_account_event = True
                try:
                    window.account_event((account, peer, message))
                finally:
                    window._forwarding_account_event = False
    for window in tuple(getattr(app, '_chat_windows', ())):
        window.receive(account, peer, message)


def forward_chat_change(app, account, kind, payload):
    if getattr(app, '_linked_owner', None) is None:
        for window in tuple(getattr(app, '_app_windows', ())):
            if (not window.closed and not window.closing
                    and (not getattr(window, '_chat_only', False) or account == window._pinned_account)):
                window.account_change((account, kind, payload))
    for window in tuple(getattr(app, '_chat_windows', ())):
        window.change(account, kind, payload)
    for browser in tuple(getattr(app, '_topic_browsers', ())):
        browser.change(account, kind, payload)


def close_chat_windows(app):
    for window in tuple(getattr(app, '_app_windows', ())):
        window._parent_close = True
        window.close()
    for window in tuple(getattr(app, '_chat_windows', ())):
        window.close()


class LinkedChatWindow(DesktopAdvancedMixin, DesktopTools):
    thread = None
    thread_id = None
    topic = None
    topic_id = None
    _history_revision = 0
    attachment_bar = None

    @property
    def ui_account(self):
        return getattr(self, '_ui_account', getattr(self, 'account', None))

    @ui_account.setter
    def ui_account(self, value):
        self._ui_account = value

    @property
    def active(self):
        return getattr(self, '_active', getattr(self, 'peer', None))

    @active.setter
    def active(self, value):
        self._active = value

    @property
    def preferences(self):
        return getattr(self, '_preferences', getattr(getattr(self, 'app', None), 'preferences', None))

    @preferences.setter
    def preferences(self, value):
        self._preferences = value

    def __init__(self, app, account, peer, *, thread=None, topic=None):
        self.app, self.account, self.peer = app, account, peer
        self.thread = thread
        self.thread_id = thread['root_id'] if thread else None
        # 3.3: a forum topic (contract of forum_topics.py) is a paged, scoped view.
        self.topic = dict(topic) if topic else None
        self.topic_id = topic['id'] if topic else None
        self.backend = pinned_backend(app, account)
        self.closed = self.busy = self.loading = False
        self.messages = ([thread['root']] if thread else
            list(app.messages) if (app.ui_account, app.active) == (account, peer) else [])
        self.pending = set()
        self.history_changes = []
        self.generation = 0
        self.photos = []
        self.attachment = None
        self.reply_to = None
        self.format_tags = {}
        self._draft_edited = self._draft_applying = self._draft_saving = False
        self._draft_again = None
        self.read_max = 0
        self.read_pending = False
        self.dirty = True
        self.follow = True
        self.window = tk.Toplevel(app.root)
        from .transitions import fade_in
        fade_in(app, self.window)
        # A scoped Composer adapter: no operation consults the main window's
        # current account after this window has been opened.
        self.ui_account, self.active = account, peer
        self.root, self.demo, self.preferences = self.window, app.demo, app.preferences
        self.service = SimpleNamespace(backend=self.backend, entries=getattr(getattr(app, 'service', None), 'entries', {}))
        self.worker = getattr(app, 'worker', None)
        self.load_photo = getattr(app, 'load_photo', None)
        self.emoji_art = getattr(app, 'emoji_art', None)
        self.emoji_tint = getattr(app, 'emoji_tint', None)
        self.request_photo = getattr(app, 'request_photo', None)
        self.fetch_art = getattr(app, 'fetch_art', None)
        self.text_display = getattr(app, 'text_display', lambda t, *_: t)
        self.open_link = getattr(app, 'open_link', None)
        self.preview_dir = getattr(app, 'preview_dir', None)
        self.media_temps = getattr(app, 'media_temps', [])
        self.audio_jobs = getattr(app, 'audio_jobs', [])
        self.show_error = getattr(app, 'show_error', None)
        self.chat_translations = getattr(app, 'chat_translations', {})
        self.translated = getattr(app, 'translated', {})
        self.translation_pending = getattr(app, 'translation_pending', set())
        self.translation_failed = getattr(app, 'translation_failed', set())
        self._translation_originals = getattr(app, '_translation_originals', set())
        self._translation_attempted = getattr(app, '_translation_attempted', set())
        self.reply_cache = getattr(app, 'reply_cache', {})
        self.message_palettes = getattr(app, 'message_palettes', {})
        self.wallpaper_path = getattr(app, 'wallpaper_path', None)
        self.wallpapers = getattr(app, 'wallpapers', {})
        self.popups = []
        if hasattr(app, '_suppressed_thread_peers'):
            app._suppressed_thread_peers.discard(peer)
        if thread and hasattr(app, 'active') and hasattr(app, 'chat_translations'):
            channel_lang = app.chat_translations.get(f'{account}:{app.active}')
            if channel_lang and f'{account}:{peer}' not in self.chat_translations:
                self.chat_translations[f'{account}:{peer}'] = channel_lang
        self.render_messages = lambda *_: self.request_render()

        family = getattr(app, 'preferences', None) and app.preferences.values.get('font_family', 'Menlo' if sys.platform == 'darwin' else 'Consolas') or ('Menlo' if sys.platform == 'darwin' else 'Consolas')
        size = getattr(app, 'preferences', None) and app.preferences.values.get('font_size', 12) or 12
        font = (family, size)
        self.font = font
        self.font_family = getattr(app, 'font_family', family)
        from .appearance import app_palette
        colors = app_palette(getattr(getattr(app, 'preferences', None), 'values', {}))
        self.colors = colors
        self.window.configure(bg=colors['bg'])

        chat = next((chat for chat in getattr(app, 'chats', ()) if chat.id == peer), None)
        labels = getattr(getattr(app, 'service', None), 'labels', {})
        self.window.title(f'{chat.name if chat else peer} · {labels.get(account, account)} · {APP_NAME}')
        if self.topic:
            self.window.title(f'# {self.topic.get("title") or self.topic_id} · {chat.name if chat else peer} · {APP_NAME}')
        self.window.geometry('640x650')
        self.window.minsize(360, 300)
        toolbar = ttk.Frame(self.window, padding=6)
        toolbar.pack(fill='x')
        ttk.Button(toolbar, text=tr('Actualizar'), command=self.refresh).pack(side='left')
        from .advanced_features import feature_enabled
        if feature_enabled(self.app, 'chat_translation'):
            ttk.Button(toolbar, text=tr('Translate chat'), command=self.translation_dialog).pack(side='left', padx=4)
        if thread or topic:
            ttk.Button(toolbar, text=tr('Previous page'), command=self.older_comments).pack(side='left')
            if thread:
                ttk.Label(toolbar, text=tr('Comment drafts stay on this device.')).pack(side='left', padx=6)
            else:
                # 3.3: search and scheduled messages inside the topic.
                from .desktop_forums import topic_search, topic_scheduled
                ttk.Button(toolbar, text=tr('Search'), command=lambda: topic_search(self)).pack(side='left', padx=4)
                ttk.Button(toolbar, text=tr('Scheduled messages'), command=lambda: topic_scheduled(self)).pack(side='left')
            self._thread_offset, self._thread_more = 0, False
        ttk.Button(toolbar, text=tr('Close'), command=self.close).pack(side='right')
        body = ttk.Frame(self.window)
        body.pack(fill='both', expand=True)
        self.body = body
        from .composer import Composer
        from .bubbles import BubbleView
        self.history = Composer(body, self, state='disabled', wrap='word', font=font,
                               bg=colors['bg'], fg=colors['text'], insertbackground=colors['text'],
                               selectbackground=colors['line'], relief='flat', borderwidth=0, padx=10, pady=10)
        self.bubble_view = BubbleView(body, self, bg=colors['bg'])
        scrollbar = ttk.Scrollbar(body, command=self.scroll_messages)
        scrollbar.pack(side='right', fill='y')
        self.scrollbar = scrollbar
        self.history.configure(yscrollcommand=self.scroll_position)
        self.bubble_view.configure(yscrollcommand=self.scroll_position)
        body._scroll_target = self.bubble_view
        self.status = tk.StringVar(master=self.window, value='')
        ttk.Label(self.window, textvariable=self.status, wraplength=500).pack(fill='x', padx=8)
        self.reply_label = ttk.Label(self.window)
        self.reply_label.pack(fill='x', padx=8)

        self.attachment_bar = ttk.Frame(self.window, padding=(8, 2))
        self.attachment_label = ttk.Label(self.attachment_bar, text='')
        self.attachment_label.pack(side='left')
        ttk.Button(self.attachment_bar, text=tr('Quitar archivo'), command=self.clear_attachment).pack(side='right')

        self.editor = Composer(self.window, self, height=3, wrap='word', font=font, undo=True,
                               bg=colors['panel'], fg=colors['text'], insertbackground=colors['text'],
                               selectbackground=colors['line'], highlightbackground=colors['line'], highlightthickness=1)
        self.snapshot_custom = self.editor.snapshot_custom
        self.editor.pack(fill='x', padx=8, pady=4)
        controls = ttk.Frame(self.window, padding=6)
        controls.pack(fill='x')
        self.composer_controls = controls
        self.attach_button = ttk.Button(controls, text=tr('[+] Adjuntar'), command=self.attach)
        self.attach_button.pack(side='left')
        ttk.Button(controls, text=tr('Format'), command=self.format_dialog).pack(side='left')
        ttk.Button(controls, text=tr('Quitar archivo'), command=self.clear_attachment).pack(side='left')
        self.send_button = ttk.Button(controls, text=tr('Enviar >'), command=self.send)
        self.send_button.pack(side='right')
        self.job = FrameJob(self.window, self.render)
        self.draft_job = FrameJob(self.window, self.persist_draft, delay=600)
        self.draft_store = getattr(getattr(app, 'draft_manager', None), 'store', None)
        used = {getattr(window, 'draft_account', '') for window in getattr(app, '_chat_windows', ()) if window.peer == peer}
        self.draft_account = (f'topic:{account}:{self.topic_id}' if topic else
                              f'thread:{account}:{self.thread_id}' if thread else f'linked:{account}')
        prefix = self.draft_account
        slot = 1
        while self.draft_account in used:
            self.draft_account = f'{prefix}:{slot}'
            slot += 1
        record = self.draft_store.get(self.draft_account, peer) if self.draft_store else None
        if record is None and self.draft_store and not thread and not topic:
            record = self.draft_store.get(account, peer)
        if record:
            self.editor.insert('1.0', record['text'])
            self.editor.restore_custom(record.get('custom', ()))
            self.restore_formats(record.get('formats', ()))
            files = record.get('files', ())
            if files:
                valid_files = tuple(Path(path) for path in files if Path(path).is_file())
                self.attachment = valid_files[0] if len(valid_files) == 1 else (valid_files if valid_files else None)
                self.update_attachment()
            self.reply_to = record.get('reply')
            self.reply_label.configure(text=f'↪ #{self.reply_to}' if self.reply_to else '')
            self._draft_edited = bool(record.get('pending'))
        self.editor.edit_modified(False)
        self.editor.bind('<<Modified>>', self.draft_changed, add='+')
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.bind('<Destroy>', lambda event: self.close(destroy=False) if event.widget is self.window else None, add='+')
        self.window.bind('<Map>', self._mapped, add='+')
        self.window.bind('<Unmap>', self._unmapped, add='+')
        self.window.bind('<FocusIn>', lambda _: self.acknowledge(), add='+')
        from .composer_keys import install as install_composer_keys
        install_composer_keys(self.editor, lambda: self.app.preferences.values, self.send)
        self.editor.bind('<Escape>', lambda _: self.reply(None))
        self.history.bind('<Button-3>', self.context)
        if sys.platform == 'darwin':
            self.history.bind('<Button-2>', self.context)
            self.history.bind('<Control-Button-1>', self.context)
        self.history.bind('<Double-Button-1>', self.double_click)
        try:
            from .media_viewer import enable_drop
            enable_drop(self.window, [self.editor, self.history], self.dropped_files)
        except Exception:
            pass
        from .themes import apply_widget
        apply_widget(self.window)
        self.request_render()
        if thread or not self.messages:
            self.refresh()

    def valid(self):
        return (not self.closed and not getattr(self.app, 'closing', False)
                and self.account not in getattr(self.app, '_logging_out_accounts', ())
                and self.account in self.app.service.entries
                and getattr(self.app.service.services.get(self.account), 'backend', None) is self.backend)

    def visible(self):
        return not self.closed and bool(self.window.winfo_viewable())

    def chat_visible(self):
        return self.valid() and self.visible()

    def scroll_position(self, *args):
        if hasattr(self, 'scrollbar') and self.scrollbar.winfo_exists():
            self.scrollbar.set(*args)

    def scroll_messages(self, *args):
        target = self.bubble_view if getattr(self, '_canvas_chat_view', self.preferences.values.get('bubbles', True)) else self.history
        if hasattr(target, 'yview') and target.winfo_exists():
            target.yview(*args)

    def dialog(self, title, size='520x500'):
        for previous in getattr(self, 'popups', ()):
            if previous.winfo_exists() and previous.title() == tr(title):
                previous.destroy()
        if not hasattr(self, 'popups'):
            self.popups = []
        self.popups = [w for w in self.popups if w.winfo_exists()]
        window = tk.Toplevel(self.root)
        window.title(tr(title))
        from .appearance import app_palette
        colors = app_palette(getattr(getattr(self, 'preferences', None), 'values', {}))
        window.configure(bg=colors.get('bg', '#08100c'))
        width, height = map(int, size.split('x'))
        window.geometry(f'{min(width, window.winfo_screenwidth()-48)}x{min(height, window.winfo_screenheight()-80)}')
        window.minsize(320, 260)
        window.transient(self.root)
        window.bind('<Escape>', lambda _: window.destroy())
        from .scrolling import Viewport
        viewport = Viewport(window, minimum=(320, 260))
        viewport.pack(fill='both', expand=True)
        frame = viewport.content
        frame.configure(padding=12, style='Surface.TFrame')
        self.popups.append(window)
        from .themes import apply_widget
        apply_widget(window)
        return window, frame

    def update_appearance(self):
        if self.closed or not self.window.winfo_exists():
            return
        from .appearance import app_palette
        colors = app_palette(getattr(getattr(self.app, 'preferences', None), 'values', {}))
        self.colors = colors
        family = getattr(self.app, 'preferences', None) and self.app.preferences.values.get('font_family', 'Menlo' if sys.platform == 'darwin' else 'Consolas') or ('Menlo' if sys.platform == 'darwin' else 'Consolas')
        size = getattr(self.app, 'preferences', None) and self.app.preferences.values.get('font_size', 12) or 12
        font = (family, size)
        self.font = font
        self.font_family = family
        self.window.configure(bg=colors['bg'])
        self.history.configure(background=colors['bg'], foreground=colors['text'], insertbackground=colors['text'],
                               selectbackground=colors['line'], font=font)
        self.editor.configure(background=colors['panel'], foreground=colors['text'], insertbackground=colors['text'],
                              selectbackground=colors['line'], highlightbackground=colors['line'], font=font)
        if hasattr(self, 'bubble_view') and self.bubble_view.winfo_exists():
            self.bubble_view.configure(bg=colors['bg'])
        from .themes import apply_widget
        apply_widget(self.window)
        self.request_render()

    def reply_message(self, message):
        self.reply(message)

    def quick_react(self, message):
        self.react(message)

    def message_accent(self, message):
        if hasattr(self.app, 'message_accent'):
            return self.app.message_accent(message)
        return ['#6ec9cb']

    def draw_bubble_wallpaper(self, canvas):
        if hasattr(self.app, 'draw_bubble_wallpaper'):
            self.app.draw_bubble_wallpaper(canvas)

    def view_message_media(self, message, peer=None):
        if not self.valid() or self.busy:
            return
        peer = self.peer if peer is None else peer
        if message.media_kind in ('poll', 'checklist', 'location', 'contact', 'gift', 'article'):
            return self.open_advanced_message(message, peer)
        if message.media_kind == 'conference':
            from .desktop_calls import DesktopCalls
            return DesktopCalls.join_conference_message(self, message, peer)
        if message.media_kind in ('image', 'video'):
            return self.open_image_message(message, peer)
        from .desktop_features import DesktopFeatures
        return DesktopFeatures.view_message_media(self, message, peer)

    def media_dialog(self, *args, **kwargs):
        from .desktop_features import DesktopFeatures
        return DesktopFeatures.media_dialog(self, *args, **kwargs)

    def field(self, *args, **kwargs):
        from .desktop_features import DesktopFeatures
        return DesktopFeatures.field(self, *args, **kwargs)

    def start_group_call(self, **kwargs):
        from .desktop_calls import DesktopCalls
        return DesktopCalls.start_group_call(self, **kwargs)

    @property
    def _linked_owner(self):
        return getattr(self.app, '_linked_owner', None) or self.app

    def canvas_emoji(self, canvas, item, document, epoch, size, keep_text=False):
        from .desktop_modern import DesktopModern
        return DesktopModern.canvas_emoji(self, canvas, item, document, epoch, size, keep_text=keep_text)

    def canvas_media(self, canvas, item, message, epoch, size):
        from .desktop_modern import DesktopModern
        return DesktopModern.canvas_media(self, canvas, item, message, epoch, size)

    def open_image_message(self, message, peer=None):
        peer = self.peer if peer is None else peer
        if message.media_kind not in ('image', 'video'):
            return self.view_message_media(message, peer)
        from .custom_menus import handled
        from .menu_style import uses_system
        kind = 'video_player' if message.media_kind == 'video' else 'image_viewer'
        if handled(kind, self, message, peer):
            return
        if uses_system(kind):
            return self.open_message_natively(message, peer)
        from .media_gallery import open_chat_gallery
        return open_chat_gallery(self, message, peer)

    def open_message_natively(self, message, peer=None):
        from .desktop_modern import DesktopModern
        return DesktopModern.open_message_natively(self, message, self.peer if peer is None else peer)

    def native_open_failed(self, error):
        self.worker.events.put((self.show_error, error))

    def open_sender_profile(self, message, scope=None):
        if hasattr(self.app, 'open_sender_profile'):
            self.app.open_sender_profile(message, scope)

    def send_reaction(self, message, value):
        if not self.valid() or self.busy or self.app.demo:
            return
        from .chat_capabilities import chat_capabilities
        if not chat_capabilities(self).allows_message('react', message):
            return
        def updated(result):
            self.messages = [result if item.id == result.id else item for item in self.messages]
            self.request_render()
        self.call(self.backend.react(self.peer, message.id, value), updated)

    def jump(self, ident):
        if getattr(self, '_canvas_chat_view', False) and hasattr(self, 'bubble_view') and self.bubble_view.winfo_exists():
            return self.bubble_view.jump(ident)
        return False

    def jump_message(self, ident, peer=None):
        if peer is not None and peer != self.peer:
            return False
        return self.reveal_message(ident)

    def message_selected(self, ident):
        return False

    def toggle_message_selection(self, message):
        pass

    def clear_selection(self):
        pass

    def _mapped(self, event):
        if event.widget is self.window and self.dirty:
            self.request_render()

    def _unmapped(self, event):
        if event.widget is self.window:
            self.job.cancel()

    def draft_changed(self, event=None):
        if self.closed or self._draft_applying or not self.editor.edit_modified():
            return
        self.editor.edit_modified(False)
        self.draft_job.request()

    def persist_draft(self, capture_only=False):
        if self.draft_store is None or self.closed or self.account in getattr(self.app, '_logging_out_accounts', ()):
            return
        self.draft_job.cancel()
        from .drafts import draft_content
        from .attachments import paths_in
        record = {
            'text': self.editor.get('1.0', 'end-1c'),
            'files': [str(p) for p in paths_in(self.attachment)],
            'custom': self.editor.snapshot_custom(), 'formats': self.snapshot_formats(), 'reply': self.reply_to}
        if record['files']:
            from .attachments import photo_quality_for
            record['photo_quality']=photo_quality_for(self)
        previous = self.draft_store.get(self.draft_account, self.peer)
        if previous is None or draft_content(previous) != draft_content(record):
            self._draft_edited = True
        self.draft_store.put(self.draft_account, self.peer, record, pending=self._draft_edited)
        if not capture_only:
            store = self.draft_store
            async def flush():
                await asyncio.to_thread(store.flush)
            self.call(flush(), lambda _: None)
            self.sync_draft(record)

    def composer_focused(self):
        return self.visible() and self.window.focus_displayof() is self.editor

    def sync_draft(self, record):
        """Telegram has one draft per chat; only the actively edited view writes.

        Other window slots keep their private drafts and cannot overwrite a
        newer edit merely because the window closes or regains visibility.
        """
        if self.thread_id or self.topic_id or self.app.demo or not self.valid() or not self.composer_focused() or not self._draft_edited:
            return
        if self._draft_saving:
            self._draft_again = record
            return
        self._draft_saving = True
        self._draft_again = None
        def done(_):
            from .drafts import draft_content
            self._draft_saving = False
            current = self.draft_store.get(self.draft_account, self.peer)
            if current and draft_content(current) == draft_content(record):
                self._draft_edited = False
                self.draft_store.put(self.draft_account, self.peer, current, pending=False)
            again, self._draft_again = self._draft_again, None
            if again is not None:
                self.sync_draft(again)
        def failed(error):
            from .auth import error_message
            self._draft_saving = False
            self._draft_again = None
            self.status.set(error_message(error))
        self.call(self.backend.save_draft(self.peer, record['text'], record['formats'], record['custom'], record['reply']), done, failed)

    def remote_draft(self, record):
        # Snapshot pending keystrokes before considering another client's draft.
        if self.busy or self._draft_saving or self.composer_focused() or self._draft_edited or self.editor.edit_modified():
            return
        if record.get('unsupported'):
            return  # Never reduce a media/quoted draft to text in this editor.
        self._draft_applying = True
        try:
            self.editor.delete('1.0', 'end')
            self.editor.insert('1.0', record.get('text', ''))
            self.editor.restore_custom(record.get('custom', ()))
            self.restore_formats(record.get('formats', ()))
            self.reply_to = record.get('reply')
            self.reply_label.configure(text=f'↪ #{self.reply_to}' if self.reply_to else '')
            self.editor.edit_modified(False)
            if self.draft_store:
                from .attachments import paths_in, photo_quality_for
                self.draft_store.put(self.draft_account, self.peer, {**record,
                    'files': [str(path) for path in paths_in(self.attachment)],
                    'photo_quality': photo_quality_for(self)}, pending=False)
        finally:
            self._draft_applying = False

    def apply_format(self, style, selection=None):
        result = super().apply_format(style, selection)
        self.draft_job.request()
        return result

    def request_render(self, follow=False):
        self.dirty = True
        self.follow = self.follow or follow
        if self.visible():
            self.job.request()

    def call(self, operation, success, status_or_failure=None, timeout=90, *, failure=None):
        # Shared media controls use Desktop.call's status label; existing
        # window callers pass their error callback as the third argument.
        if callable(status_or_failure):
            failure = status_or_failure
        elif isinstance(status_or_failure, str):
            self.status.set(status_or_failure)
        if callable(timeout):
            # Desktop's inspector contract supplies its error callback fourth.
            failure, timeout = timeout, 90
        if not self.valid():
            operation.close()
            if not self.closed:
                self.status.set(tr('Inicia sesion de nuevo'))
            return None
        reference = weakref.ref(self)
        future = None
        def complete(value, failed=False):
            owner = reference()
            if owner is None:
                return
            owner.pending.discard(future)
            if not owner.valid():
                return
            if failed:
                if failure:
                    failure(value)
                else:
                    from .auth import error_message
                    owner.status.set(error_message(value))
            else:
                from .pending_actions import handle
                if not handle(owner, value, success, failure):
                    success(value)
        async def bounded():
            return await asyncio.wait_for(operation, timeout)
        future = self.app.worker.submit(bounded(), complete, lambda error: complete(error, True))
        self.pending.add(future)
        def release_unstarted(result):
            if result.cancelled() and inspect.getcoroutinestate(operation) == inspect.CORO_CREATED:
                try:
                    operation.close()
                except RuntimeError:
                    pass
        future.add_done_callback(release_unstarted)
        return future

    def refresh(self):
        if self.loading or not self.valid():
            return
        self.loading = True
        self.history_changes = []
        self.status.set(tr('Cargando mensajes...'))
        revision = self.next_history_revision()
        def loaded(messages):
            from .telegram_extras import reconcile_history
            if revision != self._history_revision:
                return  # A later load (a jump to a message) owns the history now.
            self.loading = False
            incoming = [item for kind, (peer, item) in self.history_changes if kind == 'new' and peer == self.peer]
            root = [self.thread['root']] if self.thread else []
            self.messages = reconcile_history([*root, *messages, *incoming], self.history_changes, self.peer)[-200:]
            if self.thread or self.topic_id:
                self._thread_offset, self._thread_more = messages.next_offset, messages.more
            self.history_changes = []
            self.status.set('')
            self.update_topic_state()
            self.request_render()
            self.schedule_translations()
        def failed(error):
            from .auth import error_message
            if revision != self._history_revision:
                return
            self.loading = False
            self.status.set(error_message(error))
        self.call(self.history_page() if (self.thread or self.topic_id) else self.backend.history(self.peer), loaded, failed)

    def next_history_revision(self):
        """Every history request gets a number; only the newest one is applied."""
        self._history_revision = self._history_revision + 1
        return self._history_revision

    def history_page(self, before=0):
        """One page of this window's thread or topic, ending before ``before``."""
        if self.topic_id:
            return self.backend.forum_history(self.peer, self.topic_id, before)
        return self.backend.discussion_history(self.peer, self.thread_id, before)

    def update_topic_state(self):
        """A closed topic or one without send rights keeps the composer read-only."""
        if not self.topic or not hasattr(self, 'send_button'):
            return
        writable = self.topic.get('can_send', True) is not False
        self.send_button.state(['!disabled'] if writable else ['disabled'])
        self.attach_button.state(['!disabled'] if writable else ['disabled'])
        if not writable:
            from .interface_layout import caption
            self.status.set(caption('This topic is closed.', 'Este tema está cerrado.') if self.topic.get('closed')
                            else caption('You cannot write in this topic.', 'No puedes escribir en este tema.'))

    def reveal_message(self, ident):
        """Show and highlight a message, loading its page when it is not here (3.3)."""
        if not self.valid():
            return
        if self.jump(ident):
            self.highlight(ident)
            return
        self.loading = True
        self.history_changes = []
        revision = self.next_history_revision()
        def loaded(page):
            from .telegram_extras import reconcile_history
            if revision != self._history_revision or not self.valid():
                return
            self.loading = False
            root = [self.thread['root']] if self.thread else []
            self.messages = reconcile_history([*root, *page], self.history_changes, self.peer)
            if self.thread or self.topic_id:
                self._thread_offset = getattr(page, 'next_offset', 0)
                self._thread_more = getattr(page, 'more', False)
            self.history_changes = []
            self.follow = False
            self.request_render(follow=False)
            self.window.after(120, lambda: self.highlight(ident) if self.jump(ident) else None)
        def failed(error):
            from .auth import error_message
            if revision != self._history_revision:
                return
            self.loading = False
            self.status.set(error_message(error))
        if self.topic_id:
            # 3.3 core: a page centred on the message within its topic.
            operation = self.backend.forum_history(self.peer, self.topic_id, 0, around=ident)
        elif self.thread and hasattr(self.backend, 'discussion_around'):
            operation = self.backend.discussion_around(self.peer, self.thread_id, ident)
        elif self.thread:
            operation = self.history_page(ident + 1)
        else:
            operation = self.backend.message_context(self.peer, ident)
        self.call(operation, loaded, failed)

    def highlight(self, ident):
        from .transitions import flash_message
        flash_message(self, ident)

    def older_comments(self):
        if not (self.thread or self.topic_id) or self.loading or not self._thread_more or not self.valid():
            return
        self.loading = True
        self.history_changes = []
        revision = self.next_history_revision()
        def loaded(page):
            from .telegram_extras import reconcile_history
            if revision != self._history_revision:
                return
            self.loading = False
            self._thread_more = page.more and page.next_offset != self._thread_offset
            self._thread_offset = page.next_offset
            self.messages = reconcile_history([*page, *self.messages], self.history_changes, self.peer)
            self.history_changes = []
            self.request_render()
            self.schedule_translations()
        def failed(error):
            if revision != self._history_revision:
                return
            self.loading = False
            self.app.show_error(error)
        self.call(self.history_page(self._thread_offset), loaded, failed)

    def belongs(self, message):
        if self.topic_id:
            return (getattr(message, 'topic_id', None) or 1) == self.topic_id
        return (not self.thread_id or message.id == self.thread_id
                or getattr(message, 'thread_id', None) == self.thread_id
                or message.reply_to_id == self.thread_id)

    def receive(self, account, peer, message):
        if self.closed or (account, peer) != (self.account, self.peer):
            return
        if not self.belongs(message):
            return
        if self.loading:
            self.history_changes.append(('new', (peer, message)))
        if any(item.id == message.id and item == message for item in self.messages):
            return
        merged = {item.id: item for item in (*self.messages, message)}
        self.messages = sorted(merged.values(), key=lambda item: item.id)[-200:]
        self.request_render(follow=message.outgoing or self.history.yview()[1] >= .98)
        self.schedule_translations()

    def change(self, account, kind, payload):
        if self.closed or account != self.account:
            return
        if kind == 'connection':
            self.status.set(tr('Connected' if payload == 'online' else 'Sin conexion'))
            return
        if kind == 'draft':
            if not self.thread_id and not self.topic_id and payload[0] == self.peer:
                self.remote_draft(payload[1])
            return
        if kind == 'forum_topics':
            if (self.topic_id and payload and payload[0] == self.peer and payload[1] in (None, self.topic_id)
                    and getattr(self, '_topic_job', None) is None):
                # One request per burst: the core reports every new forum message.
                def fetch():
                    self._topic_job = None
                    if self.valid():
                        self.call(self.backend.forum_topic(self.peer, self.topic_id), self.topic_changed, self.topic_failed)
                self._topic_job = self.window.after(1500, fetch)
            return
        if kind not in ('edit', 'advanced_media', 'delete', 'read', 'reaction'):
            return
        if payload[0] is not None and payload[0] != self.peer:
            return
        if kind == 'reaction':
            peer, message = payload
            if peer == self.peer:
                self.refresh()
            return
        from .telegram_extras import reconcile_history
        if kind in ('edit', 'advanced_media', 'delete'):
            if self.thread_id and kind != 'delete' and not self.belongs(payload[1]):
                return
            if self.loading:
                self.history_changes.append((kind, payload))
            self.messages = reconcile_history(self.messages, [(kind, payload)], self.peer)
            if kind != 'delete':
                self.advanced_media_changed(account, self.peer, payload[1])
        elif kind == 'read' and payload[0] == self.peer:
            changed = False
            for message in self.messages:
                if message.outgoing and message.id <= payload[1] and not message.read:
                    message.read = changed = True
            if not changed:
                return
        self.request_render()

    def topic_failed(self, error):
        """A deleted topic stops accepting messages; a network error changes nothing."""
        from .forum_topics import ForumTopicUnavailable
        if not isinstance(error, ForumTopicUnavailable) or not self.valid():
            return
        self.topic = dict(self.topic or {}, can_send=False, deleted=True)
        self.update_topic_state()
        from .interface_layout import caption
        self.status.set(caption('This topic was deleted.', 'Este tema se ha borrado.'))

    def topic_changed(self, row):
        if not isinstance(row, dict) or not self.valid():
            return
        self.topic = dict(row)
        chat = next((chat for chat in getattr(self.app, 'chats', ()) if chat.id == self.peer), None)
        self.window.title(f'# {row.get("title") or self.topic_id} · {chat.name if chat else self.peer} · {APP_NAME}')
        self.update_topic_state()

    def render(self):
        if not self.visible():
            return
        from .appearance import app_palette
        from .interface_background import chat_backdrop
        from .visual_effects import text_effects_enabled
        from .message_tools import display_segments
        from .links import detected_links
        colors = getattr(self, 'colors', None) or app_palette(getattr(getattr(self.app, 'preferences', None), 'values', {}))
        font = getattr(self, 'font', ('Menlo' if sys.platform == 'darwin' else 'Consolas', 12))
        self.dirty = False
        preferences = getattr(self, 'preferences', None) or getattr(getattr(self, 'app', None), 'preferences', None)
        pref_values = getattr(preferences, 'values', {})
        from .line_breaking import needs_canvas, apply_text_widget
        canvas_view = bool(pref_values.get('bubbles', True) or chat_backdrop(self) or text_effects_enabled(pref_values) or needs_canvas(pref_values))
        if not canvas_view and preferences is not None:apply_text_widget(SimpleNamespace(preferences=preferences), self.history)
        self._canvas_chat_view = canvas_view
        if hasattr(self, 'body'):
            self.body._scroll_target = self.bubble_view if canvas_view else self.history
        if canvas_view and hasattr(self, 'bubble_view') and self.bubble_view.winfo_exists():
            self.history.pack_forget()
            self.bubble_view.pack(side='left', fill='both', expand=True)
            self.bubble_view.render(self.messages, self.follow)
            self.follow = False
            self.acknowledge()
            return
        if hasattr(self, 'bubble_view') and self.bubble_view.winfo_exists():
            self.bubble_view.pack_forget()
        self.history.pack(side='left', fill='both', expand=True)
        previous = self.history.yview()[0]
        self.generation += 1
        epoch = self.generation
        self.photos = []
        clear_text_actions(self.history)
        self.history.configure(state='normal', background=colors['bg'], foreground=colors['text'], font=font)
        self.history.delete('1.0', 'end')
        for name in self.history.mark_names():
            if name.startswith(('linked_', 'media_', 'message_')):
                self.history.mark_unset(name)
        for tag in self.history.tag_names():
            if tag.startswith(('msg_', 'link_', 'tr_')):
                self.history.tag_delete(tag)
        self.history.tag_configure('sender', foreground=colors['muted'], font=(font[0], max(9, font[1]-2), 'bold'))
        self.history.tag_configure('outgoing', foreground=colors['text'])
        from .translated_view import presentation
        for raw_msg in self.messages:
            message, tr_key, tr_label = presentation(self, raw_msg)
            tag = f'msg_{message.id}'
            start = self.history.index('end-1c')
            self.history.mark_set(f'message_{message.id}', start)
            from .timestamps import message_time
            time_str = message_time(message, getattr(self, 'preferences', None) and self.preferences.values)
            self.history.insert('end', f'{message.sender} · {time_str}' + (' ✓✓' if message.read else ' ✓' if message.outgoing else '') + '\n', (tag, 'sender'))
            if message.reply_to_id:
                self.history.insert('end', f'↪ #{message.reply_to_id}\n', tag)
            if tr_key and tr_label:
                tr_tag = f'tr_{message.id}'
                from .translated_view import toggle_original
                self.history.insert('end', f'[{tr(tr_label)}]\n', (tag, tr_tag, 'translation_toggle'))
                self.history.tag_configure('translation_toggle', foreground=colors['muted'], underline=True)
                bind_text_action(self.history, tr_tag, '<Button-1>', lambda _, k=tr_key: toggle_original(self, k))
            alternatives = None
            for index, segment in enumerate(display_segments(message)):
                if isinstance(segment, int):
                    if alternatives is None:
                        from .message_tools import entity_spans
                        raw = message.raw_text if message.raw_text is not None else message.text
                        _, spans = entity_spans(raw, message.entities)
                        alternatives = {}
                        for _, _, document, alt in spans:
                            alternatives.setdefault(document, alt)
                    alt = alternatives.get(segment, '◇')
                    self.history.insert_custom(segment, alt, 'end-1c')
                else:
                    base = self.history.index('end-1c')
                    shown = self.app.text_display(segment)
                    self.history.insert('end', shown, tag)
                    for number, (left, right, url) in enumerate(detected_links(shown)):
                        link = f'link_{message.id}_{index}_{number}'
                        start_offset = self.history.tk.call('string', 'length', shown[:left])
                        end_offset = self.history.tk.call('string', 'length', shown[:right])
                        self.history.tag_add(link, f'{base}+{start_offset} indices', f'{base}+{end_offset} indices')
                        self.history.tag_configure(link, underline=True)
                        bind_text_action(self.history, link, '<Button-1>', lambda _, target=url: self.app.open_link(target))
            if message.media:
                self.history.insert('end', '\n' + (message.filename or tr('Archivo adjunto')), tag)
                from .preferences import shows_preview
                if message.media_kind in ('image', 'video', 'sticker') and shows_preview(self.app.preferences.values, message.media_kind):
                    self.history.insert('end', '\n', tag)
                    marker = f'media_{message.id}'
                    self.history.mark_set(marker, 'end-1c')
                    self.history.mark_gravity(marker, 'left')
                    self.history.insert('end', '◇', tag)
                    self.media_preview(message, marker, tag, epoch)
            if message.reactions:
                self.history.insert('end', '\n' + '  '.join(f'{value if isinstance(value,str) else "◇"} {count}' for value, count, _ in message.reactions), tag)
            self.history.insert('end', '\n\n', tag)
            self.history.tag_add(tag, start, 'end-1c')
        self.history.configure(state='disabled')
        self.history.yview_moveto(1 if self.follow else previous)
        self.follow = False
        self.acknowledge()

    def insert_photo(self, path, marker, tag, epoch, size, tint=None):
        def current():
            return self.valid() and epoch == self.generation and marker in self.history.mark_names()
        if not path or not current():
            return
        def loaded(photo):
            if not photo or not current():
                return
            self.photos.append(photo)
            self.history.configure(state='normal')
            self.history.delete(marker, f'{marker}+1c')
            self.history.image_create(marker, image=photo, align='center')
            self.history.tag_add(tag, marker, f'{marker}+1c')
            self.history.configure(state='disabled')
        self.app.request_photo(path, size, loaded, owner=self.window, tint=tint, valid=current)

    def media_preview(self, message, marker, tag, epoch):
        if self.app.demo:
            return
        from .desktop_media_lifetime import private_preview
        if private_preview(self,message,self.peer):return
        backend, app, account, peer = self.backend, self.app, self.account, self.peer
        async def fetch():
            if message.media_kind == 'sticker':
                from .animation import emoji_file
                return await emoji_file(app, getattr(message.media, 'document', message.media), account, backend, side=256)
            return await backend.download_media(message.media, app.preview_dir / f'{account}-{peer}-{message.id}-thumb.jpg', thumbnail=True)
        reference = weakref.ref(self)
        def loaded(path):
            owner = reference()
            if owner is not None:
                owner.insert_photo(path, marker, tag, epoch, (280, 180))
        key = (account, peer, message.id)
        if message.media_kind == 'sticker':
            key += (animated_emoji_enabled(app.preferences.values),)
        self.app.fetch_art(key, fetch, loaded)

    def acknowledge(self):
        if not self.valid() or not self.visible() or self.app.demo or not self.messages or self.read_pending:
            return
        focused = self.window.focus_displayof()
        if focused is None or focused.winfo_toplevel() is not self.window:
            return
        latest = max(message.id for message in self.messages)
        if latest <= self.read_max:
            return
        self.read_pending = True
        def done(_):
            self.read_pending = False
            self.read_max = latest
            self.acknowledge()
        def failed(_):
            self.read_pending = False
        self.call(self.backend.forum_mark_read(self.peer, self.topic_id, latest) if self.topic_id
                  else self.backend.read_discussion(self.peer, self.thread_id, latest)
                  if self.thread_id else self.backend.mark_read(self.peer, latest), done, failed)

    def reply(self, message):
        self.reply_to = message.id if message else None
        self.reply_label.configure(text=f'↪ {message.sender}: {message.text[:80]}' if message else '')
        self.editor.focus_set()
        self.draft_job.request()

    def attach(self):
        if self.busy:
            return
        from .chat_capabilities import chat_capabilities
        caps = chat_capabilities(self)
        if not self.demo and not self.thread and not any(caps.allows('send_' + kind) for kind in ('photos','videos','docs','audios','gifs')):
            return
        from .app_dialogs import filedialog
        options = {}
        if not self.demo and not self.thread and not caps.allows('send_docs'):
            options['filetypes'] = [(tr(title), extensions) for action, title, extensions in (
                ('send_photos', 'Photos', '*.jpg *.jpeg *.png *.webp'),
                ('send_videos', 'Videos', '*.mp4 *.webm *.mov *.mkv *.avi'),
                ('send_gifs', 'GIF', '*.gif'), ('send_audios', 'Audio', '*.mp3 *.m4a *.ogg *.flac *.wav *.aac')) if caps.allows(action)]
        filenames = filedialog.askopenfilenames(parent=self.window, title=tr('Elegir archivo'), **options)
        if filenames and not self.busy:
            self.prepare_attachments(filenames)

    def prepare_attachments(self, filenames):
        if self.busy:
            return
        from .attachments import merge_paths, paths_in, attachments_allowed
        try:
            merged = merge_paths(self.attachment, filenames)
        except (OSError, ValueError) as exc:
            self.app.show_error(exc)
            return
        if not self.thread and not attachments_allowed(self, paths_in(merged)):
            return
        account, peer = self.ui_account, self.active
        def accept(value):
            if (account, peer) == (self.ui_account, self.active) and not self.busy:
                self.attachment = value
                self.update_attachment()
        paths = paths_in(merged)
        if len(paths) == 1 and hasattr(self.app, 'preview_photo_attachment'):
            self.app.preview_photo_attachment(paths[0], accept)
        else:
            accept(merged)

    def schedule_translations(self):
        if getattr(self, 'demo', False) or not getattr(self, 'chat_translations', None) or not getattr(self, 'worker', None):
            return
        from .translation_queue import schedule
        schedule(self)

    def update_attachment(self):
        bar = getattr(self, 'attachment_bar', None)
        from .attachments import paths_in
        paths = paths_in(self.attachment)
        from .attachments import update_quality_control
        update_quality_control(self,paths)
        if paths:
            name = (tr('[Archivo] ') + paths[0].name) if len(paths) == 1 else (tr('Attachments') + f' ({len(paths)})')
            if hasattr(self, 'attachment_label'):
                self.attachment_label.configure(text=name)
            if bar:
                bar.pack(fill='x', before=self.editor, pady=2)
            if hasattr(self, 'status'):
                self.status.set(name)
        else:
            if bar:
                bar.pack_forget()
            if hasattr(self, 'status') and (self.status.get().startswith(tr('[Archivo] ')) or (self.attachment is None and not getattr(self, 'busy', False))):
                self.status.set('')
        if hasattr(self, 'draft_job'):
            self.draft_job.request()

    def clear_attachment(self):
        if not self.busy:
            self.attachment = None
            self.update_attachment()

    def dropped_files(self, filenames):
        if not self.busy and self.valid():
            self.prepare_attachments(filenames)

    def enter(self, event):
        if self.app.preferences.values['enter_send'] and not event.state & 1:
            self.send()
            return 'break'

    def send(self):
        if self.busy or not self.valid():
            return
        if self.topic and self.topic.get('can_send', True) is False:
            self.update_topic_state()
            return
        text = self.editor.get('1.0', 'end-1c')
        from .attachments import paths_in
        paths = paths_in(self.attachment)
        if not text.strip() and not paths:
            return
        limit = 1024 if paths else 4096
        if len(text.encode('utf-16-le')) // 2 > limit:
            self.status.set(tr('Texto demasiado largo. Limite: ') + str(limit))
            return
        self.busy = True
        self.editor.configure(state='disabled')
        self.send_button.state(['disabled'])
        self.attach_button.state(['disabled'])
        self.status.set(tr('Enviando...'))
        reply_to = self.reply_to or self.thread_id
        from .attachments import photo_quality_for
        quality=photo_quality_for(self) if paths else None
        if self.topic_id and not self.app.demo:
            single = paths[0] if len(paths) == 1 else None
            operation = self.backend.forum_send(
                self.peer, self.topic_id, text, self.snapshot_formats(), self.editor.snapshot_custom(),
                paths=tuple(paths), reply_to=self.reply_to,
                as_photo=bool(single and single.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp')),**({'photo_quality':quality} if quality else {}))
        elif self.app.demo:
            path = paths[0] if paths else None
            operation = self.backend.send_attachment(self.peer, path, caption=text) if path else self.backend.send(self.peer, text)
        else:
            if len(paths) > 1:
                operation = self.backend.send_batch(self.peer, paths, text, self.snapshot_formats(), self.editor.snapshot_custom(), reply_to=reply_to,**({'photo_quality':quality} if quality else {}))
            else:
                path = paths[0] if paths else None
                as_photo = bool(path and path.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp'))
                operation = self.backend.send_formatted(self.peer, text, self.snapshot_formats(), self.editor.snapshot_custom(), path=path,
                    reply_to=reply_to, as_photo=as_photo,**({'photo_quality':quality} if quality else {}))
        def release():
            self.busy = False
            self.editor.configure(state='normal')
            self.send_button.state(['!disabled'])
            self.attach_button.state(['!disabled'])
        def done(message):
            release()
            self.editor.delete('1.0', 'end')
            self.attachment = None
            self.update_attachment()
            self.reply(None)
            self.status.set(tr('Enviado.'))
            self.persist_draft()
            # Main and all linked views receive exactly the same account scope.
            items = message if isinstance(message, list) else [message]
            for item in items:
                self.app.account_event((self.account, self.peer, item))
        def failed(error):
            from .auth import error_message
            release()
            self.status.set(error_message(error) + tr(' Borrador conservado; revisa el chat antes de reintentar.'))
        self.call(operation, done, failed, timeout=None if paths else 90)

    def message_at(self, event):
        if getattr(self, '_canvas_chat_view', False) and hasattr(self, 'bubble_view') and getattr(event, 'widget', None) is self.bubble_view:
            return self.bubble_view.target(event)
        try:
            index = self.history.index(f'@{event.x},{event.y}')
            for tag in self.history.tag_names(index):
                if tag.startswith('msg_'):
                    return next((message for message in self.messages if str(message.id) == tag[4:]), None)
        except tk.TclError:
            pass
        return None

    def context(self, event):
        message = self.message_at(event)
        if message is None:
            return
        # 1.5.1: through popup_menu, so Settings › Menus applies here too.
        entries = [(tr('Reply'), lambda: self.reply(message))]
        def copy():
            self.window.clipboard_clear()
            self.window.clipboard_append(message.raw_text if message.raw_text is not None else message.text)
        entries.append((tr('Copy text'), copy))
        from .advanced_features import feature_enabled
        if feature_enabled(self.app, 'chat_translation'):
            entries.append((tr('Translate chat'), self.translation_dialog))
            if (message.raw_text if message.raw_text is not None else message.text).strip():
                entries.append((tr('Translation'), lambda: self.message_actions(message)))
        if message.media:
            entries.append((tr('Guardar archivo como...'), lambda: self.save_media(message)))
        if not self.app.demo:
            entries.append((tr('Reactions'), lambda: self.react(message)))
        from .app_dialogs import popup_menu
        self.context_menu = popup_menu(self.window, entries, event=event)
        return 'break'

    def double_click(self, event):
        message = self.message_at(event)
        if message is not None:
            if message.media:
                self.save_media(message)
            else:
                self.reply(message)
            return 'break'

    def react(self, message):
        self.send_reaction(message, self.app.preferences.values['quick_reaction'])

    def save_media(self, message):
        if not self.valid() or self.app.demo:
            return
        from .desktop_media_lifetime import export_blocked
        if export_blocked(message,self,self.peer):
            self.status.set(tr('Protected content'));return
        from .app_dialogs import filedialog
        name = message.filename.replace('\\', '/').split('/')[-1] or 'attachment'
        target = filedialog.asksaveasfilename(parent=self.window, initialfile=name)
        if target:
            self.call(self.backend.download_media(message.media, Path(target)),
                      lambda _: self.status.set(tr('Archivo guardado.')), timeout=None)

    def close(self, destroy=True, discard_draft=False):
        if self.closed:
            return
        if self.thread:
            if not hasattr(self.app, '_suppressed_thread_peers'):
                self.app._suppressed_thread_peers = set()
            self.app._suppressed_thread_peers.add(self.peer)
        publish = not self.thread_id and not self.topic_id and not discard_draft and not self.app.demo and self.valid() and self.composer_focused()
        if not discard_draft:
            try:
                self.persist_draft(capture_only=True)
            except (OSError, ValueError, tk.TclError) as error:
                if destroy:
                    self.app.show_error(error)
                    return
        self.closed = True
        self.job.cancel()
        self.draft_job.cancel()
        for future in tuple(self.pending):
            future.cancel()
        self.pending.clear()
        # Final autosave belongs to the app worker rather than a disappearing
        # widget. All callbacks below use only the thread-safe draft store.
        record = self.draft_store.get(self.draft_account, self.peer) if self.draft_store else None
        if not discard_draft and self.draft_store is not None and not getattr(self.app, 'closing', False):
            backend, store, account, peer = self.backend, self.draft_store, self.draft_account, self.peer
            async def save_last():
                from .drafts import draft_content
                await asyncio.to_thread(store.flush)
                if publish and record and record.get('pending'):
                    await backend.save_draft(peer, record['text'], record['formats'], record['custom'], record['reply'])
                    with store._lock:
                        current = store.get(account, peer)
                        if current and draft_content(current) == draft_content(record):
                            store.put(account, peer, current, pending=False)
                    await asyncio.to_thread(store.flush)
            self.app.worker.submit(save_last(), lambda _: None, self.app.show_error)
        self.photos = []
        if self in getattr(self.app, '_chat_windows', ()):
            self.app._chat_windows.remove(self)
        try:
            if hasattr(self, 'bubble_view') and hasattr(self.bubble_view, 'destroy'):
                self.bubble_view.destroy()
            clear_text_actions(self.history)
            if destroy:
                self.window.destroy()
        except tk.TclError:
            pass


class WindowWorker:
    """Submit on the app's one loop, but retire callbacks with their view."""
    def __init__(self, app, owner):
        self.app, self.owner = app, owner
        self.loop, self.events = owner.loop, owner.events
        self._stopping = False
        self.pending = set()
        self._pending_lock = threading.Lock()

    def submit(self, coroutine, success, failure):
        if self._stopping or self.app.closed:
            from concurrent.futures import Future
            coroutine.close()
            result = Future()
            result.cancel()
            return result
        generation = getattr(self.app, '_view_generation', 0)
        def deliver(callback, value):
            if not self.app.closed and not self._stopping and generation == getattr(self.app, '_view_generation', 0):
                callback(value)
            elif hasattr(value, 'close'):
                # PIL images can arrive after their view is closed.
                value.close()
        future = self.owner.submit(coroutine, lambda value: deliver(success, value),
                                   lambda error: deliver(failure, error))
        with self._pending_lock:
            self.pending.add(future)
        def release(result):
            with self._pending_lock:
                self.pending.discard(result)
        future.add_done_callback(release)
        return future

    def stop(self):
        self._stopping = True
        self.cancel_pending()

    def cancel_pending(self):
        with self._pending_lock:
            pending = tuple(self.pending)
            self.pending.clear()
        for future in pending:
            future.cancel()


def open_linked_app_window(app,initial_chat=None):
    from .accounts import AccountsView
    from .desktop import Desktop
    from .interface_layout import caption
    owner = getattr(app, '_linked_owner', None) or app
    if owner.closed or owner.closing or getattr(app, 'stage', None) != 'ready':
        raise ValueError(tr('Inicia sesion de nuevo'))
    if not hasattr(owner, '_app_windows'):
        owner._app_windows = []
    occupied = {view.window_slot for view in owner._app_windows if not view.closed}
    slot = 1
    while f'window-{slot}' in occupied:
        slot += 1
    root = tk.Toplevel(owner.root)
    try:
        view = Desktop(root, demo=owner.demo,
                       service=AccountsView(owner.service, app.ui_account, pinned=initial_chat is not None),
                       linked_owner=owner, window_slot=f'window-{slot}', chat_target=initial_chat)
        owner._app_windows.append(view)
        owner.update_window_titles()
        return view
    except BaseException:
        root.destroy()
        raise


def cancel_view_timers(root):
    """Retire only Tcl callbacks owned by a disappearing linked subtree."""
    commands = {}
    def collect(widget):
        commands.update({name: widget for name in (getattr(widget, '_tclCommands', ()) or ())})
        for child in widget.winfo_children():
            collect(child)
    try:
        collect(root)
        for ident in root.tk.splitlist(root.tk.call('after', 'info')):
            script = root.tk.call('after', 'info', ident)[0]
            owner = commands.get(str(script).split(' ', 1)[0])
            if owner is not None:
                # Tk tracks registered commands on the registering widget.
                # Cancel through that owner so destroy cannot delete it twice.
                owner.after_cancel(ident)
    except tk.TclError:
        pass


def navigate_from_chat_window(app, *, chat=None, peer=None, message=None):
    """Cross-chat links navigate in the owner; the source window stays pinned."""
    owner = app._linked_owner
    account = app._pinned_account
    if app.closed or app.closing or owner.closed or owner.closing or account not in owner.service.entries:
        return
    from .app_lock import show_locked
    if show_locked(owner):
        return
    owner.root.deiconify()
    owner.root.lift()
    if owner.busy:
        return
    def opened(_=None):
        if (owner.closed or owner.closing or account != owner.ui_account
                or account not in owner.service.entries or show_locked(owner)):
            return
        if chat is not None:
            owner.open_resolved(chat)
        elif message is not None:
            owner.jump_message(message, peer)
    if owner.ui_account == account:
        opened()
    else:
        owner.switch_account(account)
        # Account selection is async; only this navigation waits on that one
        # operation, and it is invalidated by a later user selection.
        expected_generation = getattr(owner, '_view_generation', 0)
        def selected():
            if (owner.closed or owner.closing or app.closed or app.closing
                    or account not in owner.service.entries
                    or expected_generation != getattr(owner, '_view_generation', 0)):
                return
            if owner.busy:
                owner.root.after(50, selected)
            else:
                opened()
        owner.root.after_idle(selected)


def sync_window_accounts(owner):
    """Reflect login/logout without selecting another window's current chat."""
    if owner.closed or owner.closing:
        return
    owner.update_account_picker()
    for view in tuple(getattr(owner, '_app_windows', ())):
        if view.closed or view.closing:
            continue
        for account in tuple(view.draft_manager.store.records):
            if account not in owner.service.entries and not account.startswith('linked:'):
                view.draft_manager.store.remove_account(account)
        for account in tuple(view.account_states):
            if account not in owner.service.entries:
                view.account_states.pop(account, None)
        view.update_account_picker()
        for chat in tuple(getattr(view, '_chat_windows', ())):
            if chat.account not in owner.service.entries:
                chat.close(discard_draft=True)
        if view.ui_account not in owner.service.entries:
            if getattr(view, '_chat_only', False):
                # Never change a conversation window's account after logout.
                # Clear the composer before close() snapshots it to avoid
                # resurrecting a draft that the logout just removed.
                view._parent_close = True
                view.active, view.messages, view.chats, view.drafts = None, [], [], {}
                view.attachment = None
                view.close()
                continue
            view._view_generation = getattr(view, '_view_generation', 0) + 1
            view.worker.cancel_pending()
            view.busy = False
            for popup in tuple(view.popups):
                if popup.winfo_exists():
                    popup.destroy()
            view.popups.clear()
            view.active, view.messages, view.chats, view.drafts = None, [], [], {}
            if hasattr(view, 'editor') and view.editor.winfo_exists():
                view.editor.delete('1.0', 'end')
            if not owner.service.entries:
                view.close()
            elif not view.busy:
                key = owner.service.current
                if key not in owner.service.entries:
                    key = next(iter(owner.service.entries))
                view.active, view.messages, view.chats, view.drafts = None, [], [], {}
                view.switch_account(key)
        # Persist removal in the per-window copy as well as the main store.
        async def flush(store=view.draft_manager.store):
            await asyncio.to_thread(store.flush)
        view.worker.submit(flush(), lambda _: None, view.show_error)


def watch_shared_design(owner):
    """One event-driven observer; no timer per view and no polling of files."""
    pending = set()
    def changed():
        if owner.closed or owner.closing or not getattr(owner, '_app_windows', ()):
            return
        pending.update((owner, *tuple(getattr(owner, '_app_windows', ()))))
        if getattr(owner, '_shared_design_after', None):
            return
        def apply():
            owner._shared_design_after = None
            if owner.closed or owner.closing:
                pending.clear()
                return
            for view in tuple(pending):
                if view.closed or view.closing:
                    pending.discard(view)
                    continue
                if view.busy:
                    continue
                # Snapshot each independent composer and selection once.
                pending.discard(view)
                view.rebuild_screen()
            if pending:
                owner._shared_design_after = owner.root.after(200, apply)
        owner._shared_design_after = owner.root.after_idle(apply)
    owner.preferences.listeners.append(changed)
    owner.interface_store.listeners.append(changed)


def purge_window_drafts(owner, account):
    """Purge only the logged-out account, including closed window slots."""
    from .drafts import DraftStore
    import re
    active = {view.draft_manager.store.path: view.draft_manager.store
              for view in getattr(owner, '_app_windows', ()) if not view.closed}
    directory = Path(getattr(owner.service, 'root', owner.preferences.path.parent)) / 'window-drafts'
    if directory.is_dir() and not directory.is_symlink():
        for folder in directory.iterdir():
            if folder.is_dir() and not folder.is_symlink() and re.fullmatch(r'window-[1-9][0-9]*', folder.name):
                path = folder / 'drafts.json'
                if path.is_file() and not path.is_symlink() and path not in active:
                    active[path] = DraftStore(folder, demo=owner.demo)
    for store in active.values():
        store.remove_account(account)
        store.flush()


def share_view_value(app, name, value):
    """Publish saved per-chat options without sharing selection/composer state."""
    owner = getattr(app, '_linked_owner', None) or app
    for view in (owner, *tuple(getattr(owner, '_app_windows', ())), *tuple(getattr(owner, '_chat_windows', ()))):
        setattr(view, name, value)
        if view is app or getattr(view, 'closed', False):
            continue
        if getattr(view, 'stage', None) not in ('ready', None):
            continue
        if name == 'wallpapers' and hasattr(view, 'refresh_wallpaper'):
            view.refresh_wallpaper()
        elif name == 'chat_translations':
            view._translation_scope = None
            if hasattr(view, 'render_messages'):
                view.render_messages(False)
            elif hasattr(view, 'request_render'):
                view.request_render()


def publish_local_message(app, account, peer, message):
    """Successful sends share the same routing as Telegram push updates."""
    owner = getattr(app, '_linked_owner', None) or app
    owner.account_event((account, peer, message))
