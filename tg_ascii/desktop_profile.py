"""Contact, group and channel information using the app's themed controls."""
from datetime import datetime, timezone, timedelta
import tkinter as tk
from tkinter import ttk
from telethon import types as t, utils
from .app_dialogs import Choice, scrollable, messagebox, simpledialog, filedialog
from .i18n import tr
from .profile_details import PERMISSIONS


def permission_enabled(rights,key):
    if getattr(rights,key,False):return False
    if key.startswith('send_') or key=='embed_links':
        if getattr(rights,'send_messages',False):return False
    if key in ('send_photos','send_videos','send_roundvideos','send_audios','send_voices','send_docs') and getattr(rights,'send_media',False):return False
    return True


class DesktopProfile:
    def extend_profile(self,window,notebook,info,profile,backend,account,summary=True):
        if self.demo:return
        peer=profile['id']
        def valid():return window.winfo_exists() and account==self.ui_account and backend is self.service.backend
        def available():return valid() and not self.busy
        def button(parent,label,callback):
            ttk.Button(parent,text=tr(label),command=lambda:callback() if available() else None).pack(fill='x',pady=3)
        def line(label,value):
            from .contact_profile import copyable_field
            copyable_field(info,label,value,self,valid)
        line('Type',tr({'user':'Contact','bot':'Bot','group':'Group','channel':'Channel'}[profile['kind']]))
        if summary:
            for key,label in [('premium','Premium'),('verified','Verified'),('scam','Scam'),('fake','Fake')]:
                if profile.get(key):line('Status',tr(label))
        for key,label in [('members_count','Subscribers' if profile['kind']=='channel' else 'Members'),('admins_count','Administrators'),('online_count','Online'),('common_chats_count','Groups in common')]:
            if not (key=='online_count' and profile['kind']!='group') and profile.get(key) is not None and (key!='common_chats_count' or profile.get(key)):line(label,profile[key])
        for name in profile['usernames']:
            link='https://t.me/'+name
            def copy_link(url=link):
                # 1.4: clicking the profile link copies it.
                self.root.clipboard_clear();self.root.clipboard_append(url)
                self.status.set(tr('Link copied to the clipboard.'))
            button(info,link,copy_link)
        location=profile.get('location')
        if getattr(location,'address',None):line('Address',location.address)
        hours=profile.get('work_hours')
        if hours:
            line('Time zone',hours.timezone_id)
            days=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
            def minute(value):
                day,mins=divmod(value,1440);hour,minute=divmod(mins,60)
                return f'{tr(days[day%7])} {hour:02d}:{minute:02d}'
            for span in hours.weekly_open:line('Opening hours',minute(span.start_minute)+' — '+minute(span.end_minute))
        for key,label in [('protected_content','Protected content'),('forum','Topics'),('join_request','Join requests'),('hidden_prehistory','History hidden for new members')]:
            if profile.get(key):line(label,tr('Enabled'))
        for key,label in [('linked_chat_id','Linked discussion / channel'),('personal_channel_id','Personal channel')]:
            if profile.get(key):button(info,label,lambda ident=profile[key]:self.show_contact_profile(utils.get_peer_id(t.PeerChannel(ident))))
        if profile.get('invite_link'):
            line('Invite link',profile['invite_link'])
            button(info,'Copy link',lambda:(self.root.clipboard_clear(),self.root.clipboard_append(profile['invite_link'])))
        def open_chat():
            def loaded(chat):
                if valid():window.destroy();self.open_resolved(chat)
            self.call(backend.resolve_chat(peer),loaded,tr('Loading...'))
        if summary:
            button(info,'Abrir chat',open_chat)
            button(info,'Shared media',lambda:self.message_browser(True,peer))
        if profile.get('can_view_members'):
            button(info,'Members',lambda:self.profile_people(peer,backend,account))
            button(info,'Administrators',lambda:self.profile_people(peer,backend,account,admins=True))
        if profile.get('common_chats_count'):button(info,'Groups in common',lambda:self.profile_people(peer,backend,account,common=True))
        settings=ttk.Frame(notebook);notebook.add(settings,text=tr('Ajustes'));body=scrollable(settings)
        if profile.get('can_view_members') or profile.get('can_ban') or profile.get('creator'):
            from .desktop_community import manage_members
            button(body,'Manage members',lambda:manage_members(self,peer))
        if profile['kind']=='channel' and profile.get('can_edit_info'):
            from .desktop_community import discussion_settings
            button(body,'Linked discussion / channel',lambda:discussion_settings(self,peer))
        button(body,'Notifications',lambda:self.profile_notifications(peer,backend,account))
        def changed(_):
            if valid():window.destroy();self.show_contact_profile(peer)
        def apply(field,value):
            if available():self.call(backend.profile_change(peer,field,value),changed,tr('Saving...'),timeout=None if field=='photo' and value is not None else 45)
        def confirm_action(label,operation):
            if available() and messagebox.askyesno(tr(label),tr(label)+'?\n'+profile['name'],parent=window) and available():
                self.call(operation(),changed,tr('Saving...'))
        if profile['is_user'] and not profile.get('is_self'):
            label='Unblock' if profile.get('blocked') else 'Block'
            button(body,label,lambda:confirm_action(label,lambda:backend.profile_block(peer,not profile.get('blocked'))))
            if profile.get('contact'):button(body,'Delete contact',lambda:confirm_action('Delete contact',lambda:backend.profile_delete_contact(peer)))
        def field_editor(label,key,current):
            value=simpledialog.askstring(tr(label),tr(label),initialvalue=current,parent=window)
            if value is not None and value!=current:apply(key,value)
        if profile.get('can_edit_info'):
            button(body,'Edit title',lambda:field_editor('Edit title','title',profile['name']))
            button(body,'Description',lambda:field_editor('Description','about',profile['about']))
            def photo():
                path=filedialog.askopenfilename(parent=window,title=tr('Cambiar foto'),filetypes=[('Images','*.jpg *.jpeg *.png')])
                if path:apply('photo',path)
            button(body,'Cambiar foto',photo)
            button(body,'Remove photo',lambda:confirm_action('Remove photo',lambda:backend.profile_change(peer,'photo',None)))
        if profile.get('can_change_username'):button(body,'Nombre de usuario',lambda:field_editor('Nombre de usuario','username',profile['username']))
        def choice_setting(label,key,current,options,confirm=False):
            group=ttk.LabelFrame(body,text=tr(label),padding=6);group.pack(fill='x',pady=5)
            entries=list(options)
            if current not in [v for v,_ in entries]:entries.insert(0,(current,str(current)))
            picker=Choice(group,values=[tr(label) for _,label in entries]);picker.pack(fill='x');picker.current([v for v,_ in entries].index(current))
            def save():
                if picker.current()<0:return
                value=entries[picker.current()][0]
                if value==current:return
                if confirm and not messagebox.askyesno(tr(label),tr('Apply this setting to the chat for everyone?'),parent=window):return
                apply(key,value)
            button(group,'Save',save)
        if profile.get('can_set_ttl'):
            choice_setting('Auto-delete messages','ttl',profile['ttl_period'],[(0,'Off'),(86400,'1 day'),(604800,'1 week'),(2678400,'1 month')],True)
        if profile.get('can_ban') and profile['kind']=='group':
            button(body,'Permissions',lambda:self.profile_permissions(profile,backend,account))
            if profile['is_channel']:choice_setting('Slow mode','slowmode',profile['slowmode_seconds'],[(0,'Off'),(10,'10 s'),(30,'30 s'),(60,'1 min'),(300,'5 min'),(900,'15 min'),(3600,'1 h')],True)
        if profile.get('can_manage_reactions'):
            reactions=profile.get('available_reactions');current='all' if isinstance(reactions,t.ChatReactionsAll) else 'none' if isinstance(reactions,t.ChatReactionsNone) else 'keep'
            choice_setting('Reactions','reactions',current,([('keep','Keep current selection')] if current=='keep' else [])+[('all','All reactions'),('none','No reactions')],True)
        if profile.get('can_invite'):
            def invite():
                if not messagebox.askyesno(tr('Create link'),tr('Create an additional invite link?'),parent=window):return
                if not available():return
                def ready(result):
                    if valid():
                        value=getattr(result,'link','')
                        dialog,frame=self.dialog('Invite link','540x160')
                        entry=ttk.Entry(frame);entry.insert(0,value);entry.configure(state='readonly');entry.pack(fill='x',pady=12)
                        ttk.Button(frame,text=tr('Copy link'),command=lambda:(self.root.clipboard_clear(),self.root.clipboard_append(value))).pack()
                self.call(backend.profile_change(peer,'invite',None),ready,tr('Saving...'))
            button(body,'Create link',invite)
        from .chat_capabilities import chat_capabilities
        if chat_capabilities(self,peer).allows('clear_history'):
            button(body,'Clear history',lambda:self.chat_history_action(peer,True))
        button(body,'Delete chat',lambda:self.chat_history_action(peer,False))

    def profile_people(self,peer,backend,account,admins=False,common=False):
        title='Groups in common' if common else 'Administrators' if admins else 'Members'
        window,frame=self.dialog(title,'540x550');query=tk.StringVar();records=[];cursor=[0];more=[True]
        def valid():return window.winfo_exists() and account==self.ui_account and backend is self.service.backend
        if not common and not admins:ttk.Entry(frame,textvariable=query).pack(fill='x',pady=4)
        list_frame=ttk.Frame(frame);list_frame.pack(fill='both',expand=True)
        listing=ttk.Treeview(list_frame,show='tree',selectmode='browse');listing.pack(side='left',fill='both',expand=True)
        bar=ttk.Scrollbar(list_frame,command=listing.yview);bar.pack(side='right',fill='y');listing.configure(yscrollcommand=bar.set)
        def fetch(reset=False):
            if self.busy or not valid():return
            if reset:cursor[0]=0;records.clear();listing.delete(*listing.get_children());more[0]=True
            if not more[0]:return
            def loaded(result):
                if not valid():return
                if common:
                    items=[dict(id=c.id,name=c.name,role='') for c in result]
                    cursor[0]=abs(result[-1].id)-1000000000000 if result and result[-1].id<-1000000000000 else abs(result[-1].id) if result else 0
                    more[0]=len(result)==50
                else:items=result['items'];cursor[0]=result['next_offset'];more[0]=result['more']
                for item in items:
                    if any(r['id']==item['id'] for r in records):continue
                    from .telegram_actions import peer_activity
                    activity=peer_activity(item['activity_entity'],self.preferences.values.get('show_seconds',False)) if item.get('activity_entity') is not None else ''
                    records.append(item);listing.insert('','end',iid=str(item['id']),text=item['name']+(' · '+tr(item['role']) if item['role'] else '')+(' · '+item.get('rank','') if item.get('rank') else '')+(' · '+activity if activity else ''))
                next_button.configure(state='normal' if more[0] else 'disabled')
            operation=backend.profile_common_chats(peer,cursor[0]) if common else backend.profile_members(peer,cursor[0],query.get(),admins)
            self.call(operation,loaded,tr('Loading...'))
        def selected():
            if valid() and not self.busy and listing.selection():self.show_contact_profile(int(listing.selection()[0]))
        listing.bind('<Double-Button-1>',lambda _:selected());listing.bind('<Return>',lambda _:selected())
        controls=ttk.Frame(frame);controls.pack(fill='x')
        if not common and not admins:ttk.Button(controls,text=tr('Search'),command=lambda:fetch(True)).pack(side='left')
        next_button=ttk.Button(controls,text=tr('More'),command=fetch);next_button.pack(side='left')
        ttk.Button(controls,text=tr('Informacion'),command=selected).pack(side='right');fetch()

    def profile_permissions(self,profile,backend,account):
        window,outer=self.dialog('Permissions','530x620');frame=scrollable(outer);variables={};before={}
        def available():return window.winfo_exists() and not self.busy and account==self.ui_account and backend is self.service.backend
        rights=profile.get('default_banned_rights')
        for key,label in PERMISSIONS.items():
            if key=='manage_topics' and not profile.get('forum'):continue
            before[key]=permission_enabled(rights,key);variables[key]=tk.BooleanVar(value=before[key])
            ttk.Checkbutton(frame,text=tr(label),variable=variables[key]).pack(anchor='w',pady=4)
        def save():
            if not available():return
            changes={k:v.get() for k,v in variables.items() if v.get()!=before[k]}
            if not changes:return
            if not messagebox.askyesno(tr('Permissions'),tr('Apply this setting to the chat for everyone?'),parent=window):return
            if not available():return
            self.call(backend.profile_change(profile['id'],'permissions',changes),lambda _:window.destroy() if window.winfo_exists() else None,tr('Saving...'))
        ttk.Button(frame,text=tr('Save'),command=save).pack(fill='x',pady=12)

    def profile_notifications(self,peer,backend,account):
        def loaded(current):
            if account!=self.ui_account or backend is not self.service.backend:return
            window,outer=self.dialog('Notifications','540x490');frame=scrollable(outer)
            muted=getattr(current,'mute_until',None)
            if muted and muted.timestamp()>datetime.now(timezone.utc).timestamp():
                ttk.Label(frame,text=tr('Muted until')+': '+muted.astimezone().strftime('%d/%m/%Y %H:%M')).pack(anchor='w')
            choices=[('keep','Keep current setting'),(0,'Enabled'),(3600,'Mute for 1 hour'),(28800,'Mute for 8 hours'),(172800,'Mute for 2 days'),(-1,'Mute')]
            picker=Choice(frame,values=[tr(label) for _,label in choices]);picker.current(0);picker.pack(fill='x',pady=8)
            values={}
            for key,label in [('show_previews','Show message previews'),('stories_muted','Mute stories'),('stories_hide_sender','Hide story sender')]:
                ttk.Label(frame,text=tr(label)).pack(anchor='w')
                value=getattr(current,key,None)
                ttk.Label(frame,text=tr('Default') if value is None else tr('Enabled') if value else tr('Disabled'),style='Muted.TLabel').pack(anchor='w')
                choice=Choice(frame,values=[tr('Keep current setting'),tr('Enabled'),tr('Disabled')]);choice.current(0);choice.pack(fill='x',pady=4)
                values[key]=(value,choice)
            ttk.Label(frame,text=tr('Sound')).pack(anchor='w')
            sound=Choice(frame,values=[tr('Keep current setting'),tr('Default'),tr('Off')]);sound.current(0);sound.pack(fill='x')
            def save():
                if self.busy or account!=self.ui_account or backend is not self.service.backend:return
                changes={}
                duration=choices[picker.current()][0]
                if duration!='keep':changes['mute_until']=datetime.fromtimestamp(2147483647 if duration==-1 else 0,timezone.utc) if duration<=0 else datetime.now(timezone.utc)+timedelta(seconds=duration)
                for key,(before,choice) in values.items():
                    index=choice.current()
                    if index==0:continue # Omitted fields preserve the server's inheritance/override.
                    after=index==1
                    if after!=before:changes[key]=after
                if sound.current()>0:changes['sound']=t.NotificationSoundDefault() if sound.current()==1 else t.NotificationSoundNone()
                self.call(backend.profile_notify(peer,changes),lambda _:window.destroy() if window.winfo_exists() else None,tr('Saving...'))
            ttk.Button(frame,text=tr('Save'),command=save).pack(fill='x',pady=12)
        async def fetch():
            from telethon import functions
            return await backend.client(functions.account.GetNotifySettingsRequest(t.InputNotifyPeer(await backend.client.get_input_entity(peer))))
        self.call(fetch(),loaded,tr('Loading...'))
