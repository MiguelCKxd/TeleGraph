"""Short interface transitions for the Tk desktop (3.3).

Every effect is brief (≤ 160 ms, the highlight ≤ 900 ms), finite and
cancellable, and none runs when Personalization › Disable all animations is
on or the operating system asks to reduce motion (macOS Accessibility,
Windows client-area animations off, GNOME enable-animations off). With
motion off the end state is applied at once.
"""
import functools
import subprocess
import sys
import time
import tkinter as tk

FADE_MS = 120
SLIDE_MS = 140
SLIDE_PX = 24
FLASH_MS = 900
STEP_MS = 16


@functools.lru_cache(maxsize=1)
def _system_reduces_motion_cached(_minute):
    try:
        if sys.platform == 'darwin':
            import AppKit
            return bool(AppKit.NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion())
        if sys.platform == 'win32':
            import ctypes
            enabled = ctypes.c_int(1)
            # SPI_GETCLIENTAREAANIMATION
            if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
                return not enabled.value
            return False
        result = subprocess.run(['gsettings', 'get', 'org.gnome.desktop.interface', 'enable-animations'],
                                capture_output=True, text=True, timeout=1)
        return result.returncode == 0 and result.stdout.strip() == 'false'
    except Exception:
        return False


def system_reduces_motion():
    """The OS accessibility setting, rechecked at most once a minute."""
    return _system_reduces_motion_cached(int(time.monotonic() // 60))


def motion_allowed(app):
    values = getattr(getattr(app, 'preferences', None), 'values', None) or {}
    from .preferences import animations_allowed
    return animations_allowed(values) and not system_reduces_motion()


def _ease_out(value):
    return 1 - (1 - max(0.0, min(1.0, value))) ** 3


class Tween:
    """Calls ``update(fraction)`` from 0 to 1 over ``duration`` ms, then ``finish``."""

    def __init__(self, widget, duration, update, finish=lambda: None, enabled=True):
        self.widget, self.duration, self.update, self.finish = widget, duration, update, finish
        self.job = None
        self.started = time.monotonic()
        if not enabled or duration <= 0:
            self._end()
        else:
            self.update(0.0)
            self.job = widget.after(STEP_MS, self._step)

    def _step(self):
        self.job = None
        try:
            if not self.widget.winfo_exists():
                return
        except tk.TclError:
            return
        elapsed = (time.monotonic() - self.started) * 1000
        if elapsed >= self.duration:
            self._end()
            return
        try:
            self.update(_ease_out(elapsed / self.duration))
        except tk.TclError:
            return
        self.job = self.widget.after(STEP_MS, self._step)

    def _end(self):
        try:
            self.update(1.0)
        except tk.TclError:
            pass
        self.finish()

    def cancel(self):
        if self.job is not None:
            try:
                self.widget.after_cancel(self.job)
            except tk.TclError:
                pass
            self.job = None


def fade_in(app, window):
    """A new window or dialog appears with a short fade (not on all X11 setups)."""
    enabled = motion_allowed(app)
    try:
        if enabled:
            window.attributes('-alpha', 0.0)
    except tk.TclError:
        return None

    def update(fraction):
        window.attributes('-alpha', fraction)
    return Tween(window, FADE_MS, update, enabled=enabled)


SLIDE_TAG = 'tg_slide'


def slide_in(app, canvas, keep=('wallpaper',)):
    """Canvas content enters from the right by a few pixels (chat switches).

    Only the items present now move (tagged ``tg_slide``); anything drawn
    during the effect, and the wallpaper, stays where it is drawn.
    """
    previous = getattr(canvas, '_tg_slide', None)
    if previous is not None:
        previous.cancel()
        previous.finish()
    enabled = motion_allowed(app)
    if not enabled:
        return None
    canvas.dtag(SLIDE_TAG, SLIDE_TAG)
    for item in canvas.find_all():
        if not set(canvas.gettags(item)) & set(keep):
            canvas.addtag_withtag(SLIDE_TAG, item)
    offset = [SLIDE_PX]
    canvas.move(SLIDE_TAG, SLIDE_PX, 0)

    def update(fraction):
        target = round(SLIDE_PX * (1 - fraction))
        canvas.move(SLIDE_TAG, target - offset[0], 0)
        offset[0] = target

    def finish():
        try:
            if offset[0]:
                canvas.move(SLIDE_TAG, -offset[0], 0)
                offset[0] = 0
            canvas.dtag(SLIDE_TAG, SLIDE_TAG)
        except tk.TclError:
            pass
        canvas._tg_slide = None
    canvas._tg_slide = Tween(canvas, SLIDE_MS, update, finish)
    return canvas._tg_slide


def _mix(first, second, fraction):
    a = [int(first[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(second[i:i + 2], 16) for i in (1, 3, 5)]
    return '#%02x%02x%02x' % tuple(round(x + (y - x) * fraction) for x, y in zip(a, b))


def flash_message(view, ident):
    """Highlight the message just jumped to; it fades back to normal."""
    from .appearance import app_palette
    values = getattr(getattr(view, 'preferences', None), 'values', None) or {}
    colors = app_palette(values)
    accent = values.get('accent_color') or colors.get('strong', colors['text'])
    background = colors['bg']
    canvas_view = getattr(view, '_canvas_chat_view', values.get('bubbles', False))
    canvas = getattr(view, 'bubble_view', None)
    app = getattr(view, 'app', view)
    enabled = motion_allowed(app)
    if canvas_view and canvas is not None and canvas.winfo_exists():
        bounds = canvas.bbox(f'message:{ident}')
        if not bounds:
            return None
        canvas.delete('jump_highlight')
        item = canvas.create_rectangle(bounds[0] - 4, bounds[1] - 2, bounds[2] + 4, bounds[3] + 2,
                                       outline=accent, width=3, tags='jump_highlight')

        def update(fraction):
            canvas.itemconfigure(item, outline=_mix(accent, background, fraction))

        def finish():
            try:
                canvas.delete(item)
            except tk.TclError:
                pass
        if not enabled:
            # Motion off: a steady marker for a moment, without animation.
            canvas.after(FLASH_MS, finish)
            return None
        return Tween(canvas, FLASH_MS, update, finish)
    history = getattr(view, 'history', None)
    if history is None or not history.winfo_exists():
        return None
    tag = f'msg_{ident}'
    if not history.tag_ranges(tag):
        return None
    history.tag_configure('jump_highlight', background=accent)
    history.tag_add('jump_highlight', *history.tag_ranges(tag)[:2])
    history.tag_raise('jump_highlight')

    def update(fraction):
        history.tag_configure('jump_highlight', background=_mix(accent, background, fraction))

    def finish():
        try:
            history.tag_remove('jump_highlight', '1.0', 'end')
        except tk.TclError:
            pass
    if not enabled:
        history.after(FLASH_MS, finish)
        return None
    return Tween(history, FLASH_MS, update, finish)
