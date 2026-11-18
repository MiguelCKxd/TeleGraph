"""Responsive, image-only Telegram sticker and custom-emoji mosaics."""
from . import APP_NAME
import tkinter as tk
from collections import OrderedDict
from tkinter import ttk

from .app_dialogs import Choice, messagebox, popup_menu
from .i18n import tr


class StickerGrid(ttk.Frame):
    def __init__(self,parent,app,account,backend,activate,small=False):
        super().__init__(parent)
        self.app,self.account,self.backend,self.activate=app,account,backend,activate
        self.cell=64 if small else 104
        self.documents=[];self.photos=OrderedDict();self.pending=set();self.failed=set();self.version=0;self.selected=None;self._cells={};self._wanted=set()
        self._loads={}
        from .animation import AnimationPlayer
        if not hasattr(app,'animation_player'):app.animation_player=AnimationPlayer(app.root)
        from .ui_work import FrameJob
        self.repaint=FrameJob(self,self.paint)
        self.canvas=tk.Canvas(self,highlightthickness=0,bg='#101b14',height=300)
        self._scroll_target=self.canvas
        parent._scroll_target=self.canvas
        bar=ttk.Scrollbar(self,command=self.canvas.yview)
        bar.pack(side='right',fill='y');self.canvas.pack(fill='both',expand=True)
        self.canvas.configure(yscrollcommand=lambda a,b:(bar.set(a,b),self.repaint.request()))
        self.canvas.bind('<Configure>',lambda _:self.layout())
        self.canvas.bind('<Button-1>',self.click)
        self.canvas.bind('<Return>',lambda _:self.activate(self.selected) if self.selected else None)
        self.canvas.bind('<space>',lambda _:self.activate(self.selected) if self.selected else None)
        for sequence,delta in (('<Left>',-1),('<Right>',1),('<Up>','up'),('<Down>','down'),('<Home>','home'),('<End>','end')):
            self.canvas.bind(sequence,lambda _,delta=delta:self.navigate(delta))
        self.bind('<Destroy>',self.closed)
        self.bind('<Map>',lambda _:self.repaint.request(),add='+')
        self.bind('<Unmap>',lambda _:self._wanted.clear(),add='+')
    def cancel_loads(self):
        for future in self._loads.values():future.cancel()
        self._loads.clear();self.pending.clear()
        retry=getattr(self,'_retry_job',None)
        if retry is not None:
            try:self.after_cancel(retry)
            except tk.TclError:pass
        self._retry_job=None
    def closed(self,event):
        if event.widget is self:
            self.version+=1;self._wanted=set();self.repaint.cancel();self.cancel_loads();self.photos.clear();self._cells.clear()
    def set_documents(self,documents):
        self.cancel_loads()
        self.version+=1;self.documents=list(documents);self.failed=set();self.selected=None;self._wanted=set()
        self._failed_times=OrderedDict()
        self.canvas.delete('tile');self._cells.clear()
        self.canvas.yview_moveto(0);self.layout()
    def layout(self):
        if not self.winfo_exists():return
        columns=max(1,self.canvas.winfo_width()//self.cell)
        if columns!=getattr(self,'columns',None):self.canvas.delete('tile');self._cells.clear()
        self.columns=columns
        rows=(len(self.documents)+self.columns-1)//self.columns
        region=(0,0,self.canvas.winfo_width(),max(1,rows*self.cell))
        if region!=getattr(self,'_region',None):self.canvas.configure(scrollregion=region);self._region=region
        self.repaint.request()
    def paint(self):
        if not self.winfo_exists() or not self.winfo_viewable() or not hasattr(self,'columns'):return
        first=max(0,int(self.canvas.canvasy(0)//self.cell)*self.columns)
        last=min(len(self.documents),(int(self.canvas.canvasy(self.canvas.winfo_height())//self.cell)+2)*self.columns)
        self._wanted={d.id for d in self.documents[first:last]}
        for i in list(self._cells):
            if not first<=i<last:self.canvas.delete(f'tile:{i}');del self._cells[i]
        for i in range(first,last):
            doc=self.documents[i];photo=self.photos.get(doc.id);selected=self.selected is doc
            if photo is None:self.load(doc)
            state=(doc.id,photo,selected)
            if self._cells.get(i)==state:continue
            x=(i%self.columns)*self.cell;y=(i//self.columns)*self.cell
            tag=f'tile:{i}';self.canvas.delete(tag)
            self.canvas.create_rectangle(x+2,y+2,x+self.cell-2,y+self.cell-2,outline='#65d88c' if selected else '#203729',tags=('tile',tag))
            if photo:self.canvas.create_image(x+self.cell/2,y+self.cell/2,image=photo,tags=('tile',tag))
            else:
                self.canvas.create_text(x+self.cell/2,y+self.cell/2,text='◇',fill='#65d88c',tags=('tile',tag))
            self._cells[i]=state
        visible={d.id for d in self.documents[first:last]}
        for ident in list(self.photos):
            if ident not in visible:self.photos.pop(ident,None)
        self.canvas.tag_raise('_tgas_corners')
    def load(self,doc):
        from .media_retry import grid_failed_recently, remember_grid_failure
        epoch=self.version;request=(epoch,doc.id)
        if self.account!=self.app.ui_account or request in self.pending or grid_failed_recently(self,doc.id) or len(self.pending)>=16:return
        self.pending.add(request)
        async def fetch():
            import asyncio
            if self.app.preview_slots is None:self.app.preview_slots=asyncio.Semaphore(3)
            async with self.app.preview_slots:
                if epoch!=self.version or doc.id not in self._wanted:return None
                from .animation import decode_frames, emoji_file
                path=await emoji_file(self.app,doc,self.account,self.backend)
                if epoch!=self.version or doc.id not in self._wanted:return None
                player=getattr(self.app,'animation_player',None)
                frames=None
                if path:
                    size=(self.cell-14,self.cell-14)
                    enabled=self.app.preferences.values.get('animated_emoji',True)
                    if player:frames=await asyncio.to_thread(player.prepare,path,size,enabled)
                    else:frames=await asyncio.to_thread(decode_frames,path,size,animated=enabled)
                return path,frames
        def ready(result):
            self.pending.discard(request)
            getattr(self,'_loads',{}).pop(request,None)
            if not self.winfo_exists():return
            if epoch!=self.version or self.account!=self.app.ui_account or doc.id not in self._wanted:
                self.repaint.request();return
            if result is None:
                self.repaint.request();return
            path,frames=result if result else (None,None)
            from .animation import AnimationPlayer
            if not hasattr(self.app,'animation_player'):self.app.animation_player=AnimationPlayer(self.app.root)
            try:
                from .appearance import app_palette
                from .telegram_extras import emoji_attribute
                attr=emoji_attribute(doc)
                tint=app_palette(self.app.preferences.values)['text'] if getattr(attr,'text_color',False) else None
                photo=self.app.animation_player.photo(path,(self.cell-14,self.cell-14),self.app.preferences.values.get('animated_emoji',True),prepared=frames,tint=tint,owner=self) if path else None
            except (OSError,ValueError,tk.TclError):photo=None
            if photo:self.photos[doc.id]=photo
            else:remember_grid_failure(self,doc.id)
            self.repaint.request()
        # Failed thumbnails remain neutral placeholders, never equivalent Unicode emoji.
        future=self.app.worker.submit(fetch(),ready,lambda _:ready((None,None)))
        if future is not None and hasattr(self,'_loads'):self._loads[request]=future
    def click(self,event):
        self.canvas.focus_set()
        column=int(event.x//self.cell)
        if not 0<=column<self.columns:return 'break'
        index=int(self.canvas.canvasy(event.y)//self.cell)*self.columns+column
        if 0<=index<len(self.documents):
            self.selected=self.documents[index];self.repaint.request();self.activate(self.selected)
        return 'break'

    def navigate(self,direction):
        if not self.documents:return 'break'
        index=next((i for i,doc in enumerate(self.documents) if doc is self.selected),-1)
        if direction=='home':index=0
        elif direction=='end':index=len(self.documents)-1
        else:
            delta=-self.columns if direction=='up' else self.columns if direction=='down' else direction
            index=0 if index<0 else max(0,min(len(self.documents)-1,index+delta))
        self.selected=self.documents[index]
        y=(index//self.columns)*self.cell;top=self.canvas.canvasy(0);height=self.canvas.winfo_height()
        rows=(len(self.documents)+self.columns-1)//self.columns
        if y<top:self.canvas.yview_moveto(y/max(1,rows*self.cell))
        elif y+self.cell>top+height:self.canvas.yview_moveto((y+self.cell-height)/max(1,rows*self.cell))
        self.repaint.request()
        return 'break'


def document_send_allowed(app, peer, document, custom=False):
    """Cached send policy only; browsing/saving packs and chooser callbacks bypass it."""
    from .chat_capabilities import chat_capabilities
    capabilities = chat_capabilities(app, peer)
    if not custom:return capabilities.allows('send_stickers')
    if not capabilities.allows('send_text'):return False
    from .telegram_extras import emoji_attribute
    attribute = emoji_attribute(document)
    if attribute is None or not attribute.alt:return False
    if attribute.free is True or capabilities.premium or capabilities.kind == 'self':return True
    # Telegram's own client also permits a megagroup's assigned emoji pack.
    assigned = getattr(getattr(capabilities.full, 'emojiset', None), 'id', None)
    return (capabilities.kind == 'group' and type(assigned) is int and assigned > 0
            and assigned == getattr(attribute.stickerset, 'id', None))


def insert_selected_emoji(app,window,account,peer,document,*,backend=None):
    """Pickers retain the conversation they were opened for, including pack views."""
    if app.busy or peer is None or (account,peer)!=(app.ui_account,app.active) or not window.winfo_exists():return
    if backend is not None and backend is not app.service.backend:return
    if not document_send_allowed(app,peer,document,True):return
    from .telegram_extras import emoji_attribute
    attr=emoji_attribute(document)
    if attr is None:return
    selection=app.editor.tag_ranges('sel')
    if len(selection)==2:app.editor.delete(*selection)
    app.editor.insert_custom(document.id,attr.alt)
    window.destroy();app.editor.focus_set();app.editor.see('insert')


def send_selected_sticker(app, window, backend, account, peer, document):
    if app.busy or peer is None or (account,peer)!=(app.ui_account,app.active) or not window.winfo_exists(): return
    if backend is not getattr(getattr(app,'service',None),'backend',None) or not document_send_allowed(app,peer,document):return
    # No reply state exists until the user replies for the first time.
    reply=getattr(app,'reply_drafts',{}).get((account,peer))
    def sent(msg):
        app.clear_sent_reply(account,peer,reply)
        if account==app.ui_account:app.incoming((peer,msg))
        if window.winfo_exists():window.destroy()
    app.call(backend.send_sticker(peer,document,reply_to=reply),sent,tr('Enviando...'))


def open_picker(app,custom=False,on_choose=None):
    if app.busy or (app.active is None and on_choose is None):return
    backend,account,peer=app.service.backend,app.ui_account,app.active
    if app.demo:
        messagebox.showinfo(APP_NAME,tr('Connect an account to load Telegram packs.'),parent=app.root);return
    from .i18n import get_language
    from .sticker_search import (
        PickerRequests,
        matching_documents,
        matching_packs,
        search,
        unique,
    )
    window,frame=app.dialog('Custom emoji' if custom else 'Stickers','640x650')
    query=tk.StringVar(master=window)
    ttk.Label(frame,text=tr('Search packs, keywords or an emoji')).pack(anchor='w')
    from .native_emoji import search_entry
    entry=search_entry(frame,app,query)
    chooser=Choice(frame,values=[]);chooser.pack(fill='x')
    status=ttk.Label(frame,text=tr('Loading...'));status.pack(anchor='w')
    selected=[None];state={'packs':[],'choices':[],'results':[],'next':None}
    def current():return account==app.ui_account and backend is app.service.backend and (on_choose is not None or peer==app.active)
    requests=PickerRequests(app,window,current);catalogue=PickerRequests(app,window,current)
    def choose(document):
        if not current() or app.busy or document is None:return
        if on_choose:window.destroy();on_choose(document);return
        if custom:insert_selected_emoji(app,window,account,peer,document,backend=backend)
        else:send_selected_sticker(app,window,backend,account,peer,document)
    def usable(document):
        return document is not None and current() and (on_choose is not None or document_send_allowed(app,peer,document,custom))
    def show_use(document):
        if usable(document):use_button.pack(side='right')
        else:use_button.pack_forget()
    def activate(document):
        selected[0]=document
        show_use(document)
        if not current():return
        entries=[]
        if usable(document):entries.append((tr('Insert emoji') if custom else tr('Send sticker'),lambda:choose(document)))
        entries.append((tr('View pack'),lambda:app.show_document_pack(document) if current() else None))
        popup_menu(window,entries)
    grid=StickerGrid(frame,app,account,backend,activate,small=custom);grid.pack(fill='both',expand=True,pady=8)
    def display(docs):
        selected[0]=None;show_use(None);grid.set_documents(docs)
        status.configure(text=str(len(docs))+' · '+tr('Custom emoji' if custom else 'Stickers'))
    def failed(exc):status.configure(text=tr('Search failed.'))
    def options(packs,searching=False):
        # Like Telegram: open on the recent / most used ones, then favourites, then each pack.
        if searching:first,names=[None],[tr('Search results')]
        elif custom:first,names=['recent_emoji'],[tr('Recent')]
        else:first,names=[None,'favourites'],[tr('Recent'),tr('Favorites')]
        state['choices']=first+list(packs)
        labels=names+[p.title for p in packs]
        chooser.configure(values=labels)
        if labels:chooser.current(0)
        else:chooser.set('')
    def change(_=None):
        i=chooser.current()
        if not current():return
        if not 0<=i<len(state['choices']):display([]);return
        pack=state['choices'][i]
        if pack is None and query.get().strip():
            requests.cancel();display(state['results']);more.configure(state='normal' if state['next'] is not None else 'disabled');return
        more.configure(state='disabled');status.configure(text=tr('Loading...'))
        requests.load(lambda:backend.sticker_documents(pack),display,failed)
    def search_changed(*_):
        value=query.get().strip();requests.cancel();state['next']=None;more.configure(state='disabled')
        if not value:options(state['packs']);change();return
        local_packs=matching_packs(state['packs'],value)
        local_docs=matching_documents(grid.documents,value)
        state['results']=local_docs;options(local_packs,True);display(local_docs)
        status.configure(text=tr('Loading...'))
        def found(result):
            state['results']=unique(local_docs+result['documents']);state['next']=result['next']
            options(unique(local_packs+result['packs']),True);display(state['results'])
            more.configure(state='normal' if state['next'] is not None else 'disabled')
        requests.load(lambda:search(backend,value,custom,get_language()),found,failed,delay=300)
    def next_page():
        offset=state['next'];value=query.get().strip()
        if offset is None or not value:return
        more.configure(state='disabled');status.configure(text=tr('Loading...'))
        def found(result):
            previous=len(state['results']);state['results']=unique(state['results']+result['documents'])
            state['next']=result['next'] if len(state['results'])>previous else None
            position=grid.canvas.canvasy(0)
            display(state['results'])
            height=max(1,((len(grid.documents)+grid.columns-1)//grid.columns)*grid.cell)
            grid.canvas.yview_moveto(position/height)
            more.configure(state='normal' if state['next'] is not None else 'disabled')
        requests.load(lambda:search(backend,value,custom,get_language(),offset),found,failed)
    more=ttk.Button(frame,text=tr('More'),command=next_page,state='disabled');more.pack(fill='x')
    ttk.Label(frame,text=tr('Some emoji require Telegram Premium.')).pack(anchor='w')
    ttk.Button(frame,text=tr('View pack'),command=lambda:app.show_document_pack(selected[0]) if selected[0] else None).pack(side='left')
    use_button=ttk.Button(frame,text=tr('Insert emoji') if custom else tr('Send sticker'),command=lambda:choose(selected[0]))
    chooser.bind('<<ComboboxSelected>>',change);query.trace_add('write',search_changed)
    def packs_loaded(packs):
        state['packs']=packs
        if not query.get().strip():options(packs);change()
    catalogue.load(lambda:backend.sticker_packs(custom),packs_loaded,failed)
    window.bind('<Destroy>',lambda e:(requests.cancel(),catalogue.cancel()) if e.widget is window else None,add='+')
    entry.focus_set()


def show_pack(app,document):
    if app.busy or app.demo:return
    backend,account,peer=app.service.backend,app.ui_account,app.active
    from .sticker_search import PickerRequests
    window,frame=app.dialog(tr('View pack'),'620x570')
    loading=ttk.Label(frame,text=tr('Loading...'));loading.pack(fill='x')
    requests=PickerRequests(app,window,lambda:account==app.ui_account and backend is app.service.backend)
    window.bind('<Destroy>',lambda e:requests.cancel() if e.widget is window else None,add='+')
    def loaded(result):
        if account!=app.ui_account or backend is not app.service.backend or not window.winfo_exists():return
        loading.destroy();pack=result.set;window.title(pack.title)
        ttk.Label(frame,text=pack.title,style='Title.TLabel').pack(fill='x')
        ttk.Label(frame,text=str(len(result.documents))+' · '+tr('Custom emoji' if pack.emojis else 'Stickers')).pack(fill='x')
        selected=[None]
        def use(document):
            if document is None:return
            if pack.emojis:insert_selected_emoji(app,window,account,peer,document,backend=backend)
            else:send_selected_sticker(app,window,backend,account,peer,document)
        def activate(document):
            selected[0]=document
            if backend is app.service.backend and peer is not None and (account,peer)==(app.ui_account,app.active) and document_send_allowed(app,peer,document,bool(pack.emojis)):
                use_button.pack(fill='x',pady=4,before=button)
                popup_menu(window,[(tr('Insert emoji') if pack.emojis else tr('Send sticker'),lambda:use(document))])
            else:use_button.pack_forget()
        grid=StickerGrid(frame,app,account,backend,activate,small=bool(pack.emojis))
        grid.pack(fill='both',expand=True,pady=8);grid.set_documents(result.documents)
        use_button=ttk.Button(frame,text=tr('Insert emoji') if pack.emojis else tr('Send sticker'),command=lambda:use(selected[0]))
        installed=bool(pack.installed_date) and not pack.archived
        def install():
            if app.busy or account!=app.ui_account or backend is not app.service.backend:return
            def done(result):
                if not window.winfo_exists():return
                button.configure(text=tr('Pack saved'),state='disabled')
                if getattr(result,'sets',None):
                    messagebox.showinfo(APP_NAME,tr('Telegram archived older packs to make room for this pack.'),parent=window)
            app.call(backend.install_pack(pack),done,tr('Guardando...'))
        button=ttk.Button(frame,text=tr('Pack saved' if installed else 'Save pack'),command=install,state='disabled' if installed else 'normal')
        button.pack(fill='x',pady=6)
    requests.load(lambda:backend.document_pack(document),loaded,lambda _:loading.configure(text=tr('Search failed.')))
