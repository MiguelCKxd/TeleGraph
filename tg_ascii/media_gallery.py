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
    def __init__(self,backend,peer):self.backend,self.peer=backend,peer
    async def neighbor(self,item,direction):
        # Only adjacent metadata is requested. No chat-wide media download or
        # history scan is triggered by opening an image.
        options={'max_id':item.ident} if direction>0 else {'min_id':item.ident,'reverse':True}
        rows=await self.backend.client.get_messages(self.peer,limit=1,filter=types.InputMessagesFilterPhotos(),**options)
        if not rows:return None
        message=self.backend.message(rows[0])
        return GalleryItem(message.id,message.media,message.text,message.filename)


class MediaGallery:
    def __init__(self,app,peer,item,*,profile=False,path=None):
        self.app,self.account,self.backend,self.peer=app,app.ui_account,app.service.backend,peer
        self.item=item;self.index=0;self.path=None;self.profile=profile
        self.source=ProfileSource(self.backend,peer,item.media,item.caption) if profile else ChatSource(self.backend,peer)
        from .media_viewer import show_image
        from .contact_profile import ProfileRequests
        self.window=show_image(app.root,None,item.caption,navigate=self.navigate,name=item.filename or None,
            on_error=lambda error:app.worker.events.put((app.show_error,error)) if hasattr(app,'worker') else None)
        self.window._media_gallery=self
        self.requests=ProfileRequests(app,self.window,self.account,self.backend)
        self.window.bind('<Destroy>',self.closed,add='+')
        self.status=ttk.Label(self.window,text=tr('Loading...'));self.status.pack(fill='x',padx=16)
        controls=ttk.Frame(self.window);controls.pack(fill='x',padx=16,pady=8)
        self.save_button=ttk.Button(controls,text=tr('Guardar archivo como...'),command=self.save,state='disabled');self.save_button.pack(side='left')
        ttk.Button(controls,text=tr('Actualizar'),command=self.refresh).pack(side='right')
        if not profile:ttk.Button(controls,text=tr('Go to message'),command=self.go_to).pack(side='left')
        if hasattr(app,'popups'):app.popups.append(self.window)
        if path:self.loaded(path,item)
        if item.media is not None:self.load(item)
        else:self.navigate(0)
    def valid(self):return self.requests.valid()
    def closed(self,event):
        if event.widget is self.window:self.requests.close()
    def go_to(self):
        if self.valid():self.app.jump_message(self.item.ident,self.peer)
    def save(self):
        if not self.valid() or self.path is None:return
        path=self.path
        from .media_formats import download_name
        name=download_name(self.item.media,self.item.filename)
        # Markup avatars are generated PNGs; never disguise them as JPEG files.
        if self.profile:name='profile'+path.suffix
        destination=filedialog.asksaveasfilename(parent=self.window,initialfile=name)
        if destination and self.valid():
            try:shutil.copyfile(path,destination)
            except OSError as error:self.app.show_error(error)
    def refresh(self):
        if not self.valid():return
        if self.profile:self.source.pages.clear();self.source.prefix=None;self.source.total=None
        self.load(self.item,refresh=True)
    def failed(self,error):
        self.status.configure(text=tr('Search failed.')+' '+str(error))
        self.save_button.configure(state='normal' if self.path else 'disabled')
    def loaded(self,path,item):
        if item is not self.item or not self.valid():return
        self.path=Path(path);self.window._set_media(path,item.caption)
        self.save_button.configure(state='normal');self.status.configure(text=str(self.index+1) if self.profile else tr('Photos'))
    def load(self,item,refresh=False):
        if not self.valid():return
        self.path=None;self.save_button.configure(state='disabled');self.status.configure(text=tr('Downloading...'))
        async def download():
            if self.profile:
                from .profile_media import prepare_profile_photo
                photo=item.media
                if refresh:
                    replacement=await self.source.at(self.index)
                    if replacement is not None and replacement.ident==item.ident:photo=replacement.media
                return await prepare_profile_photo(self.app,self.backend,self.account,self.peer,photo)
            target=self.app.preview_dir/f'{self.account}-{self.peer}-{item.ident}-gallery'
            # The extension is deliberately fixed: Telethon writes content, PIL/
            # AV detect its real format, and repeated navigation reuses the file.
            target=target.with_suffix('.media')
            if target.is_file() and target.stat().st_size and not refresh:return target
            media=await self.backend.media_message(self.peer,item.ident) if refresh else item.media
            from telethon.errors import FileReferenceExpiredError,FileReferenceInvalidError,FileReferenceEmptyError
            try:return await self.backend.download_media(media,target)
            except (FileReferenceExpiredError,FileReferenceInvalidError,FileReferenceEmptyError):
                media=await self.backend.media_message(self.peer,item.ident)
                return await self.backend.download_media(media,target)
        self.requests.submit('image',download(),lambda path:self.loaded(path,item),self.failed,timeout=None)
    def navigate(self,direction):
        if not self.valid() or 'navigate' in self.requests.jobs:return
        wanted=self.index+direction;item=self.item
        self.status.configure(text=tr('Loading...'))
        operation=self.source.at(wanted) if self.profile else self.source.neighbor(item,direction)
        def loaded(next_item):
            if next_item is None:
                self.status.configure(text=tr('No results.'));return
            self.index=wanted;self.item=next_item;self.load(next_item)
        self.requests.submit('navigate',operation,loaded,self.failed)


def open_profile_gallery(app,peer,profile,path=None):
    photo=profile.get('display_photo')
    item=GalleryItem(getattr(photo,'id',0),photo,profile.get('name',''),'profile.jpg')
    return MediaGallery(app,peer,item,profile=True,path=path)


def open_chat_gallery(app,message,peer=None):
    item=GalleryItem(message.id,message.media,message.text,message.filename)
    return MediaGallery(app,app.active if peer is None else peer,item)
