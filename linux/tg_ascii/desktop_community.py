"""On-demand community editors; no membership polling or startup widgets."""
from . import APP_NAME
from datetime import datetime, timedelta, timezone
import tkinter as tk
from tkinter import ttk
from .app_dialogs import Choice, scrollable, messagebox, simpledialog
from .app_lock import is_locked, hide_locked_dialog
from .i18n import tr
from .desktop_profile import permission_enabled
from .profile_details import PERMISSIONS


class Panel:
    def __init__(self,app,title,size='560x590'):
        self.app=app;self.backend=app.service.backend;self.account=app.ui_account;self.pending=None
        self.window,self.outer=app.dialog(title,size)
        self.footer=ttk.Frame(self.outer);self.footer.pack(side='bottom',fill='x')
        self.body=scrollable(self.outer)
        self.status=ttk.Label(self.footer,wraplength=480);self.status.pack(fill='x',pady=4)
        def closed(event):
            if event.widget is self.window and self.pending is not None:self.pending.cancel()
        self.window.bind('<Destroy>',closed,add='+');hide_locked_dialog(app,self.window)
    def valid(self):
        return bool(self.window.winfo_exists() and not getattr(self.app,'closing',False) and not is_locked(self.app)
            and self.account==self.app.ui_account and self.backend is self.app.service.backend)
    def available(self):return self.valid() and self.pending is None
    def run(self,factory,done):
        if not self.available():return
        self.status.configure(text=tr('Loading...'))
        def ready(result):
            self.pending=None
            if self.valid():self.status.configure(text='');done(result)
        def error(exc):
            self.pending=None
            if self.valid():self.status.configure(text=str(exc))
        self.pending=self.app.worker.submit(factory(),ready,error)
    def button(self,label,command,parent=None):
        button=ttk.Button(parent or self.body,text=tr(label),command=lambda:command() if self.available() else None)
        button.pack(fill='x',pady=4);return button
    def confirm(self,label):return self.available() and messagebox.askyesno(tr(label),tr(label)+'?',parent=self.window) and self.available()
    def clear(self):
        for widget in self.body.winfo_children():widget.destroy()


def create_community(app,broadcast=False):
    if app.demo or is_locked(app):return
    panel=Panel(app,'New channel' if broadcast else 'Nuevo grupo','500x350')
    ttk.Label(panel.body,text=tr('Title')).pack(anchor='w');title=ttk.Entry(panel.body);title.pack(fill='x',pady=5)
    ttk.Label(panel.body,text=tr('Description')).pack(anchor='w');about=ttk.Entry(panel.body);about.pack(fill='x',pady=5)
    def created(chat):
        panel.window.destroy();app.open_resolved(chat)
    panel.button('Create',lambda:panel.run(lambda:panel.backend.create_community(title.get(),about.get(),broadcast),created),panel.footer)


def discussion_settings(app,peer):
    if app.demo or is_locked(app):return
    panel=Panel(app,'Linked discussion / channel','560x510')
    def refresh():panel.run(lambda:panel.backend.discussion_groups(peer),render)
    def render(info):
        panel.clear()
        items=info['items'];linked=info['linked'];listing=tk.Listbox(panel.body,exportselection=False)
        listing.pack(fill='both',expand=True,pady=6)
        for item in items:listing.insert('end',item['name']+(' · '+tr('Upgrade to supergroup') if item['basic'] else ''))
        ttk.Label(panel.body,text=tr('Linking makes the discussion history visible to new members. A basic group must be upgraded first.'),wraplength=490).pack(fill='x',pady=5)
        def link():
            if not listing.curselection():return
            target=items[listing.curselection()[0]]
            if panel.confirm('Link this discussion group and make its history visible?'):
                panel.run(lambda:panel.backend.set_discussion_group(peer,target['id'],expected_link=linked,expose_history=True,migrate=target['basic']),lambda _:refresh())
        panel.button('Link discussion group',link)
        if linked:
            panel.button('Open linked group',lambda:app.show_contact_profile(-1000000000000-linked))
            def unlink():
                if panel.confirm('Unlink discussion group'):panel.run(lambda:panel.backend.set_discussion_group(peer,None,expected_link=linked),lambda _:refresh())
            panel.button('Unlink discussion group',unlink)
        panel.button('Create discussion group',lambda:create_community(app,False))
    panel.button('Refresh',refresh,panel.footer);refresh()


def member_editor(app,peer,user,changed=None):
    if app.demo or is_locked(app):return
    panel=Panel(app,'Manage member')
    def refresh():panel.run(lambda:panel.backend.community_member(peer,user),render)
    def saved(_):
        if changed:changed()
        refresh()
    def render(info):
        panel.clear();person=info['person'];entity=info['entity'];part=info['participant']
        from .telegram_actions import peer_activity
        from telethon import types as t,utils
        ttk.Label(panel.body,text=utils.get_display_name(person)).pack(fill='x',pady=6)
        ttk.Label(panel.body,text=tr(info['role'])+' · '+peer_activity(person,app.preferences.values.get('show_seconds',False))).pack(fill='x',pady=4)
        if info['can_admin']:
            box=ttk.LabelFrame(panel.body,text=tr('Administrator permissions'),padding=8);box.pack(fill='x',pady=7)
            if isinstance(entity,t.Chat):
                admin=tk.BooleanVar(value=info['role']=='Administrator')
                ttk.Checkbutton(box,text=tr('Administrator'),variable=admin).pack(anchor='w')
                def save_basic():
                    if panel.confirm('Apply administrator permissions'):panel.run(lambda:panel.backend.community_admin(peer,user,{'administrator':admin.get()}),saved)
                panel.button('Save',save_basic,box)
            else:
                variables={};before=info['rights']
                for key,label in info['fields'].items():
                    enabled=bool(getattr(before,key,False));allowed=entity.creator or getattr(entity.admin_rights,key,False)
                    # Already granted flags remain visible even if this admin cannot grant them.
                    if not allowed and not enabled:continue
                    variable=variables[key]=tk.BooleanVar(value=enabled)
                    ttk.Checkbutton(box,text=tr(label),variable=variable).pack(anchor='w',pady=3)
                ttk.Label(box,text=tr('Administrator title')).pack(anchor='w')
                rank=ttk.Entry(box);rank.insert(0,getattr(part,'rank','') or '');rank.pack(fill='x',pady=4)
                def save_admin():
                    changes={k:v.get() for k,v in variables.items() if v.get()!=bool(getattr(before,k,False))}
                    if panel.confirm('Apply administrator permissions'):panel.run(lambda:panel.backend.community_admin(peer,user,changes,rank.get()),saved)
                panel.button('Save',save_admin,box)
        if info['can_ban']:
            def change(action,label):
                if panel.confirm(label):panel.run(lambda:panel.backend.community_restrict(peer,user,action=action),saved)
            panel.button('Remove member',lambda:change('remove','Remove member'))
            if isinstance(entity,t.Channel):
                if info['role']=='Removed':panel.button('Unban member',lambda:change('unban','Unban member'))
                else:panel.button('Ban member',lambda:change('ban','Ban member'))
                if entity.megagroup and info['role']!='Removed':
                    box=ttk.LabelFrame(panel.body,text=tr('Permissions'),padding=8);box.pack(fill='x',pady=6);variables={}
                    for key,label in PERMISSIONS.items():
                        if key=='manage_topics' and not entity.forum:continue
                        variable=variables[key]=tk.BooleanVar(value=permission_enabled(info['banned'],key))
                        ttk.Checkbutton(box,text=tr(label),variable=variable).pack(anchor='w',pady=3)
                    ttk.Label(box,text=tr('Duration')).pack(anchor='w')
                    duration=Choice(box,values=[tr('Forever'),tr('1 hour'),tr('1 day'),tr('1 week')]);duration.current(0);duration.pack(fill='x',pady=5)
                    def restrict():
                        changes={k:v.get() for k,v in variables.items() if v.get()!=permission_enabled(info['banned'],k)}
                        seconds=(None,3600,86400,604800)[duration.current()]
                        until=None if seconds is None else datetime.now(timezone.utc)+timedelta(seconds=seconds)
                        if panel.confirm('Apply member permissions'):panel.run(lambda:panel.backend.community_restrict(peer,user,changes,until=until),saved)
                    panel.button('Save',restrict,box)
                    if info['role']=='Restricted':panel.button('Remove restrictions',lambda:change('unban','Remove restrictions'))
    panel.button('Refresh',refresh,panel.footer);refresh()


def manage_members(app,peer):
    if app.demo or is_locked(app):return
    panel=Panel(app,'Manage members');state={'info':None,'cursor':0,'mode':None}
    picker=Choice(panel.footer,values=[tr('Members'),tr('Administrators'),tr('Restricted'),tr('Removed')]);picker.current(0);picker.pack(fill='x',pady=3)
    records={};listing=ttk.Treeview(panel.body,show='tree',selectmode='browse');listing.pack(fill='both',expand=True)
    bar=ttk.Scrollbar(panel.body,command=listing.yview);bar.pack(side='right',fill='y');listing.configure(yscrollcommand=bar.set)
    def fetch(reset=False):
        if not panel.available():return
        index=picker.current();mode=('members','members','restricted','removed')[index]
        if reset or index!=state['mode']:
            state.update(cursor=0,mode=index);records.clear();listing.delete(*listing.get_children())
        def loaded(result):
            from .telegram_actions import peer_activity
            for item in result['items']:
                if item['id'] in records:continue
                records[item['id']]=item
                status=peer_activity(item['activity_entity'],app.preferences.values.get('show_seconds',False))
                listing.insert('','end',iid=str(item['id']),text=item['name']+' · '+tr(item['role'])+' · '+status)
            state['cursor']=result['next_offset'];more.configure(state='normal' if result['more'] else 'disabled')
        panel.run(lambda:panel.backend.profile_members(peer,state['cursor'],admins=index==1,mode=mode),loaded)
    def selected():
        if listing.selection():member_editor(app,peer,int(listing.selection()[0]),lambda:fetch(True))
    listing.bind('<Double-Button-1>',lambda _:selected());picker.bind('<<ComboboxSelected>>',lambda _:fetch(True))
    more=panel.button('More',fetch,panel.footer);panel.button('Manage member',selected,panel.footer)
    def add():
        value=simpledialog.askstring(tr('Add members'),tr('Introduce un @usuario o telefono internacional.'),parent=panel.window)
        if value and panel.available():panel.run(lambda:panel.backend.community_add(peer,[value]),lambda result:added(result))
    def added(result):
        if getattr(result,'missing_invitees',None):messagebox.showinfo(APP_NAME,tr('Grupo creado; algunos usuarios no pudieron ser invitados.'),parent=panel.window)
        fetch(True)
    def info_loaded(profile):
        state['info']=profile
        if profile['can_invite']:panel.button('Add members',add,panel.footer)
        if not profile['is_channel']:
            picker.configure(values=[tr('Members'),tr('Administrators')])
        fetch(True)
    panel.run(lambda:panel.backend.profile(peer),info_loaded)
