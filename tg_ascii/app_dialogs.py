"""Native dropdowns and prompts, with compact app palettes for emoji."""
import tkinter as tk
from tkinter import ttk
from .ui_work import content_scrollregion,content_width

BG, FG = '#08100c', '#8cf5a6'


def window(parent, title, size='540x300'):
    top = tk.Toplevel(parent)
    top.title(title)
    top.configure(bg=BG)
    top.geometry(size)
    top.transient(parent)
    frame = ttk.Frame(top, padding=18)
    frame.pack(fill='both', expand=True)
    from .themes import apply_widget
    # The root owns the Tcl command even if this dialog closes before idle.
    top._root().after_idle(lambda: apply_widget(top) if top.winfo_exists() else None)
    return top, frame


class Choice(ttk.Combobox):
    """Native readonly dropdown, including keyboard navigation and dismissal."""
    def __init__(self, parent, values=(), state=None, **kwargs):
        super().__init__(parent, values=list(values), state='readonly', **kwargs)

    def bind(self, sequence=None, func=None, add=None):
        if sequence == '<<ComboboxSelected>>' and func is not None:
            callback = func
            def deferred(event):
                root = self._root()
                root.after_idle(lambda: callback(event) if self.winfo_exists() else None)
                return 'break'
            func = deferred
        return super().bind(sequence, func, add)


class CheckList(tk.Listbox):
    """Each click toggles one contact; no modifier keys required."""
    def __init__(self, parent, **kwargs):
        kwargs.pop('selectmode', None)
        super().__init__(parent, selectmode='multiple', **kwargs)
        self.labels, self.checked = [], set()
        self.bind('<Button-1>', self.toggle_at)
        self.bind('<space>', lambda _: self.toggle(self.index('active')))
    def insert(self, index, *values):
        for value in values:
            self.labels.append(str(value))
            super().insert('end', '☐ ' + str(value))
    def toggle_at(self, event):
        return self.toggle(self.nearest(event.y))
    def toggle(self, index):
        if not 0 <= index < len(self.labels): return 'break'
        if index in self.checked: self.checked.remove(index)
        else: self.checked.add(index)
        # Keep scroll position and avoid the Listbox modifier-key bindings.
        position = self.yview()[0]
        super().delete(index)
        super().insert(index, ('☑ ' if index in self.checked else '☐ ') + self.labels[index])
        for selected in self.checked: self.selection_set(selected)
        self.activate(index)
        self.yview_moveto(position)
        return 'break'
    def curselection(self):
        return tuple(sorted(self.checked))


# Public dialog re-exports are consumed throughout the desktop modules.
# Standard platform dialogs avoid stacking app-owned modal windows.
from tkinter import filedialog as _filedialog, messagebox as _messagebox, simpledialog as _simpledialog


def locked_parent(parent=None):
    parent=parent or tk._default_root
    if not isinstance(parent,tk.Misc):return False
    if vars(parent.winfo_toplevel()).get('_app_lock_gate',False):return False
    owner=vars(parent._root()).get('_lock_app_owner')
    return owner is not None and bool(getattr(owner,'_app_locked',False))


class _PrivateDialogs:
    """Native prompts cannot reveal late callback data above the lock screen.

    1.5.1: ``kind`` names the Settings › Menus entry; when it selects the app
    version, the same call goes to app_menus (same signature and result)."""
    def __init__(self,module,kind=None):self.module=module;self.kind=kind
    def __getattr__(self,name):
        original=getattr(self.module,name)
        if not callable(original) or not name.startswith(('ask','show')):return original
        kind=self.kind
        def guarded(*args,**kwargs):
            if locked_parent(kwargs.get('parent')):
                if name in ('askyesno','askokcancel','askretrycancel'):return False
                if name=='askquestion':return 'cancel'
                if name in ('askopenfilenames',):return ()
                if name in ('askopenfilename','asksaveasfilename','askdirectory'):return ''
                if name=='askcolor':return (None,None)
                return None
            if kind is not None:
                from .menu_style import choice
                if choice(kind)=='app':
                    from . import app_menus
                    replacement=getattr(app_menus,name,None)
                    if replacement is not None:return replacement(*args,**kwargs)
            return original(*args,**kwargs)
        return guarded


from tkinter import colorchooser as _colorchooser
filedialog=_PrivateDialogs(_filedialog,'file_picker')
messagebox=_PrivateDialogs(_messagebox,'message_box')
simpledialog=_PrivateDialogs(_simpledialog)
colorchooser=_PrivateDialogs(_colorchooser,'color_picker')


def event_action(widget, callback):
    """Consume the original input before opening another UI surface."""
    widget.after_idle(callback)
    return 'break'


def popup_menu(parent, entries, anchor=None, event=None):
    """Use system menus for ordinary actions; retain rich folder artwork."""
    if locked_parent(parent):return None
    entries = list(entries)
    from .menu_style import choice
    if choice('context_menu') == 'app':
        from . import custom_menus
        if custom_menus.active('context_menu'):
            # 1.5.2: the user's own menu (menus/context_menu/style.json or menu.py).
            entries = custom_entries(entries, custom_menus.style('context_menu'))
            return custom_menus.run('context_menu', lambda: rich_popup_menu(parent, entries, anchor, event, kind='context_menu'),
                                    parent, entries, anchor, event)
        return rich_popup_menu(parent, entries, anchor, event)  # 1.5.1 Settings › Menus
    native_entries = []
    for entry in entries:
        if entry is None:
            native_entries.append(None); continue
        label = entry[0]
        if hasattr(label, 'build_menu'):
            label = getattr(label, 'native_menu_label', lambda:None)()
            if label is None: return rich_popup_menu(parent, entries, anchor, event)
        native_entries.append((str(label), *entry[1:]))
    owner, root = parent.winfo_toplevel(), parent._root()
    for name in ('_context_menu', '_popover'):
        previous = getattr(root, name, None)
        if previous:
            try: getattr(previous, '_dismiss', previous.destroy)()
            except tk.TclError: pass
    menu = tk.Menu(owner, tearoff=False)
    root._context_menu = menu
    chosen = [None]; closed = [False]; disposed = [False]; queued = [False]

    def finish():
        queued[0] = False
        if disposed[0]: return
        if getattr(root, '_native_menu_tracking', None) is menu:
            queued[0] = True; root.after(10, finish); return
        disposed[0] = True
        try:
            menu.unpost()
            if menu.grab_current() is menu: menu.grab_release()
            menu.destroy()
        except tk.TclError: pass
        if getattr(root, '_context_menu', None) is menu: root._context_menu = None
        if chosen[0] is not None:
            callback = chosen[0]; chosen[0] = None
            root.after_idle(callback)

    def queue_finish(_=None):
        if not queued[0] and not disposed[0]:
            queued[0] = True; root.after_idle(finish)

    def dismiss():
        closed[0] = True; chosen[0] = None
        try: menu.unpost()
        except tk.TclError: pass
        queue_finish()

    def invoke(callback):
        if closed[0] or disposed[0]: return
        closed[0] = True; chosen[0] = callback
        menu.unpost(); queue_finish()

    menu._dismiss = dismiss
    for entry in native_entries:
        if entry is None: menu.add_separator(); continue
        label, callback = entry[:2]
        enabled = entry[2] if len(entry) > 2 else True
        menu.add_command(label=label, command=lambda fn=callback:invoke(fn), state='normal' if enabled else 'disabled')
    menu.bind('<Unmap>', queue_finish, add='+')
    menu.bind('<Destroy>', queue_finish, add='+')
    if event: x, y = event.x_root, event.y_root
    elif anchor: x, y = anchor.winfo_rootx(), anchor.winfo_rooty() + anchor.winfo_height()
    else: x, y = owner.winfo_pointerxy()

    def show():
        if locked_parent(parent):dismiss();return
        if closed[0] or disposed[0] or getattr(root, '_context_menu', None) is not menu:
            dismiss(); return
        if getattr(root, '_native_menu_tracking', None) is not None:
            root.after(10, show); return
        root._native_menu_tracking = menu
        try:
            menu.tk_popup(x, y)
        finally:
            root._native_menu_tracking = None
            if chosen[0] is not None or closed[0] or not menu.winfo_exists() or not menu.winfo_ismapped(): queue_finish()
    # Cocoa must not start tracking a native menu inside the triggering gesture.
    root.after_idle(show)
    return menu


def custom_entries(entries, style):
    """Rename, hide and reorder menu items as the user's style.json says."""
    rename = style.get('rename') or {}
    hide = set(style.get('hide') or ())
    order = list(style.get('order') or ())
    result = []
    for entry in entries:
        if entry is None:
            result.append(None); continue
        label = entry[0]
        text = str(label) if not hasattr(label, 'build_menu') else None
        if text is not None and text in hide:
            continue
        if text is not None and text in rename:
            entry = (str(rename[text]), *entry[1:])
        result.append(entry)
    if order:
        rank = {name: index for index, name in enumerate(order)}
        def key(item):
            index, entry = item
            if entry is None: return (len(rank), index)
            label = entry[0]
            original = next((old for old, new in rename.items() if new == str(label)), str(label))
            return (rank.get(original, rank.get(str(label), len(rank))), index)
        result = [entry for _, entry in sorted(enumerate(result), key=key)]
    while result and result[0] is None: result.pop(0)
    while result and result[-1] is None: result.pop()
    return result


def rich_popup_menu(parent, entries, anchor=None, event=None, kind=None):
    """App-owned dropdown: never invoke Tk/Cocoa's native menu tracking loop."""
    from .themes import _palette
    custom = {}
    if kind:
        from .custom_menus import style as user_style
        custom = user_style(kind)
    owner = parent.winfo_toplevel()
    root = parent._root()
    previous = getattr(root, '_context_menu', None)
    if previous:
        try: getattr(previous, '_dismiss', previous.destroy)()
        except tk.TclError: pass
    previous = getattr(root, '_popover', None)
    if previous:
        try: previous.destroy()
        except tk.TclError: pass
    menu = tk.Toplevel(owner)
    menu.withdraw()
    menu.transient(owner)
    menu.overrideredirect(True)
    menu.configure(bg=custom.get('border') or _palette['line'])
    root._context_menu = menu
    subscriptions = []
    selected = [False]
    buttons = []
    prior_focus = owner.focus_get()
    def cleanup(e):
        if e.widget is not menu: return
        if getattr(root, '_context_menu', None) is menu: root._context_menu = None
        for target, sequence, ident in subscriptions:
            try: target.unbind(sequence, ident)
            except tk.TclError: pass
    menu.bind('<Destroy>', cleanup)
    def close():
        if menu.winfo_exists(): menu.destroy()
    def invoke(callback):
        if selected[0]: return 'break'
        selected[0] = True
        close()
        root.after_idle(callback)
        return 'break'
    def cancel(_=None):
        close()
        if prior_focus and prior_focus.winfo_exists(): prior_focus.focus_set()
        return 'break'
    canvas = tk.Canvas(menu, bg=custom.get('background') or _palette['panel'], highlightthickness=0)
    look = None
    if custom:
        from .app_menus import _look
        look = _look(kind)
    menu._scroll_target = canvas
    canvas.pack(fill='both', expand=True, padx=1, pady=1)
    body = ttk.Frame(canvas, padding=int(custom.get('padding') or 3), style=look['frame'] if look else 'TFrame')
    item = canvas.create_window(0, 0, window=body, anchor='nw')
    body._scroll_target = canvas
    body.bind('<Configure>', lambda _:content_scrollregion(canvas,item))
    canvas.bind('<Configure>', lambda e:content_width(canvas,item,e.width))
    for entry in entries:
        if entry is None:
            ttk.Separator(body).pack(fill='x', pady=3); continue
        label, callback = entry[:2]
        enabled = entry[2] if len(entry) > 2 else True
        if hasattr(label,'build_menu'):
            button=label.build_menu(body,lambda fn=callback:invoke(fn),enabled)
        else:
            button = ttk.Button(body, text=label, command=lambda fn=callback:invoke(fn), state='normal' if enabled else 'disabled', takefocus=enabled,
                                style=look['button'] if look else 'TButton')
        button.pack(fill='x')
        if enabled: buttons.append(button)
    def move(step):
        current = menu.focus_get()
        if buttons:
            index = buttons.index(current) if current in buttons else -1
            button=buttons[(index + step) % len(buttons)]
            button.focus_set()
            canvas.yview_moveto(button.winfo_y()/max(1,body.winfo_reqheight()))
        return 'break'
    menu.bind('<Down>', lambda _:move(1))
    menu.bind('<Up>', lambda _:move(-1))
    menu.bind('<Escape>', cancel)
    menu.bind('<FocusOut>', lambda _:root.after_idle(lambda:close() if menu.winfo_exists() and menu.focus_displayof() is None else None))
    menu.bind('<Return>', lambda _:event_action(menu, menu.focus_get().invoke) if menu.focus_get() in buttons else 'break')
    menu.bind('<Button-3>', cancel)
    def outside(e):
        if e.widget.winfo_toplevel() is not menu: close()
    def install_outside():
        if not menu.winfo_exists(): return
        for target in {root, owner}:
            for sequence in ('<ButtonPress-1>', '<ButtonPress-3>', '<Unmap>'):
                subscriptions.append((target, sequence, target.bind(sequence, outside, add='+')))
    menu.update_idletasks()
    if event: x,y=event.x_root,event.y_root
    elif anchor: x,y=anchor.winfo_rootx(),anchor.winfo_rooty()+anchor.winfo_height()
    else: x,y=owner.winfo_pointerxy()
    width=min(int(custom.get('max_width') or 520),body.winfo_reqwidth()+2,menu.winfo_screenwidth()-24)
    height=min(int(custom.get('max_height') or 520),body.winfo_reqheight()+2,menu.winfo_screenheight()-80)
    canvas.configure(width=width,height=height,scrollregion=canvas.bbox(item))
    if body.winfo_reqheight()>height:
        bar=ttk.Scrollbar(menu,command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side='right',fill='y',before=canvas)
    x=max(0,min(x,menu.winfo_screenwidth()-width))
    y=max(0,min(y,menu.winfo_screenheight()-height))
    menu.geometry(f'{width}x{height}+{x}+{y}')
    menu.deiconify()
    menu.lift()
    if buttons: buttons[0].focus_set()
    root.after_idle(install_outside)
    return menu



def scrollable(parent):
    from .themes import _palette
    canvas = tk.Canvas(parent, bg=_palette['bg'], highlightthickness=0)
    parent._scroll_target = canvas
    scrollbar = ttk.Scrollbar(parent, command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side='right', fill='y')
    canvas.pack(fill='both', expand=True)
    frame = ttk.Frame(canvas)
    item = canvas.create_window((0, 0), window=frame, anchor='nw')
    frame.bind('<Configure>', lambda _:content_scrollregion(canvas,item))
    def resize(event):
        content_width(canvas,item,event.width)
        from .scrolling import wrap_labels
        wrap_labels(frame,max(80,event.width-24))
    canvas.bind('<Configure>',resize)
    frame._scroll_target = canvas
    return frame


def popover(parent,title,anchor=None,size=(370,420)):
    """Small dismissible palette; never grabs the entire application."""
    context=getattr(parent._root(),'_context_menu',None)
    if context: context.destroy()
    previous=getattr(parent,'_popover',None)
    if previous and previous.winfo_exists(): previous.destroy()
    top=tk.Toplevel(parent); top.transient(parent); top.overrideredirect(True)
    parent._popover=top
    from .themes import _palette,apply_widget
    top.configure(bg=_palette['line'])
    width=min(size[0],parent.winfo_screenwidth()-24)
    height=min(size[1],max(240,parent.winfo_height()-40))
    x=anchor.winfo_rootx() if anchor else parent.winfo_pointerx()
    y=anchor.winfo_rooty()+anchor.winfo_height() if anchor else parent.winfo_pointery()
    x=max(12,min(x,parent.winfo_screenwidth()-width-12))
    y=max(12,min(y,parent.winfo_screenheight()-height-40))
    top.geometry(f'{width}x{height}+{x}+{y}')
    body=ttk.Frame(top,padding=8,style='Surface.TFrame'); body.pack(fill='both',expand=True,padx=1,pady=1)
    header=ttk.Frame(body);header.pack(fill='x')
    ttk.Label(header,text=title).pack(side='left')
    ttk.Button(header,text='×',width=3,command=top.destroy).pack(side='right')
    frame=ttk.Frame(body); frame.pack(fill='both',expand=True)
    outside=parent.bind('<ButtonPress-1>',lambda _:top.destroy() if top.winfo_exists() else None,add='+')
    def cleanup(event):
        if event.widget is not top: return
        if getattr(parent,'_popover',None) is top: parent._popover=None
        try: parent.unbind('<ButtonPress-1>',outside)
        except tk.TclError: pass
    top.bind('<Destroy>',cleanup)
    top.bind('<Escape>',lambda _:top.destroy())
    top._root().after_idle(lambda:apply_widget(top) if top.winfo_exists() else None)
    top.focus_set()
    return top,frame
