"""Swipe right to go back on desktop (3.2).

A two-finger horizontal swipe that can no longer scroll anything towards the
left edge goes back, as in browsers and Telegram's phone apps. Every window
registers what "back" means for it (a dialog closes, the main window returns
to the chat list). Keyboard: Command-[ on macOS, Alt-Left elsewhere.
"""
import sys
import time
import tkinter as tk

THRESHOLD = 140      # pixels of unconsumed horizontal travel
WINDOW = 0.45        # seconds within which the travel must happen
COOLDOWN = 0.8       # one swipe, one step back


class BackTracker:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.travel = 0.0
        self.started = 0.0
        self.blocked_until = 0.0

    def feed(self, amount):
        """``amount`` < 0 moves content towards its start (a swipe "back").

        Returns True once when the swipe should go back.
        """
        now = self.clock()
        if now < self.blocked_until:
            return False
        if amount >= 0 or now - self.started > WINDOW:
            self.travel, self.started = 0.0, now
            if amount >= 0:
                return False
        self.travel += -amount
        if self.travel >= THRESHOLD:
            self.travel = 0.0
            self.blocked_until = now + COOLDOWN
            return True
        return False


def install(window, action):
    """Make ``action`` the back step of ``window`` (a Tk or Toplevel)."""
    window._back_action = action
    window._back_tracker = BackTracker()
    sequence = '<Command-bracketleft>' if sys.platform == 'darwin' else '<Alt-Left>'
    try:
        window.bind(sequence, lambda _: (run(window), 'break')[1], add='+')
    except tk.TclError:
        pass


def run(window):
    action = getattr(window, '_back_action', None)
    if action is None:
        return False
    try:
        result = action()
    except tk.TclError:
        return False
    return result is not False


def overscroll(widget, amount):
    """Horizontal travel the scroll router could not use; may trigger back."""
    try:
        window = widget.winfo_toplevel()
    except (tk.TclError, AttributeError):
        return False
    tracker = getattr(window, '_back_tracker', None)
    if tracker is None or not tracker.feed(amount):
        return False
    return run(window)
