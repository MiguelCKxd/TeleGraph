"""RTL interface alignment without rewriting user text, offsets or clipboard data.

Tk does not provide Qt's complete bidi text layout on every platform. This module
mirrors default navigation and aligns controls; it deliberately never reshapes or
reverses strings, which would corrupt Telegram entities, searches and drafts.
"""
import sys
import tkinter as tk
from tkinter import font as tkfont

RTL_LANGUAGES = frozenset(('ar', 'ur', 'he'))
TEXT_TAG = '_tg_ui_direction'


def rtl_language(language=None):
    if language is None:
        from .i18n import get_language
        language = get_language()
    return language in RTL_LANGUAGES


def mirrored_anchor(value):
    value = str(value)
    return {'w': 'e', 'e': 'w', 'nw': 'ne', 'ne': 'nw', 'sw': 'se', 'se': 'sw'}.get(value, value)


def pane_order(sidebar, conversation):
    return [conversation, sidebar] if rtl_language() else [sidebar, conversation]


def flow_position(position, available):
    x, y, width, height = position
    return (max(0, available - x - width), y, width, height) if rtl_language() else position


def ui_font_family(root, requested, language=None):
    """Keep explicit choices; automatic RTL defaults use a real script font."""
    if language is None:
        from .i18n import get_language
        language = get_language()
    if requested or language not in RTL_LANGUAGES:
        return requested
    cached = getattr(root, '_tg_rtl_font', None)
    if isinstance(cached, tuple) and cached[0] == language:
        return cached[1]
    mac = sys.platform == 'darwin'
    preferred = {
        'ar': ('Geeza Pro', 'Arial') if mac else ('Segoe UI', 'Arial', 'Noto Sans Arabic'),
        'ur': ('Noto Nastaliq Urdu', 'Geeza Pro', 'Arial') if mac else ('Urdu Typesetting', 'Segoe UI', 'Noto Nastaliq Urdu'),
        'he': ('Arial Hebrew', 'Arial') if mac else ('Segoe UI', 'Arial', 'Noto Sans Hebrew'),
    }[language]
    installed = {name.casefold(): name for name in tkfont.families(root)}
    family = next((installed[name.casefold()] for name in preferred if name.casefold() in installed), requested)
    root._tg_rtl_font = (language, family)
    return family


def align_text(widget):
    """A display-only tag leaves the Text contents and entity indices intact."""
    if not rtl_language():
        if getattr(widget, '_tg_direction_tag', False):
            widget.tag_remove(TEXT_TAG, '1.0', 'end')
        return
    widget.tag_configure(TEXT_TAG, justify='right')
    widget.tag_add(TEXT_TAG, '1.0', 'end')
    # Other formatting tags can still control colors, links, size and selection.
    widget.tag_lower(TEXT_TAG)
    widget._tg_direction_tag = True


def apply_widget(widget):
    """Apply one mapped widget once; no periodic traversal or text mutation."""
    if not hasattr(widget, 'winfo_class'):
        return
    rtl = rtl_language()
    if getattr(widget, '_tg_direction_applied', None) is rtl:
        return
    widget._tg_direction_applied = rtl
    if not rtl and not hasattr(widget, '_tg_direction_original'):
        return
    try:
        kind = widget.winfo_class()
        options = set(widget.keys())
        saved = getattr(widget, '_tg_direction_original', None)
        if saved is None:
            saved = {key: widget.cget(key) for key in ('anchor', 'justify') if key in options}
            if widget.winfo_manager() == 'pack':
                saved['pack_anchor'] = widget.pack_info().get('anchor', 'center')
            widget._tg_direction_original = saved
        changes = {}
        if 'anchor' in saved:
            changes['anchor'] = mirrored_anchor(saved['anchor']) if rtl else saved['anchor']
        if 'justify' in saved:
            changes['justify'] = ('right' if str(saved['justify']) != 'center' else 'center') if rtl else saved['justify']
        if changes:
            widget.configure(**changes)
        if 'pack_anchor' in saved and widget.winfo_manager() == 'pack':
            widget.pack_configure(anchor=mirrored_anchor(saved['pack_anchor']) if rtl else saved['pack_anchor'])
        if kind == 'Treeview':
            columns = ('#0', *widget['columns'])
            originals = getattr(widget, '_tg_column_anchors', None)
            if originals is None:
                originals = {column: widget.column(column, 'anchor') for column in columns}
                widget._tg_column_anchors = originals
            for column, anchor in originals.items():
                widget.column(column, anchor=mirrored_anchor(anchor) if rtl else anchor)
        if kind == 'Text':
            align_text(widget)
    except (tk.TclError, AttributeError, KeyError):
        pass  # A native popup can disappear while Map is delivered.


def install(root):
    """One Map hook per Tcl interpreter, including later dialogs and linked UI."""
    if getattr(root, '_tg_direction_installed', False):
        return
    root._tg_direction_installed = True
    root.bind_all('<Map>', lambda event: apply_widget(event.widget), add='+')


def align_composer(widget):
    # Bind key-release, not <<Modified>>: draft logic owns the modified flag.
    # Programmatic inserts and paste use Composer.insert's display-only hook.
    align_text(widget)
    widget.bind('<KeyRelease>', lambda _: align_text(widget), add='+')
