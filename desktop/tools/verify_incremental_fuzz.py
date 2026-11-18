from dataclasses import replace
import argparse
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import time
import tkinter as tk

parser=argparse.ArgumentParser(description='Compare250 native incremental renders against complete renders with isolated demo data.')
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
temporary = tempfile.TemporaryDirectory(prefix='tg-render-fuzz-')
os.environ['TG_ASCII_DATA_DIR'] = temporary.name
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tg_ascii.backend import Message
from tg_ascii.desktop import Desktop
from telethon import types

root = tk.Tk()
root.withdraw()
app = Desktop(root, demo=True)
errors = []
root.report_callback_exception = lambda k,e,t:errors.append(repr(e))
app.show_error = lambda error:errors.append(repr(error))
deadline = time.monotonic()+10
while (not app.chats or app.busy) and time.monotonic()<deadline:
    root.update()
    time.sleep(.005)
app.preferences.values.update(bubbles=False, animated_emoji=False, inline_media=False)
app.active = 1
rng = random.Random(701)
native = app.render_plain_history

def snapshot():
    history = app.history
    ranges = {tag:tuple(str(x) for x in history.tag_ranges(tag)) for tag in history.tag_names()
              if tag.startswith(('msg_', 'sender_profile_')) or tag in ('sender', 'outgoing')}
    links = sorted(tuple(str(x) for x in history.tag_ranges(tag)) for tag in history.tag_names()
                   if tag.startswith('link_') and history.tag_ranges(tag))
    marks = {str(mark):str(history.index(mark)) for mark in history.mark_names() if mark.startswith('message_')}
    return {'text':history.get('1.0','end'), 'ranges':ranges, 'links':links, 'marks':marks}

report = {'cases':0, 'differences':[], 'callback_errors':errors}
try:
    for case in range(250):
        old = [Message(i, 'Name '+str(i), 'A 😀 https://example.com/'+str(i)+'\ntext', '12:00',
                       outgoing=bool(i%2), read=bool(i%3)) for i in range(1,16)]
        app.preferences.values['advanced_features']['links']=bool(case%2)
        if case%3:
            for message in old:
                message.entities=(types.MessageEntityTextUrl(0,len(message.text.encode('utf-16-le'))//2,'https://explicit.example'),)
        app._plain_render_state = None
        app.messages = old
        app.render_messages(False)
        updated = old[:]
        action = case%7
        if action==0:
            updated = updated[rng.randrange(1,15):]
        elif action==1:
            updated.pop(rng.randrange(len(updated)))
        elif action==2:
            at = rng.randrange(len(updated))
            updated[at] = replace(updated[at], text='new https://b.example 😀', sender='Other')
        elif action==3:
            updated.append(Message(20, 'More', 'append', '12:05'))
        elif action==4:
            updated.insert(0, Message(0, 'More', 'prepend', '11:59'))
        elif action==5:
            rng.shuffle(updated)
        else:
            at = rng.randrange(len(updated))
            updated[at] = replace(updated[at], read=not updated[at].read)
        app.messages = updated
        app.render_messages(False)
        incremental = snapshot()
        app.render_plain_history = lambda follow:False
        app.render_messages(False)
        reference = snapshot()
        app.render_plain_history = native
        report['cases'] += 1
        if incremental != reference:
            report['differences'].append({'case':case, 'action':action,
                'components':{key:{'incremental':value, 'full':reference[key]}
                              for key,value in incremental.items() if value!=reference[key]}})
            if len(report['differences']) >= 7:
                break
finally:
    app.close()
    deadline = time.monotonic()+10
    while not app.closed and time.monotonic()<deadline:
        root.update()
        time.sleep(.005)
    app.worker.thread.join(3)
    report['worker_stopped'] = not app.worker.thread.is_alive()
    temporary.cleanup()
    args.output.write_text(json.dumps(report, indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report, indent=2))
    if report['differences'] or errors or not report['worker_stopped']:raise SystemExit(1)
