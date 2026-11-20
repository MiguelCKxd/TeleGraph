"""Chat list width chosen by the user (1.5.0.1).

Dragging the divider between the chat list and the conversation stores the
list's share of the window (chat-layout.json, not preferences.json, so a
drag does not rebuild every chat window). The share is restored whenever the
chat page is rebuilt (settings, menus, account switch) and kept when the
window is resized, so the list keeps its proportion. Until the user drags,
nothing is stored and the layout is exactly the previous default.

1.5.2: dragging the divider until the list (or the conversation) disappears
stores it as hidden; the window then works like a narrow one, with the
"Chats / Conversation" button. Settings › Appearance › "Restore chat list
size" forgets all of it and brings back the default layout.
"""
import tkinter as tk

from .preferences import read_json, write_json

MINIMUM, MAXIMUM = 0.08, 0.85
HIDDEN_PX = 40   # a pane narrower than this after a drag counts as dragged away


def _path(app):
    return app.service.root / 'chat-layout.json'


def _load(app):
    data = {}
    if not app.demo:
        data = read_json(_path(app), {})
        if not isinstance(data, dict):
            data = {}
    try:
        value = float(data.get('chat_list_share', 0.0))
    except (TypeError, ValueError):
        value = 0.0
    app._chat_list_share = value if MINIMUM <= value <= MAXIMUM else 0.0
    hidden = data.get('hidden_pane')
    app._chat_hidden_pane = hidden if hidden in ('list', 'conversation') else None


def stored(app):
    if getattr(app, '_chat_list_share', None) is None:
        _load(app)
    return app._chat_list_share


def hidden_pane(app):
    """'list', 'conversation' or None: which pane the user dragged away."""
    if getattr(app, '_chat_list_share', None) is None:
        _load(app)
    return getattr(app, '_chat_hidden_pane', None)


def _save(app):
    if app.demo:
        return
    data = {}
    if app._chat_list_share:
        data['chat_list_share'] = app._chat_list_share
    if app._chat_hidden_pane:
        data['hidden_pane'] = app._chat_hidden_pane
    try:
        write_json(_path(app), data)
    except OSError:
        pass


def reset(app):
    """Forget the stored width and any dragged-away pane (Appearance setting)."""
    stored(app)
    app._chat_list_share, app._chat_hidden_pane = 0.0, None
    if not app.demo:
        try:
            _path(app).unlink(missing_ok=True)
        except OSError:
            pass
    panes = getattr(app, 'chat_panes', None)
    try:
        if panes is None or not panes.winfo_exists():
            return
        # Re-adding the panes gives Tk's default split, exactly as at start.
        for pane in list(panes.panes()):
            panes.forget(pane)
    except tk.TclError:
        return
    if hasattr(app, 'adapt_chat_layout'):
        app.adapt_chat_layout()


def _sidebar_first(app, panes):
    panes_now = list(map(str, panes.panes()))
    return len(panes_now) == 2 and panes_now[0] == str(app.chat_sidebar)


def remember(app, panes):
    try:
        if len(panes.panes()) != 2:
            return
        width = panes.winfo_width()
        if width < 200:
            return
        position = panes.sashpos(0)
        list_px = position if _sidebar_first(app, panes) else width - position
        share = round(min(MAXIMUM, max(MINIMUM, list_px / width)), 4)
    except tk.TclError:
        return
    stored(app)
    hidden = 'list' if list_px < HIDDEN_PX else 'conversation' if width - list_px < HIDDEN_PX else None
    if hidden:
        app._chat_hidden_pane = hidden
        # Show what is left; the button switches to the other pane.
        app.compact_conversation = hidden == 'list'
        _save(app)
        if hasattr(app, 'adapt_chat_layout'):
            app.adapt_chat_layout()
        return
    if abs(share - app._chat_list_share) < 0.002:
        return
    app._chat_list_share = share
    _save(app)


def restore(app, panes):
    share = stored(app)
    if not share:
        return
    try:
        if len(panes.panes()) != 2:
            return
        width = panes.winfo_width()
        if width < 200:
            return
        target = int(width * share) if _sidebar_first(app, panes) else int(width * (1 - share))
        if abs(panes.sashpos(0) - target) > 2:
            panes.sashpos(0, target)
    except tk.TclError:
        pass


def install(app, panes):
    def released(_=None):
        app.root.after_idle(lambda: remember(app, panes))
    panes.bind('<ButtonRelease-1>', released, add='+')

    def resized(_=None):
        job = getattr(panes, '_share_job', None)
        if job is not None:
            try:
                panes.after_cancel(job)
            except tk.TclError:
                pass
        # after_idle runs before the next redraw: no visible two-step jump.
        panes._share_job = panes.after_idle(lambda: restore(app, panes))
    panes.bind('<Configure>', resized, add='+')
    # Coming back from another tab re-lays the panes out without a size change.
    panes.bind('<Map>', resized, add='+')
    notebook = getattr(app, 'notebook', None)
    if notebook is not None:
        notebook.bind('<<NotebookTabChanged>>', resized, add='+')
    app.root.after_idle(lambda: restore(app, panes))
