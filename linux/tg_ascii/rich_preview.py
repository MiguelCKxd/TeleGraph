from .appearance import app_palette
"""Compact rich text for replies and folder titles; custom emoji occupy one slot."""
import tkinter as tk
from tkinter import font
from .message_tools import entity_spans
from .text_layout import cluster_ends, iter_cluster_ends
from .visual_effects import canvas_text, bind_text


def preview_runs(text, entities=(), limit=120):
    _, spans = entity_spans(text, entities)
    starts = {a: (b, doc) for a, b, doc, *_ in spans if b > a}
    boundaries = iter_cluster_ends(text)
    boundary = next(boundaries, None)
    index = 0; count = 0; pending = ''
    while index < len(text) and count < limit:
        if index in starts:
            if pending: yield pending, None; pending = ''
            end, doc = starts[index]
            yield '', doc
            index = end
        else:
            while boundary is not None and boundary <= index:
                boundary = next(boundaries, None)
            stop = boundary if boundary is not None else index + 1
            pending += ''.join(' ' if char in '\n\r\t' else char if ord(char) >= 32 else '' for char in text[index:stop])
            index = stop
        count += 1
    if index < len(text): pending += '…'
    if pending: yield pending, None


def fit_text(value,width,measure):
    """Fit a whole span first, then bisect; avoid a Tcl measurement per character."""
    if width<=0:return '',bool(value)
    if measure(value)<=width:return value,False
    if measure('…')>width:return '',True
    ends=[0,*cluster_ends(value)]
    low,high=0,len(ends)-1
    while low<high:
        middle=(low+high+1)//2
        if measure(value[:ends[middle]]+'…')<=width:low=middle
        else:high=middle-1
    return value[:ends[low]]+'…',True


def draw_line(canvas, app, text, entities, x, y, width, text_font, color, tags=(), prefix='', callback=None):
    right = x + max(0, width); size = text_font.metrics('linespace') + 2
    items = []
    for value, doc in [(prefix, None), *preview_runs(text, entities)]:
        if doc:
            if x + size > right: break
            item = canvas.create_text(x,y,text='◇',anchor='nw',font=text_font,fill=color,tags=tags)
            if callback:
                if hasattr(canvas,'interactive'): canvas.interactive(item,callback)
                else:
                    tag=f'_preview_action:{item}';canvas.addtag_withtag(tag,item)
                    canvas.tag_bind(tag,'<Button-1>',lambda e:callback())
            app.canvas_emoji(canvas,item,doc,canvas.generation,size)
            items.append(item); x += size
        elif value:
            clipped,truncated=fit_text(value,right-x,text_font.measure)
            if not clipped:break
            item=canvas_text(canvas,x,y,text=clipped,anchor='nw',font=text_font,fill=color,tags=tags)
            items.append(item)
            if callback:
                if hasattr(canvas,'interactive'): canvas.interactive(item,callback)
                else: bind_text(canvas,item,'<Button-1>',lambda e:callback())
            x += text_font.measure(clipped)
            if truncated: break
    return items


class RichPreview(tk.Canvas):
    def __init__(self,parent,app,text='',entities=(),prefix='',command=None,**kwargs):
        self.colors=app_palette(app.preferences.values)
        super().__init__(parent,height=26,width=150,highlightthickness=0,bg=self.colors['panel'],**kwargs)
        self.app=app; self.text=text; self.entities=entities; self.prefix=prefix; self.command=command
        self.generation=0; self.photos=[]
        self.text_font=font.Font(root=self,family=app.font_family,size=10)
        self.bind('<Configure>',lambda _:self.render())
        if command: self.bind('<Button-1>',lambda _:self.command())
    def set(self,text,entities=(),prefix=''):
        self.text,self.entities,self.prefix=text,entities,prefix
        self.render()
    def render(self):
        self.generation+=1;self.delete('all');self.photos=[]
        if getattr(self,'accent',None):self.create_rectangle(0,0,3,self.winfo_height(),fill=self.accent,outline='')
        draw_line(self,self.app,self.text,self.entities,4,3,max(20,self.winfo_width()-8),self.text_font,self.colors['text'],prefix=self.prefix)
