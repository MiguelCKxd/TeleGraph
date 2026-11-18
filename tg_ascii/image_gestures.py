"""Shared image navigation: cursor-centred zoom and two-axis panning."""
import sys
import tkinter as tk
from tkinter import ttk
from .i18n import tr


def wheel_motion(event, mode='zoom', platform=None):
    platform = platform or sys.platform
    state = int(getattr(event, 'state', 0))
    # Control/Command always zoom; Shift scrolls horizontally.
    if (mode == 'zoom' and not state & 1) or state & (4 | 8):
        from .image_tools import wheel_zoom_factor
        return 'zoom', 1 / wheel_zoom_factor(event, platform)
    delta = float(getattr(event, 'delta', 0))
    number = getattr(event, 'num', None)
    if number in (4, 5): delta = 120 if number == 4 else -120
    pixels = delta * 3 if platform == 'darwin' and number not in (4, 5) else delta / 120 * 40
    return ('x' if state & 1 else 'y'), max(-240, min(240, pixels))


def bounded_pan(pan, image_size, viewport, factor):
    # Keep at least the viewport covered, or centre an image smaller than it.
    return [max(-max(0, (image_size[i] * factor - viewport[i]) / 2),
                min(max(0, (image_size[i] * factor - viewport[i]) / 2), pan[i])) for i in (0, 1)]


class ImageGestures:
    def __init__(self, canvas, scale, pan, zoom, draw, reset):
        self.canvas, self.scale, self.pan = canvas, scale, pan
        self.zoom, self.draw, self.reset = zoom, draw, reset
        # 1.4: 'auto' (default) behaves like native viewers: the mouse wheel
        # zooms at the pointer, a trackpad pans a zoomed picture and zooms a
        # fitted one, Ctrl/Cmd always zooms. 'zoom' and 'pan' are unchanged.
        self.mode = tk.StringVar(master=canvas, value='auto')
        self._gesture_at = 0.0
        self._gesture_action = None
        canvas._wheel_handler = self.wheel
        canvas._touchpad_handler = self.touchpad
        for sequence in ('<MouseWheel>', '<Shift-MouseWheel>', '<Button-4>', '<Button-5>', '<Shift-Button-4>', '<Shift-Button-5>'):
            canvas.bind(sequence, self.wheel)
        self.precise=False
        try:
            canvas.bind('<TouchpadScroll>', self.precise_event)
            self.precise=True
        except tk.TclError: pass
        canvas.bind('<Double-Button-1>', self.double_click)
        canvas.bind('<Destroy>',self.close,add='+')
        # Tk dispatches wheel events to focus on some platforms; the app router
        # routes from pointer coordinates, without requiring a click first.

    def close(self,event):
        if event.widget is not self.canvas:return
        from .image_tools import release_variables
        release_variables([self.mode])
        self.canvas._wheel_handler=None;self.canvas._touchpad_handler=None

    def double_click(self, event):
        # Fitted picture: zoom in where clicked. Zoomed picture: back to fit.
        if self.scale[0] <= 1.05:
            self.zoom(2.5, (event.x, event.y))
        else:
            self.reset()
        return 'break'

    def wheel(self, event):
        platform='win32' if getattr(self,'precise',False) and sys.platform=='darwin' else None
        mode = self.mode.get()
        action, value = wheel_motion(event, 'zoom' if mode == 'auto' else mode, platform)
        if action == 'zoom':
            self.zoom(value, (event.x_root-self.canvas.winfo_rootx(), event.y_root-self.canvas.winfo_rooty()))
        else:
            self.pan[0 if action == 'x' else 1] += value
            self.draw()
        return 'break'

    def precise_event(self,event):
        from .scrolling import precise_deltas
        return self.touchpad(event,*precise_deltas(event.delta))

    def touchpad(self,event,dx,dy):
        state=int(getattr(event,'state',0))
        mode=self.mode.get()
        if mode=='auto' and not state & (4|8):
            import time
            now=time.monotonic()
            # One continuous gesture keeps one meaning: a zoom that crosses
            # 100 % keeps zooming until the fingers pause, then it pans.
            if now-getattr(self,'_gesture_at',0)>.3 or getattr(self,'_gesture_action',None) is None:
                self._gesture_action='pan' if self.scale[0]>1.01 else 'zoom'
            self._gesture_at=now
            mode='zoom' if self._gesture_action=='zoom' and not state & 1 else 'pan'
        if (mode=='zoom' and not state & 1) or state & (4|8):
            if dy:self.zoom(1.15**max(-4,min(4,-dy/40)),
                (event.x_root-self.canvas.winfo_rootx(),event.y_root-self.canvas.winfo_rooty()))
        else:
            self.pan[0]+=dx;self.pan[1]+=dy;self.draw()
        return 'break'

    def controls(self, parent):
        ttk.Radiobutton(parent, text=tr('Auto'), value='auto', variable=self.mode).pack(side='left')
        ttk.Radiobutton(parent, text=tr('Zoom'), value='zoom', variable=self.mode).pack(side='left')
        ttk.Radiobutton(parent, text=tr('Move image'), value='pan', variable=self.mode).pack(side='left')
        ttk.Button(parent, text=tr('Fit image'), command=self.reset).pack(side='left')
