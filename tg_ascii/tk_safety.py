"""Keep Tk image destruction on the thread that owns the Tcl interpreter.

Real crash (macOS, TG-ASCII 1.3.1, 2026-11-01): Python's cyclic garbage
collector ran on the asyncio worker thread (inside a task step) and collected a
cycle that held a ``tkinter.PhotoImage``. Its ``__del__`` then executed
``image delete`` from that worker thread and Tk 9 crashed with SIGSEGV in
``Tk_FreeGC``/``TkImgDisposeInstance``. Which thread runs a GC pass is not
under the application's control, so a "never drop images on the worker" rule
cannot be enforced by code review alone.

This guard keeps the exact original behaviour on the Tk (main) thread. On any
other thread it only *queues* the image name; ``drain()``, called from the Tk
event pump, performs the deletion. Images are therefore still released, just
a few milliseconds later and on the correct thread.
"""
from collections import deque
import threading
import tkinter

_pending = deque()
_installed = False
_owner = None


def _on_owner_thread():
    return threading.current_thread() is (_owner or threading.main_thread())


def _defer(tk, name):
    if tk is not None and name:
        _pending.append((tk, name))


def install():
    """Idempotent. Call from the thread that will run Tk's mainloop."""
    global _installed, _owner
    if _installed:
        return
    _owner = threading.current_thread()
    original = tkinter.Image.__del__

    def __del__(self):
        if _on_owner_thread():
            return original(self)
        name = getattr(self, 'name', None)
        _defer(getattr(self, 'tk', None), name)
        self.name = None

    tkinter.Image.__del__ = __del__
    try:
        from PIL import ImageTk
        pil_original = ImageTk.PhotoImage.__del__

        def pil_del(self):
            if _on_owner_thread():
                return pil_original(self)
            try:
                photo = self._PhotoImage__photo
            except AttributeError:
                return
            name = getattr(photo, 'name', None)
            _defer(getattr(photo, 'tk', None), name)
            photo.name = None  # The wrapped tkinter image must not delete it again.

        ImageTk.PhotoImage.__del__ = pil_del
    except (ImportError, AttributeError):
        pass
    _installed = True


def drain(limit=256):
    """Delete images queued by other threads. Must run on the Tk thread."""
    if not _pending or not _on_owner_thread():
        return 0
    done = 0
    while _pending and done < limit:
        tk, name = _pending.popleft()
        try:
            tk.call('image', 'delete', name)
        except (tkinter.TclError, RuntimeError):
            pass  # Already deleted, or its interpreter was destroyed.
        done += 1
    return done


def pending():
    return len(_pending)
