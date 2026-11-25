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
    from .startup_look import display_name
    ttk.Label(frame, text=display_name(app.preferences.values), style='Title.TLabel',
              font=(app.font_family, 22, 'bold')).pack(anchor='w', pady=(12, 0))
    ttk.Label(frame, text=caption('Choose account', 'Elegir cuenta')).pack(anchor='w', pady=(4, 12))
    ttk.Label(frame, text=caption('Your other accounts will stay available after opening.', 'Las demás cuentas seguirán disponibles después de entrar.'), wraplength=500).pack(anchor='w', pady=8)
    style = ttk.Style(frame)
    style.configure('Accounts.Treeview', rowheight=48)
    tree = ttk.Treeview(frame, show='tree', selectmode='browse', height=6, style='Accounts.Treeview')
    tree.pack(fill='both', expand=True, pady=8)
    tree.pictures = {}
    for key in app.service.entries:
        label = account_label(app, key, key)
        tree.insert('', 'end', iid=key, text='  ' + label, image=account_picture(app, tree, key, label))
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


def account_picture(app, tree, key, label):
    """Own photo saved at the last connection, else Telegram's placeholder."""
    try:
        from PIL import ImageTk
        from .account_photos import display_path, round_image
        entry = app.service.entries.get(key) or {}
        folder = getattr(app, 'preview_dir', None) or app.service.root / 'media-cache'
        path = display_path(app.service.root, key, entry.get('label') or label, entry.get('user_id'), folder)
        photo = ImageTk.PhotoImage(round_image(path, 40), master=tree)
    except Exception:
        return ''
    tree.pictures[key] = photo
    return photo

