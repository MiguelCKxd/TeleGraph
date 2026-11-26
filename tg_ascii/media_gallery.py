"""Cancellable image galleries that share the active account without blocking chat."""
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
import shutil
from tkinter import ttk

from telethon import types
from .app_dialogs import filedialog
from .i18n import tr


@dataclass(frozen=True)
class GalleryItem:
    ident:int
    media:object
    caption:str=''
    filename:str=''
    topic_id:int|None=None  # 3.3: forum topic of the message, for "Go to message"
    kind:str='image'
    message:object=None  # Preserve message-level auto-delete/protection metadata.


class ProfileSource:
    """Only three small metadata pages remain in memory, however long the history."""
    def __init__(self,backend,peer,photo,name):
        self.backend,self.peer,self.initial,self.name=backend,peer,photo,name
        self.pages=OrderedDict();self.prefix=None;self.total=None
    async def page(self,offset):
        from .profile_media import profile_history
        if offset not in self.pages:
            photos,total=await profile_history(self.backend,self.peer,offset,20)
            self.pages[offset]=photos
            if total is not None:self.total=total
            while len(self.pages)>3:self.pages.popitem(last=False)
        self.pages.move_to_end(offset)
        return self.pages[offset]
    async def at(self,index):
        if index<0:return None
        if self.prefix is None:
            first=await self.page(0)
            self.prefix=bool(self.initial is not None and (not first or first[0].id!=self.initial.id))
        if self.prefix and index==0:photo=self.initial
        else:
            offset=index-int(self.prefix)
            if self.total is not None and offset>=self.total:return None
            page=await self.page(offset//20*20)
            if offset%20>=len(page):return None
            photo=page[offset%20]
        return GalleryItem(photo.id,photo,self.name,f'profile-{photo.id}.jpg')


class ChatSource:
    def __init__(self,backend,peer,kind='media',query=''):
        self.backend,self.peer,self.kind,self.query=backend,peer,kind,query
        self.neighbors=OrderedDict()
        self.filter={'media':types.InputMessagesFilterPhotoVideo,'photos':types.InputMessagesFilterPhotos,
                     'videos':types.InputMessagesFilterVideo}[kind]
    async def neighbor(self,item,direction):
        # One small metadata page serves successive swipes, without downloading
        # adjacent media. Keep a bounded set of known contiguous links.
        key=(item.ident,direction)
        if key in self.neighbors:
            self.neighbors.move_to_end(key)
            return self.neighbors[key]
        options={'max_id':item.ident} if direction>0 else {'min_id':item.ident,'reverse':True}
        from .secret_chats import is_secret_peer
        if is_secret_peer(self.peer):
            self.backend.secret_chats._prune_expired_sync()
            session=self.backend.secret_chats.session_for_peer(self.peer)
            kinds={'media':('image','video'),'photos':('image',),'videos':('video',)}[self.kind]
            rows=[row for row in session.messages if row.get('media_kind') in kinds and
                  (row['id']<item.ident if direction>0 else row['id']>item.ident) and
                  (not self.query or self.query.casefold() in (row.get('text','')+' '+row.get('filename','')).casefold())]
            if not rows:return None
            row=(max if direction>0 else min)(rows,key=lambda value:value['id'])
            message=self.backend.secret_chats._record_to_message(session,row)
        else:
            rows=await self.backend.client.get_messages(self.peer,limit=20,filter=self.filter(),search=self.query,**options)
            previous=item
            first=None
            for row in rows:
                message=self.backend.message(row)
                current=GalleryItem(message.id,message.media,message.text,message.filename,getattr(message,'topic_id',None),getattr(message,'media_kind','image'),message)
                self.neighbors[(previous.ident,direction)]=current
                self.neighbors[(current.ident,-direction)]=previous
                if first is None:first=current
                previous=current
            if len(rows)<20:self.neighbors[(previous.ident,direction)]=None
            while len(self.neighbors)>120:self.neighbors.popitem(last=False)
            return first
        return GalleryItem(message.id,message.media,message.text,message.filename,getattr(message,'topic_id',None),getattr(message,'media_kind','image'),message)


class MediaGallery:
    def __init__(self,app,peer,item,*,profile=False,path=None,kind='media',query=''):
        self.app,self.account,self.backend,self.peer=app,app.ui_account,app.service.backend,peer
        self.item=item;self.index=0;self.path=None;self.profile=profile;self.original=False
        self.stream=None;self.lease=None
        self.source=ProfileSource(self.backend,peer,item.media,item.caption) if profile else ChatSource(self.backend,peer,kind,query)
        from .media_viewer import show_image
        from .contact_profile import ProfileRequests
        self.window=show_image(app.root,None,item.caption,navigate=self.navigate,name=item.filename or None,
            on_error=lambda error:app.worker.events.put((app.show_error,error)) if hasattr(app,'worker') else None)
        self.window._media_gallery=self
        self.window._media_error=self.stream_failed
        self.window._open_native=self.open_native
        self.requests=ProfileRequests(app,self.window,self.account,self.backend)
        self.window.bind('<Destroy>',self.closed,add='+')
        self.status=ttk.Label(self.window,text=tr('Loading...'));self.status.pack(fill='x',padx=16)
        controls=ttk.Frame(self.window);controls.pack(fill='x',padx=16,pady=8)
        self.save_button=ttk.Button(controls,text=tr('Guardar archivo como...'),command=self.save,state='disabled');self.save_button.pack(side='left')
        ttk.Button(controls,text=tr('Retry'),command=self.refresh).pack(side='right')
        if not profile:ttk.Button(controls,text=tr('Go to message'),command=self.go_to).pack(side='left')
        if hasattr(app,'popups'):app.popups.append(self.window)
        if path:self.loaded(path,item)
        if item.media is not None:self.load(item)
        else:self.navigate(0)
    def valid(self):return self.requests.valid()
    def closed(self,event):
        if event.widget is self.window:
            self.requests.close()
            if getattr(self,'lease',None) is not None:self.lease.close()
    def expired(self):
        self.requests.reset()
        if self.stream is not None:self.stream.abort();self.stream=None
        self.path=None
        self.window._set_media(None,'',preserve_view=True)
        self.save_button.configure(state='disabled')
        self.status.configure(text=tr('El archivo ya no esta disponible.'))
    def exportable(self):
        lease=getattr(self,'lease',None)
        return lease is None or (not lease.closed and not lease.export_blocked)
    def go_to(self):
        if self.valid():
            from .desktop_forums import reveal_in_context
            reveal_in_context(self.app,self.peer,self.item.ident,getattr(self.item,'topic_id',None))
    def save(self):
        if not self.valid() or (self.path is None and self.stream is None):return
        if not self.exportable():self.status.configure(text=tr('Protected content'));return
        path=self.path
        from .media_formats import download_name
        name=download_name(self.item.media,self.item.filename)
        # Markup avatars are generated PNGs; never disguise them as JPEG files.
        if self.profile:name='profile'+path.suffix
        destination=filedialog.asksaveasfilename(parent=self.window,initialfile=name)
        if destination and self.valid():
            item=self.item;is_original=path is not None and (self.profile or self.original)
            async def save_original():
                import asyncio
                original=path if is_original else await self.download(item,'original')
                if not self.exportable():raise PermissionError(tr('Protected content'))
                await asyncio.to_thread(shutil.copyfile,original,destination)
            self.requests.submit('save',save_original(),lambda _:None,self.failed,timeout=None)
    def open_native(self):
        if not self.valid():return
        if not self.exportable():self.status.configure(text=tr('Protected content'));return
        item=self.item
        path=self.path if self.original or self.profile else None
        async def original():return path if path is not None else await self.download(item,'original')
        def opened(result):
            if not self.exportable():self.status.configure(text=tr('Protected content'));return
            from .native_open import open_with_system
            lease=getattr(self,'lease',None)
            if lease is not None:lease.retain_copy()
            open_with_system(result,item.filename or item.caption,
                on_error=lambda error:self.app.worker.events.put((lambda exc:self.failed(exc) if self.valid() else None,error)),
                on_done=(lambda:self.app.worker.events.put((lambda _:lease.release_copy(),None))) if lease is not None else None)
        self.requests.submit('native',original(),opened,self.failed,timeout=None)
    def stream_failed(self,error):
        if self.stream is None or not self.valid():return False
        self.stream.abort()
        self.stream=None
        self.window._set_media(None,self.item.caption,preserve_view=True)
        self.load(self.item,stream=False)
        return True
    def refresh(self):
        if not self.valid():return
        if self.profile:self.source.pages.clear();self.source.prefix=None;self.source.total=None
        self.load(self.item,refresh=True)
    def failed(self,error):
        self.status.configure(text=tr('Search failed.')+' '+str(error))
        self.save_button.configure(state='normal' if self.path and self.exportable() else 'disabled')
    def loaded(self,path,item):
        if item is not self.item or not self.valid():return
        lease=getattr(self,'lease',None)
        if lease is not None and not lease.active():lease.expire();return
        from .video_stream import StreamDescriptor,StreamingFrames
        if isinstance(path,StreamDescriptor):
            from dataclasses import replace
            # This guard uses plain state only: decoding threads never call Tk.
            lease=getattr(self,'lease',None)
            path=replace(path,current=lease.active if lease is not None else lambda:self.account==self.app.ui_account and
                not getattr(self.app,'closed',False) and not getattr(self.app,'closing',False))
            self.stream=StreamingFrames(path);self.path=None;self.original=False
            self.window._set_media(self.stream,item.caption,preserve_view=True)
        else:
            self.stream=None;self.path=Path(path);self.window._set_media(path,item.caption,preserve_view=True)
        lease=getattr(self,'lease',None)
        if lease is not None:lease.viewed()
        self.save_button.configure(state='normal' if self.exportable() else 'disabled');self.status.configure(text=str(self.index+1) if self.profile else tr('Videos' if item.kind=='video' else 'Photos'))
    async def download(self,item,quality,refresh=False,*,lease=None):
        from .media_cache import media_identity
        lease=lease if lease is not None else getattr(self,'lease',None)
        from .desktop_media_lifetime import source_message
        media=await source_message(self.backend,self.peer,item.ident) if refresh else item.media
        if lease is not None:
            if refresh:lease.update(media)
            lease.check()
            if lease.restricted:return await lease.download(media,quality=quality)
        identity=media_identity(item.media)
        suffix='-'.join(map(str,identity)) if identity else str(item.ident)
        target=self.app.preview_dir/f'{self.account}-{self.peer}-{suffix}-gallery-{quality}.media'
        original=self.app.preview_dir/f'{self.account}-{self.peer}-{suffix}-gallery-original.media'
        if not refresh:
            for candidate in (original,target):
                if candidate.is_file() and candidate.stat().st_size:return candidate
        from telethon.errors import FileReferenceExpiredError,FileReferenceInvalidError,FileReferenceEmptyError
        try:return await self.backend.download_media(media,target,quality=quality)
        except (FileReferenceExpiredError,FileReferenceInvalidError,FileReferenceEmptyError):
            media=await source_message(self.backend,self.peer,item.ident)
            if lease is not None:
                lease.update(media)
                if lease.restricted:return await lease.download(media,quality=quality)
            return await self.backend.download_media(media,target,quality=quality)
    def load(self,item,refresh=False,*,stream=True):
        if not self.valid():return
        previous=getattr(self,'lease',None)
        if previous is not None:previous.close()
        self.requests.reset()
        if not self.profile:
            from .desktop_media_lifetime import ViewerMedia
            self.lease=ViewerMedia(self.app,self.window,self.account,self.backend,self.peer,item.ident,
                                   item.message or item.media,self.expired)
        lease=getattr(self,'lease',None)
        if getattr(self,'stream',None) is not None:
            self.stream.abort();self.stream=None
            self.window._set_media(None,item.caption,preserve_view=True)
        self.path=None;self.save_button.configure(state='disabled');self.status.configure(text=tr('Downloading...'))
        from .advanced_features import feature_enabled
        from .media_cache import media_identity
        identity=media_identity(item.media)
        quality='display' if identity and identity[0]=='p' and not feature_enabled(self.app,'media_originals') else 'original'
        self.original=quality=='original'
        async def download():
            if self.profile:
                from .profile_media import prepare_profile_photo
                photo=item.media
                if refresh:
                    replacement=await self.source.at(self.index)
                    if replacement is not None and replacement.ident==item.ident:photo=replacement.media
                return await prepare_profile_photo(self.app,self.backend,self.account,self.peer,photo)
            if stream and item.kind=='video':
                from .video_stream import describe
                from telethon import errors
                try:
                    from .secret_chats import is_secret_peer
                    raw=item.media if is_secret_peer(self.peer) else await self.backend.media_message(self.peer,item.ident)
                    lease.update(raw)
                    descriptor=await describe(self.backend,self.peer,item.ident,raw)
                except (OSError,TimeoutError,errors.RPCError):descriptor=None
                if descriptor is not None:
                    if lease.restricted:
                        from dataclasses import replace
                        descriptor=replace(descriptor,cacheable=False)
                    return descriptor
            return await self.download(item,quality,refresh,lease=lease)
        self.requests.submit('image',download(),lambda path:self.loaded(path,item),self.failed,timeout=None)
    def navigate(self,direction):
        if not self.valid() or 'navigate' in self.requests.jobs:return
        wanted=self.index+direction;item=self.item
        self.status.configure(text=tr('Loading...'))
        operation=self.source.at(wanted) if self.profile else self.source.neighbor(item,direction)
        def loaded(next_item):
            if next_item is None:
                self.status.configure(text=tr('No results.'));return
            self.index=wanted;self.item=next_item;self.window._reset_media_view();self.load(next_item)
        self.requests.submit('navigate',operation,loaded,self.failed)


def open_profile_gallery(app,peer,profile,path=None):
    photo=profile.get('display_photo')
    item=GalleryItem(getattr(photo,'id',0),photo,profile.get('name',''),'profile.jpg')
    return MediaGallery(app,peer,item,profile=True,path=path)


def open_chat_gallery(app,message,peer=None,*,kind='media',query=''):
    item=GalleryItem(message.id,message.media,message.text,message.filename,getattr(message,'topic_id',None),getattr(message,'media_kind','image'),message)
    return MediaGallery(app,app.active if peer is None else peer,item,kind=kind,query=query)
