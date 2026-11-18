"""Actual Tk fixtures for invitation revalidation and notification journal."""
import sys,time,json,tkinter as tk
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from verify_channel_calls_ui import Worker
from tg_ascii.desktop_conference import open_invitation
from tg_ascii.notification_history import NotificationHistory,open_history
from tg_ascii.i18n import set_language

def main():
    set_language('en');root=tk.Tk();root.withdraw();report={'success':False,'checks':[]}
    def dialog(title,size):
        window=tk.Toplevel(root);window.title(title);window.geometry(size);frame=tk.Frame(window);frame.pack(fill='both',expand=True);return window,frame
    app=NS(root=root,demo=False,closing=False,active=41,ui_account='fixture',_app_locked=False,
        preferences=NS(values={'show_seconds':True,'advanced_features':{'calls':True}}),service=NS(backend=object()),
        worker=Worker(root),dialog=dialog,start_group_call=Mock())
    def pump():
        until=time.monotonic()+.1
        while time.monotonic()<until:root.update();time.sleep(.002)
    def windows():return [w for w in root.winfo_children() if isinstance(w,tk.Toplevel)]
    def widgets(w):
        for x in w.winfo_children():yield x;yield from widgets(x)
    def buttons(w):return {str(x.cget('text')):x for x in widgets(w) if x.winfo_class()=='TButton'}
    active=dict(title='Public call fixture',count=3,participants=['Public fixture'],joinable=True,video=False,state='active')
    ended={**active,'joinable':False,'state':'missed'}
    try:
        with patch('tg_ascii.desktop_conference.invitation',new=AsyncMock(side_effect=[active,ended])) as fetch:
            open_invitation(app,41,90);pump();window=windows()[-1]
            assert 'Join call' in buttons(window);buttons(window)['Join call'].invoke();pump()
            assert fetch.await_count==2;app.start_group_call.assert_not_called();assert 'Join call' not in buttons(window)
            report['checks'].append('expired invitation is rechecked before join; no capture starts')
            window.destroy()
        with patch('tg_ascii.desktop_conference.invitation',new=AsyncMock(return_value=active)):
            open_invitation(app,41,90);pump();window=windows()[-1];app._app_locked=True
            buttons(window)['Join call'].invoke();pump();app.start_group_call.assert_not_called();app._app_locked=False;window.destroy()
            report['checks'].append('locked app cannot accept an invitation')
        app.notification_history=NotificationHistory();app.notification_history.record('submitted','push','public fixture')
        open_history(app);pump();window=windows()[-1];trees=[x for x in widgets(window) if x.winfo_class()=='Treeview']
        assert len(trees[0].get_children())==1
        values=trees[0].item(trees[0].get_children()[0],'values');assert values[1]=='Submitted to system' and values[2]=='push'
        window.geometry('360x260');pump();assert buttons(window)['Refresh'].winfo_ismapped()
        report['checks'].append('journal shows redacted metadata and remains refreshable at small size')
        report['success']=True
    except Exception as error:
        import traceback
        report['error']=type(error).__name__;report['trace']=[[Path(x.filename).name,x.name,x.lineno] for x in traceback.extract_tb(error.__traceback__)]
    finally:root.destroy()
    print(json.dumps(report,indent=2));return report['success']
if __name__=='__main__':raise SystemExit(0 if main() else 1)
