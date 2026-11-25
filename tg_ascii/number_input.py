"""Slider plus a typed number, for every setting adjusted with a slider (3.2).

The slider covers the usual range; the number field accepts a wider one,
so values beyond the slider's ends can be typed with the keyboard.
"""
import tkinter as tk
from tkinter import ttk


def parse(text, low, high, integer=False):
    """The clamped number typed by the user, or None if it is not a number."""
    try:
        value = float(str(text).strip().replace(',', '.'))
    except ValueError:
        return None
    if value != value or value in (float('inf'), float('-inf')):
        return None
    value = min(high, max(low, value))
    return int(round(value)) if integer else value


def show(value, integer=False, digits=2):
    if integer:
        return str(int(round(value)))
    return f'{value:.{digits}f}'.rstrip('0').rstrip('.') or '0'


class NumberField(ttk.Spinbox):
    """A Spinbox mirroring ``variable``; Return, focus-out or arrows apply it."""

    def __init__(self, parent, variable, low, high, command=None, integer=False, step=None, digits=2, width=6):
        self.variable, self.low, self.high = variable, low, high
        self.integer, self.digits, self.command = integer, digits, command
        self.text = tk.StringVar(master=parent)
        step = step or (1 if integer else max((high - low) / 100, 0.01))
        super().__init__(parent, from_=low, to=high, increment=step, textvariable=self.text, width=width,
                         command=self.apply)
        self._sync()
        self._trace = variable.trace_add('write', lambda *_: self._sync())
        self.bind('<Return>', self.apply)
        self.bind('<KP_Enter>', self.apply)
        self.bind('<FocusOut>', self.apply)

    def _sync(self):
        try:
            value = self.variable.get()
        except (tk.TclError, ValueError):
            return
        text = show(value, self.integer, self.digits)
        if self.text.get() != text:
            self.text.set(text)

    def apply(self, _event=None):
        value = parse(self.text.get(), self.low, self.high, self.integer)
        if value is None:
            self._sync()
            return
        try:
            changed = self.variable.get() != value
        except (tk.TclError, ValueError):
            changed = True
        self.variable.set(value)
        self._sync()
        if changed and self.command:
            self.command(value)

    def destroy(self):
        try:
            self.variable.trace_remove('write', self._trace)
        except (tk.TclError, ValueError):
            pass
        super().destroy()


def slider(parent, variable, low, high, command=None, *, typed_low=None, typed_high=None,
           integer=False, digits=2, width=6):
    """Pack a Scale and its NumberField side by side in a new frame."""
    row = ttk.Frame(parent)
    scale = ttk.Scale(row, from_=low, to=high, variable=variable,
                      command=(lambda value: command(float(value))) if command else None)
    scale.pack(side='left', fill='x', expand=True)
    field = NumberField(row, variable, low if typed_low is None else typed_low,
                        high if typed_high is None else typed_high, command=command,
                        integer=integer, digits=digits, width=width)
    field.pack(side='left', padx=(6, 0))
    row.scale, row.field = scale, field
    return row
