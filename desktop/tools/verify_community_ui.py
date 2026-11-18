"""Tk integration fixtures; no accounts, network or permission mutations."""
import asyncio,json,sys,time,tkinter as tk
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from telethon import types as t
from tg_ascii.desktop_community import create_community,member_editor,manage_members,discussion_settings
from tg_ascii.i18n import set_language
from verify_channel_calls_ui import Worker

class Backend:
    def __init__(self):self.actions=[]
    async def create_community(self,*args):self.actions.append(('create',args));return NS(id=41)
    async def community_member(self,*args):
        return dict(entity=t.Channel(41,'Fixture',t.ChatPhotoEmpty(),datetime.now(timezone.utc),creator=True,megagroup=True),person=t.User(4,first_name='Public fixture',status=t.UserStatusRecently()),participant=t.ChannelParticipant(4,datetime.now(timezone.utc)),role='Member',can_admin=True,can_ban=True,rights=None,banned=None,fields={'invite_users':'Add members'})
    async def community_admin(self,*args):self.actions.append(('admin',args))
    async def community_restrict(self,*args,**kwargs):self.actions.append(('restrict',args,kwargs))
    async def profile(self,*args):return dict(can_invite=True,is_channel=True)
    async def profile_members(self,*args,**kwargs):
        self.actions.append(('members',args,kwargs));return dict(items=[dict(id=4,name='Public fixture',role='Member',activity_entity=t.User(4,status=t.UserStatusRecently()))],next_offset=1,more=False)
    async def discussion_groups(self,*args):return dict(linked=6,items=[dict(id=7,name='Public fixture',basic=False)])
    async def set_discussion_group(self,*args,**kwargs):self.actions.append(('link',args,kwargs))


def main():
    set_language('en');root=tk.Tk();root.withdraw();backend=Backend();report={'success':False,'checks':[]}
    def dialog(title,size):
        w=tk.Toplevel(root);w.title(title);w.geometry(size);frame=tk.Frame(w);frame.pack(fill='both',expand=True);return w,frame
    app=NS(root=root,demo=False,ui_account='fixture',closing=False,_app_locked=False,service=NS(backend=backend),worker=Worker(root),preferences=NS(values={'show_seconds':False}),dialog=dialog,open_resolved=Mock(),show_contact_profile=Mock())
    def pump():
        until=time.monotonic()+.1
        while time.monotonic()<until:root.update();time.sleep(.003)
    def widgets(w):
        for child in w.winfo_children():yield child;yield from widgets(child)
    def window():return [w for w in root.winfo_children() if isinstance(w,tk.Toplevel)][-1]
    def buttons(w):return {str(c.cget('text')):c for c in widgets(w) if c.winfo_class()=='TButton'}
    def closeall():
        for w in list(root.winfo_children()):w.destroy()
    try:
        create_community(app,True);w=window();entries=[e for e in widgets(w) if e.winfo_class()=='TEntry'];entries[0].insert(0,'Public fixture');buttons(w)['Create'].invoke();pump()
        assert backend.actions[-1][0]=='create' and backend.actions[-1][1][-1] is True;app.open_resolved.assert_called_once()
        report['checks'].append('channel creation uses captured backend and opens the created chat')
        member_editor(app,41,4);w=window();pump();assert 'Ban member' in buttons(w)
        w.geometry('320x280');pump();assert buttons(w)['Refresh'].winfo_ismapped()
        before=len(backend.actions);app._app_locked=True;buttons(w)['Ban member'].invoke();pump();assert len(backend.actions)==before
        app._app_locked=False;closeall();report['checks'].append('member controls scroll and app lock prevents writes')
        manage_members(app,41);w=window();pump();assert backend.actions[-1][0]=='members'
        trees=[c for c in widgets(w) if c.winfo_class()=='Treeview'];assert 'Last seen recently' in trees[0].item('4','text')
        closeall();report['checks'].append('member list shows real presence category')
        discussion_settings(app,41);w=window();pump()
        with patch('tg_ascii.desktop_community.messagebox.askyesno',return_value=True):buttons(w)['Unlink discussion group'].invoke()
        pump();action=next(x for x in reversed(backend.actions) if x[0]=='link');assert action[1]==(41,None) and action[2]['expected_link']==6
        before=len(backend.actions);app.ui_account='different';buttons(w)['Refresh'].invoke();pump();assert len(backend.actions)==before
        report['checks'].append('unlink pins expected relationship and account switch invalidates callbacks');report['success']=True
    except Exception as error:
        import traceback
        report['error']=type(error).__name__;report['trace']=[[Path(x.filename).name,x.name,x.lineno] for x in traceback.extract_tb(error.__traceback__)]
    finally:root.destroy()
    print(json.dumps(report,indent=2));return report['success']
if __name__=='__main__':raise SystemExit(0 if main() else 1)
