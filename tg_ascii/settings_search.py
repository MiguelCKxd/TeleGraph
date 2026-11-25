"""Search inside Settings (3.2).

Every option already built in the Settings page is indexed by its visible
text. A result switches to its category, scrolls the option into view and
gives it the focus. Matching ignores case and accents.
"""
import tkinter as tk
from tkinter import ttk
import unicodedata

from .interface_layout import caption

TEXT_CLASSES = {'TLabel', 'Label', 'TCheckbutton', 'Checkbutton', 'TButton', 'Button',
                'TRadiobutton', 'Radiobutton', 'TLabelframe', 'Labelframe'}
LIMIT = 12


def fold(text):
    decomposed = unicodedata.normalize('NFKD', str(text or ''))
    return ' '.join(''.join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold().split())


def matches(query, text):
    words = fold(query).split()
    folded = fold(text)
    return bool(words) and all(word in folded for word in words)


def walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from walk(child)


def index(sections, labels):
    """[(category, label, text, widget)] for every text-bearing option."""
    found = []
    for category, frame in sections.items():
        seen = set()
        for widget in walk(frame):
            if widget.winfo_class() not in TEXT_CLASSES:
                continue
            try:
                text = ' '.join(str(widget.cget('text')).split())
            except tk.TclError:
                continue
            if not text or len(text) > 240 or text in seen:
                continue
            seen.add(text)
            found.append((category, labels.get(category, category), text, widget))
    return found


def search(entries, query, limit=LIMIT):
    if not fold(query):
        return []
    hits = [entry for entry in entries if matches(query, entry[2]) or matches(query, entry[1])]
    # Option text matches first, then whole-category matches.
    hits.sort(key=lambda entry: (not matches(query, entry[2]), entry[1], entry[2]))
    return hits[:limit]


def reveal(widget):
    """Scroll the option's settings page so the widget is visible, then focus it."""
    canvas, inner = None, widget
    while inner is not None:
        parent = inner.master
        if parent is not None and getattr(parent, '_scroll_target', None) is not None and isinstance(parent, ttk.Frame) \
                and isinstance(getattr(parent, 'master', None), tk.Canvas):
            canvas, inner = parent.master, parent
            break
        inner = parent
    try:
        widget.update_idletasks()
        if canvas is not None:
            top = widget.winfo_rooty() - inner.winfo_rooty()
            height = max(1, inner.winfo_height())
            canvas.yview_moveto(max(0, top - 24) / height)
        if str(widget.cget('takefocus')) != '0' and widget.winfo_class() not in ('TLabel', 'Label'):
            widget.focus_set()
    except tk.TclError:
        pass


def build(parent, sections, labels, choose_category, categories):
    """Search field plus a results list shown while there is a query."""
    frame = ttk.Frame(parent)
    query = tk.StringVar(master=parent)
    ttk.Label(frame, text=caption('Search settings', 'Buscar en ajustes'), style='Muted.TLabel').pack(anchor='w')
    entry = ttk.Entry(frame, textvariable=query)
    entry.pack(fill='x', pady=(2, 4))
    results = tk.Listbox(frame, height=6, exportselection=False, activestyle='none')
    shown = []
    state = {'entries': None}

    def refresh(*_):
        text = query.get()
        if not fold(text):
            results.pack_forget()
            return
        if state['entries'] is None:
            state['entries'] = index(sections, labels)
        shown[:] = search(state['entries'], text)
        results.delete(0, 'end')
        for _category, label, option, _widget in shown:
            results.insert('end', f'{label} › {option}')
        if not shown:
            results.insert('end', caption('No settings found', 'No se encontraron ajustes'))
        results.configure(height=max(1, min(6, len(shown) or 1)))
        results.pack(fill='x')

    def open_selected(_=None):
        selection = results.curselection() or ((0,) if shown else ())
        if not selection or selection[0] >= len(shown):
            return
        category, _label, _option, widget = shown[selection[0]]
        choose_category(categories.index(category))
        frame.after_idle(lambda: reveal(widget))

    query.trace_add('write', refresh)
    entry.bind('<Return>', open_selected)
    entry.bind('<Down>', lambda _: (results.focus_set(), results.selection_set(0)) if shown else None)
    results.bind('<Return>', open_selected)
    results.bind('<Double-Button-1>', open_selected)
    results.bind('<ButtonRelease-1>', open_selected)
    entry.bind('<Escape>', lambda _: query.set(''))
    frame.query, frame.entry, frame.results, frame.open_selected = query, entry, results, open_selected
    frame.reindex = lambda: state.update(entries=None)
    return frame
