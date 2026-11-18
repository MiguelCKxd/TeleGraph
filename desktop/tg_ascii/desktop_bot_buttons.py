"""Inline rows in both renderers, plus a bounded, scrollable reply keyboard."""
from . import APP_NAME
from .appearance import app_palette
import tkinter as tk
from tkinter import ttk, font
from telethon import types
from .bot_buttons import button_available, keyboard_message, button_action
from .i18n import tr
from .app_dialogs import messagebox
from .ui_work import FrameJob, bind_text_action, clear_text_actions


def visible_button_rows(app, message, capabilities=None):
    from .chat_capabilities import chat_capabilities
    capabilities = capabilities or chat_capabilities(app)
    profile = getattr(getattr(getattr(app, 'service', None), 'backend', None), 'account_profile', None)
    phone_available = bool(getattr(getattr(profile, 'user', None), 'phone', None))
    for row_index, row in enumerate(getattr(getattr(message, 'reply_markup', None), 'rows', ())):
        buttons = [(column, button) for column, button in enumerate(row.buttons)
                   if button_available(button, capabilities, phone_available=phone_available)]
        if buttons:
            yield row_index, buttons


def paint_buttons(canvas, app, message, x, y, width, tag='', interactive=None, scope=None, capabilities=None):
    colors = app_palette(app.preferences.values)
    face = getattr(canvas, 'bot_font', None)
    if face is None: face = font.Font(root=canvas, family=app.font_family, size=app.preferences.values['font_size'])
    else: face.configure(family=app.font_family, size=app.preferences.values['font_size'])
    canvas.bot_font = face
    scope = scope or (app.ui_account, app.active)
    from .advanced_features import feature_enabled
    for row_index, buttons in visible_button_rows(app, message, capabilities):
        cell = (width - 4 * (len(buttons) - 1)) / len(buttons)
        labels = []
        height = 32
        for visible_column, (column, button) in enumerate(buttons):
            left = x + visible_column * (cell + 4)
            kind, _ = button_action(button)
            feature = {'phone': 'contacts', 'locations': 'locations', 'polls': 'polls'}.get(kind)
            disabled = feature is not None and not feature_enabled(app, feature)
            label = button.text + (' · ' + tr('Disabled') if disabled else '')
            item = canvas.create_text(left + cell / 2, y + 8, text=label,
                anchor='n', width=max(10, cell - 12), justify='center', font=face,
                fill=colors['muted'] if disabled else colors['text'], tags=tag)
            bounds = canvas.bbox(item)
            height = max(height, (bounds[3] - y + 8) if bounds else 32)
            labels.append((left, item, button, column))
        for left, item, button, column in labels:
            box = canvas.create_rectangle(left, y, left + cell, y + height,
                fill=colors['panel'], outline=colors['muted'], tags=tag)
            canvas.tag_lower(box, item)
            callback = lambda r=row_index, c=column, b=button: app.press_bot_button(message, r, c, b, scope)
            for target in (box, item):
                if interactive: interactive(target, callback)
                else: bind_text_action(canvas,target, '<Button-1>', lambda e, cb=callback: cb())
        y += height + 4
    return y


class KeyboardCanvas(tk.Canvas):
    def __init__(self, parent, app, message, bounded=False):
        colors = app_palette(app.preferences.values)
        super().__init__(parent, height=36, highlightthickness=0, bg=colors['bg'])
        self.app, self.message, self.bounded = app, message, bounded
        self.scope = (app.ui_account, app.active)
        self.render_job=FrameJob(self,self.render)
        self.bind('<Configure>', self.render_job.request)
        self.bind('<Destroy>',lambda event:self.render_job.cancel() if event.widget is self else None,add='+')

    def render(self, event=None):
        width=self.winfo_width()
        from .chat_capabilities import chat_capabilities
        capabilities = chat_capabilities(self.app)
        context = (width, capabilities.actions, tuple(sorted(self.app.preferences.values.get('advanced_features', {}).items())))
        if context==getattr(self,'_render_context',None):return
        self._render_context=context
        position = self.yview()[0]
        clear_text_actions(self)
        self.delete('all')
        height = paint_buttons(self, self.app, self.message, 2, 2, max(100, width - 4), scope=self.scope, capabilities=capabilities)
        desired = min(140, height) if self.bounded else height
        if int(float(self.cget('height'))) != int(desired): self.configure(height=int(desired))
        self.configure(scrollregion=(0, 0, width, height))
        self.yview_moveto(position)


class DesktopBotButtons:
    def setup_bot_keyboard(self, conversation):
        self.bot_keyboard_cache = {}; self.bot_keyboard_hidden = set(); self.bot_inline_widgets = []
        self.bot_keyboard_panel = ttk.Frame(conversation)
        self.bot_keyboard_toggle = ttk.Button(conversation, text=tr('Bot keyboard'), command=self.toggle_bot_keyboard)
        self.bot_keyboard_key = None

    def toggle_bot_keyboard(self):
        key = self.bot_keyboard_key
        message = self.bot_keyboard_cache.get((self.ui_account, self.active))
        if isinstance(getattr(message, 'reply_markup', None), types.ReplyKeyboardForceReply):
            from .chat_capabilities import chat_capabilities
            if not chat_capabilities(self).allows('send'):return
            self.reply_message(message)
            return
        if key in self.bot_keyboard_hidden: self.bot_keyboard_hidden.remove(key)
        else: self.bot_keyboard_hidden.add(key)
        self.refresh_bot_keyboard(force=True)

    def refresh_bot_keyboard(self, force=False):
        from .chat_capabilities import chat_capabilities
        capabilities = chat_capabilities(self)
        scope = (self.ui_account, self.active)
        previous = self.bot_keyboard_cache.get(scope)
        message = keyboard_message(self.messages, previous)
        if message:
            self.bot_keyboard_cache[scope] = message
            while len(self.bot_keyboard_cache) > 512:
                self.bot_keyboard_cache.pop(next(iter(self.bot_keyboard_cache)))
        markup = getattr(message, 'reply_markup', None)
        key = (*scope, message.id, bytes(markup)) if message else (*scope, None)
        context = (capabilities.actions, tuple(sorted(self.preferences.values.get('advanced_features', {}).items())))
        if key == self.bot_keyboard_key and context == getattr(self, '_bot_capabilities_key', None) and not force: return
        self._bot_capabilities_key = context
        self.bot_keyboard_key = key
        self.bot_keyboard_panel.pack_forget(); self.bot_keyboard_toggle.pack_forget()
        for widget in self.bot_keyboard_panel.winfo_children(): widget.destroy()
        self.bot_keyboard_toggle.configure(text=tr('Bot keyboard'))
        if self.active is None: return
        if isinstance(markup, types.ReplyKeyboardForceReply):
            if capabilities.allows('send') and not any(item.outgoing and item.id > message.id for item in self.messages):
                self.bot_keyboard_toggle.configure(text=tr('Reply') + ' · ' + message.sender)
                self.bot_keyboard_toggle.pack(fill='x', before=self.editor)
            return
        if not isinstance(markup, types.ReplyKeyboardMarkup) or not any(visible_button_rows(self, message, capabilities)): return
        self.bot_keyboard_toggle.pack(fill='x', before=self.editor)
        if key in self.bot_keyboard_hidden: return
        self.bot_keyboard_panel.pack(fill='x', before=self.editor)
        canvas = KeyboardCanvas(self.bot_keyboard_panel, self, message, bounded=True)
        self.bot_keyboard_panel._scroll_target = canvas
        bar = ttk.Scrollbar(self.bot_keyboard_panel, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side='right', fill='y'); canvas.pack(side='left', fill='x', expand=True)

    def clear_inline_buttons(self):
        for widget in getattr(self, 'bot_inline_widgets', []): widget.destroy()
        self.bot_inline_widgets = []

    def insert_bot_buttons(self, message):
        if not isinstance(getattr(message, 'reply_markup', None), types.ReplyInlineMarkup): return
        if not any(visible_button_rows(self, message)): return
        canvas = KeyboardCanvas(self.history, self, message)
        canvas.configure(width=max(160, self.history.winfo_width() - 28))
        self.bot_inline_widgets.append(canvas)
        self.history.window_create('end', window=canvas)
        self.history.insert('end', '\n')
        # A text-window does not expand automatically when the main window resizes.
        def resized(event):
            for widget in self.bot_inline_widgets:
                widget.configure(width=max(160, event.width - 28))
        if not getattr(self, '_bot_resize_bound', False):
            self.history.bind('<Configure>', resized, add='+'); self._bot_resize_bound = True

    def press_bot_button(self, message, row, column, button, scope):
        if self.busy or self.demo or scope != (self.ui_account, self.active) or getattr(self, 'selection_kind', None) or getattr(self, '_preview_only', False): return
        if not any(r == row and any(c == column and bytes(b) == bytes(button) for c, b in buttons)
                   for r, buttons in visible_button_rows(self, message)):
            return
        kind, action = button_action(button)
        if kind in ('phone', 'locations', 'polls'):
            from .advanced_features import feature_enabled
            feature = 'contacts' if kind == 'phone' else kind
            if not feature_enabled(self, feature):
                return self.complex_settings()
        if kind in ('webview', 'simplewebview'):
            if not messagebox.askyesno(tr('Open Mini App'), tr('Open this bot’s Mini App in your browser using your Telegram account? Some native Telegram features may be unavailable.'), parent=self.root): return
            if scope != (self.ui_account, self.active) or self.busy: return
        account, peer = scope
        backend = self.service.backend
        key = (*scope, message.id, bytes(message.reply_markup))
        def current():
            return scope == (self.ui_account, self.active) and backend is self.service.backend and not getattr(self, 'closed', False) and not getattr(self, 'closing', False)
        def done(result):
            if not current(): return
            if result.get('compose'):
                self.compose_bot_request(result['compose'], result['reply_to'], quiz=result.get('quiz'))
                return
            if result.get('request_phone'):
                card = result['request_phone']
                detail = tr('¿Compartir tu número de teléfono con este bot?') + '\n\n' + card['recipient'] + '\n+' + card['phone'].lstrip('+')
                if messagebox.askyesno(tr('Compartir contacto'), detail, parent=self.root) and current() and not self.busy:
                    from .advanced_features import feature_enabled
                    if feature_enabled(self, 'contacts'):
                        self.call(backend.activate_bot_button(peer, message.id, row, column, bytes(button), phone_consent=card['phone']), done, tr('Enviando...'))
                return
            if result.get('profile'):
                self.show_contact_profile(result['profile'])
            if result.get('message') and getattr(message.reply_markup, 'single_use', False): self.bot_keyboard_hidden.add(key)
            if scope != (self.ui_account, self.active): return
            if result.get('message'):
                from .interface_windows import publish_local_message
                publish_local_message(self, account, peer, result['message'])
                self.refresh_bot_keyboard(force=True)
            if result.get('notice'):
                if result.get('alert'): messagebox.showinfo(APP_NAME, result['notice'], parent=self.root)
                else: self.status.set(result['notice'])
            if 'copy' in result:
                self.root.clipboard_clear(); self.root.clipboard_append(result['copy'])
            if result.get('url'):
                # Callback URLs are supplied only after the request; show their destination first.
                if kind in ('webview', 'simplewebview') or messagebox.askyesno(APP_NAME, tr('Open link?')+'\n'+result['url'], parent=self.root):
                    if current() and not self.busy:
                        self.open_link(result['url'])
        self.call(backend.activate_bot_button(peer, message.id, row, column, bytes(button)), done, tr('Loading...'))
