"""Local image preview/editor. Originals are never overwritten."""
from . import APP_NAME
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import ttk
from .i18n import tr
from .app_dialogs import Choice


def release_variables(variables):
    """Dispose Tk variables on Tk's thread before worker GC can reclaim UI cycles."""
    for variable in variables:
        try:variable.__del__()
        except tk.TclError:pass
        finally:variable._tk=None


def close_images(value):
    """Release worker results that no longer have a live view."""
    from PIL import Image
    if isinstance(value,Image.Image):value.close()
    elif isinstance(value,(tuple,list)):
        for item in value:close_images(item)


class ImageWork:
    """A single local image operation; all callbacks are delivered by Tk polling."""
    def __init__(self,window,failed):
        self.window=window;self.failed=failed;self.future=None;self.job=None;self.closed=False
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='tg-image-edit')

    def submit(self,operation,done):
        if self.closed or self.future is not None:return False
        self.future=self.executor.submit(operation)
        def poll():
            self.job=None
            if self.closed:return
            if not self.future.done():self.job=self.window.after(16,poll);return
            future,self.future=self.future,None
            try:result=future.result()
            except Exception as exc:self.failed(exc);return
            done(result)
        self.job=self.window.after(16,poll)
        return True

    def close(self,release=lambda:None):
        if self.closed:return
        self.closed=True
        if self.job is not None:
            try:self.window.after_cancel(self.job)
            except tk.TclError:pass
            self.job=None
        future,self.future=self.future,None
        if future is None:release()
        else:
            def completed(result):
                try:close_images(result.result())
                except Exception:pass
                release()
            future.add_done_callback(completed);future.cancel()
        self.executor.shutdown(wait=False,cancel_futures=True)


def load_editor_image(path):
    from PIL import Image
    with Image.open(path) as image:
        if image.width*image.height>30_000_000:raise ValueError(tr('This image is too large to preview.'))
        source=image.copy()
    try:return source,editor_preview(source)
    except Exception:source.close();raise


def rendered_edit(source,state,crop,values,layers,wallpaper=False):
    image=edited_image(source,**state,crop=crop,**({} if wallpaper else values))
    try:
        if wallpaper:
            result=wallpaper_crop(image,900,1200,**values)
        else:result=render_annotations(image,layers)
    finally:image.close()
    return result


def edited_image(source, rotation=0, mirror=False, crop='Original', brightness=1, contrast=1, saturation=1):
    from PIL import ImageOps, ImageEnhance
    image=ImageOps.exif_transpose(source).convert('RGB')
    if rotation: image=image.rotate(rotation,expand=True)
    if mirror: image=ImageOps.mirror(image)
    ratios={'1:1':1,'4:3':4/3,'16:9':16/9,'9:16':9/16}
    if crop in ratios:
        ratio=ratios[crop]; w,h=image.size
        if w/h>ratio: new=int(h*ratio); image=image.crop(((w-new)//2,0,(w+new)//2,h))
        else: new=int(w/ratio); image=image.crop((0,(h-new)//2,w,(h+new)//2))
    for cls,factor in [(ImageEnhance.Brightness,brightness),(ImageEnhance.Contrast,contrast),(ImageEnhance.Color,saturation)]:
        if float(factor)!=1:image=cls(image).enhance(float(factor))
    return image


def editor_preview(source, size=(1280,1280)):
    """Keep slider/drawing work bounded; export still uses the full original."""
    from PIL import ImageOps
    image=source.copy()
    if source.getexif():image.info['exif']=source.getexif().tobytes()
    image.thumbnail(size)
    return ImageOps.exif_transpose(image)


def wallpaper_crop(source, width, height, zoom=1, x=.5, y=.5):
    from PIL import ImageOps
    image=ImageOps.exif_transpose(source).convert('RGB')
    width,height=max(1,int(width)),max(1,int(height))
    scale=max(width/image.width,height/image.height)*max(1,float(zoom))
    cw,ch=width/scale,height/scale
    left=(image.width-cw)*min(1,max(0,float(x))); top=(image.height-ch)*min(1,max(0,float(y)))
    return image.crop((left,top,left+cw,top+ch)).resize((width,height))


def render_annotations(image, annotations):
    """Composite normalized editable layers; drawing never modifies the source image."""
    from PIL import Image,ImageDraw,ImageFont
    if not annotations:return image.convert('RGB')
    result=image.convert('RGBA')
    w,h=result.size
    fonts={}
    for item in annotations:
        opacity=item.get('opacity',1)
        layer=Image.new('RGBA',(w,h)) if opacity<1 else result
        draw=ImageDraw.Draw(layer)
        color=item.get('color','#00cc66')
        if item['kind']=='stroke':
            points=[(round(x*w),round(y*h)) for x,y in item['points']]
            width=max(1,round(item['width']*min(w,h)))
            if points:
                if len(points)>1: draw.line(points,fill=color,width=width,joint='curve')
                radius=width/2
                for x,y in (points[0],points[-1]): draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=color)
        elif item['kind']=='text':
            size=max(8,round(item['size']*min(w,h)))
            font=fonts.get(size)
            if font is None:
                for candidate in ('/System/Library/Fonts/Supplemental/Arial.ttf','C:/Windows/Fonts/arial.ttf','DejaVuSans.ttf'):
                    try: font=ImageFont.truetype(candidate,size); break
                    except OSError: pass
                if font is None: font=ImageFont.load_default(size=size)
                fonts[size]=font
            draw.multiline_text((round(item['x']*w),round(item['y']*h)),item['text'],font=font,fill=color,spacing=max(2,size//5),anchor='la')
        if opacity<1:
            layer.putalpha(layer.getchannel('A').point(lambda a:round(a*opacity)))
            result=Image.alpha_composite(result,layer)
    return result.convert('RGB')


def preview_point(x,y,box):
    left,top,width,height=box
    if width<=0 or height<=0 or not (left<=x<=left+width and top<=y<=top+height): return None
    return (x-left)/width,(y-top)/height


def image_editor(parent,path,output,accepted,wallpaper=False,native=None):
    from PIL import ImageTk
    from copy import deepcopy
    from .app_dialogs import colorchooser
    from .app_dialogs import scrollable,messagebox
    from .scrolling import FlowFrame
    source=preview_source=None
    top=tk.Toplevel(parent); top.title(tr('Preview and edit')); top.geometry('740x760'); top.transient(parent)
    # Keep final actions outside the scrolled body, reachable on short windows.
    footer=ttk.Frame(top,padding=8); footer.pack(side='bottom',fill='x')
    body=scrollable(top)
    canvas=tk.Canvas(body,width=620,height=340,bg='#111814',highlightthickness=0);canvas.pack(fill='x')
    from .free_crop import CropSelection,draw_selection,cropped_image
    selection=CropSelection();crop_backup=[None];crop_buttons={}
    state={'rotation':0,'mirror':False}; layers=[]; base=[None]; box=[(0,0,1,1)]; stroke=[None]
    mode=tk.StringVar(value='Pencil');color=['#00cc66'];width=tk.DoubleVar(value=4);text_size=tk.DoubleVar(value=28)
    text=tk.StringVar();previous_crop=['Original'];pending=[None]
    busy=[False];disabled=[];cancel_button=None
    def set_busy(value):
        busy[0]=value
        if value:
            pending_widgets=list(top.winfo_children())
            while pending_widgets:
                widget=pending_widgets.pop();pending_widgets.extend(widget.winfo_children())
                if widget is cancel_button:continue
                try:
                    old=widget.cget('state');widget.configure(state='disabled');disabled.append((widget,old))
                except tk.TclError:pass
            top.configure(cursor='watch')
        else:
            for widget,old in disabled:
                if widget.winfo_exists():widget.configure(state=old)
            disabled.clear();top.configure(cursor='')
    def failed(error):
        set_busy(False)
        messagebox.showerror(tr('Preview and edit'),str(error),parent=top)
    work=ImageWork(top,failed)
    def run(operation,done):
        if busy[0]:return False
        set_busy(True)
        def loaded(result):
            set_busy(False);done(result)
        if work.submit(operation,loaded):return True
        set_busy(False);return False
    crop=Choice(body,values=['Original','1:1','4:3','16:9','9:16']);crop.current(0)
    if not wallpaper: crop.pack(fill='x',pady=4)
    def paint():
        if not top.winfo_exists() or base[0] is None: return
        preview=base[0].copy();preview.thumbnail((max(100,canvas.winfo_width()-12),max(100,canvas.winfo_height()-12)))
        preview=render_annotations(preview,layers)
        w,h=preview.size;left=(canvas.winfo_width()-w)/2;upper=(canvas.winfo_height()-h)/2;box[0]=(left,upper,w,h)
        canvas.photo=ImageTk.PhotoImage(preview,master=top);canvas.delete('all');canvas.create_image(left,upper,image=canvas.photo,anchor='nw')
        if not wallpaper and mode.get()=='Crop':draw_selection(canvas,selection,box[0])
        if 'apply' in crop_buttons:crop_buttons['apply'].configure(state='normal' if selection.pixels(base[0].size) else 'disabled')
        if wallpaper:
            canvas.create_rectangle(left+20,upper+30,left+w-20,upper+65,fill='#163b27',outline='')
            canvas.create_text(left+w/2,upper+47,text=APP_NAME,fill='#8cf5a6')
    from .ui_work import FrameJob
    repaint=FrameJob(top,paint)
    draw=repaint.request
    values={}
    def prepared(original=False):
        image=edited_image(source if original else preview_source,**state,crop=crop.get(),**({k:v.get() for k,v in values.items()} if not wallpaper else {}))
        if wallpaper: image=wallpaper_crop(image,900,1200,**{k:v.get() for k,v in values.items()})
        return image
    def refresh():
        pending[0]=None
        if not top.winfo_exists() or preview_source is None or busy[0]:return
        previous=base[0];base[0]=prepared()
        if previous is not None:previous.close()
        draw()
    def schedule(_=None):
        if busy[0]:return
        if pending[0]: top.after_cancel(pending[0])
        pending[0]=top.after(60,refresh)
    from .number_input import slider
    # Typed values may go beyond the slider (wallpaper zoom stays bounded by memory).
    for key,label,low,high,initial,typed_low,typed_high in ([('zoom','Zoom',1,3,1,1,4),('x','Horizontal position',0,1,.5,0,1),('y','Vertical position',0,1,.5,0,1)] if wallpaper else [('brightness','Brightness',.25,2,1,0,4),('contrast','Contrast',.25,2,1,0,4),('saturation','Saturation',0,2,1,0,4)]):
        row=ttk.Frame(body);row.pack(fill='x',pady=2)
        ttk.Label(row,text=tr(label),width=20).pack(side='left')
        values[key]=tk.DoubleVar(value=initial)
        slider(row,values[key],low,high,schedule,typed_low=typed_low,typed_high=typed_high).pack(side='left',fill='x',expand=True)
    def reset_geometry():
        if busy[0] or source is None:return False
        if layers and not messagebox.askyesno(tr('Preview and edit'),tr('Changing crop or orientation clears drawings and text. Continue?'),parent=top): return False
        layers.clear();selection.clear();return True
    def rotate():
        if reset_geometry(): state['rotation']=(state['rotation']+90)%360;refresh()
    def mirror():
        if reset_geometry(): state['mirror']=not state['mirror'];refresh()
    def recrop(_=None):
        if not reset_geometry():crop.set(previous_crop[0]);return
        previous_crop[0]=crop.get();refresh()
    crop.bind('<<ComboboxSelected>>',recrop)
    tools=FlowFrame(body);tools.pack(fill='x',pady=4)
    ttk.Button(tools,text=tr('Rotate'),command=rotate).pack(side='left')
    ttk.Button(tools,text=tr('Flip'),command=mirror).pack(side='left')
    if not wallpaper:
        def choose_mode(value):
            mode.set(value);stroke[0]=None;selection.clear();canvas.configure(cursor='crosshair' if value!='Text' else 'xterm');draw()
        for label in ('Pencil','Marker','Text'):
            ttk.Button(tools,text=tr(label),command=lambda v=label:choose_mode(v)).pack(side='left')
        ttk.Button(tools,text=tr('Free crop'),command=lambda:choose_mode('Crop')).pack(side='left')
        def apply_free_crop(on_done=None):
            nonlocal source,preview_source
            if busy[0] or source is None:return False
            if pending[0]:top.after_cancel(pending[0]);pending[0]=None
            refresh()
            if base[0] is None or not selection.pixels(base[0].size):return False
            saved=(source,dict(state),{k:v.get() for k,v in values.items()},crop.get(),deepcopy(layers))
            rectangle=selection.rectangle()
            def prepare_crop():
                full=rendered_edit(saved[0],saved[1],saved[3],saved[2],saved[4])
                try:cropped=cropped_image(full,rectangle)
                finally:full.close()
                try:return cropped,editor_preview(cropped)
                except Exception:cropped.close();raise
            def cropped(result):
                nonlocal source,preview_source
                if crop_backup[0] is not None:crop_backup[0][0].close()
                crop_backup[0]=saved
                if preview_source is not None:preview_source.close()
                source,preview_source=result
                state.update(rotation=0,mirror=False);layers.clear();selection.clear();stroke[0]=None
                crop.current(0);previous_crop[0]='Original'
                for variable in values.values():variable.set(1)
                mode.set('Pencil');refresh();crop_buttons['undo'].configure(state='normal')
                if on_done:on_done()
            return run(prepare_crop,cropped)
        def undo_crop():
            nonlocal source,preview_source
            if busy[0] or crop_backup[0] is None:return
            saved_source,saved_state,saved_values,saved_ratio,saved_layers=crop_backup[0]
            def restored(preview):
                nonlocal source,preview_source
                source.close();preview_source.close()
                source,preview_source=saved_source,preview
                state.update(saved_state);layers[:]=saved_layers
                for key,value in saved_values.items():values[key].set(value)
                crop.set(saved_ratio);previous_crop[0]=saved_ratio;selection.clear();crop_backup[0]=None
                mode.set('Pencil');refresh();crop_buttons['undo'].configure(state='disabled')
            run(lambda:editor_preview(saved_source),restored)
        crop_buttons['apply']=ttk.Button(tools,text=tr('Apply crop'),command=apply_free_crop,state='disabled');crop_buttons['apply'].pack(side='left')
        crop_buttons['undo']=ttk.Button(tools,text=tr('Undo crop'),command=undo_crop,state='disabled');crop_buttons['undo'].pack(side='left')
        ttk.Label(body,text=tr('Free crop: drag over the image, then apply. Escape cancels the selection.'),wraplength=650).pack(fill='x',pady=3)
        def choose_color():
            chosen=colorchooser.askcolor(color[0],parent=top,title=tr('Color'))[1]
            if chosen: color[0]=chosen;color_button.configure(text=tr('Color')+' '+chosen)
        color_button=ttk.Button(tools,text=tr('Color'),command=choose_color);color_button.pack(side='left')
        def undo():
            if layers: layers.pop();draw()
        ttk.Button(tools,text=tr('Undo'),command=undo).pack(side='left')
        pen=ttk.Frame(body);pen.pack(fill='x',pady=3)
        ttk.Label(pen,text=tr('Stroke width')).pack(side='left')
        from .number_input import slider
        slider(pen,width,1,40,typed_high=200,integer=True).pack(side='left',fill='x',expand=True)
        line=ttk.Frame(body);line.pack(fill='x',pady=3)
        ttk.Label(line,text=tr('Text')).pack(side='left')
        ttk.Entry(line,textvariable=text).pack(side='left',fill='x',expand=True,padx=5)
        ttk.Spinbox(line,from_=10,to=96,textvariable=text_size,width=5).pack(side='left')
        ttk.Label(body,text=tr('Choose Text, then click the image to place it. Undo removes the last edit.'),wraplength=650).pack(fill='x',pady=3)
        def press(event):
            if busy[0] or base[0] is None:return 'break'
            if mode.get()=='Crop':
                selection.begin(event.x,event.y,box[0]);draw();return 'break'
            point=preview_point(event.x,event.y,box[0])
            if point is None: return
            minimum=min(box[0][2:])
            if mode.get()=='Text':
                if not text.get().strip(): return
                try: size=max(10,min(96,text_size.get()))
                except tk.TclError:return
                layers.append({'kind':'text','text':text.get()[:1000],'x':point[0],'y':point[1],'size':size/minimum,'color':color[0]})
            else:
                item={'kind':'stroke','points':[point],'width':width.get()/minimum,'color':color[0],'opacity':.35 if mode.get()=='Marker' else 1}
                layers.append(item);stroke[0]=item
            draw();return 'break'
        def move(event):
            if busy[0] or base[0] is None:return 'break'
            if mode.get()=='Crop':
                selection.move(event.x,event.y,box[0]);draw();return 'break'
            point=preview_point(event.x,event.y,box[0])
            if stroke[0] is not None and point is not None:
                stroke[0]['points'].append(point);draw()
            return 'break'
        canvas.bind('<ButtonPress-1>',press);canvas.bind('<B1-Motion>',move)
        canvas.bind('<ButtonRelease-1>',lambda _:stroke.__setitem__(0,None))
    disposed=False
    def cleanup(event=None):
        nonlocal disposed
        if event is not None and event.widget is not top:return
        if disposed:return
        disposed=True
        release_variables([mode,width,text_size,text,*values.values()])
        if pending[0]:
            try:top.after_cancel(pending[0])
            except tk.TclError:pass
            pending[0]=None
        repaint.cancel()
        images=(source,preview_source,base[0],crop_backup[0][0] if crop_backup[0] else None)
        work.close(lambda:close_images(images))
        canvas.photo=None
    def close():
        cleanup()
        top.destroy()
    def save():
        if busy[0] or source is None:return
        if not wallpaper and mode.get()=='Crop' and selection.pixels(base[0].size):
            if apply_free_crop(on_done=save):return
        if Path(output).resolve()==Path(path).resolve(): raise ValueError('Output must differ from original')
        if pending[0]:top.after_cancel(pending[0]);pending[0]=None
        captured=(source,dict(state),crop.get(),{k:v.get() for k,v in values.items()},deepcopy(layers),wallpaper)
        def export():
            import os,tempfile
            target=Path(output)
            descriptor,temporary=tempfile.mkstemp(prefix='tg-edit-',suffix='.jpg',dir=target.parent)
            os.close(descriptor)
            try:
                image=rendered_edit(*captured)
                try:image.save(temporary,format='JPEG',quality=93)
                finally:image.close()
                if not work.closed:os.replace(temporary,target)
            finally:Path(temporary).unlink(missing_ok=True)
        run(export,lambda _:(close(),accepted(Path(output))))
    ttk.Button(footer,text=tr('Continue'),command=save).pack(side='right')
    if native is not None and not wallpaper:
        # 1.4: hand the original to the operating system's editor instead.
        ttk.Button(footer,text=tr('Edit with system editor'),command=lambda:(close(),native())).pack(side='left')
    cancel_button=ttk.Button(footer,text=tr('Cancel'),command=close)
    cancel_button.pack(side='right',padx=4)
    canvas.bind('<Configure>',lambda _:draw())
    def escape(_):
        if not wallpaper and mode.get()=='Crop':choose_mode('Pencil')
        else:close()
        return 'break'
    top.protocol('WM_DELETE_WINDOW',close);top.bind('<Escape>',escape)
    top.bind('<Destroy>',cleanup,add='+')
    def initialized(result):
        nonlocal source,preview_source
        source,preview_source=result;refresh()
    run(lambda:load_editor_image(path),initialized)
    return top


def wheel_zoom_factor(event, platform=None):
    import sys
    platform=platform or sys.platform
    delta=float(getattr(event,'delta',0))
    if getattr(event,'num',None) in (4,5): delta=120 if event.num==4 else -120; platform='win32'
    steps=delta/8 if platform=='darwin' else delta/120
    return 1.15 ** max(-4,min(4,steps))


def zoom_at(scale, pan, factor, point, size):
    """Keep the point under the cursor stationary, including when zoom hits a limit."""
    new=max(.25,min(12,scale*factor)); ratio=new/scale
    offset=(point[0]-size[0]/2,point[1]-size[1]/2)
    return new,[offset[i]-(offset[i]-pan[i])*ratio for i in (0,1)]


def lightbox(parent,path,go_to=None):
    from PIL import Image,ImageTk,ImageOps
    from .app_dialogs import messagebox
    original=None
    # A dim in-app overlay; no global desktop dimming or screenshot capture.
    top=tk.Toplevel(parent); top.transient(parent); top.overrideredirect(True)
    top.geometry(f'{parent.winfo_width()}x{parent.winfo_height()}+{parent.winfo_rootx()}+{parent.winfo_rooty()}')
    canvas=tk.Canvas(top,bg='#080b09',highlightthickness=0); canvas.pack(fill='both',expand=True)
    scale=[1.]; pan=[0,0]; drag=[None]
    closed=False
    def cleanup(event=None):
        nonlocal closed
        if event is not None and event.widget is not top:return
        if closed:return
        closed=True;repaint.cancel();work.close(lambda:close_images(original));canvas.photo=None
    def close():
        cleanup();top.destroy()
    def paint():
        if closed or original is None or not top.winfo_exists():return
        w,h=max(200,canvas.winfo_width()),max(200,canvas.winfo_height())
        fit=min((w-40)/original.width,(h-100)/original.height,1)
        factor=fit*scale[0]
        from .image_gestures import bounded_pan
        pan[:]=bounded_pan(pan,original.size,(w,h),factor)
        # Crop to visible viewport before resizing: zoom never allocates huge bitmaps.
        cx=original.width/2-pan[0]/factor; cy=original.height/2-pan[1]/factor
        box=(cx-w/2/factor,cy-h/2/factor,cx+w/2/factor,cy+h/2/factor)
        canvas.photo=ImageTk.PhotoImage(original.transform((w,h),Image.Transform.EXTENT,box,resample=Image.Resampling.BICUBIC),master=top)
        canvas.delete('picture'); canvas.create_image(0,0,image=canvas.photo,anchor='nw',tags='picture')
        canvas.tag_lower('picture')
    from .ui_work import FrameJob
    repaint=FrameJob(top,paint)
    draw=repaint.request
    def zoom(factor,point=None):
        size=(canvas.winfo_width(),canvas.winfo_height())
        scale[0],pan[:]=zoom_at(scale[0],pan,factor,point or (size[0]/2,size[1]/2),size)
        draw()
    controls=ttk.Frame(top); controls.place(relx=.5,rely=1,anchor='s',y=-12)
    for label,fn in [('−',lambda:zoom(1/1.25)),('+',lambda:zoom(1.25)),('×',close)]: ttk.Button(controls,text=label,command=fn,width=4).pack(side='left')
    if go_to: ttk.Button(controls,text=tr('Go to message'),command=lambda:(close(),go_to())).pack(side='left')
    ttk.Button(top,text='×',command=close).place(relx=1,x=-12,y=12,anchor='ne')
    def press(e): drag[0]=(e.x,e.y,pan[0],pan[1])
    def move(e):
        if drag[0]: pan[:]=[drag[0][2]+e.x-drag[0][0],drag[0][3]+e.y-drag[0][1]]; draw()
    def release(e):
        if original is not None and drag[0] and abs(e.x-drag[0][0])+abs(e.y-drag[0][1])<5:
            w,h=canvas.winfo_width(),canvas.winfo_height(); fit=min((w-40)/original.width,(h-100)/original.height,1)*scale[0]
            if abs(e.x-w/2-pan[0])>original.width*fit/2 or abs(e.y-h/2-pan[1])>original.height*fit/2: close()
        drag[0]=None
    canvas.bind('<ButtonPress-1>',press); canvas.bind('<B1-Motion>',move); canvas.bind('<ButtonRelease-1>',release)
    def reset():
        scale[0]=1.; pan[:]=[0,0]; draw()
    from .image_gestures import ImageGestures
    gestures=ImageGestures(canvas,scale,pan,zoom,draw,reset)
    gestures.controls(controls)
    ttk.Label(top,text=tr('Wheel / two fingers: selected mode · Shift: horizontal · Ctrl: zoom · drag: move')).place(relx=.5,y=12,anchor='n')
    canvas.bind('<Configure>',lambda _:draw()); top.bind('<Escape>',lambda _:close())
    top.bind('<Destroy>',cleanup,add='+')
    top.protocol('WM_DELETE_WINDOW',close)
    def failed(error):
        messagebox.showerror(tr('Preview and edit'),str(error),parent=top);close()
    work=ImageWork(top,failed)
    def load():
        with Image.open(path) as image:
            if image.width*image.height>30_000_000:raise ValueError(tr('This image is too large to preview.'))
            return ImageOps.exif_transpose(image).convert('RGB')
    def loaded(image):
        nonlocal original
        original=image;canvas.delete('loading');draw()
    canvas.create_text(20,20,text=tr('Loading...'),anchor='nw',fill='#8cf5a6',tags='loading')
    work.submit(load,loaded)
    top.focus_set()
    return top
