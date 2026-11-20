from .appearance import app_palette
from .timestamps import message_time
"""Canvas message view: aligned bubbles, reply navigation and direct gestures."""
import tkinter as tk
from functools import lru_cache
from heapq import heappush, heappop
from tkinter import font
from .i18n import tr
from .links import message_links
from .message_tools import entity_spans
from .text_layout import cluster_ends
from .visual_effects import canvas_text


def rich_runs(message,links_enabled=True):
    text=message.raw_text if message.raw_text is not None else message.text
    _,emojis=entity_spans(text,getattr(message,'entities',()))
    links=list(message_links(text,getattr(message,'entities',()))) if links_enabled else []
    if not links and not emojis:
        if text:yield text,None,None
        return
    starts={start:(end,document) for start,end,document,*_ in emojis if end>start}
    events={}
    boundaries={0,len(text),*starts}
    for priority,(start,end,url) in enumerate(links):
        boundaries.update((start,end))
        events.setdefault(start,[]).append((priority,end,url))
    boundaries.update(end for end,_ in starts.values())
    points=sorted(boundaries);active=[];cursor=0;pending=None
    for start,end in zip(points,points[1:]):
        for entry in events.get(start,()):heappush(active,entry)
        while active and active[0][1]<=start:heappop(active)
        if start<cursor:continue
        if start in starts:
            if pending is not None:
                a,b,url=pending;yield text[a:b],url,None;pending=None
            cursor,document=starts[start]
            yield '◇',None,document
            continue
        url=active[0][2] if active else None
        if pending is not None and pending[2]==url and pending[1]==start:
            pending=(pending[0],end,url)
        else:
            if pending is not None:
                a,b,previous=pending;yield text[a:b],previous,None
            pending=(start,end,url)
    if pending is not None:
        a,b,url=pending;yield text[a:b],url,None


def cached_measure(face):
    cached=lru_cache(maxsize=1024)(face.measure)
    return lambda text:cached(text) if len(text)<=4096 else face.measure(text)


def message_signature(message, app=None):
    if message is None:return None
    time_str = message_time(message, getattr(app, 'preferences', None) and app.preferences.values) if app else message.time
    return (message.id,message.sender,message.text,message.raw_text,time_str,message.outgoing,
            message.media_kind,message.filename,message.size,id(message.media),message.custom_emojis,
            tuple(bytes(entity) for entity in message.entities),message.reply_to_id,message.read,
            tuple(message.reactions),message.sender_id,message.sender_color,message.reply_icon_id,
            bytes(message.reply_markup) if message.reply_markup is not None else None,
            message.keyboard_applicable, getattr(message, 'comments_count', None))


def layout_text_run(text,x,y,left,right,line,measure):
    """Measure whole spans, then bisect overflowing lines instead of one Tcl call per character."""
    chunks=[]
    for index,paragraph in enumerate(text.split('\n')):
        if index:x=left;y+=line
        ends=cluster_ends(paragraph); start=0; cluster=0
        while start<len(paragraph):
            available=max(0,right-x);remaining=len(ends)-cluster
            if measure(paragraph[start:])<=available:count=remaining
            else:
                low,high=0,remaining
                while low<high:
                    mid=(low+high+1)//2
                    if measure(paragraph[start:ends[cluster+mid-1]])<=available:low=mid
                    else:high=mid-1
                count=low
            if not count and x>left:x=left;y+=line;continue
            count=max(1,count)
            stop=ends[cluster+count-1];chunk=paragraph[start:stop]
            chunks.append((x,y,chunk));x+=measure(chunk);start=stop;cluster+=count
            if start<len(paragraph):x=left;y+=line
    return chunks,x,y


def bubble_left(width,bubble_width,outgoing):
    return max(12,width-bubble_width-16) if outgoing else 16


class BubbleView(tk.Canvas):
    def __init__(self,parent,app,**kwargs):
        super().__init__(parent,highlightthickness=0,**kwargs)
        self.app=app; self.messages=[]; self.locations={}; self.photos=[]; self.generation=0
        self._nodes={}; self._bindings=[]; self._job=None; self._click=None; self._hold=None; self._press=None
        self.bind('<Configure>',self.resize)
        from .interactions import ContextGesture
        from .motion import motion_event
        self.gesture=ContextGesture(self,self.target,self.app.message_actions,
            single=lambda m:self.app.toggle_message_selection(m) if getattr(self.app,'selection_kind',None)=='messages' else None,
            reply=self.app.reply_message,animate=self.swipe_feedback,
            scope=lambda:(self.app.ui_account,self.app.active),double=self.app.quick_react,click=self.profile_click,
            motion_options=lambda:motion_event(self.app))
        self.bind('<Escape>',lambda _:self.app.clear_selection() if getattr(self.app,'selection_kind',None) else None)
        self._swipe_offset=0
    def destroy(self):
        if getattr(self,'_swipe_motion',None):self._swipe_motion.cancel()
        for job in (self._job,self._click,self._hold):
            if job:
                try: self.after_cancel(job)
                except tk.TclError: pass
        # Do not leave Tk images/fonts in callback cycles for a worker's GC.
        self._nodes.clear();self.photos=[];self._bindings=[]
        self.wallpaper=None;self._swipe_photo=None
        self._measures=();self._text_fonts=()
        super().destroy()

    def resize(self,event=None):
        size=(self.winfo_width(),self.winfo_height())
        if size==getattr(self,'_last_size',None):return
        self._last_size=size
        if self._job: self.after_cancel(self._job)
        self._job=self.after(80,lambda:self.render(self.messages,False))
    def target(self,event):
        tags=self.gettags('current')
        for tag in tags:
            if tag.startswith('message:'): return next((m for m in self.messages if m.id==int(tag.split(':')[1])),None)
        return None
    def profile_click(self,event):
        if getattr(self.app,'selection_kind',None):return None
        message=self.target(event)
        if message and 'sender_profile' in self.gettags('current'):
            scope=(self.app.ui_account,self.app.active)
            return lambda:self.app.open_sender_profile(message,scope)

    def swipe_feedback(self,message,offset,release):
        from .motion import motion_event, ReturnMotion, indicator_photo
        event=motion_event(self.app)
        previous=getattr(self,'_swipe_motion',None)
        if previous:previous.cancel()
        tag=f'message:{message.id}'
        if not event['enabled']:
            self.move(tag,-getattr(self,'_swipe_offset',0),0);self._swipe_offset=0
            self.delete('swipe_hint');self._swipe_photo=None;return
        if not release:
            previous=getattr(self,'_swipe_offset',0)
            if not previous:self._swipe_photo=indicator_photo(self.app,event)
            self.move(tag,offset-previous,0);self._swipe_offset=offset
            self.delete('swipe_hint')
            bounds=self.bbox(tag)
            if bounds:
                x,y=min(self.winfo_width()-12,bounds[2]+25),bounds[1]+20
                if self._swipe_photo:self.create_image(x,y,image=self._swipe_photo,tags='swipe_hint')
                else:canvas_text(self,x,y,text='↩',fill='#8cf5a6',font=self._text_fonts[0],tags='swipe_hint')
            return
        start=getattr(self,'_swipe_offset',0);epoch=self.generation
        def update(target):
            self.move(tag,target-self._swipe_offset,0);self._swipe_offset=target
        def finish():self.delete('swipe_hint');self._swipe_photo=None
        if start:self._swipe_motion=ReturnMotion(self,start,update,finish,event,lambda:self.generation==epoch)

    def rounded(self,x,y,w,h,color,tag):
        from .appearance import rounded_points
        radius=self.app.preferences.values.get('bubble_radius',0)
        if not radius:return self.create_rectangle(x,y,x+w,y+h,fill=color,outline='',tags=tag)
        return self.create_polygon(rounded_points(x,y,w,h,radius),fill=color,outline='',tags=tag)
    def interactive(self,item,callback):
        tag=f'interactive:{item}'; self.addtag_withtag(tag,item)
        self.addtag_withtag(tag,f'_effect_text:{item}')
        def activate(event):
            state=getattr(self.gesture,'press_state',None)
            if getattr(self.app,'selection_kind',None)=='messages' or self.gesture.held:return
            if state and abs(event.x-state[0])+abs(event.y-state[1])<8:callback()
        ident=self.tag_bind(tag,'<ButtonRelease-1>',activate)
        self._bindings=getattr(self,'_bindings',[])
        self._bindings.append((tag,ident))
    def keep_photo(self,item,photo):
        for tag in self.gettags(item):
            if tag.startswith('message:'):
                node=self._nodes.get(int(tag.split(':')[1]))
                if node is not None:node['photos'].append(photo);return
        self.photos.append(photo)

    def discard_node(self,ident):
        node=self._nodes.pop(ident)
        for tag,binding in node['bindings']:
            if binding:self.tag_unbind(tag,'<ButtonRelease-1>',binding)
        self.delete(f'message:{ident}')

    def render(self,messages,follow=True):
        from .translated_view import presentation, toggle_original
        from .animated_emojis import animated_content
        if getattr(self,'_swipe_motion',None):self._swipe_motion.cancel()
        force=bool(getattr(self,'_swipe_offset',0))
        self._swipe_photo=None
        if self._job is not None:self.after_cancel(self._job)
        self._job=None;previous=self.yview()[0];self.messages=list(messages)
        self.locations={};self._swipe_offset=0
        from .customization_sync import palette_for_chat
        c=palette_for_chat(self.app,app_palette(self.app.preferences.values))
        if self.cget('bg')!=c['bg']:self.configure(bg=c['bg'])
        family=self.app.font_family
        key=(family,self.app.preferences.values['font_size'])
        if key!=getattr(self,'_font_key',None):
            self._text_fonts=(font.Font(root=self,family=family,size=key[1]),font.Font(root=self,family=family,size=10));self._font_key=key
            self._measures=tuple(cached_measure(face) for face in self._text_fonts)
        body,small=self._text_fonts
        measure_body,measure_small=self._measures
        self._text_fonts=(body,small)  # Keep named fonts alive for the canvas items.
        use_bubbles=self.app.preferences.values.get('bubbles',True)
        from .line_breaking import mode as line_mode, layout as break_layout
        break_mode=line_mode(self.app.preferences.values);break_language=self.app.preferences.values.get('language','en')
        line=body.metrics('linespace')+3; width=max(120,self.winfo_width()); max_width=min(570,max(80,int(width*.76))) if use_bubbles else max(80,width-32); y=18
        context=(self.app.ui_account,self.app.active,width,tuple(sorted(self.app.preferences.values.items())),
                 tuple(sorted(c.items())),family,getattr(self.app,'selection_kind',None))
        if force or context!=getattr(self,'_render_context',None):
            for ident in list(self._nodes):self.discard_node(ident)
            self.delete('all');self.photos=[];self.generation+=1
            self._render_context=context
        by_id={message.id:message for message in messages}
        for ident in set(self._nodes)-set(by_id):self.discard_node(ident)
        epoch=self.generation
        from .day_separators import day_headers
        base_palette = c
        bubble_palettes = {}
        for outgoing, key in ((True, 'bubble_out_color'), (False, 'bubble_in_color')):
            color = self.app.preferences.values.get(key) if use_bubbles else None
            if color:
                rgb = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
                linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]
                ink = '#000000' if sum(a*b for a, b in zip(linear, (.2126,.7152,.0722))) > .179 else '#ffffff'
                bubble_palettes[outgoing] = dict(c, text=ink, muted=ink, strong=ink, selected=color, panel=color)
        for m,day_header in zip(messages,day_headers(messages)):
            c = base_palette
            content,translation_key,translation_label=presentation(self.app,m)
            content=animated_content(self.app,content)
            from .expandable_text import presentation as quote_presentation, toggle, control_label
            content,quote_controls=quote_presentation(self.app,content)
            original=(by_id.get(m.reply_to_id) or self.app.reply_cache.get((self.app.ui_account,self.app.active,m.reply_to_id))) if m.reply_to_id else None
            accent=self.app.message_accent(m)
            quote_accent=self.app.message_accent(original) if original else accent
            selected=getattr(self.app,'message_selected',lambda _:False)(m.id)
            signature=(message_signature(m, self.app),message_signature(content, self.app),translation_key,translation_label,
                       message_signature(original, self.app),tuple(accent),tuple(quote_accent),selected,quote_controls,day_header)
            node=self._nodes.get(m.id)
            if node is not None and node['signature']==signature:
                delta=y-node['start']
                if delta:self.move(f'message:{m.id}',0,delta)
                node['start']=y;self.locations[m.id]=y;y+=node['height']
                continue
            if node is not None:self.discard_node(m.id)
            self._bindings=[]
            plain=content.raw_text if content.raw_text is not None else content.text
            m_time = message_time(m, getattr(self.app, 'preferences', None) and self.app.preferences.values)
            measured=max([measure_body(part) for part in plain.splitlines()]+[measure_small(m.sender),measure_small(m_time+' ✓✓'),90])+28
            if translation_key: measured=max(measured,measure_small(tr(translation_label))+28)
            if m.media: measured=max(measured,280)
            if m.reply_to_id: measured=max(measured,260)
            if type(getattr(m,'reply_markup',None)).__name__=='ReplyInlineMarkup': measured=max(measured,300)
            bw=min(max_width,measured) if use_bubbles else max_width
            tag=f'message:{m.id}'; x=bubble_left(width,bw,m.outgoing) if use_bubbles else 16; start=y; self.locations[m.id]=y
            if day_header:
                # Centred date pill before the first message of each day.
                label_item=self.create_text(width/2,y+5,text=day_header,anchor='n',font=small,fill=c['muted'],tags=(tag,'day_divider'))
                left_edge,top_edge,right_edge,bottom_edge=self.bbox(label_item)
                pill=self.rounded(left_edge-10,top_edge-3,right_edge-left_edge+20,bottom_edge-top_edge+6,c['panel'],tag)
                self.tag_raise(label_item,pill)
                y=bottom_edge+14
            bubble_top=y
            if m.outgoing in bubble_palettes:
                c = bubble_palettes[m.outgoing]
                accent = quote_accent = [c['text']]
            marker=('☑ ' if selected else '☐ ') if getattr(self.app,'selection_kind',None)=='messages' else ''
            name=self.app.text_display(m.sender,True)
            sender_item=canvas_text(self,x+14,y+10,text=marker+name,anchor='nw',font=small,width=max(30,bw-28),fill=accent[0],tags=(tag,'sender_profile'))
            y=max(y+31,self.bbox(sender_item)[3]+10)
            if m.reply_to_id:
                quote_y=y
                from .rich_preview import draw_line
                quote=(original.raw_text if original.raw_text is not None else original.text) if original else tr('Reply to message')+f' #{m.reply_to_id}'
                draw_line(self,self.app,quote,getattr(original,'entities',()),x+14,y,bw-60,small,quote_accent[0],tags=tag,
                          prefix='↪ '+original.sender+' · ' if original else '↪ ',callback=lambda mid=m.reply_to_id:self.app.jump_message(mid))
                y+=small.metrics('linespace')+12
                for index,color in enumerate(quote_accent[:3]): self.create_rectangle(x+5+index*2,quote_y,x+7+index*2,y-4,fill=color,outline='',tags=tag)
                if original and original.reply_icon_id:
                    icon=self.create_text(x+bw-35,quote_y,text='◇',anchor='nw',font=small,fill=quote_accent[0],tags=tag)
                    self.app.canvas_emoji(self,icon,original.reply_icon_id,epoch,22)
            px=x+14; left=px; right=x+bw-14
            from .advanced_features import feature_enabled
            for text,url,doc in rich_runs(content,feature_enabled(self.app,'links')):
                if doc:
                    if px+line>right: px=left; y+=line
                    item=self.create_text(px,y,text='◇',anchor='nw',fill=c['text'],font=body,tags=tag)
                    self.interactive(item,lambda d=doc:self.app.show_document_pack(d))
                    self.app.canvas_emoji(self,item,doc,epoch,line); px+=line; continue
                if break_mode=='auto':chunks,px,y=layout_text_run(text,px,y,left,right,line,measure_body)
                else:chunks,px,y=break_layout(text,px,y,left,right,line,measure_body,break_mode,break_language)
                for tx,ty,chunk in chunks:
                    item=canvas_text(self,tx,ty,text=chunk,anchor='nw',fill=c['text'],font=body,tags=tag)
                    if url:self.itemconfigure(item,font=(family,body.cget('size'),'underline'));self.interactive(item,lambda u=url:self.app.open_link(u))
            y+=line+5
            for offset,expanded in quote_controls:
                item=canvas_text(self,x+14,y,text=control_label(expanded),anchor='nw',font=(family,10,'underline'),fill=c['text'],tags=tag)
                self.interactive(item,lambda ident=m.id,value=offset,scope=(self.app.ui_account,self.app.active):toggle(self.app,ident,value,scope))
                y+=small.metrics('linespace')+8
            if m.media:
                if m.media_kind in ('image','sticker','video') and self.app.preferences.values['inline_media']:
                    item=self.create_text(x+14,y+10,text=tr('Loading...'),anchor='nw',font=body,fill=c['text'],tags=tag)
                    self.app.canvas_media(self,item,m,epoch,(int(bw-28),180))
                    self.interactive(item,lambda msg=m:self.app.open_image_message(msg))
                    y+=190
                else:
                    label = (tr('Join') + ' · ' if not getattr(m.media, 'missed', False) else '') + tr('Conference call') if m.media_kind == 'conference' else m.filename or tr('Attachment')
                    item=canvas_text(self,x+14,y,text=label,anchor='nw',font=body,fill=c['text'],tags=tag)
                    self.interactive(item,lambda msg=m:self.app.view_message_media(msg)); y+=26
            if translation_key:
                item=canvas_text(self,x+14,y,text=tr(translation_label),anchor='nw',font=(family,10,'underline'),width=max(30,bw-28),fill=c['text'],tags=tag)
                self.interactive(item,lambda key=translation_key:toggle_original(self.app,key))
                y=self.bbox(item)[3]+8
            if getattr(m, 'comments_count', None) is not None:
                item=canvas_text(self,x+14,y,text=f'💬 {m.comments_count}',anchor='nw',font=small,fill=c['text'],tags=tag)
                self.interactive(item,lambda msg=m:self.app.open_comments(msg))
                y+=26
            for value,count,chosen in getattr(m,'reactions',()):
                custom=isinstance(value,int)
                item=canvas_text(self,x+14+(18 if custom else 0),y,text=('' if custom else value)+f' {count}'+(' ✓' if chosen else ''),anchor='nw',fill=c['text'],font=small,tags=tag)
                action=lambda msg=m,v=value:self.app.send_reaction(msg,v)
                self.interactive(item,action)
                if custom:
                    icon=self.create_text(x+14,y,text='◇',anchor='nw',fill=c['text'],font=small,tags=tag)
                    self.interactive(icon,action)
                    self.app.canvas_emoji(self,icon,value,epoch,18)
                y+=24
            item=canvas_text(self,x+bw-12,y,text=m_time+(' ✓✓' if m.read else ' ✓' if m.outgoing else ''),anchor='ne',font=small,fill=c['muted'],tags=tag)
            y+=27
            if use_bubbles or selected:
                bg=self.rounded(x,bubble_top,bw,y-bubble_top,c['selected'] if m.outgoing else c['panel'],tag); self.tag_lower(bg)
                if selected:self.itemconfigure(bg,outline=c['text'],width=2)
            if type(getattr(m,'reply_markup',None)).__name__=='ReplyInlineMarkup':
                from .desktop_bot_buttons import paint_buttons
                y=paint_buttons(self,self.app,m,x,y+4,bw,tag,self.interactive)
            y+=14
            self._nodes[m.id]={'signature':signature,'start':start,'height':y-start,
                              'bindings':self._bindings,'photos':[]}
        self._bindings=[binding for node in self._nodes.values() for binding in node['bindings']]
        self.configure(scrollregion=(0,0,width,max(y,self.winfo_height())))
        self.app.draw_bubble_wallpaper(self)
        self.yview_moveto(1 if follow else previous)
    def jump(self,ident):
        if ident not in self.locations: return False
        total=float(self.cget('scrollregion').split()[-1]); self.yview_moveto(max(0,self.locations[ident]-20)/max(1,total)); return True
