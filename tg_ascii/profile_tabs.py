"""Profile data fetched only when its tab is selected; no polling or bulk artwork."""
import tkinter as tk
from tkinter import ttk
from telethon import types, utils
from .i18n import tr
from .app_dialogs import messagebox
from .advanced_features import profile_feature_enabled


class ProfileTabPane:
    def __init__(self, view, kind):
        self.view, self.app, self.kind = view, view.app, kind
        self.rows, self.cursor, self.more, self.loaded = [], '' if kind == 'gifts' else 0, True, False
        parent = view.pages[kind]
        content=ttk.Frame(parent);content.pack(fill='both',expand=True)
        self.listing = tk.Listbox(content, exportselection=False)
        self.listing.pack(side='left', fill='both', expand=True)
        scrollbar=ttk.Scrollbar(content,command=self.listing.yview);scrollbar.pack(side='right',fill='y')
        self.listing.configure(yscrollcommand=scrollbar.set)
        self.listing.bind('<Double-Button-1>', lambda _: self.open())
        self.listing.bind('<Return>', lambda _: self.open())
        self.status = ttk.Label(parent); self.status.pack(fill='x')
        buttons = ttk.Frame(parent); buttons.pack(fill='x', pady=8)
        ttk.Button(buttons, text=tr('Open'), command=self.open).pack(side='left')
        self.more_button=ttk.Button(buttons, text=tr('More'), command=lambda: self.fetch(True));self.more_button.pack(side='left')
        ttk.Button(buttons, text=tr('Actualizar'), command=self.fetch).pack(side='left')
        if view.profile.get('is_self') and kind in ('posts', 'profile_music'):
            ttk.Button(buttons, text=tr('Quitar del perfil'), command=self.remove).pack(side='right')
        if view.profile.get('is_self') and kind == 'posts':
            ttk.Button(buttons, text=tr('Publish story'), command=self.app.new_story).pack(side='right')

    def fetch(self, more=False):
        view = self.view
        if not view.valid() or not profile_feature_enabled(self.app,self.kind) or self.app.demo or more and not self.more:
            return
        key = 'profile-tab:' + self.kind
        if key in view.requests.jobs:
            return
        self.status.configure(text=tr('Cargando...'))
        self.more_button.configure(state='disabled')
        cursor = self.cursor if more else ('' if self.kind == 'gifts' else 0)
        async def request():
            if self.kind == 'posts': return await view.backend.profile_posts(view.peer, cursor)
            if self.kind == 'profile_music': return await view.backend.profile_music(view.peer, cursor)
            if self.kind == 'similar':
                return {'items': await view.backend.similar_channels(view.peer), 'next': 0, 'more': False}
            result = await view.backend.profile_gifts(view.peer, cursor, include_hidden=bool(view.profile.get('is_self')))
            next_offset = getattr(result, 'next_offset', '') or ''
            return {'items': result.gifts, 'next': next_offset, 'more': bool(next_offset) and next_offset != cursor}
        def loaded(result):
            if not view.valid() or not profile_feature_enabled(self.app,self.kind):return
            if not more:
                self.rows.clear(); self.listing.delete(0, 'end')
            def identity(item):
                if self.kind=='gifts':return (getattr(item,'saved_id',None),getattr(item,'msg_id',None),getattr(item,'date',None),item.gift.id)
                return item.id
            seen={identity(item) for item in self.rows}
            for item in result['items']:
                ident=identity(item)
                if ident not in seen:self.rows.append(item);seen.add(ident)
            self.cursor, self.more, self.loaded = result['next'], result['more'] and result['next']!=cursor, True
            self.more_button.configure(state='normal' if self.more else 'disabled')
            self.listing.delete(0, 'end')
            for item in self.rows:
                if self.kind == 'posts':
                    date = getattr(item, 'date', None)
                    label = (date.astimezone().strftime('%d/%m/%Y') + ' · ' if date else '') + (getattr(item, 'caption', '') or tr('Historia'))
                elif self.kind == 'similar': label = item.name
                elif self.kind == 'profile_music':
                    audio = next((a for a in item.attributes if isinstance(a, types.DocumentAttributeAudio)), None)
                    label = ' · '.join(v for v in (getattr(audio, 'performer', None), getattr(audio, 'title', None)) if v) or tr('Audio')
                else:
                    gift = item.gift
                    label = getattr(gift, 'title', None) or tr('Regalo') + ' #' + str(gift.id)
                    if getattr(gift, 'num', None): label += ' #' + str(gift.num)
                    if getattr(item, 'unsaved', False): label += ' · ' + tr('Oculto')
                self.listing.insert('end', self.app.text_display(label, True))
            self.status.configure(text=str(len(self.rows)) if self.rows else tr('No results.'))
        def failed(error):
            self.status.configure(text=str(error));self.more_button.configure(state='normal' if self.more else 'disabled')
        view.requests.submit(key, request(), loaded, failed)

    def selected(self):
        selection = self.listing.curselection()
        return self.rows[selection[0]] if selection and self.view.valid() and profile_feature_enabled(self.app,self.kind) else None

    def open(self):
        item = self.selected()
        if item is None or self.app.busy:
            return
        view = self.view
        if self.kind == 'similar':
            view.requests.submit('open-similar', view.backend.resolve_chat(item.id),
                                 lambda chat: self.app.open_resolved(chat) if not self.app.busy else None, self.app.show_error)
        elif self.kind == 'gifts':
            self.app.open_saved_gift(item, view.peer, own=bool(view.profile.get('is_self')))
        elif self.kind == 'profile_music':
            filename=next((a.file_name for a in item.attributes if isinstance(a,types.DocumentAttributeFilename)),None)
            self.app.media_dialog(item, filename or 'profile-music'+(utils.get_extension(item) or '.audio'), 'audio', '')
        else:
            media = getattr(item, 'media', None)
            if media is None:
                self.status.configure(text=tr('Esta publicación ya no está disponible.')); return
            from .telegram_features import Story
            story = Story(utils.get_peer(view.peer), item.id, view.profile['name'], getattr(item, 'caption', '') or '', media)
            kind = 'image' if isinstance(media, types.MessageMediaPhoto) else 'video'
            self.app.media_dialog(media, tr('Historia'), kind, story.caption,
                                  getattr(getattr(media, 'document', None), 'size', 0) or 0, story=story)

    def remove(self):
        item = self.selected()
        view = self.view
        if item is None or self.app.busy or not view.profile.get('is_self'):
            return
        if not messagebox.askyesno(tr('Quitar del perfil'), tr('¿Quitar este elemento del perfil?'), parent=view.window):
            return
        if not view.valid() or not profile_feature_enabled(self.app,self.kind) or self.app.busy:
            return
        async def operation():
            if self.kind == 'profile_music': return await view.backend.save_profile_music(item, remove=True)
            from telethon import functions
            return await view.backend.client(functions.stories.TogglePinnedRequest(
                await view.backend.client.get_input_entity(view.peer), [item.id], False))
        view.requests.submit('profile-remove:' + self.kind, operation(), lambda _: self.fetch(), self.app.show_error)
