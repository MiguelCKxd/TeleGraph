"""TG-ASCII's own versions of menus the device normally draws (1.5.1).

Same call signatures and return values as tkinter.messagebox, filedialog and
colorchooser, so callers do not change; ``app_dialogs`` routes to these when
Settings › Menus chooses the app version. All are modal Tk windows themed
with the app palette.
"""
from . import APP_NAME
from datetime import datetime
import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk

from .i18n import tr


def _parent(options):
    parent = options.get('parent') or tk._default_root
    try:
        return parent.winfo_toplevel() if parent is not None else None
    except tk.TclError:
        return tk._default_root


def _palette():
    from .themes import _palette as palette
    return palette


def _look(kind):
    """ttk style names and values for this kind, with the user's style.json
    (Complex features › Customizable menus) applied over the app palette."""
    from .custom_menus import style as user_style
    custom = user_style(kind) if kind else {}
    palette = _palette()
    look = {
        'background': custom.get('background') or palette.get('bg', '#08100c'),
        'foreground': custom.get('foreground') or palette.get('text', '#8cf5a6'),
        'button_background': custom.get('button_background') or palette.get('panel', '#0e1b13'),
        'button_foreground': custom.get('button_foreground') or custom.get('foreground') or palette.get('text', '#8cf5a6'),
        'accent': custom.get('accent') or palette.get('selected', '#294d34'),
        'border': custom.get('border') or palette.get('line', '#294d34'),
        'padding': int(custom.get('padding') or 14),
        'custom': custom,
    }
    font = None
    if custom.get('font_family') or custom.get('font_size'):
        font = (custom.get('font_family') or 'TkDefaultFont', int(custom.get('font_size') or 12))
    look['font'] = font
    prefix = f'TgMenu{kind or "base"}'
    style = ttk.Style()
    try:
        style.configure(f'{prefix}.TFrame', background=look['background'])
        options = {'background': look['background'], 'foreground': look['foreground']}
        if font:
            options['font'] = font
        style.configure(f'{prefix}.TLabel', **options)
        style.configure(f'{prefix}.Muted.TLabel', background=look['background'], foreground=palette.get('muted', '#80a98c'), **({'font': font} if font else {}))
        button = {'background': look['button_background'], 'foreground': look['button_foreground'], 'bordercolor': look['border']}
        if font:
            button['font'] = font
        style.configure(f'{prefix}.TButton', **button)
        style.map(f'{prefix}.TButton', background=[('active', look['accent'])])
    except tk.TclError:
        pass
    look.update(frame=f'{prefix}.TFrame', label=f'{prefix}.TLabel', muted=f'{prefix}.Muted.TLabel', button=f'{prefix}.TButton')
    return look


def _modal(parent, title, size=None, kind=None):
    look = _look(kind)
    custom = look['custom']
    window = tk.Toplevel(parent)
    window.title(custom.get('title') or title or APP_NAME)
    window.configure(bg=look['background'])
    if parent is not None:
        try:
            window.transient(parent)
        except tk.TclError:
            pass
    if custom.get('width') and custom.get('height'):
        size = f"{int(custom['width'])}x{int(custom['height'])}"
    if size:
        window.geometry(size)
    body = ttk.Frame(window, padding=look['padding'], style=look['frame'])
    body.pack(fill='both', expand=True)
    window._look = look
    return window, body


def _center(window, parent):
    window.update_idletasks()
    try:
        if parent is not None and parent.winfo_viewable():
            x = parent.winfo_rootx() + (parent.winfo_width() - window.winfo_reqwidth()) // 2
            y = parent.winfo_rooty() + (parent.winfo_height() - window.winfo_reqheight()) // 3
        else:
            x = (window.winfo_screenwidth() - window.winfo_reqwidth()) // 2
            y = (window.winfo_screenheight() - window.winfo_reqheight()) // 3
        window.geometry(f'+{max(0, x)}+{max(0, y)}')
    except tk.TclError:
        pass


def _run(window, result, default):
    try:
        window.grab_set()
    except tk.TclError:
        pass
    window.focus_force()
    window.wait_window()
    return result[0] if result else default


# -- message boxes --------------------------------------------------------
ICONS = {'info': 'ℹ', 'warning': '⚠', 'error': '✖', 'question': '?'}


def _box(icon, buttons, title=None, message=None, **options):
    from .custom_menus import run
    parent = _parent(options)
    return run('message_box', lambda: _builtin_box(icon, buttons, title, message, **options),
               icon, [(tr(label), value) for label, value in buttons], title, message, parent)


def _builtin_box(icon, buttons, title=None, message=None, **options):
    parent = _parent(options)
    window, body = _modal(parent, title, kind='message_box')
    look = window._look
    custom = look['custom']
    wrap = int(custom.get('wraplength') or 420)
    renamed = custom.get('button_labels') or {}
    result = [None]
    top = ttk.Frame(body, style=look['frame'])
    top.pack(fill='both', expand=True)
    ttk.Label(top, text=custom.get('icon') or ICONS.get(icon, 'ℹ'), font=('TkDefaultFont', 22), style=look['label']).pack(side='left', anchor='n', padx=(0, 12))
    texts = ttk.Frame(top, style=look['frame'])
    texts.pack(side='left', fill='both', expand=True)
    ttk.Label(texts, text=str(message or ''), wraplength=wrap, justify='left', style=look['label']).pack(anchor='w')
    if options.get('detail'):
        ttk.Label(texts, text=str(options['detail']), wraplength=wrap, justify='left', style=look['muted']).pack(anchor='w', pady=(6, 0))
    row = ttk.Frame(body, style=look['frame'])
    row.pack(fill='x', pady=(14, 0))
    default = options.get('default') or buttons[0][1]
    widgets = []
    for label, value in reversed(buttons):
        text = renamed.get(value) or renamed.get(label) or tr(label)
        button = ttk.Button(row, text=text, style=look['button'], command=lambda value=value: (result.__setitem__(0, value), window.destroy()))
        button.pack(side='right', padx=(6, 0))
        widgets.append((value, button))
    cancel_value = next((value for value in ('cancel', 'no') if any(v == value for _, v in buttons)), None)
    window.bind('<Escape>', lambda _: (result.__setitem__(0, cancel_value), window.destroy()))
    window.bind('<Return>', lambda _: (result.__setitem__(0, default), window.destroy()))
    window.protocol('WM_DELETE_WINDOW', lambda: (result.__setitem__(0, cancel_value), window.destroy()))
    for value, button in widgets:
        if value == default:
            button.focus_set()
    _center(window, parent)
    return _run(window, result, cancel_value)


def showinfo(title=None, message=None, **options):
    return _box(options.pop('icon', 'info'), [('OK', 'ok')], title, message, **options) or 'ok'


def showwarning(title=None, message=None, **options):
    return _box('warning', [('OK', 'ok')], title, message, **options) or 'ok'


def showerror(title=None, message=None, **options):
    return _box('error', [('OK', 'ok')], title, message, **options) or 'ok'


def askyesno(title=None, message=None, **options):
    return _box('question', [('Yes', 'yes'), ('No', 'no')], title, message, **options) == 'yes'


def askokcancel(title=None, message=None, **options):
    return _box('question', [('OK', 'ok'), ('Cancel', 'cancel')], title, message, **options) == 'ok'


def askretrycancel(title=None, message=None, **options):
    return _box('warning', [('Retry', 'retry'), ('Cancel', 'cancel')], title, message, **options) == 'retry'


def askquestion(title=None, message=None, **options):
    return _box('question', [('Yes', 'yes'), ('No', 'no')], title, message, **options) or 'no'


def askyesnocancel(title=None, message=None, **options):
    value = _box('question', [('Yes', 'yes'), ('No', 'no'), ('Cancel', 'cancel')], title, message, **options)
    return None if value in (None, 'cancel') else value == 'yes'


# -- file picker -------------------------------------------------------------
def _places():
    home = Path.home()
    places = [(tr('Home'), home)]
    for name, label in (('Desktop', 'Desktop'), ('Documents', 'Documents'), ('Downloads', 'Downloads'), ('Pictures', 'Pictures'), ('Movies' if sys.platform == 'darwin' else 'Videos', 'Videos'), ('Music', 'Music')):
        path = home / name
        if path.is_dir():
            places.append((tr(label), path))
    if sys.platform == 'win32':
        import string
        for letter in string.ascii_uppercase:
            drive = Path(f'{letter}:\\')
            if drive.exists():
                places.append((f'{letter}:', drive))
    else:
        places.append(('/', Path('/')))
        volumes = Path('/Volumes')
        if volumes.is_dir():
            try:
                for item in sorted(volumes.iterdir())[:8]:
                    places.append((item.name, item))
            except OSError:
                pass
    return places


def _patterns(filetypes):
    result = []
    for entry in filetypes or ():
        try:
            label, patterns = entry
        except (TypeError, ValueError):
            continue
        if isinstance(patterns, str):
            patterns = patterns.split()
        result.append((str(label), [str(item).lower() for item in patterns]))
    if not result:
        result = [(tr('All files'), ['*'])]
    return result


def _matches(name, patterns):
    import fnmatch
    lower = name.lower()
    return any(pattern in ('*', '*.*') or fnmatch.fnmatch(lower, pattern if pattern.startswith('*') else '*' + pattern)
               for pattern in patterns)


def _size(value):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if value < 1024 or unit == 'GB':
            return f'{value:.0f} {unit}' if unit == 'B' else f'{value:.1f} {unit}'
        value /= 1024


def _browser(mode, options):
    """mode: open | open_many | save | folder."""
    from .custom_menus import run
    return run('file_picker', lambda: _builtin_browser(mode, options), mode, dict(options))


def _builtin_browser(mode, options):
    parent = _parent(options)
    titles = {'open': tr('Open'), 'open_many': tr('Open'), 'save': tr('Save'), 'folder': tr('Choose folder')}
    window, body = _modal(parent, options.get('title') or titles[mode], '760x520', kind='file_picker')
    window.minsize(520, 360)
    custom = window._look['custom']
    result = [None]
    start = Path(options.get('initialdir') or custom.get('start_folder') or Path.home()).expanduser()
    if not start.is_dir():
        start = Path.home()
    state = {'path': start.resolve(), 'patterns': _patterns(options.get('filetypes'))}
    top = ttk.Frame(body)
    top.pack(fill='x')
    up = ttk.Button(top, text='↑', width=3)
    up.pack(side='left')
    location = tk.StringVar(value=str(state['path']))
    entry = ttk.Entry(top, textvariable=location)
    entry.pack(side='left', fill='x', expand=True, padx=6)
    middle = ttk.Panedwindow(body, orient='horizontal')
    middle.pack(fill='both', expand=True, pady=8)
    side = tk.Listbox(middle, exportselection=False, width=16, activestyle='none')
    places = _places()
    for extra in custom.get('places') or ():
        try:
            places.append((Path(extra).expanduser().name or str(extra), Path(extra).expanduser()))
        except (TypeError, ValueError):
            pass
    for label, _ in places:
        side.insert('end', label)
    middle.add(side, weight=1)
    list_frame = ttk.Frame(middle)
    middle.add(list_frame, weight=5)
    tree = ttk.Treeview(list_frame, columns=('size', 'modified'), selectmode='extended' if mode == 'open_many' else 'browse')
    tree.heading('#0', text=tr('Name'))
    tree.heading('size', text=tr('Size'))
    tree.heading('modified', text=tr('Modified'))
    tree.column('#0', width=330, stretch=True)
    tree.column('size', width=90, stretch=False, anchor='e')
    tree.column('modified', width=140, stretch=False)
    bar = ttk.Scrollbar(list_frame, command=tree.yview)
    tree.configure(yscrollcommand=bar.set)
    bar.pack(side='right', fill='y')
    tree.pack(fill='both', expand=True)
    bottom = ttk.Frame(body)
    bottom.pack(fill='x')
    name = tk.StringVar(value=options.get('initialfile') or '')
    if mode == 'save':
        ttk.Label(bottom, text=tr('Name')).pack(side='left')
        name_entry = ttk.Entry(bottom, textvariable=name, width=32)
        name_entry.pack(side='left', padx=6)
    types = ttk.Combobox(bottom, state='readonly', values=[label for label, _ in state['patterns']], width=26)
    if mode != 'folder':
        types.current(0)
        types.pack(side='left', padx=6)
    hidden = tk.BooleanVar(value=bool(custom.get('show_hidden')))
    ttk.Checkbutton(bottom, text=tr('Hidden files'), variable=hidden, command=lambda: fill()).pack(side='left', padx=6)
    accept = ttk.Button(bottom, text=titles[mode] if mode != 'open_many' else tr('Open'))
    accept.pack(side='right')
    ttk.Button(bottom, text=tr('Cancel'), command=window.destroy).pack(side='right', padx=6)
    entries = {}

    def fill():
        tree.delete(*tree.get_children())
        entries.clear()
        path = state['path']
        location.set(str(path))
        patterns = state['patterns'][types.current()][1] if mode != 'folder' and types.current() >= 0 else ['*']
        try:
            items = sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))
        except OSError as exc:
            tree.insert('', 'end', text=f'⚠ {exc.strerror or exc}')
            return
        for item in items:
            if not hidden.get() and item.name.startswith('.'):
                continue
            try:
                is_dir = item.is_dir()
                info = item.stat()
            except OSError:
                continue
            if not is_dir and (mode == 'folder' or not _matches(item.name, patterns)):
                continue
            modified = datetime.fromtimestamp(info.st_mtime).strftime('%Y-%m-%d %H:%M')
            row = tree.insert('', 'end', text=('📁 ' if is_dir else '📄 ') + item.name,
                              values=('' if is_dir else _size(info.st_size), modified))
            entries[row] = item

    def go(path):
        path = Path(path).expanduser()
        if path.is_dir():
            state['path'] = path.resolve()
            fill()

    def opened(_=None):
        selection = tree.selection()
        if len(selection) == 1 and entries.get(selection[0]) and entries[selection[0]].is_dir():
            go(entries[selection[0]])
            return 'break'
        finish()
        return 'break'

    def selected(_=None):
        selection = [entries[row] for row in tree.selection() if row in entries]
        if mode == 'save' and len(selection) == 1 and not selection[0].is_dir():
            name.set(selection[0].name)

    def finish():
        selection = [entries[row] for row in tree.selection() if row in entries]
        if mode == 'folder':
            target = selection[0] if len(selection) == 1 and selection[0].is_dir() else state['path']
            result[0] = str(target)
        elif mode == 'save':
            value = name.get().strip()
            if not value:
                return
            target = state['path'] / value
            extension = options.get('defaultextension') or ''
            if extension and not target.suffix:
                target = target.with_name(target.name + extension)
            if target.exists() and options.get('confirmoverwrite', True):
                if not askyesno(tr('Save'), tr('{name} already exists. Replace it?').format(name=target.name), parent=window):
                    return
            result[0] = str(target)
        else:
            files = [item for item in selection if item.is_file()]
            if not files:
                return
            result[0] = tuple(str(item) for item in files) if mode == 'open_many' else str(files[0])
        window.destroy()

    up.configure(command=lambda: go(state['path'].parent))
    entry.bind('<Return>', lambda _: go(location.get()))
    side.bind('<<ListboxSelect>>', lambda _: go(places[side.curselection()[0]][1]) if side.curselection() else None)
    tree.bind('<Double-Button-1>', opened)
    tree.bind('<Return>', opened)
    tree.bind('<<TreeviewSelect>>', selected)
    types.bind('<<ComboboxSelected>>', lambda _: fill())
    accept.configure(command=finish)
    window.bind('<Escape>', lambda _: window.destroy())
    fill()
    _center(window, parent)
    value = _run(window, result, None)
    if value is None:
        return () if mode == 'open_many' else ''
    return value


def askopenfilename(**options):
    return _browser('open', options)


def askopenfilenames(**options):
    return _browser('open_many', options)


def asksaveasfilename(**options):
    return _browser('save', options)


def askdirectory(**options):
    return _browser('folder', options)


# -- colour picker -----------------------------------------------------------
SWATCHES = ('#000000', '#404040', '#808080', '#c0c0c0', '#ffffff', '#08100c', '#0e1b13', '#294d34', '#80a98c', '#8cf5a6',
            '#ff3b30', '#ff9500', '#ffcc00', '#34c759', '#00c7be', '#30b0c7', '#32ade6', '#007aff', '#5856d6', '#af52de',
            '#ff2d55', '#a2845e', '#7f0000', '#7f3f00', '#7f6600', '#006400', '#00635e', '#003f7f', '#2c2b6b', '#57296f',
            '#ffb3ae', '#ffd59e', '#fff0a0', '#b8f0c4', '#a6eeea', '#a8d8f0', '#a8cfff', '#c8c7f2', '#e4c3f2', '#ffc0d0')


def askcolor(color=None, **options):
    from .custom_menus import run
    return run('color_picker', lambda: _builtin_askcolor(color, **options), color, dict(options))


def _builtin_askcolor(color=None, **options):
    parent = _parent(options)
    window, body = _modal(parent, options.get('title') or tr('Choose a colour'), kind='color_picker')
    swatches = window._look['custom'].get('swatches') or SWATCHES
    result = [None]
    current = tk.StringVar(value=color if isinstance(color, str) and len(color) == 7 and color.startswith('#') else '#8cf5a6')
    grid = ttk.Frame(body)
    grid.pack()
    preview = tk.Label(body, width=30, height=2, relief='solid', bd=1)
    def set_hex(value):
        value = value.strip().lower()
        if len(value) == 7 and value.startswith('#') and all(c in '0123456789abcdef' for c in value[1:]):
            current.set(value)
            preview.configure(bg=value)
            r, g, b = (int(value[i:i + 2], 16) for i in (1, 3, 5))
            for scale, channel in zip(scales, (r, g, b)):
                if int(scale.get()) != channel:
                    scale.set(channel)
            return True
        return False
    for index, swatch in enumerate(swatches):
        cell = tk.Label(grid, bg=swatch, width=3, height=1, relief='raised', bd=1, cursor='hand2')
        cell.grid(row=index // 10, column=index % 10, padx=2, pady=2)
        cell.bind('<Button-1>', lambda _, swatch=swatch: set_hex(swatch))
    sliders = ttk.Frame(body)
    sliders.pack(fill='x', pady=8)
    scales = []
    def slid(_=None):
        value = '#%02x%02x%02x' % tuple(int(scale.get()) for scale in scales)
        if value != current.get():
            current.set(value)
            preview.configure(bg=value)
    for label in ('R', 'G', 'B'):
        row = ttk.Frame(sliders)
        row.pack(fill='x')
        ttk.Label(row, text=label, width=2).pack(side='left')
        scale = ttk.Scale(row, from_=0, to=255, command=slid)
        scale.pack(side='left', fill='x', expand=True)
        scales.append(scale)
        from .number_input import NumberField
        channel = tk.IntVar(master=row, value=0)
        scale.configure(variable=channel)
        NumberField(row, channel, 0, 255, command=lambda _value: slid(), integer=True, width=4).pack(side='left', padx=(6, 0))
    preview.pack(fill='x', pady=4)
    code = ttk.Frame(body)
    code.pack(fill='x', pady=4)
    ttk.Label(code, text='#').pack(side='left')
    hex_entry = ttk.Entry(code, textvariable=current, width=10)
    hex_entry.pack(side='left')
    hex_entry.bind('<Return>', lambda _: set_hex(current.get()))
    hex_entry.bind('<FocusOut>', lambda _: set_hex(current.get()))
    buttons = ttk.Frame(body)
    buttons.pack(fill='x', pady=(8, 0))
    def accept():
        if set_hex(current.get()):
            result[0] = current.get()
            window.destroy()
    ttk.Button(buttons, text=tr('OK'), command=accept).pack(side='right')
    ttk.Button(buttons, text=tr('Cancel'), command=window.destroy).pack(side='right', padx=6)
    window.bind('<Escape>', lambda _: window.destroy())
    set_hex(current.get())
    _center(window, parent)
    value = _run(window, result, None)
    if not value:
        return (None, None)
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5)), value


# -- emoji picker --------------------------------------------------------------
EMOJI = {
    'Smileys': '😀 😃 😄 😁 😆 😅 🤣 😂 🙂 🙃 😉 😊 😇 🥰 😍 🤩 😘 😗 😚 😙 😋 😛 😜 🤪 😝 🤑 🤗 🤭 🤫 🤔 🤐 🤨 😐 😑 😶 😏 😒 🙄 😬 🤥 😌 😔 😪 🤤 😴 😷 🤒 🤕 🤢 🤮 🥵 🥶 🥴 😵 🤯 🤠 🥳 😎 🤓 🧐 😕 😟 🙁 😮 😯 😲 😳 🥺 😦 😧 😨 😰 😥 😢 😭 😱 😖 😣 😞 😓 😩 😫 🥱 😤 😡 😠 🤬 😈 👿 💀 💩 🤡 👻 👽 🤖',
    'People': '👋 🤚 🖐 ✋ 🖖 👌 🤌 🤏 ✌ 🤞 🤟 🤘 🤙 👈 👉 👆 👇 ☝ 👍 👎 ✊ 👊 🤛 🤜 👏 🙌 👐 🤲 🤝 🙏 💪 🦾 👀 👁 👅 👄 👶 🧒 👦 👧 🧑 👱 👨 🧔 👩 🧓 👴 👵 🙍 🙎 🙅 🙆 💁 🙋 🧏 🙇 🤦 🤷 👮 🕵 💂 👷 🤴 👸 👳 🧕 🤵 👰 🤰 🤱 👼 🎅 🤶 🦸 🦹 🧙 🧚 🧛 🧜 🧝 🧞 🧟 💃 🕺',
    'Nature': '🐶 🐱 🐭 🐹 🐰 🦊 🐻 🐼 🐨 🐯 🦁 🐮 🐷 🐸 🐵 🙈 🙉 🙊 🐔 🐧 🐦 🐤 🦆 🦅 🦉 🦇 🐺 🐗 🐴 🦄 🐝 🐛 🦋 🐌 🐞 🐜 🐢 🐍 🦎 🐙 🦑 🦀 🐠 🐟 🐬 🐳 🐋 🦈 🐊 🐅 🐆 🦓 🦍 🐘 🦒 🐪 🐫 🦘 🐎 🐖 🐑 🐐 🦌 🐕 🐈 🐓 🦃 🦚 🦜 🦢 🌵 🎄 🌲 🌳 🌴 🌱 🌿 ☘ 🍀 🍁 🍂 🍃 🌷 🌹 🥀 🌺 🌸 🌼 🌻 🌞 🌝 🌚 🌙 ⭐ 🌟 ✨ ⚡ 🔥 🌈 ☀ ⛅ ☁ 🌧 ⛈ ❄ ☃ 💧 🌊',
    'Food': '🍏 🍎 🍐 🍊 🍋 🍌 🍉 🍇 🍓 🍈 🍒 🍑 🥭 🍍 🥥 🥝 🍅 🍆 🥑 🥦 🥬 🥒 🌶 🌽 🥕 🧄 🧅 🥔 🍠 🥐 🥯 🍞 🥖 🥨 🧀 🥚 🍳 🧈 🥞 🧇 🥓 🥩 🍗 🍖 🌭 🍔 🍟 🍕 🥪 🥙 🧆 🌮 🌯 🥗 🥘 🍝 🍜 🍲 🍛 🍣 🍱 🥟 🍤 🍙 🍚 🍘 🍥 🥠 🍢 🍡 🍧 🍨 🍦 🥧 🧁 🍰 🎂 🍮 🍭 🍬 🍫 🍿 🍩 🍪 🥛 ☕ 🍵 🧃 🥤 🍺 🍻 🥂 🍷 🥃 🍸 🍹 🧉 🍾',
    'Activity': '⚽ 🏀 🏈 ⚾ 🥎 🎾 🏐 🏉 🥏 🎱 🏓 🏸 🏒 🏑 🥍 🏏 🥅 ⛳ 🏹 🎣 🥊 🥋 🎽 🛹 🛷 ⛸ 🥌 🎿 ⛷ 🏂 🏋 🤸 ⛹ 🤺 🤾 🏌 🏇 🧘 🏄 🏊 🤽 🚣 🧗 🚵 🚴 🏆 🥇 🥈 🥉 🏅 🎖 🎗 🎫 🎟 🎪 🎭 🎨 🎬 🎤 🎧 🎼 🎹 🥁 🎷 🎺 🎸 🪕 🎻 🎲 ♟ 🎯 🎳 🎮 🎰 🧩',
    'Travel': '🚗 🚕 🚙 🚌 🚎 🏎 🚓 🚑 🚒 🚐 🚚 🚛 🚜 🛴 🚲 🛵 🏍 🚨 🚔 🚍 🚘 🚖 🚡 🚠 🚟 🚃 🚋 🚞 🚝 🚄 🚅 🚈 🚂 🚆 🚇 🚊 🚉 ✈ 🛫 🛬 🛩 💺 🛰 🚀 🛸 🚁 🛶 ⛵ 🚤 🛥 🛳 ⛴ 🚢 ⚓ ⛽ 🚧 🚦 🚥 🗺 🗿 🗽 🗼 🏰 🏯 🏟 🎡 🎢 🎠 ⛲ ⛱ 🏖 🏝 🏜 🌋 ⛰ 🏔 🗻 🏕 ⛺ 🏠 🏡 🏘 🏚 🏗 🏭 🏢 🏬 🏣 🏤 🏥 🏦 🏨 🏪 🏫 🏩 💒 🏛 ⛪ 🕌 🕍 🛕 🕋',
    'Objects': '⌚ 📱 📲 💻 ⌨ 🖥 🖨 🖱 🖲 🕹 🗜 💽 💾 💿 📀 📼 📷 📸 📹 🎥 📽 🎞 📞 ☎ 📟 📠 📺 📻 🎙 🎚 🎛 🧭 ⏱ ⏲ ⏰ 🕰 ⌛ ⏳ 📡 🔋 🔌 💡 🔦 🕯 🧯 🛢 💸 💵 💴 💶 💷 💰 💳 💎 ⚖ 🧰 🔧 🔨 ⚒ 🛠 ⛏ 🔩 ⚙ 🧱 ⛓ 🧲 🔫 💣 🧨 🪓 🔪 🗡 ⚔ 🛡 🚬 ⚰ ⚱ 🏺 🔮 📿 🧿 💈 ⚗ 🔭 🔬 🕳 💊 💉 🩸 🧬 🦠 🧫 🧪 🌡 🧹 🧺 🧻 🚽 🚰 🚿 🛁 🛀 🧼 🧽 🧴 🛎 🔑 🗝 🚪 🛋 🛏 🛌 🧸 🖼 🛍 🛒 🎁 🎈 🎏 🎀 🎊 🎉 🎎 🏮 🎐 🧧 ✉ 📩 📨 📧 💌 📥 📤 📦 🏷 📪 📫 📬 📭 📮 📯 📜 📃 📄 📑 🧾 📊 📈 📉 🗒 🗓 📆 📅 🗑 📇 🗃 🗳 🗄 📋 📁 📂 🗂 🗞 📰 📓 📔 📒 📕 📗 📘 📙 📚 📖 🔖 🧷 🔗 📎 🖇 📐 📏 🧮 📌 📍 ✂ 🖊 🖋 ✒ 🖌 🖍 📝 ✏ 🔍 🔎 🔏 🔐 🔒 🔓',
    'Symbols': '❤ 🧡 💛 💚 💙 💜 🖤 🤍 🤎 💔 ❣ 💕 💞 💓 💗 💖 💘 💝 💟 ☮ ✝ ☪ 🕉 ☸ ✡ 🔯 🕎 ☯ ☦ 🛐 ⛎ ♈ ♉ ♊ ♋ ♌ ♍ ♎ ♏ ♐ ♑ ♒ ♓ 🆔 ⚛ 🉑 ☢ ☣ 📴 📳 🈶 🈚 🈸 🈺 🈷 ✴ 🆚 💮 🉐 ㊙ ㊗ 🈴 🈵 🈹 🈲 🅰 🅱 🆎 🆑 🅾 🆘 ❌ ⭕ 🛑 ⛔ 📛 🚫 💯 💢 ♨ 🚷 🚯 🚳 🚱 🔞 📵 🚭 ❗ ❕ ❓ ❔ ‼ ⁉ 🔅 🔆 〽 ⚠ 🚸 🔱 ⚜ 🔰 ♻ ✅ 🈯 💹 ❇ ✳ ❎ 🌐 💠 Ⓜ 🌀 💤 🏧 🚾 ♿ 🅿 🈳 🈂 🛂 🛃 🛄 🛅 🚹 🚺 🚼 🚻 🚮 🎦 📶 🈁 🔣 ℹ 🔤 🔡 🔠 🆖 🆗 🆙 🆒 🆕 🆓 0️⃣ 1️⃣ 2️⃣ 3️⃣ 4️⃣ 5️⃣ 6️⃣ 7️⃣ 8️⃣ 9️⃣ 🔟 🔢 #️⃣ *️⃣ ▶ ⏸ ⏯ ⏹ ⏺ ⏭ ⏮ ⏩ ⏪ ⏫ ⏬ ◀ 🔼 🔽 ➡ ⬅ ⬆ ⬇ ↗ ↘ ↙ ↖ ↕ ↔ ↪ ↩ ⤴ ⤵ 🔀 🔁 🔂 🔄 🔃 🎵 🎶 ➕ ➖ ➗ ✖ ♾ 💲 💱 ™ © ® 〰 ➰ ➿ 🔚 🔙 🔛 🔝 🔜 ✔ ☑ 🔘 🔴 🟠 🟡 🟢 🔵 🟣 ⚫ ⚪ 🟤 🔺 🔻 🔸 🔹 🔶 🔷 🔳 🔲 ▪ ▫ ◾ ◽ ◼ ◻ 🟥 🟧 🟨 🟩 🟦 🟪 ⬛ ⬜ 🟫 🔈 🔇 🔉 🔊 🔔 🔕 📣 📢 💬 💭 🗯 ♠ ♣ ♥ ♦ 🃏 🎴 🀄',
    'Flags': '🏁 🚩 🎌 🏴 🏳 🏳️‍🌈 🏴‍☠️ 🇪🇸 🇨🇱 🇦🇷 🇲🇽 🇨🇴 🇵🇪 🇻🇪 🇺🇾 🇧🇴 🇪🇨 🇵🇾 🇨🇺 🇩🇴 🇵🇷 🇺🇸 🇬🇧 🇫🇷 🇩🇪 🇮🇹 🇵🇹 🇧🇷 🇨🇦 🇯🇵 🇰🇷 🇨🇳 🇮🇳 🇷🇺 🇺🇦 🇵🇱 🇳🇱 🇧🇪 🇨🇭 🇦🇹 🇸🇪 🇳🇴 🇩🇰 🇫🇮 🇮🇪 🇬🇷 🇹🇷 🇮🇱 🇸🇦 🇦🇪 🇪🇬 🇲🇦 🇿🇦 🇳🇬 🇦🇺 🇳🇿 🇪🇺 🇺🇳',
}


def open_emoji_picker(entry, anchor=None):
    """App emoji palette: inserts at the cursor of an Entry or Text widget."""
    from .custom_menus import run
    return run('emoji_picker', lambda: _builtin_emoji_picker(entry, anchor), entry)


def _builtin_emoji_picker(entry, anchor=None):
    look = _look('emoji_picker')
    custom = look['custom']
    parent = entry.winfo_toplevel()
    window = tk.Toplevel(parent)
    window.title(custom.get('title') or tr('Emoji'))
    window.configure(bg=look['background'])
    window.transient(parent)
    notebook = ttk.Notebook(window)
    notebook.pack(fill='both', expand=True, padx=6, pady=6)
    size = int(custom.get('emoji_size') or (18 if sys.platform == 'darwin' else 16))
    face = ('Apple Color Emoji', size) if sys.platform == 'darwin' else ('Segoe UI Emoji', size)
    columns = int(custom.get('columns') or 10)
    categories = dict(EMOJI)
    if custom.get('favourites'):
        categories = {'Favourites': str(custom['favourites']), **categories}

    def insert(symbol):
        try:
            if not entry.winfo_exists():
                return
            entry.insert('insert', symbol)
            entry.focus_set()
        except tk.TclError:
            pass

    for category, symbols in categories.items():
        page = ttk.Frame(notebook)
        notebook.add(page, text=tr(category))
        canvas = tk.Canvas(page, bg=look['button_background'], highlightthickness=0, width=int(custom.get('width') or 420), height=int(custom.get('height') or 300))
        bar = ttk.Scrollbar(page, command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side='right', fill='y')
        canvas.pack(fill='both', expand=True)
        grid = tk.Frame(canvas, bg=look['button_background'])
        canvas.create_window(0, 0, window=grid, anchor='nw')
        canvas._scroll_target = canvas
        for index, symbol in enumerate(symbols.split()):
            label = tk.Label(grid, text=symbol, font=face, bg=look['button_background'], cursor='hand2', padx=3, pady=2)
            label.grid(row=index // columns, column=index % columns)
            label.bind('<Button-1>', lambda _, symbol=symbol: insert(symbol))
        grid.bind('<Configure>', lambda _, canvas=canvas: canvas.configure(scrollregion=canvas.bbox('all')))
    window.bind('<Escape>', lambda _: window.destroy())
    try:
        x = (anchor or entry).winfo_rootx()
        y = (anchor or entry).winfo_rooty() + (anchor or entry).winfo_height() + 4
        window.geometry(f'+{x}+{y}')
    except tk.TclError:
        pass
    return window
