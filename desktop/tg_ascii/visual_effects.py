"""Optional decoration; native controls and the undecorated path stay native.

Canvas text keeps the original tags and text item so links, selection and
gestures continue to work. No timers, images or extra items are allocated when
all effect sizes are zero.
"""
import re

EFFECT_LIMITS = {
    'button_border_width': 12, 'menu_border_width': 12,
    'button_shadow_size': 12, 'menu_shadow_size': 12,
    'text_border_width': 4, 'text_shadow_size': 8, 'text_underline_size': 8,
}
EFFECT_DEFAULTS = {key: 0 for key in EFFECT_LIMITS}
EFFECT_DEFAULTS.update({
    key.rsplit('_', 1)[0] + '_color': '' for key in EFFECT_LIMITS
})


def validated_effects(values):
    result = EFFECT_DEFAULTS.copy()
    for key, maximum in EFFECT_LIMITS.items():
        value = values.get(key)
        if type(value) is int and 0 <= value <= maximum:
            result[key] = value
    for key in result:
        if key.endswith('_color'):
            value = values.get(key)
            if isinstance(value, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', value):
                result[key] = value.lower()
    return result


def text_effects_enabled(values):
    return any(values.get(key, 0) for key in (
        'text_border_width', 'text_shadow_size', 'text_underline_size'))


def canvas_text(canvas, x, y, **options):
    """A Canvas.create_text replacement with bounded opt-in decoration.

    Decoration has the same tags as the text, so moving/removing a message or
    dispatching a gesture works over the entire decorated area. Callers that
    bind a specific item should use bind_text below.
    """
    root_getter = getattr(canvas, '_root', None)
    values = getattr(root_getter(), '_shape_values', {}) if root_getter else {}
    if not isinstance(values, dict):
        values = {}
    if not text_effects_enabled(values) or not options.get('text'):
        return canvas.create_text(x, y, **options)
    width = values.get('text_border_width', 0)
    shadow = values.get('text_shadow_size', 0)
    underline = values.get('text_underline_size', 0)
    decorated = []
    if shadow:
        painted = {**options, 'fill': values.get('text_shadow_color') or '#000000'}
        decorated.append(canvas.create_text(x + shadow, y + shadow, **painted))
    if width:
        painted = {**options, 'fill': values.get('text_border_color') or '#000000'}
        # Eight native glyph copies preserve Tk's Unicode shaping/font fallback.
        # Work is constant even at the maximum stroke width.
        for dx, dy in ((-width, 0), (width, 0), (0, -width), (0, width),
                       (-width, -width), (width, -width), (-width, width), (width, width)):
            decorated.append(canvas.create_text(x + dx, y + dy, **painted))
    item = canvas.create_text(x, y, **options)
    if underline:
        from tkinter import font as tkfont
        bounds = canvas.bbox(item)
        if bounds:
            text = str(options.get('text', ''))
            font = tkfont.Font(root=canvas, font=options.get('font') or 'TkDefaultFont')
            line_height = font.metrics('linespace')
            # create_text's bbox includes wrapped lines. A per-line underline
            # never spans an embedded newline or an empty line.
            lines = _wrapped_lines(text, font.measure, options.get('width', 0))
            top = bounds[1] + font.metrics('ascent') + 2
            justify = options.get('justify', 'left')
            available = bounds[2] - bounds[0] - 2
            for index, line in enumerate(lines):
                length = font.measure(line)
                if not length:
                    continue
                offset = (available - length) / 2 if justify == 'center' else available - length if justify == 'right' else 0
                left = bounds[0] + 1 + offset
                baseline = top + index * line_height
                decorated.append(canvas.create_line(left, baseline, left + length, baseline,
                    fill=values.get('text_underline_color') or options.get('fill', '#000000'),
                    width=underline, tags=options.get('tags', ())))
    # Associate through a tag instead of a Python registry; deleting the canvas
    # items then releases all state without retaining message ids indefinitely.
    tag = f'_effect_text:{item}'
    for part in (*decorated, item):
        canvas.addtag_withtag(tag, part)
    return item


def _wrapped_lines(text, measure, width):
    """Wrap with bounded prefix probes instead of remeasuring every long tail."""
    if not width:
        return text.split('\n')
    result = []
    for paragraph in text.split('\n'):
        start, total = 0, len(paragraph)
        while start < total:
            remaining = total-start
            low, high = 0, min(32, remaining)
            while measure(paragraph[start:start+high]) <= width:
                low = high
                if high == remaining:
                    break
                high = min(remaining, high*2)
            if low == remaining:
                break
            while low < high:
                middle = (low+high+1)//2
                if measure(paragraph[start:start+middle]) <= width:
                    low = middle
                else:
                    high = middle-1
            end = start+max(1, low)
            boundary = paragraph.rfind(' ', start, end+1)
            if boundary > start:
                end = boundary
            result.append(paragraph[start:end])
            start = end
            while start < total and paragraph[start] == ' ':
                start += 1
        result.append(paragraph[start:])
    return result


def bind_text(canvas, item, sequence, callback, add=None):
    """Bind decorations as well as the returned main text item."""
    tag = f'_effect_text:{item}'
    target = tag if tag in canvas.gettags(item) else item
    return canvas.tag_bind(target, sequence, callback, add)


def apply_text_effects(root, values, colors=None):
    """Apply native underline to input/text surfaces; exact effects use canvas.

    Does not replace text, focus handling, selection, copying or input methods.
    Tk text underline colour is optional on older Tk releases.
    """
    import tkinter as tk
    from tkinter import font as tkfont
    colors = colors or {'text': '#000000'}
    enabled = bool(values.get('text_underline_size', 0))
    if not enabled and not getattr(root, '_native_underline_enabled', False):
        return
    for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont',
                 'TkCaptionFont', 'TkSmallCaptionFont', 'TkIconFont', 'TkTooltipFont'):
        font = tkfont.nametofont(name, root=root)
        if bool(font.actual('underline')) != enabled:
            font.configure(underline=enabled)
    root._native_underline_enabled = enabled
    def visit(widget):
        if isinstance(widget, tk.Text):
            tag = '_local_underline'
            if enabled:
                widget.tag_configure(tag, underline=True)
                try:
                    widget.tag_configure(tag, underlinefg=values.get('text_underline_color') or colors['text'])
                except tk.TclError:
                    pass
                widget.tag_add(tag, '1.0', 'end')
            else:
                widget.tag_delete(tag)
        for child in widget.winfo_children():
            visit(child)
    visit(root)


class EffectSettings:
    """Simple size-and-colour form, created only while settings are open."""
    def __init__(self, parent, values):
        import tkinter as tk
        from tkinter import ttk, colorchooser
        from .i18n import tr
        self.frame = ttk.Frame(parent)
        self.variables = {}
        titles = (('button', 'Buttons'), ('menu', 'Panels and controls'), ('text', 'Message text'))
        for group, title in titles:
            section = ttk.LabelFrame(self.frame, text=tr(title), padding=8)
            section.pack(fill='x', pady=5)
            section.columnconfigure(0, weight=1)
            kinds = [('border', 'Border', 'width'), ('shadow', 'Shadow', 'size')]
            if group == 'text':
                kinds.append(('underline', 'Underline', 'size'))
            for row, (kind, title, unit) in enumerate(kinds):
                key = f'{group}_{kind}_{unit}'
                color_key = f'{group}_{kind}_color'
                size = self.variables[key] = tk.StringVar(master=parent, value=str(values.get(key, 0)))
                color = self.variables[color_key] = tk.StringVar(master=parent, value=values.get(color_key, ''))
                ttk.Label(section, text=tr(title) + ' (px)').grid(row=row, column=0, sticky='w', pady=3)
                ttk.Spinbox(section, from_=0, to=EFFECT_LIMITS[key], textvariable=size, width=5).grid(row=row, column=1, padx=4)
                def choose(variable=color):
                    result = colorchooser.askcolor(variable.get() or '#000000', parent=parent.winfo_toplevel())[1]
                    if result:
                        variable.set(result.lower())
                ttk.Button(section, text=tr('Color'), command=choose).grid(row=row, column=2, padx=2)
                ttk.Entry(section, textvariable=color, width=9).grid(row=row, column=3, padx=2)
                ttk.Button(section, text='↺', command=lambda variable=color: variable.set('')).grid(row=row, column=4)
        ttk.Label(self.frame, text=tr('Zero disables the effect. Empty colors follow the theme. Text outlines and shadows apply to messages; controls keep their native interactions.'), wraplength=420).pack(fill='x', pady=6)

    def read_values(self):
        result = {}
        for key, variable in self.variables.items():
            value = variable.get().strip()
            if key in EFFECT_LIMITS:
                try:
                    value = int(value)
                except ValueError as exc:
                    raise ValueError('El tamaño debe ser un número entero.') from exc
                if not 0 <= value <= EFFECT_LIMITS[key]:
                    raise ValueError(f'El tamaño debe estar entre 0 y {EFFECT_LIMITS[key]} px.')
            elif value and not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
                raise ValueError('Usa un color hexadecimal como #12ab34 o deja el campo vacío.')
            result[key] = value.lower() if isinstance(value, str) else value
        return result


def build_effect_settings(parent, values):
    return EffectSettings(parent, values)
