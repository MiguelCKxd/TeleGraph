"""Settings › Account › Devices: the Telegram sessions of the account open here.

Shows this device and every other session Telegram reports, ends one or all
the others, chooses when inactive sessions end, and whether each device can
receive calls and secret chats. A tg://login link (copied from a login QR) can
also be pasted to sign another device in with this account.
"""
from . import APP_NAME
from datetime import datetime
import tkinter as tk
from tkinter import ttk

from .app_dialogs import Choice, messagebox, simpledialog
from .devices import TTL_CHOICES, accept_login, end_other_sessions, end_session, list_sessions, set_session_flags, set_session_ttl, login_token
from .i18n import tr
from .timestamps import date_text


def _when(stamp, values):
    return date_text(datetime.fromtimestamp(stamp).astimezone(), values) if stamp else '—'


def _title(item):
    return item['device'] or item['app'] or tr('Devices')


def _detail(item):
    return ' · '.join(part for part in (item['app'], ' '.join(p for p in (item['platform'], item['system']) if p), item['place'], item['ip']) if part)


def open_devices(app):
    if app.demo or app.busy:
        return
    account = app.ui_account
    backend = app.service.backend
    client = getattr(backend, 'client', None)
    if client is None:
        return
    window, body = app.dialog('Devices', '600x640')
    values = getattr(app.preferences, 'values', {})

    def current():
        return window.winfo_exists() and account == app.ui_account

    def reload():
        app.call(list_sessions(client), draw, tr('Loading...'))

    def draw(data):
        if not current():
            return
        for child in body.winfo_children():
            child.destroy()
        sessions = data['sessions']
        mine = [item for item in sessions if item['current']]
        others = [item for item in sessions if not item['current']]
        for heading, items in ((tr('This device'), mine), (tr('Other sessions'), others)):
            ttk.Label(body, text=heading, style='Title.TLabel').pack(anchor='w', pady=(10, 4))
            if not items:
                ttk.Label(body, text=tr('No other sessions.')).pack(anchor='w', pady=4)
            for item in items:
                row = ttk.Frame(body, padding=(0, 6))
                row.pack(fill='x')
                ttk.Label(row, text=_title(item), font=('TkDefaultFont', 0, 'bold')).pack(anchor='w')
                ttk.Label(row, text=_detail(item), wraplength=520, style='Muted.TLabel').pack(anchor='w')
                ttk.Label(row, text=tr('Last active: {time}').format(time=_when(item['active'], values)) + '   ' +
                          tr('Signed in: {time}').format(time=_when(item['created'], values))).pack(anchor='w')
                if item['current']:
                    continue
                flags = ttk.Frame(row)
                flags.pack(anchor='w', pady=2)
                for key, label in (('calls', 'Accept calls'), ('secret_chats', 'Accept secret chats')):
                    variable = tk.BooleanVar(master=window, value=item[key])
                    def toggle(item=item, key=key, variable=variable):
                        app.call(set_session_flags(client, item['hash'], **{key: variable.get()}), lambda _: None, tr('Saving...'),
                                 failure=lambda error: (variable.set(not variable.get()), app.show_error(error)))
                    ttk.Checkbutton(flags, text=tr(label), variable=variable, command=toggle).pack(side='left', padx=(0, 12))
                ttk.Button(row, text=tr('End session'), command=lambda item=item: end(item)).pack(anchor='w', pady=2)
        if others:
            ttk.Button(body, text=tr('End all other sessions'), command=end_all).pack(fill='x', pady=(14, 4))
        ttk.Label(body, text=tr('End inactive sessions after')).pack(anchor='w', pady=(14, 2))
        labels = [tr('{days} days').format(days=days) for days in TTL_CHOICES]
        picker = Choice(body, values=labels)
        if data['ttl_days'] in TTL_CHOICES:
            picker.current(TTL_CHOICES.index(data['ttl_days']))
        picker.pack(anchor='w')
        picker.bind('<<ComboboxSelected>>', lambda _: app.call(set_session_ttl(client, TTL_CHOICES[picker.current()]), lambda _: None, tr('Saving...')))
        ttk.Separator(body).pack(fill='x', pady=14)
        ttk.Label(body, text=tr('Scan the login QR code shown on another device to sign it in with this account.'), wraplength=520).pack(anchor='w')
        ttk.Button(body, text=tr('Paste login link'), command=paste_link).pack(fill='x', pady=6)

    def end(item):
        if not messagebox.askyesno(tr('End session'), _title(item) + '\n\n' + tr('Sign this device out of Telegram?'), parent=window):
            return
        app.call(end_session(client, item['hash']), lambda _: (app.status.set(tr('Session ended.')), reload()), tr('Saving...'))

    def end_all():
        if not messagebox.askyesno(tr('End all other sessions'), tr('Sign out every other device? Only this one stays signed in.'), parent=window):
            return
        app.call(end_other_sessions(client), lambda _: (app.status.set(tr('Session ended.')), reload()), tr('Saving...'))

    def paste_link():
        try:
            text = window.clipboard_get()
        except tk.TclError:
            text = ''
        if login_token(text) is None:
            text = simpledialog.askstring(tr('Devices'), 'tg://login?token=…', parent=window) or ''
        if not text:
            return
        if login_token(text) is None:
            messagebox.showinfo(APP_NAME, tr('This is not a Telegram login code.'), parent=window)
            return
        label = app.service.labels.get(account, account)
        if not messagebox.askyesno(tr('Devices'), tr('Sign in the device showing this code with {account}? Only scan codes from your own devices.').format(account=label), parent=window):
            return
        app.call(accept_login(client, text), lambda _: (app.status.set(tr('Device signed in.')), reload()), tr('Saving...'))

    reload()
    return window
