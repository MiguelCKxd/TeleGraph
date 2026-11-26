"""Image viewer; keeps downloaded content private and never executes attachments."""
import sys
import tkinter as tk
from tkinter import ttk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .i18n import tr


class ImageFrames:
    """Decode only on animation advance, retaining a single full-size frame."""
    def __init__(self,path):
        from PIL import Image,UnidentifiedImageError
        self.video=None;self.frame=None;self.index=None
        try:self.image=Image.open(path)
        except UnidentifiedImageError:
            # Telegram's GIFs are normally silent MP4 documents. Decode their
            # actual content instead of relying on a misleading filename suffix.
            from .video_frames import VideoFrames
            self.video=VideoFrames(path);self.image=self.video.image;self.count=self.video.count
            return
        try:
            if self.image.width*self.image.height>30_000_000:
                raise ValueError(tr('Imagen demasiado grande para la vista previa.'))
            self.count=getattr(self.image,'n_frames',1)
        except Exception:
            self.close();raise

    def get(self,index):
        if self.video is not None:
            frame=self.video.get(index);self.count=self.video.count
            return frame
        from PIL import ImageOps
        if self.index!=index:
            self.image.seek(index)
            frame=ImageOps.exif_transpose(self.image).convert('RGBA')
            if self.frame is not None:self.frame.close()
            self.frame=frame;self.index=index
            if self.count==1:self.image.close()
        return self.frame

    def viewport(self,size,scale=1):
        if self.video is not None:self.video.viewport(size,scale)

    def close(self):
        if self.video is not None:self.video.close();return
        if self.frame is not None:self.frame.close();self.frame=None
        self.image.close()


class FrameRenderer:
    """One decoding worker and one replaceable pending viewport; never calls Tk.

    1.4: large still images keep a small pyramid of 2x reductions, so a zoomed
    out viewport is resampled from the smallest level that still has at least
    screen resolution instead of from the full original on every step.
    Interactive steps may request ``fast`` bilinear output; the viewer then
    asks for a bicubic pass once the gesture settles.
    """
    def __init__(self,source):
        self.path=source if isinstance(source,(str,Path)) else None
        self.source=None if self.path is not None else source
        self.count=getattr(self.source,'count',1)
        self.future=None;self.pending=None;self.closed=False
        self._levels=[];self._levels_index=None
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='tg-image-view')

    def request(self,index,size,scale,pan,fast=False):
        if self.closed:return
        request=(index,tuple(size),scale,tuple(pan))+((True,) if fast else ())
        if self.future is not None:self.pending=request
        else:self.future=self.executor.submit(self.render,*request)

    def _release_levels(self):
        levels,self._levels=self._levels,[]
        for _,image in levels:
            try:image.close()
            except Exception:pass  # Already released with its source.

    def _level(self,index,frame,fit):
        """(image, reduction) to resample from for a display factor ``fit``."""
        if self.count!=1 or fit>=.5:return frame,1
        if self._levels_index!=index:
            self._release_levels();self._levels_index=index
        target=1/fit;best=(frame,1);previous=frame;reduction=2;position=0
        while reduction<=target and min(previous.size)>=64:
            if position<len(self._levels):level=self._levels[position][1]
            else:
                level=previous.reduce(2);self._levels.append((reduction,level))
            best=(level,reduction);previous=level;reduction*=2;position+=1
        return best

    def render(self,index,size,scale,pan,fast=False):
        from PIL import Image
        from .image_gestures import bounded_pan
        from .animation import frame_duration
        if self.source is None:
            self.source=ImageFrames(self.path)
            self.count=self.source.count
        viewport=getattr(self.source,'viewport',None)
        if viewport is not None:viewport(size,scale)
        frame=self.source.get(index)
        self.count=getattr(self.source,'count',1)
        w,h=size;fit=min(w/frame.width,h/frame.height,1)*scale
        pan=bounded_pan(pan,frame.size,size,fit)
        cx,cy=frame.width/2-pan[0]/fit,frame.height/2-pan[1]/fit
        box=(cx-w/2/fit,cy-h/2/fit,cx+w/2/fit,cy+h/2/fit)
        image,reduction=self._level(index,frame,fit)
        if reduction>1:box=tuple(value/reduction for value in box)
        resample=Image.Resampling.BILINEAR if fast else Image.Resampling.BICUBIC
        shown=image.transform(size,Image.Transform.EXTENT,box,resample=resample)
        return shown,pan,frame_duration(self.source.image.info.get('duration',100))

    def poll(self):
        if self.closed or self.future is None or not self.future.done():return None
        future,self.future=self.future,None
        if self.pending is not None:
            request,self.pending=self.pending,None
            try:future.result()[0].close()
            except Exception:pass  # A newer viewport superseded this result.
            self.future=self.executor.submit(self.render,*request)
            return None
        return future.result()

    def busy(self):
        return self.future is not None or self.pending is not None

    def close(self):
        if self.closed:return
        self.closed=True;self.pending=None
        abort=getattr(self.source,'abort',None)
        if abort is not None:abort()
        future,self.future=self.future,None
        def close_source():
            self._release_levels()
            if self.source is not None:self.source.close()
        if future is None:close_source()
        else:
            def release(result):
                try:result.result()[0].close()
                except Exception:pass
                close_source()
            future.add_done_callback(release)
            future.cancel()
        self.executor.shutdown(wait=False,cancel_futures=True)


def show_image(parent, path, caption='', preview_only=False, *, navigate=None, name=None, on_error=None):
    from PIL import ImageTk
    window=tk.Toplevel(parent)
    window.title(tr('Visor de archivos'))
    window.configure(bg='#08100c')
    window.geometry('820x680')
    label = tk.Canvas(window, bg='#08100c', highlightthickness=0)
    label.pack(fill='both', expand=True, padx=16, pady=16)
    caption_label=ttk.Label(window,text=caption,wraplength=760)
    caption_label.pack(padx=16)
    if preview_only:
        ttk.Label(window, text=tr('Vista previa estatica del sticker o video.')).pack(pady=8)
    from .image_tools import zoom_at
    scale,pan,drag=[1.],[0,0],[None]
    # Pan of the pixels currently on screen. While a newer viewport is being
    # rendered the old picture is shifted by (pan - shown_pan) at once, so
    # dragging follows the pointer instead of waiting for the worker.
    shown_pan=[0,0];shown_scale=[1.]
    frame_number = 0
    timer = None
    render_timer = None
    settle_timer = None
    renderer=FrameRenderer(path) if path else None
    current_path=[path]
    closed=False
    def advance():
        nonlocal frame_number,timer
        timer=None
        if closed or renderer is None:return
        if not window.winfo_viewable():
            timer=window.after(250,advance);return
        frame_number=(frame_number+1)%renderer.count
        repaint.request()
    def place_picture():
        if shown_scale[0]==scale[0]:
            label.coords('picture',pan[0]-shown_pan[0],pan[1]-shown_pan[1])
    def completed():
        nonlocal timer,render_timer
        render_timer=None
        if closed or renderer is None:return
        try:
            result=renderer.poll()
            if result is None:
                render_timer=window.after(16,completed);return
            shown,position,duration=result
            requested=getattr(renderer,'last_request',None)
            if not renderer.busy() and (requested is None or (requested[0]==scale[0] and list(requested[1])==list(pan))):
                pan[:]=position  # Settled: adopt the bounded position.
            shown_pan[:]=position;shown_scale[0]=requested[0] if requested else scale[0]
            try:
                photo=getattr(label,'image',None)
                if (renderer.count==1 and photo is not None and photo.width()==shown.width
                        and photo.height()==shown.height):
                    photo.paste(shown)  # Same Tk image: no create/delete churn.
                else:
                    label.image=ImageTk.PhotoImage(shown,master=window)
            finally:shown.close()
            if not label.find_withtag('picture'):
                label.create_image(0,0,image=label.image,anchor='nw',tags='picture')
            else:
                label.itemconfigure('picture',image=label.image)
            label.coords('picture',pan[0]-shown_pan[0],pan[1]-shown_pan[1])
            if timer is None and renderer.count>1:
                timer=window.after(max(40,duration),advance)
        except (EOFError, OSError, ValueError, ImportError, tk.TclError) as error:
            handler=getattr(window,'_media_error',None)
            if handler is not None and handler(error):return
            from .app_dialogs import messagebox
            if window.winfo_exists():messagebox.showerror(tr('Visor de archivos'),str(error),parent=window)
            close()
    fast_next=[False]
    def draw():
        nonlocal render_timer
        if closed or renderer is None or not window.winfo_viewable():return
        size=(max(100,label.winfo_width()),max(100,label.winfo_height()))
        fast=fast_next[0];fast_next[0]=False
        renderer.last_request=(scale[0],tuple(pan))
        if fast:renderer.request(frame_number,size,scale[0],pan,fast=True)
        else:renderer.request(frame_number,size,scale[0],pan)
        if render_timer is None:render_timer=window.after(16,completed)
    from .ui_work import FrameJob
    repaint=FrameJob(window,draw)
    def settle():
        nonlocal settle_timer
        settle_timer=None
        if not closed:repaint.request()  # Full-quality pass once input stops.
    def interactive():
        nonlocal settle_timer
        fast_next[0]=True;place_picture();repaint.request()
        if settle_timer is not None:
            try:window.after_cancel(settle_timer)
            except tk.TclError:pass
        settle_timer=window.after(140,settle)
    def zoom(factor,point=None):
        size=(label.winfo_width(),label.winfo_height())
        scale[0],pan[:]=zoom_at(scale[0],pan,factor,point or (size[0]/2,size[1]/2),size)
        interactive()
    label.bind('<Configure>',repaint.request)
    window.bind('<Map>',repaint.request,add='+')
    def press(e): drag[0]=(e.x,e.y,*pan)
    def move(e):
        if drag[0]:
            pan[:]=[drag[0][2]+e.x-drag[0][0],drag[0][3]+e.y-drag[0][1]]
            interactive()
    label.bind('<ButtonPress-1>',press); label.bind('<B1-Motion>',move)
    def release(event):
        if navigate and drag[0] and scale[0]<=1.05:
            dx,dy=event.x-drag[0][0],event.y-drag[0][1]
            if abs(dx)>=70 and abs(dx)>abs(dy)*1.5:navigate(1 if dx<0 else -1)
        drag[0]=None
    label.bind('<ButtonRelease-1>',release)
    controls=ttk.Frame(window); controls.pack(pady=4)
    def step(direction):
        # Arrows move a zoomed picture; at fit they browse the gallery.
        if scale[0]>1.05:
            pan[0]+=-80*direction;interactive()
        elif navigate:navigate(direction)
    if navigate:
        ttk.Button(controls,text='‹',width=4,command=lambda:navigate(-1)).pack(side='left')
        ttk.Button(controls,text='›',width=4,command=lambda:navigate(1)).pack(side='left')
    window.bind('<Left>',lambda _:step(-1))
    window.bind('<Right>',lambda _:step(1))
    def vertical(direction):
        if scale[0]>1.05:pan[1]+=-80*direction;interactive()
    window.bind('<Up>',lambda _:vertical(-1))
    window.bind('<Down>',lambda _:vertical(1))
    ttk.Button(controls,text='−',width=4,command=lambda:zoom(1/1.25)).pack(side='left')
    ttk.Button(controls,text='+',width=4,command=lambda:zoom(1.25)).pack(side='left')
    for key,factor in (('<plus>',1.25),('<equal>',1.25),('<KP_Add>',1.25),('<minus>',1/1.25),('<KP_Subtract>',1/1.25)):
        window.bind(key,lambda _,f=factor:zoom(f))
    def reset():
        scale[0]=1.; pan[:]=[0,0]; interactive()
    window.bind('<Key-0>',lambda _:reset())
    from .image_gestures import ImageGestures
    gestures=ImageGestures(label,scale,pan,zoom,interactive,reset)
    gestures.controls(controls)
    def open_native():
        handler=getattr(window,'_open_native',None)
        if handler is not None:return handler()
        if current_path[0] is None:return
        from .native_open import open_with_system
        open_with_system(current_path[0],name or caption,on_error=on_error)
    ttk.Button(controls,text=tr('Open with system viewer'),command=open_native).pack(side='left',padx=(8,0))
    ttk.Label(window,text=tr('Wheel / two fingers: selected mode · Shift: horizontal · Ctrl: zoom · drag: move')).pack(pady=4)
    def cancel_timers():
        nonlocal timer,render_timer,settle_timer
        for pending in (timer,render_timer,settle_timer):
            if pending is not None:
                try:window.after_cancel(pending)
                except tk.TclError:pass
        timer=render_timer=settle_timer=None
    def cleanup(event=None):
        nonlocal closed
        if event is not None and event.widget is not window:return
        if closed:return
        closed=True;repaint.cancel()
        cancel_timers()
        if renderer is not None:renderer.close()
        label.image=None
    def replace_media(path,caption='',*,preserve_view=False):
        nonlocal renderer,frame_number
        if closed:return
        repaint.cancel()
        cancel_timers()
        if renderer is not None:renderer.close()
        renderer=FrameRenderer(path) if path is not None else None;frame_number=0
        if not preserve_view:scale[0]=1.;pan[:]=[0,0]
        shown_pan[:]=[0,0];shown_scale[0]=1.;current_path[0]=path
        label.image=None;label.delete('picture')
        caption_label.configure(text=caption)
        repaint.request()
    window._set_media=replace_media
    window._reset_media_view=lambda:(scale.__setitem__(0,1.),pan.__setitem__(slice(None),[0,0]))
    window._media_canvas=label
    def close():
        cleanup()
        window.destroy()
    window.bind('<Destroy>',cleanup,add='+')
    window.protocol('WM_DELETE_WINDOW', close)
    window.bind('<Escape>',lambda _:close())
    from .themes import apply_widget
    apply_widget(window)
    repaint.request()
    return window


def enable_drop(root, widgets, callback):
    """Use TkDnD's platform binaries; a missing ABI never disables Attach."""
    try:
        from tkinterdnd2 import TkinterDnD, DND_FILES
        if not getattr(root, '_tg_dnd_ready', False):
            TkinterDnD.require(root)
            root._tg_dnd_ready = True
        def dropped(event):
            callback(root.tk.splitlist(event.data))
            return 'copy'
        for widget in widgets:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind('<<Drop>>', dropped)
        return True
    except (ImportError, RuntimeError, tk.TclError):
        if sys.platform == 'win32':
            try:
                from .windows_drop import install
                return install(root, callback)
            except (OSError, AttributeError):
                return False
        return False
