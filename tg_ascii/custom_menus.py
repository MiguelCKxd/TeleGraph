"""User-made menus (1.5.2, Complex features › Customizable menus).

Every menu kind has a folder ``<data>/menus/<kind>/`` with:

- ``style.json``      appearance and behaviour of TG-ASCII's own version of
                      that menu (colours, font, sizes, padding, title, rename /
                      hide / reorder options). Editing it makes it active.
- ``menu.py``         optional full replacement: a ``show(...)`` function the
                      app calls instead of its own menu (see the example).
- ``menu.py.example`` the documented starting point for ``menu.py``.
- ``LEEME.md``        instructions.

A kind with an active customization always opens the user's version. Any
error in user code falls back to the built-in menu and is written to
diagnostics.log; a broken file never leaves the app without that menu.
"""
import hashlib
import types
import json
from pathlib import Path
import sys

_enabled = False
_root = None
_modules = {}   # kind -> (content hash, module or None)
_styles = {}    # kind -> (content hash, dict or None)

COMMON_STYLE = {
    'background': '', 'foreground': '', 'button_background': '', 'button_foreground': '',
    'accent': '', 'border': '', 'font_family': '', 'font_size': 0, 'padding': 0,
    'width': 0, 'height': 0, 'title': '',
}
KIND_STYLE = {
    'context_menu': {'rename': {}, 'hide': [], 'order': [], 'max_width': 0, 'max_height': 0},
    'message_box': {'button_labels': {}, 'icon': '', 'wraplength': 0},
    'file_picker': {'show_hidden': False, 'start_folder': '', 'places': []},
    'color_picker': {'swatches': []},
    'emoji_picker': {'favourites': '', 'columns': 0, 'emoji_size': 0},
}
VIEWER_KINDS = ('image_viewer', 'video_player', 'audio_player', 'file_viewer', 'media_editor', 'file_preview')

SIGNATURES = {
    'context_menu': ('show(parent, entries, anchor, event, style)',
                     'entries: list of (label, callback[, enabled]) or None for a separator. Call callback() for the chosen item. Return the menu window (or None).'),
    'message_box': ('show(icon, buttons, title, message, parent, style)',
                    "icon: 'info'|'warning'|'error'|'question'; buttons: list of (label, value). Return the chosen value, or None if closed."),
    'file_picker': ('show(mode, options, style)',
                    "mode: 'open'|'open_many'|'save'|'folder'; options: title, filetypes, initialdir, initialfile, defaultextension. Return a path, a tuple of paths (open_many) or '' / () if cancelled."),
    'color_picker': ('show(color, options, style)', "color: '#rrggbb' or None. Return ((r, g, b), '#rrggbb') or (None, None)."),
    'emoji_picker': ('show(entry, style)', 'entry: the Entry/Text widget; insert the chosen emoji with entry.insert("insert", emoji).'),
    'image_viewer': ('show(app, message, peer, style)', 'Open the photo of this Telegram message your way. Return True if handled.'),
    'video_player': ('show(app, message, peer, style)', 'Play the video of this message your way. Return True if handled.'),
    'audio_player': ('show(app, message, peer, style)', 'Play the audio of this message your way. Return True if handled.'),
    'file_viewer': ('show(app, message, peer, style)', 'Open this received file your way. Return True if handled.'),
    'media_editor': ('show(app, path, accepted, style)', 'Edit the photo/video at path, then call accepted(new_path). Return True if handled.'),
    'file_preview': ('show(app, path, accepted, style)', 'Preview the file at path; call accepted(path) to attach it. Return True if handled.'),
}


def configure(values, root=None):
    global _enabled, _root
    features = (values or {}).get('advanced_features') or {}
    _enabled = isinstance(features, dict) and features.get('custom_menus') is True
    if root is not None:
        _root = Path(root)


def enabled():
    return _enabled


def folder(kind):
    base = _root or Path.home() / '.tg-ascii'
    return base / 'menus' / kind


def template_style(kind):
    style = dict(COMMON_STYLE)
    if kind in KIND_STYLE:
        style.update(KIND_STYLE[kind])
    if kind in VIEWER_KINDS:
        style = {'title': '', 'background': ''}
    return style


def _template_text(kind):
    return json.dumps(template_style(kind), indent=2, ensure_ascii=False) + '\n'


def _digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def ensure(kind):
    """Create the folder with its starting files (never overwrites user files)."""
    path = folder(kind)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    style = path / 'style.json'
    if not style.exists():
        text = _template_text(kind)
        style.write_text(text, encoding='utf-8')
        (path / '.template').write_text(_digest(text), encoding='utf-8')
    example = path / 'menu.py.example'
    example.write_text(_example(kind), encoding='utf-8')
    (path / 'LEEME.md').write_text(_readme(kind), encoding='utf-8')
    return path


def _style_active(kind):
    path = folder(kind) / 'style.json'
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding='utf-8')
        template = (folder(kind) / '.template').read_text(encoding='utf-8').strip()
    except OSError:
        return False
    return _digest(text) != template


def active(kind):
    """True when this kind opens the user's own version."""
    if not _enabled:
        return False
    return (folder(kind) / 'menu.py').is_file() or _style_active(kind)


def style(kind):
    """The user's style for this kind (merged over the template), or {}."""
    if not active(kind):
        return {}
    path = folder(kind) / 'style.json'
    try:
        raw = path.read_bytes()
    except OSError:
        return {}
    # Keyed by content, not mtime: Windows timestamps can miss a quick edit.
    key = _digest_bytes(raw)
    cached = _styles.get(kind)
    if cached and cached[0] == key:
        return cached[1] or {}

    try:
        data = json.loads(raw.decode('utf-8'))
        merged = template_style(kind)
        if isinstance(data, dict):
            merged.update(data)
    except (OSError, ValueError) as exc:
        _note(kind, exc)
        merged = {}
    _styles[kind] = (key, merged)
    return merged


def replacement(kind):
    """The user's ``show`` function for this kind, or None."""
    if not _enabled:
        return None
    path = folder(kind) / 'menu.py'
    if not path.is_file():
        return None
    try:
        source = path.read_bytes()
    except OSError:
        return None
    key = _digest_bytes(source)
    cached = _modules.get(kind)
    if cached and cached[0] == key:
        module = cached[1]
    else:
        module = None
        try:
            # Compiled from the text just read: no __pycache__ in the user's
            # folder and no stale bytecode after a quick edit.
            module = types.ModuleType(f'tg_ascii_user_menu_{kind}')
            module.__file__ = str(path)
            exec(compile(source, str(path), 'exec'), module.__dict__)
        except Exception as exc:
            _note(kind, exc)
            module = None
        _modules[kind] = (key, module)
    return getattr(module, 'show', None) if module is not None else None


def run(kind, fallback, *args):
    """Call the user's menu if there is one; otherwise (or on error) the built-in."""
    show = replacement(kind)
    if show is not None:
        try:
            return show(*args, style(kind))
        except Exception as exc:
            _note(kind, exc)
    return fallback()


def _note(kind, exc):
    try:
        from .recovery import record_failure
        record_failure(_root or Path.home() / '.tg-ascii', f'custom_menu:{kind}', exc)
    except Exception:
        pass


def open_folder(kind, on_error=None):
    """Create the folder if needed and show it in Finder / File Explorer."""
    path = ensure(kind)
    import threading
    def work():
        try:
            from .native_open import launch
            launch(path)
        except Exception as error:
            if on_error is not None:
                on_error(error)
    threading.Thread(target=work, name='tg-open-menu-folder', daemon=True).start()
    return path


def _readme(kind):
    signature, detail = SIGNATURES.get(kind, ('show(...)', ''))
    return f"""# Menú «{kind}» de TG-ASCII

Esta carpeta es tuya. Con «Funciones complejas › Menús personalizables»
activado, lo que pongas aquí se usa cada vez que se abre este menú.

## 1. Cambiar su aspecto y comportamiento: `style.json`
Edita `style.json` (colores `#rrggbb`, `font_family`, `font_size`,
`padding`, `width`, `height`, `title`… y las opciones propias de este menú).
En cuanto el archivo es distinto del original, este menú usa siempre la
versión de TG-ASCII con tu estilo. Para volver al original, borra
`style.json`: se vuelve a crear la próxima vez que pulses la carpeta.

## 2. Sustituirlo por completo: `menu.py`
Copia `menu.py.example` como `menu.py` y cámbialo a tu gusto. La app llama a:

    {signature}

{detail}

`style` es el contenido de tu `style.json`. Si `menu.py` falla, la app usa
su menú normal y anota el error en `diagnostics.log`.

**Aviso:** `menu.py` es código Python que la app ejecuta con tus permisos.
Pon aquí solo código que hayas escrito tú o del que te fíes.

---

# TG-ASCII menu «{kind}»

This folder is yours. With Complex features › Customizable menus on, it is
used every time this menu opens. Edit `style.json` to restyle TG-ASCII's own
version, or copy `menu.py.example` to `menu.py` to replace it entirely:

    {signature}

{detail}
"""


def _example(kind):
    signature, detail = SIGNATURES.get(kind, ('show(...)', ''))
    bodies = {
        'context_menu': '''import tkinter as tk


def show(parent, entries, anchor, event, style):
    """A plain Tk menu with your own colours; any widget/window works."""
    menu = tk.Menu(parent, tearoff=False, bg=style.get('background') or None,
                   fg=style.get('foreground') or None)
    for entry in entries:
        if entry is None:
            menu.add_separator()
            continue
        label, callback = entry[:2]
        enabled = entry[2] if len(entry) > 2 else True
        menu.add_command(label=str(label), command=callback,
                         state='normal' if enabled else 'disabled')
    x, y = (event.x_root, event.y_root) if event else parent.winfo_pointerxy()
    menu.tk_popup(x, y)
    return menu
''',
        'message_box': '''from tkinter import messagebox


def show(icon, buttons, title, message, parent, style):
    """Example: always use simple yes/no or OK boxes with a prefix."""
    text = (style.get('title') or '') + str(message or '')
    values = [value for _, value in buttons]
    if 'yes' in values:
        return 'yes' if messagebox.askyesno(title, text, parent=parent) else 'no'
    messagebox.showinfo(title, text, parent=parent)
    return values[0] if values else None
''',
        'file_picker': '''from tkinter import filedialog


def show(mode, options, style):
    """Example: the device picker, always starting in your chosen folder."""
    options = dict(options)
    if style.get('start_folder'):
        options['initialdir'] = style['start_folder']
    if mode == 'open_many':
        return filedialog.askopenfilenames(**options)
    if mode == 'save':
        return filedialog.asksaveasfilename(**options)
    if mode == 'folder':
        return filedialog.askdirectory(**options)
    return filedialog.askopenfilename(**options)
''',
        'color_picker': '''from tkinter import colorchooser


def show(color, options, style):
    return colorchooser.askcolor(color, **options)
''',
        'emoji_picker': '''import tkinter as tk


def show(entry, style):
    """Example: a small row of your favourite emoji."""
    window = tk.Toplevel(entry)
    for emoji in (style.get('favourites') or '😀 👍 ❤️ 😂 🔥 🙏').split():
        tk.Button(window, text=emoji, command=lambda e=emoji: entry.insert('insert', e)).pack(side='left')
    return window
''',
    }
    viewer = '''def show(app, message, peer, style):
    """Return False to let TG-ASCII open it as usual."""
    # Example: always open with the device app.
    app.open_message_natively(message, peer)
    return True
'''
    editor = '''def show(app, path, accepted, style):
    """Return False to let TG-ASCII handle it as usual."""
    accepted(path)  # Example: attach without editing.
    return True
'''
    body = bodies.get(kind) or (editor if kind in ('media_editor', 'file_preview') else viewer)
    return f'"""TG-ASCII custom menu for «{kind}». Rename to menu.py to use it.\n\nCalled as: {signature}\n{detail}\n"""\n' + body


def handled(kind, *args):
    """Viewers/editors: True if the user's menu.py took care of it."""
    show = replacement(kind)
    if show is None:
        return False
    try:
        return bool(show(*args, style(kind)))
    except Exception as exc:
        _note(kind, exc)
        return False
