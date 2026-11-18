"""Responsive, peer-scoped contact cards with lazy shared-media pages."""
from .advanced_features import profile_feature_enabled
import asyncio
import tkinter as tk
from tkinter import ttk
from .app_dialogs import Choice,scrollable
from .appearance import app_palette
from .i18n import tr
from .shared_media import MediaPages,SharedPhotoGrid
from .scrolling import FlowFrame
from .ui_work import FrameJob

SECTIONS={'info':'Informacion','photos':'Photos','files':'Files','audio':'Audio','voice':'Voice messages','links':'Links',
          'gifs':'GIF', 'polls':'Encuestas', 'posts':'Publicaciones', 'gifts':'Regalos',
          'profile_music':'Música del perfil', 'similar':'Canales similares','settings':'Ajustes'}
PROFILE_TABS = ('posts', 'gifts', 'profile_music', 'similar')


def copyable_field(parent,label,value,app,valid=lambda:True):
    """Read-only text remains keyboard-selectable; Copy preserves the exact value."""
    if value is None or value=='':return
    value=str(value)
    row=ttk.Frame(parent);row.pack(fill='x',pady=7)
    heading=ttk.Frame(row);heading.pack(fill='x')
    ttk.Label(heading,text=tr(label),style='Muted.TLabel').pack(side='left')
    def copy():
        if valid():app.root.clipboard_clear();app.root.clipboard_append(value)
    ttk.Button(heading,text=tr('Copy'),command=copy,width=6).pack(side='right')
    if '\n' in value or len(value)>90:
        colors=app_palette(app.preferences.values)
        entry=tk.Text(row,height=min(6,max(2,len(value)//65+value.count('\n')+1)),wrap='word',borderwidth=0,
                      highlightthickness=0,bg=colors['panel'],fg=colors['text'],font=(app.font_family,app.preferences.values['font_size']),takefocus=True)
        entry.insert('1.0',value);entry.configure(state='disabled')
    else:
        entry=ttk.Entry(row);entry.insert(0,value);entry.configure(state='readonly')
    entry.pack(fill='x',pady=(3,0))
    return row


def normalized_profile(profile):
    result=dict(kind='user',is_user=True,is_self=False,usernames=[],name='',username='',phone='',about='',activity='',first_name='',last_name='')
    result.update(profile)
    if not result['usernames'] and result['username']:result['usernames']=[result['username']]
    if result.get('bot'):result['kind']='bot'
    if result.get('is_secret'):result['kind']='secret'
    return result


def profile_subtitle(profile):
    if profile.get('is_secret'):return '🔒 '+tr('Cifrado de extremo a extremo')
    if profile.get('deleted'):return tr('Deleted account')
    if profile['kind']=='bot':return tr('Bot')
    if profile.get('is_user'):return profile.get('activity','')
    label='Subscribers' if profile['kind']=='channel' else 'Members'
    count=profile.get('members_count')
    value=(f'{count:,} '+tr(label)) if count is not None else tr('Channel' if profile['kind']=='channel' else 'Group')
    if profile['kind']=='group' and profile.get('online_count'):value+=' · '+str(profile['online_count'])+' '+tr('Online')
    return value


def prepare_avatar(path,size,rounded):
    from PIL import Image,ImageOps,ImageDraw
    with Image.open(path) as source:
        if source.width*source.height>30_000_000:raise ValueError(tr('Image is too large'))
        oriented=ImageOps.exif_transpose(source)
        try:image=ImageOps.fit(oriented,(size,size),method=Image.Resampling.LANCZOS).convert('RGBA')
        finally:oriented.close()
    if rounded:
        mask=Image.new('L',(size*4,size*4))
        try:
            ImageDraw.Draw(mask).ellipse((0,0,size*4-1,size*4-1),fill=255)
            smaller=mask.resize((size,size),Image.Resampling.LANCZOS)
            try:image.putalpha(smaller)
            finally:smaller.close()
        finally:mask.close()
    return image


class ProfileRequests:
    """Owned reads cancel on refresh/close and never toggle the app-wide busy flag."""
    def __init__(self,app,window,account,backend):
        self.app,self.window,self.account,self.backend=app,window,account,backend
        self.jobs={};self.generation=0;self.closed=False
    def valid(self):
        return not self.closed and self.account==self.app.ui_account and self.backend is self.app.service.backend and bool(self.window.winfo_exists())
    def reset(self):
        self.generation+=1
        for future in self.jobs.values():future.cancel()
        self.jobs.clear()
        if hasattr(self,'tokens'):self.tokens.clear()
    def close(self):self.closed=True;self.reset()
    def submit(self,key,operation,done,failed=lambda _:None,timeout=30):
        if not self.valid():operation.close();return
        previous=self.jobs.pop(key,None)
        if previous is not None:previous.cancel()
        epoch=self.generation;token=object()
        # Tokens, rather than just keys, also reject a replaced request in one generation.
        tokens=getattr(self,'tokens',None)
        if tokens is None:tokens=self.tokens={}
        tokens[key]=token
        def current():return self.valid() and epoch==self.generation and tokens.get(key) is token
        def loaded(result):
            if not current():
                from .image_tools import close_images
                close_images(result);return
            self.jobs.pop(key,None);tokens.pop(key,None);done(result)
        def error(exc):
            if current():self.jobs.pop(key,None);tokens.pop(key,None);failed(exc)
        started=[False]
        async def bounded():
            started[0]=True
            return await asyncio.wait_for(operation,timeout)
        future=self.app.worker.submit(bounded(),loaded,error)
        if future is not None:
            self.jobs[key]=future
            future.add_done_callback(lambda _:operation.close() if not started[0] else None)


class ContactProfile:
    def __init__(self,app,peer,standalone=False):
        # standalone (1.4): opened from the contact list; several cards may be
        # open at once and they do not follow the active chat.
        self.standalone=standalone
        self.app,self.peer=app,peer;self.account=app.ui_account;self.backend=app.service.backend
        self.origin_chat=app.active;self.profile=None;self.images=[];self.widgets={};self.media_status={};self.media_more={}
        from .contact_appearance import card_style
        self.style=card_style(app.preferences.values)
        self.window,self.outer=app.dialog('Informacion',f"{self.style.get('width',620)}x740",unique=not standalone)
        self.requests=ProfileRequests(app,self.window,self.account,self.backend)
        self.window._contact_profile=self
        self.window.bind('<Destroy>',self.closed,add='+')
        self.content=ttk.Frame(self.outer);self.content.pack(fill='both',expand=True)
        self.refresh()
    def valid(self):return self.requests.valid()
    def closed(self,event):
        if event.widget is not self.window:return
        self.requests.close()
        if hasattr(self,'repaint'):self.repaint.cancel()
        self.images.clear();self.avatar=None;self.pattern=None;self.profile=None
        self.widgets.clear();self.media_status.clear();self.media_more.clear()
        if hasattr(self,'media'):self.media.rows.clear();self.media.pending.clear()
        if hasattr(self,'art_cache'):self.art_cache.clear()
    def refresh(self):
        if not self.valid():return
        from .contact_appearance import card_style
        self.style=card_style(self.app.preferences.values);self.origin_chat=self.app.active
        self.requests.reset()
        if hasattr(self,'repaint'):self.repaint.cancel()
        for child in self.content.winfo_children():child.destroy()
        self.images.clear();self.widgets.clear();self.media_status.clear();self.media_more.clear()
        self.profile=None;self.art_cache={}
        ttk.Label(self.content,text=tr('Loading...'),style='Title.TLabel').pack(pady=24)
        def failed(error):
            for child in self.content.winfo_children():child.destroy()
            ttk.Label(self.content,text=str(error),wraplength=440).pack(fill='x',pady=12)
            ttk.Button(self.content,text=tr('Actualizar'),command=self.refresh).pack()
        def loaded(profile):
            if not self.standalone and self.origin_chat!=self.app.active:self.window.destroy();return
            self.profile=normalized_profile(profile)
            if profile.get('entity') is not None:
                from .telegram_actions import peer_activity
                self.profile['activity']=peer_activity(profile['entity'],self.app.preferences.values.get('show_seconds',False))
            self.build()
        self.requests.submit('profile',self.backend.profile(self.peer),loaded,failed)
    def restyle(self):
        if not self.valid():return
        if self.profile is None:return self.refresh()
        from .contact_appearance import card_style
        self.style=card_style(self.app.preferences.values)
        self.requests.reset();self.repaint.cancel()
        self.images.clear();self.widgets.clear();self.media_status.clear();self.media_more.clear()
        self.build()
    def build(self):
        for child in self.content.winfo_children():child.destroy()
        app=self.app;profile=self.profile;values=app.preferences.values
        from .contact_appearance import ordered_sections,ordered_actions
        self.colors=app_palette(values)
        for option,target in [('background','panel'),('text','text'),('accent','selected')]:
            if self.style.get(option):self.colors[target]=self.style[option]
        self.banner_colors=None;self.avatar=None;self.pattern=None;self.avatar_path=None;self.avatar_remote=False
        self.padding=self.style.get('padding',16);self.avatar_size=self.style.get('avatar_size',96)
        self.banner=tk.Canvas(self.content,height=self.avatar_size+2*self.padding,
                              highlightthickness=self.style.get('border_width',0),
                              highlightbackground=self.style.get('border_color') or self.colors['muted'],bg=self.colors['panel'])
        self.banner._local_appearance={
            'background':self.colors['panel'],'highlightthickness':self.style.get('border_width',0),
            'highlightbackground':self.style.get('border_color') or self.colors['muted'],
            'highlightcolor':self.style.get('border_color') or self.colors['muted']}
        self.banner.pack(fill='x')
        self.reacts=ttk.Frame(self.content);self.reacts.pack(fill='x',padx=self.padding,pady=(0,8))
        self.status_label=ttk.Label(self.reacts);self.status_label.pack(side='left')
        badges=[tr(label) for key,label in [('premium','Premium'),('verified','Verified'),('scam','Scam'),('fake','Fake'),('blocked','Block')] if profile.get(key)]
        ttk.Label(self.reacts,text=' · '.join(badges),style='Muted.TLabel').pack(side='left',padx=6)
        self.rebuild_header()
        actions=FlowFrame(self.content);actions.pack(fill='x',padx=self.padding,pady=(0,8))
        self.notebook=ttk.Notebook(self.content);self.notebook.pack(fill='both',expand=True)
        self.pages={};available=list(SECTIONS)
        from .advanced_features import feature_enabled
        gated={'polls':'polls','posts':'stories','gifts':'stars_gifts','links':'links'}
        available=[key for key in available if key not in gated or feature_enabled(app,gated[key])]
        if profile['kind']!='channel':available.remove('similar')
        if not profile.get('is_user'):available.remove('profile_music')
        if app.demo:available=[key for key in available if key!='settings']
        self.order=ordered_sections(values,available)
        for kind in self.order:
            if kind=='settings':continue  # Existing permission-aware management creates this tab.
            page=ttk.Frame(self.notebook);self.pages[kind]=page;self.notebook.add(page,text=tr(SECTIONS[kind]))
        information=scrollable(self.pages['info']) if 'info' in self.pages else None
        if information is not None:
            copyable_field(information,{'user':'Contact','bot':'Bot','group':'Group','channel':'Channel','secret':'Chat secreto'}.get(profile['kind'],'Contact'),profile['name'],app,self.valid)
            if profile.get('is_secret') and isinstance(profile.get('secret'),dict):
                sec=profile['secret']
                copyable_field(information,'Clave de cifrado (emojis)',sec.get('emojis',''),app,self.valid)
                copyable_field(information,'Huella SHA-256 / SHA-1',sec.get('hex',''),app,self.valid)
                copyable_field(information,'Autodestrucción (TTL)',sec.get('ttl_label',''),app,self.valid)
                copyable_field(information,'Capa MTProto 2.0',f"Layer {sec.get('layer', 144)}",app,self.valid)
            for name in profile['usernames']:copyable_field(information,'Nombre de usuario','@'+name,app,self.valid)
            if profile.get('is_user') and profile.get('id') is not None:
                copyable_field(information,'Telegram ID',str(profile['id']),app,self.valid)
            copyable_field(information,'Telefono internacional','+'+profile['phone'].lstrip('+') if profile['phone'] else '',app,self.valid)
            copyable_field(information,'Biografia' if profile['is_user'] else 'Description',profile['about'],app,self.valid)
            birthday=profile.get('birthday')
            if birthday:
                value=f'{birthday.day:02d}/{birthday.month:02d}'+(f'/{birthday.year}' if birthday.year else '')
                copyable_field(information,'Birthday',value,app,self.valid)
        if not app.demo:
            details=information if information is not None else ttk.Frame(self.content)
            before=set(self.notebook.tabs())
            app.extend_profile(self.window,self.notebook,details,profile,self.backend,self.account,summary=False)
            added=[tab for tab in self.notebook.tabs() if tab not in before]
            if added:self.pages['settings']=self.notebook.nametowidget(added[0])
        # Keep the management tab reachable even if the custom order omitted it.
        self.order=[key for key in self.order if key in self.pages]+[key for key in self.pages if key not in self.order]
        for index,kind in enumerate(self.order):self.notebook.insert(index,self.pages[kind])
        callbacks={'message':self.open_chat,'refresh':self.refresh,'manage':lambda:self.select('settings')}
        from .desktop_calls import call_allowed
        if call_allowed(app, self.peer, self.account):
            callbacks['call'] = lambda:app.start_call(self.peer, account=self.account)
        if call_allowed(app, self.peer, self.account, video=True):
            callbacks['video_call'] = lambda:app.start_call(self.peer, account=self.account, video=True)
        if profile.get('is_secret'):
            callbacks['secret_settings'] = lambda:app.secret_chat_dialog(self.peer)
        elif profile.get('is_user') and not profile.get('is_self') and not profile.get('bot'):
            callbacks['secret_chat'] = lambda:(self.window.destroy(),app.start_secret_chat(self.peer))
        if not app.demo:
            callbacks.update(notifications=lambda:app.profile_notifications(self.peer,self.backend,self.account),
                             add_username=lambda:app.add_username_contact(self.window))
            if profile['is_user'] and not profile.get('is_self'):callbacks['edit_contact']=lambda:app.edit_contact(profile,self.backend,self.window)
            if profile['is_user'] and profile.get('entity') is not None:
                from .contact_tools import share_contacts_dialog
                callbacks['share']=lambda:share_contacts_dialog(app,[profile['entity']])
            if profile['kind'] in ('group','channel'):
                from .chat_capabilities import capabilities_for
                caps=capabilities_for(entity=profile.get('entity'))
                if caps.can_join or caps.can_leave:
                    callbacks['membership']=lambda:app.membership_action(self.peer,leave=caps.can_leave,profile=profile)
            if profile.get('is_self'):
                from .profile_customization import open_profile_customization
                callbacks['edit_self']=app.edit_profile
                callbacks['profile_design']=lambda:open_profile_customization(app)
        labels={'message':'Abrir chat','notifications':'Notifications','edit_contact':'Edit contact','add_username':'Add by username','refresh':'Actualizar','manage':'Ajustes'}
        labels.update(call='Call', video_call='Video call', share='Share contact',
                      secret_chat='Iniciar chat secreto', secret_settings='Clave de cifrado y autodestrucción')
        labels.update(membership='Salir del grupo o canal' if profile.get('member') else 'Unirse',edit_self='Editar mi perfil',profile_design='Diseño del perfil')
        if 'settings' not in self.pages:callbacks.pop('manage',None)
        self.action_widgets={}
        action_order=ordered_actions(values,list(callbacks))
        for extra in ('secret_chat','secret_settings'):
            if extra in callbacks and extra not in action_order:action_order.append(extra)
        for kind in action_order:
            button=ttk.Button(actions,text=tr(labels[kind]),command=lambda key=kind:self.action(
                callbacks[key],key in ('message','notifications','edit_contact','add_username','secret_chat')))
            button.pack(side='left',padx=3,pady=3);self.action_widgets[kind]=button
        self.selector=Choice(self.content,values=[tr(SECTIONS[key]) for key in self.order])
        if self.order:self.selector.current(0)
        self.selector.bind('<<ComboboxSelected>>',lambda _:self.select(self.order[self.selector.current()]))
        self.extra_panes={}
        self.media=MediaPages([key for key in self.order if key not in ('info','settings',*PROFILE_TABS)])
        self.notebook.bind('<<NotebookTabChanged>>',self.changed)
        self.notebook.bind('<Configure>',self.resize)
        self.compact=None
        from .contact_settings import open_contact_settings
        self.design_button=ttk.Button(actions,text=tr('Apariencia'),command=lambda:self.action(
            lambda:open_contact_settings(app,on_saved=self.restyle)))
        self.design_button.pack(side='left',padx=3,pady=3)
        self.load_art()
        from .profile_customization import PROFILE_TABS as native_tabs
        selected=next((key for key,cls in native_tabs.items() if isinstance(profile.get('main_tab'),cls)),None)
        selected={'media':'photos','music':'profile_music'}.get(selected,selected)
        if selected in self.pages:self.notebook.select(self.pages[selected])
        self.window.after_idle(self.changed)
    def action(self,callback,requires_idle=False):
        if self.valid() and (not requires_idle or not self.app.busy):callback()
    def select(self,kind):
        if self.valid() and kind in self.pages:self.notebook.select(self.pages[kind])
    def selected(self):
        tab=self.notebook.select();return next((key for key,page in self.pages.items() if str(page)==tab),'info')
    def resize(self,event):
        compact=event.width<620
        if compact==self.compact:return
        self.compact=compact
        ttk.Style(self.notebook).layout('ProfileHidden.TNotebook.Tab',[])
        self.notebook.configure(style='ProfileHidden.TNotebook' if compact else 'TNotebook')
        if compact and self.order:self.selector.pack(fill='x',before=self.notebook,padx=self.padding,pady=4)
        else:self.selector.pack_forget()
    def rebuild_header(self):
        self.repaint=FrameJob(self.banner,self.paint_header)
        self.banner.bind('<Configure>',self.repaint.request)
        self.banner.bind('<ButtonRelease-1>',self.avatar_click)
        self.repaint.request()
    def paint_header(self):
        canvas=self.banner;canvas.delete('all');width=max(1,canvas.winfo_width());pad=self.padding;size=self.avatar_size
        center=self.style.get('alignment','left')=='center' or width<size+240
        height=size+2*pad+(85 if center else 0)
        if self.banner_colors:
            first,last=self.banner_colors[0],self.banner_colors[-1]
            for index in range(48):
                ratio=index/47;rgb=[round(((first>>shift)&255)*(1-ratio)+((last>>shift)&255)*ratio) for shift in (16,8,0)]
                canvas.create_rectangle(index*width/48,0,(index+1)*width/48+1,height,fill='#%02x%02x%02x'%tuple(rgb),outline='',tags='gradient')
        if self.pattern:
            for x in range(24,width,54):
                for y in range(20,height,50):canvas.create_image(x,y,image=self.pattern)
        x=width/2 if center else pad+size/2;y=pad+size/2
        self.avatar_bounds=(x-size/2,y-size/2,x+size/2,y+size/2)
        if self.avatar:canvas.create_image(x,y,image=self.avatar)
        else:
            shape=canvas.create_oval if self.style.get('round_avatar',True) else canvas.create_rectangle
            shape(x-size/2,y-size/2,x+size/2,y+size/2,fill=self.colors['selected'],outline='')
            initials=''.join(word[0] for word in self.profile['name'].split()[:2]).upper() or '?'
            canvas.create_text(x,y,text=initials,font=(self.app.font_family,max(18,size//3),'bold'),fill=self.colors['text'])
        anchor='n' if center else 'nw';tx=width/2 if center else pad*2+size;ty=pad+size+10 if center else pad+12
        text_width=width-pad*2 if center else max(80,width-tx-pad)
        ink=self.colors['text']
        if self.banner_colors and not self.style.get('text'):
            rgb=[sum((color>>shift)&255 for color in self.banner_colors)/len(self.banner_colors) for shift in (16,8,0)]
            ink='#101820' if .2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2]>150 else '#ffffff'
        name=canvas.create_text(tx,ty,text=self.app.text_display(self.profile['name']),width=text_width,anchor=anchor,
                           fill=ink,font=(self.app.font_family,self.app.preferences.values['font_size']+5,'bold'))
        status=canvas.create_text(tx,canvas.bbox(name)[3]+7,text=profile_subtitle(self.profile),width=text_width,anchor=anchor,
                           fill=ink if self.banner_colors else self.colors['muted'],font=(self.app.font_family,self.app.preferences.values['font_size']))
        needed=max(height,canvas.bbox(status)[3]+pad)
        if int(float(canvas.cget('height')))!=needed:canvas.configure(height=needed)
        if needed!=height:
            for item in canvas.find_withtag('gradient'):
                a,b,c,d=canvas.coords(item);canvas.coords(item,a,b,c,needed)
    def avatar_click(self,event):
        a,b,c,d=self.avatar_bounds
        if not self.valid() or not (a<=event.x<=c and b<=event.y<=d):return
        if not self.avatar_path and not self.profile.get('photo_id'):return
        if self.avatar_path and not self.avatar_remote:
            self.app.full_profile_photo(self.avatar_path,self.profile['name']);return
        from .media_gallery import open_profile_gallery
        gallery=getattr(self,'avatar_gallery',None)
        if gallery is not None and getattr(self,'avatar_gallery_photo',None)==self.profile.get('photo_id') and gallery.window.winfo_exists() and gallery.valid():
            gallery.window.lift();return
        self.avatar_gallery=open_profile_gallery(self.app,self.peer,self.profile,path=self.avatar_path)
        self.avatar_gallery_photo=self.profile.get('photo_id')
    def load_art(self):
        if self.app.demo:return
        epoch=self.requests.generation;profile=self.profile
        def valid():return self.valid() and epoch==self.requests.generation
        async def avatar():
            from .profile_customization import local_photo
            path=self.art_cache.get('avatar') or local_photo(self.backend,self.peer)
            remote=self.art_cache.get('avatar_remote',False)
            if path is None:
                revision=profile.get('photo_id') or 'current'
                remote=True
                path=self.app.preview_dir/f'{self.account}-profile-{self.peer}-{revision}-thumb.jpg'
                if profile.get('full_photo_known'):
                    photo=profile.get('display_photo')
                    if photo is None:return None
                    from .profile_media import prepare_profile_photo
                    path=await prepare_profile_photo(self.app,self.backend,self.account,self.peer,photo,thumbnail=True)
                else:path=await self.backend.profile_photo(self.peer,path)
            if not path:return None
            return path,await asyncio.to_thread(prepare_avatar,path,self.avatar_size,self.style.get('round_avatar',True)),remote
        def avatar_ready(result):
            if result is None:return
            from PIL import ImageTk
            path,image,self.avatar_remote=result
            try:self.avatar=ImageTk.PhotoImage(image,master=self.window)
            finally:image.close()
            self.avatar_path=path;self.images.append(self.avatar);self.repaint.request()
            self.art_cache['avatar']=path;self.art_cache['avatar_remote']=self.avatar_remote
        self.requests.submit('avatar',avatar(),avatar_ready)
        color=profile.get('profile_color')
        if color:
            from .themes import resolve_theme
            def palette(colors):self.banner_colors=colors;self.art_cache['palette']=colors;self.repaint.request()
            if 'palette' in self.art_cache:palette(self.art_cache['palette'])
            else:self.requests.submit('palette',self.backend.profile_palette(color.color,resolve_theme(self.app.preferences.values['theme'])=='dark'),palette)
            pattern=getattr(color,'background_emoji_id',None)
            if pattern:
                def ready(path):
                    if path and valid():
                        self.art_cache['pattern']=path
                        def painted(photo):self.pattern=photo;self.images.append(photo);self.repaint.request()
                        self.app.request_photo(path,(24,24),painted,owner=self.banner,valid=valid,enabled=False)
                if 'pattern' in self.art_cache:ready(self.art_cache['pattern'])
                else:self.app.emoji_art(pattern,self.account,self.backend,ready,valid=valid)
        status=profile.get('emoji_status');document=getattr(status,'document_id',None)
        if document:
            self.status_label.configure(cursor='hand2',takefocus=True,text='◇')
            def pack(event=None):
                if valid() and not self.app.busy:self.app.show_document_pack(document)
                return 'break'
            self.status_label.bind('<Button-1>',pack)
            self.status_label.bind('<Return>',pack)
            self.status_label.bind('<space>',pack)
            def ready(path):
                if path and valid():
                    self.art_cache['status']=path
                    def painted(photo):self.status_label.configure(image=photo);self.images.append(photo)
                    self.app.request_photo(path,(24,24),painted,owner=self.status_label,valid=valid)
            if 'status' in self.art_cache:ready(self.art_cache['status'])
            else:self.app.emoji_art(document,self.account,self.backend,ready,valid=valid)
    def open_chat(self):
        def loaded(chat):
            if not self.app.busy:self.window.destroy();self.app.open_resolved(chat)
        self.requests.submit('open',self.backend.resolve_chat(self.peer),loaded,self.app.show_error)
    def changed(self,event=None):
        if not self.valid() or not self.order:return
        kind=self.selected()
        if not profile_feature_enabled(self.app,kind):return
        self.selector.current(self.order.index(kind))
        if kind in PROFILE_TABS:
            if kind not in self.extra_panes:
                from .profile_tabs import ProfileTabPane
                self.extra_panes[kind]=ProfileTabPane(self,kind)
            if not self.extra_panes[kind].loaded:self.extra_panes[kind].fetch()
            return
        if kind not in self.media.rows:return
        if kind not in self.widgets:self.build_media(kind)
        if kind not in self.media.queries and kind not in self.media.pending:self.fetch_media(kind)
    def build_media(self,kind):
        page=self.pages[kind];controls=FlowFrame(page);controls.pack(side='bottom',fill='x',pady=6)
        status=ttk.Label(page,text=tr('Loading...'),style='Muted.TLabel');status.pack(side='bottom',fill='x',padx=8);self.media_status[kind]=status
        if kind=='photos':
            widget=SharedPhotoGrid(page,self.app,self.account,self.backend,self.peer,lambda message:self.app.open_image_message(message,self.peer) if self.valid() and not self.app.busy else None)
            widget.pack(fill='both',expand=True)
        else:
            widget=tk.Listbox(page,exportselection=False,activestyle='dotbox');widget.pack(side='left',fill='both',expand=True)
            bar=ttk.Scrollbar(page,command=widget.yview);bar.pack(side='right',fill='y');widget.configure(yscrollcommand=bar.set)
            widget.bind('<Double-Button-1>',lambda _:self.open_media(kind));widget.bind('<Return>',lambda _:self.open_media(kind))
            ttk.Button(controls,text=tr('Open'),command=lambda:self.open_media(kind)).pack(side='left')
            ttk.Button(controls,text=tr('Go to message'),command=lambda:self.open_media(kind,True)).pack(side='left')
        self.widgets[kind]=widget
        self.media_more[kind]=ttk.Button(controls,text=tr('More'),command=lambda:self.fetch_media(kind,True));self.media_more[kind].pack(side='left')
        ttk.Button(controls,text=tr('Actualizar'),command=lambda:self.fetch_media(kind)).pack(side='right')
    def fetch_media(self,kind,more=False):
        if not self.valid() or not profile_feature_enabled(self.app,kind):return
        request=self.media.begin(kind,'',more)
        if request is None:return
        ticket,offset=request;self.media_status[kind].configure(text=tr('Loading...'));self.media_more[kind].configure(state='disabled')
        def loaded(items):
            if not profile_feature_enabled(self.app,kind):self.media.fail(ticket);return
            if not self.media.finish(ticket,items):return
            rows=self.media.rows[kind];widget=self.widgets[kind]
            if kind=='photos':widget.set_messages(rows)
            else:
                widget.delete(0,'end')
                for item in rows:widget.insert('end',self.app.text_display(item.filename or item.text[:160],True))
            self.media_status[kind].configure(text=str(len(rows)) if rows else tr('No results.'))
            self.media_more[kind].configure(state='normal' if self.media.more[kind] else 'disabled')
        def failed(error):
            if self.media.fail(ticket):
                self.media_status[kind].configure(text=tr('Search failed.')+' '+str(error));self.media_more[kind].configure(state='normal')
        self.requests.submit('media:'+kind,self.backend.search_messages(self.peer,'',kind,offset),loaded,failed)
    def open_media(self,kind,jump=False):
        if not self.valid() or not profile_feature_enabled(self.app,kind) or self.app.busy:return
        selected=self.widgets[kind].curselection()
        if not selected:return
        message=self.media.rows[kind][selected[0]]
        if jump or not message.media:self.app.jump_message(message.id,self.peer)
        else:self.app.view_message_media(message,self.peer)
