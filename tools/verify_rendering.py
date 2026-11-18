"""Native retained-rendering regressions with isolated demo data only."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
import tkinter as tk

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tg_ascii.backend import Message
from tg_ascii.desktop import Desktop
from telethon import types


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result={'success':False,'platform':sys.platform}
    with tempfile.TemporaryDirectory(prefix='tg-rendering-isolated-') as folder:
        os.environ['TG_ASCII_DATA_DIR']=folder
        root=tk.Tk();app=Desktop(root,demo=True);failures=[]
        root.report_callback_exception=lambda kind,exc,trace:failures.append(repr(exc))
        app.show_error=lambda exc:failures.append(repr(exc))
        def spin(predicate,timeout=10):
            deadline=time.monotonic()+timeout
            while not predicate() and time.monotonic()<deadline:
                root.update();time.sleep(.005)
            assert predicate(), 'Native rendering timed out'
        try:
            spin(lambda:bool(app.chats) and not app.busy)
            app.preferences.values.update(bubbles=False,animated_emoji=False,inline_media=False)
            app.active=1
            initial=[Message(i,'Sender',f'Line {i} 👋 https://example.com/{i}\nsecond line','12:00',outgoing=i%2==0) for i in range(1,61)]
            for message in initial:
                url=f'https://example.com/{message.id}'
                offset=len(message.text[:message.text.index(url)].encode('utf-16-le'))//2
                message.entities=(types.MessageEntityUrl(offset,len(url)),types.MessageEntityBold(0,4))
            def snapshot():
                history=app.history
                links=sorted(tuple(map(str,history.tag_ranges(tag))) for tag in history.tag_names() if tag.startswith('link_') and history.tag_ranges(tag))
                marks={m.id:str(history.index(f'message_{m.id}')) for m in app.messages}
                return history.get('1.0','end-1c'),links,marks
            cases={
                'edit_last':lambda values:values[:-1]+[replace(values[-1],text='edited 👩🏽‍💻\nhttps://example.com/new')],
                'append':lambda values:values+[Message(61,'Other','new tail https://example.org','12:01')],
                'trim_and_append':lambda values:values[5:]+[Message(61,'Other','tail','12:01')],
                'delete_middle':lambda values:values[:20]+values[21:],
                'read_receipts':lambda values:[replace(m,read=True) for m in values],
                'prepend_history':lambda values:[Message(0,'First','older','11:59')]+values,
            }
            for name,change in cases.items():
                app.messages=list(initial);app._plain_render_state=None;app.render_messages(False)
                first_links=tuple(app._plain_render_state['nodes'][0][2])
                app.messages=change(list(initial));app.render_messages(False);root.update_idletasks()
                cached=snapshot()
                if name in ('edit_last','append','delete_middle'):
                    assert tuple(app._plain_render_state['nodes'][0][2])==first_links,name+' rebuilt unchanged prefix'
                retained=app.render_plain_history
                app.render_plain_history=lambda _:False
                try:app.render_messages(False)
                finally:app.render_plain_history=retained
                fresh=snapshot()
                if cached!=fresh:
                    result['difference']={str(i):{'cached':str(a)[-500:],'full':str(b)[-500:]} for i,(a,b) in enumerate(zip(cached,fresh)) if a!=b}
                assert cached==fresh,name+' differs from the complete renderer'
            result['classic_equivalent_cases']=list(cases)
            app.preferences.values['bubbles']=True
            app.messages=list(initial[:20]);app.render_messages(False);root.update_idletasks()
            canvas=app.bubble_view
            # Switching from Text changes the canvas geometry once it is mapped.
            app.render_messages(False);root.update_idletasks()
            first=canvas.find_withtag('message:1');following=canvas.find_withtag('message:2')
            old_start=canvas.locations[2]
            app.messages[0]=replace(app.messages[0],text='expanded\n'*20)
            app.render_messages(False);root.update_idletasks()
            assert canvas.find_withtag('message:1')!=first,'changed message retained stale items'
            assert canvas.find_withtag('message:2')==following,'unchanged message was recreated'
            assert canvas.locations[2]>old_start,'changed height did not move following items'
            result['unchanged_bubble_items_retained']=True
            result['changed_height_moves_following_items']=True
            app.messages[1]=replace(app.messages[1],reply_to_id=1)
            app.render_messages(False);before=canvas.find_withtag('message:2')
            app.messages[0]=replace(app.messages[0],text='updated quote')
            app.render_messages(False)
            assert canvas.find_withtag('message:2')!=before
            result['quoted_message_invalidates_reply']=True
            from PIL import Image
            wallpaper=Path(folder)/'wallpaper.png'
            Image.new('RGB',(120,90),'#143820').save(wallpaper)
            app.wallpaper_path=wallpaper
            app.render_messages(False)
            spin(lambda:bool(canvas.find_withtag('wallpaper')) or bool(canvas.find_withtag('interface_background')))
            old_bottom=canvas.find_all()[0]
            app.messages[-1]=replace(app.messages[-1],text='edited with wallpaper')
            app.render_messages(False);root.update_idletasks()
            assert canvas.find_all()[0]==old_bottom,'message background went below wallpaper'
            result['wallpaper_stays_below_messages']=True
            app.wallpaper_path=None
            app.messages=app.messages[5:]
            app.render_messages(False)
            assert not canvas.find_withtag('message:1')
            assert set(canvas._nodes)=={m.id for m in app.messages}
            before=(len(root.tk.call('info','commands')),len(canvas.find_all()))
            for _ in range(25):app.render_messages(False)
            root.update_idletasks()
            after=(len(root.tk.call('info','commands')),len(canvas.find_all()))
            assert after[1]==before[1] and after[0]<=before[0],(before,after)
            result['stable_commands_and_items']=True
            result['callback_errors']=failures
            assert not failures,failures
            result['success']=True
        except Exception as exc:
            result['error']=repr(exc)
            result['traceback']=traceback.format_exc()
        finally:
            app.busy=False;app.close()
            spin(lambda:app.closed)
            app.worker.thread.join(timeout=3)
        args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result,indent=2))
        if not result['success']:raise SystemExit(1)


if __name__=='__main__':main()
