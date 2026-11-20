"""A local interface image, separate from per-account Telegram chat wallpapers."""
import io
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import uuid
from .i18n import tr


def save_image(source, directory):
    """Keep our own decoded image: moving the user's source file must not break settings."""
    from PIL import Image, ImageOps
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    with Image.open(source) as image:
        if image.width*image.height>30_000_000:raise ValueError(tr('Image is too large'))
        image=ImageOps.exif_transpose(image).convert('RGB');image.thumbnail((2560,2560))
        target=directory/(uuid.uuid4().hex+'.jpg');image.save(target,quality=92)
    return target


def choose_interface_background(app, changed):
    from .app_dialogs import filedialog
    path=filedialog.askopenfilename(parent=app.root,filetypes=[(tr('Images'),'*.png *.jpg *.jpeg *.webp')])
    if not path:return
    from .image_tools import image_editor
    def accept(edited):
        try:
            directory=app.preview_dir if app.demo else app.preferences.path.parent/'interface-backgrounds'
            changed(str(save_image(edited,directory)))
        except (OSError,ValueError) as exc:app.show_error(exc)
    try:image_editor(app.root,path,app.preview_dir/(uuid.uuid4().hex+'.jpg'),accept,wallpaper=True)
    except (OSError,ValueError,ImportError) as exc:app.show_error(exc)


def chat_backdrop(app):
    # Availability only: the interface image must never be fitted again to a chat.
    for path in (getattr(app,'wallpaper_path',None),app.preferences.values.get('interface_background','')):
        if path and Path(path).is_file():return path
    return None


def pin_canvas_background(canvas):
    """Keep one image in viewport coordinates while content scrolls in either axis."""
    if canvas.find_withtag('wallpaper'):
        origin=(canvas.canvasx(0),canvas.canvasy(0))
        if getattr(canvas,'_wallpaper_origin',None)!=origin:
            canvas.coords('wallpaper',*origin);canvas._wallpaper_origin=origin


def reuse_canvas_background(canvas,key):
    if getattr(canvas,'_wallpaper_key',None)!=key or getattr(canvas,'wallpaper',None) is None:return False
    if not canvas.find_withtag('wallpaper'):
        canvas.create_image(canvas.canvasx(0),canvas.canvasy(0),image=canvas.wallpaper,anchor='nw',tags='wallpaper')
        canvas._wallpaper_origin=None
    # Incremental message renders may have lowered new bubble backgrounds.
    # The reused wallpaper must remain beneath those newly created items too.
    canvas.tag_lower('wallpaper')
    pin_canvas_background(canvas)
    return True


def canvas_background(canvas, picture, master, key=None):
    from PIL import ImageTk
    canvas.delete('wallpaper')
    canvas.wallpaper=ImageTk.PhotoImage(picture,master=master)
    canvas._wallpaper_key=key;canvas._wallpaper_origin=(canvas.canvasx(0),canvas.canvasy(0))
    canvas.create_image(canvas.canvasx(0),canvas.canvasy(0),image=canvas.wallpaper,anchor='nw',tags='wallpaper')
    canvas.tag_lower('wallpaper')


def _chat_picture(path,size):
    from PIL import Image
    from .image_tools import wallpaper_crop
    with Image.open(path) as image:
        if image.width*image.height>30_000_000:return None
        return wallpaper_crop(image,*size)


def request_chat_background(app,canvas,key):
    """One crop in flight per canvas; resize bursts retain only the latest key."""
    canvas._wallpaper_requested=key
    if reuse_canvas_background(canvas,key):return
    if canvas.find_withtag('wallpaper'):canvas.tag_lower('wallpaper')
    if getattr(canvas,'_wallpaper_loading',False) is True:return
    def start():
        request=canvas._wallpaper_requested
        if request is None or request==getattr(canvas,'_wallpaper_key',None) or request==getattr(canvas,'_wallpaper_failed_key',None):return
        if getattr(app,'closed',False) or getattr(app,'closing',False) or not canvas.winfo_exists():return
        canvas._wallpaper_loading=True
        async def prepare():
            import asyncio
            return await asyncio.to_thread(_chat_picture,request[1],request[-2:])
        def loaded(picture):
            canvas._wallpaper_loading=False
            if getattr(app,'closed',False) or getattr(app,'closing',False) or not canvas.winfo_exists():return
            if picture is None:canvas._wallpaper_failed_key=request
            current=canvas._wallpaper_requested
            if current==request and str(getattr(app,'wallpaper_path',None))==request[1] and picture is not None:
                if (max(1,canvas.winfo_width()),max(1,canvas.winfo_height()))==request[-2:]:
                    canvas_background(canvas,picture,app.root,request)
            if current!=request:start()
        app.worker.submit(prepare(),loaded,lambda _:loaded(None))
    start()


def _interface_picture(signature, source, source_known):
    """Decode, fit and blend immutable PIL data outside Tk."""
    from PIL import Image,ImageOps
    path,width,height,color=signature
    if not source_known:
        with Image.open(path) as image:
            if image.width*image.height>30_000_000:return None,None
            image.draft('RGB',(2560,2560))
            source=ImageOps.exif_transpose(image).convert('RGB')
            source.thumbnail((2560,2560))
    if source is None:return None,None
    picture=ImageOps.fit(source,(width,height),method=Image.Resampling.LANCZOS)
    return source,Image.blend(picture,Image.new('RGB',picture.size,color),.22)


class InterfaceBackground:
    """Stitched ttk frame images. Native menus and readable input surfaces stay intact."""
    def __init__(self, app):
        self.app=app;self.root=app.root;self.entries={};self.free=[];self.source=None;self.path=None
        self.job=None;self.serial=0;self.signature=None;self.picture=None
        self._preparing=False;self._picture_pending=False;self._wanted=None
        self.root.bind('<Configure>',self.schedule,add='+')
        self.root.bind('<Map>',self.schedule,add='+')
        viewport=getattr(app,'viewport',None)
        if viewport is not None:viewport.on_scroll=self.schedule
        self.schedule()

    def schedule(self,event=None):
        # Configure events also bubble here from every child control. The default
        # background should not cross into Tcl at all for those events.
        if not self.app.preferences.values.get('interface_background') and not self.entries:return
        if self.job is not None:return
        if event is not None and event.widget is not self.root and not isinstance(event.widget,ttk.Frame):return
        if event is not None and event.widget.winfo_toplevel()!=self.root:return
        self.job=self.root.after(16,self.paint)

    def picture_signature(self):
        path=self.app.preferences.values.get('interface_background','')
        if not path:return None
        width,height=max(1,self.root.winfo_width()),max(1,self.root.winfo_height())
        from .appearance import app_palette
        colors=app_palette(self.app.preferences.values)
        return path,width,height,colors['bg']

    def fitted_picture(self):
        """Keep the last complete frame while preparing the newest window size."""
        self._wanted=self.picture_signature()
        if self._wanted is None:
            self.source=self.path=self.signature=self.picture=None
            self._picture_pending=False
            return None
        self._picture_pending=self._wanted!=self.signature
        if self._picture_pending and not self._preparing:self.prepare_picture()
        return self.picture

    def prepare_picture(self):
        request=self._wanted
        if request is None or request==self.signature:return
        if getattr(self.app,'closed',False) or getattr(self.app,'closing',False) or not self.root.winfo_exists():return
        self._preparing=True
        source,source_known=self.source,self.path==request[0]
        async def prepare():
            import asyncio
            return await asyncio.to_thread(_interface_picture,request,source,source_known)
        def loaded(result):
            self._preparing=False
            if getattr(self.app,'closed',False) or getattr(self.app,'closing',False) or not self.root.winfo_exists():return
            self._wanted=self.picture_signature()
            if self._wanted is None:
                self.source=self.path=self.signature=self.picture=None
                self._picture_pending=False
            else:
                if request[0]==self._wanted[0]:
                    self.source,self.path=result[0],request[0]
                if request==self._wanted:
                    self.picture,self.signature=result[1],request
                    self._picture_pending=False
                else:
                    self._picture_pending=True
                    self.prepare_picture()
                    return
            self.schedule()
        self.app.worker.submit(prepare(),loaded,lambda _:loaded((None,None)))

    def viewport_picture(self,widget):
        picture=self.fitted_picture()
        if picture is None or self._picture_pending:return None
        x=widget.winfo_rootx()-self.root.winfo_rootx();y=widget.winfo_rooty()-self.root.winfo_rooty()
        return picture.crop((x,y,x+widget.winfo_width(),y+widget.winfo_height()))

    def paint_canvas(self,canvas):
        picture=self.fitted_picture()
        if self._picture_pending:
            if canvas.find_withtag('wallpaper'):
                canvas.tag_lower('wallpaper');pin_canvas_background(canvas)
            return
        if picture is None:
            canvas.delete('wallpaper');canvas.wallpaper=None;canvas._wallpaper_key=None;return
        key=('interface',self.signature,canvas.winfo_rootx()-self.root.winfo_rootx(),canvas.winfo_rooty()-self.root.winfo_rooty(),canvas.winfo_width(),canvas.winfo_height())
        if self.picture is not None and reuse_canvas_background(canvas,key):return
        picture=self.viewport_picture(canvas)
        if picture is not None:canvas_background(canvas,picture,self.root,key)
        else:canvas.delete('wallpaper');canvas.wallpaper=None;canvas._wallpaper_key=None

    def retire(self,widget,entry):
        name,photo,_,original=entry
        if widget.winfo_exists() and widget.cget('style')!=original:
            widget.configure(style=original)
        # Ttk cannot delete an image element. Keep and recycle its tiny photo
        # rather than leak a new element after each account/layout rebuild.
        photo.configure(width=1,height=1)
        self.free.append((name,photo))

    def paint(self):
        self.job=None
        picture=self.fitted_picture()
        if self._picture_pending:return
        for widget in list(self.entries):
            if picture is None or not widget.winfo_exists() or not widget.winfo_ismapped():
                self.retire(widget,self.entries.pop(widget))
        if picture is None:
            canvas=getattr(self.app,'bubble_view',None)
            wallpaper=getattr(self.app,'wallpaper_path',None)
            if canvas is not None and canvas.winfo_exists() and not (wallpaper and Path(wallpaper).is_file()):
                canvas.delete('wallpaper');canvas.wallpaper=None
            return
        widgets=[]
        def walk(parent):
            for widget in parent.winfo_children():
                if isinstance(widget,tk.Toplevel) or not widget.winfo_ismapped():continue
                if isinstance(widget,ttk.Frame):widgets.append(widget)
                walk(widget)
        walk(self.app.container)
        widgets.insert(0,self.app.container)
        style=ttk.Style(self.root)
        for widget in widgets:
            original=widget.cget('style') or 'TFrame'
            if widget in self.entries:original=self.entries[widget][3]
            if original not in ('TFrame',''):continue  # Preserve intentionally raised surfaces.
            x=widget.winfo_rootx()-self.root.winfo_rootx();y=widget.winfo_rooty()-self.root.winfo_rooty()
            w,h=widget.winfo_width(),widget.winfo_height()
            if w<2 or h<2:continue
            geometry=(*self.signature,x,y,w,h)
            previous=self.entries.get(widget)
            if previous and previous[2]==geometry:
                if widget.cget('style')!=previous[0]:widget.configure(style=previous[0])
                continue
            # Tk accepts raw PPM: avoid repeatedly PNG-compressing every panel
            # while the window is resized or its contents scroll.
            tile=picture.crop((x,y,x+w,y+h));data=io.BytesIO();tile.save(data,format='PPM')
            if previous:
                name,photo,_,original=previous;photo.configure(data=data.getvalue(),width=w,height=h)
            elif self.free:
                name,photo=self.free.pop();photo.configure(data=data.getvalue(),width=w,height=h)
            else:
                self.serial+=1;name=f'InterfaceImage{self.serial}.TFrame';element=f'InterfaceImage{self.serial}.background'
                photo=tk.PhotoImage(master=self.root,data=data.getvalue())
                style.element_create(element,'image',photo,sticky='nsew',width=0,height=0)
                style.layout(name,[(element,{'sticky':'nsew'})])
            self.entries[widget]=(name,photo,geometry,original)
            if widget.cget('style')!=name:widget.configure(style=name)
        canvas=getattr(self.app,'bubble_view',None)
        wallpaper=getattr(self.app,'wallpaper_path',None)
        if canvas is not None and canvas.winfo_exists() and canvas.winfo_ismapped() and not (wallpaper and Path(wallpaper).is_file()):
            self.paint_canvas(canvas)
