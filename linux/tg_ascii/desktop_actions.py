from .appearance import app_palette
"""Clickable logo gallery, contact photographs and peer-scoped chat actions."""
from pathlib import Path
import shutil
import tkinter as tk
from tkinter import ttk
from .scrolling import FlowFrame
from .app_dialogs import Choice, messagebox, filedialog
from .desktop_tools import DesktopTools
from .desktop_profile import DesktopProfile
from .i18n import tr
from .logos import LOGO_PALETTES, VARIANTS, brand_asset_path
from .ui_work import bind_text_action
from .desktop_advanced import DesktopAdvancedMixin


class DesktopActions(DesktopAdvancedMixin, DesktopProfile, DesktopTools):
    def update_chat_capabilities(self):
        """Hide impossible composer actions without touching drafts or layouts."""
        from .chat_capabilities import chat_capabilities
        from .advanced_features import feature_enabled
        caps = chat_capabilities(self)
        demo = bool(getattr(self, 'demo', False))
        media = any(caps.allows('send_' + kind) for kind in ('photos', 'videos', 'docs', 'audios','gifs'))
        optional = any(feature_enabled(self, feature) and caps.allows(action) for feature, action in (
            ('polls', 'poll'), ('checklists', 'checklist'), ('locations', 'location'),
            ('contacts', 'contact'), ('articles', 'article'), ('stars_gifts', 'gift')))
        flags = {'attach_button': media or demo, 'send_button': caps.writable or demo,
                 'advanced_button': optional, 'sticker_button': caps.allows('send_stickers') or demo,
                 'custom_emoji_button': caps.allows('send_text') or demo}
        from .desktop_calls import call_allowed
        flags.update(
            call_button=call_allowed(self),
            video_call_button=call_allowed(self, video=True),
            secret_chat_button=caps.kind == 'secret',
        )
        for name, visible in flags.items():
            widget = getattr(self, name, None)
            if widget is None or not widget.winfo_exists():
                continue
            if visible == getattr(widget, '_capability_visible', None):
                continue
            widget._capability_visible = visible
            widget.flow_hidden = not visible
            if visible:
                geometry = getattr(widget, '_capability_geometry', None)
                if geometry and not getattr(widget,'_layout_hidden',False):
                    manager, options = geometry
                    restore=getattr(widget,'_layout_geometry',{}).get(manager,getattr(widget,manager))
                    restore(**options)
            else:
                manager = widget.winfo_manager()
                if manager in ('pack','grid','place'):
                    widget._capability_geometry = (manager,getattr(widget,manager+'_info')())
                    getattr(widget,manager+'_forget')()
            arrange = getattr(widget.master, 'arrange', None)
            if arrange:
                arrange()

    def choose_wallpaper(self):
        if self.busy or self.demo or self.active is None: return
        from .chat_capabilities import chat_capabilities
        if not chat_capabilities(self).allows('wallpaper'): return
        backend,account,peer=self.service.backend,self.ui_account,self.active
        path=filedialog.askopenfilename(parent=self.root,title=tr('Chat background'),filetypes=[('Images','*.jpg *.jpeg *.png')])
        if not path: return
        def saved(_):
            if (account,peer)==(self.ui_account,self.active): self.refresh_wallpaper()
        self.call(backend.set_wallpaper(peer,path),saved,tr('Guardando...'),timeout=None)

    def refresh_wallpaper(self):
        if not hasattr(self,'history_canvas') or not self.history_canvas.winfo_exists(): return
        self.history_canvas.delete('wallpaper'); self.wallpaper_photo=None
        if self.demo or self.active is None: return
        backend,account,peer=self.service.backend,self.ui_account,self.active
        path=self.preview_dir/f'{account}-wallpaper-{peer}'
        def loaded(path):
            if path and (account,peer)==(self.ui_account,self.active) and self.history_canvas.winfo_exists():
                self.wallpaper_photo=self.load_photo(path,(1200,1200))
                if self.wallpaper_photo:
                    self.history_canvas.create_image(0,0,image=self.wallpaper_photo,anchor='nw',tags='wallpaper')
                    self.history_canvas.tag_lower('wallpaper')
        self.worker.submit(backend.wallpaper_image(peer,path),loaded,lambda _:None)

    def open_link(self, url, *, browser_only=False):
        from .links import browser_url, link_target
        from .advanced_features import feature_enabled
        import webbrowser
        try:
            target=link_target(url)
            if not browser_only and feature_enabled(self,'links') and target.kind!='browser':
                from .link_navigation import open_target
                if open_target(self,target):return
            # Explicit purchase/help/bot buttons still open HTTPS pages when
            # message-link interaction is disabled. Never hand tg:// to the OS.
            address=browser_url(target.url or url)
        except (ValueError,TypeError) as exc: self.show_error(exc); return
        if not messagebox.askyesno(tr('Open link'),address,parent=self.root):return
        if getattr(self,'closed',False) or getattr(self,'closing',False):return
        if not webbrowser.open(address,new=2):
            self.show_error(ValueError(tr('The default browser could not be opened.')))

    def insert_linked_text(self, text, outgoing=False):
        from .links import message_links
        from .advanced_features import feature_enabled
        if not feature_enabled(self,'links'):
            self.history.insert('end',text,'outgoing' if outgoing else '')
            return
        cursor=0
        for start,end,url in message_links(text):
            self.history.insert('end',text[cursor:start],'outgoing' if outgoing else '')
            self._link_counter=getattr(self,'_link_counter',0)+1
            tag=f'link_{self._link_counter}'
            self.history.tag_configure(tag,underline=True)
            bind_text_action(self.history,tag,'<Button-1>',lambda _,u=url:self.open_link(u))
            self.history.insert('end',text[start:end],tag); cursor=end
        self.history.insert('end',text[cursor:],'outgoing' if outgoing else '')

    def open_bot_app(self):
        if self.busy or self.demo or self.active is None: return
        backend,peer=self.service.backend,self.active
        if not messagebox.askyesno(tr('Open Mini App'),tr('Open this bot’s Mini App in your browser using your Telegram account? Some native Telegram features may be unavailable.'),parent=self.root): return
        self.call(backend.webapp(peer),self.open_link,tr('Cargando...'))

    def new_story(self):
        from .advanced_features import feature_enabled
        if not feature_enabled(self,'stories'):return self.complex_settings()
        if self.busy or self.demo: return
        backend=self.service.backend
        window,frame=self.dialog('Publish story','560x560')
        path=[None]; info=tk.StringVar()
        preview=ttk.Label(frame); preview.pack(pady=6)
        def choose():
            name=filedialog.askopenfilename(parent=window,title=tr('Choose a JPEG, PNG or MP4 file.'),filetypes=[('Photo / Video','*.jpg *.jpeg *.png *.mp4')])
            if name:
                path[0]=Path(name); info.set(path[0].name)
                preview.image=self.load_photo(path[0],(180,180)) if path[0].suffix.lower()!='.mp4' else None
                preview.configure(image=preview.image or '')
        ttk.Button(frame,text=tr('Elegir archivo'),command=choose).pack(fill='x')
        ttk.Label(frame,textvariable=info,wraplength=480).pack(pady=6)
        caption=self.field(frame,'Caption')
        audience=Choice(frame,values=[tr('Contacts only'),tr('Everyone'),tr('Close friends')]); audience.current(0); audience.pack(fill='x',pady=8)
        ttk.Label(frame,text=tr('Visible for 24 hours. Telegram applies your account’s posting limits.'),wraplength=480).pack(pady=8)
        def publish():
            if self.busy or not path[0]: return
            if not messagebox.askyesno(tr('Publish story'),tr('Publish {file} to {audience}?').format(file=path[0].name,audience=audience.get()),parent=window): return
            def done(_): window.destroy(); self.status.set(tr('Story published.')); self.load_stories()
            self.call(backend.publish_story(path[0],caption.get(),('contacts','everyone','close')[audience.current()]),done,tr('Enviando...'),timeout=None)
        ttk.Button(frame,text=tr('Publish story'),command=publish).pack(fill='x',pady=10)

    def toggle_compact_panel(self):
        self.compact_conversation = not getattr(self,'compact_conversation',False)
        self.adapt_chat_layout()

    def adapt_chat_layout(self, event=None):
        if getattr(self, '_chat_only', False):
            controls = sum(w.winfo_reqheight()+5 for w in self.chat_conversation.winfo_children()
                           if w is not self.history_canvas and w.winfo_manager() and not getattr(w, 'flow_hidden', False))
            minimum = (320, max(360, controls+160))
            if self.viewport.minimum != minimum:
                self.viewport.minimum = minimum
                self.viewport.fit_content()
            return
        if not hasattr(self,'chat_panes') or not self.chat_panes.winfo_exists(): return
        runtime = getattr(self, 'layout_runtime', None)
        if runtime is not None and runtime.native_layout_changed():
            self.compact_button.pack_forget()
            self.viewport.minimum = (440, 420)
            self.viewport.fit_content()
            return
        # Preserve some message height; the outer viewport is the fallback on very short windows.
        controls=sum(w.winfo_reqheight()+5 for w in self.chat_conversation.winfo_children() if w is not self.history_canvas and w.winfo_manager() and not getattr(w,'flow_hidden',False))
        floor=max(420,controls+180+getattr(self,'account_bar',self.chat_page).winfo_reqheight()+50)
        if self.viewport.minimum[1]!=floor:
            self.viewport.minimum=(440,floor);self.viewport.fit_content()
            if hasattr(self,'fit_initial_window'):self.root.after_idle(self.fit_initial_window)
        from .pane_memory import hidden_pane
        # 1.5.2: a pane dragged away works like a narrow window (one pane + button).
        compact=self.chat_page.winfo_width()<760 or hidden_pane(self) is not None
        if compact: self.compact_button.pack(before=self.chat_panes,anchor='w',pady=2)
        else: self.compact_button.pack_forget()
        from .rtl_ui import pane_order
        desired=[self.chat_conversation if self.compact_conversation else self.chat_sidebar] if compact else pane_order(self.chat_sidebar,self.chat_conversation)
        current=list(map(str,self.chat_panes.panes()))
        if current==list(map(str,desired)): return
        for pane in current: self.chat_panes.forget(pane)
        for pane in desired: self.chat_panes.add(pane,weight=3 if pane==self.chat_conversation else 1)
        from .pane_memory import restore
        self.root.after_idle(lambda: restore(self, self.chat_panes) if self.chat_panes.winfo_exists() else None)

    def qr_login(self):
        if self.busy or self.demo: return
        try: import qrcode
        except ImportError:
            self.show_error(ValueError(tr('QR support is missing from this build.'))); return
        self.cancel_qr()
        window, frame=self.dialog('Log in with QR', '500x560')
        ttk.Label(frame,text=tr('Telegram on your phone: Settings → Devices → Link Desktop Device.'),wraplength=440).pack(pady=12)
        label=ttk.Label(frame); label.pack(pady=12)
        account=self.ui_account
        def show(url):
            if not window.winfo_exists() or account!=self.ui_account: return
            # Generate locally: never send login tokens to an image or web service.
            from PIL import ImageTk
            qr=qrcode.QRCode(box_size=6,border=4); qr.add_data(url); qr.make(fit=True)
            picture=qr.make_image(fill_color='black',back_color='white').convert('RGB')
            label.image=ImageTk.PhotoImage(picture,master=window); label.configure(image=label.image)
        def publish(url): self.worker.events.put((show,url))
        def finished(stage):
            self.qr_future=None
            if window.winfo_exists(): window.destroy()
            if account==self.ui_account: self.login_stage(stage)
        def failed(exc):
            self.qr_future=None
            if window.winfo_exists(): window.destroy()
            self.show_error(exc)
        self.qr_future=self.worker.submit(self.service.login_qr(publish),finished,failed)
        def cancel(): self.cancel_qr(); window.destroy()
        window.protocol('WM_DELETE_WINDOW',cancel)
        window.bind('<Destroy>',lambda event:self.cancel_qr() if event.widget==window else None)
        ttk.Button(frame,text=tr('Cancel'),command=cancel).pack(pady=10)

    def cancel_qr(self):
        future=getattr(self,'qr_future',None)
        if future: future.cancel(); self.qr_future=None

    def insert_message_content(self, message):
        from .bubbles import rich_runs
        from .advanced_features import feature_enabled
        from .expandable_text import presentation, toggle, control_label
        message,quote_controls=presentation(self,message)
        start = self.history.index('end-1c')
        raw=message.raw_text if message.raw_text is not None else message.text
        prefix=message.text[:-len(raw)] if raw and message.text.endswith(raw) else message.text if not raw else ''
        if prefix:self.history.insert('end',self.text_display(prefix))
        for index, (text,url,segment) in enumerate(rich_runs(message,feature_enabled(self,'links'))):
            if segment is None:
                tag='outgoing' if message.outgoing else ''
                if url:
                    self._link_counter=getattr(self,'_link_counter',0)+1;tag=f'link_{self._link_counter}'
                    self.history.tag_configure(tag,underline=True)
                    bind_text_action(self.history,tag,'<Button-1>',lambda _,u=url:self.open_link(u))
                self.history.insert('end',self.text_display(text),tag)
            else:
                mark = f'preview_custom_{message.id}_{index}'
                self.history.mark_set(mark,'end-1c'); self.history.mark_gravity(mark,'left')
                self.history.insert('end','◇')
                tag=f'emoji_pack_{message.id}_{index}'
                self.history.tag_add(tag,mark,mark+' +1 chars')
                bind_text_action(self.history,tag,'<Button-1>',lambda e,doc=segment:self.show_document_pack(doc))
                self.emoji_at(segment,mark,self.preview_generation)
        self.history.insert('end','\n')
        for offset,expanded in quote_controls:
            tag=f'quote_toggle_{message.id}_{offset}'
            self.history.tag_configure(tag,underline=True)
            bind_text_action(self.history,tag,'<Button-1>',lambda _,ident=message.id,value=offset,scope=(self.ui_account,self.active):toggle(self,ident,value,scope))
            self.history.insert('end',control_label(expanded)+'\n',tag)
        if self.preferences.values.get('bubbles',False):
            colors=app_palette(self.preferences.values)
            tag='bubble_out' if message.outgoing else 'bubble_in'
            self.history.tag_configure(tag,background=colors['selected'] if message.outgoing else colors['panel'],
                                       lmargin1=48 if message.outgoing else 8,lmargin2=48 if message.outgoing else 8,
                                       rmargin=8 if message.outgoing else 48,spacing1=7,spacing3=7)
            self.history.tag_add(tag,start,'end-1c')

    def emoji_at(self, document_id, mark, epoch):
        if self.demo:return
        backend,account=self.service.backend,self.ui_account
        def current():
            return account==self.ui_account and epoch==self.preview_generation and self.history.winfo_exists() and mark in self.history.mark_names()
        def show(path):
            if not path or not current():return
            def painted(photo):
                self.preview_images[mark]=photo
                self.history.configure(state='normal')
                tags=self.history.tag_names(mark)
                self.history.delete(mark,mark+' +1 chars')
                self.history.image_create(mark,image=photo,padx=1)
                for tag in tags:self.history.tag_add(tag,mark,mark+' +1 chars')
                self.history.configure(state='disabled')
            self.request_photo(path,(28,28),painted,owner=self.history,tint=self.emoji_tint(document_id,account),valid=current)
        self.emoji_art(document_id,account,backend,show,valid=current)

    def message_actions(self, message):
        if self.busy or self.demo or self.active is None: return
        backend, account, peer = self.service.backend, self.ui_account, self.active
        from .chat_capabilities import chat_capabilities
        caps = chat_capabilities(self, peer)
        from .app_dialogs import popup_menu
        window = self.root
        def close(): pass
        entries = []
        def information():
            from .timestamps import date_text
            rows=[]
            if message.date is not None:rows.append(tr('Sent')+': '+date_text(message.date,self.preferences.values))
            if getattr(message,'edited_at',None) is not None:rows.append(tr('Edited')+': '+date_text(message.edited_at,self.preferences.values))
            if rows:messagebox.showinfo(tr('Informacion'),'\n'.join(rows),parent=self.root)
        if message.date is not None:entries.append((tr('Informacion'),information))
        if getattr(message, 'comments_count', None) is not None:
            entries.append((f'💬 {message.comments_count}', lambda: self.open_comments(message)
                if (account, peer) == (self.ui_account, self.active) and backend is self.service.backend else None))
        if message.media_kind == 'conference':
            entries.append((tr('Conference call'), lambda: self.join_conference_message(message, peer=peer)
                if (account, peer) == (self.ui_account, self.active) and backend is self.service.backend else None))
        def reply():
            if not hasattr(self, 'reply_drafts'): self.reply_drafts = {}
            self.reply_drafts[(account,peer)] = message.id
            self.remember_replies({(account,peer,message.id):message})
            close(); self.update_reply(); self.editor.focus_set()
        def remove(everyone):
            if self.busy: return
            prompt = 'Delete this message for everyone?' if everyone else 'Delete this message for you?'
            if not messagebox.askyesno(tr('Delete message'), tr(prompt), parent=window): return
            if (account,peer)!=(self.ui_account,self.active) or backend is not self.service.backend:return
            if everyone and not chat_capabilities(self,peer).allows_message('delete',message):return
            def done(_):
                close()
                if (account,peer)==(self.ui_account,self.active):
                    self.messages = [m for m in self.messages if m.id != message.id]
                    self.render_messages(False)
            self.call(backend.delete_message(peer,message.id,everyone),done,tr('Guardando...'))
        def forward():
            close()
            target, body = self.dialog('Forward message', '540x480')
            chats = [chat for chat in self.chats if chat_capabilities(self, chat.id, chat=chat).writable]
            listing = tk.Listbox(body, exportselection=False); listing.pack(fill='both',expand=True)
            for chat in chats: listing.insert('end',chat.name)
            def send():
                if self.busy or not listing.curselection(): return
                if account!=self.ui_account or backend is not self.service.backend:return
                chat = chats[listing.curselection()[0]]
                if not chat_capabilities(self,chat.id,chat=chat).writable:return
                if not messagebox.askyesno(tr('Forward message'), tr('Forward to {name}?').format(name=chat.name), parent=target): return
                if account!=self.ui_account or backend is not self.service.backend:return
                self.call(backend.forward_message(peer,message.id,chat.id),lambda _:target.destroy(),tr('Enviando...'))
            ttk.Button(body,text=tr('Enviar >'),command=send).pack(fill='x',pady=8)
        def edit():
            close(); self.edit_message_dialog(backend,account,peer,message)
        def read_time():
            if not self.busy:
                self.call(backend.read_time(peer,message.id,seconds=self.preferences.values.get('show_seconds',False)),lambda value:messagebox.showinfo(tr('Read time'),value,parent=window),tr('Cargando...'))
        for label, action, permission in [('Reply',reply,'reply'),('Reactions',lambda:(close(),self.reaction_picker(message)),'react'),('Pinned messages',lambda:(close(),self.pin_message_dialog(message)),'pin'),('Forward message',forward,'forward'),('Edit message',edit,'edit'),('Delete for me',lambda:remove(False),'delete_self'),('Delete for everyone',lambda:remove(True),'delete'),('Read time',read_time,'read_time'),('Translation / AI',lambda:(close(),DesktopTools.message_actions(self,message)),None)]:
            if label=='Translation / AI' and not self.message_tool_kinds(message):continue
            allowed = caps.kind in ('self','user','bot','group','secret') if permission == 'delete_self' else permission is None or caps.allows_message(permission,message)
            if not allowed: continue
            def scoped(callback=action, check=permission):
                if (account,peer)!=(self.ui_account,self.active) or backend is not self.service.backend:return
                current=chat_capabilities(self,peer)
                if check not in (None,'delete_self') and not current.allows_message(check,message):return
                callback()
            entries.append((tr(label),scoped))
        entries.insert(0,(tr('Select'),lambda:self.toggle_message_selection(message)))
        entries.insert(1,(tr('Copy text'),lambda:self.copy_message_text(message)))
        def open_windows():
            # 1.4.1: with several messages selected, one window per message.
            from .message_window import open_message_windows
            selected=sorted(getattr(self,'selected_messages',()) or ()) if self.message_selected(message.id) else []
            chosen=[m for m in self.messages if m.id in selected] if selected else [message]
            open_message_windows(self,chosen,peer)
        entries.insert(2,(tr('Open in new window'),open_windows))
        if caps.allows_message('forward',message):
            entries.insert(2,(tr('Save to Saved Messages'),lambda:self.save_message_to_self(message,backend,account,peer)))
        entries.extend(self.advanced_message_actions(message))
        popup_menu(self.root,entries)

    def remember_replies(self,replies):
        """Bound old contexts without evicting visible or composed reply targets."""
        self.reply_cache.update(replies)
        if len(self.reply_cache)<=1024:return
        account,peer=self.ui_account,self.active
        needed={message.reply_to_id for message in self.messages if message.reply_to_id}
        needed.add(getattr(self,'reply_drafts',{}).get((account,peer)))
        protected={(account,peer,ident) for ident in needed if ident is not None}
        for key in list(self.reply_cache):
            if len(self.reply_cache)<=1024:break
            if key not in protected:self.reply_cache.pop(key,None)

    def update_reply(self):
        ident = getattr(self,'reply_drafts',{}).get((self.ui_account,self.active))
        if hasattr(self,'reply_label') and self.reply_label.winfo_exists():
            original=next((m for m in self.messages if m.id==ident),None) or getattr(self,'reply_cache',{}).get((self.ui_account,self.active,ident))
            text=(original.raw_text if original.raw_text is not None else original.text) if original else (tr('Reply to message')+f' #{ident}' if ident else '')
            self.reply_label.set(text,getattr(original,'entities',()),'↪ '+original.sender+' · ' if original else '')
            if hasattr(self,'reply_row'):
                if ident: self.reply_row.pack(fill='x',before=self.editor)
                else: self.reply_row.pack_forget()

    def clear_sent_reply(self, account, peer, reply_to):
        replies = getattr(self, 'reply_drafts', {})
        if reply_to is not None and replies.get((account, peer)) == reply_to:
            replies.pop((account, peer), None)
            if account == self.ui_account and peer == self.active:
                self.update_reply()

    def cancel_reply(self):
        getattr(self,'reply_drafts',{}).pop((self.ui_account,self.active),None)
        self.update_reply()

    def edit_message_dialog(self, backend, account, peer, message):
        window, frame = self.dialog('Edit message', '580x460')
        editor = tk.Text(frame,height=8,wrap='word'); editor.pack(fill='both',expand=True)
        editor.insert('1.0', message.raw_text if message.raw_text is not None else message.text)
        replacement = [None]
        info = tk.StringVar()
        ttk.Label(frame,textvariable=info,wraplength=500).pack(fill='x',pady=5)
        def choose():
            value = filedialog.askopenfilename(parent=window,title=tr('Replace attachment'))
            if value: replacement[0] = value; info.set(Path(value).name)
        if message.media: ttk.Button(frame,text=tr('Replace attachment'),command=choose).pack(fill='x',pady=4)
        def save():
            if self.busy or account!=self.ui_account or backend is not self.service.backend:return
            from .chat_capabilities import chat_capabilities
            if not chat_capabilities(self,peer).allows_message('edit',message):return
            def done(item):
                window.destroy()
                if (account,peer)==(self.ui_account,self.active):
                    self.messages = [item if m.id==item.id else m for m in self.messages]; self.render_messages(False)
            self.call(backend.edit_existing(peer,message.id,editor.get('1.0','end-1c'),replacement[0]),done,tr('Guardando...'))
        ttk.Label(frame,text=tr('Telegram decides whether this message or attachment can be edited.'),wraplength=500).pack(pady=6)
        ttk.Button(frame,text=tr('Save'),command=save).pack(fill='x',pady=4)

    def logo_gallery(self, parent):
        ttk.Label(parent, text='TeleGraph', style='Title.TLabel').pack(anchor='w', pady=(16, 8))
        gallery = ttk.Frame(parent)
        gallery.pack(fill='x')
        variant = ttk.Combobox(gallery, state='readonly', values=tuple(VARIANTS.values()))
        variant.current(tuple(VARIANTS).index(self.preferences.values['logo_variant']))
        variant.pack(fill='x', pady=4)
        colors = tuple(LOGO_PALETTES)
        color = ttk.Combobox(gallery, state='readonly', values=tuple(tr(value.title()) for value in colors))
        color.current(colors.index(self.preferences.values['logo_color']))
        color.pack(fill='x', pady=4)
        themes = ('dark', 'light', 'system')
        theme = ttk.Combobox(gallery, state='readonly', values=tuple(tr(value.title()) for value in themes))
        theme.current(themes.index(self.preferences.values['logo_theme']))
        theme.pack(fill='x', pady=4)
        preview = ttk.Label(gallery)
        preview.pack(pady=6)

        def selection():
            return tuple(VARIANTS)[variant.current()], themes[theme.current()], colors[color.current()]

        def draw_preview(_event=None):
            from .themes import resolve_theme
            selected, mode, tint = selection()
            try:
                path = brand_asset_path(self.preferences.path.parent, selected, resolve_theme(mode), tint)
            except OSError:
                preview.configure(image='', text=VARIANTS[selected])
                return
            preview.image = self.load_photo(path, (128, 128))
            preview.configure(image=preview.image or '', text='' if preview.image else VARIANTS[selected])

        for control in (variant, color, theme):
            control.bind('<<ComboboxSelected>>', draw_preview)
        ttk.Button(gallery, text=tr('Apply'), command=lambda: self.select_logo(*selection())).pack(anchor='w', pady=4)
        self.logo_selection = tk.StringVar()
        ttk.Label(parent, textvariable=self.logo_selection).pack(anchor='w', pady=6)
        draw_preview()
        self.update_logo_selection()

    def update_logo_selection(self):
        if not hasattr(self, 'logo_selection'):
            return
        values = self.preferences.values
        if values.get('custom_icon'):
            selected = values.get('official_icon_label') or tr('Custom app icon')
        else:
            selected = ' · '.join((VARIANTS[values['logo_variant']], tr(values['logo_color'].title()),
                                   tr(values['logo_theme'].title())))
        self.logo_selection.set(tr('Selected') + ': ' + selected)

    def select_logo(self, variant, theme, color='default'):
        try:
            self.preferences.save({'logo_variant': variant, 'logo_theme': theme, 'logo_color': color,
                                   'custom_icon': '', 'official_icon_label': ''})
        except OSError as exc:
            self.show_error(exc)
            return
        if hasattr(self, 'logo_theme_picker'):
            self.logo_theme_picker.current(('dark', 'light', 'system').index(theme))
        self.refresh_logo()
        self.update_logo_selection()

    def setup_actions(self, sidebar, conversation):
        if sidebar is not None:
            self.chat_list.configure(columns=('actions',))
            self.chat_list.column('actions', width=36, minwidth=36, stretch=False, anchor='center')
            self.chat_list.bind('<Button-1>', self.chat_action_click, add='+')
        row = FlowFrame(conversation)
        self.action_row, self.action_buttons = row, {}
        row.pack(fill='x', pady=4)
        for title, callback in [('Search in chat', self.search_chat), ('Shared media', self.shared_media), ('Bot commands', self.commands_menu), ('Open Mini App', self.open_bot_app), ('Chat background', self.choose_wallpaper)]:
            button = ttk.Button(row, text=tr(title), command=callback)
            button.pack(side='left', padx=2)
            self.action_buttons[title] = button
        for name, title, video in (('call_button', 'Call', False), ('video_call_button', 'Video call', True)):
            button = ttk.Button(row, text=tr(title), command=lambda v=video:self.start_call(video=v))
            button.pack(side='left', padx=2)
            setattr(self, name, button)
            self.action_buttons[title] = button
        secret_btn = ttk.Button(row, text='🔒 ' + tr('Clave / TTL'), command=self.secret_chat_dialog)
        secret_btn.pack(side='left', padx=2)
        self.secret_chat_button = secret_btn
        self.action_buttons['Clave de cifrado y autodestrucción'] = secret_btn
        reply_row = ttk.Frame(conversation)
        self.reply_row = reply_row
        from .rich_preview import RichPreview
        self.reply_label = RichPreview(reply_row,self,command=lambda:self.jump_message(self.reply_drafts.get((self.ui_account,self.active))))
        self.reply_label.pack(side='left',fill='x',expand=True)
        ttk.Button(reply_row,text=tr('Cancel reply'),command=self.cancel_reply).pack(side='right')
        self.update_reply()

    def chat_action_click(self, event):
        ident = self.chat_list.identify_row(event.y)
        if ident and self.chat_list.identify_column(event.x) == '#1':
            from .app_dialogs import event_action
            return event_action(self.chat_list, lambda:self.chat_actions(int(ident)))

    def chat_actions(self, peer):
        if self.busy or self.demo: return
        chat = next((c for c in self.chats if c.id == peer), None)
        if chat is None: return
        from .app_dialogs import popup_menu
        from .chat_menus import list_entries, in_chat_entries, mark_chat_read
        account=self.ui_account
        # List-exclusive entries first, then every chat tool (1.4: same tools
        # as the in-chat ⋯ menu; a tool for another chat opens it first).
        exclusive=[(tr('Open chat in new window'),lambda:self.open_chat_in_new_window(peer,chat,account)),
            (tr('Select'),lambda:self.toggle_chat_selection(peer)),
            (tr('Preview chat — unread'),lambda:self.preview_chat(peer)),
            (tr('Mark as read'),lambda:mark_chat_read(self,peer))]
        tools=in_chat_entries(self,peer,include_pin=False)
        popup_menu(self.root,[*exclusive,None,*list_entries(self,peer,chat),None,*tools])

    def open_sender_profile(self,message,scope):
        if scope!=(self.ui_account,self.active) or self.busy or getattr(self,'selection_kind',None):return
        sender=getattr(message,'sender_id',None)
        if sender is None or not any(m.id==message.id and m.sender_id==sender for m in self.messages):return
        self.show_contact_profile(sender)

    def show_contact_profile(self,peer=None):
        if peer is None:peer=self.active
        if peer is None:return
        from .contact_profile import ContactProfile
        return ContactProfile(self,peer)

    def full_profile_photo(self, path, name):
        from .media_viewer import show_image
        if __import__('tg_ascii.menu_style',fromlist=['x']).uses_system('image_viewer'):
            from .native_open import open_with_system
            open_with_system(path,name or 'profile',on_error=lambda error:self.worker.events.put((self.show_error,error)))
            return
        try:
            window = show_image(self.root, path, name, name=name,
                                on_error=lambda error:self.worker.events.put((self.show_error,error)))
            self.popups.append(window)
            def save():
                destination = filedialog.asksaveasfilename(parent=window, initialfile='profile.jpg', defaultextension='.jpg', filetypes=[('JPEG','*.jpg'),('All files','*')])
                if destination:
                    try: shutil.copyfile(path, destination)
                    except OSError as exc: self.show_error(exc)
            ttk.Button(window, text=tr('Guardar archivo como...'), command=save).pack(pady=10)
        except (ImportError, OSError, ValueError) as exc: self.show_error(exc)

    def edit_contact(self, profile, backend, previous=None):
        account=self.ui_account
        if previous and previous.winfo_exists(): previous.destroy()
        window, frame = self.dialog('Edit contact', '540x620')
        first = self.field(frame, 'Nombre', profile['first_name'])
        last = self.field(frame, 'Apellidos', profile['last_name'])
        phone = self.field(frame, 'Telefono internacional', profile['phone'])
        def valid():return window.winfo_exists() and account==self.ui_account and backend is self.service.backend
        note_value = None
        if not self.demo:
            from .contact_tools import extend_edit_contact
            note_value = extend_edit_contact(self, frame, profile, backend, valid)
        def save():
            if self.busy or account!=self.ui_account or backend is not self.service.backend: return
            def saved(_):
                if account==self.ui_account and window.winfo_exists():window.destroy(); self.refresh()
            note = note_value() if note_value else None
            async def operation():
                result = await backend.save_contact(profile['id'], first.get(), last.get(), phone.get())
                if note is not None and note != (profile.get('note') or ''):
                    from .contact_tools import save_contact_note
                    await save_contact_note(backend, profile['id'], note)
                return result
            self.call(operation(), saved, tr('Guardando...'))
        ttk.Button(frame, text=tr('Guardar contacto'), command=save).pack(fill='x', pady=16)

    def add_username_contact(self, previous=None):
        if self.busy or self.demo: return
        if previous and previous.winfo_exists(): previous.destroy()
        backend, account = self.service.backend, self.ui_account
        window, frame = self.dialog('Add by username', '500x300')
        username = self.field(frame, 'Nombre de usuario')
        def valid():
            return window.winfo_exists() and account == self.ui_account and backend is self.service.backend
        def loaded(profile):
            if not valid(): return
            if profile['is_user']: self.edit_contact(profile, backend, window)
            else: self.show_error(ValueError(tr('Choose a person, not a channel or group.')))
        def find():
            if self.busy or not valid(): return
            self.call(backend.profile(username.get().strip().lstrip('@')), loaded, tr('Cargando...'))
        ttk.Button(frame, text=tr('Añadir contacto'), command=find).pack(fill='x', pady=16)

    def universal_search(self):
        if self.busy or self.demo: return
        backend = self.service.backend
        account=self.ui_account
        window, frame = self.dialog('Search Telegram', '620x560')
        query = self.field(frame, 'Buscar chats', self.search.get(),emoji=True)
        listing = tk.Listbox(frame, exportselection=False)
        listing.pack(fill='both', expand=True, pady=8)
        results = []
        def valid():return window.winfo_exists() and account==self.ui_account and backend is self.service.backend
        def loaded(items):
            if not valid(): return
            results[:] = items; listing.delete(0,'end')
            for chat in items: listing.insert('end', f'{chat.name} [{chat.kind}]')
        def find():
            if valid() and not self.busy: self.call(backend.search_public(query.get()), loaded, tr('Cargando...'))
        def open_chat():
            if not valid() or self.busy or not listing.curselection(): return
            chat = results[listing.curselection()[0]]; window.destroy(); self.open_resolved(chat)
        ttk.Button(frame, text=tr('Search Telegram'), command=find).pack(fill='x', pady=4)
        ttk.Button(frame, text=tr('Abrir chat'), command=open_chat).pack(fill='x', pady=4)
        def join():
            if valid() and not self.busy and listing.curselection():
                chat=results[listing.curselection()[0]]
                if chat.kind in ('channel','group'):self.membership_action(chat.id)
        join_button=ttk.Button(frame,text=tr('Unirse al grupo o canal'),command=join)
        def selected(_=None):
            selection=listing.curselection()
            chat=results[selection[0]] if selection else None
            from .chat_capabilities import capabilities_for
            if chat is not None and capabilities_for(chat,entity=chat.entity).can_join:
                join_button.pack(fill='x',pady=4)
            else:join_button.pack_forget()
        listing.bind('<<ListboxSelect>>',selected)
        listing.bind('<Double-Button-1>', lambda _: open_chat())
        if query.get(): find()

    def search_chat(self):
        self.message_browser(False)

    def shared_media(self):
        self.message_browser(True)

    def commands_menu(self):
        if self.busy or self.active is None or self.demo: return
        peer, account = self.active, self.ui_account
        def loaded(commands):
            if (account,peer)!=(self.ui_account,self.active): return
            from .app_dialogs import popup_menu
            if not commands:
                self.status.set(tr('No commands published by this bot.')); return
            def choose(command):
                if (account,peer)!=(self.ui_account,self.active): return
                self.editor.insert('insert','/'+command+' '); self.editor.focus_set()
            popup_menu(self.root,[('/'+c.command+' — '+c.description,lambda command=c.command:choose(command)) for c in commands],anchor=self.pinned_button)
        self.call(self.service.backend.bot_commands(peer),loaded,tr('Cargando...'))

    def start_secret_chat(self, peer=None):
        if self.busy:
            return
        peer = self.active if peer is None else peer
        if peer is None:
            return
        backend, account = self.service.backend, self.ui_account

        def created(chat):
            if account != self.ui_account or backend is not self.service.backend:
                return
            self.open_resolved(chat)
            self.status.set(tr('Chat secreto iniciado.'))

        self.call(backend.start_secret_chat(peer), created, tr('Iniciando chat secreto...'))

    def rekey_secret_chat_action(self, peer=None):
        if self.busy:
            return
        peer = self.active if peer is None else peer
        from .secret_chats import is_secret_peer
        if not is_secret_peer(peer):
            return
        backend, account = self.service.backend, self.ui_account

        def done(_):
            if account == self.ui_account:
                self.status.set(tr('Rotación de clave solicitada (PFS).'))

        self.call(backend.rekey_secret_chat(peer), done, tr('Rotando clave...'))

    def close_secret_chat_action(self, peer=None):
        if self.busy:
            return
        peer = self.active if peer is None else peer
        from .secret_chats import is_secret_peer
        if not is_secret_peer(peer):
            return
        if not messagebox.askyesno(
            tr('Cerrar chat secreto'),
            tr('¿Cerrar este chat secreto y borrar sus claves y mensajes locales?'),
            parent=self.root,
        ):
            return
        backend, account = self.service.backend, self.ui_account

        def done(_):
            if account != self.ui_account:
                return
            if self.active == peer:
                self.active = None
                self.messages = []
                self.render_messages(False)
            self.refresh()
            self.status.set(tr('Chat secreto cerrado.'))

        self.call(backend.discard_secret_chat(peer, delete_history=True), done, tr('Cerrando chat secreto...'))

    def secret_chat_dialog(self, peer=None):
        if self.busy:
            return
        peer = self.active if peer is None else peer
        from .secret_chats import TTL_CHOICES, format_ttl, is_secret_peer
        from .secret_tl import FINGERPRINT_GRID_GLYPHS
        if not is_secret_peer(peer):
            return
        backend, account = self.service.backend, self.ui_account
        window, frame = self.dialog('Clave de cifrado y autodestrucción', '560x660')

        def valid():
            return window.winfo_exists() and account == self.ui_account and backend is self.service.backend

        def render(info):
            if not valid():
                return
            for child in frame.winfo_children():
                child.destroy()
            ttk.Label(
                frame,
                text=f"🔒 {info.get('user_name') or info.get('peer_id')}",
                style='Title.TLabel',
            ).pack(anchor='w', pady=(0, 4))
            state_lbl = {
                'active': tr('Cifrado de extremo a extremo activo'),
                'waiting': tr('Esperando a que el contacto se conecte…'),
                'requested': tr('Solicitud de chat secreto'),
                'discarded': tr('Chat secreto cerrado'),
            }.get(info.get('state', 'active'), info.get('state', ''))
            ttk.Label(
                frame,
                text=f"{state_lbl} · Layer {info.get('layer', 144)} · PFS {info.get('key_use_count', 0)}/100",
                style='Muted.TLabel',
            ).pack(anchor='w', pady=(0, 8))

            if info.get('emojis'):
                ttk.Label(
                    frame,
                    text=info['emojis'],
                    font=(self.font_family, self.preferences.values.get('font_size', 13) + 10, 'bold'),
                ).pack(pady=4)

            grid = info.get('grid') or []
            if grid:
                colors = app_palette(self.preferences.values)
                palette_4 = ('#ffffff', '#d5e6f3', '#2d5775', '#2f99c9')
                cell = 12
                size = len(grid) * cell
                canvas = tk.Canvas(frame, width=size, height=size, highlightthickness=1,
                                   highlightbackground=colors['muted'], bg=colors['panel'])
                canvas.pack(pady=6)
                for r_idx, row_vals in enumerate(grid):
                    for c_idx, val in enumerate(row_vals):
                        fill = palette_4[FINGERPRINT_GRID_GLYPHS.index(val)]
                        canvas.create_rectangle(
                            c_idx * cell, r_idx * cell, (c_idx + 1) * cell, (r_idx + 1) * cell,
                            fill=fill, outline='',
                        )

            if info.get('hex'):
                from .contact_profile import copyable_field
                copyable_field(frame, 'HEX', info['hex'], self, valid)

            if grid:
                ttk.Label(
                    frame,
                    text=tr('Si estos 5 emojis y la cuadrícula coinciden con los del teléfono de {name}, el cifrado de extremo a extremo está garantizado.').format(
                        name=info.get('user_name') or tr('tu contacto')
                    ),
                    wraplength=500,
                    style='Muted.TLabel',
                ).pack(anchor='w', pady=(4, 10))
            elif info.get('state') == 'active':
                ttk.Label(frame, text='HEX · ' + tr('Unavailable'), style='Muted.TLabel').pack(anchor='w')

            ttl_row = ttk.Frame(frame)
            ttl_row.pack(fill='x', pady=6)
            ttk.Label(ttl_row, text=tr('Temporizador de autodestrucción (TTL)')).pack(side='left')
            ttl_values = [ seconds for seconds, _ in TTL_CHOICES ]
            ttl_labels = [ format_ttl(seconds) for seconds, _ in TTL_CHOICES ]
            picker = Choice(ttl_row, values=ttl_labels, width=16)
            cur_ttl = int(info.get('ttl', 0))
            picker.current(ttl_values.index(cur_ttl) if cur_ttl in ttl_values else 0)
            picker.pack(side='right')

            def apply_ttl():
                if not valid() or self.busy:
                    return
                chosen = ttl_values[picker.current()]
                self.call(backend.set_secret_ttl(peer, chosen), render, tr('Guardando...'))

            ttk.Button(frame, text=tr('Aplicar autodestrucción'), command=apply_ttl).pack(fill='x', pady=4)
            ttk.Button(
                frame,
                text=tr('Rotar clave ahora (PFS)'),
                command=lambda: self.call(backend.rekey_secret_chat(peer), render, tr('Rotando clave...')) if valid() and not self.busy else None,
            ).pack(fill='x', pady=4)
            ttk.Button(
                frame,
                text=tr('Enviar aviso de captura de pantalla'),
                command=lambda: self.call(backend.notify_secret_screenshot(peer), lambda _: None, tr('Enviando...')) if valid() and not self.busy else None,
            ).pack(fill='x', pady=4)
            ttk.Button(
                frame,
                text=tr('Cerrar chat secreto'),
                command=lambda: (window.destroy(), self.close_secret_chat_action(peer)),
            ).pack(fill='x', pady=(10, 4))

        self.call(backend.secret_chat_info(peer), render, tr('Cargando...'))
