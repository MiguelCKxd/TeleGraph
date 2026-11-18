from .timestamps import message_time
"""Modern interaction layer. Captures account/peer before every asynchronous action."""
from pathlib import Path
import asyncio
import time
import uuid
import tkinter as tk
from tkinter import ttk
from .desktop_actions import DesktopActions
from .app_dialogs import Choice, CheckList, scrollable, filedialog, messagebox
from .i18n import tr
from .preferences import read_json, write_json
from .ui_work import bind_text_action

ART_TIMEOUT = 60
EMOJI_CONCURRENCY = 4


from .interactions import DesktopInteractions
from .desktop_bot_buttons import DesktopBotButtons
from .resources import cache_entries, network_slots


def privacy_global_fields(premium, config, settings):
    """Account/config-gated controls; existing flags can always be turned off."""
    fields = {'hide_read_marks': 'Hide read time'}
    for key, label, flag in (
            ('archive_and_mute_new_noncontact_peers', 'Archive and mute new non-contacts', 'autoarchive_setting_available'),
            ('new_noncontact_peers_require_premium', 'Require Premium for new non-contacts', 'new_noncontact_peers_require_premium_without_ownpremium')):
        if premium or config.get(flag) is True or getattr(settings, key, False) is True:
            fields[key] = label
    return fields


class DesktopModern(DesktopBotButtons, DesktopInteractions, DesktopActions):
    def init_modern(self):
        self.message_palettes={}; self.palette_pending=set(); self.reply_cache={}; self.reply_pending=set()
        self.wallpaper_path=None; self.media_requests={}; self.presence_last={}; self.typing_last={}
        self.wallpapers_file=self.preferences.path.parent/'wallpapers.json'
        owner = getattr(self, '_linked_owner', None)
        self.wallpapers = owner.wallpapers if owner is not None else {} if self.demo else read_json(self.wallpapers_file,{})
        self._preview_only=False; self._header_key=None; self._search_timer=None; self._typing_stop=None
        if owner is None:
            self.root.after(1000,self.presence_tick)

    def setup_actions(self,sidebar,conversation):
        super().setup_actions(sidebar,conversation)
        self._header_key=None
        # Existing buttons are placed above the history, and bot-only controls start hidden.
        row=self.action_row
        row.pack_forget()
        from .scrolling import FlowFrame
        self.bot_row=FlowFrame(conversation)
        self.bot_buttons={}
        for label,widget in self.action_buttons.items():
            if label in ('Bot commands','Open Mini App'):
                widget.destroy()
                button=ttk.Button(self.bot_row,text=tr(label),command=self.commands_menu if label=='Bot commands' else self.open_bot_app)
                button.flow_hidden=True; self.bot_buttons[label]=button
        from .bubbles import BubbleView
        self.bubble_view=BubbleView(self.history_canvas,self,bg='#08100c')
        self.conversation_scroll_panel=conversation
        conversation._scroll_target=self.history
        if sidebar is not None:
            sidebar._scroll_target=self.chat_list
        self.history_bar.configure(command=self.scroll_messages)
        self.bubble_view.configure(yscrollcommand=self.scroll_position)
        self.history.configure(yscrollcommand=self.scroll_position)
        self.down_button=ttk.Button(self.history_canvas,text='↓',width=3,command=self.latest_messages)
        self.header_details=ttk.Frame(conversation); self.header_details.pack(fill='x',before=self.history_canvas,pady=(0,4))
        self.header_avatar=ttk.Label(self.header_details); self.header_avatar.pack(side='left',padx=(0,8))
        self.chat_title_label.pack_forget()
        names=ttk.Frame(self.header_details); names.pack(side='left',fill='x',expand=True)
        name_row=ttk.Frame(names); name_row.pack(anchor='w')
        self.header_name=ttk.Label(name_row,textvariable=self.title,width=22,anchor='w',cursor='hand2')
        self.header_name.pack(side='left')
        self.header_name.bind('<ButtonRelease-1>',lambda _:self.show_contact_profile())
        self.header_status_emoji=ttk.Label(name_row); self.header_status_emoji.pack(side='left',padx=6)
        self.activity=tk.StringVar(); ttk.Label(names,textvariable=self.activity,style='Muted.TLabel').pack(anchor='w')
        self.pinned_button=ttk.Button(self.header_details,text='⋯',width=3,command=self.chat_tools_menu)
        self.pinned_button.pack(side='right',before=self.header_avatar)
        # Modern hides action_row: call controls must belong to the visible
        # conversation header. Reuse the capability-aware attribute names.
        for name, title, video in (('video_call_button', 'Video call', True),
                                   ('call_button', 'Call', False)):
            previous = getattr(self, name, None)
            if previous is not None:
                previous.destroy()
            button = ttk.Button(self.header_details, text=tr(title),
                                command=lambda v=video: self.start_call(video=v))
            button.pack(side='right')
            setattr(self, name, button)
            self.action_buttons[title] = button
        if sidebar is not None:
            self.search.trace_add('write',lambda *_:self.schedule_global_search())
            self.global_results=ttk.Treeview(sidebar,show='tree',height=5,selectmode='browse')
            self.global_results.bind('<Double-Button-1>',lambda _:self.open_search_result())
            self.global_results.bind('<Return>',lambda _:self.open_search_result())
            self.search_records={}
            self.search_offset=None
            self.search_more=ttk.Button(sidebar,text=tr('More'),command=lambda:self.run_global_search(True))
        self.editor.bind('<KeyRelease>',self.typing_changed,add='+')
        self.editor.bind('<<Paste>>',lambda _:self.root.after_idle(self.typing_changed),add='+')
        self.setup_interactions()
        self.setup_bot_keyboard(conversation)

    def scroll_messages(self,*args):
        target=self.bubble_view if getattr(self,'_canvas_chat_view',self.preferences.values['bubbles']) else self.history
        target.yview(*args)
    def scroll_position(self,first,last):
        self.history_bar.set(first,last)
        canvas=getattr(self,'bubble_view',None)
        if canvas is not None:
            from .interface_background import pin_canvas_background
            pin_canvas_background(canvas)
        if hasattr(self,'down_button'):
            if float(last)<.97: self.down_button.place(relx=1,rely=1,x=-28,y=-12,anchor='se')
            else: self.down_button.place_forget()
        if float(first)<.01 and getattr(self,'_allow_history_load',False): self.load_older()
        if hasattr(self,'preview_cache'):
            from .read_visibility import schedule
            schedule(self)
    def latest_messages(self):
        if not self.demo and getattr(self,'_jumped',False):
            account,peer,backend=self.ui_account,self.active,self.service.backend
            def loaded(items):
                if (account,peer)!=(self.ui_account,self.active): return
                self.messages=items; self._jumped=False; self.render_messages(True)
            self.call(backend.history(peer),loaded,tr('Loading...'))
        elif getattr(self,'_canvas_chat_view',self.preferences.values['bubbles']): self.bubble_view.yview_moveto(1)
        else: self.history.see('end')
    def load_older(self):
        if self.busy or self.demo or not self.messages or getattr(self,'_older_pending',False): return
        # After a failed page (offline, rate limit) every scroll event at the
        # top used to repeat the request immediately. Back off briefly instead.
        if time.monotonic()<getattr(self,'_older_retry_at',0): return
        account,peer,backend=self.ui_account,self.active,self.service.backend
        before=min(m.id for m in self.messages)
        if getattr(self,'_oldest_loaded',None)==(account,peer,before): return
        self._older_pending=True
        def loaded(items):
            self._older_pending=False
            if (account,peer)!=(self.ui_account,self.active): return
            if not items: self._oldest_loaded=(account,peer,before); return
            old=self.messages[0].id
            self.messages=sorted({m.id:m for m in items+self.messages}.values(),key=lambda m:m.id)
            self.render_messages(False); self.jump_loaded(old)
        def failed(exc):
            self._older_pending=False
            from .flood_control import FLOOD_ERRORS,wait_seconds
            delay=wait_seconds(exc) if isinstance(exc,FLOOD_ERRORS) else 3
            self._older_retry_at=time.monotonic()+min(delay,60)
        self.worker.submit(backend.older_messages(peer,before),loaded,failed)

    def update_modern_view(self,follow):
        from .interface_background import chat_backdrop
        from .visual_effects import text_effects_enabled
        from .line_breaking import needs_canvas, apply_text_widget
        canvas_view=self.preferences.values['bubbles'] or bool(chat_backdrop(self)) or text_effects_enabled(self.preferences.values) or needs_canvas(self.preferences.values)
        if not canvas_view:apply_text_widget(self,self.history)
        self._canvas_chat_view=canvas_view
        self.refresh_bot_keyboard()
        self.conversation_scroll_panel._scroll_target=self.bubble_view if canvas_view else self.history
        self.ensure_message_accents()
        self._allow_history_load=False
        if canvas_view:
            self.history.pack_forget(); self.bubble_view.pack(fill='both',expand=True)
            self.bubble_view.render(self.messages,follow)
        else:
            self.bubble_view.pack_forget(); self.history.pack(fill='both',expand=True,padx=4,pady=4)
        self.root.after_idle(lambda:setattr(self,'_allow_history_load',True))
        key=(self.ui_account,self.active)
        if key!=self._header_key:
            self._header_key=key; self.stop_typing(); self.refresh_header(); self.refresh_wallpaper()

    def refresh_header(self):
        self.update_chat_capabilities()
        if hasattr(self,'bot_row'):
            self.bot_row.pack_forget()
            for button in self.bot_buttons.values():
                button.flow_hidden=True;button.pack_forget();button.place_forget()
        if self.demo or self.active is None or not hasattr(self,'header_avatar'): return
        account,peer,backend=self.ui_account,self.active,self.service.backend
        widget=self.header_avatar
        avatar_token=widget._avatar_request=object()
        self.activity.set(''); widget.configure(image=''); widget.image=None
        self.header_status_emoji.configure(image=''); self.header_status_emoji.image=None
        self.header_status_emoji._emoji_request=object()
        self.bot_row.pack_forget()
        for button in self.bot_buttons.values(): button.flow_hidden=True; button.pack_forget(); button.place_forget()
        def loaded(info):
            if (account,peer)!=(self.ui_account,self.active) or not widget.winfo_exists(): return
            from .telegram_actions import peer_activity
            status=peer_activity(info['activity_entity'],self.preferences.values.get('show_seconds',False)) if info.get('activity_entity') is not None else info['status']
            self.activity.set(status); self.header_base_status=status
            for label,enabled in [('Bot commands',bool(info['commands'])),('Open Mini App',info['mini'])]:
                self.bot_buttons[label].flow_hidden=not enabled
                if enabled:self.bot_buttons[label].pack(side='left',padx=2)
            if info['commands'] or info['mini']:self.bot_row.pack(fill='x',before=self.editor,pady=2)
            self.bot_row.arrange()
            if info['emoji']: self.label_emoji(self.header_status_emoji,info['emoji'],account,backend)
        self.worker.submit(backend.chat_header(peer),loaded,lambda _:None)
        def avatar_current():
            return (account,peer)==(self.ui_account,self.active) and bool(widget.winfo_exists()) and widget is self.header_avatar and widget._avatar_request is avatar_token
        def avatar(path):
            if path and avatar_current():
                def painted(photo):widget.image=photo;widget.configure(image=photo or '')
                self.request_photo(path,(40,40),painted,owner=widget,valid=avatar_current)
        self.worker.submit(backend.avatar(peer,self.preview_dir/f'{account}-{peer}-header.jpg'),avatar,lambda _:None)

    def fetch_art(self,key,operation,done,valid=None):
        from .media_retry import failed_recently,remember_failure,clear_failure,retry_visible_art,clear_art_retry
        if valid is not None:
            callback=done
            def done(path):
                try:
                    if valid():callback(path)
                except tk.TclError:pass
            done.media_valid=valid
        if key in self.preview_cache:
            path=self.preview_cache[key]
            self.root.after_idle(lambda:done(path)); return
        if failed_recently(self,key):
            retry_visible_art(self,key,operation,[done]);done(None);return
        if key in self.media_requests: self.media_requests[key].append(done); return
        self.media_requests[key]=[done]
        def loaded(path):
            if path:
                clear_failure(self,key)
                clear_art_retry(self,key)
                self.preview_cache[key]=path
                while len(self.preview_cache)>cache_entries(512):self.preview_cache.pop(next(iter(self.preview_cache)))
            else:
                remember_failure(self,key)
            listeners=self.media_requests.pop(key,[])
            if not path:retry_visible_art(self,key,operation,listeners)
            for callback in listeners:
                try:callback(path)
                except tk.TclError:pass  # Another view may have been closed during delivery.
        def failed(_):
            remember_failure(self,key)
            listeners=self.media_requests.pop(key,[])
            retry_visible_art(self,key,operation,listeners)
            for callback in listeners:
                try:callback(None)
                except tk.TclError:pass
        coroutine=operation()
        async def bounded():
            # A silent connection must not hold an art slot forever (1.4.1).
            return await asyncio.wait_for(coroutine,ART_TIMEOUT)
        self.worker.submit(bounded(),loaded,failed)

    def emoji_art(self,document,account,backend,callback,valid=None):
        async def fetch():
            standard=getattr(self,'_standard_emoji_documents',{}).get((account,document))
            docs=[standard] if standard else await backend.custom_emoji_documents([document])
            if not docs: return None
            from collections import OrderedDict
            from .telegram_extras import emoji_attribute
            attribute=emoji_attribute(docs[0])
            colors=getattr(self,'_emoji_text_color',None)
            if colors is None:colors=self._emoji_text_color=OrderedDict()
            colors[(account,document)]=bool(getattr(attribute,'text_color',False))
            colors.move_to_end((account,document))
            while len(colors)>512:colors.popitem(last=False)
            from .animation import emoji_file
            if not hasattr(self,'_emoji_slots'):self._emoji_slots=asyncio.Semaphore(__import__('tg_ascii.resources',fromlist=['x']).network_slots(EMOJI_CONCURRENCY))
            async with self._emoji_slots:return await emoji_file(self,docs[0],account,backend)
        self.fetch_art((account,'emoji',document,self.preferences.values.get('animated_emoji',True)),fetch,callback,valid=valid)
    def label_emoji(self,widget,document,account,backend):
        token=widget._emoji_request=object()
        def current():return widget.winfo_exists() and account==self.ui_account and widget._emoji_request is token and (backend is None or backend is self.service.backend)
        def open_pack(_=None):
            if current() and not getattr(self,'busy',False):self.show_document_pack(document)
            return 'break'
        widget.configure(cursor='hand2',takefocus=True)
        for event in ('<ButtonRelease-1>','<Return>','<space>'):widget.bind(event,open_pack)
        def done(path):
            if path and current():
                def painted(photo):widget.image=photo;widget.configure(image=photo or '')
                self.request_photo(path,(20,20),painted,owner=widget,tint=self.emoji_tint(document,account),valid=current)
        self.emoji_art(document,account,backend,done,valid=current)

    def emoji_tint(self,document,account,color=None):
        if not getattr(self,'_emoji_text_color',{}).get((account,document)):return None
        from .appearance import app_palette
        color=color or app_palette(self.preferences.values)['text']
        if not color.startswith('#'):
            color='#%02x%02x%02x'%tuple(value//257 for value in self.root.winfo_rgb(color))
        return color
    def canvas_emoji(self,canvas,item,document,epoch,size,keep_text=False):
        if self.demo:return
        account,backend=self.ui_account,self.service.backend
        def current():
            return canvas.winfo_exists() and canvas.generation==epoch and account==self.ui_account and bool(canvas.coords(item))
        def done(path):
            if not path or not current():return
            tint=self.emoji_tint(document,account,canvas.itemcget(item,'fill'))
            def painted(photo):
                coords=canvas.coords(item)
                if hasattr(canvas,'keep_photo'):canvas.keep_photo(item,photo)
                else:canvas.photos.append(photo)
                if keep_text:
                    canvas.move(item,size,0)
                    canvas.itemconfigure(item,text=canvas.itemcget(item,'text').removeprefix('◇'))
                else:canvas.itemconfigure(item,text='')
                canvas.create_image(*coords,image=photo,anchor='nw',tags=canvas.gettags(item))
            self.request_photo(path,(size,size),painted,owner=canvas,tint=tint,valid=current)
        self.emoji_art(document,account,backend,done,valid=current)

    def canvas_media(self,canvas,item,message,epoch,size):
        if self.demo:return
        account,peer,backend=self.ui_account,self.active,self.service.backend
        async def fetch():
            if message.media_kind=='sticker':
                from .animation import emoji_file
                # Message stickers are shown up to ~180 px: render the TGS sharper.
                return await emoji_file(self,getattr(message.media,'document',message.media),account,backend,side=256)
            return await backend.download_media(message.media,self.preview_dir/f'{account}-{peer}-{message.id}-thumb.jpg',thumbnail=True)
        def current():
            return canvas.winfo_exists() and canvas.generation==epoch and (account,peer)==(self.ui_account,self.active) and bool(canvas.coords(item))
        def loaded(path):
            if not path or not current():return
            def painted(photo):
                coords=canvas.coords(item)
                if hasattr(canvas,'keep_photo'):canvas.keep_photo(item,photo)
                else:canvas.photos.append(photo)
                canvas.itemconfigure(item,text='')
                canvas.create_image(*coords,image=photo,anchor='nw',tags=canvas.gettags(item))
            self.request_photo(path,size,painted,owner=canvas,valid=current)
        self.fetch_art((account,peer,message.id,self.preferences.values.get('animated_emoji',True)) if message.media_kind=='sticker' else (account,peer,message.id),fetch,loaded,valid=current)

    def open_image_message(self,message,peer=None):
        if message.media_kind=='image':
            from .custom_menus import handled
            if handled('image_viewer',self,message,self.active if peer is None else peer):return  # 1.5.2 user viewer
        if message.media_kind=='sticker': return self.show_document_pack(getattr(message.media,'document',message.media))
        if message.media_kind not in ('image','sticker'): return self.view_message_media(message,peer)
        if message.size>40*1024*1024: return self.view_message_media(message,peer)
        if __import__('tg_ascii.menu_style',fromlist=['x']).uses_system('image_viewer') and message.media_kind=='image':
            return self.open_message_natively(message,peer)
        from .media_gallery import open_chat_gallery
        return open_chat_gallery(self,message,peer)

    def native_open_failed(self,error):
        # Called from the opener thread: hand the error to Tk through the pump.
        self.worker.events.put((self.show_error,error))

    def open_message_natively(self,message,peer=None):
        """Setting 'Always open photos with the system viewer' (off by default)."""
        if self.demo:return
        account,backend=self.ui_account,self.service.backend
        peer=self.active if peer is None else peer
        target=self.preview_dir/f'{account}-{peer}-{message.id}-gallery.media'
        async def fetch():
            # Same private file as the in-app gallery, so both share downloads.
            if target.is_file() and target.stat().st_size:return target
            from telethon.errors import FileReferenceExpiredError,FileReferenceInvalidError,FileReferenceEmptyError
            try:return await backend.download_media(message.media,target)
            except (FileReferenceExpiredError,FileReferenceInvalidError,FileReferenceEmptyError):
                media=await backend.media_message(peer,message.id)
                return await backend.download_media(media,target)
        def loaded(path):
            from .native_open import open_with_system
            open_with_system(path,message.filename,on_error=self.native_open_failed)
            self.status.set(tr('Opened with the system viewer.'))
        self.call(fetch(),loaded,tr('Downloading...'),timeout=300)

    def link_inline_preview(self,mark):
        if getattr(self,'selection_kind',None)=='messages':return
        try: ident=int(mark.split('_')[1])
        except (ValueError,IndexError): return
        message=next((m for m in self.messages if m.id==ident),None)
        if not message: return
        tag='lightbox_'+str(ident)
        self.history.tag_add(tag,mark,f'{mark}+1c')
        bind_text_action(self.history,tag,'<Button-1>',lambda e:self.open_image_message(message))

    def open_comments(self, message):
        if self.demo or self.active is None or message.comments_count is None:
            return
        backend, account, peer = self.service.backend, self.ui_account, self.active
        def loaded(thread):
            if account != self.ui_account or backend is not self.service.backend:
                return
            from .interface_windows import LinkedChatWindow
            window = LinkedChatWindow(self, account, thread['peer'], thread=thread)
            window.window.title(f'💬 #{message.id} · {self.root.title()}')
            if not hasattr(self, '_chat_windows'):
                self._chat_windows = []
            self._chat_windows.append(window)
        self.call(backend.discussion_message(peer, message.id), loaded, tr('Cargando mensajes...'))

    def reply_message(self,message):
        from .chat_capabilities import chat_capabilities
        if not self.demo and not chat_capabilities(self).allows_message('reply',message):return
        if not hasattr(self,'reply_drafts'): self.reply_drafts={}
        self.reply_drafts[(self.ui_account,self.active)]=message.id
        self.remember_replies({(self.ui_account,self.active,message.id):message})
        self.update_reply(); self.editor.focus_set()
    def message_at(self,event):
        index=self.history.index(f'@{event.x},{event.y}')
        for tag in self.history.tag_names(index):
            if tag.startswith('msg_'): return next((m for m in self.messages if m.id==int(tag[4:])),None)
        return None
    def classic_double(self,event):
        message=self.message_at(event)
        if message: self.quick_react(message); return 'break'
    def classic_release(self,event):
        start=getattr(self,'_classic_press',None)
        if start and event.x-start[0]<-65 and abs(start[1]-event.y)<55:
            message=self.message_at(event)
            if message: self.reply_message(message); return 'break'
    def jump_loaded(self,ident):
        if getattr(self,'_canvas_chat_view',self.preferences.values['bubbles']): return self.bubble_view.jump(ident)
        mark=f'message_{ident}'
        if mark in self.history.mark_names(): self.history.see(mark); return True
        return False
    def jump_message(self,ident,peer=None):
        peer=self.active if peer is None else peer
        if getattr(self, '_chat_only', False) and peer != self._pinned_peer:
            from .interface_windows import navigate_from_chat_window
            navigate_from_chat_window(self, peer=peer, message=ident)
            return
        if peer==self.active and self.jump_loaded(ident): return
        if self.busy or self.demo: return
        account,backend=self.ui_account,self.service.backend
        async def fetch():
            entity=await backend.client.get_entity(peer)
            from telethon.utils import get_display_name
            return await backend.message_context(peer,ident),get_display_name(entity),entity
        def loaded(data):
            if account!=self.ui_account: return
            if self.active is not None:
                self.save_custom_draft(); self.drafts[self.active]=(self.editor.get('1.0','end-1c'),self.attachment)
            from .backend import Chat
            if not any(c.id==peer for c in self.chats): self.chats.append(Chat(peer,data[1],entity=data[2]))
            self.active=peer; self.messages=data[0]; self._jumped=True
            self.restore_draft(); self.render_messages(False); self.jump_loaded(ident)
            self.compact_conversation=True; self.adapt_chat_layout()
        self.call(fetch(),loaded,tr('Loading...'))

    def chat_tools_menu(self):
        from .app_dialogs import popup_menu
        from .chat_menus import in_chat_entries, list_entries, select_messages
        entries=[(tr('Close'), self.close)] if getattr(self, '_chat_only', False) else [
                 (tr('Open chat in new window'), self.open_chat_in_new_window),
                 # 1.5.2, in-chat exclusive: back to "choose a chat".
                 (tr('Close chat'), lambda: self.close_active_chat())]
        entries+=in_chat_entries(self,self.active)
        # In-chat exclusive (1.4): start message selection directly.
        entries.append((tr('Select messages'),lambda:select_messages(self)))
        chat=next((c for c in self.chats if c.id==self.active),None)
        if chat is not None and not self.demo and not getattr(self,'_chat_only',False):
            # 1.4: the chat-list tools are available here too.
            entries+=[None,*list_entries(self,self.active,chat,include_pin=False)]
        popup_menu(self.root,entries,anchor=self.pinned_button)

    def close_active_chat(self):
        """Close the open chat in this window (1.5.2): its draft is kept and
        the conversation goes back to "choose a chat"."""
        if getattr(self, '_chat_only', False):
            self.close(); return
        peer=self.active
        if peer is None or self.busy: return
        self.save_custom_draft()
        if hasattr(self,'draft_manager'):
            self.draft_manager.snapshot(); self.draft_manager.persist_async()
        self.drafts[peer]=(self.editor.get('1.0','end-1c'),self.attachment)
        if self.messages:
            cache=self.__dict__.setdefault('_history_cache',{})
            cache[(self.ui_account,peer)]=list(self.messages)[-200:]
        self.active=None;self.messages=[];self._history_key,self._history_changes=None,[]
        self.title.set(tr('Elige un chat'))
        self.editor.delete('1.0','end');self.attachment=None;self.update_attachment()
        self.cancel_reply()
        self.render_messages(False)
        widget=getattr(self,'chat_list',None)
        if widget is not None and widget.winfo_exists() and widget.exists(str(peer)):
            widget.selection_remove(str(peer))
        self.compact_conversation=False
        self.adapt_chat_layout()

    def chat_history_action(self,peer,clear=False):
        if self.busy or self.demo: return
        from .app_dialogs import popup_menu
        account,backend=self.ui_account,self.service.backend
        chat=next((c for c in self.chats if c.id==peer),None)
        name=chat.name if chat else str(peer)
        def loaded(info):
            if account!=self.ui_account: return
            def apply(everyone):
                if self.busy or account!=self.ui_account: return
                scope=tr('For everyone') if everyone else tr('Only me')
                title=tr('Clear history') if clear else tr('Delete chat')
                detail=tr('Keep the chat and remove its messages.') if clear else (
                    tr('Delete the entire group or channel for all participants.') if everyone and not info['person'] else
                    tr('Delete this chat from your account? For groups and channels this leaves the conversation.') if not everyone else tr('Delete this chat for both participants.'))
                if not messagebox.askyesno(title,f'{name}\n{scope}\n\n{detail}',parent=self.root): return
                def done(cutoff):
                    if account!=self.ui_account: return
                    for key in list(self.reply_cache):
                        if key[:2]==(account,peer): self.reply_cache.pop(key,None)
                    if self.active==peer:
                        if clear: self.messages=[m for m in self.messages if m.id>cutoff]
                        else:
                            self.active=None;self.messages=[];self.title.set(tr('Elige un chat'))
                            self.editor.delete('1.0','end');self.attachment=None;self.update_attachment()
                            self.cancel_reply()
                        self.render_messages(False)
                    if not clear:
                        self.chats=[c for c in self.chats if c.id!=peer]
                        self.drafts.pop(peer,None)
                        for mapping in (self.rich_drafts,self.format_drafts,getattr(self,'reply_drafts',{})):
                            mapping.pop((account,peer),None)
                    if not clear and getattr(self, '_chat_only', False):
                        self.close()
                        return
                    self.refresh()
                operation=backend.clear_chat(peer,everyone) if clear else backend.delete_chat(peer,everyone)
                self.call(operation,done,tr('Saving...'))
            allowed_self=info['clear_self'] if clear else True
            allowed_all=info['clear_all'] if clear else info['delete_all']
            entries=[]
            if allowed_self:entries.append((tr('Only me'),lambda:apply(False)))
            if allowed_all:entries.append((tr('For everyone'),lambda:apply(True)))
            if entries:popup_menu(self.root,entries)
        self.call(backend.history_permissions(peer),loaded,tr('Loading...'))

    def schedule_message(self):
        if self.busy or self.demo or self.active is None: return
        from .chat_capabilities import chat_capabilities
        if not chat_capabilities(self).allows('schedule'):return
        from datetime import datetime,timedelta
        from .messaging_features import parse_schedule
        account,peer=self.ui_account,self.active
        window,frame=self.dialog('Schedule message','480x220')
        ttk.Label(frame,text=tr('Local date and time (YYYY-MM-DD HH:MM)'),wraplength=420).pack(fill='x')
        value=tk.StringVar(value=(datetime.now()+timedelta(hours=1)).strftime('%Y-%m-%d %H:%M'))
        ttk.Entry(frame,textvariable=value).pack(fill='x',pady=8)
        def submit():
            if self.busy or (account,peer)!=(self.ui_account,self.active): return
            try:when=parse_schedule(value.get())
            except ValueError as exc:messagebox.showerror(tr('Schedule message'),str(exc),parent=window);return
            window.destroy();self.send(schedule=when)
        ttk.Button(frame,text=tr('Schedule message'),command=submit).pack(anchor='e',pady=6)

    def scheduled_messages(self):
        if self.busy or self.demo or self.active is None: return
        account,peer,backend=self.ui_account,self.active,self.service.backend
        window,frame=self.dialog('Scheduled messages','560x440')
        listing=tk.Listbox(frame,exportselection=False);listing.pack(side='left',fill='both',expand=True)
        bar=ttk.Scrollbar(frame,command=listing.yview);bar.pack(side='right',fill='y');listing.configure(yscrollcommand=bar.set)
        records=[]
        def current():return window.winfo_exists() and account==self.ui_account
        def loaded(items):
            if not current():return
            records[:]=items;listing.delete(0,'end')
            for item in items:listing.insert('end',item.date.astimezone().strftime('%Y-%m-%d %H:%M')+' · '+(item.raw_text or tr('Archivo adjunto')).replace('\n',' ')[:100])
        def refresh():
            if current():self.call(backend.scheduled_history(peer),loaded,tr('Loading...'))
        def actions(event=None):
            if self.busy or not current():return
            if event:
                index=listing.nearest(event.y);listing.selection_clear(0,'end');listing.selection_set(index)
            selection=listing.curselection()
            if not selection or selection[0]>=len(records):return
            ident=records[selection[0]].id
            from .app_dialogs import popup_menu
            def apply(send_now):
                if self.busy or not current():return
                label=tr('Send now') if send_now else tr('Delete message')
                if not messagebox.askyesno(tr('Scheduled messages'),label+'?',parent=window):return
                self.call(backend.change_scheduled(peer,ident,send_now),lambda _:refresh(),tr('Saving...'))
            from .app_dialogs import event_action
            return event_action(listing, lambda:popup_menu(window,[(tr('Send now'),lambda:apply(True)),(tr('Delete message'),lambda:apply(False))],event=event))
        listing.bind('<Double-Button-1>',actions);listing.bind('<Button-3>',actions);listing.bind('<Return>',lambda _:actions())
        refresh()

    def saved_messages(self):
        if self.busy or self.demo: return
        account,backend=self.ui_account,self.service.backend
        self.call(backend.resolve_chat('me'),lambda chat:self.open_resolved(chat) if account==self.ui_account else None,tr('Loading...'))

    def copy_message_text(self,message):
        text=message.raw_text if message.raw_text is not None else message.text
        self.root.clipboard_clear(); self.root.clipboard_append(text)

    def save_message_to_self(self,message,backend,account,peer):
        if self.busy or account!=self.ui_account: return
        from .chat_capabilities import chat_capabilities
        if not chat_capabilities(self,peer).allows_message('forward',message):return
        if not messagebox.askyesno(tr('Saved Messages'),tr('Save to Saved Messages')+'?',parent=self.root): return
        self.call(backend.forward_message(peer,message.id,'me'),lambda _:self.status.set(tr('Saved Messages')),tr('Saving...'))

    def quick_react(self,message):
        if getattr(self,'selection_kind',None) or getattr(self,'_preview_only',False):return
        if self.active is None or not any(m.id==message.id for m in self.messages):return
        self.send_reaction(message,self.preferences.values['quick_reaction'])
    def send_reaction(self,message,value):
        if self.busy or self.demo: return
        from .chat_capabilities import chat_capabilities
        if not chat_capabilities(self).allows_message('react',message):return
        account,peer,backend=self.ui_account,self.active,self.service.backend
        def done(updated):
            if (account,peer)!=(self.ui_account,self.active): return
            self.messages=[updated if m.id==updated.id else m for m in self.messages]; self.render_messages(False)
        self.call(backend.react(peer,message.id,value),done,tr('Saving...'))
    def reaction_picker(self,message=None):
        if self.busy or self.demo: return
        if message is not None and self.active is None: return
        from .app_dialogs import popover
        from .messaging_features import reaction_allowed
        account,peer,backend=self.ui_account,self.active,self.service.backend
        window,frame=popover(self.root,tr('Reactions'),anchor=self.pinned_button,size=(370,420))
        self.popups.append(window)
        status=tk.StringVar(value=tr('Loading...'))
        ttk.Label(frame,textvariable=status,wraplength=330).pack(fill='x')
        standard=ttk.Frame(frame); standard.pack(fill='x',pady=4)
        packs=Choice(frame,values=[tr('Custom emoji')],width=24); packs.current(0); packs.pack(fill='x')
        grid=scrollable(frame)
        state={'policy':None,'packs':[],'docs':[],'page':0,'epoch':0}
        def current():
            return window.winfo_exists() and (account,peer)==(self.ui_account,self.active)
        def select(value):
            if self.busy or not current(): return
            if message is None:
                self.preferences.save({'quick_reaction':value})
                # Also Telegram's default reaction, as in the mobile app.
                self.worker.submit(backend.set_default_reaction(value),lambda _:None,lambda _:None)
            else: self.send_reaction(message,value)
            window.destroy()
        def show_docs(values,page=0):
            if not current(): return
            for child in grid.winfo_children(): child.destroy()
            state['docs'],state['page']=values,page
            for index,value in enumerate(values[page*48:(page+1)*48]):
                button=ttk.Button(grid,text='◇',width=4,command=lambda v=value:select(v))
                button.grid(row=index//6,column=index%6,padx=1,pady=2)
                self.label_emoji(button,value,account,backend)
            row=ttk.Frame(grid); row.grid(row=9,column=0,columnspan=6,sticky='ew')
            if page: ttk.Button(row,text='‹',width=3,command=lambda:show_docs(values,page-1)).pack(side='left')
            if (page+1)*48<len(values): ttk.Button(row,text='›',width=3,command=lambda:show_docs(values,page+1)).pack(side='right')
        def loaded(data):
            if not current(): return
            policy,values,recent=data; state['policy']=policy
            status.set(tr('Reactions') if policy['premium'] else tr('Custom reactions may require Telegram Premium.'))
            # Keep the standard palette compact; native overflow handles the rest.
            for i,value in enumerate(values[:12]):
                ttk.Button(standard,text=value,width=4,command=lambda v=value:select(v)).grid(row=i//6,column=i%6,pady=1)
            if len(values)>12:
                from .app_dialogs import popup_menu
                more=ttk.Button(standard,text='⋯',width=4)
                more.configure(command=lambda:popup_menu(window,[(v,lambda value=v:select(value)) for v in values[12:]],anchor=more))
                more.grid(row=2,column=0)
            show_docs(recent)
            if policy['premium'] and (policy['allowed'] is None and policy['custom'] or policy['allowed']):
                def packs_loaded(records):
                    if not current(): return
                    state['packs']=records; packs.configure(values=[tr('Custom emoji')]+[r.title for r in records]); packs.current(0)
                self.worker.submit(backend.sticker_packs(True),packs_loaded,lambda _:status.set(tr('Search failed.')) if current() else None)
            state['recent']=recent
        def choose_pack(_=None):
            if not current() or state['policy'] is None: return
            index=packs.current(); state['epoch']+=1; epoch=state['epoch']
            if index==0: show_docs(state.get('recent',[])); return
            if index>len(state['packs']): return
            status.set(tr('Loading...'))
            def docs_loaded(docs):
                if not current() or epoch!=state['epoch']: return
                values=[d.id for d in docs if reaction_allowed(d.id,state['policy'])]
                show_docs(values); status.set(tr('Reactions') if values else tr('This reaction is unavailable for your account or this chat.'))
            self.worker.submit(backend.sticker_documents(state['packs'][index-1]),docs_loaded,
                               lambda _:status.set(tr('Search failed.')) if current() else None)
        packs.bind('<<ComboboxSelected>>',choose_pack)
        self.worker.submit(backend.reaction_choices(peer,message.id if message else None),loaded,
                           lambda exc:(window.destroy(),self.show_error(exc)) if current() else None)

    def pin_message_dialog(self,message):
        if self.demo or self.busy: return
        account,peer,backend=self.ui_account,self.active,self.service.backend
        window,frame=self.dialog('Pinned messages','420x250')
        both=tk.BooleanVar(value=False)
        ttk.Checkbutton(frame,text=tr('For both participants'),variable=both).pack(anchor='w')
        def apply(unpin):
            def done(_):
                if window.winfo_exists(): window.destroy()
                if (account,peer)==(self.ui_account,self.active): self.pinned_dialog()
            self.call(backend.pin_message(peer,message.id,unpin,both.get()),done,tr('Saving...'))
        ttk.Button(frame,text=tr('Pin message'),command=lambda:apply(False)).pack(fill='x',pady=8)
        ttk.Button(frame,text=tr('Unpin message'),command=lambda:apply(True)).pack(fill='x')
    def pinned_dialog(self):
        if self.demo or self.busy or self.active is None: return
        account,peer,backend=self.ui_account,self.active,self.service.backend
        def loaded(items):
            if (account,peer)!=(self.ui_account,self.active): return
            window,outer=self.dialog('Pinned messages','560x460'); frame=scrollable(outer)
            for message in items:
                ttk.Button(frame,text=(message.raw_text or message.text)[:100],command=lambda m=message:(window.destroy(),self.jump_message(m.id,peer))).pack(fill='x',pady=4)
            if not items: ttk.Label(frame,text=tr('No pinned messages')).pack()
        self.call(backend.pinned_messages(peer),loaded,tr('Loading...'))

    def choose_wallpaper(self,global_default=False):
        from .customization_sync import sync_enabled, mark_wallpaper_scope, label
        if self.busy or (not global_default and self.active is None): return
        account,peer=self.ui_account,self.active
        backend=None if self.demo else self.service.backend
        chat=next((c for c in self.chats if c.id==peer),None)
        private=bool(chat and chat.kind=='user')
        window,frame=self.dialog('Chat background','540x360')
        scope=Choice(frame,values=[tr('All chats in this app')] if global_default else ([tr('Only me'),tr('For both participants')] if private and sync_enabled(self.preferences) else [tr('Only me')])); scope.current(0); scope.pack(fill='x',pady=8)
        ttk.Label(frame,text=tr('Preview before applying. Telegram may require Premium for both participants.'),wraplength=460).pack(pady=10)
        if not sync_enabled(self.preferences) or global_default or not private:
            ttk.Label(frame,text=label('This background is local to this app.', 'Este fondo es local a esta app.'),wraplength=460).pack(fill='x')
        def persist(path):
            key=f'{account}:default' if global_default else f'{account}:{peer}'
            updated=dict(self.wallpapers)
            if path is None: updated[key]=''
            else:
                folder=self.preferences.path.parent/'wallpapers' if not self.demo else self.preview_dir
                folder.mkdir(parents=True,exist_ok=True)
                target=folder/(uuid.uuid4().hex+'.jpg')
                import shutil
                shutil.copyfile(path,target); updated[key]=str(target)
            if not self.demo: write_json(self.wallpapers_file,updated)
            if not global_default:
                mark_wallpaper_scope(self,account,peer,self.demo or not private or not sync_enabled(self.preferences))
            from .interface_windows import share_view_value
            share_view_value(self, 'wallpapers', updated)
            if window.winfo_exists(): window.destroy()
            if account==self.ui_account: self.refresh_wallpaper()
        def apply(path):
            if self.busy or account!=self.ui_account: return
            both=scope.current()==1 and not global_default
            if global_default or self.demo or not private or not sync_enabled(self.preferences): persist(path); return
            if not messagebox.askyesno(tr('Chat background'),tr('For both participants') if both else tr('Only me'),parent=window): return
            self.call(backend.apply_wallpaper(peer,path,both),lambda _:persist(path),tr('Saving...'))
        def choose():
            path=filedialog.askopenfilename(parent=window,filetypes=[(tr('Images'),'*.png *.jpg *.jpeg')])
            if not path: return
            from .image_tools import image_editor
            try: image_editor(window,path,self.preview_dir/(uuid.uuid4().hex+'.jpg'),apply,wallpaper=True)
            except (OSError,ValueError,ImportError) as exc: self.show_error(exc)
        ttk.Button(frame,text=tr('Choose file'),command=choose).pack(fill='x',pady=8)
        if self.preferences.values.get('telegram_backgrounds',False):
            from .telegram_wallpapers import open_gallery
            ttk.Button(frame,text=tr('Telegram backgrounds'),command=lambda:open_gallery(self,on_choose=apply)).pack(fill='x',pady=8)
        ttk.Button(frame,text=tr('Remove background'),command=lambda:apply(None)).pack(fill='x',pady=8)
        if not global_default:
            def use_default():
                if self.busy or account!=self.ui_account: return
                def done(_):
                    key=f'{account}:{peer}'; updated=dict(self.wallpapers); updated.pop(key,None)
                    if not sync_enabled(self.preferences):
                        from .telegram_wallpapers import selected_default
                        updated[key]=selected_default(self,account) or ''
                    mark_wallpaper_scope(self,account,peer,not sync_enabled(self.preferences))
                    if not self.demo: write_json(self.wallpapers_file,updated)
                    from .interface_windows import share_view_value
                    share_view_value(self, 'wallpapers', updated)
                    if window.winfo_exists(): window.destroy()
                    self.refresh_wallpaper()
                if private and not self.demo and sync_enabled(self.preferences): self.call(backend.apply_wallpaper(peer,None,False),done,tr('Saving...'))
                else: done(None)
            ttk.Button(frame,text=tr('Use default background'),command=use_default).pack(fill='x')

    def refresh_wallpaper(self):
        if not hasattr(self,'history_canvas') or not self.history_canvas.winfo_exists(): return
        account,peer=self.ui_account,self.active
        self.wallpaper_path=None; self.history_canvas.delete('wallpaper')
        explicit=self.wallpapers.get(f'{account}:{peer}',None)
        from .telegram_wallpapers import selected_default
        from .customization_sync import local_theme_wallpaper, server_chat_appearance
        from .themes import resolve_theme
        default=selected_default(self,account)
        def apply(path):
            if (account,peer)!=(self.ui_account,self.active): return
            self.wallpaper_path=Path(path) if path and Path(path).is_file() else None
            if hasattr(self,'bubble_view') and self.bubble_view.winfo_exists(): self.update_modern_view(False)
        if explicit is not None: apply(explicit); return
        has_theme, theme_path=local_theme_wallpaper(self)
        if has_theme: apply(theme_path or default); return
        if self.demo or peer is None: apply(default); return
        backend=self.service.backend
        async def fetch():
            return await server_chat_appearance(backend,peer,self.preview_dir/f'{account}-themes',
                resolve_theme(self.preferences.values.get('theme','dark'))=='dark')
        def loaded(result):
            if (account,peer)!=(self.ui_account,self.active): return
            self._active_chat_theme=((account,peer),result)
            apply(result.get('wallpaper') or default)
        self.worker.submit(fetch(),loaded,lambda _:apply(default))
    def draw_bubble_wallpaper(self,canvas):
        from .interface_background import request_chat_background
        path=getattr(self,'wallpaper_path',None)
        if not path or not Path(path).is_file():
            canvas._wallpaper_requested=None
            painter=getattr(self,'interface_background',None)
            if painter is not None:painter.paint_canvas(canvas)
            return
        try:
            stat=Path(path).stat();key=('chat',str(path),stat.st_mtime_ns,max(1,canvas.winfo_width()),max(1,canvas.winfo_height()))
            request_chat_background(self,canvas,key)
        except (ImportError,OSError,ValueError): pass

    def preview_photo_attachment(self,path,accepted):
        # 1.4: photos → built-in editor (or the system editor); every other
        # file → a preview card before it is attached. See attachment_preview.
        from .attachment_preview import route_attachment
        route_attachment(self,path,accepted)

    def preview_attachment(self,path,accepted):
        """'Preview / edit': photo editor, or the file's preview card."""
        from .attachment_preview import route_attachment
        route_attachment(self,path,accepted,interactive=True)

    def preview_current_attachment(self):
        from .attachments import paths_in
        paths=paths_in(self.attachment)
        if self.busy or not paths:return
        if len(paths)>1:return self.attachment_manager()
        account,peer,before=self.ui_account,self.active,self.attachment
        def accepted(value):
            if (account,peer)==(self.ui_account,self.active) and self.attachment==before and not self.busy:
                self.attachment=value;self.update_attachment()
        self.preview_attachment(paths[0],accepted)

    def native_emoji(self):
        self.editor.focus_set()
        try:
            from .native_emoji import open_palette
            open_palette()
        except (OSError,RuntimeError,ImportError,AttributeError) as exc: self.show_error(exc)

    def privacy_dialog(self):
        if self.busy or self.demo: return
        from .messaging_features import PRIVACY_KEYS,privacy_base
        from .chat_capabilities import account_premium
        account,backend=self.ui_account,self.service.backend
        window,outer=self.dialog('Privacy','610x650'); frame=scrollable(outer)
        def edit(label):
            if label == 'Voice messages' and not account_premium(self):return
            def loaded(snapshot):
                if not window.winfo_exists() or account!=self.ui_account: return
                dialog,body=self.dialog(label,'550x550')
                base=privacy_base(snapshot.rules)
                choices=['Everyone','Contacts only','Nobody']; picker=Choice(body,values=[tr(s) for s in choices]); picker.current(choices.index(base) if base in choices else -1); picker.pack(fill='x',pady=8)
                ttk.Label(body,text=tr('Other exceptions are preserved.'),wraplength=470).pack()
                exceptions={'allow':None,'deny':None}
                def contacts(kind):
                    def ready(items):
                        if not dialog.winfo_exists(): return
                        pop,inner=self.dialog('Contacts','500x500'); listing=CheckList(inner); listing.pack(fill='both',expand=True)
                        name='PrivacyValueAllowUsers' if kind=='allow' else 'PrivacyValueDisallowUsers'
                        previous={u for r in snapshot.rules if type(r).__name__==name for u in r.users}
                        selected=set(exceptions[kind] if exceptions[kind] is not None else previous)
                        for index,item in enumerate(items):
                            listing.insert('end',(getattr(item,'first_name','') or '')+' '+(getattr(item,'last_name','') or ''))
                            if item.id in selected: listing.toggle(index)
                        known={item.id for item in items}
                        def save():
                            exceptions[kind]=list((selected-known)|{items[i].id for i in listing.curselection()}); pop.destroy()
                        ttk.Button(inner,text=tr('Save'),command=save).pack(fill='x')
                    self.call(backend.contacts(),ready,tr('Loading...'))
                for label2,kind in [('Always allow','allow'),('Never allow','deny')]:
                    ttk.Button(body,text=tr(label2),command=lambda k=kind:contacts(k)).pack(fill='x',pady=5)
                def save():
                    if self.busy or account!=self.ui_account or picker.current()<0: return
                    if label == 'Voice messages' and not account_premium(self):return
                    def done(_): dialog.destroy(); self.status.set(tr('Settings saved.'))
                    self.call(backend.save_privacy(label,choices[picker.current()],snapshot,exceptions['allow'],exceptions['deny']),done,tr('Saving...'))
                ttk.Button(body,text=tr('Save'),command=save).pack(fill='x',pady=10)
            self.call(backend.privacy(label),loaded,tr('Loading...'))
        for label in PRIVACY_KEYS:
            if label == 'Voice messages' and not account_premium(self):continue
            ttk.Button(frame,text=tr(label),command=lambda name=label:edit(name)).pack(fill='x',pady=4)
        def global_settings():
            async def fetch():
                from .advanced_messaging import config_values
                settings, config = await asyncio.gather(backend.global_privacy(), backend.app_config(), return_exceptions=True)
                if isinstance(settings, BaseException):raise settings
                return settings, {} if isinstance(config, BaseException) else config_values(config)
            def loaded(snapshot):
                if not window.winfo_exists() or account!=self.ui_account: return
                settings, config = snapshot
                top,body=self.dialog('Privacy','560x380'); values={}
                labels=privacy_global_fields(account_premium(self),config,settings)
                for key,label in labels.items():
                    values[key]=tk.BooleanVar(value=bool(getattr(settings,key,False)))
                    ttk.Checkbutton(body,text=tr(label),variable=values[key]).pack(anchor='w',pady=9)
                def save():
                    if account!=self.ui_account or self.busy: return
                    allowed=privacy_global_fields(account_premium(self),config,settings)
                    changes={k:v.get() for k,v in values.items() if k in allowed and v.get()!=bool(getattr(settings,k,False))}
                    if not changes:top.destroy();return
                    self.call(backend.save_global_privacy(changes),lambda _:top.destroy(),tr('Saving...'))
                ttk.Button(body,text=tr('Save'),command=save).pack(fill='x')
            self.call(fetch(),loaded,tr('Loading...'))
        ttk.Button(frame,text=tr('Global privacy'),command=global_settings).pack(fill='x',pady=10)

    def presence_tick(self):
        if self.closed or self.closing: return
        if not self.demo:
            from .notifications import foreground_view
            view = foreground_view(self)
            online = view is not None and view.stage == 'ready'
            now=time.monotonic()
            for account,service in list(self.service.services.items()):
                backend=getattr(service,'backend',None)
                if backend is None: continue
                recovery=getattr(service,'recovery',None)
                if recovery is not None and (getattr(recovery,'auth_required',False) or getattr(recovery,'state','online')!='online'):
                    # Offline/reconnecting/revoked sessions cannot update presence;
                    # the request would only fail (hundreds of logged errors on
                    # Windows). Forget the last value so it is sent on recovery.
                    self.presence_last.pop(account,None)
                    continue
                desired=online and account==view.ui_account
                previous=self.presence_last.get(account)
                if previous is None or previous[0]!=desired or now-previous[1]>45:
                    self.presence_last[account]=(desired,now)
                    def presence_failed(exc,visible=account==getattr(view,'ui_account',None)):
                        # Retried after the usual 45 s, not every 5 s tick.
                        # Background accounts failing must not overwrite the
                        # status line of the account the user is looking at.
                        if visible:self.status.set(tr('Presence update failed.'))
                    self.worker.submit(backend.presence(desired),lambda _:None,presence_failed)
        self.root.after(5000,self.presence_tick)
    def typing_changed(self,event=None):
        if self.demo or self.active is None or self.stage!='ready': return
        if not self.editor.get('1.0','end-1c').strip(): self.stop_typing(); return
        account,peer,backend=self.ui_account,self.active,self.service.backend
        key=(account,peer); now=time.monotonic()
        if now-self.typing_last.get(key,0)>4:
            self.typing_last[key]=now; self._typing_context=(account,peer,backend)
            self.worker.submit(backend.typing(peer),lambda _:None,lambda _:None)
        if self._typing_stop: self.root.after_cancel(self._typing_stop)
        self._typing_stop=self.root.after(5000,self.stop_typing)
    def stop_typing(self):
        if self._typing_stop: self.root.after_cancel(self._typing_stop); self._typing_stop=None
        context=getattr(self,'_typing_context',None); self._typing_context=None
        if context:
            _,peer,backend=context
            self.worker.submit(backend.typing(peer,False),lambda _:None,lambda _:None)

    def preview_chat(self,peer):
        if self.busy or self.demo: return
        account,backend=self.ui_account,self.service.backend
        async def fetch():
            # History, header and avatar together; none of them marks as read.
            async def header():
                try:return await backend.chat_header(peer)
                except Exception:return None
            async def avatar():
                try:return await backend.avatar(peer,self.preview_dir/f'{account}-{peer}-header.jpg')
                except Exception:return None
            return await asyncio.gather(backend.history(peer),header(),avatar())
        def loaded(result):
            messages,info,avatar_path=result
            if account!=self.ui_account: return
            window,frame=self.dialog('Preview chat — unread','650x660')
            # 1.4: same header as an open chat (avatar · name · activity · status emoji).
            top=ttk.Frame(frame);top.pack(fill='x',pady=(0,6))
            picture=ttk.Label(top);picture.pack(side='left',padx=(0,8))
            names=ttk.Frame(top);names.pack(side='left',fill='x',expand=True)
            chat=next((c for c in self.chats if c.id==peer),None)
            title=(info or {}).get('name') or (chat.name if chat else str(peer))
            ttk.Label(names,text=self.text_display(title,True),style='Title.TLabel').pack(anchor='w')
            if info:
                from .telegram_actions import peer_activity
                status=peer_activity(info['activity_entity'],self.preferences.values.get('show_seconds',False)) if info.get('activity_entity') is not None else info['status']
                ttk.Label(names,text=status,style='Muted.TLabel').pack(anchor='w')
            emoji=ttk.Label(top);emoji.pack(side='right')
            def alive():return window.winfo_exists() and account==self.ui_account
            if avatar_path:
                def painted(photo):
                    if alive():picture.image=photo;picture.configure(image=photo or '')
                self.request_photo(avatar_path,(40,40),painted,owner=picture,valid=alive)
            if info and info.get('emoji'):self.label_emoji(emoji,info['emoji'],account,backend)
            history=tk.Text(frame,wrap='word',height=20); history.pack(fill='both',expand=True)
            bar=ttk.Scrollbar(frame,command=history.yview); bar.pack(side='right',fill='y'); history.configure(yscrollcommand=bar.set)
            for message in messages: history.insert('end',f'{message.sender} · {message_time(message,self.preferences.values)}\n{message.text}\n\n')
            history.configure(state='disabled'); history.see('end')
        # Pure history fetch: never select/open the chat or call mark_read.
        self.call(fetch(),loaded,tr('Loading...'))

    def cancel_global_search(self):
        self._search_token=object()
        timer=getattr(self,'_search_timer',None)
        self._search_timer=None
        if timer:
            try:self.root.after_cancel(timer)
            except tk.TclError:pass
        job=getattr(self,'_search_job',None)
        self._search_job=None
        if job is not None:job.cancel()

    def schedule_global_search(self):
        self.cancel_global_search()
        self.search_offset=None
        if hasattr(self,'search_more'): self.search_more.pack_forget()
        self._search_timer=self.root.after(500,self.run_global_search)
    def run_global_search(self,more=False):
        query=self.search.get().strip()
        if not hasattr(self,'global_results'):
            self.cancel_global_search();return
        if len(query)<2 or self.demo:
            self.cancel_global_search()
            self.global_results.pack_forget(); self.search_more.pack_forget(); self.search_offset=None; return
        account,backend=self.ui_account,self.service.backend
        widget=self.global_results
        if more and self.search_offset is None: return
        # Repeated clicks on More share one page request instead of racing cursors.
        if more and getattr(self,'_search_job',None) is not None:return
        self.cancel_global_search()
        token=self._search_token
        offset=self.search_offset if more else None
        async def fetch():
            async def results():
                if more:return [],await backend.global_messages(query,offset)
                # Independent RPCs run together. A failed public-chat lookup must
                # not hide successful message matches (and vice versa).
                public,messages=await asyncio.gather(backend.search_public(query),backend.global_messages(query,offset),return_exceptions=True)
                if isinstance(public,BaseException) and isinstance(messages,BaseException):raise messages
                return ([] if isinstance(public,BaseException) else public),(([],None) if isinstance(messages,BaseException) else messages)
            return await asyncio.wait_for(results(),25)
        def current():
            return (token is self._search_token and account==self.ui_account
                    and backend is self.service.backend and widget is self.global_results
                    and not getattr(self,'closed',False) and not getattr(self,'closing',False)
                    and widget.winfo_exists() and query==self.search.get().strip())
        def loaded(result):
            if not current(): return
            self._search_job=None
            if not more: widget.delete(*widget.get_children()); self.search_records={}
            public,(messages,cursor)=result
            self.search_offset=cursor
            for chat in public:
                key='p'+str(chat.id); self.search_records[key]=('chat',chat)
                widget.insert('','end',iid=key,text=chat.name)
            for index,(peer,name,message) in enumerate(messages):
                key=f'm{peer}:{message.id}'
                if key in self.search_records: continue
                self.search_records[key]=('message',(peer,message.id))
                widget.insert('','end',iid=key,text=name+' · '+(message.raw_text or message.text).replace('\n',' ')[:90])
            widget.pack(fill='both',expand=True,pady=5)
            if cursor: self.search_more.pack(fill='x')
            else: self.search_more.pack_forget()
        def failed(exc):
            if current():
                self._search_job=None
                self.status.set(tr('Search failed.'))
        self._search_job=self.worker.submit(fetch(),loaded,failed)
    def open_search_result(self):
        selected=self.global_results.selection()
        if not selected or self.busy: return
        value=self.search_records.get(selected[0])
        if not value: return
        kind,data=value
        if kind=='message': self.jump_message(data[1],data[0]); return
        if not any(c.id==data.id for c in self.chats): self.chats.append(data)
        self.search.set(''); self.render_chats(); self.chat_list.selection_set(str(data.id)); self.choose_chat()

    def photos_mosaic(self,peer=None):
        peer=self.active if peer is None else peer
        if self.demo or self.busy or peer is None: return
        account,backend=self.ui_account,self.service.backend
        window,outer=self.dialog('Photos','720x600'); frame=scrollable(outer)
        from .scrolling import FlowFrame
        grid=FlowFrame(frame); grid.pack(fill='x'); records=[]
        def fetch():
            if self.busy: return
            def loaded(items):
                if not window.winfo_exists() or account!=self.ui_account: return
                records.extend(items)
                for item in items:
                    button=ttk.Button(grid,text='…',width=15,command=lambda m=item:self.open_image_message(m,peer) if account==self.ui_account else None); button.pack(side='left',padx=3,pady=3)
                    async def download(m=item): return await backend.download_media(m.media,self.preview_dir/f'{account}-{peer}-{m.id}-mosaic.jpg',thumbnail=True)
                    def thumb(path,b=button):
                        if b.winfo_exists() and path:
                            b.image=self.load_photo(path,(150,150)); b.configure(image=b.image or '',text='')
                    self.fetch_art((account,peer,item.id,'mosaic'),download,thumb)
            self.call(backend.search_messages(peer,'','photos',records[-1].id if records else 0),loaded,tr('Loading...'))
        ttk.Button(frame,text=tr('More'),command=fetch).pack(fill='x'); fetch()

    def modern_update(self,account,kind,payload):
        if account!=self.ui_account or self.stage!='ready': return
        if kind=='accents':
            peer=payload; backend=self.service.backend
            def loaded(style):
                if account!=self.ui_account: return
                for message in self.messages:
                    if message.sender_id==peer: message.sender_color,message.reply_icon_id=style[:2]
                for key,message in self.reply_cache.items():
                    if key[0]==account and message and message.sender_id==peer: message.sender_color,message.reply_icon_id=style[:2]
                for chat in self.chats:
                    if chat.id==peer: chat.emoji_status_id=style[2]
                self.render_chats(); self.render_messages(False)
                if peer==self.active: self.refresh_header()
            self.worker.submit(backend.sender_style(peer),loaded,lambda _:None)
        elif kind=='activity':
            peer,status=payload
            from .chat_activity import remember_typing, schedule_refresh, TYPING_SECONDS
            remember_typing(self,peer,status)
            schedule_refresh(self)
            if status:self.root.after(TYPING_SECONDS*1000+100,lambda:schedule_refresh(self))  # Clear the ··· mark.
            if peer==self.active:
                if status is None: self.refresh_header()
                else:
                    self.activity.set(status)
                    if getattr(self,'_activity_timer',None): self.root.after_cancel(self._activity_timer)
                    self._activity_timer=self.root.after(6000,lambda:self.activity.set(getattr(self,'header_base_status','')) if peer==self.active else None)
        elif kind=='reaction':
            peer,ident=payload
            if peer!=self.active or not any(m.id==ident for m in self.messages): return
            backend=self.service.backend
            async def fetch(): return backend.message(await backend.checked_message(peer,ident))
            def loaded(message):
                if (account,peer)==(self.ui_account,self.active):
                    self.messages=[message if m.id==ident else m for m in self.messages]; self.render_messages(False)
            self.worker.submit(fetch(),loaded,lambda _:None)
        elif kind=='wallpaper':
            peer=payload; key=f'{account}:{peer}'
            from .customization_sync import sync_enabled, wallpaper_is_local
            if not sync_enabled(self.preferences) or wallpaper_is_local(self,account,peer): return
            if key in self.wallpapers:
                updated=dict(self.wallpapers); updated.pop(key)
                try:
                    write_json(self.wallpapers_file,updated)
                    from .interface_windows import share_view_value
                    share_view_value(self, 'wallpapers', updated)
                except OSError: pass
            if peer==self.active: self.refresh_wallpaper()
        elif kind=='chat_theme' and payload==self.active:
            self.refresh_wallpaper()
        elif kind=='pins' and payload==self.active:
            self.pinned_button.configure(text='⋯ •')

    def decorate_chat_status(self,peer,chat=None):
        if self.demo:return
        if chat is None:chat=next((c for c in self.chats if c.id==peer),None)
        if not chat or not chat.emoji_status_id:return
        account,backend=self.ui_account,self.service.backend
        widget=self.chat_list;key=(account,peer,'avatar')
        status=(chat.emoji_status_id,id(self.avatar_images.get(key)))
        cache=getattr(self,'_avatar_status',None)
        if cache is None:cache=self._avatar_status={}
        if cache.get((account,peer))==status and (account,peer,'status-composite') in self.avatar_images:return
        pending=getattr(self,'_avatar_status_pending',None)
        if pending is None:pending=self._avatar_status_pending=set()
        request=(account,peer,status)
        if request in pending:return
        pending.add(request)
        def current():
            if account!=self.ui_account or widget is not self.chat_list or not widget.winfo_exists() or not widget.exists(str(peer)):return False
            chat=getattr(self,'_chat_by_id',{}).get(peer)
            if chat is not None and chat.emoji_status_id!=status[0]:return False
            return cache.get((account,peer))!=(status[0],id(self.avatar_images.get(key))) or (account,peer,'status-composite') not in self.avatar_images
        def loaded(path):
            pending.discard(request)
            if not path or not current():return
            def painted(emoji):
                from PIL import Image,ImageTk
                canvas=Image.new('RGBA',(56,32),(0,0,0,0))
                avatar=self.avatar_images.get(key)
                try:
                    if avatar:
                        image=ImageTk.getimage(avatar)
                        try:canvas.alpha_composite(image,(0,0))
                        finally:image.close()
                    image=ImageTk.getimage(emoji)
                    try:canvas.alpha_composite(image,(34,6))
                    finally:image.close()
                    photo=ImageTk.PhotoImage(canvas,master=self.root)
                finally:canvas.close()
                self.remember_avatar((account,peer,'status-composite'),photo)
                cache[(account,peer)]=(status[0],id(avatar))
                self.show_avatar(widget,peer,photo)
            self.request_photo(path,(20,20),painted,owner=widget,valid=current,enabled=False)
        self.emoji_art(chat.emoji_status_id,account,backend,loaded)

    def message_browser(self,media=False,peer=None):
        peer=self.active if peer is None else peer
        if self.busy or peer is None or self.demo:return
        from .shared_media import SharedMediaBrowser
        SharedMediaBrowser(self,media,peer)

    def ensure_message_accents(self):
        if self.demo or self.active is None: return
        account,peer,backend=self.ui_account,self.active,self.service.backend
        if account not in self.message_palettes and account not in self.palette_pending:
            self.palette_pending.add(account)
            def loaded(palettes):
                self.palette_pending.discard(account); self.message_palettes[account]=palettes
                if account==self.ui_account and getattr(self,'_canvas_chat_view',self.preferences.values['bubbles']): self.bubble_view.render(self.messages,False)
            self.worker.submit(backend.message_palettes(),loaded,lambda _,done=loaded:done({}))
        present={m.id for m in self.messages}
        missing={m.reply_to_id for m in self.messages if m.reply_to_id and m.reply_to_id not in present and (account,peer,m.reply_to_id) not in self.reply_cache and (account,peer,m.reply_to_id) not in self.reply_pending}
        if missing:
            keys={(account,peer,ident) for ident in missing}; self.reply_pending.update(keys)
            def loaded(replies):
                self.reply_pending.difference_update(keys)
                self.remember_replies({(account,peer,ident):replies.get(ident) for ident in missing})
                if (account,peer)==(self.ui_account,self.active):
                    self.render_messages(False); self.update_reply()
            self.worker.submit(backend.reply_contexts(peer,missing),loaded,lambda _:loaded({}))

    def message_accent(self,message):
        from .themes import resolve_theme
        dark=resolve_theme(self.preferences.values['theme'])=='dark'
        defaults=['#e17076','#eda86c','#a695e7','#7bc862','#6ec9cb','#65aadd','#e98abd'] if dark else ['#c5424b','#a46019','#7654b0','#387e28','#208688','#2979ac','#b04488']
        color=message.sender_color
        if color is None: color=abs(message.sender_id or 0)%7
        palette=self.message_palettes.get(self.ui_account,{}).get(color,{})
        colors=palette.get('dark' if dark else 'light',[])
        return [f'#{value:06x}' for value in colors] if colors else [defaults[color%7]]
