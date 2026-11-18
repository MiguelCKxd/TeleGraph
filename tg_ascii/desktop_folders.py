"""Folder creation, rules, ordering and shared-link management."""
from . import APP_NAME
from copy import deepcopy
import tkinter as tk
from tkinter import ttk
from telethon import types,utils
from .i18n import tr
from .app_dialogs import Choice,popup_menu,scrollable,messagebox,simpledialog
from .rich_preview import RichPreview
from .folder_features import RULES,folder_title
from .telegram_features import matches_folder, compile_folder, in_chat_list

FOLDER_COLORS={0:'#e46d69',1:'#e7a85b',2:'#b88be0',3:'#68bb75',4:'#59bfc8',5:'#6d9fe4',6:'#d886b5'}

RULE_LABELS=('Contacts','Non-contacts','Groups','Channels','Bots','Exclude muted chats','Exclude read chats','Exclude archived chats')


class FolderLabel:
    def __init__(self,app,folder=None,prefix=''):
        self.app,self.folder,self.prefix=app,folder,prefix
    def native_menu_label(self):
        title=self.folder.title if self.folder else types.TextWithEntities(tr('Todos los chats'),[])
        if title.entities or getattr(self.folder,'color',None) not in (None,-1): return None
        return self.prefix+title.text
    def build_menu(self,parent,command,enabled=True):
        title=self.folder.title if self.folder else types.TextWithEntities(tr('Todos los chats'),[])
        widget=RichPreview(parent,self.app,title.text,title.entities,prefix=self.prefix,command=command if enabled else None,takefocus=enabled)
        widget.accent=FOLDER_COLORS.get(getattr(self.folder,'color',None))
        widget.configure(width=280)
        widget.invoke=command if enabled else lambda:None
        return widget


class FolderPicker(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent);self.app=app;self.records=[];self.selection=0;self.account=None;self.selections={}
        self.line=RichPreview(self,app,command=self.open);self.line.pack(side='left',fill='x',expand=True)
        ttk.Button(self,text='▾',width=3,command=self.open).pack(side='right')
    def current(self,index=None):
        if index is None:return next((i+1 for i,f in enumerate(self.records) if f.id==self.selection),0)
        self.selection=self.records[index-1].id if 0<index<=len(self.records) else 0
        self.selections[self.app.ui_account]=self.selection;self.paint()
    def set_records(self,records):
        if self.account!=self.app.ui_account:
            self.account=self.app.ui_account;self.selection=self.selections.get(self.account,0)
        self.records=list(records)
        if self.selection not in {f.id for f in records}:self.selection=0
        self.paint()
    def paint(self):
        archive_view=bool(getattr(self.app,'archive_view',False))
        folder=None if archive_view else next((f for f in self.records if f.id==self.selection),None)
        title=types.TextWithEntities(tr('Archived chats'),[]) if archive_view else folder.title if folder else types.TextWithEntities(tr('Todos los chats'),[])
        compiled=compile_folder(folder)
        count=sum(c.unread>0 or getattr(c,'unread_mark',False) for c in self.app.chats if in_chat_list(c,folder,compiled,archive_view))
        self.line.accent=FOLDER_COLORS.get(getattr(folder,'color',None))
        self.line.set(title.text,title.entities,prefix=(str(count)+' · ') if count else '')
    def open(self):
        def choose(index):
            self.app.archive_view=False  # Choosing a folder leaves the archived list.
            self.current(index);self.app.render_chats()
        records={f.id:(i+1,f) for i,f in enumerate(self.records)}
        order=getattr(self.app.service.backend,'folder_order',[0]+list(records))
        order=list(dict.fromkeys(order+[0]+list(records)))
        entries=[]
        for ident in order:
            index,folder=records.get(ident,(0,None))
            if ident and folder is None:continue
            compiled=compile_folder(folder)
            count=sum(c.unread>0 or getattr(c,'unread_mark',False) for c in self.app.chats if in_chat_list(c,folder,compiled))
            entries.append((FolderLabel(self.app,folder,('✓ ' if ident==self.selection else '')+(str(count)+' · ' if count else '')),lambda i=index:choose(i)))
        entries.extend([None,(tr('Manage folders'),self.app.folder_dialog)])
        popup_menu(self,entries,anchor=self)


class DesktopFolders:
    def prepare_folder_tags(self):
        from .rich_preview import preview_runs
        self._folder_tag_rows=[]
        if not getattr(self.service.backend,'folder_tags_enabled',False):return
        from .row_emoji import PLACEHOLDER
        for folder in self.folder_records:
            if getattr(folder,'color',None)==-1:continue
            runs=list(preview_runs(folder.title.text,folder.title.entities,12))
            # 1.5.0.1: a gap where the real custom emoji is drawn (row_emoji).
            title=''.join(PLACEHOLDER if doc else value for value,doc in runs)
            docs=[doc for _,doc in runs if doc]
            self._folder_tag_rows.append((folder,compile_folder(folder),title,docs))

    def folder_tags_text(self,chat):
        if not getattr(self.service.backend,'folder_tags_enabled',False):return ''
        if not hasattr(self,'_folder_tag_rows'):self.prepare_folder_tags()
        titles=[title for folder,compiled,title,_ in self._folder_tag_rows if matches_folder(chat,folder,compiled)]
        return ('  '+ ' '.join('['+title+']' for title in titles)) if titles else ''

    def folder_tag_docs(self,chat):
        """Custom emoji ids of this chat's folder tags, in the order shown."""
        if not getattr(self.service.backend,'folder_tags_enabled',False):return []
        if not hasattr(self,'_folder_tag_rows'):self.prepare_folder_tags()
        return [doc for folder,compiled,_,docs in self._folder_tag_rows if matches_folder(chat,folder,compiled) for doc in docs]

    def folder_guard(self,account,window=None):
        return not self.busy and account==self.ui_account and (window is None or window.winfo_exists())

    def select_folder_peers(self,title,selected,accepted,candidates=None):
        window,frame=self.dialog(title,'530x590');chosen=set(selected)
        footer=ttk.Frame(frame);footer.pack(side='bottom',fill='x',pady=6)
        query=tk.StringVar();ttk.Entry(frame,textvariable=query).pack(fill='x',pady=4)
        body=scrollable(frame)
        records={c.id:c.name for c in self.chats} if candidates is None else dict(candidates)
        for ident in chosen:records.setdefault(ident,f'Chat #{ident}')
        variables={ident:tk.BooleanVar(value=ident in chosen) for ident in records}
        def draw(*_):
            for child in body.winfo_children():child.destroy()
            for ident,label in records.items():
                if query.get().casefold() not in label.casefold():continue
                ttk.Checkbutton(body,text=label,variable=variables[ident]).pack(anchor='w',fill='x',pady=3)
        def done():
            values=[ident for ident,var in variables.items() if var.get()]
            window.destroy();accepted(values)
        ttk.Button(footer,text=tr('Continue'),command=done).pack(side='right')
        ttk.Button(footer,text=tr('Cancel'),command=window.destroy).pack(side='right')
        query.trace_add('write',draw);draw()

    def folder_dialog(self):
        if self.busy:return
        backend,account=self.service.backend,self.ui_account
        def loaded(folders):
            if account!=self.ui_account:return
            window,frame=self.dialog('Carpetas','570x640')
            footer=ttk.Frame(frame);footer.pack(side='bottom',fill='x')
            body=scrollable(frame)
            self.folder_records=folders;self.update_folder_picker();self.render_chats()
            order=list(dict.fromkeys(getattr(backend,'folder_order',[0]+[f.id for f in folders])+[0]))
            by_id={f.id:f for f in folders}
            def finish(_):
                if window.winfo_exists():window.destroy()
                if account==self.ui_account:self.refresh()
            def move(ident,delta):
                if not self.folder_guard(account,window):return
                position=order.index(ident);target=position+delta
                if not 0<=target<len(order):return
                changed=list(order);changed[position],changed[target]=changed[target],changed[position]
                self.call(backend.reorder_folders(changed),finish,tr('Guardando...'))
            def actions(folder):
                ident=folder.id if folder else 0
                entries=[(tr('Move up'),lambda:move(ident,-1),order.index(ident)>0),(tr('Move down'),lambda:move(ident,1),order.index(ident)<len(order)-1)]
                if not self.demo:entries.append((tr('Mark folder as read'),lambda:self.call(backend.mark_folder_read(folder),finish,tr('Guardando...')) if self.folder_guard(account,window) else None))
                if folder:
                    entries.insert(0,(tr('Edit folder'),lambda:self.edit_folder(folder)))
                    if folder.pinned_peers:entries.append((tr('Pinned chats'),lambda:self.folder_pin_order(folder)))
                    if not self.demo:
                        entries.append((tr('Share folder'),lambda:self.folder_links(folder)))
                        if isinstance(folder,types.DialogFilterChatlist):entries.append((tr('Folder updates'),lambda:self.shared_folder_updates(folder)))
                    entries.append((tr('Eliminar carpeta'),lambda:self.delete_folder_dialog(folder,finish)))
                popup_menu(window,entries)
            for ident in order:
                folder=by_id.get(ident)
                if ident and folder is None:continue
                row=FolderLabel(self,folder).build_menu(body,lambda f=folder:actions(f));row.pack(fill='x',pady=3)
            ttk.Button(footer,text=tr('Nueva carpeta'),command=lambda:self.edit_folder()).pack(fill='x',pady=3)
            if not self.demo:
                ttk.Button(footer,text=tr('Suggested folders'),command=self.folder_suggestions).pack(fill='x',pady=3)
                ttk.Button(footer,text=tr('Join folder link'),command=self.join_folder_dialog).pack(fill='x',pady=3)
                enabled=tk.BooleanVar(value=getattr(backend,'folder_tags_enabled',False))
                def tags():
                    if self.folder_guard(account,window):self.call(backend.toggle_folder_tags(enabled.get()),finish,tr('Guardando...'))
                ttk.Checkbutton(footer,text=tr('Show folder tags (Premium)'),variable=enabled,command=tags).pack(anchor='w',pady=5)
        self.call(backend.folders(),loaded,tr('Cargando...'))

    def edit_folder(self,folder=None):
        if self.busy:return
        backend,account=self.service.backend,self.ui_account
        window,frame=self.dialog('Edit folder' if folder else 'Nueva carpeta','590x690')
        footer=ttk.Frame(frame);footer.pack(side='bottom',fill='x')
        body=scrollable(frame)
        initial=folder.title if folder else types.TextWithEntities('',[])
        name=tk.StringVar(value=initial.text);entities=deepcopy(initial.entities);old=[initial.text]
        ttk.Label(body,text=tr('Nombre de carpeta (max. 12):')).pack(anchor='w')
        entry=ttk.Entry(body,textvariable=name);entry.pack(fill='x')
        preview=RichPreview(body,self,initial.text,entities);preview.pack(fill='x',pady=3)
        def changed(*_):
            from .folder_features import shift_title_entities
            entities[:]=shift_title_entities(old[0],name.get(),entities);old[0]=name.get()
            preview.set(name.get(),entities)
        name.trace_add('write',changed)
        def insert(document):
            if not window.winfo_exists() or account!=self.ui_account:return
            from .telegram_extras import emoji_attribute
            attr=emoji_attribute(document)
            if not attr:return
            index=entry.index('insert');offset=len(name.get()[:index].encode('utf-16-le'))//2
            name.set(name.get()[:index]+attr.alt+name.get()[index:])
            entities.append(types.MessageEntityCustomEmoji(offset,len(attr.alt.encode('utf-16-le'))//2,document.id));preview.set(name.get(),entities)
        ttk.Button(body,text=tr('Custom emoji'),command=lambda:self.telegram_picker(True,on_choose=insert)).pack(anchor='w',pady=3)
        included=[utils.get_peer_id(p) for p in folder.include_peers+folder.pinned_peers] if folder else []
        excluded=[utils.get_peer_id(p) for p in getattr(folder,'exclude_peers',[])] if folder else []
        original_include=list(included);original_exclude=list(excluded)
        def member_button(label,collection):
            button=ttk.Button(body)
            def update(values):collection[:]=values;button.configure(text=tr(label)+f' ({len(collection)})')
            button.configure(command=lambda:self.select_folder_peers(label,collection,update));update(collection[:]);button.pack(fill='x',pady=5)
        member_button('Included chats',included)
        shared=isinstance(folder,types.DialogFilterChatlist)
        flags={}
        if not shared:
            for key,label in zip(RULES,RULE_LABELS):
                flags[key]=tk.BooleanVar(value=bool(getattr(folder,key,False)))
                ttk.Checkbutton(body,text=tr(label),variable=flags[key]).pack(anchor='w',pady=3)
            member_button('Excluded chats',excluded)
        else:ttk.Label(body,text=tr('Shared folders only support explicit chats.'),wraplength=470).pack(fill='x',pady=6)
        icon=self.field(body,'Folder icon',getattr(folder,'emoticon',None) or '')
        colors=['Default','Hidden','Red','Orange','Violet','Green','Cyan','Blue','Pink'];color_values=[None,-1,0,1,2,3,4,5,6]
        ttk.Label(body,text=tr('Folder color (Premium)')).pack(anchor='w',pady=4)
        color=Choice(body,values=[tr(c) for c in colors]);color.current(color_values.index(getattr(folder,'color',None)));color.pack(fill='x')
        still=tk.BooleanVar(value=bool(getattr(folder,'title_noanimate',False)))
        ttk.Checkbutton(body,text=tr('Disable title animation'),variable=still).pack(anchor='w',pady=5)
        def save():
            if not self.folder_guard(account,window):return
            try:title=folder_title(types.TextWithEntities(name.get(),entities))
            except ValueError as exc:self.show_error(exc);return
            values={key:var.get() for key,var in flags.items()}
            values.update(emoticon=icon.get() or None,color=color_values[color.current()],title_noanimate=still.get())
            options={key:val for key,val in values.items() if val!=getattr(folder,key,None)}
            title_changed=folder is None or bytes(title)!=bytes(folder.title)
            def done(_):
                window.destroy()
                if account==self.ui_account:self.refresh()
            self.call(backend.save_folder(title if title_changed else None,
                included if folder is None or included!=original_include else None,folder,options,
                excluded if not shared and (folder is None or excluded!=original_exclude) else None),done,tr('Guardando...'))
        ttk.Button(footer,text=tr('Save'),command=save).pack(side='right',pady=6)
        ttk.Button(footer,text=tr('Cancel'),command=window.destroy).pack(side='right',padx=4)

    def folder_pin_order(self,folder):
        backend,account=self.service.backend,self.ui_account
        order=[utils.get_peer_id(p) for p in folder.pinned_peers]
        names={c.id:c.name for c in self.chats}
        window,frame=self.dialog('Pinned chats','480x480')
        listing=tk.Listbox(frame,exportselection=False);listing.pack(fill='both',expand=True)
        def draw(index=0):
            listing.delete(0,'end')
            for ident in order:listing.insert('end',names.get(ident,f'#{ident}'))
            if order:listing.selection_set(index)
        def move(step):
            if not listing.curselection():return
            i=listing.curselection()[0];j=i+step
            if 0<=j<len(order):order[i],order[j]=order[j],order[i];draw(j)
        for label,step in [('Move up',-1),('Move down',1)]:ttk.Button(frame,text=tr(label),command=lambda v=step:move(v)).pack(side='left')
        def save():
            if self.folder_guard(account,window):self.call(backend.reorder_folder_pins(folder,order),lambda _:(window.destroy(),self.refresh()),tr('Guardando...'))
        ttk.Button(frame,text=tr('Save'),command=save).pack(side='right');draw()

    def delete_folder_dialog(self,folder,finished):
        backend,account=self.service.backend,self.ui_account
        if self.busy:return
        if isinstance(folder,types.DialogFilterChatlist) and not self.demo:
            def loaded(suggested):
                if account!=self.ui_account:return
                names={c.id:c.name for c in self.chats};members={utils.get_peer_id(p):names.get(utils.get_peer_id(p),f'#{utils.get_peer_id(p)}') for p in folder.include_peers+folder.pinned_peers}
                def leave(peers):
                    if self.folder_guard(account) and messagebox.askyesno(tr('Eliminar carpeta'),tr('Delete folder and leave the checked groups/channels? Unchecked chats will be kept.'),parent=self.root):
                        self.call(backend.leave_folder(folder,peers),finished,tr('Guardando...'))
                self.select_folder_peers('Also leave checked chats',[utils.get_peer_id(p) for p in suggested],leave,members)
            self.call(backend.folder_leave_suggestions(folder),loaded,tr('Cargando...'))
        elif messagebox.askyesno(tr('Eliminar carpeta'),tr('Eliminar esta carpeta de Telegram? Los chats se conservan.'),parent=self.root):
            self.call(backend.delete_folder(folder.id),finished,tr('Guardando...'))

    def folder_suggestions(self):
        if self.busy:return
        backend,account=self.service.backend,self.ui_account
        def loaded(items):
            if account!=self.ui_account:return
            window,frame=self.dialog('Suggested folders','520x480');body=scrollable(frame)
            if not items:ttk.Label(body,text=tr('No suggestions available.')).pack()
            for suggestion in items:
                def create(f=suggestion.filter):
                    if self.folder_guard(account,window):
                        options={key:getattr(f,key,False) for key in RULES};options['emoticon']=f.emoticon
                        self.call(backend.save_folder(f.title,f.include_peers,options=options,excluded=f.exclude_peers),lambda _:(window.destroy(),self.refresh()),tr('Guardando...'))
                FolderLabel(self,suggestion.filter).build_menu(body,create).pack(fill='x',pady=3)
                ttk.Label(body,text=suggestion.description,wraplength=450).pack(fill='x',pady=4)
        self.call(backend.suggested_folders(),loaded,tr('Cargando...'))

    def folder_links(self,folder):
        if self.busy or self.demo:return
        backend,account=self.service.backend,self.ui_account
        def loaded(result):
            if account!=self.ui_account:return
            window,frame=self.dialog('Share folder','590x570');footer=ttk.Frame(frame);footer.pack(side='bottom',fill='x');body=scrollable(frame)
            def edit(invite=None):
                if not self.folder_guard(account,window):return
                title=simpledialog.askstring(tr('Share folder'),tr('Private link title:'),initialvalue=invite.title if invite else '',parent=window)
                if title is None:return
                names={c.id:c.name for c in self.chats};ids={utils.get_peer_id(p) for p in folder.include_peers+folder.pinned_peers}
                candidates={ident:names.get(ident,f'#{ident}') for ident in ids if ident<0}
                def save(peers):
                    if not self.folder_guard(account,window):return
                    if any(-1000000000000<p<0 for p in peers) and not messagebox.askyesno(tr('Share folder'),tr('Telegram will convert basic groups in this link into supergroups. Continue?'),parent=window):return
                    def done(result):
                        window.destroy();self.refresh()
                        link=getattr(getattr(result,'invite',None),'url',None)
                        if link:
                            created,content=self.dialog('Folder link','540x180')
                            value=tk.StringVar(value=link)
                            ttk.Entry(content,textvariable=value,state='readonly').pack(fill='x',pady=8)
                            def copy():self.root.clipboard_clear();self.root.clipboard_append(link)
                            ttk.Button(content,text=tr('Copy link'),command=copy).pack(fill='x')
                    self.call(backend.export_folder_invite(folder,title,peers,invite.url if invite else None),done,tr('Guardando...'))
                self.select_folder_peers('Included chats',[utils.get_peer_id(p) for p in invite.peers] if invite else [],save,candidates)
            def revoke(invite):
                if self.folder_guard(account,window) and messagebox.askyesno(tr('Revoke link'),tr('Stop new people from joining through this link?'),parent=window):
                    self.call(backend.revoke_folder_invite(folder,invite.url),lambda _:(window.destroy(),self.folder_links(folder)),tr('Guardando...'))
            for invite in result.invites:
                ttk.Label(body,text=invite.title or tr('Folder link')).pack(anchor='w',pady=4)
                value=tk.StringVar(value=invite.url);entry=ttk.Entry(body,textvariable=value,state='readonly');entry.pack(fill='x')
                row=ttk.Frame(body);row.pack(fill='x')
                def copy(url=invite.url):self.root.clipboard_clear();self.root.clipboard_append(url)
                for label,action in [('Copy link',copy),('Edit link',lambda i=invite:edit(i)),('Revoke link',lambda i=invite:revoke(i))]:ttk.Button(row,text=tr(label),command=action).pack(side='left')
            ttk.Label(footer,text=tr('Only groups and channels you can invite others to can be shared.'),wraplength=500).pack(fill='x',pady=6)
            ttk.Button(footer,text=tr('Create link'),command=edit).pack(fill='x')
        self.call(backend.folder_invites(folder),loaded,tr('Cargando...'))

    def join_folder_dialog(self,url=None):
        if self.busy or self.demo:return
        backend,account=self.service.backend,self.ui_account
        if not url:url=simpledialog.askstring(tr('Join folder link'),tr('Folder link'),parent=self.root)
        if not url:return
        def loaded(result):
            if account!=self.ui_account:return
            peers=getattr(result,'missing_peers',None)
            if peers is None:peers=getattr(result,'peers',[])
            entities={utils.get_peer_id(c):c for c in result.chats+result.users}
            candidates={utils.get_peer_id(p):utils.get_display_name(entities[utils.get_peer_id(p)]) for p in peers if utils.get_peer_id(p) in entities and not isinstance(entities[utils.get_peer_id(p)],(types.ChannelForbidden,types.ChatForbidden))}
            if not candidates:messagebox.showinfo(APP_NAME,tr('No new accessible chats in this folder.'),parent=self.root);return
            def join(selected):
                if self.folder_guard(account) and messagebox.askyesno(tr('Join folder link'),tr('Add this folder and join the checked chats?'),parent=self.root):
                    if not self.folder_guard(account) or backend is not self.service.backend:return
                    self.call(backend.join_folder_invite(url,selected),lambda _:self.refresh(),tr('Guardando...'))
            self.select_folder_peers('Join folder link',list(candidates),join,candidates)
        self.call(backend.check_folder_invite(url),loaded,tr('Cargando...'))

    def shared_folder_updates(self,folder):
        if self.busy or self.demo:return
        backend,account=self.service.backend,self.ui_account
        def loaded(result):
            if account!=self.ui_account:return
            entities={utils.get_peer_id(c):c for c in result.chats+result.users}
            candidates={utils.get_peer_id(p):utils.get_display_name(entities[utils.get_peer_id(p)]) for p in result.missing_peers if utils.get_peer_id(p) in entities and not isinstance(entities[utils.get_peer_id(p)],(types.ChannelForbidden,types.ChatForbidden))}
            if not candidates:messagebox.showinfo(APP_NAME,tr('No new accessible chats in this folder.'),parent=self.root);return
            def accept(selected):
                if not self.folder_guard(account):return
                if selected and not messagebox.askyesno(tr('Folder updates'),tr('Join the checked chats and add them to the folder?'),parent=self.root):return
                if not self.folder_guard(account) or backend is not self.service.backend:return
                self.call(backend.accept_folder_updates(folder,selected) if selected else backend.hide_folder_updates(folder),lambda _:self.refresh(),tr('Guardando...'))
            self.select_folder_peers('Folder updates',list(candidates),accept,candidates)
        self.call(backend.folder_updates(folder),loaded,tr('Cargando...'))
