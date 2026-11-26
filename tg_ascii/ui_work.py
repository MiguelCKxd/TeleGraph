"""Coalesce cosmetic work and never feed canvas drawing back into scrolling."""
from collections import OrderedDict
import tkinter as tk


class FrameJob:
    def __init__(self,widget,callback,delay=16):
        self.widget,self.callback,self.delay=widget,callback,delay;self.job=None
    def request(self,*_):
        if self.job is None:
            try:
                if self.widget.winfo_exists():self.job=self.widget.after(self.delay,self.run)
            except tk.TclError:pass
    def run(self):
        self.job=None
        try:exists=self.widget.winfo_exists()
        except tk.TclError:return
        if exists:self.callback()
    def cancel(self):
        job,self.job=self.job,None
        if job is not None:
            try:self.widget.after_cancel(job)
            except tk.TclError:pass


def bind_text_action(widget,tag,sequence,callback):
    """Keep Tcl callback IDs so replacing/removing a text tag releases Python closures."""
    bindings=vars(widget).get('_text_action_bindings')
    if bindings is None:bindings=widget._text_action_bindings={}
    previous=bindings.pop((tag,sequence),None)
    if previous:widget.tag_unbind(tag,sequence,previous)
    ident=widget.tag_bind(tag,sequence,callback)
    if ident:bindings[(tag,sequence)]=ident
    return ident


def clear_text_actions(widget):
    bindings=vars(widget).get('_text_action_bindings',{})
    # Text.tag_delete alone leaves registered Tcl commands and captured messages alive.
    for (tag,sequence),ident in list(bindings.items()):
        widget.tag_unbind(tag,sequence,ident)
    bindings.clear()


def sync_tree_rows(widget,rows):
    """Update labels/order in place, preserving avatars, selection and scroll position."""
    existing=tuple(widget.get_children());wanted=tuple(ident for ident,_ in rows)
    wanted_set=set(wanted);existing_set=set(existing)
    removed=[ident for ident in existing if ident not in wanted_set]
    if removed:widget.delete(*removed)
    labels=vars(widget).get('_synced_tree_labels',{})
    for ident,label in rows:
        if ident not in existing_set:
            widget.insert('','end',iid=ident,values=('⋯',),text=label)
        elif (labels[ident] if ident in labels else widget.item(ident,'text'))!=label:
            widget.item(ident,text=label)
    if existing!=wanted:widget.set_children('',*wanted)
    widget._synced_tree_labels=dict(rows)
    widget._synced_tree_order=wanted


def visible_tree_rows(widget,overscan=8):
    """Rows near the viewport only, including during geometry transitions."""
    if not widget.winfo_viewable() or widget.winfo_height()<2:return ()
    rows=vars(widget).get('_synced_tree_order')
    if rows is None:rows=widget.get_children()
    first,last=widget.yview();count=len(rows)
    start=max(0,int(float(first)*count)-overscan)
    # A newly packed tree may still report (0,1); do not prefetch every chat.
    end=min(count,int(float(last)*count)+1+overscan,
            start+max(32,widget.winfo_height()//20+2*overscan))
    return rows[start:end]


class CanvasCorners:
    def __init__(self,canvas):
        self.canvas=canvas;self.radius=0;self.background='';self.images=[];self.items=[];self.geometry=None;self.art=None
        self.job=FrameJob(canvas,self.draw)
        self.delete=canvas.delete
        for option in ('yscrollcommand','xscrollcommand'):
            command=canvas.cget(option);last=[None]
            def moved(*args,command=command,last=last):
                # Tk may report identical fractions after *drawing*. Do not rerun
                # gallery callbacks in that case, or they can redraw forever.
                if args!=last[0]:
                    last[0]=args
                    if command:canvas.tk.call(*canvas.tk.splitlist(command),*args)
                if self.radius:self.job.request()
            canvas.configure(**{option:moved})
        def delete(*tags):
            self.delete(*tags)
            if 'all' in tags or '_tgas_corners' in tags:
                self.items=[];self.geometry=None
                if self.radius:self.job.request()
        canvas.delete=delete
        canvas.bind('<Configure>',self.job.request,add='+')
        canvas.bind('<Destroy>',lambda e:self.job.cancel() if e.widget is canvas else None,add='+')

    def configure(self,radius,background):
        self.radius,self.background=radius,background
        if radius:self.job.request()
        else:
            self.job.cancel();self.delete('_tgas_corners');self.items=[];self.images=[];self.geometry=None;self.art=None

    def draw(self):
        if not self.radius:return
        canvas=self.canvas;w,h=canvas.winfo_width(),canvas.winfo_height();r=min(self.radius,w//2,h//2)
        if r<1:return
        art=(r,self.background);x,y=canvas.canvasx(0),canvas.canvasy(0)
        geometry=(art,x,y,w,h)
        if self.items and geometry==self.geometry:return
        if art!=self.art:
            from PIL import ImageTk
            from .appearance import corner_masks
            root=canvas._root()
            cache=getattr(root,'_corner_art_cache',None)
            if cache is None:cache=root._corner_art_cache=OrderedDict()
            if art not in cache:cache[art]=[ImageTk.PhotoImage(image,master=root) for image in corner_masks(r,self.background)]
            self.images=cache[art];cache.move_to_end(art)
            while len(cache)>16:cache.popitem(last=False)
            self.art=art
            for item,image in zip(self.items,self.images):canvas.itemconfigure(item,image=image)
        points=((x,y,'nw'),(x+w,y,'ne'),(x,y+h,'sw'),(x+w,y+h,'se'))
        if not self.items:
            self.items=[canvas.create_image(xx,yy,image=image,anchor=anchor,tags='_tgas_corners') for image,(xx,yy,anchor) in zip(self.images,points)]
        else:
            for item,(xx,yy,_) in zip(self.items,points):canvas.coords(item,xx,yy)
        canvas.tag_raise('_tgas_corners');self.geometry=geometry


def content_scrollregion(canvas,item):
    """Only the content window defines scrolling; viewport decoration must not grow it."""
    region=canvas.bbox(item)
    if region!=getattr(canvas,'_content_scrollregion',None):
        canvas._content_scrollregion=region
        canvas.configure(scrollregion=region or (0,0,0,0))


def content_width(canvas,item,width):
    width=max(1,width)
    if width!=getattr(canvas,'_content_width',None):
        canvas._content_width=width;canvas.itemconfigure(item,width=width)
