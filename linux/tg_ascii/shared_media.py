"""Peer-scoped shared media, with independent paginated requests per category."""
from .advanced_features import profile_feature_enabled
import asyncio
import tkinter as tk
from tkinter import ttk
from .app_dialogs import Choice
from .scrolling import FlowFrame
from .i18n import tr
from .sticker_picker import StickerGrid
from .resources import cache_entries


class SharedPhotoGrid(StickerGrid):
    """Only visible photos own Tk images or queue thumbnail downloads."""
    def __init__(self,parent,app,account,backend,peer,activate):
        super().__init__(parent,app,account,backend,activate)
        self.peer=peer;self.cell=164

    def set_messages(self,messages):
        messages=list(messages)
        if len(messages)>=len(self.documents) and all(
                old.id==new.id for old,new in zip(self.documents,messages)):
            self.documents=messages;self.layout()  # More keeps scroll, tiles and photos.
        else:self.set_documents(messages)

    def load(self,message):
        from .media_retry import grid_failed_recently,remember_grid_failure
        epoch=self.version;request=(epoch,message.id)
        if self.account!=self.app.ui_account or request in self.pending or grid_failed_recently(self,message.id) or len(self.pending)>=8:return
        self.pending.add(request)
        key=(self.account,self.peer,message.id,'mosaic')
        async def fetch():
            from pathlib import Path
            if self.app.preview_slots is None:self.app.preview_slots=asyncio.Semaphore(2)
            async with self.app.preview_slots:
                if epoch!=self.version or message.id not in self._wanted:return None
                path=self.app.preview_cache.get(key) or self.app.preview_dir/f'{self.account}-{self.peer}-{message.id}-mosaic.jpg'
                if not Path(path).is_file():
                    path=await self.backend.download_media(message.media,path,thumbnail=True)
                if epoch!=self.version or message.id not in self._wanted:return None
                frames=await asyncio.to_thread(self.app.animation_player.prepare,path,(150,150),False) if path else None
                return path,frames
        def ready(result):
            self.pending.discard(request);self._loads.pop(request,None)
            if not self.winfo_exists():return
            if epoch!=self.version or self.account!=self.app.ui_account or message.id not in self._wanted:
                self.repaint.request();return
            if result is None:self.repaint.request();return
            path,frames=result
            try:
                photo=self.app.animation_player.photo(path,(150,150),False,prepared=frames,owner=self) if path else None
            except (OSError,ValueError,tk.TclError):photo=None
            if photo:
                self.photos[message.id]=photo
                self.app.preview_cache[key]=path
                while len(self.app.preview_cache)>cache_entries(512):self.app.preview_cache.pop(next(iter(self.app.preview_cache)))
            else:remember_grid_failure(self,message.id)
            self.repaint.request()
        future=self.app.worker.submit(fetch(),ready,lambda _:ready((None,None)))
        if future is not None:self._loads[request]=future


class MediaPages:
    def __init__(self,kinds):
        self.rows={kind:[] for kind in kinds};self.queries={};self.pending={};self.more={kind:True for kind in kinds};self.serial=0
        self.offsets={kind:0 for kind in kinds}
    def begin(self,kind,query,more=False):
        if more and (kind in self.pending or self.queries.get(kind)!=query or not self.more[kind]):return None
        self.serial+=1;ticket=(self.serial,kind,query,more)
        self.pending[kind]=ticket
        offset=self.offsets[kind] if more else 0
        return ticket,offset
    def finish(self,ticket,items):
        _,kind,query,more=ticket
        if self.pending.get(kind)!=ticket:return False
        self.pending.pop(kind);self.queries[kind]=query
        if not more:self.rows[kind]=[]
        seen={m.id for m in self.rows[kind]};new=[]
        for item in items:
            if item.id not in seen:new.append(item);seen.add(item.id)
        previous=self.offsets[kind] if more else 0
        self.offsets[kind]=getattr(items,'next_offset',items[-1].id if items else previous)
        self.rows[kind].extend(new)
        self.more[kind]=bool(getattr(items,'more',len(items)==50 and bool(new))) and self.offsets[kind]!=previous
        return True
    def fail(self,ticket):
        kind=ticket[1]
        if self.pending.get(kind)!=ticket:return False
        self.pending.pop(kind);return True


class SharedMediaBrowser:
    def __init__(self,app,media,peer):
        self.app=app;self.peer=peer;self.account=app.ui_account;self.backend=app.service.backend
        self.window,outer=app.dialog('Shared media' if media else 'Search in chat','730x650')
        from .advanced_features import feature_enabled
        entries=[('photos','Photos'),('files','Files'),('audio','Audio'),('voice','Voice messages'),('gifs','GIFs')]
        if feature_enabled(app,'links'):entries.append(('links','Links'))
        if feature_enabled(app,'polls'):entries.append(('polls','Encuestas'))
        chat=next((c for c in getattr(app,'chats',()) if c.id==peer),None)
        if chat is not None and chat.kind=='channel':entries.append(('similar','Canales similares'))
        if not media:entries=[('all','Messages')]
        self.kinds=[kind for kind,_ in entries];names=[name for _,name in entries]
        self.pages=MediaPages(self.kinds);self.widgets={};self._requests={}
        controls=FlowFrame(outer);controls.pack(side='bottom',fill='x',pady=5)
        self.status=tk.StringVar();ttk.Label(outer,textvariable=self.status,wraplength=580).pack(side='bottom',fill='x')
        self.query=app.field(outer,'Search in chat',emoji=True)
        self.selector=Choice(outer,values=[tr(v) for v in names]);self.selector.current(0)
        self.tabs=ttk.Notebook(outer);self.tabs.pack(fill='both',expand=True)
        ttk.Style(outer).layout('Hidden.TNotebook.Tab',[])
        self.compact=None
        for kind,label in zip(self.kinds,names):
            page=ttk.Frame(self.tabs);self.tabs.add(page,text=tr(label))
            if kind=='photos':
                self.widgets[kind]=SharedPhotoGrid(page,app,self.account,self.backend,self.peer,
                    lambda message:app.open_image_message(message,self.peer) if self.valid() and not app.busy else None)
                self.widgets[kind].pack(fill='both',expand=True)
            else:
                listing=tk.Listbox(page,exportselection=False,height=10);listing.pack(side='left',fill='both',expand=True)
                bar=ttk.Scrollbar(page,command=listing.yview);bar.pack(side='right',fill='y');listing.configure(yscrollcommand=bar.set)
                listing.bind('<Double-Button-1>',lambda _:self.open());listing.bind('<Return>',lambda _:self.open());self.widgets[kind]=listing
        for label,callback in [('Search',self.fetch),('More',lambda:self.fetch(True)),('Open',self.open),('Go to message',lambda:self.open(True))]:
            ttk.Button(controls,text=tr(label),command=callback).pack(side='left')
        self.selector.bind('<<ComboboxSelected>>',lambda _:self.tabs.select(self.selector.current()))
        self.tabs.bind('<<NotebookTabChanged>>',self.changed);self.tabs.bind('<Configure>',self.resize)
        self.query.entry.bind('<Return>',lambda _:self.fetch());self.window.after_idle(self.changed)
        from .secret_chats import is_secret_peer
        self.search_scope = None if is_secret_peer(peer) else f'messages:{peer}'
        from .recent_search_ui import RecentStrip
        if self.search_scope:
            RecentStrip(app,outer,self.query,self.search_scope,pick=lambda _:self.fetch(),before=self.tabs)
        self.window.bind('<Destroy>',self.close,add='+')
    def close(self,event=None):
        if event is not None and event.widget is not self.window:return
        for future in self._requests.values():future.cancel()
        self._requests.clear();self.pages.pending.clear()
    def valid(self):return self.window.winfo_exists() and self.account==self.app.ui_account and self.backend is self.app.service.backend
    def kind(self):return self.kinds[self.tabs.index(self.tabs.select())]
    def resize(self,event):
        compact=event.width<620
        if compact==self.compact:return
        self.compact=compact;self.tabs.configure(style='Hidden.TNotebook' if compact else 'TNotebook')
        if compact:self.selector.pack(fill='x',before=self.tabs,pady=4)
        else:self.selector.pack_forget()
    def changed(self,event=None):
        if not self.valid() or not self.tabs.select():return
        kind=self.kind();self.selector.current(self.kinds.index(kind))
        if self.pages.queries.get(kind)!=self.query.get() and kind not in self.pages.pending:self.fetch()
        else:self.status.set(tr('Loading...') if kind in self.pages.pending else str(len(self.pages.rows[kind])))
    def fetch(self,more=False):
        if not self.valid():return
        kind=self.kind()
        if not profile_feature_enabled(self.app,kind):return
        query=self.query.get();request=self.pages.begin(kind,query,more)
        if not more and query.strip() and self.search_scope:
            from .recent_search_ui import remember
            remember(self.app,self.search_scope,query)
        if request is None:return
        ticket,offset=request;self.status.set(tr('Loading...'))
        previous=self._requests.pop(kind,None)
        if previous is not None:previous.cancel()
        def loaded(items):
            if not profile_feature_enabled(self.app,kind):self.pages.fail(ticket);return
            if not self.valid() or not self.pages.finish(ticket,items):return
            self._requests.pop(kind,None)
            self.render(kind)
            if kind==self.kind():self.status.set(str(len(self.pages.rows[kind])))
        def failed(exc):
            if self.valid() and self.pages.fail(ticket):
                self._requests.pop(kind,None)
                if kind==self.kind():self.status.set(tr('Search failed.'))
                self.app.show_error(exc)
        async def request():
            if kind=='similar':return await asyncio.wait_for(self.backend.similar_channels(self.peer),30)
            return await asyncio.wait_for(self.backend.search_messages(self.peer,query,kind,offset),30)
        future=self.app.worker.submit(request(),loaded,failed)
        if future is not None:self._requests[kind]=future
    def render(self,kind):
        target=self.widgets[kind]
        if kind=='photos':
            target.set_messages(self.pages.rows[kind])
        else:
            target.delete(0,'end')
            for message in self.pages.rows[kind]:target.insert('end',self.app.text_display(message.name if kind=='similar' else message.filename or message.text[:120],True))
    def open(self,jump=False):
        if not self.valid() or self.app.busy:return
        kind=self.kind()
        if not profile_feature_enabled(self.app,kind) or kind=='photos':return
        selected=self.widgets[kind].curselection()
        if not selected:return
        message=self.pages.rows[kind][selected[0]]
        if kind=='similar':
            self.app.call(self.backend.resolve_chat(message.id),lambda chat:self.app.open_resolved(chat) if self.valid() else None,tr('Cargando...'))
            return
        if jump or not message.media:self.app.jump_message(message.id,self.peer)
        else:self.app.view_message_media(message,self.peer)
