"""Recent searches under the desktop's search fields (3.2).

The strip appears while its field is focused and empty: the account's last
queries for that search (tg_ascii.recent_searches) and, where given,
Telegram's own suggestions (contacts.getTopPeers). A query is remembered when
it is submitted or when one of its results is opened.
"""
import tkinter as tk
from tkinter import ttk

from .i18n import tr
from .interface_layout import caption

SHOWN = 6


def store(app):
    owner = getattr(app, '_linked_owner', None) or app
    store = getattr(owner, '_recent_search_store', None)
    if store is None:
        from .recent_searches import RecentSearches
        root = getattr(getattr(owner, 'service', None), 'root', None)
        if root is None:
            return None
        store = owner._recent_search_store = RecentSearches(root)
    return store


def remember(app, scope, query):
    """Save a submitted query (never in demo mode or for empty text)."""
    query = ' '.join(str(query or '').split())
    if getattr(app, 'demo', False) or not query:
        return
    recent = store(app)
    if recent is None:
        return
    try:
        recent.remember(app.ui_account, scope, query)
    except Exception:
        return


class RecentStrip:
    """Chips of recent queries (and optional suggestions) for one field."""

    def __init__(self, app, parent, variable, scope, pick=None, suggestions=None, before=None):
        self.app, self.variable, self.scope = app, variable, scope
        self.pick = pick or (lambda query: None)
        self.suggestions = suggestions  # callable(done) -> fills [(label, callback)]
        self.entry = getattr(variable, 'entry', None)
        self.frame = ttk.Frame(parent)
        self.before = before
        self.shown = False
        self._closed = False
        self._hide_job = None
        self._suggested = []
        if self.entry is not None:
            self.entry.bind('<FocusIn>', lambda _: self.refresh(), add='+')
            self.entry.bind('<FocusOut>', lambda _: self.hide_later(), add='+')
        self._trace = variable.trace_add('write', lambda *_: self.refresh())
        self.frame.bind('<Destroy>', self.destroyed, add='+')
        if suggestions is not None:
            suggestions(self.suggested)

    def destroyed(self, event=None):
        if event is not None and event.widget is not self.frame:
            return
        self._closed = True
        self.cancel_hide()
        self.shown = False
        self._suggested.clear()
        try:
            self.variable.trace_remove('write', self._trace)
        except (tk.TclError, ValueError):
            pass

    def suggested(self, items):
        if self._closed:
            return
        self._suggested = list(items or ())[:SHOWN]
        if self.shown:
            self.refresh(force=True)

    def queries(self):
        if getattr(self.app, 'demo', False):
            return []
        recent = store(self.app)
        try:
            return recent.list(self.app.ui_account, self.scope)[:SHOWN] if recent is not None else []
        except Exception:
            return []

    def focused(self):
        try:
            widget = self.frame.focus_get()
        except (tk.TclError, KeyError):
            return False
        return widget is not None and (widget is self.entry or str(widget).startswith(str(self.frame)))

    def cancel_hide(self):
        if self._hide_job:
            try:
                self.frame.after_cancel(self._hide_job)
            except tk.TclError:
                pass
            self._hide_job = None

    def refresh(self, force=False):
        if self._closed:
            return
        self.cancel_hide()
        try:
            empty = not self.variable.get().strip()
        except tk.TclError:
            return
        if not empty or not (self.focused() or force):
            self.hide()
            return
        queries = self.queries()
        if not queries and not self._suggested:
            self.hide()
            return
        for child in self.frame.winfo_children():
            child.destroy()
        from .scrolling import FlowFrame
        if queries:
            head = ttk.Frame(self.frame)
            head.pack(fill='x')
            ttk.Label(head, text=caption('Recent searches', 'Búsquedas recientes'), style='Muted.TLabel').pack(side='left')
            ttk.Button(head, text=caption('Clear', 'Borrar'), takefocus=False, command=self.clear).pack(side='right')
            chips = FlowFrame(self.frame)
            chips.pack(fill='x', pady=(2, 4))
            for query in queries:
                ttk.Button(chips, text='🕘 ' + query, takefocus=False,
                           command=lambda q=query: self.choose(q)).pack(side='left', padx=2, pady=2)
        if self._suggested:
            ttk.Label(self.frame, text=caption('Frequent', 'Frecuentes'), style='Muted.TLabel').pack(anchor='w')
            chips = FlowFrame(self.frame)
            chips.pack(fill='x', pady=(2, 4))
            for label, callback in self._suggested:
                ttk.Button(chips, text=label, takefocus=False, command=callback).pack(side='left', padx=2, pady=2)
        if not self.shown:
            options = {'fill': 'x', 'pady': (0, 4)}
            if self.before is not None:
                options['before'] = self.before
            self.frame.pack(**options)
            self.shown = True

    def hide_later(self):
        # A click on a chip moves the focus first; let it land.
        if self._closed:
            return
        self.cancel_hide()
        def finish():
            self._hide_job = None
            if not self.focused():
                self.hide()
        try:
            self._hide_job = self.frame.after(250, finish)
        except tk.TclError:
            pass

    def hide(self):
        if self.shown:
            self.frame.pack_forget()
            self.shown = False

    def choose(self, query):
        self.variable.set(query)
        remember(self.app, self.scope, query)
        self.hide()
        self.pick(query)

    def clear(self):
        recent = store(self.app)
        if recent is not None:
            try:
                recent.clear(self.app.ui_account, self.scope)
            except Exception:
                pass
        self.refresh(force=True)
