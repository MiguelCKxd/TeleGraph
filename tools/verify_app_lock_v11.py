"""Native lock QA with synthetic accounts and simulated OS authentication only."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk
from unittest.mock import AsyncMock,Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tg_ascii import app_lock,app_dialogs
from tg_ascii.accounts import Accounts
from tg_ascii.desktop import Desktop,run_desktop
from tg_ascii.interface_windows import open_linked_app_window
from tg_ascii.notifications import NotificationCenter

PASSWORD='Synthetic-only-password-11'


def pump(root,condition,errors,timeout=10):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        root.update()
        if errors:raise AssertionError(errors)
        if condition():return
        time.sleep(.005)
    raise TimeoutError('Synthetic native lock check timed out')


def capture_errors(root,errors):
    root.report_callback_exception=lambda kind,error,trace:errors.append(type(error).__name__+': '+str(error))
    root.tk.createcommand('bgerror',lambda message:errors.append('Tcl: '+str(message)))


def startup_check(directory,result,errors):
    store=app_lock.LockStore(directory);store.save(app_lock.make_record(PASSWORD))
    root=tk.Tk();capture_errors(root,errors)
    constructed=[];state={};instance=Mock(acquired=True)
    watchdog=None
    def close_startup():
        nonlocal watchdog
        if watchdog is not None:
            root.after_cancel(watchdog);watchdog=None
        root.destroy()
    gate=app_lock.startup_gate
    def desktop_started(*args,**kwargs):
        constructed.append('Desktop')
        # Stand-in for the account constructor reached inside Desktop.__init__.
        Accounts(demo=True,root=directory)
        constructed.append('Accounts')
        root.after_idle(close_startup)
    def capture_gate(window,lock,start):
        state['panel']=gate(window,lock,start)
        return state['panel']
    def check_start():
        try:
            assert not constructed
            panel=state['panel'];panel.password.set('incorrect-password');panel.submit.invoke()
            def incorrect_done():
                try:
                    if panel.pending:root.after(10,incorrect_done);return
                    assert not constructed and not panel.closed
                    assert panel.password.get()=='' and panel.attempts==1
                    result['startup_wrong_password_does_not_construct_accounts']=True
                    panel.password.set(PASSWORD);panel.submit.invoke()
                except Exception as error:errors.append(repr(error));close_startup()
            root.after(10,incorrect_done)
        except Exception as error:errors.append(repr(error));close_startup()
    root.after(20,check_start)
    watchdog=root.after(10000,lambda:(errors.append('Startup timeout'),close_startup()))
    with patch('tg_ascii.desktop.tk.Tk',return_value=root),patch('tg_ascii.preferences.data_root',return_value=directory),patch('tg_ascii.instance.InstanceLock',return_value=instance),patch('tg_ascii.desktop.Desktop',side_effect=desktop_started),patch('tg_ascii.app_lock.startup_gate',side_effect=capture_gate),patch('tg_ascii.notifications.clear_locked_notification_history',return_value=Mock()) as clear_notices:
        run_desktop(demo=False)
    assert constructed==['Desktop','Accounts'] and not errors
    assert state['panel'].closed and state['panel'].timer is None
    instance.close.assert_called_once()
    clear_notices.assert_called_once()
    result['startup_correct_password_constructs_accounts_after_unlock']=True
    assert watchdog is None
    result['startup_watchdog_canceled_before_destroy']=True


def windows_check(directory,result,errors):
    root=tk.Tk();app=None;views=[]
    try:
        service=Accounts(demo=True,root=directory)
        app=Desktop(root,demo=True,service=service);capture_errors(root,errors)
        app.show_error=lambda error:errors.append(repr(error))
        pump(root,lambda:app.chats and not app.busy,errors)
        views=[open_linked_app_window(app),open_linked_app_window(app)]
        for view in views:view.show_error=app.show_error
        pump(root,lambda:all(view.chats and not view.busy for view in views),errors)
        for index,view in enumerate((app,*views)):
            view.editor.insert('1.0',f'Synthetic retained draft {index}')
        drafts=[view.editor.get('1.0','end-1c') for view in (app,*views)]
        dialog=tk.Toplevel(root);ttk.Label(dialog,text='Synthetic private profile').pack()
        dialog.geometry('420x260');dialog.deiconify()
        hidden=tk.Toplevel(root);hidden.withdraw()
        try:pump(root,lambda:dialog.winfo_ismapped(),errors)
        except TimeoutError:
            result['prelock_window_states']={str(window):{'state':window.state(),'mapped':bool(window.winfo_ismapped())} for window in (root,*(view.root for view in views),dialog,hidden)}
            raise
        dialog.grab_set()
        prior_map=root.bind_class('Toplevel','<Map>')
        adapter=Mock();center=NotificationCenter(app.show_error);center.adapter=adapter
        app.notification_center=center
        # Focus events can call the live-client presence hook when the guard is
        # exercised. Its replacement remains wholly local to this demo backend.
        service.backend.presence=AsyncMock(return_value=None)
        app.demo=False  # Only the interface guard; the injected Accounts/backend remain demo.
        assert app_lock.lock_app(app)
        panel=app._app_lock_panel
        pump(root,lambda:panel.window.winfo_ismapped(),errors)
        roots=[root,*(view.root for view in views),dialog]
        assert all(window.state()=='withdrawn' for window in roots)
        assert center.locked and adapter.set_locked.call_args.args==(True,)
        result['root_linked_and_existing_dialogs_hidden']=True
        grabbed=root.grab_current()
        assert grabbed in (None,panel.window),f'Hidden modal retained grab: {grabbed}'
        result['existing_modal_grab_does_not_block_unlock']=True
        reply=Mock();center.show('Private sender','Private text','synthetic',reply=reply)
        notification=adapter.show.call_args.args
        assert notification[0]=='TG-ASCII' and notification[1]!='Private text' and notification[4] is None
        result['locked_notifications_redacted_and_reply_removed']=True
        # Native prompt wrappers must not forward late callback content.
        with patch.object(app_dialogs._messagebox,'showerror') as native_error,patch.object(app_dialogs._filedialog,'asksaveasfilename') as native_file:
            assert app_dialogs.messagebox.showerror('Private','text',parent=root) is None
            assert app_dialogs.filedialog.asksaveasfilename(parent=views[0].root)==''
            native_error.assert_not_called();native_file.assert_not_called()
        assert app_dialogs.popup_menu(root,[('Private action',Mock())]) is None
        result['locked_native_dialogs_and_menus_suppressed']=True
        # Existing windows may be activated from taskbar; new Toplevels can
        # originate in a media callback rather than the common dialog factory.
        roots[1].deiconify();pump(root,lambda:roots[1].state()=='withdrawn',errors)
        late=tk.Toplevel(root);ttk.Label(late,text='Late synthetic private media').pack();late.grab_set()
        pump(root,lambda:late.state()=='withdrawn',errors)
        assert any(window is late for window,_ in app._locked_windows)
        assert root.grab_current() in (None,panel.window),'A late hidden window retained a modal grab'
        result['taskbar_reopen_and_late_toplevel_concealed']=True
        panel.password.set('wrong-password');panel.submit.invoke()
        pump(root,lambda:not panel.pending,errors)
        assert app_lock.is_locked(app) and all(window.state()=='withdrawn' for window in roots)
        assert panel.password.get()==''
        panel.password.set(PASSWORD);panel.submit.invoke()
        pump(root,lambda:not app_lock.is_locked(app),errors)
        pump(root,lambda:all(window.winfo_ismapped() for window in [*roots,late]),errors)
        assert hidden.state()=='withdrawn'
        assert [view.editor.get('1.0','end-1c') for view in (app,*views)]==drafts
        assert not center.locked and adapter.set_locked.call_args.args==(False,)
        assert not app._lock_covers and not app._lock_bindings
        assert root.bind_class('Toplevel','<Map>')==prior_map
        assert panel.closed and panel.timer is None
        result['unlock_restores_windows_drafts_and_original_map_binding']=True
        for window in (dialog,late,hidden):window.destroy()
        # No stale Map bindings or callbacks may accumulate over another cycle.
        assert app_lock.lock_app(app,show=False)
        second=app._app_lock_panel
        assert second.window.state()=='withdrawn'
        assert app_lock.show_locked(views[0])
        pump(root,lambda:second.window.winfo_ismapped(),errors)
        second.password.set(PASSWORD);second.submit.invoke()
        pump(root,lambda:not app_lock.is_locked(app),errors)
        assert root.bind_class('Toplevel','<Map>')==prior_map and second.timer is None
        result['second_lock_cycle_cleans_callbacks']=True
        closed_dialog_check(app,result,errors)
        settings_check(app,directory,result,errors)
        cancellation_check(root,directory,result,errors)
    finally:
        if app is not None:
            app.demo=True;app.busy=False
            for view in views:view.busy=False
            app.close()
            deadline=time.monotonic()+8
            while not app.closed and time.monotonic()<deadline:
                root.update();time.sleep(.005)
            if not app.closed:
                app.worker.stop();root.destroy()
            app.worker.thread.join(3)
            result['worker_stopped']=not app.worker.thread.is_alive()
        elif root.winfo_exists():root.destroy()


def closed_dialog_check(app,result,errors):
    """Destroy before idle: deferred styling must never call a deleted command."""
    for factory in (lambda:app.dialog('Synthetic immediate close'),
                    lambda:app_dialogs.window(app.root,'Synthetic immediate close'),
                    lambda:app_dialogs.popover(app.root,'Synthetic immediate close')):
        window,body=factory()
        ttk.Label(body,text='Synthetic content').pack()
        window.destroy()
    app.root.update()
    assert not errors,errors
    result['immediately_closed_dialogs_leave_no_tcl_callbacks']=True


def settings_check(app,directory,result,errors):
    """Actual settings entries/buttons, synthetic data and no OS auth prompt."""
    root=app.root;store=app_lock.LockStore(directory)
    store.disable(PASSWORD)
    original=app.dialog
    def open_settings(count):
        opened=[]
        def dialog(*args,**kwargs):
            value=original(*args,**kwargs);opened.append(value);return value
        with patch.object(app,'dialog',side_effect=dialog):app_lock.open_lock_settings(app)
        window,body=opened[0]
        entries=[widget for widget in body.winfo_children() if isinstance(widget,ttk.Entry)]
        assert len(entries)==count,(len(entries),count)
        labels=[widget.cget('text') for widget in body.winfo_children() if isinstance(widget,ttk.Label)]
        assert (app_lock.tr('Current app password') in labels)==(count==3)
        return window,body,entries
    def button(body,label):
        return next(widget for widget in body.winfo_children()
                    if isinstance(widget,ttk.Button) and widget.cget('text')==app_lock.tr(label))
    def enter(entry,text):
        entry.delete(0,'end');entry.insert(0,text)
    def save(window,body,label='Change app password'):
        button(body,label).invoke();pump(root,lambda:not window.winfo_exists(),errors)
    def has_error(body,label):
        return any(isinstance(widget,ttk.Label) and widget.cget('text')==app_lock.tr(label)
                   for widget in body.winfo_children())
    with patch('tg_ascii.native_auth.availability',return_value=(False,'Synthetic availability')):
        window,body,entries=open_settings(2)
        enter(entries[0],'7');enter(entries[1],'7')
        save(window,body,'Enable app lock')
        assert app_lock.verify_password(store.load(),'7')
        result['settings_creation_two_fields_and_one_digit_pin']=True

        window,body,entries=open_settings(3)
        enter(entries[0],'7')  # New fields intentionally untouched.
        hidden=next(widget for widget in body.winfo_children()
                    if isinstance(widget,ttk.Checkbutton) and widget.cget('text')==app_lock.tr('Lock when hiding the app'))
        hidden.invoke();save(window,body)
        record=store.load()
        assert app_lock.verify_password(record,'7') and not record['lock_on_hide']
        assert not app_lock.verify_password(record,'')
        result['settings_untouched_fields_keep_password']=True

        password='  '+('漢🙂'*1100)+' e\u0301 !  '
        window,body,entries=open_settings(3)
        for entry,value in zip(entries,('7',password,password)):enter(entry,value)
        save(window,body)
        assert app_lock.verify_password(store.load(),password)
        assert not app_lock.verify_password(store.load(),password.strip())
        result['settings_long_unicode_password_preserves_spaces']=True

        window,body,entries=open_settings(3);before=store.load()
        for entry,value in zip(entries,('wrong current','9','9')):enter(entry,value)
        button(body,'Change app password').invoke()
        pump(root,lambda:has_error(body,'Incorrect app password.'),errors)
        assert store.load()==before and window.winfo_exists()
        window.destroy();result['settings_change_still_requires_current_password']=True

        window,body,entries=open_settings(3)
        enter(entries[0],password)
        for entry in entries[1:]:
            enter(entry,'explicitly cleared');entry.delete(0,'end')
        save(window,body)
        assert app_lock.verify_password(store.load(),'')
        assert not app_lock.verify_password(store.load(),password)
        result['settings_edited_empty_fields_select_empty_password']=True

        window,body,entries=open_settings(3)  # Empty password still has a record.
        enter(entries[1],'9');enter(entries[2],'9');save(window,body)
        assert app_lock.verify_password(store.load(),'9')
        result['settings_existing_empty_password_has_current_field']=True

        window,body,entries=open_settings(3);before=store.load()
        enter(entries[0],'wrong');button(body,'Disable app lock').invoke()
        pump(root,lambda:has_error(body,'Incorrect app password.'),errors)
        assert store.load()==before
        enter(entries[0],'9');save(window,body,'Disable app lock')
        assert store.load() is None
        result['settings_disable_still_requires_current_password']=True

        window,body,entries=open_settings(2)
        save(window,body,'Enable app lock')  # Empty on first creation is valid.
        assert app_lock.verify_password(store.load(),'')
        result['settings_initial_empty_password_allowed']=True
        unlocked=Mock();prompt=tk.Toplevel(root)
        panel=app_lock.UnlockPanel(prompt,store,unlocked,prompt.destroy)
        panel.submit.invoke();pump(root,lambda:panel.closed,errors)
        unlocked.assert_called_once();assert panel.timer is None
        prompt.destroy();result['unlock_accepts_exact_empty_password']=True
        window,body,entries=open_settings(3)
        save(window,body,'Disable app lock')
        assert store.load() is None


def cancellation_check(root,directory,result,errors):
    store=app_lock.LockStore(directory);store.save(app_lock.make_record(PASSWORD,biometric=True))
    window=tk.Toplevel(root);unlocked=Mock();started=threading.Event();finished=threading.Event()
    def fake_auth(reason,hwnd,cancel):
        started.set();cancel.wait(3);finished.set();return True  # Deliberately stale positive reply.
    with patch('tg_ascii.native_auth.availability',return_value=(True,'Synthetic biometrics')),patch('tg_ascii.native_auth.authenticate',side_effect=fake_auth):
        panel=app_lock.UnlockPanel(window,store,unlocked,window.destroy)
        panel.attempt(True);pump(root,started.is_set,errors)
        window.destroy();pump(root,finished.is_set,errors)
        assert panel.closed and panel.cancel.is_set() and panel.timer is None
        # Deliver the queued late result after the window has already gone.
        panel.poll();unlocked.assert_not_called()
    result['closing_prompt_cancels_worker_and_rejects_late_success']=True


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path)
    args=parser.parse_args();errors=[];started=time.monotonic()
    result={'success':False,'synthetic_only':True,'platform':sys.platform,'os_authentication_prompts':False}
    try:
        with tempfile.TemporaryDirectory(prefix='tg-lock-native-') as folder:
            directory=Path(folder)
            startup_check(directory,result,errors)
            windows_check(directory,result,errors)
        result['success']=not errors and result.get('worker_stopped',False)
    except Exception as error:
        import traceback
        result.update(error=type(error).__name__,detail=str(error),traceback=traceback.format_exc())
    result.update(callback_errors=errors,seconds=round(time.monotonic()-started,3))
    text=json.dumps(result,indent=2,ensure_ascii=True)+'\n'
    if args.output:args.output.write_text(text,encoding='utf-8')
    print(text);return 0 if result['success'] else 1


if __name__=='__main__':raise SystemExit(main())
