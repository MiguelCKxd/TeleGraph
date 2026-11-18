"""Native capability-driven controls and menus with synthetic data only."""
import argparse
from datetime import UTC,datetime
import json
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from telethon import types as t
from tg_ascii.backend import Chat
from tg_ascii.desktop_actions import DesktopActions
from tg_ascii.i18n import tr


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    report={'success':False,'synthetic_only':True,'platform':sys.platform,'callback_errors':[],'cases':[]}
    root=tk.Tk();root.title('TG-ASCII · Synthetic capability test')
    root.report_callback_exception=lambda kind,error,trace:report['callback_errors'].append(repr(error))
    began=time.monotonic()
    try:
        app=DesktopActions();app.root=root;app.demo=app.busy=False;app.ui_account='synthetic-a';app.closed=app.closing=False
        app.preferences=NS(values={'advanced_features':dict.fromkeys(('polls','checklists','contacts','locations','articles','stars_gifts'),True)})
        backend=NS(account_profile=NS(user_id=99,premium=False),client=Mock(side_effect=AssertionError('No RPC from menus')))
        app.service=NS(backend=backend);app.composer_controls=ttk.Frame(root);app.composer_controls.pack()
        for name in ('attach_button','send_button','advanced_button','sticker_button','custom_emoji_button'):
            widget=ttk.Button(app.composer_controls,text=name);widget.pack(side='left');setattr(app,name,widget)
        def scenario(label,entity,expected,send=True):
            peer=entity.id if isinstance(entity,t.User) else -entity.id if isinstance(entity,t.Chat) else -1000000000000-entity.id
            app.active=peer;app.chats=[Chat(peer,label,entity=entity)]
            app.update_chat_capabilities();root.update()
            with patch('tg_ascii.desktop_advanced.popup_menu') as menu:
                app.open_advanced_menu()
            labels=[item[0] for item in menu.call_args.args[1]] if menu.called else []
            assert (tr('Poll / quiz') in labels)==expected,(label,labels)
            assert bool(app.send_button.winfo_manager())==send,label
            backend.client.assert_not_called()
            report['cases'].append(label)
        scenario('private human hides polls',t.User(1),False)
        scenario('bot can request polls',t.User(2,bot=True),True)
        group=t.Chat(3,'Synthetic',t.ChatPhotoEmpty(),2,datetime.now(UTC),1)
        scenario('group can create polls',group,True)
        group.default_banned_rights=t.ChatBannedRights(None,send_polls=True)
        scenario('group poll restriction updates menu',group,False)
        channel=t.Channel(4,'Synthetic',t.ChatPhotoEmpty(),datetime.now(UTC),broadcast=True)
        scenario('subscriber hides publish controls',channel,False,False)
        channel.admin_rights=t.ChatAdminRights(post_messages=True)
        scenario('channel publisher gets publish controls back',channel,True)
        scenario('saved messages supported',t.User(99,is_self=True),True)
        scenario('deleted account hides sending',t.User(5,deleted=True),False,False)
        # User layouts use place and disable FlowFrame's automatic arrangement.
        # Restoring permission must restore the exact user geometry, not pack it.
        from tg_ascii.scrolling import FlowFrame
        manual=FlowFrame(root);manual._manual_layout=True;manual.configure(width=500,height=120);manual.pack()
        placed=ttk.Button(manual,text='Synthetic manual attachment')
        placed.place(relx=.2,rely=.15,relwidth=.35,relheight=.4,x=3,y=5,width=-6,height=-10)
        original=placed.place_info()
        app.attach_button=placed
        scenario('manual layout permitted initially',t.User(1),False)
        scenario('manual layout hidden for subscriber',channel.__class__(4,'Synthetic',t.ChatPhotoEmpty(),datetime.now(UTC),broadcast=True),False,False)
        assert placed.winfo_manager()==''
        scenario('manual layout restored after permission change',t.User(1),False)
        assert placed.winfo_manager()=='place' and placed.place_info()==original
        report['manual_place_geometry_restored']=True
        from tg_ascii.interface_layout import LayoutRuntime
        LayoutRuntime.guard_geometry(placed,{'rect':[.2,.15,.35,.4]})
        scenario('guarded layout hidden on permission loss',channel.__class__(4,'Synthetic',t.ChatPhotoEmpty(),datetime.now(UTC),broadcast=True),False,False)
        scenario('guarded layout restored using original geometry method',t.User(1),False)
        assert placed.winfo_manager()=='place' and placed.place_info()==original
        scenario('guarded button becomes unavailable again',channel.__class__(4,'Synthetic',t.ChatPhotoEmpty(),datetime.now(UTC),broadcast=True),False,False)
        placed._layout_hidden=True
        scenario('user hidden button stays hidden on permission recovery',t.User(1),False)
        assert placed.winfo_manager()==''
        report['custom_layout_guard_and_user_hidden_preserved']=True
        # Simulate the same widgets after an account switch, including Premium.
        app.ui_account='synthetic-b';app.service=NS(backend=NS(account_profile=NS(user_id=101,premium=True)))
        app.active=6;app.chats=[Chat(6,'Synthetic peer',entity=t.User(6))]
        with patch('tg_ascii.desktop_advanced.popup_menu') as menu:app.open_advanced_menu()
        assert tr('Checklist') in [item[0] for item in menu.call_args.args[1]]
        app.service.backend.account_profile.premium=False
        with patch('tg_ascii.desktop_advanced.popup_menu') as menu:app.open_advanced_menu()
        assert tr('Checklist') not in [item[0] for item in menu.call_args.args[1]]
        report['cases'].append('account switch and Premium revocation change actions')
        assert not report['callback_errors']
        report.update(success=True,zero_menu_rpcs=True)
    except Exception as error:
        report['error']=repr(error)
    finally:
        root.destroy();report['elapsed_seconds']=round(time.monotonic()-began,4)
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
    return 0 if report['success'] else 1


if __name__=='__main__':raise SystemExit(main())
