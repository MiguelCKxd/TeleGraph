"""Channel-call planning and RTMP setup, loaded only when explicitly opened."""
from datetime import datetime
import tkinter as tk
from tkinter import ttk
from .app_dialogs import simpledialog,messagebox,scrollable
from .app_lock import is_locked,hide_locked_dialog
from .i18n import tr
from .advanced_features import feature_enabled
from .calls_native import engine_available


def open_channel_calls(app):
    if app.demo or app.active is None or is_locked(app):
        return
    backend,account,peer=app.service.backend,app.ui_account,app.active
    controls=backend.channel_call_controls()
    window=tk.Toplevel(app.root);window.title(tr('Group call'));window.geometry('520x420')
    footer=ttk.Frame(window,padding=8);footer.pack(side='bottom',fill='x')
    content=scrollable(window)
    body=ttk.Frame(content,padding=16);body.pack(fill='both',expand=True)
    heading=ttk.Label(body,text=tr('Loading...'),wraplength=480);heading.pack(fill='x',pady=8)
    buttons=ttk.Frame(body);buttons.pack(fill='x')
    status=ttk.Label(body,wraplength=480);status.pack(fill='x',pady=8)
    state={'future':None,'info':None}
    def valid():
        return bool(window.winfo_exists() and not app.closing and not is_locked(app)
            and feature_enabled(app,'calls') and app.ui_account==account and app.service.backend is backend)
    def launch(factory,ready):
        if not valid() or state['future'] is not None:return
        status.configure(text=tr('Loading...'))
        def done(result):
            state['future']=None
            if valid():ready(result)
        def failed(error):
            state['future']=None
            if valid():status.configure(text=str(error))
        state['future']=app.worker.submit(factory(),done,failed)
    def refresh():launch(lambda:controls.info(peer),render)
    def change(action,expected,**kwargs):
        if not valid() or state['future'] is not None:return
        if state['info']['call_id']!=expected:return
        ident=expected
        launch(lambda:controls.change(peer,ident,action,**kwargs),
            show_rtmp if action in ('rtmp','rotate_rtmp') else show_link if action in ('invite','speaker_invite') else lambda _:refresh())
    def confirm_change(action,label,expected):
        if not valid():return
        if state['info']['call_id']!=expected:return
        ident=expected
        if messagebox.askyesno(tr('Group call'),tr(label),parent=window) and valid() and state['info']['call_id']==ident:
            change(action,expected)
    def add(label,command):ttk.Button(buttons,text=tr(label),command=command).pack(fill='x',pady=3)
    def create(rtmp=False,schedule=False):
        if not valid() or state['future'] is not None:return
        title=simpledialog.askstring(tr('Title'),tr('Title'),parent=window)
        if title is None or not valid():return
        date=None
        if schedule:
            value=simpledialog.askstring(tr('Schedule call'),tr('Local date and time (YYYY-MM-DD HH:MM)'),parent=window)
            if not value or not valid():return
            try:date=datetime.strptime(value,'%Y-%m-%d %H:%M').astimezone()
            except ValueError:status.configure(text=tr('Invalid date'));return
        launch(lambda:controls.create(peer,title=title,schedule=date,rtmp=rtmp),lambda _:refresh())
    def secret_dialog(title,fields):
        if not valid():return
        dialog=tk.Toplevel(window);dialog.title(tr(title))
        panel=ttk.Frame(dialog,padding=14);panel.pack(fill='both',expand=True)
        for label,value,secret in fields:
            ttk.Label(panel,text=tr(label)).pack(anchor='w')
            entry=ttk.Entry(panel,width=60,show='•' if secret else '')
            entry.insert(0,value);entry.configure(state='readonly');entry.pack(fill='x',pady=5)
            if secret:
                visible=tk.BooleanVar(master=dialog,value=False)
                ttk.Checkbutton(panel,text=tr('Show'),variable=visible,
                    command=lambda e=entry,v=visible:e.configure(show='' if v.get() else '•')).pack(anchor='w')
        hide_locked_dialog(app,dialog)
    def show_link(result):
        status.configure(text='')
        secret_dialog('Invite link',[('Link',result.link,False)])
    def show_rtmp(result):
        status.configure(text='')
        # Keys stay in the local window; no persistence, telemetry or logging.
        secret_dialog('RTMP',[('Server URL',result.url,False),('Stream key',result.key,True)])
    def render(info):
        state['info']=info
        for widget in buttons.winfo_children():widget.destroy()
        status.configure(text='')
        heading.configure(text=(info['title'] or tr('Group call'))+' · '+str(info['participants_count']))
        if not info['active']:
            if info['admin']:
                add('Start a new group call?',lambda:app.start_group_call(peer=peer,create=True))
                add('Schedule call',lambda:create(schedule=True))
                add('Create RTMP stream',lambda:create(rtmp=True))
                add('Schedule RTMP stream',lambda:create(rtmp=True,schedule=True))
            else:status.configure(text=tr('No active call'))
            return
        if info['scheduled']:
            ttk.Label(buttons,text=info['scheduled'].astimezone().strftime('%Y-%m-%d %H:%M')).pack(fill='x')
            add('Disable reminder' if info['subscribed'] else 'Remind me',lambda:change('subscribe',info['call_id'],enabled=not info['subscribed']))
            if info['admin']:add('Start now',lambda:confirm_change('start','Start scheduled call now?',info['call_id']))
        elif engine_available():add('Join call',lambda:app.start_group_call(peer=peer,view_only=info['rtmp']))
        else:status.configure(text=tr('Call engine is not installed.'))
        if info.get('can_invite'):add('Invite link',lambda:change('invite',info['call_id']))
        if info['admin']:
            if info.get('public') and not info['rtmp']:add('Speaker invite link',lambda:change('speaker_invite',info['call_id']))
            if info['rtmp']:
                add('RTMP server and key',lambda:change('rtmp',info['call_id']))
                add('Replace stream key',lambda:confirm_change('rotate_rtmp','Replace stream key? Existing publishers will disconnect.',info['call_id']))
            add('Cancel scheduled call' if info['scheduled'] else 'End call for everyone',
                lambda:confirm_change('cancel' if info['scheduled'] else 'end','End call for everyone?',info['call_id']))
    ttk.Button(footer,text=tr('Refresh'),command=refresh).pack(fill='x')
    def destroyed(event):
        if event.widget is window and state['future'] is not None:state['future'].cancel()
    window.bind('<Destroy>',destroyed,add='+')
    hide_locked_dialog(app,window);refresh()
    return window
