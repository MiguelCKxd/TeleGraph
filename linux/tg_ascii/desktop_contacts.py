"""Settings › Account › Device contacts, and automatic sync when enabled."""
from . import APP_NAME
import asyncio
import tkinter as tk
from tkinter import ttk

from .i18n import tr

_synced_this_session = set()


def _context(app):
    return app.service.root, app.ui_account, app.service.backend


def summary_text(last):
    if not last:
        return tr('Not synchronized yet.')
    if last.get('reset'):
        return tr('Synchronized contacts were deleted from Telegram.')
    return tr('Device contacts: {device} · uploaded: {sent} · on Telegram: {users}').format(
        device=last.get('device', 0), sent=last.get('sent', 0), users=last.get('on_telegram', 0)) + (
        ' · ' + tr('Telegram asked to continue later.') if last.get('retry') else '')


async def _sync(root, account, backend, contacts=None):
    from .contact_sync import import_contacts, load_state, save_state
    from .device_contacts import read_device_contacts
    if contacts is None:
        contacts = await asyncio.to_thread(read_device_contacts)
    state = await asyncio.to_thread(load_state, root, account)
    try:
        return await import_contacts(backend, contacts, state)
    finally:
        await asyncio.to_thread(save_state, root, account, state, preserve_enabled=True)


def auto_sync(app):
    """Official behaviour: with sync on, device changes are uploaded on login."""
    if getattr(app, 'demo', False) or getattr(app, '_chat_only', False):
        return
    root, account, backend = _context(app)
    key = (account, id(backend))
    if backend is None or key in _synced_this_session:
        return
    from .contact_sync import load_state
    if not load_state(root, account)['enabled']:
        return
    _synced_this_session.add(key)
    app.worker.submit(_sync(root, account, backend), lambda _: None, lambda _: None)


def open_contact_sync(app):
    if getattr(app, 'busy', False):
        return
    from .contact_sync import load_state, save_state, reset_synced
    from .device_contacts import native_supported, read_vcard
    root, account, backend = _context(app)
    window, frame = app.dialog('Device contacts', '560x520')
    state = load_state(root, account) if not app.demo else {'enabled': False, 'imported': {}, 'last': {}}

    def valid():
        return window.winfo_exists() and account == app.ui_account and backend is app.service.backend

    ttk.Label(frame, text=tr('Your contact list in TG-ASCII shows only Telegram contacts. With sync on, the contacts of this device are uploaded to Telegram so people who use it appear there, like in the official app.'),
              wraplength=500).pack(fill='x', pady=8)
    enabled = tk.BooleanVar(master=window, value=state['enabled'])
    status = tk.StringVar(master=window, value=summary_text(state['last']))
    ttk.Label(frame, textvariable=status, wraplength=500).pack(fill='x', pady=8)

    def finished(summary):
        if valid():
            status.set(summary_text(summary))

    def failed(error):
        if valid():
            status.set(tr('Contacts could not be synchronized: ') + str(error))

    def sync_now(contacts=None):
        if app.demo or not valid():
            return
        app.call(_sync(root, account, backend, contacts), finished, tr('Syncing contacts...'), failure=failed, timeout=600)

    def toggled():
        if app.demo:
            return
        current = load_state(root, account)
        current['enabled'] = bool(enabled.get())
        save_state(root, account, current)
        if current['enabled']:
            sync_now()

    ttk.Checkbutton(frame, text=tr('Sync contacts from this device'), variable=enabled, command=toggled,
                    style='Settings.TCheckbutton').pack(fill='x', pady=6)
    sync_button = ttk.Button(frame, text=tr('Sync now'), command=sync_now)
    if native_supported():
        sync_button.pack(fill='x', pady=4)

    def import_file():
        from .app_dialogs import filedialog
        path = filedialog.askopenfilename(parent=window, filetypes=[('vCard', '*.vcf *.vcard'), ('*', '*')])
        if not path or not valid():
            return
        try:
            contacts = read_vcard(path)
        except (OSError, ValueError) as error:
            failed(error)
            return
        sync_now(contacts)

    ttk.Button(frame, text=tr('Import contacts from a vCard file (.vcf)'), command=import_file).pack(fill='x', pady=4)

    def reset():
        from .app_dialogs import messagebox
        if app.demo or not valid():
            return
        if not messagebox.askyesno(APP_NAME, tr('Delete all contacts synchronized from your devices from Telegram? Your Telegram contacts that you added manually are not removed.'), parent=window):
            return
        current = load_state(root, account)

        async def run():
            await reset_synced(backend, current)
            await asyncio.to_thread(save_state, root, account, current)
            return current['last']
        app.call(run(), finished, tr('Saving...'), failure=failed)

    ttk.Button(frame, text=tr('Delete synced contacts from Telegram'), command=reset).pack(fill='x', pady=4)
    note = {'darwin': tr('macOS asks for permission to access Contacts the first time.'),
            'win32': tr('Windows uses the contacts of the People app. Privacy › Contacts must allow access.')}
    import sys
    if sys.platform in note:
        ttk.Label(frame, text=note[sys.platform], wraplength=500, style='Muted.TLabel').pack(fill='x', pady=8)
