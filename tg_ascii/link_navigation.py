"""Explicit, account-scoped navigation for supported Telegram deep links."""
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace

from telethon import functions as f
from telethon import types as t
from telethon import utils

from .advanced_features import feature_enabled
from .app_dialogs import messagebox
from .contact_profile import ProfileRequests
from .i18n import tr


def open_target(app, target):
    if not feature_enabled(app, 'links') or app.demo or app.busy: return False
    backend, account, origin = app.service.backend, app.ui_account, app.active
    def valid():
        return (account == app.ui_account and backend is app.service.backend
                and origin == app.active and feature_enabled(app, 'links')
                and not getattr(app, 'closing', False) and not getattr(app, 'closed', False))
    if target.kind == 'browser': return False
    if target.kind == 'invite': app.invite_dialog(target.value); return True
    if target.kind == 'folder': app.join_folder_dialog(target.url); return True
    if target.kind == 'pack':
        document = SimpleNamespace(attributes=[t.DocumentAttributeSticker('', t.InputStickerSetShortName(target.value))])
        app.show_document_pack(document)
        return True
    if target.kind == 'hashtag':
        if app.active is None: return True
        window, frame = app.dialog('Search messages', '620x580')
        ttk.Label(frame, text=target.value, style='Title.TLabel').pack(fill='x')
        listing = tk.Listbox(frame, exportselection=False, height=16); listing.pack(fill='both', expand=True, pady=6)
        status = ttk.Label(frame, wraplength=550)
        status.pack(fill='x')
        requests = ProfileRequests(app, window, account, backend)
        original_valid = requests.valid
        requests.valid = lambda: original_valid() and valid()
        def close(event):
            if event.widget is window:
                requests.close()
                requests.valid = lambda: False
        window.bind('<Destroy>', close, add='+')
        records, offset, loading = [], [0], [False]
        def load():
            if loading[0] or not requests.valid(): return
            loading[0] = True; status.configure(text=tr('Loading...')); more.configure(state='disabled')
            def loaded(items):
                loading[0] = False; status.configure(text='')
                seen = {item.id for item in records}
                for item in items:
                    if item.id not in seen:
                        records.append(item); seen.add(item.id)
                        listing.insert('end', item.sender + ' · ' + item.text.replace('\n', ' ')[:220])
                next_offset = items[-1].id if items else offset[0]
                can_load = bool(items) and next_offset != offset[0]
                offset[0] = next_offset
                more.configure(state='normal' if can_load else 'disabled')
            def failed(error):
                loading[0] = False; status.configure(text=str(error)); more.configure(state='normal')
            requests.submit('search', backend.search_messages(origin, target.value, offset=offset[0]), loaded, failed)
        def jump(_=None):
            selected = listing.curselection()
            if requests.valid() and selected:
                ident = records[selected[0]].id
                window.destroy(); app.jump_message(ident, origin)
        listing.bind('<Double-Button-1>', jump); listing.bind('<Return>', jump)
        ttk.Button(frame, text=tr('Open message'), command=jump).pack(fill='x', pady=4)
        more = ttk.Button(frame, text=tr('Load more'), command=load); more.pack(fill='x', pady=4)
        load(); return True
    if target.kind == 'peer':
        async def resolve():
            chat = await backend.resolve_chat(target.peer)
            if target.comment_id is None: return chat, target.message_id, None
            if target.message_id is None: raise ValueError(tr('This discussion link has no channel post.'))
            result = await backend.client(f.messages.GetDiscussionMessageRequest(
                await backend.client.get_input_entity(chat.id), target.message_id))
            candidate = next((item for item in result.messages if utils.get_peer_id(item.peer_id) != chat.id), None)
            if candidate is None: raise ValueError(tr('This discussion is no longer available.'))
            discussion = await backend.resolve_chat(utils.get_peer_id(candidate.peer_id))
            return discussion, target.comment_id, None
        def loaded(data):
            if not valid(): return
            chat, ident, _ = data
            if ident is not None: app.jump_message(ident, chat.id)
            elif target.profile: app.show_contact_profile(chat.id)
            else: app.open_resolved(chat)
        app.call(resolve(), loaded, tr('Loading...'))
        return True
    messagebox.showinfo(tr('Telegram link'), tr('This link is not supported by the current app.'), parent=app.root)
    return True
