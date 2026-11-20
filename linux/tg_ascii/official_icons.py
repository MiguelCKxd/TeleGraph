"""Unmodified PNG artwork from Telegram's official downloadable logo collection."""
import asyncio
import hashlib
from html.parser import HTMLParser
import io
from pathlib import Path
import shutil
import urllib.parse
import urllib.request
import zipfile
from .i18n import tr

PAGE='https://telegram.org/tour/screenshots'
ARCHIVE='https://telegram.org/file/464001088/1/bI7AJLo7oX4.287931.zip/374fe3b0a59dc60005'
LOGO='https://telegram.org/img/t_logo.png'


def official_url(url):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname!='telegram.org' or parsed.username or parsed.password:
        raise ValueError('Unexpected icon source')
    return url


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        official_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def download(url,limit=20*1024*1024):
    request=urllib.request.Request(official_url(url),headers={'User-Agent':'TG-ASCII/desktop'})
    with urllib.request.build_opener(OfficialRedirect()).open(request,timeout=12) as response:
        official_url(response.geturl());data=response.read(limit+1)
    if len(data)>limit:raise ValueError('Icon download is too large')
    return data


class ArchiveLinks(HTMLParser):
    def __init__(self):super().__init__();self.links=[]
    def handle_starttag(self,tag,attrs):
        href=dict(attrs).get('href','')
        if tag=='a' and '.zip' in href:self.links.append(urllib.parse.urljoin(PAGE,href))


def import_collection(data, directory):
    from PIL import Image
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    choices=[];seen=set()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for entry in archive.infolist():
            if not entry.filename.lower().endswith('.png') or entry.filename.startswith('__MACOSX/') or not 0<entry.file_size<=4*1024*1024:continue
            payload=archive.read(entry)
            with Image.open(io.BytesIO(payload)) as image:
                if image.format!='PNG' or not 64<=min(image.size) or max(image.size)>2048:continue
                image.verify()
            digest=hashlib.sha256(payload).hexdigest()
            if digest in seen:continue
            seen.add(digest)
            # Never extract remote paths, and never redraw/recolour the official artwork.
            name='official-telegram-'+digest[:20]+'.png';target=directory/name;target.write_bytes(payload)
            label=Path(entry.filename).stem.replace('_',' ').replace('-',' ')
            choices.append((label,target))
            if len(choices)>=24:break
    return choices


def load_collection(directory):
    from PIL import Image
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    from .preferences import read_json,write_json
    manifest=directory/'official-telegram-icons.json'
    cached=read_json(manifest,{})
    if not isinstance(cached,dict):cached={}
    choices=[(label,directory/name) for name,label in cached.items() if Path(name).name==name and name.startswith('official-telegram-') and (directory/name).is_file()]
    if choices:return choices
    archive=ARCHIVE
    try:
        parser=ArchiveLinks();parser.feed(download(PAGE,1024*1024).decode('utf-8'))
        if parser.links:archive=official_url(parser.links[0])
    except (OSError,ValueError):pass
    try:choices=import_collection(download(archive),directory)
    except (OSError,ValueError,zipfile.BadZipFile):choices=[]
    if not choices:
        payload=download(LOGO,4*1024*1024)
        with Image.open(io.BytesIO(payload)) as image:
            if image.format!='PNG' or max(image.size)>2048:raise ValueError('Invalid icon')
            image.verify()
        target=directory/'official-telegram-blue.png';target.write_bytes(payload);choices=[('Telegram',target)]
    write_json(manifest,{path.name:label for label,path in choices})
    return choices


def copy_icon(path,directory):
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    target=directory/Path(path).name
    if Path(path).resolve()!=target.resolve():shutil.copyfile(path,target)
    return target


def select_icon(app,path,label):
    directory=app.preview_dir if app.demo else app.preferences.path.parent/'custom-icons'
    target=copy_icon(path,directory)
    app.preferences.save({'custom_icon':str(target),'official_icon_label':label})
    app.refresh_logo();app.update_logo_selection()


def open_official_icons(app):
    from tkinter import ttk
    from .scrolling import FlowFrame
    from .app_dialogs import scrollable
    window,frame=app.dialog('Official Telegram icons','650x600')
    from .app_dialogs import Choice
    platform=Choice(frame,values=['Telegram','Android','iOS']);platform.current(0);platform.pack(fill='x',pady=4)
    ttk.Label(frame,text=tr('Tg-As is an unofficial client. The ASCII icon remains the default.'),wraplength=560).pack(fill='x',pady=6)
    status=ttk.Label(frame,text=tr('Loading...'),wraplength=560);status.pack(fill='x')
    body=scrollable(frame);grid=FlowFrame(body);grid.pack(fill='x')
    generation=[0];pending=[None];closed=[False]
    def valid(epoch):return not closed[0] and epoch==generation[0] and window.winfo_exists()
    def loaded(choices,epoch):
        if not valid(epoch):return
        pending[0]=None
        for child in grid.winfo_children():child.destroy()
        status.configure(text=tr('Choose an icon'))
        def choose(path,label):
            if not valid(epoch):return
            generation[0]+=1;selected_epoch=generation[0]
            for button in grid.winfo_children():button.configure(state='disabled')
            status.configure(text=tr('Loading...'))
            directory=app.preview_dir if app.demo else app.preferences.path.parent/'custom-icons'
            async def copy():return await asyncio.to_thread(copy_icon,path,directory)
            def selected(target):
                if not valid(selected_epoch):return
                pending[0]=None
                try:app.preferences.save({'custom_icon':str(target),'official_icon_label':label})
                except OSError as exc:selection_failed(exc);return
                app.refresh_logo();app.update_logo_selection();window.destroy()
            def selection_failed(exc):
                if not valid(selected_epoch):return
                pending[0]=None
                # Recreate commands with the current generation after a failed copy/save.
                loaded(choices,selected_epoch);app.show_error(exc)
            pending[0]=app.worker.submit(copy(),selected,selection_failed)
        for label,path in choices:
            button=ttk.Button(grid,text=label,compound='top',command=lambda p=path,l=label:choose(p,l));button.image=None;button.pack(side='left',padx=6,pady=6)
            def photo_loaded(photo,button=button):
                button.image=photo;button.configure(image=photo or '')
            app.request_photo(path,(120,120),photo_loaded,owner=button,enabled=False,
                              valid=lambda button=button:valid(epoch) and bool(button.winfo_exists()))
    async def fetch(selected):
        directory=app.preview_dir/'official-icons' if app.demo else app.preferences.path.parent/'official-icons'
        if selected!='Telegram':
            from .mobile_icons import load_mobile_icons
            return await asyncio.to_thread(load_mobile_icons,selected,directory)
        bundled=Path(__file__).parent/'assets'
        if (bundled/'official-telegram-icons.json').is_file():return await asyncio.to_thread(load_collection,bundled)
        return await asyncio.to_thread(load_collection,directory)
    def failed(exc):
        if window.winfo_exists():status.configure(text=tr('Could not download official icons. Check your connection and try again.'))
    def start(_=None):
        if closed[0]:return
        if pending[0] is not None:pending[0].cancel();pending[0]=None
        generation[0]+=1;epoch=generation[0];selected=platform.get()
        for child in grid.winfo_children():child.destroy()
        status.configure(text=tr('Loading...'))
        pending[0]=app.worker.submit(fetch(selected),lambda choices:loaded(choices,epoch) if valid(epoch) else None,
                          lambda exc:failed(exc) if valid(epoch) else None)
    def close(event):
        if event.widget is not window:return
        closed[0]=True;generation[0]+=1
        if pending[0] is not None:pending[0].cancel();pending[0]=None
    window.bind('<Destroy>',close,add='+')
    platform.bind('<<ComboboxSelected>>',start)
    ttk.Button(frame,text=tr('Actualizar'),command=start).pack(fill='x',pady=5)
    start()
