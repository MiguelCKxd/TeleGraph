"""Opt-in Telegram wallpaper gallery. Opening it only reads the server catalogue."""
import asyncio
import gzip
import io
import math
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from .i18n import tr
from .preferences import write_json


def fill_image(settings, size):
    from PIL import Image
    values=[getattr(settings,key,None) for key in ('background_color','second_background_color','third_background_color','fourth_background_color')]
    colors=[((v>>16)&255,(v>>8)&255,v&255) for v in values if v is not None]
    if not colors:colors=[(214,226,209)]
    if len(colors)==1:return Image.new('RGB',size,colors[0])
    # Render a stationary preview; Telegram's animated freeform gradients are not simulated.
    w,h=128,128;image=Image.new('RGB',(w,h));pixels=[]
    angle=math.radians(getattr(settings,'rotation',0) or 0)
    for y in range(h):
        for x in range(w):
            xx,yy=x/(w-1),y/(h-1)
            if len(colors)==2:
                t=max(0,min(1,.5+(yy-.5)*math.cos(angle)-(xx-.5)*math.sin(angle)))
                pixels.append(tuple(round(a*(1-t)+b*t) for a,b in zip(*colors)))
            else:
                a,b,c=colors[:3];d=colors[3] if len(colors)>3 else a
                pixels.append(tuple(round(a[k]*(1-xx)*(1-yy)+b[k]*xx*(1-yy)+c[k]*xx*yy+d[k]*(1-xx)*yy) for k in range(3)))
    image.putdata(pixels);return image.resize(size,Image.Resampling.BICUBIC)


def render_wallpaper(wallpaper, path, destination, size=(900,1200)):
    from PIL import Image,ImageOps,ImageFilter
    settings=getattr(wallpaper,'settings',None)
    if not getattr(wallpaper,'document',None):image=fill_image(settings,size)
    elif not getattr(wallpaper,'pattern',False):
        with Image.open(path) as source:
            if source.width*source.height>30_000_000:raise ValueError(tr('Image is too large'))
            source=ImageOps.exif_transpose(source).convert('RGB')
            if getattr(settings,'blur',False):source.thumbnail((450,450));source=source.filter(ImageFilter.BoxBlur(12))
            image=ImageOps.fit(source,size)
    else:
        mime=getattr(wallpaper.document,'mime_type','')
        if mime=='application/x-tgwallpattern':
            try:import resvg_py
            except ImportError:raise ValueError(tr('This background needs the SVG rendering engine.')) from None
            with gzip.open(path,'rb') as source:data=source.read(4*1024*1024+1)
            if len(data)>4*1024*1024:raise ValueError(tr('Image is too large'))
            # Wallpaper patterns contain vector paths, never external images or file references.
            import xml.etree.ElementTree as ET
            root=ET.fromstring(data)
            if any(node.tag.split('}')[-1] in ('image','script','foreignObject') or any(k.split('}')[-1]=='href' for k in node.attrib) for node in root.iter()):
                raise ValueError(tr('Unsupported background format'))
            source=Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=data.decode('utf-8'),width=size[0],height=size[1],skip_system_fonts=True)))
        else:source=Image.open(path)
        with source:
            if source.width*source.height>30_000_000:raise ValueError(tr('Image is too large'))
            pattern=ImageOps.fit(source.convert('RGBA'),size)
        mask=pattern.getchannel('A');intensity=getattr(settings,'intensity',50)
        intensity=50 if intensity is None else max(-100,min(100,intensity))
        if intensity<0:mask=ImageOps.invert(mask)
        mask=mask.point(lambda value:round(value*abs(intensity)/100))
        image=fill_image(settings,size);image.paste((0,0,0),(0,0,*size),mask)
    image.save(destination,format='JPEG',quality=90)
    return Path(destination)


async def catalog(backend):
    from telethon import functions
    result=await backend.client(functions.account.GetWallPapersRequest(hash=0))
    return sorted(getattr(result,'wallpapers',[]) or [],key=lambda item:not getattr(item,'default',False))


async def wallpaper_file(backend, wallpaper, directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    target=directory/f'telegram-wallpaper-{wallpaper.id}.jpg'
    doc=getattr(wallpaper,'document',None);path=None
    if doc:
        if getattr(doc,'size',0)>12*1024*1024:raise ValueError(tr('Image is too large'))
        path=await backend.download_media(doc,directory/f'telegram-wallpaper-{wallpaper.id}.source')
    return await asyncio.to_thread(render_wallpaper,wallpaper,path,target)


def selected_default(app, account):
    selected=app.wallpapers.get(f'{account}:telegram-default') if app.preferences.values.get('telegram_backgrounds',False) else None
    return selected or app.wallpapers.get(f'{account}:default')


def open_gallery(app, on_choose=None, enabled=None):
    from .scrolling import FlowFrame
    from .app_dialogs import scrollable
    if enabled is None:enabled=app.preferences.values.get('telegram_backgrounds',False)
    window,frame=app.dialog('Telegram backgrounds','660x620')
    if not enabled:
        ttk.Label(frame,text=tr('Enable Telegram chat backgrounds in Settings first.'),wraplength=540).pack(fill='x');return
    if app.demo or app.service.backend is None:
        ttk.Label(frame,text=tr('Connect a Telegram account to load backgrounds.'),wraplength=540).pack(fill='x');return
    account,backend=app.ui_account,app.service.backend
    def valid():return window.winfo_exists() and account==app.ui_account and backend is app.service.backend
    status=tk.StringVar(value=tr('Loading...'));ttk.Label(frame,textvariable=status,wraplength=540).pack(fill='x')
    body=scrollable(frame);grid=FlowFrame(body);grid.pack(fill='x')
    footer=FlowFrame(frame);footer.pack(fill='x',pady=5)
    records=[];page=[0];generation=[0];slots=asyncio.Semaphore(2)
    def select(path):
        if not valid():return
        preview,content=app.dialog('Preview and edit','540x560')
        image=app.load_photo(path,(400,380));label=ttk.Label(content,image=image or '');label.image=image;label.pack(fill='both',expand=True)
        ttk.Label(content,text=tr('All chats in this app') if on_choose is None else tr('Chat background'),wraplength=440).pack(fill='x')
        def apply():
            if not valid():return
            if on_choose:on_choose(path)
            else:
                from .interface_background import save_image
                target=save_image(path,app.preferences.path.parent/'wallpapers')
                updated=dict(app.wallpapers);updated[f'{account}:telegram-default']=str(target)
                try:
                    write_json(app.wallpapers_file,updated);app.preferences.save({'telegram_backgrounds':True})
                except OSError as exc:app.show_error(exc);return
                app.wallpapers=updated;app.refresh_wallpaper()
            preview.destroy();window.destroy()
        ttk.Button(content,text=tr('Apply'),command=apply).pack(fill='x',pady=8)
    def render():
        if not valid():return
        generation[0]+=1;epoch=generation[0]
        for child in grid.winfo_children():child.destroy()
        for record in records[page[0]:page[0]+12]:
            button=ttk.Button(grid,text=tr('Loading...'),state='disabled');button.pack(side='left',padx=4,pady=4)
            async def fetch(record=record):
                async with slots:return await wallpaper_file(backend,record,app.preview_dir/f'{account}-wallpapers')
            def loaded(path,button=button,epoch=epoch):
                if not valid() or epoch!=generation[0] or not button.winfo_exists():return
                button.image=app.load_photo(path,(128,160));button.configure(image=button.image or '',text='',command=lambda:select(path),state='normal')
            def failed(exc,button=button,epoch=epoch):
                if valid() and epoch==generation[0] and button.winfo_exists():
                    button.configure(text=tr('Unavailable'));status.set(str(exc))
            app.worker.submit(fetch(),loaded,failed)
        previous.configure(state='normal' if page[0]>0 else 'disabled');following.configure(state='normal' if page[0]+12<len(records) else 'disabled')
        status.set(f'{page[0]+1}–{min(page[0]+12,len(records))} / {len(records)}' if records else tr('No backgrounds available'))
    def move(delta):page[0]=max(0,page[0]+delta);render()
    previous=ttk.Button(footer,text='‹',command=lambda:move(-12));previous.pack(side='left')
    following=ttk.Button(footer,text='›',command=lambda:move(12));following.pack(side='left')
    def loaded(items):
        if valid():records.extend(items);render()
    app.worker.submit(catalog(backend),loaded,lambda exc:status.set(str(exc)) if valid() else None)
