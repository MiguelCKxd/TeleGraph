"""One wheel router, inner scroll regions first, outer viewport at their edges."""
import sys
import tkinter as tk
from tkinter import ttk


def wheel_units(delta, platform=None):
    platform = platform or sys.platform
    return -int(delta) if platform == 'darwin' else -int(delta / 120)


def precise_deltas(packed):
    """Tk 8.7/9 TouchpadScroll packs signed X/Y pixels into one 32-bit delta."""
    value=int(packed) & 0xffffffff
    x,y=(value >> 16) & 0xffff,value & 0xffff
    return (x-65536 if x & 0x8000 else x, y-65536 if y & 0x8000 else y)


def hover_widget(root, event):
    """Windows can address wheel events to the focused widget, not the hovered one."""
    try:
        try: x,y=root.winfo_pointerxy()
        except AttributeError: x,y=event.x_root,event.y_root
        return root.winfo_containing(x,y)
    except KeyError:
        return None  # Tcl-owned native popup: leave its events to the system.
    except (AttributeError,tk.TclError):
        return event.widget if hasattr(event.widget,'winfo_class') else None


def panel_views(widget, axis, depth=8):
    """Find a unique nested scroll region under a panel's empty space."""
    views=[]
    if not depth: return views
    for child in widget.winfo_children():
        if isinstance(child, tk.Toplevel) or not child.winfo_ismapped(): continue
        if child.winfo_class() in ('Entry', 'TEntry', 'TCombobox', 'Combobox'): continue
        target=getattr(child, '_scroll_target', child)
        if hasattr(target, axis+'view') and target not in views: views.append(target)
        else: views.extend(panel_views(child, axis, depth-1))
        if len(views)>1: break
    return views



class WheelRouter:
    def __init__(self, root):
        self.root, self.remainders = root, {}
        self.tag = 'TgWheel' + str(id(root))
        root.bind_class(self.tag, '<MouseWheel>', self.wheel)
        root.bind_class(self.tag, '<Shift-MouseWheel>', self.wheel)
        for sequence in ('<Button-4>','<Button-5>','<Shift-Button-4>','<Shift-Button-5>'):
            root.bind_class(self.tag, sequence, self.wheel)
        root.bind_class(self.tag, '<Destroy>', self.forget)
        self.precise=False
        try:
            root.bind_class(self.tag, '<TouchpadScroll>', self.touchpad)
            self.precise=True
        except tk.TclError: pass  # Older Tk emits MouseWheel for two-finger gestures.
        # Map/Enter are delivered for each widget. Rewalking the entire root tree
        # on every pointer crossing is quadratic for large chat windows/dialogs.
        root.bind_all('<Map>', lambda event:self.install(event.widget,recursive=False), add='+')
        root.bind_all('<Enter>', lambda event:self.install(event.widget,recursive=False), add='+')
        self.install(root)

    def install(self, widget, recursive=True):
        if not hasattr(widget,'winfo_class'): return
        # A focused combobox must still route wheel input over another panel.
        # Only leave actual native menus out of the routing bindtag.
        if widget.winfo_class() == 'Menu': return
        tags=widget.bindtags()
        # Route before widget-specific handlers too: a focused image viewer must
        # not consume a wheel intended for a different panel under the pointer.
        if not tags or tags[0]!=self.tag: widget.bindtags((self.tag,*(tag for tag in tags if tag!=self.tag)))
        if recursive:
            for child in widget.winfo_children(): self.install(child)

    def forget(self,event):
        path=str(event.widget)
        self.remainders.pop((path,'x'),None)
        self.remainders.pop((path,'y'),None)

    def wheel(self,event):
        widget=hover_widget(self.root,event)
        if widget is None or widget.winfo_class() == 'Menu': return
        handler=getattr(widget,'_wheel_handler',None)
        if handler: handler(event); return 'break'
        number=getattr(event,'num',None)
        if number in (4,5): amount=-3 if number==4 else 3
        else:
            legacy_mac=sys.platform=='darwin' and not getattr(self,'precise',False)
            amount=-float(event.delta) if legacy_mac else -float(event.delta)/120*3
        if amount: return self.route(widget,event,amount)
        return 'break'

    def touchpad(self,event):
        widget=hover_widget(self.root,event)
        if widget is None or widget.winfo_class() == 'Menu': return
        dx,dy=precise_deltas(event.delta)
        handler=getattr(widget,'_touchpad_handler',None)
        if handler: handler(event,dx,dy); return 'break'
        if dx:self.route(widget,event,-dx,axis='x',pixels=True)
        if dy:self.route(widget,event,-dy,axis='y',pixels=True)
        return 'break'

    def route(self,widget,event,amount,axis=None,pixels=False):
        axis=axis or ('x' if event.state & 1 else 'y')
        visited=set();found_view=False
        while widget is not None:
            if widget.winfo_class()=='Menu':return
            # Hovering a scrollbar targets its linked view even if it lacks focus.
            if widget.winfo_class() in ('Scrollbar','TScrollbar'):
                command=widget.cget('command')
                if command:
                    key=(str(widget),axis)
                    value=self.remainders.get(key,0)+(amount/20 if pixels else amount); units=int(value)
                    self.remainders[key]=value-units
                    if units: widget.tk.call(*widget.tk.splitlist(command),'scroll',units,'units')
                    return 'break'
            target=getattr(widget,'_scroll_target',widget)
            outer=clipped_by_viewport(target,axis,amount)
            candidates=[outer,target] if outer is not None else [target]
            # A panel's unused space scrolls its visible content, not another window.
            if not found_view and not hasattr(target,axis+'view'):
                views=panel_views(target,axis)
                if len(views)==1: candidates.extend(views)
            for target in candidates:
                if str(target) in visited: continue
                visited.add(str(target))
                try:
                    first,last=getattr(target,axis+'view')()
                    found_view=True
                    if not (amount<0 and first>0 or amount>0 and last<1): continue
                    if isinstance(target,tk.Canvas):
                        region=target.tk.splitlist(target.cget('scrollregion'))
                        if len(region)==4:
                            start,end=(0,2) if axis=='x' else (1,3)
                            extent=float(region[end])-float(region[start])
                            if extent>0:
                                getattr(target,axis+'view_moveto')(first+amount*(1 if pixels else 8)/extent)
                                return 'break'
                    if pixels and target.winfo_class()=='Text':
                        getattr(target,axis+'view_scroll')(int(amount),'pixels')
                        return 'break'
                    key=(str(target),axis)
                    value=self.remainders.get(key,0)+(amount/(20 if axis=='y' else 10) if pixels else amount); units=int(value)
                    self.remainders[key]=value-units
                    if units: getattr(target,axis+'view_scroll')(units,'units')
                    return 'break'
                except (AttributeError,ValueError,tk.TclError): pass
            if isinstance(widget,(tk.Toplevel,tk.Tk)): break
            widget=getattr(widget,'master',None)
        return 'break'


def clipped_by_viewport(target,axis,amount):
    """1.5.0.1: an inner view (e.g. the article editor) that is partly hidden
    by its scrolled window lets that window scroll first, until the inner view
    is fully visible on that side; only then does the inner view scroll. In a
    small window this removed the 'stuck' feeling of scrolling a half-visible
    editor while the buttons below stayed out of reach."""
    if isinstance(target,tk.Canvas) and getattr(target,'_viewport',False):return None
    viewport=getattr(target,'master',None)
    while viewport is not None and not (isinstance(viewport,tk.Canvas) and getattr(viewport,'_viewport',False)):
        viewport=getattr(viewport,'master',None)
    if viewport is None:return None
    try:
        first,last=getattr(viewport,axis+'view')()
        if not (amount<0 and first>0 or amount>0 and last<1):return None
        if axis=='y':start,size,view_start,view_size=target.winfo_rooty(),target.winfo_height(),viewport.winfo_rooty(),viewport.winfo_height()
        else:start,size,view_start,view_size=target.winfo_rootx(),target.winfo_width(),viewport.winfo_rootx(),viewport.winfo_width()
        if amount>0 and start+size>view_start+view_size+1:return viewport
        if amount<0 and start<view_start-1:return viewport
    except (tk.TclError,AttributeError,ValueError):return None
    return None


def wrap_labels(parent,width):
    for widget in parent.winfo_children():
        if isinstance(widget,(tk.Label,ttk.Label)):
            if not hasattr(widget,'_wrap_limit'):
                try:widget._wrap_limit=int(widget.cget('wraplength'))
                except (ValueError,tk.TclError):widget._wrap_limit=0
            if widget._wrap_limit:
                value=min(width,widget._wrap_limit)
                if value!=getattr(widget,'_applied_wrap',None):
                    widget.configure(wraplength=value);widget._applied_wrap=value
        if isinstance(widget,(ttk.Frame,tk.Frame,ttk.LabelFrame)):wrap_labels(widget,width)


FIT_LIMIT = 760


class Viewport(ttk.Frame):
    def __init__(self, parent, minimum=(440, 420)):
        super().__init__(parent)
        self.minimum = minimum
        # Fixed 18-pixel increments discard slow, precise touchpad movement.
        self.canvas = tk.Canvas(self, highlightthickness=0, yscrollincrement=0, xscrollincrement=0)
        self.canvas._viewport = True
        v = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        h = ttk.Scrollbar(self, orient='horizontal', command=self.canvas.xview)
        self.on_scroll=None
        def moved(bar,first,last):
            bar.set(first,last)
            if self.on_scroll:self.on_scroll()
            self.schedule_text_redraw()
        self.canvas.configure(yscrollcommand=lambda a,b:moved(v,a,b),xscrollcommand=lambda a,b:moved(h,a,b))
        v.pack(side='right', fill='y'); h.pack(side='bottom', fill='x')
        self.canvas.pack(fill='both', expand=True)
        self.content = ttk.Frame(self.canvas, padding=8)
        self.fit_to_window = False
        self.content._scroll_target = self.canvas
        self.item = self.canvas.create_window(0, 0, window=self.content, anchor='nw')
        self.canvas.bind('<Configure>', self.resize)
        self.content.bind('<Configure>', self.fit_content)
        self.bind('<Destroy>', self.cancel_jobs, add='+')

    def cancel_jobs(self, event):
        if event.widget is self:
            for name in ('_request_job', '_redraw_job', '_fit_job'):
                handle = getattr(self, name, None)
                if handle is not None:
                    self.after_cancel(handle)
                    setattr(self, name, None)

    def watch_request(self):
        """An explicit height hides request changes from <Configure>: poll lightly."""
        if getattr(self,'_request_job',None) is not None:return
        def run():
            self._request_job=None
            try:
                if not self.winfo_exists():return
                requested=self.content.winfo_reqheight()
                if requested!=getattr(self,'_last_request',None):
                    self._last_request=requested;self.fit_content()
                elif self.fit_to_window:self.watch_request()
            except tk.TclError:pass
        try:self._request_job=self.after(400,run)
        except (tk.TclError,AttributeError):self._request_job=None

    def schedule_text_redraw(self):
        """Tk draws a Text embedded in a scrolled canvas only partly after the
        canvas moves (long article drafts showed cut lines until scrolled back
        to the top). Re-layout visible Text widgets once the scroll settles."""
        # Wait until scrolling settles (touchpad momentum sends many events);
        # re-laying the text on every step made small windows stutter.
        job=getattr(self,'_redraw_job',None)
        if job is not None:
            try:self.after_cancel(job)
            except tk.TclError:pass
        def run():
            self._redraw_job=None
            pending=[self.content]
            while pending:
                widget=pending.pop()
                try:
                    if widget.winfo_class()=='Text' and widget.winfo_ismapped():
                        top,bottom=widget.winfo_rooty(),widget.winfo_rooty()+widget.winfo_height()
                        view_top=self.canvas.winfo_rooty();view_bottom=view_top+self.canvas.winfo_height()
                        if bottom>view_top and top<view_bottom:  # Only text actually on screen.
                            widget.configure(padx=widget.cget('padx'))
                    else:pending.extend(widget.winfo_children())
                except tk.TclError:pass
        try:self._redraw_job=self.after(160,run)
        except tk.TclError:self._redraw_job=None

    def resize(self, event):
        from .ui_work import content_width
        content_width(self.canvas,self.item,max(self.minimum[0],event.width))
        wrap_labels(self.content,max(80,event.width-32))
        self.fit_content()

    def fit_content(self, event=None):
        from .ui_work import content_scrollregion
        # 1.4.1: even a window-fitted layout never gets less than it needs.
        # Below that, Tk clipped the last packed widgets (Send, toolbars) with
        # no way to reach them; now the viewport scrolls instead.
        # Height 0 lets Tk follow the content's own request as it grows (a
        # panel switch, a new toolbar), so nothing is clipped in between.
        filled=max(self.minimum[1],self.canvas.winfo_height())
        requested=self.content.winfo_reqheight()
        if getattr(self,'fit_to_window',False):
            # Window-fitted chat layout: grow to its real request (so Send and
            # the toolbars stay reachable) but never to a runaway request from
            # a toolbar that is still being arranged (v0.9 regression).
            height=filled if requested<=filled else min(requested,max(filled,FIT_LIMIT))
            self.watch_request()
        else:
            height=0 if requested>=filled else filled
        if height!=getattr(self,'_content_height',None):
            self._content_height=height;self.canvas.itemconfigure(self.item,height=height)
        content_scrollregion(self.canvas,self.item)


def flow_positions(sizes,available):
    available=max(1,available);x=y=line=0;positions=[]
    for width,height in sizes:
        width=min(available,width)
        if x and x+width>available:x,y,line=0,y+line+4,0
        positions.append((x,y,width,height));x+=width+4;line=max(line,height)
    return positions,y+line+4


class FlowFrame(ttk.Frame):
    """Wrap toolbar controls to available width without hiding any action."""
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.bind('<Configure>', self.arrange)
        self.bind('<Map>', self.arrange)
        self._arranging = False

    def arrange(self, event=None):
        if getattr(self, '_manual_layout', False): return
        if self._arranging or not self.winfo_exists(): return
        self._arranging = True
        try:
            available = max(100, self.winfo_width())
            children=[]
            for child in self.winfo_children():
                if getattr(child,'flow_hidden',False) or getattr(child,'_layout_hidden',False):
                    if child.winfo_manager()=='pack':child.pack_forget()
                    elif child.winfo_manager()=='place':child.place_forget()
                else:children.append(child)
            positions,height=flow_positions([(child.winfo_reqwidth(),child.winfo_reqheight()) for child in children],available)
            from .rtl_ui import flow_position
            for child,(x,y,width,item_height) in zip(children,positions):
                position=flow_position((x,y,width,item_height),available)
                if child.winfo_manager()!='place' or getattr(child,'_flow_position',None)!=position:
                    if child.winfo_manager()=='pack':child.pack_forget()
                    px,py,pwidth,pheight=position
                    child.place(x=px,y=py,width=pwidth,height=pheight);child._flow_position=position
            if height!=getattr(self,'_flow_height',None):self.configure(height=height);self._flow_height=height
        finally: self._arranging = False


def fit_to_content(window, viewport, margin=(48, 96)):
    """On open, grow a window so every control is visible (up to the screen).

    Anything that still does not fit stays reachable with the scrollbars, the
    wheel and touchpad gestures (WheelRouter) — never clipped.
    """
    def run(attempt=0):
        viewport._fit_job = None
        try:
            if not window.winfo_exists():
                return
            window.update_idletasks()
            content = viewport.content
            need_w = content.winfo_reqwidth() + 24
            need_h = content.winfo_reqheight() + 24
            have_w, have_h = window.winfo_width(), window.winfo_height()
            if have_w <= 1 and attempt < 5:
                viewport._fit_job = viewport.after(60, lambda: run(attempt + 1))
                return
            max_w = window.winfo_screenwidth() - margin[0]
            max_h = window.winfo_screenheight() - margin[1]
            width = min(max_w, max(have_w, need_w))
            height = min(max_h, max(have_h, need_h))
            if (width, height) != (have_w, have_h):
                x = min(max(0, window.winfo_x()), max(0, window.winfo_screenwidth() - width - 8))
                y = min(max(0, window.winfo_y()), max(0, window.winfo_screenheight() - height - 48))
                window.geometry(f'{width}x{height}+{x}+{y}')
        except tk.TclError:
            pass
    try:
        pending = getattr(viewport, '_fit_job', None)
        if pending is not None:
            viewport.after_cancel(pending)
        viewport._fit_job = viewport.after(80, run)
    except tk.TclError:
        pass
