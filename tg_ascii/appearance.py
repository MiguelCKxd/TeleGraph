"""Local appearance choices, independent of Telegram peer colours and app logos."""
import math
from PIL import Image,ImageDraw,ImageTk


def blend(a,b,weight):
    return '#'+''.join(f'{round(int(a[i:i+2],16)*(1-weight)+int(b[i:i+2],16)*weight):02x}' for i in (1,3,5))


def app_palette(values):
    from .themes import palette,resolve_theme
    result=palette(resolve_theme(values.get('theme','dark'))).copy()
    foreground=values.get('text_color','');background=values.get('background_color','')
    if foreground:result['text']=foreground
    if background:result['bg']=background
    if foreground or background:
        fg,bg=result['text'],result['bg']
        result.update(panel=blend(bg,fg,.05),selected=blend(bg,fg,.19),muted=blend(bg,fg,.70),line=blend(bg,fg,.30),strong=fg)
    if accent := values.get('accent_color'):
        result.update(strong=accent, selected=blend(result['bg'], accent, .35))
    return result


def rounded_points(x,y,width,height,radius):
    radius=max(0,min(radius,width/2,height/2))
    if not radius:return [x,y,x+width,y,x+width,y+height,x,y+height]
    points=[]
    for cx,cy,start in ((x+width-radius,y+radius,-90),(x+width-radius,y+height-radius,0),(x+radius,y+height-radius,90),(x+radius,y+radius,180)):
        for n in range(9):
            angle=math.radians(start+n*90/8);points.extend((cx+radius*math.cos(angle),cy+radius*math.sin(angle)))
    return points


def control_image(radius,fill,border,background,scale=3):
    # ttk tiles the centre instead of stretching it. A 2px centre turns a
    # large panel into hundreds of thousands of native image draws.
    size=2*(radius+3)+128
    image=Image.new('RGB',(size*scale,size*scale),background)
    draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((scale,scale,(size-1)*scale,(size-1)*scale),radius=radius*scale,fill=fill,outline=border,width=scale)
    return image.resize((size,size),Image.Resampling.LANCZOS)


def _surface_image(radius, fill, border, background, border_width=0,
                   shadow_size=0, shadow_color='#000000', narrow=False):
    """Stable nine-patch dimensions allow updating photos instead of elements.

    ttk has no element-delete API. A new element per colour/theme change leaked
    its Tcl definition indefinitely. Only the existing pixels now change.
    """
    from PIL import ImageFilter
    scale=3;slice_size=12 if narrow else 40
    size=2*slice_size+128
    radius=min(radius,5) if narrow else radius
    shadow_size=min(shadow_size,3) if narrow else shadow_size
    border_width=min(border_width,3) if narrow else border_width
    picture=Image.new('RGBA',(size*scale,size*scale),background)
    inset=scale;right=(size-shadow_size-1)*scale;bottom=right
    if shadow_size:
        layer=Image.new('RGBA',picture.size,(0,0,0,0));draw=ImageDraw.Draw(layer)
        delta=shadow_size*scale
        draw.rounded_rectangle((inset+delta,inset+delta,right+delta,bottom+delta),radius=radius*scale,fill=shadow_color)
        picture.alpha_composite(layer.filter(ImageFilter.GaussianBlur(shadow_size*scale/3)))
    draw=ImageDraw.Draw(picture)
    draw.rounded_rectangle((inset,inset,right,bottom),radius=radius*scale,fill=fill,
                           outline=border if border_width else None,width=max(1,border_width*scale))
    return picture.convert('RGB').resize((size,size),Image.Resampling.LANCZOS)


def configure_shapes(root,style,values,colors):
    """Swap drawing only: native ttk children, focus and bindings are preserved."""
    from .visual_effects import EFFECT_DEFAULTS
    if not hasattr(root,'_original_button_layout'):root._original_button_layout=style.layout('TButton')
    signature=tuple((key,values.get(key)) for key in ('button_radius','menu_radius',*EFFECT_DEFAULTS))+tuple(sorted(colors.items()))
    root._shape_values=dict(values)
    if getattr(root,'_shape_signature',None)==signature:
        configure_effect_padding(root,style,values)
        return
    root._shape_signature=signature
    if not hasattr(root,'_shape_photos'):
        root._shape_photos={};root._shape_elements=set();root._shape_art={}
    # Keep a bounded set alive while disabled: ttk retains these image names.
    root._shape_images=list(root._shape_photos.values())
    def enabled(group):
        return any(values.get(f'{group}_{suffix}',0) for suffix in ('radius','border_width','shadow_size'))
    def photo(group,fill_role='panel',state='normal',narrow=False):
        key=(group,fill_role,state,narrow);fill=colors[fill_role]
        border=values.get(f'{group}_border_color') or colors['line']
        if state in ('active','focus'):
            fill=colors['selected'] if state=='active' else fill
            border=values.get(f'{group}_border_color') or colors['text']
        elif state=='disabled':fill=colors['bg']
        args=(values.get(f'{group}_radius',0),fill,border,colors['bg'],
              values.get(f'{group}_border_width',0),values.get(f'{group}_shadow_size',0),
              values.get(f'{group}_shadow_color') or '#000000',narrow)
        if root._shape_art.get(key)!=args:
            picture=_surface_image(*args)
            if key in root._shape_photos:root._shape_photos[key].paste(picture)
            else:root._shape_photos[key]=ImageTk.PhotoImage(picture,master=root)
            root._shape_art[key]=args
        return root._shape_photos[key]
    def element(name,group,fill_role='panel',narrow=False,width=0,height=0):
        normal=photo(group,fill_role,narrow=narrow);active=photo(group,fill_role,'active',narrow)
        if name not in root._shape_elements:
            style.element_create(name,'image',normal,('focus',active),('pressed',active),('active',active),
                                 border=12 if narrow else 40,padding=0,sticky='nsew',width=width,height=height)
            root._shape_elements.add(name)
        return name
    root._shape_photo=photo;root._shape_element=element;root._shape_enabled=enabled
    if enabled('button'):
        name=element('Tgas.Button.border','button')
        style.layout('TButton',[(name,{'sticky':'nsew','children':[('Button.padding',{'sticky':'nsew','children':[('Button.label',{'sticky':'nsew'})]})]})])
    else:style.layout('TButton',root._original_button_layout)
    if not hasattr(root,'_original_frame_layout'):root._original_frame_layout=style.layout('TFrame')
    if enabled('menu'):
        name=element('Tgas.Surface.border','menu','bg');layout=[(name,{'sticky':'nsew'})]
        style.layout('Surface.TFrame',layout);style.layout('TFrame',layout)
    else:
        style.layout('TFrame',root._original_frame_layout);style.layout('Surface.TFrame',root._original_frame_layout)
    style.configure('Surface.TFrame',background=colors['bg'])
    configure_control_shapes(root,style,values,colors)
    configure_effect_padding(root,style,values)
    root._shape_images=list(root._shape_photos.values())


def configure_effect_padding(root,style,values):
    """Reserve real border/shadow space without using the image slice size.

    The 40px nine-patch slice controls painting, never minimum control size.
    This runs after the application's base style configuration.
    """
    groups={'TButton':'button','TMenubutton':'button','TNotebook.Tab':'button',
            'Treeview.Heading':'button','TEntry':'menu','TCombobox':'menu',
            'TSpinbox':'menu','TLabelframe':'menu'}
    if not hasattr(root,'_effect_original_padding'):root._effect_original_padding={}
    for name,group in groups.items():
        border=values.get(f'{group}_border_width',0)
        shadow=values.get(f'{group}_shadow_size',0)
        if not border and not shadow and name not in getattr(root,'_effect_padded',set()):continue
        if name not in root._effect_original_padding:
            value=style.lookup(name,'padding')
            try:
                pieces=tuple(int(item) for item in (value.split() if isinstance(value,str) else value))
            except (TypeError,ValueError):pieces=()
            if not pieces:pieces=(0,)
            if len(pieces)==1:pieces=pieces*4
            elif len(pieces)==2:pieces=pieces*2
            elif len(pieces)==3:pieces=(*pieces,pieces[1])
            root._effect_original_padding[name]=pieces
        original=root._effect_original_padding[name]
        if border or shadow:
            left,top,right,bottom=original
            style.configure(name,padding=(left+border,top+border,right+border+shadow,bottom+border+shadow))
        elif name in getattr(root,'_effect_padded',set()):style.configure(name,padding=original)
    root._effect_padded={name for name,group in groups.items()
                         if values.get(f'{group}_border_width',0) or values.get(f'{group}_shadow_size',0)}


def replace_elements(layout,replacements):
    result=[]
    for name,options in layout:
        options=dict(options)
        if 'children' in options:options['children']=replace_elements(options['children'],replacements)
        result.append((replacements.get(name,name),options))
    return result


def configure_control_shapes(root,style,values,colors):
    """Keep ttk's child elements and event bindings; only swap their drawing."""
    import tkinter as tk
    specs={
        'TEntry':('menu',('Entry.field',),'panel'),
        'TSpinbox':('menu',('Spinbox.field',),'panel'),
        'TCombobox':('menu',('Combobox.field',),'panel'),
        'Treeview':('menu',('Treeview.field',),'panel'),
        'TNotebook':('menu',('Notebook.client',),'bg'),
        'TNotebook.Tab':('button',('Notebook.tab',),'panel'),
        'TLabelframe':('menu',('Labelframe.border',),'bg'),
        'TMenubutton':('button',('Menubutton.border',),'panel'),
        'Treeview.Heading':('button',('Treeheading.border',),'panel'),
        'Horizontal.TProgressbar':('menu',('Horizontal.Progressbar.trough','Horizontal.Progressbar.pbar'),'panel'),
        'Vertical.TProgressbar':('menu',('Vertical.Progressbar.trough','Vertical.Progressbar.pbar'),'panel'),
        'Horizontal.TScrollbar':('button',('Horizontal.Scrollbar.thumb',),'line'),
        'Vertical.TScrollbar':('button',('Vertical.Scrollbar.thumb',),'line'),
        'Horizontal.TScale':('button',('Horizontal.Scale.slider',),'panel'),
        'Vertical.TScale':('button',('Vertical.Scale.slider',),'panel'),
    }
    if not hasattr(root,'_control_layouts'):root._control_layouts={}
    for name,(group,elements,fill_role) in specs.items():
        if name not in root._control_layouts:
            try:root._control_layouts[name]=style.layout(name)
            except tk.TclError:continue
        original=root._control_layouts[name]
        if not root._shape_enabled(group):style.layout(name,original);continue
        replacements={}
        for old in elements:
            narrow=any(part in old for part in ('Progressbar','Scrollbar','Scale'))
            actual='text' if old.endswith('.pbar') else fill_role;width=height=0
            if any(part in old for part in ('Scrollbar','Scale')):width=height=14
            elif 'Progressbar' in old:
                if old.startswith('Horizontal'):height=12
                else:width=12
            replacements[old]=root._shape_element(f'Tgas.{old}',group,actual,narrow,width,height)
        style.layout(name,replace_elements(original,replacements))
    for name,old in (('TCheckbutton','Checkbutton.indicator'),('TRadiobutton','Radiobutton.indicator')):
        if name not in root._control_layouts:
            try:root._control_layouts[name]=style.layout(name)
            except tk.TclError:continue
        original=root._control_layouts[name]
        if not root._shape_enabled('button'):style.layout(name,original);continue
        photos=[]
        for selected in (False,True):
            key=(name,selected)
            signature=(selected,values.get('button_radius',0),values.get('button_border_width',0),values.get('button_border_color'),tuple(sorted(colors.items())))
            if root._shape_art.get(key)!=signature:
                picture=Image.new('RGB',(48,48),colors['bg']);draw=ImageDraw.Draw(picture)
                radius=21 if name=='TRadiobutton' else min(values.get('button_radius',0),6)*3
                draw.rounded_rectangle((3,3,44,44),radius=radius,fill=colors['selected'] if selected else colors['panel'],
                    outline=values.get('button_border_color') or colors['text'],width=max(3,min(4,values.get('button_border_width',0))*3))
                if selected:
                    if name=='TRadiobutton':draw.ellipse((15,15,33,33),fill=colors['text'])
                    else:draw.line((12,25,21,34,37,14),fill=colors['text'],width=5)
                size=16 if name=='TCheckbutton' else 14
                picture=picture.resize((size,size),Image.Resampling.LANCZOS)
                if key in root._shape_photos:root._shape_photos[key].paste(picture)
                else:root._shape_photos[key]=ImageTk.PhotoImage(picture,master=root)
                root._shape_art[key]=signature
            photos.append(root._shape_photos[key])
        element=f'Tgas.{old}'
        if element not in root._shape_elements:
            size=16 if name=='TCheckbutton' else 14
            style.element_create(element,'image',photos[0],('selected',photos[1]),width=size,height=size)
            root._shape_elements.add(element)
        style.layout(name,replace_elements(original,{old:element}))

def corner_masks(radius,background):
    """Transparent inner corner, opaque parent background outside the curve."""
    radius=max(1,int(radius));scale=3
    square=Image.new('RGBA',(radius*scale*2,radius*scale*2),background)
    ImageDraw.Draw(square).ellipse((0,0,square.width-1,square.height-1),fill=(0,0,0,0))
    square=square.resize((radius*2,radius*2),Image.Resampling.LANCZOS)
    return [square.crop(box) for box in ((0,0,radius,radius),(radius,0,2*radius,radius),(0,radius,radius,2*radius),(radius,radius,2*radius,2*radius))]


def shape_widget(widget):
    """Round the app's classic Tk editing/list/canvas surfaces, never OS menus."""
    import tkinter as tk
    if not isinstance(widget,(tk.Text,tk.Listbox,tk.Canvas)):return
    root=widget._root();values=getattr(root,'_shape_values',{})
    border=values.get('menu_border_width',0)
    original=getattr(widget,'_effect_border_original',None)
    if border or original is not None:
        if original is None:
            original={key:widget.cget(key) for key in ('highlightthickness','highlightbackground','highlightcolor')}
            widget._effect_border_original=original
        if border:
            from .themes import _palette
            color=values.get('menu_border_color') or _palette['line']
            widget.configure(highlightthickness=border,highlightbackground=color,highlightcolor=color)
        else:widget.configure(**original)
    radius=values.get('menu_radius',0)
    if isinstance(widget,tk.Canvas):
        from .themes import _palette
        manager=getattr(widget,'_canvas_corners',None)
        if manager is None and radius:
            from .ui_work import CanvasCorners
            manager=widget._canvas_corners=CanvasCorners(widget)
        if manager is not None:manager.configure(radius,_palette['bg'])
        return
    binding=getattr(widget,'_corner_binding',None)
    if binding:widget.unbind('<Configure>',binding);widget._corner_binding=None
    if not radius:
        for child in getattr(widget,'_corner_labels',[]):child.destroy()
        widget._corner_labels=[];widget._corner_signature=None
        if isinstance(widget,tk.Canvas):widget.delete('_tgas_corners');widget._corner_images=[]
        if hasattr(widget,'_corner_padding'):widget.configure(**widget._corner_padding)
        return
    from .themes import _palette
    def draw(event=None):
        if not widget.winfo_exists():return
        r=min(radius,widget.winfo_width()//2,widget.winfo_height()//2)
        if r<1:return
        signature=(r,_palette['bg'])
        if getattr(widget,'_corner_signature',None)==signature:return
        widget._corner_signature=signature
        if not hasattr(widget,'_corner_padding'):
            keys=('padx','pady') if isinstance(widget,tk.Text) else ('borderwidth',)
            widget._corner_padding={key:widget.cget(key) for key in keys}
        widget.configure(**{key:max(int(float(value)),r) for key,value in widget._corner_padding.items()})
        for child in getattr(widget,'_corner_labels',[]):child.destroy()
        widget._corner_labels=[]
        for picture,(x,y,anchor) in zip(corner_masks(r,_palette['bg']),((0,0,'nw'),(1,0,'ne'),(0,1,'sw'),(1,1,'se'))):
            photo=ImageTk.PhotoImage(picture,master=widget)
            # Tiny corner covers do not resize the control or intercept its centre.
            label=tk.Label(widget,image=photo,bd=0,highlightthickness=0,bg=widget.cget('bg'))
            label._corner_overlay=True;label.image=photo
            label.place(relx=x,rely=y,anchor=anchor);widget._corner_labels.append(label)
    widget._corner_binding=widget.bind('<Configure>',draw,add='+')
    draw()
