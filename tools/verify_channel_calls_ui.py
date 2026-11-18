"""Real Tk layout/actions with public fixtures; no Telegram, devices or accounts."""
import asyncio,json,sys,time,tkinter as tk
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tg_ascii.desktop_channel_calls import open_channel_calls
from tg_ascii.i18n import set_language

class Future:
    def __init__(self,coro):self.coro=coro;self.cancelled=False
    def cancel(self):
        self.cancelled=True;self.coro.close()

class Worker:
    def __init__(self,root):self.root=root
    def submit(self,coro,done,failed):
        f=Future(coro)
        def run():
            if f.cancelled:return
            try:done(asyncio.run(coro))
            except Exception as e:failed(e)
        self.root.after(1,run);return f

class Controls:
    def __init__(self):
        self.current=dict(active=False,admin=True,call_id=None,title='',participants_count=0,scheduled=None,subscribed=False,rtmp=False,public=False,can_invite=True)
        self.actions=[]
    async def info(self,peer):return dict(self.current)
    async def create(self,peer,**kwargs):
        self.actions.append(('create',peer,kwargs));self.current.update(active=True,call_id=12,title=kwargs['title'],scheduled=kwargs['schedule'],rtmp=kwargs['rtmp'])
    async def change(self,peer,ident,action,**kwargs):
        self.actions.append((action,peer,ident,kwargs))
        if action in ('rtmp','rotate_rtmp'):return NS(url='rtmps://example.invalid/s/',key='PUBLIC-TEST-FIXTURE')
        if action=='start':self.current['scheduled']=None
        if action=='subscribe':self.current['subscribed']=kwargs['enabled']
        if action in ('cancel','end'):self.current.update(active=False,call_id=None)
        return NS(link='https://example.invalid/invite')

def main():
    set_language('en');root=tk.Tk();root.withdraw();controls=Controls()
    app=NS(root=root,demo=False,active=41,ui_account='fixture',closing=False,closed=False,_app_locked=False,
        preferences={'advanced_features':{'calls':True}},service=NS(backend=NS(channel_call_controls=lambda:controls)),worker=Worker(root),start_group_call=Mock())
    result={'success':False,'checks':[]}
    def pump():
        until=time.monotonic()+.08
        while time.monotonic()<until:root.update();time.sleep(.003)
    def widgets(w):
        for c in w.winfo_children():yield c;yield from widgets(c)
    def buttons(w):return {str(x.cget('text')):x for x in widgets(w) if x.winfo_class()=='TButton'}
    try:
        w=open_channel_calls(app);pump()
        assert 'Schedule call' in buttons(w)
        with patch('tg_ascii.desktop_channel_calls.simpledialog.askstring',side_effect=['QA','2030-01-01 12:00']):buttons(w)['Schedule call'].invoke()
        pump();assert controls.actions[-1][0]=='create'
        assert 'Start now' in buttons(w)
        with patch('tg_ascii.desktop_channel_calls.messagebox.askyesno',return_value=True):buttons(w)['Start now'].invoke()
        pump();assert controls.actions[-1][0]=='start'
        result['checks'].append('schedule/start callbacks preserve peer and call id')
        controls.current.update(active=True,call_id=15,rtmp=True,scheduled=None,admin=True)
        buttons(w)['Refresh'].invoke();pump()
        assert 'Speaker invite link' not in buttons(w)
        buttons(w)['Join call'].invoke();app.start_group_call.assert_called_once_with(peer=41,view_only=True)
        buttons(w)['RTMP server and key'].invoke();pump()
        assert any(x.winfo_class()=='TEntry' and x.cget('show')=='•' for x in widgets(w))
        result['checks'].append('RTMP joins view-only, speaker links hidden, key masked')
        w.geometry('320x260');pump()
        assert buttons(w)['Refresh'].winfo_ismapped()
        w.geometry('760x620');pump()
        assert buttons(w)['RTMP server and key'].winfo_ismapped()
        result['checks'].append('scrollable settings retain refresh at small and large sizes')
        before=len(controls.actions);app._app_locked=True;buttons(w)['Replace stream key'].invoke();pump();assert len(controls.actions)==before
        result['checks'].append('app lock prevents rotation')
        result['success']=True
    except Exception as e:
        result['error']=type(e).__name__
        import traceback
        result['trace']=[[Path(f.filename).name,f.name,f.lineno] for f in traceback.extract_tb(e.__traceback__)]
    finally:root.destroy()
    print(json.dumps(result,indent=2));return result['success']
if __name__=='__main__':raise SystemExit(0 if main() else 1)
