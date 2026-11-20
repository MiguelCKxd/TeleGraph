"""User-selected runtime icon; never rewrites the signed app bundle or executable."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import uuid
from .i18n import tr


def icon_image(source, zoom=1, x=.5, y=.5, size=512):
    from PIL import Image,ImageDraw
    from .image_tools import wallpaper_crop
    cropped=wallpaper_crop(source,size,size,zoom,x,y)
    try:picture=cropped.convert('RGBA')
    finally:cropped.close()
    mask=Image.new('L',(size,size),0)
    try:
        ImageDraw.Draw(mask).rounded_rectangle((0,0,size-1,size-1),radius=round(size*.22),fill=255)
        picture.putalpha(mask)
    finally:mask.close()
    return picture


def load_icon_source(path):
    """Decode and orient the original off Tk, retaining only the editing resolution."""
    from PIL import Image,ImageOps
    with Image.open(path) as image:
        if image.width*image.height>30_000_000:raise ValueError(tr('Image is too large'))
        source=ImageOps.exif_transpose(image)
    try:source.thumbnail((2048,2048));return source
    except Exception:source.close();raise


class IconWork:
    """One decode/render/export at a time, retaining only the newest slider values."""
    def __init__(self,window,failed,display,accepted,folder):
        from .image_tools import ImageWork
        self.source=None;self.pending=None;self.generation=0;self.exporting=False
        self.target=None;self.adopted=False;self.folder=Path(folder)
        self.failed=failed;self.display=display;self.accepted=accepted
        self.work=ImageWork(window,self.error)

    def load(self,path,ready):
        def loaded(source):self.source=source;ready();self.next()
        return self.work.submit(lambda:load_icon_source(path),loaded)

    def error(self,error):
        self.exporting=False;self.pending=None
        if self.target is not None and not self.adopted:
            try:self.target.unlink(missing_ok=True)
            except OSError:pass
            self.target=None
        self.failed(error)

    def preview(self,values):
        if self.work.closed or self.exporting:return
        self.generation+=1;self.pending=('preview',dict(values),self.generation);self.next()

    def export(self,values):
        if self.work.closed or self.source is None or self.exporting:return False
        self.exporting=True;self.generation+=1
        self.pending=('export',dict(values),self.generation);self.next();return True

    def next(self):
        if self.work.closed or self.source is None or self.work.future is not None or self.pending is None:return
        kind,values,epoch=self.pending;self.pending=None
        if kind=='preview':
            def done(image):
                try:
                    if epoch==self.generation:self.display(image)
                finally:image.close()
                self.next()
            self.work.submit(lambda:icon_image(self.source,**values,size=192),done)
        else:
            def save():
                self.folder.mkdir(parents=True,exist_ok=True)
                target=self.folder/(uuid.uuid4().hex+'.png');self.target=target
                image=icon_image(self.source,**values,size=1024)
                try:image.save(target)
                finally:image.close()
                return target
            def saved(target):
                try:self.accepted(target)
                except Exception as exc:self.error(exc);return
            self.work.submit(save,saved)

    def close(self):
        self.pending=None
        def release():
            if self.source is not None:self.source.close();self.source=None
            if self.target is not None and not self.adopted:
                try:self.target.unlink(missing_ok=True)
                except OSError:pass
        self.work.close(release)


def choose_icon(app):
    from .app_dialogs import filedialog
    from PIL import ImageTk
    path=filedialog.askopenfilename(parent=app.root,filetypes=[(tr('Images'),'*.png *.jpg *.jpeg *.webp')])
    if not path:return
    window,frame=app.dialog('Custom app icon','480x540')
    preview=ttk.Label(frame,text=tr('Loading...'));preview.pack(pady=12)
    values={key:tk.DoubleVar(value=value) for key,value in [('zoom',1),('x',.5),('y',.5)]}
    controls=[]
    def settings():return {key:value.get() for key,value in values.items()}
    def draw(*_):worker.preview(settings())
    for key,label,low,high in [('zoom','Zoom',1,3),('x','Horizontal position',0,1),('y','Vertical position',0,1)]:
        ttk.Label(frame,text=tr(label)).pack(anchor='w')
        control=ttk.Scale(frame,from_=low,to=high,variable=values[key],command=draw,state='disabled')
        control.pack(fill='x');controls.append(control)
    def enable(value):
        for control in controls:control.configure(state='normal' if value else 'disabled')
    def failed(error):
        if worker.work.closed:return
        enable(worker.source is not None);app.show_error(error)
    def display(image):
        preview.image=ImageTk.PhotoImage(image,master=window);preview.configure(image=preview.image,text='')
    def accepted(target):
        app.preferences.save({'custom_icon':str(target),'official_icon_label':''})
        worker.adopted=True
        app.refresh_logo();app.update_logo_selection();window.destroy()
    folder=app.preview_dir if app.demo else app.preferences.path.parent/'custom-icons'
    worker=IconWork(window,failed,display,accepted,folder)
    def apply():
        if worker.export(settings()):enable(False)
    button=ttk.Button(frame,text=tr('Apply'),command=apply,state='disabled');button.pack(fill='x',pady=8);controls.append(button)
    def close(event):
        if event.widget is window:
            from .image_tools import release_variables
            release_variables(values.values());worker.close();preview.image=None
    window.bind('<Destroy>',close,add='+')
    worker.load(path,lambda:(enable(True),draw()))


def reset_icon(app):
    try:app.preferences.save({'custom_icon':'','official_icon_label':''})
    except OSError as exc:app.show_error(exc);return
    app.refresh_logo();app.update_logo_selection()
