"""Local interface lock, separate from Telegram credentials and appearance files.

Passwords are verified off the Tk thread. This is an interface access control,
not encryption of the account/session directory or a protection against code
running as the same operating-system user.
"""
import hashlib
import hmac
import json
import queue
import secrets
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from . import APP_NAME
from .i18n import tr
from .preferences import write_json

ITERATIONS=600_000
MAX_RECORD_BYTES=4096
_STORE_LOCK=threading.RLock()
_UNSPECIFIED=object()


class InvalidLock(ValueError):
    pass


def password_bytes(value):
    if not isinstance(value,str):
        raise ValueError(tr('Incorrect app password.'))
    return value.encode('utf-8')


def make_record(password,biometric=False,lock_on_hide=True):
    salt=secrets.token_bytes(16)
    digest=hashlib.pbkdf2_hmac('sha256',password_bytes(password),salt,ITERATIONS)
    return {'schema':1,'algorithm':'pbkdf2-sha256','iterations':ITERATIONS,
            'salt':salt.hex(),'digest':digest.hex(),'biometric':bool(biometric),'lock_on_hide':bool(lock_on_hide)}


def checked_record(value):
    valid=isinstance(value,dict) and set(value)=={'schema','algorithm','iterations','salt','digest','biometric','lock_on_hide'}
    if valid:
        valid=(value['schema']==1 and type(value['schema']) is int and value['algorithm']=='pbkdf2-sha256'
               and type(value['iterations']) is int and value['iterations']==ITERATIONS
               and type(value['biometric']) is bool and type(value['lock_on_hide']) is bool)
    try:
        if not valid or len(value['salt'])!=32 or len(value['digest'])!=64:raise ValueError
        if len(bytes.fromhex(value['salt']))!=16 or len(bytes.fromhex(value['digest']))!=32:raise ValueError
    except (ValueError,TypeError,KeyError):
        raise InvalidLock(tr('App lock settings are damaged. Restore your app-lock.json backup before opening the app.')) from None
    return dict(value)


def verify_password(record,password):
    record=checked_record(record)
    if not isinstance(password,str):return False
    digest=hashlib.pbkdf2_hmac('sha256',password_bytes(password),bytes.fromhex(record['salt']),ITERATIONS)
    return hmac.compare_digest(digest,bytes.fromhex(record['digest']))


class LockStore:
    def __init__(self,directory):
        self.path=Path(directory)/'app-lock.json'

    def load(self):
        try:
            if self.path.is_symlink() or self.path.stat().st_size>MAX_RECORD_BYTES:
                raise InvalidLock(tr('App lock settings are damaged. Restore your app-lock.json backup before opening the app.'))
            with self.path.open('rb') as stream:raw=stream.read(MAX_RECORD_BYTES+1)
        except FileNotFoundError:return None
        except OSError as error:raise InvalidLock(str(error)) from error
        try:
            if len(raw)>MAX_RECORD_BYTES:raise ValueError
            return checked_record(json.loads(raw))
        except (ValueError,TypeError,RecursionError):
            raise InvalidLock(tr('App lock settings are damaged. Restore your app-lock.json backup before opening the app.')) from None

    def save(self,record,expected=_UNSPECIFIED):
        record=checked_record(record)
        with _STORE_LOCK:
            if expected is not _UNSPECIFIED and self.load()!=expected:
                raise ValueError(tr('Authentication was canceled or unsuccessful.'))
            write_json(self.path.with_suffix('.json.backup'),record)
            write_json(self.path,record)

    def disable(self,password,expected=_UNSPECIFIED):
        current=self.load()
        if current is not None and not verify_password(current,password):raise ValueError(tr('Incorrect app password.'))
        with _STORE_LOCK:
            if self.load()!=current or (expected is not _UNSPECIFIED and current!=expected):
                raise ValueError(tr('Authentication was canceled or unsuccessful.'))
            # Keep the active protection if removing its backup fails.
            self.path.with_suffix('.json.backup').unlink(missing_ok=True)
            self.path.unlink(missing_ok=True)


class UnlockPanel:
    """Only one auth attempt owns a panel; late OS replies cannot unlock a new one."""
    def __init__(self,window,store,unlocked,quit_app):
        self.window,self.store,self.unlocked=window,store,unlocked
        self.closed=False;self.pending=False;self.attempts=0;self.next_attempt=0
        self.cancel=threading.Event();self.events=queue.SimpleQueue();self.timer=None
        from .startup_look import display_name,heading
        window.title(display_name() + ' · ' + tr('App lock'));window.geometry('440x380');window.minsize(360,320)
        self.body=ttk.Frame(window,padding=24);self.body.pack(fill='both',expand=True)
        heading(self.body).pack(anchor='w',pady=(0,8))
        ttk.Label(self.body,text=tr('Unlock the app to continue.'),wraplength=370).pack(fill='x',pady=(0,16))
        self.password=tk.StringVar(master=window)
        self.entry=ttk.Entry(self.body,textvariable=self.password,show='•');self.entry.pack(fill='x')
        self.status=ttk.Label(self.body,wraplength=370);self.status.pack(fill='x',pady=12)
        self.submit=ttk.Button(self.body,text=tr('Unlock'),command=self.attempt);self.submit.pack(fill='x')
        self.bio=ttk.Button(self.body,text=tr('Use device authentication'),command=lambda:self.attempt(True))
        try:
            self.record=store.load()
            if self.record is None:window.after_idle(self.finish);return
            if self.record['biometric']:self.bio.pack(fill='x',pady=8)
        except InvalidLock as error:
            self.record=None;self.status.configure(text=str(error));self.submit.configure(state='disabled');self.entry.configure(state='disabled')
        ttk.Button(self.body,text=tr('Quit TeleGraph'),command=quit_app).pack(fill='x',pady=8)
        window.protocol('WM_DELETE_WINDOW',quit_app)
        window.bind('<Destroy>',self.destroyed,add='+')
        self.entry.bind('<Return>',lambda _:self.attempt());self.entry.focus_set()
        self.timer=window.after(60,self.poll)

    def attempt(self,biometric=False):
        if self.closed or self.pending or self.record is None:return
        if time.monotonic()<self.next_attempt:
            self.status.configure(text=tr('Please wait before trying again.'));return
        if not self.refresh_record():return
        record=self.record
        if biometric and not record['biometric']:return
        password=self.password.get();self.password.set('')
        self.pending=True;self.submit.configure(state='disabled');self.bio.configure(state='disabled')
        self.status.configure(text=tr('Loading...'))
        handle=self.window.winfo_id()
        cancel,events=self.cancel,self.events
        def work():
            try:
                if biometric:
                    from .native_auth import authenticate,availability
                    available,_=availability()
                    if not available:raise ValueError(tr('Device authentication is unavailable. Use your app password.'))
                    success=authenticate(tr('Unlock your messages'),handle,cancel)
                else:success=verify_password(record,password)
                result=(bool(success),None,record)
            except Exception as error:result=(False,str(error),record)
            events.put(result)
        threading.Thread(target=work,name='tg-app-unlock',daemon=True).start()

    def poll(self):
        self.timer=None
        if self.closed:return
        try:success,error,record=self.events.get_nowait()
        except queue.Empty:pass
        else:
            self.pending=False
            if not self.refresh_record():return
            if success and self.record==record:self.finish();return
            self.attempts+=1
            self.next_attempt=time.monotonic()+(min(30,2**min(self.attempts-3,5)) if self.attempts>=3 else 0)
            self.status.configure(text=error or tr('Authentication was canceled or unsuccessful.'))
            self.submit.configure(state='normal');self.bio.configure(state='normal')
            self.entry.focus_set()
        self.timer=self.window.after(60,self.poll)

    def refresh_record(self):
        try:
            record=self.store.load()
            if record is None:self.finish();return False
            self.record=record
            if record['biometric']:self.bio.pack(fill='x',pady=8)
            else:self.bio.pack_forget()
            return True
        except InvalidLock as error:
            self.record=None;self.status.configure(text=str(error))
            self.submit.configure(state='disabled');self.bio.pack_forget();self.entry.configure(state='disabled')
            return False

    def finish(self):
        if self.closed:return
        self.close();self.body.destroy();self.unlocked()

    def destroyed(self,event):
        if event.widget is self.window:self.close()

    def close(self):
        self.closed=True;self.cancel.set();self.password.set('')
        if self.timer is not None:
            try:self.window.after_cancel(self.timer)
            except tk.TclError:pass
            self.timer=None


def startup_gate(root,store,start):
    try:record=store.load()
    except InvalidLock:record=True
    if record is None:return start()
    from .notifications import clear_locked_notification_history
    root._startup_private_notices=clear_locked_notification_history()
    def ready():
        root._startup_private_notices=None
        return start()
    return UnlockPanel(root,store,ready,root.destroy)


def open_lock_settings(app):
    owner=getattr(app,'_linked_owner',None) or app
    if app.demo or app.busy:return
    store=LockStore(owner.service.root)
    try:current=store.load()
    except InvalidLock as error:app.show_error(error);return
    window,body=app.dialog('App lock','540x560')
    ttk.Label(body,text=tr('This lock protects access to the interface. It does not encrypt Telegram session files. Keep your device account and disk protected.'),wraplength=460).pack(fill='x',pady=8)
    values=[]
    for index,title in enumerate(('Current app password','New app password','Repeat app password')):
        value=tk.StringVar(master=window);values.append(value)
        if index==0 and current is None:continue
        ttk.Label(body,text=tr(title)).pack(anchor='w',pady=(8,2))
        ttk.Entry(body,textvariable=value,show='•').pack(fill='x')
    biometric=tk.BooleanVar(master=window,value=bool(current and current['biometric']))
    hidden=tk.BooleanVar(master=window,value=current['lock_on_hide'] if current else True)
    bio_button=ttk.Checkbutton(body,text=tr('Use device authentication'),variable=biometric);bio_button.pack(fill='x',pady=8)
    capability=ttk.Label(body,text=tr('Loading...'),wraplength=460);capability.pack(fill='x')
    ttk.Checkbutton(body,text=tr('Lock when hiding the app'),variable=hidden).pack(fill='x')
    ttk.Label(body,text=tr('Remember this password. It is separate from your Telegram password and cannot be recovered.'),wraplength=460).pack(fill='x',pady=8)
    status=ttk.Label(body,wraplength=460);status.pack(fill='x')
    state={'pending':False,'password_edited':False,'clearing':False};cancel=threading.Event()
    def edited(*_):
        if not state['clearing']:state['password_edited']=True
    for value in values[1:]:value.trace_add('write',edited)
    def clear_values():
        state['clearing']=True
        try:
            for value in values:value.set('')
        finally:
            state['clearing']=False;state['password_edited']=False
    async def probe():
        import asyncio
        from .native_auth import availability
        return await asyncio.to_thread(availability)
    def probed(result):
        if window.winfo_exists():
            supported,label=result;capability.configure(text=label)
            if not supported and not biometric.get():bio_button.configure(state='disabled')
    app.worker.submit(probe(),probed,lambda _:probed((False,tr('Device authentication is unavailable. Use your app password.'))))
    def closed(event):
        if event.widget is window:
            cancel.set()
            clear_values()
    window.bind('<Destroy>',closed,add='+')
    def save(disable=False):
        if state['pending'] or not window.winfo_exists():return
        old,new,repeat=[value.get() for value in values]
        # Untouched fields save preferences without changing the password.
        # Editing then clearing either field explicitly selects an empty one.
        if current is not None and not state['password_edited'] and not new and not repeat:new=repeat=old
        if not disable:
            try:password_bytes(new)
            except ValueError as error:status.configure(text=str(error));return
            if new!=repeat:status.configure(text=tr('The passwords do not match.'));return
        use_bio,hide=biometric.get(),hidden.get();handle=window.winfo_id()
        state['pending']=True
        clear_values()
        status.configure(text=tr('Guardando...'))
        def operation():
            latest=store.load()
            if latest!=current:raise ValueError(tr('Authentication was canceled or unsuccessful.'))
            if not disable and latest and not verify_password(latest,old):raise ValueError(tr('Incorrect app password.'))
            if cancel.is_set():return False
            if disable:store.disable(old,expected=current)
            else:
                if use_bio and not (latest and latest['biometric']):
                    from .native_auth import authenticate
                    if not authenticate(tr('Unlock your messages'),handle,cancel):raise ValueError(tr('Authentication was canceled or unsuccessful.'))
                record=make_record(new,use_bio,hide)
                if cancel.is_set():return False
                store.save(record,expected=current)
            return True
        import asyncio
        async def request():return await asyncio.to_thread(operation)
        def done(saved):
            state['pending']=False
            if saved and window.winfo_exists():
                status.configure(text=tr('App lock is disabled.') if disable else tr('App lock is enabled for every launch.'))
                window.destroy()
                owner.status.set(tr('App lock is disabled.') if disable else tr('App lock is enabled for every launch.'))
        def failed(error):
            state['pending']=False
            if window.winfo_exists():status.configure(text=str(error))
        app.worker.submit(request(),done,failed)
    ttk.Button(body,text=tr('Change app password') if current else tr('Enable app lock'),command=save).pack(fill='x',pady=6)
    if current:ttk.Button(body,text=tr('Disable app lock'),command=lambda:save(True)).pack(fill='x',pady=6)


def lock_owner(app):
    return getattr(app,'_linked_owner',None) or app


def is_locked(app):
    return bool(getattr(lock_owner(app),'_app_locked',False))


def show_locked(app,after=None):
    owner=lock_owner(app)
    if not is_locked(owner):return False
    if after is not None:owner._after_unlock=after
    panel=getattr(owner,'_app_lock_panel',None)
    if panel is not None and panel.window.winfo_exists():
        panel.window.deiconify();panel.window.lift();panel.window.grab_set();panel.entry.focus_set()
    return True


def hide_locked_dialog(app,window):
    owner=lock_owner(app)
    if is_locked(owner):
        conceal_window(owner,window,'normal')


def conceal_window(owner,window,state):
    # Cover before withdrawing: taskbar activation/OS map events cannot expose
    # the retained controls before the unlock panel is brought forward again.
    if any(item is window for item,_ in owner._locked_windows):return
    cover=ttk.Frame(window)
    cover.place(x=0,y=0,relwidth=1,relheight=1);cover.lift()
    ttk.Label(cover,text=tr('Unlock the app to continue.')).place(relx=.5,rely=.5,anchor='center')
    owner._lock_covers.append(cover)
    def mapped(event):
        if event.widget is window and is_locked(owner):
            window.withdraw();show_locked(owner)
    binding=window.bind('<Map>',mapped,add='+')
    owner._lock_bindings.append((window,binding))
    owner._locked_windows.append((window,state));window.withdraw()


def lock_app(app,show=True):
    owner=lock_owner(app)
    if owner.demo or owner.closed or owner.closing:return False
    if is_locked(owner):
        if show:show_locked(owner)
        return True
    store=LockStore(owner.service.root)
    try:record=store.load()
    except InvalidLock:record=True
    if record is None:
        if show:open_lock_settings(app)
        return False
    grab=owner.root.grab_current()
    grab_status=grab.grab_status() if grab is not None else None
    if grab is not None:grab.grab_release()
    menu=getattr(owner.root,'_context_menu',None)
    if menu is not None:
        try:getattr(menu,'_dismiss',menu.destroy)()
        except tk.TclError:pass
    owner._app_locked=True;owner._locked_windows=[];owner._after_unlock=None
    from .desktop_media_lifetime import revoke
    revoke(owner)
    owner._lock_covers=[];owner._lock_bindings=[];owner._lock_errors=[]
    def hide(widget):
        for child in widget.winfo_children():hide(child)
        if isinstance(widget,(tk.Tk,tk.Toplevel)):
            conceal_window(owner,widget,widget.state())
    hide(owner.root)
    # Inline notices and quick-reply boxes belong to their individual views.
    for view in (owner,*getattr(owner,'_app_windows',())):
        notice=getattr(view,'inline_notice',None)
        if notice is not None:notice.close()
    gate=tk.Toplevel(owner.root)
    gate._app_lock_gate=True
    # A late media/profile callback may create a Toplevel directly. Protect all
    # future windows in this interpreter, not just the app's dialog factory.
    def mapped(event):
        window=event.widget
        if isinstance(window,tk.Toplevel) and window is not gate and is_locked(owner):
            conceal_window(owner,window,'normal')
            window.withdraw();show_locked(owner)
    prior_map=owner.root.bind_class('Toplevel','<Map>')
    class_binding=owner.root.bind_class('Toplevel','<Map>',mapped,add='+')
    center=getattr(owner,'notification_center',None)
    if center is not None:center.set_locked(True)
    def unlocked():
        owner._app_locked=False
        owner.root.bind_class('Toplevel','<Map>',prior_map or '')
        owner.root.deletecommand(class_binding)
        if center is not None:center.set_locked(False)
        saved=owner._locked_windows;owner._locked_windows=[]
        owner._app_lock_panel=None
        gate.destroy()
        for window,binding in owner._lock_bindings:
            try:
                if window.winfo_exists():window.unbind('<Map>',binding)
            except tk.TclError:pass
        for cover in owner._lock_covers:
            try:
                if cover.winfo_exists():cover.destroy()
            except tk.TclError:pass
        owner._lock_covers=[];owner._lock_bindings=[]
        for window,state in saved:
            try:
                if window.winfo_exists() and state not in ('withdrawn','iconic'):window.deiconify()
            except tk.TclError:pass
        owner.root.deiconify();owner.root.lift()
        if grab is not None:
            try:
                if grab.winfo_exists() and grab.winfo_toplevel().state() not in ('withdrawn','iconic'):
                    if grab_status=='global':grab.grab_set_global()
                    else:grab.grab_set()
            except tk.TclError:pass
        action=owner._after_unlock;owner._after_unlock=None
        if action is not None and not owner.closed and not owner.closing:owner.root.after_idle(action)
        failures=owner._lock_errors;owner._lock_errors=[]
        if failures:owner.root.after_idle(lambda:owner.show_error(failures[-1]))
    owner._app_lock_panel=UnlockPanel(gate,store,unlocked,owner.close)
    if show:gate.grab_set()
    else:gate.withdraw()
    return True


def lock_on_hide(app):
    owner=lock_owner(app)
    if owner.demo:return
    try:record=LockStore(owner.service.root).load()
    except InvalidLock:record={'lock_on_hide':True}
    if record is not None and record['lock_on_hide']:lock_app(owner,show=False)
