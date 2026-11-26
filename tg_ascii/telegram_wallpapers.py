"""Opt-in Telegram wallpaper gallery. Opening it only reads the server catalogue."""
import asyncio
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from .i18n import tr
from .preferences import write_json
from .wallpaper_render import fill_image, render_wallpaper


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
    from .contact_profile import ProfileRequests
    requests=ProfileRequests(app,window,account,backend)
    window.bind('<Destroy>',lambda event:requests.close() if event.widget is window else None,add='+')
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
        requests.reset()  # Retire downloads of the page the user just left.
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
            requests.submit(('wallpaper',record.id),fetch(),loaded,failed,timeout=None)
        previous.configure(state='normal' if page[0]>0 else 'disabled');following.configure(state='normal' if page[0]+12<len(records) else 'disabled')
        status.set(f'{page[0]+1}–{min(page[0]+12,len(records))} / {len(records)}' if records else tr('No backgrounds available'))
    def move(delta):page[0]=max(0,page[0]+delta);render()
    previous=ttk.Button(footer,text='‹',command=lambda:move(-12));previous.pack(side='left')
    following=ttk.Button(footer,text='›',command=lambda:move(12));following.pack(side='left')
    def loaded(items):
        if valid():records.extend(items);render()
    requests.submit('catalog',catalog(backend),loaded,lambda exc:status.set(str(exc)) if valid() else None)
