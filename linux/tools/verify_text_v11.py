"""Native plain/canvas quote and feature-gate checks with synthetic messages."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tg_ascii.backend import Message
from tg_ascii.desktop import Desktop
from tg_ascii.expandable_text import toggle
from tg_ascii.message_tools import formatted_entities


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();failures=[];checks=[]
    with tempfile.TemporaryDirectory(prefix='tg-text-v11-') as directory:
        os.environ['TG_ASCII_DATA_DIR']=directory
        root=tk.Tk();app=Desktop(root,demo=True)
        app.show_error=lambda error:failures.append(str(error))
        root.report_callback_exception=lambda kind,error,trace:failures.append(str(error))
        try:
            deadline=time.monotonic()+10
            while (not app.chats or app.busy) and time.monotonic()<deadline:
                root.update();time.sleep(.01)
            assert app.chats and not app.busy
            text='Before 😀\n'+('Long quoted text. '*40)+'\nAFTER'
            start=text.index('Long');end=text.index('\nAFTER')
            entities=tuple(formatted_entities(text,[(start,end,'collapsed_quote',''),(end+1,len(text),'bold','')]))
            message=Message(900,'Synthetic',text,'12:00',raw_text=text,entities=entities)
            for bubbles in (False,True):
                app.preferences.values['bubbles']=bubbles;app.rebuild_screen();root.update()
                app.active=app.chats[0].id;app.messages=[message]
                app._expanded_quotes={};app.render_messages(False);root.update()
                if not bubbles:
                    rendered=app.history.get('1.0','end')
                    assert len(rendered)<len(text) and 'AFTER' in rendered
                    assert any(str(tag).startswith('quote_toggle_') for tag in app.history.tag_names())
                else:
                    assert app.bubble_view._nodes[900]['height']>0
                    folded=app.bubble_view._nodes[900]['height']
                toggle(app,900,start,(app.ui_account,app.active));root.update()
                if not bubbles:assert 'Long quoted text. '*40 in app.history.get('1.0','end')
                else:assert app.bubble_view._nodes[900]['height']>folded
                assert message.raw_text==text and message.entities==entities
                checks.append('canvas_quotes' if bubbles else 'plain_quotes')
            app.complex_settings();root.update()
            assert app._settings_picker.current()==7
            app._settings_picker.current(0);app._settings_choose();app.complex_settings();root.update()
            assert app._settings_picker.current()==7
            assert app.notebook.index(app.call_page)==1
            checks.append('fixed_complex_settings_navigation_and_call_tab')
            root.geometry('480x480');root.update()
            assert not failures,failures
        finally:
            app.busy=False;app.close()
            deadline=time.monotonic()+5
            while app.worker.thread.is_alive() and time.monotonic()<deadline:
                try:root.update()
                except tk.TclError:break
                time.sleep(.01)
            app.worker.thread.join(timeout=2)
        assert not app.worker.thread.is_alive()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({'success':True,'checks':checks,'errors':failures,'synthetic_only':True},indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
