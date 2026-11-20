"""Account selection before any Telegram connection is opened."""
from .desktop_features import account_label
import tkinter as tk
from tkinter import ttk

from .interface_layout import caption


def show_account_chooser(app, configure=False):
    app.clear()
    app.stage = 'choose_account'
    app.viewport.fit_to_window = True
    app.status.set(caption('Choose the account to open.', 'Elige la cuenta que quieres abrir.'))
    frame = ttk.Frame(app.container, padding=24)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text=caption('Choose account', 'Elegir cuenta'), style='Title.TLabel').pack(anchor='w', pady=12)
    ttk.Label(frame, text=caption('Your other accounts will stay available after opening.', 'Las demás cuentas seguirán disponibles después de entrar.'), wraplength=500).pack(anchor='w', pady=8)
    tree = ttk.Treeview(frame, show='tree', selectmode='browse', height=6)
    tree.pack(fill='both', expand=True, pady=8)
    for key in app.service.entries:
        tree.insert('', 'end', iid=key, text=account_label(app, key, key))
    tree.selection_set(app.service.current)
    tree.focus(app.service.current)
    ask = tk.BooleanVar(value=True)
    ttk.Checkbutton(frame, text=caption('Show this chooser when I have several accounts', 'Mostrar este selector cuando tenga varias cuentas'), variable=ask).pack(anchor='w', pady=8)
    def start(_=None):
        selected = tree.selection()
        if app.busy or not selected:
            return
        try:
            app.preferences.save({'ask_account_startup': ask.get()})
        except OSError as exc:
            app.show_error(exc)
            return
        app.start_chosen_account(selected[0], configure)
    ttk.Button(frame, text=caption('Open account', 'Abrir cuenta'), command=start).pack(anchor='e', pady=12)
    tree.bind('<Double-Button-1>', start)
    tree.bind('<Return>', start)
    tree.focus_set()
