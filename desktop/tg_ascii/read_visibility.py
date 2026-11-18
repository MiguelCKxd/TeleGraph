"""Which messages are on screen right now (1.4.1 read receipts).

A chat is marked as read only up to the newest message the user can actually
see: unread messages below the viewport stay unread (and keep counting in the
chat list) until they are scrolled into view. The no-read preview window has
its own widget and never calls this.
"""
import tkinter as tk


def _bubble_ids(canvas):
    height = canvas.winfo_height()
    if height <= 1:
        return []
    top, bottom = canvas.canvasy(0), canvas.canvasy(height)
    width = max(1, canvas.winfo_width())
    ids = set()
    for item in canvas.find_overlapping(0, top + 2, width, bottom - 2):
        for tag in canvas.gettags(item):
            if tag.startswith('message:'):
                try:
                    ids.add(int(tag.split(':', 1)[1]))
                except ValueError:
                    pass
    return sorted(ids)


def _text_ids(text, messages):
    height = text.winfo_height()
    if height <= 1:
        return []
    first = text.index('@0,0')
    last = text.index(f'@0,{height - 1}')
    ids = []
    for message in messages:
        ranges = text.tag_ranges(f'msg_{message.id}')
        for start, end in zip(ranges[::2], ranges[1::2]):
            # Visible if the message range overlaps [first, last].
            if text.compare(start, '<=', last) and text.compare(end, '>', first):
                ids.append(message.id)
                break
    return ids


def visible_message_ids(app):
    """Ids of real (sent) messages currently drawn in the open chat's viewport."""
    try:
        canvas_view = getattr(app, '_canvas_chat_view', app.preferences.values.get('bubbles', True))
        bubble = getattr(app, 'bubble_view', None)
        if canvas_view and bubble is not None and bubble.winfo_ismapped():
            ids = _bubble_ids(bubble)
        else:
            history = getattr(app, 'history', None)
            if history is None or not history.winfo_ismapped():
                return []
            ids = _text_ids(history, app.messages)
    except (tk.TclError, AttributeError):
        return []
    known = {message.id for message in app.messages}
    return [ident for ident in ids if ident in known and ident > 0]


def schedule(app, delay=250):
    """Coalesce scroll/render bursts into one read check."""
    if getattr(app, '_read_check_job', None) is not None:
        return
    def run():
        app._read_check_job = None
        try:
            app.acknowledge_visible()
        except Exception:
            pass
    try:
        app._read_check_job = app.root.after(delay, run)
    except (tk.TclError, AttributeError):
        app._read_check_job = None


def first_unread_id(messages, unread):
    """The oldest of the last ``unread`` incoming messages (official apps open there)."""
    if not unread:
        return None
    incoming = [message.id for message in messages if not message.outgoing and not getattr(message, 'service', False)]
    if not incoming:
        return None
    return incoming[-unread] if unread <= len(incoming) else incoming[0]


def open_at_first_unread(app, ident):
    """Put the first unread message at the top of the viewport (not the bottom)."""
    if ident is None:
        return False
    try:
        canvas_view = getattr(app, '_canvas_chat_view', app.preferences.values.get('bubbles', True))
        if canvas_view and getattr(app, 'bubble_view', None) is not None:
            view = app.bubble_view
            if ident not in view.locations:
                return False
            total = float(view.cget('scrollregion').split()[-1])
            view.yview_moveto(max(0, view.locations[ident] - 8) / max(1, total))
            return True
        mark = f'message_{ident}'
        if mark in app.history.mark_names():
            app.history.yview(mark)
            return True
    except (tk.TclError, AttributeError, ValueError, IndexError):
        pass
    return False


WATCH_MS = 1500


def needs_check(app):
    """Something in the open chat may still be unread by us."""
    if getattr(app, 'active', None) is None or not getattr(app, 'messages', None):
        return False
    chat = next((item for item in getattr(app, 'chats', ()) if item.id == app.active), None)
    if chat is not None and (getattr(chat, 'unread', 0) or getattr(chat, 'unread_mark', False)):
        return True
    acked = getattr(app, '_read_ack', {}).get((app.ui_account, app.active), 0)
    newest = max((message.id for message in app.messages if not message.outgoing), default=0)
    return newest > acked


def watch(app):
    """1.5.0.2 safety net: every 1.5 s, while the open chat is on screen and
    has something unread, look again. Covers every way of coming back to a
    chat (another tab, reopening the window, clicking the open chat, a
    message arriving while the window was in the background)."""
    def tick():
        try:
            if getattr(app, 'closed', False) or getattr(app, 'closing', False):
                return
            if getattr(app, 'stage', None) == 'ready' and needs_check(app) and app.chat_visible():
                schedule(app, 0)
                evidence(app)
        except Exception:
            pass
        try:
            app.root.after(WATCH_MS, tick)
        except (tk.TclError, AttributeError):
            pass
    try:
        app.root.after(WATCH_MS, tick)
    except (tk.TclError, AttributeError):
        pass


def at_bottom(app):
    """True when the end of the open chat is on screen."""
    try:
        canvas_view = getattr(app, '_canvas_chat_view', app.preferences.values.get('bubbles', True))
        view = app.bubble_view if canvas_view and getattr(app, 'bubble_view', None) is not None else app.history
        return float(view.yview()[1]) >= 0.995
    except (tk.TclError, AttributeError, ValueError, IndexError):
        return False



def evidence(app):
    """If something on screen stays unread, write why to diagnostics.log once
    per chat and session (reason codes only, never content). Lets a later
    report point at the real cause instead of guessing (1.5.0.2)."""
    import time
    key = (app.ui_account, app.active)
    acked = getattr(app, '_read_ack', {}).get(key, 0)
    visible = visible_message_ids(app)
    chat = next((item for item in getattr(app, 'chats', ()) if item.id == app.active), None)
    unread = getattr(chat, 'unread', 0) if chat is not None else 0
    stuck = None
    if visible and max(visible) > acked:
        stuck = 'visible_not_sent'
    elif at_bottom(app) and unread and visible:
        stuck = 'count_stays'
    since = app.__dict__.setdefault('_read_stuck_since', {})
    if stuck is None:
        since.pop(key, None)
        return
    first = since.setdefault((key, stuck), time.monotonic())
    noted = app.__dict__.setdefault('_read_stuck_noted', set())
    if time.monotonic() - first < (8 if stuck == 'visible_not_sent' else 20) or (key, stuck) in noted:
        return
    noted.add((key, stuck))
    flags = [stuck, getattr(chat, 'kind', '?')]
    if time.monotonic() < getattr(app, '_read_hold_until', 0):
        flags.append('hold')
    if key in getattr(app, '_read_pending', set()):
        flags.append('pending')
    if getattr(app, '_canvas_chat_view', False):
        flags.append('canvas')
    from .recovery import record_failure
    record_failure(app.service.root, 'read_stuck:' + '/'.join(flags), RuntimeError('read stuck'))
