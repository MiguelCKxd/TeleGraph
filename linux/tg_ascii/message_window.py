"""Message › Open in new window (1.4.1).

Each message gets its own window with its full text, freely selectable and
copyable. Photos, videos, audio and files are also opened with the system's
default app (the same private download the in-app viewer uses). With several
messages selected, every message opens in its own window.
"""
import sys
import tkinter as tk
from tkinter import ttk

from .i18n import tr

MAX_WINDOWS = 20
MEDIA_KINDS = ('image', 'photo', 'video', 'gif', 'audio', 'voice', 'video_note', 'file', 'document', 'sticker')


def open_message_windows(app, messages, peer=None):
    peer = app.active if peer is None else peer
    items = [message for message in messages if message is not None][:MAX_WINDOWS]
    for index, message in enumerate(items):
        open_message_window(app, message, peer, offset=index)
    if len(messages) > MAX_WINDOWS:
        app.status.set(tr('Opened the first {count} messages.').format(count=MAX_WINDOWS))


def message_text(message):
    text = message.raw_text if getattr(message, 'raw_text', None) is not None else message.text
    return text or ''


def open_message_window(app, message, peer, offset=0):
    from .timestamps import message_time
    sender = getattr(message, 'sender', '') or ''
    when = message_time(message, app.preferences.values) if getattr(message, 'date', None) is not None else getattr(message, 'time', '')
    window, frame = app.dialog(f'{sender} · {when}' if sender else tr('Message'), '560x460', unique=False)
    try:
        x, y = app.root.winfo_rootx() + 60 + offset * 28, app.root.winfo_rooty() + 60 + offset * 28
        window.geometry(f'+{x}+{y}')
    except tk.TclError:
        pass
    header = ttk.Frame(frame)
    header.pack(fill='x', pady=(0, 6))
    ttk.Label(header, text=app.text_display(sender, True) if sender else tr('Message'), style='Title.TLabel').pack(side='left')
    ttk.Label(header, text=when, style='Muted.TLabel').pack(side='right')
    body = ttk.Frame(frame)
    body.pack(fill='both', expand=True)
    text = tk.Text(body, wrap='word', width=56, height=12, relief='flat', padx=10, pady=8, undo=False)
    bar = ttk.Scrollbar(body, orient='vertical', command=text.yview)
    text.configure(yscrollcommand=bar.set)
    bar.pack(side='right', fill='y')
    text.pack(side='left', fill='both', expand=True)
    content = message_text(message)
    if getattr(message, 'filename', ''):
        content = (content + '\n\n' if content else '') + f'[{message.filename}]'
    text.insert('1.0', content)
    from .line_breaking import apply_text_widget
    apply_text_widget(app, text)
    # Read-only but fully selectable: block edits, keep selection/copy/navigation.
    modifier = 'Command' if sys.platform == 'darwin' else 'Control'

    def guard(event):
        if event.keysym in ('Left', 'Right', 'Up', 'Down', 'Home', 'End', 'Prior', 'Next', 'Shift_L', 'Shift_R'):
            return None
        if event.state & (0x8 if sys.platform == 'darwin' else 0x4) and event.keysym.lower() in ('c', 'a'):
            return None
        return 'break'
    text.bind('<Key>', guard)
    for sequence in ('<<Paste>>', '<<Cut>>', '<<Clear>>', '<<PasteSelection>>'):
        text.bind(sequence, lambda _: 'break')
    text.bind(f'<{modifier}-a>', lambda _: (text.tag_add('sel', '1.0', 'end-1c'), 'break')[1])

    def copy_all():
        app.root.clipboard_clear()
        app.root.clipboard_append(text.get('1.0', 'end-1c'))
        app.status.set(tr('Copied.'))
    buttons = ttk.Frame(frame)
    buttons.pack(fill='x', pady=(8, 0))
    ttk.Button(buttons, text=tr('Copy text'), command=copy_all).pack(side='left')
    has_media = bool(getattr(message, 'media', None)) and getattr(message, 'media_kind', '') in MEDIA_KINDS
    if has_media and not app.demo:
        open_media = lambda: app.open_message_natively(message, peer)
        ttk.Button(buttons, text=tr('Open with system app'), command=open_media).pack(side='left', padx=6)
        open_media()
    ttk.Button(buttons, text=tr('Close'), command=window.destroy).pack(side='right')
    text.focus_set()
    return window
