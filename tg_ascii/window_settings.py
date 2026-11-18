"""Settings › Windows and Settings › Account › Accounts in this window (1.5.4).

Everything here applies at once (no "Save settings" needed): these are
actions on windows and accounts, not appearance choices.
"""
import tkinter as tk
from tkinter import ttk

from .i18n import tr


def _owner(app):
    return getattr(app, '_linked_owner', None) or app


def _muted(parent, text):
    ttk.Label(parent, text=tr(text), style='Muted.TLabel', wraplength=480).pack(fill='x', pady=(0, 6))


def build_windows_section(app, parent):
    from . import saved_windows
    owner = _owner(app)
    root = owner.service.root
    main = saved_windows.main_root(root)
    independent = saved_windows.is_independent(root)

    ttk.Label(parent, text=tr('Start'), style='Title.TLabel').pack(anchor='w', pady=(4, 4))
    if independent or owner.demo:
        _muted(parent, 'Opening the app when you log in is chosen in the main window.')
    else:
        login = tk.BooleanVar(value=bool(owner.preferences.values.get('open_at_login')))

        def login_changed():
            from .autostart import apply
            error = apply(login.get())
            if error is not None:
                login.set(not login.get())
                owner.show_error(error)
                return
            owner.preferences.save({'open_at_login': login.get()})
        check = ttk.Checkbutton(parent, text=tr('Open TG-ASCII when I log in to this computer'), variable=login,
                                command=login_changed, style='Settings.TCheckbutton')
        check.pack(fill='x', pady=2)
        check._variable = login
        _muted(parent, 'Off by default. Only your user is affected; turning it off removes the entry.')

    ttk.Label(parent, text=tr('Windows'), style='Title.TLabel').pack(anchor='w', pady=(12, 4))
    row = ttk.Frame(parent)
    row.pack(fill='x', pady=2)
    ttk.Button(row, text=tr('New window'), command=app.open_new_window).pack(side='left', fill='x', expand=True)
    ttk.Button(row, text=tr('New independent window'), command=app.open_independent_window).pack(side='left', fill='x', expand=True, padx=(6, 0))
    _muted(parent, 'A new window shows the same accounts and chats as this one. An independent window has its own logins, settings and information.')

    if owner.demo:
        _muted(parent, 'Not available in the demo.')
        return
    data = saved_windows.load(main)
    save = tk.BooleanVar(value=data['save'])
    reopen = tk.BooleanVar(value=data['reopen'])

    def flag(key, variable):
        def changed():
            saved_windows.set_flag(main, key, variable.get())
            refresh()
        return changed
    for text, key, variable, note in (
            ('Keep independent windows and their information', 'save', save,
             'Off: an independent window is temporary; when you close it, it signs out and its information is deleted.'),
            ('Open the chosen windows when the app starts', 'reopen', reopen,
             'Each one opens with its own information and logins.')):
        check = ttk.Checkbutton(parent, text=tr(text), variable=variable, command=flag(key, variable), style='Settings.TCheckbutton')
        check.pack(fill='x', pady=2)
        check._variable = variable
        _muted(parent, note)

    listing = ttk.Frame(parent)
    listing.pack(fill='x', pady=(4, 8))
    variables = []

    def refresh():
        for child in listing.winfo_children():
            child.destroy()
        variables.clear()
        current = saved_windows.load(main)
        if not current['windows']:
            ttk.Label(listing, text=tr('No saved windows yet.'), style='Muted.TLabel').pack(anchor='w')
            return
        for index, item in enumerate(current['windows']):
            ident = item['id']
            line = ttk.Frame(listing)
            line.pack(fill='x', pady=2)
            here = ' ●' if independent and ident == saved_windows.Path(root).name else ''
            name = tk.StringVar(value=saved_windows.display_name(current, item, tr))
            variables.append(name)
            entry = ttk.Entry(line, textvariable=name, width=18)
            entry.pack(side='left', fill='x', expand=True)

            def renamed(_=None, ident=ident, name=name):
                saved_windows.rename(main, ident, name.get())
            entry.bind('<Return>', renamed)
            entry.bind('<FocusOut>', renamed)
            if here:
                ttk.Label(line, text=here).pack(side='left')
            start = tk.BooleanVar(value=item['open_at_start'])
            variables.append(start)
            ttk.Checkbutton(line, text=tr('With the app'), variable=start,
                            command=lambda ident=ident, start=start: saved_windows.set_open_at_start(main, ident, start.get())
                            ).pack(side='left', padx=4)
            for label, offset in (('↑', -1), ('↓', 1)):
                button = ttk.Button(line, text=label, width=2,
                                    command=lambda ident=ident, offset=offset: (saved_windows.move(main, ident, offset), refresh()))
                button.pack(side='left')
                if (offset < 0 and index == 0) or (offset > 0 and index == len(current['windows']) - 1):
                    button.state(['disabled'])
            ttk.Button(line, text=tr('Open'), command=lambda ident=ident: app.open_independent_window(ident)).pack(side='left', padx=(4, 0))
            remove = ttk.Button(line, text=tr('Delete'), command=lambda ident=ident, label=name.get(): delete(ident, label))
            remove.pack(side='left', padx=(4, 0))
            if here:
                remove.state(['disabled'])

    def delete(ident, label):
        from .app_dialogs import messagebox
        if saved_windows.running(main, ident):
            owner.status.set(tr('Close that window first, then delete it.'))
            return
        if not messagebox.askyesno(tr('Delete window'), tr('Delete "{name}"? Its accounts are signed out and its information is deleted from this device.').format(name=label), parent=app.root):
            return
        owner.status.set(tr('Signing out and deleting data...'))

        def done(failed):
            refresh()
            owner.status.set(tr('Window deleted.') if not failed else tr('Window deleted. Some accounts could not be signed out from Telegram (no connection); you can end those sessions from Telegram › Settings › Devices.'))

        def failed(error):
            refresh()
            owner.status.set(tr('Close that window first, then delete it.') if isinstance(error, RuntimeError) else str(error))
        owner.worker.submit(saved_windows.delete_window(main, ident), done, failed)
    listing._variables = variables
    refresh()


def build_accounts_section(app, parent):
    """Visual names, order and sign-out for the accounts of this window."""
    owner = _owner(app)
    service = getattr(owner.service, 'owner', owner.service)
    ttk.Label(parent, text=tr('Accounts in this window'), style='Title.TLabel').pack(anchor='w', pady=(14, 4))
    _muted(parent, 'The name you give an account is only shown here, in this window. Telegram and your contacts do not see it.')
    box = ttk.Frame(parent)
    box.pack(fill='x', pady=(0, 8))
    variables = []

    def refresh():
        for child in box.winfo_children():
            child.destroy()
        variables.clear()
        keys = list(service.entries)
        aliases = owner.preferences.values.get('account_aliases') or {}
        for index, key in enumerate(keys):
            line = ttk.Frame(box)
            line.pack(fill='x', pady=2)
            original = service.labels.get(key, tr('Cuenta'))
            ttk.Label(line, text=original, width=16).pack(side='left')
            alias = tk.StringVar(value=aliases.get(key, ''))
            variables.append(alias)
            entry = ttk.Entry(line, textvariable=alias, width=16)
            entry.pack(side='left', fill='x', expand=True, padx=4)

            def save_alias(_=None, key=key, alias=alias):
                current = dict(owner.preferences.values.get('account_aliases') or {})
                value = ' '.join(alias.get().split())
                if value and value != service.labels.get(key):
                    current[key] = value
                else:
                    current.pop(key, None)
                if current != (owner.preferences.values.get('account_aliases') or {}):
                    owner.preferences.save({'account_aliases': current})
                    for view in (owner, *getattr(owner, '_app_windows', ())):
                        if not getattr(view, 'closed', False) and hasattr(view, 'update_account_picker'):
                            view.update_account_picker()
            entry.bind('<Return>', save_alias)
            entry.bind('<FocusOut>', save_alias)
            for label, offset in (('↑', -1), ('↓', 1)):
                button = ttk.Button(line, text=label, width=2, command=lambda key=key, offset=offset: move(key, offset))
                button.pack(side='left')
                if (offset < 0 and index == 0) or (offset > 0 and index == len(keys) - 1):
                    button.state(['disabled'])
            out = ttk.Button(line, text=tr('Sign out'), command=lambda key=key: owner.logout_account(key))
            out.pack(side='left', padx=(4, 0))
            if owner.demo:
                out.state(['disabled'])

    def move(key, offset):
        keys = list(service.entries)
        index = keys.index(key)
        target = max(0, min(len(keys) - 1, index + offset))
        keys.insert(target, keys.pop(index))
        service.reorder(keys)
        for view in (owner, *getattr(owner, '_app_windows', ())):
            if not getattr(view, 'closed', False) and hasattr(view, 'update_account_picker'):
                view.update_account_picker()
        refresh()
    box._variables = variables
    refresh()
