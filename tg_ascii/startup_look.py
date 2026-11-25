"""The user's look from the very first frame: start, lock and loading screens.

Before the main interface is built, the window used to show Tk's default
colours, fonts and the fixed product name. This applies the saved palette,
font and display name (3.2) as soon as the window exists.
"""
import tkinter as tk
import tkinter.font
from tkinter import ttk

from . import APP_NAME


def saved_values():
    """Validated preferences, without touching Telegram or the account data."""
    try:
        from .preferences import Preferences
        return dict(Preferences().values)
    except Exception:
        return {}


def display_name(values=None):
    values = saved_values() if values is None else values
    name = values.get('app_display_name') if isinstance(values, dict) else ''
    return name.strip() if isinstance(name, str) and name.strip() else APP_NAME


def apply(root, values=None, title=None):
    """Colour the empty window and the ttk styles used by the early screens."""
    values = saved_values() if values is None else values
    try:
        from .appearance import app_palette
        from .themes import set_palette
        colors = app_palette(values)
        set_palette(colors)
    except Exception:
        return None
    family = values.get('font_family') or ''
    size = values.get('font_size') if type(values.get('font_size')) is int else 12
    try:
        from .typography import configure_fonts
        family = configure_fonts(root, family, size)
    except tk.TclError:
        family = 'TkDefaultFont'
    try:
        root.configure(background=colors['bg'])
        style = ttk.Style(root)
        style.theme_use('clam')
        accent = values.get('accent_color') or colors.get('strong', colors['text'])
        style.configure('.', background=colors['bg'], foreground=colors['text'], font=(family, size))
        for name in ('TFrame', 'TLabel', 'TCheckbutton'):
            style.configure(name, background=colors['bg'], foreground=colors['text'])
        style.configure('TButton', background=colors['panel'], foreground=colors['text'])
        style.configure('TEntry', fieldbackground=colors['panel'], foreground=colors['text'])
        style.configure('Muted.TLabel', background=colors['bg'], foreground=colors['muted'])
        style.configure('Startup.Title.TLabel', background=colors['bg'], foreground=accent, font=(family, 22, 'bold'))
        root.title(title or display_name(values))
    except tk.TclError:
        return None
    return colors


def heading(parent, values=None):
    """The chosen app name, big, at the top of a start or loading card."""
    # The option database sets every widget's -font, which overrides styles.
    family = tk.font.nametofont('TkDefaultFont', root=parent).cget('family')
    return ttk.Label(parent, text=display_name(values), style='Startup.Title.TLabel', font=(family, 22, 'bold'))
