"""Explicit context gestures and account-scoped multiple selection."""
import tkinter as tk
from tkinter import ttk
from .i18n import tr
from .app_dialogs import popup_menu,messagebox


def is_reply_swipe(dx,dy,threshold=65):return dx<=-threshold and abs(dy)<55


class ContextGesture:
    def __init__(self,widget,target,context,single=None,reply=None,animate=None,scope=lambda:None,double=False,consume=False,click=None,motion_options=None):
        self.widget,self.target,self.context=widget,target,context
        self.single,self.reply,self.animate,self.scope=single,reply,animate,scope
        self.double_action=double if callable(double) else context
        self.click=click;self.click_callback=None;self.click_timer=None
        self.consume=consume;self.timer=None;self.press_state=None;self.held=False;self.animation=None
        self.motion_options=motion_options
        self.gesture_options={'enabled':True,'gesture_enabled':True,'distance':80,'threshold':65}
        widget.bind('<ButtonPress-1>',self.press)
        widget.bind('<B1-Motion>',self.motion)
        widget.bind('<ButtonRelease-1>',self.release)
        widget.bind('<Button-3>',self.right)
        # macOS secondary click may be reported as Button-2 by Tk.
        import sys
        if sys.platform=='darwin':
            widget.bind('<Button-2>',self.right)
            widget.bind('<Control-Button-1>',self.right)
        if double:widget.bind('<Double-Button-1>',self.double)
        widget.bind('<Destroy>',lambda e:(self.cancel(),self.cancel_click()) if e.widget is widget else None,add='+')
    def cancel(self):
        if self.timer:
            try:self.widget.after_cancel(self.timer)
            except tk.TclError:pass
        self.timer=None
    def cancel_click(self):
        if self.click_timer:
            try:self.widget.after_cancel(self.click_timer)
            except tk.TclError:pass
        self.click_timer=None
    def press(self,event):
        self.cancel();self.cancel_click();self.held=False
        if self.motion_options:self.gesture_options=self.motion_options()
        self.click_callback=self.click(event) if self.click else None
        value=self.target(event);self.press_state=(event.x,event.y,value,self.scope())
        if value is not None:self.timer=self.widget.after(550,self.hold)
        return 'break' if self.consume else None
    def hold(self):
        self.timer=None
        if self.press_state and self.press_state[3]==self.scope() and self.widget.winfo_exists():
            self.held=True;self.context(self.press_state[2])
    def motion(self,event):
        if not self.press_state:return
        x,y,value,scope=self.press_state;dx,dy=event.x-x,event.y-y
        if abs(dx)+abs(dy)>8:self.cancel()
        if scope==self.scope() and value is not None and self.reply and self.gesture_options['gesture_enabled'] and not self.held and dx<-12 and abs(dy)<55:
            if self.animate and self.gesture_options['enabled']:self.animate(value,max(-self.gesture_options['distance'],dx),False)
            return 'break'
        return 'break' if self.consume else None
    def release(self,event):
        self.cancel();state=self.press_state;self.press_state=None
        if not state:return
        x,y,value,scope=state
        if value is None or scope!=self.scope():return 'break' if self.consume else None
        dx,dy=event.x-x,event.y-y
        if self.animate:self.animate(value,0,True)
        if self.held:return 'break'
        if self.reply and self.gesture_options['gesture_enabled'] and is_reply_swipe(dx,dy,self.gesture_options['threshold']):self.reply(value);return 'break'
        if abs(dx)+abs(dy)<8 and self.click_callback:
            callback=self.click_callback
            def activate():
                self.click_timer=None
                if scope==self.scope() and self.widget.winfo_exists():callback()
            self.click_timer=self.widget.after(350,activate)
            return 'break'
        if abs(dx)+abs(dy)<8 and self.single:self.single(value);return 'break'
        return 'break' if self.consume else None
    def double(self,event):
        self.cancel();self.cancel_click();self.held=True;value=self.target(event)
        if value is not None:self.double_action(value)
        return 'break'
    def right(self,event):
        self.cancel();self.cancel_click();self.held=True;self.press_state=None;value=self.target(event)
        if value is not None:self.context(value)
        return 'break'


class DesktopInteractions:
    def setup_interactions(self):
        from .motion import motion_event
        self.selection_kind=None;self.selected_chats=set();self.selected_messages=set();self.selection_scope=None
        self.selection_bar=ttk.Frame(self.chat_page,padding=3)
        self.selection_label=ttk.Label(self.selection_bar);self.selection_label.pack(side='left',fill='x',expand=True)
        ttk.Button(self.selection_bar,text=tr('Actions'),command=self.selection_actions).pack(side='right')
        ttk.Button(self.selection_bar,text=tr('Cancel'),command=self.clear_selection).pack(side='right',padx=3)
        if not getattr(self, '_chat_only', False):
            def target_chat(event):
                value=self.chat_list.identify_row(event.y)
                return int(value) if value else None
            def open_chat(peer):
                if self.selection_kind=='chats':self.toggle_chat_selection(peer);return
                self.chat_list.selection_set(str(peer))
            # Capture the three-dots hit on release too, without opening/reading a chat.
            def single_chat(peer):
                press=getattr(self,'_chat_press_column',None)
                # 3.2: the chat's picture opens its settings menu, not the chat.
                on_picture=getattr(self,'_chat_press_element',None)=='image'
                if (press=='#1' or on_picture) and self.selection_kind!='chats':self.chat_actions(peer)
                else:open_chat(peer)
            self.chat_gesture=ContextGesture(self.chat_list,target_chat,self.chat_actions,single_chat,scope=lambda:self.ui_account,consume=True)
            original=self.chat_gesture.press
            def press(event):
                self._chat_press_column=self.chat_list.identify_column(event.x)
                try:self._chat_press_element=self.chat_list.identify_element(event.x,event.y)
                except tk.TclError:self._chat_press_element=None
                return original(event)
            self.chat_list.bind('<ButtonPress-1>',press)
        self.classic_gesture=ContextGesture(self.history,self.message_at,self.message_actions,
            single=lambda m:self.toggle_message_selection(m) if self.selection_kind=='messages' else None,
            reply=self.reply_message,animate=self.classic_swipe_feedback,scope=lambda:(self.ui_account,self.active),double=self.quick_react,click=self.classic_profile_click,
            motion_options=lambda:motion_event(self))
        self.history.bind('<Escape>',lambda _:self.clear_selection() if self.selection_kind else None)
        if hasattr(self, 'chat_list'):
            self.chat_list.bind('<Escape>',lambda _:self.clear_selection() if self.selection_kind else None)
        for widget in (self.history, self.bubble_view, *([self.chat_list] if hasattr(self, 'chat_list') else [])):
            widget.bind('<Control-a>',lambda _:self.select_all_visible() if self.selection_kind else None)
            widget.bind('<Command-a>',lambda _:self.select_all_visible() if self.selection_kind else None)

    def classic_profile_click(self,event):
        if self.selection_kind:return None
        tags=self.history.tag_names(f'@{event.x},{event.y}')
        message=self.message_at(event)
        if message and f'sender_profile_{message.id}' in tags:
            scope=(self.ui_account,self.active)
            return lambda:self.open_sender_profile(message,scope)

    def classic_swipe_feedback(self,message,offset,release):
        from .motion import motion_event, ReturnMotion, indicator_photo
        event=motion_event(self)
        label=getattr(self,'_reply_swipe_label',None)
        previous=getattr(self,'_classic_swipe_motion',None)
        if previous:previous.cancel()
        if not event['enabled']:
            if label is not None and label.winfo_exists():label.place_forget()
            self._reply_swipe_offset=0;return
        if release and not getattr(self,'_reply_swipe_offset',0):return
        if label is None or not label.winfo_exists():
            label=tk.Label(self.history,text='↩',bg='#163b27',fg='#8cf5a6',padx=6,pady=3);self._reply_swipe_label=label
            label.bind('<Destroy>',lambda e:getattr(self,'_classic_swipe_motion',None) and self._classic_swipe_motion.cancel() if e.widget is label else None,add='+')
        state=getattr(self.classic_gesture,'press_state',None)
        if not release:
            if not getattr(self,'_reply_swipe_offset',0):
                label.image=indicator_photo(self,event)
                label.configure(image=label.image or '',text='' if label.image else '↩')
            self._reply_swipe_offset=offset;label.place(x=max(0,self.history.winfo_width()+offset-35),y=max(0,(state[1] if state else 20)-15));return
        start=getattr(self,'_reply_swipe_offset',0)
        scope=(self.ui_account,self.active)
        def update(value):label.place_configure(x=max(0,self.history.winfo_width()+value-35))
        def finish():label.place_forget();label.image=None;label.configure(image='',text='↩')
        self._classic_swipe_motion=ReturnMotion(label,start,update,finish,event,lambda:scope==(self.ui_account,self.active))
        self._reply_swipe_offset=0

    def selection_valid(self):
        if not hasattr(self,'selection_kind'):return False
        expected=(self.ui_account,self.active) if self.selection_kind=='messages' else (self.ui_account,None)
        if self.selection_kind and expected!=self.selection_scope:
            self.selection_kind=None;self.selected_chats=set();self.selected_messages=set()
            if hasattr(self,'selection_bar') and self.selection_bar.winfo_exists():self.selection_bar.pack_forget()
        return bool(self.selection_kind)

    def toggle_chat_selection(self,peer):
        if not self.selection_valid() or self.selection_kind!='chats':
            self.selection_kind='chats';self.selection_scope=(self.ui_account,None);self.selected_chats=set();self.selected_messages=set()
        if peer in self.selected_chats:self.selected_chats.remove(peer)
        else:self.selected_chats.add(peer)
        self.refresh_selection()

    def toggle_message_selection(self,message):
        if not self.selection_valid() or self.selection_kind!='messages':
            self.selection_kind='messages';self.selection_scope=(self.ui_account,self.active);self.selected_messages=set();self.selected_chats=set()
        if message.id in self.selected_messages:self.selected_messages.remove(message.id)
        else:self.selected_messages.add(message.id)
        self.refresh_selection()

    def refresh_selection(self):
        if not self.selection_valid():return
        count=len(self.selected_messages if self.selection_kind=='messages' else self.selected_chats)
        self.selection_label.configure(text=tr('Selected')+f': {count}')
        self.selection_bar.pack(fill='x',before=self.chat_conversation if getattr(self, '_chat_only', False) else self.chat_panes)
        self.render_chats();self.render_messages(False)

    def clear_selection(self):
        self.selection_kind=None;self.selected_chats=set();self.selected_messages=set();self.selection_scope=None
        if hasattr(self,'selection_bar') and self.selection_bar.winfo_exists():self.selection_bar.pack_forget()
        self.render_chats();self.render_messages(False);return 'break'

    def select_all_visible(self):
        if not self.selection_valid():return
        if self.selection_kind=='chats':self.selected_chats={int(i) for i in self.chat_list.get_children()}
        else:self.selected_messages={m.id for m in self.messages}
        self.refresh_selection();return 'break'

    def chat_selection_prefix(self,peer):
        if self.selection_valid() and self.selection_kind=='chats':return '☑ ' if peer in self.selected_chats else '☐ '
        return ''

    def message_selected(self,ident):
        return self.selection_valid() and self.selection_kind=='messages' and ident in self.selected_messages

    def selection_actions(self,policy=None):
        if not self.selection_valid() or self.busy:return
        account,peer,backend=self.ui_account,self.active,self.service.backend
        kind=self.selection_kind
        def valid():return not self.busy and account==self.ui_account and (kind!='messages' or peer==self.active)
        def finished(_):
            if account!=self.ui_account:return
            self.clear_selection();self.refresh()
        entries=[(tr('Select all'),self.select_all_visible)]
        if kind=='chats':
            ids=sorted(self.selected_chats)
            def batch(kind,value):
                if not valid() or not ids or self.demo:return
                async def work():
                    for ident in ids:
                        if kind=='archive':await backend.archive_chat(ident,value)
                        elif kind=='read':await backend.set_chat_unread(ident,value)
                        else:await backend.mute_chat(ident,value)
                self.call(work(),finished,tr('Guardando...'))
            for label,action,value in [('Archive','archive',True),('Unarchive','archive',False),('Mute','mute',True),('Unmute','mute',False),('Mark as read','read',False),('Mark as unread','read',True)]:
                entries.append((tr(label),lambda k=action,v=value:batch(k,v),bool(ids) and not self.demo))
            def folders():
                if not valid():return
                def loaded(records):
                    if account!=self.ui_account:return
                    from .desktop_folders import FolderLabel
                    def apply(folder):
                        if not valid():return
                        async def work():
                            for ident in ids:await backend.folder_membership(folder,ident,True)
                        self.call(work(),finished,tr('Guardando...'))
                    popup_menu(self.root,[(FolderLabel(self,folder),lambda f=folder:apply(f)) for folder in records])
                self.call(backend.folders(),loaded,tr('Loading...'))
            entries.extend([(tr('Add to folder'),folders,bool(ids) and not self.demo),
                (tr('Delete chat'),lambda:self.delete_selected_chats(account,ids),bool(ids) and not self.demo)])
        else:
            ids=sorted(self.selected_messages)
            if not self.demo and policy is None and ids:
                def loaded(value):
                    if (account,peer)==(self.ui_account,self.active) and ids==sorted(self.selected_messages):self.selection_actions(value)
                self.call(backend.selected_message_policy(peer,ids),loaded,tr('Loading...'));return
            policy=policy or {'copy':True,'forward':False,'delete_self':False,'delete_all':False}
            def windows():
                if not valid():return
                from .message_window import open_message_windows
                open_message_windows(self,[m for m in self.messages if m.id in ids],peer)
            entries.append((tr('Open in new window'),windows,bool(ids)))
            def copy():
                if not valid():return
                text='\n\n'.join(m.sender+': '+(m.raw_text if m.raw_text is not None else m.text) for m in self.messages if m.id in ids)
                self.root.clipboard_clear();self.root.clipboard_append(text)
            def delete(everyone):
                if not valid() or not ids or self.demo:return
                prompt=tr('Delete this message for everyone?' if everyone else 'Delete this message for you?')+f' ({len(ids)})'
                if not messagebox.askyesno(tr('Delete message'),prompt,parent=self.root):return
                def done(_):
                    if (account,peer)==(self.ui_account,self.active):
                        self.messages=[m for m in self.messages if m.id not in ids];self.clear_selection()
                self.call(backend.delete_selected_messages(peer,ids,everyone),done,tr('Guardando...'))
            def save():
                if valid() and messagebox.askyesno(tr('Saved Messages'),tr('Save to Saved Messages')+f' ({len(ids)})?',parent=self.root):
                    self.call(backend.forward_selected_messages(peer,ids,'me'),lambda _:self.clear_selection() if (account,peer)==(self.ui_account,self.active) else None,tr('Enviando...'))
            if policy['copy']:entries.append((tr('Copy text'),copy,bool(ids)))
            if policy['forward']:
                entries.extend([(tr('Forward message'),lambda:self.forward_selection(account,peer,ids),bool(ids)),(tr('Save to Saved Messages'),save,bool(ids))])
            if policy['delete_self']:entries.append((tr('Delete for me'),lambda:delete(False),bool(ids)))
            if policy['delete_all']:entries.append((tr('Delete for everyone'),lambda:delete(True),bool(ids)))
        popup_menu(self.root,entries,anchor=self.selection_bar)

    def delete_selected_chats(self,account,ids):
        if self.busy or self.demo or not ids or account!=self.ui_account:return
        backend=self.service.backend
        async def permissions():return [await backend.history_permissions(ident) for ident in ids]
        def loaded(values):
            if account!=self.ui_account:return
            def remove(everyone):
                if self.busy or account!=self.ui_account:return
                # Bulk deletion never destroys a group/channel for all its members.
                title=tr('Delete chat')+f' ({len(ids)})'
                description=tr('Delete this chat for both participants.') if everyone else tr('Delete this chat from your account? For groups and channels this leaves the conversation.')
                names='\n'.join(c.name for c in self.chats if c.id in ids)
                if not messagebox.askyesno(title,names+'\n\n'+description,parent=self.root):return
                completed=[]
                async def work():
                    for ident in ids:
                        await backend.delete_chat(ident,everyone);completed.append(ident)
                def reconcile():
                    if account!=self.ui_account:return
                    for ident in completed:
                        self.drafts.pop(ident,None)
                        for mapping in (self.rich_drafts,self.format_drafts,self.reply_drafts):mapping.pop((account,ident),None)
                    self.chats=[c for c in self.chats if c.id not in completed]
                    if self.active in completed:
                        self.active=None;self.messages=[];self.editor.delete('1.0','end');self.attachment=None;self.update_attachment();self.update_reply()
                    self.clear_selection()
                def done(_):reconcile();self.refresh()
                def failed(error):reconcile();self.show_error(error)
                self.call(work(),done,tr('Guardando...'),failure=failed)
            entries=[(tr('Only me'),lambda:remove(False))]
            if all(v['person'] and v['delete_all'] for v in values):entries.append((tr('For everyone'),lambda:remove(True)))
            popup_menu(self.root,entries)
        self.call(permissions(),loaded,tr('Loading...'))

    def forward_selection(self,account,peer,ids):
        if self.busy or not ids or self.demo or (account,peer)!=(self.ui_account,self.active):return
        backend=self.service.backend
        window,frame=self.dialog('Forward message','500x500')
        listing=tk.Listbox(frame,exportselection=False);listing.pack(fill='both',expand=True)
        from .chat_capabilities import chat_capabilities
        targets=[chat for chat in self.chats if chat_capabilities(self,chat.id,chat=chat).writable]
        for chat in targets:listing.insert('end',chat.name)
        def send():
            if self.busy or account!=self.ui_account or not listing.curselection():return
            chat=targets[listing.curselection()[0]];destination=chat.id
            if backend is not self.service.backend or not chat_capabilities(self,destination).writable:return
            def done(_):
                if window.winfo_exists():window.destroy()
                if (account,peer)==(self.ui_account,self.active):self.clear_selection()
            from .desktop_forums import forward_to
            if forward_to(self,account,backend,chat,peer,ids,done):return  # 3.3: choose the topic
            self.call(backend.forward_selected_messages(peer,ids,destination),done,tr('Enviando...'))
        ttk.Button(frame,text=tr('Enviar >'),command=send).pack(fill='x',pady=6)
