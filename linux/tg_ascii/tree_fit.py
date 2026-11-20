"""Chat list rows are never cut (1.4.1).

Normal list: every row stays on one line; when a row (name + activity +
unread count + folder tags) is wider than the list, the text column grows and
a horizontal scrollbar appears (Shift+wheel, touchpad gestures and the bar all
work). Compact list: long rows continue on more lines (up to three; beyond
that the name is shortened, never the unread counter) and rows grow to fit.
Hovering a row shows its complete text in both modes.
"""
import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

IMAGE_SPACE = 64  # avatar (30) + padding + tree indicator area
BASE_WIDTH = 245  # column #0 as configured before 1.5
TEXT_INSET = 36   # tree indicator area + padding when a row has no picture


def _measure(tree):
    cache = vars(tree).get('_fit_cache')
    if cache is None:
        try:
            name = ttk.Style(tree).lookup('Treeview', 'font') or 'TkDefaultFont'
            face = tkfont.Font(root=tree, font=name)
        except tk.TclError:
            face = tkfont.nametofont('TkDefaultFont', root=tree)
        cache = tree._fit_cache = {'font': face, 'widths': {}}
    return cache


def _other_columns(tree):
    try:
        return sum(int(tree.column(column, 'width')) for column in tree['columns'])
    except (tk.TclError, ValueError, TypeError):
        return 0


def _has_pictures(tree):
    try:
        return any(tree.item(child, 'image') for child in tree.get_children()[:12])
    except (tk.TclError, TypeError):
        return True


def text_width(tree):
    """Pixels available for the label text of column #0."""
    try:
        inset = IMAGE_SPACE if _has_pictures(tree) else TEXT_INSET
        return max(40, int(tree.winfo_width()) - _other_columns(tree) - inset)
    except (tk.TclError, TypeError, ValueError):
        return 200


MAX_LINES = 3


def wrap_label(tree, label, width=None, max_lines=MAX_LINES, keep=''):
    """Greedy word wrap of a row label to ``width`` pixels (≤ max_lines lines).

    A single word longer than a whole line is cut between characters. When it
    still does not fit, only the start of the label is shortened: ``keep``
    (unread counter, activity, folder tags at the end) is always shown whole.
    """
    if '\n' in label:
        return label
    face = _measure(tree)['font']
    width = text_width(tree) if width is None else width
    if face.measure(label) <= width:
        return label
    if keep and label.endswith(keep):
        full = _wrap(face, label, width)
        if len(full) <= max_lines:
            return '\n'.join(full)
        head = label[:len(label) - len(keep)]
        low, high = 0, len(head)
        while low < high:  # Longest start of the name that still fits.
            middle = (low + high + 1) // 2
            if len(_wrap(face, head[:middle].rstrip() + '…' + keep, width)) <= max_lines:
                low = middle
            else:
                high = middle - 1
        return '\n'.join(_wrap(face, head[:low].rstrip() + '…' + keep, width))
    lines = _wrap(face, label, width)
    if len(lines) > max_lines:
        # Beyond three lines: ellipsis; hovering shows the complete text.
        last = ' '.join(lines[max_lines - 1:])
        while last and face.measure(last + '…') > width:
            last = last[:-1]
        lines = lines[:max_lines - 1] + [last.rstrip() + '…']
    return '\n'.join(lines)


def _wrap(face, label, width):
    lines, current = [], ''
    for word in label.split(' '):
        candidate = word if not current else current + ' ' + word
        if face.measure(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        while face.measure(word) > width and len(word) > 1:
            cut = len(word)
            while cut > 1 and face.measure(word[:cut]) > width:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        current = word
    if current:
        lines.append(current)
    return lines


def fit_row_height(tree, labels, base, style_name):
    """Rows tall enough for the longest wrapped label (chat list style only)."""
    try:
        lines = max((label.count('\n') + 1 for label in labels), default=1)
        linespace = _measure(tree)['font'].metrics('linespace')
        height = max(base, lines * linespace + 6)
        style = ttk.Style(tree)
        if str(style.lookup(style_name, 'rowheight')) != str(height):
            style.configure(style_name, rowheight=height)
        if str(tree.cget('style')) != style_name:
            tree.configure(style=style_name)
    except (tk.TclError, ValueError):
        pass


def fit_column(tree, labels):
    """Size column #0 to the widest (possibly wrapped) line; stretch otherwise."""
    try:
        cache = _measure(tree)
        widths, face = cache['widths'], cache['font']
        # Retain only lines in this list. A fixed-size cache that clears
        # during a scan repeatedly measures the entire list above its limit.
        current_widths = {}
        widest = 0
        for label in labels:
            for line in label.split('\n'):
                if line in current_widths:
                    continue
                width = widths.get(line)
                if width is None:
                    width = face.measure(line)
                current_widths[line] = width
                widest = max(widest, width)
        cache['widths'] = current_widths
        available = max(1, int(tree.winfo_width()) - _other_columns(tree))
        label_width = text_width(tree)
        needed = widest + (available - label_width)
        if widest > label_width:
            tree.column('#0', width=needed, minwidth=needed, stretch=False)
        else:
            # Same as the pre-1.5 column: stretches to fill, never changes the
            # list's requested width (which places the divider).
            tree.column('#0', width=BASE_WIDTH, minwidth=160, stretch=True)
    except tk.TclError:
        pass


def horizontal_bar(frame, tree):
    """A horizontal scrollbar shown only while some row is wider than the list."""
    bar = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)

    def moved(first, last):
        bar.set(first, last)
        overlay = getattr(tree, '_row_overlay', None)
        if overlay is not None:
            overlay.refresh()
        try:
            whole = float(first) <= 0 and float(last) >= 1
            if whole and bar.winfo_ismapped():
                bar.pack_forget()
            elif not whole and not bar.winfo_ismapped():
                bar.pack(side='bottom', fill='x', before=tree)
        except tk.TclError:
            pass
    tree.configure(xscrollcommand=moved)
    return bar


def hover_full_text(tree, delay=550):
    """Tooltip with the complete row text when the row is wider than the list."""
    state = {'job': None, 'tip': None, 'row': None}

    def hide(_=None):
        if state['job'] is not None:
            try:
                tree.after_cancel(state['job'])
            except tk.TclError:
                pass
            state['job'] = None
        if state['tip'] is not None:
            try:
                state['tip'].destroy()
            except tk.TclError:
                pass
            state['tip'] = None
        state['row'] = None

    def show(row, x, y):
        state['job'] = None
        try:
            if not tree.exists(row):
                return
            shown = tree.item(row, 'text')
            text = vars(tree).get('_full_labels', {}).get(row, shown)
            if '…' not in shown and shown.replace('\n', ' ') == text:
                cache = _measure(tree)
                if max(cache['font'].measure(line) for line in shown.split('\n')) <= text_width(tree):
                    return  # Already fully visible.
            tip = tk.Toplevel(tree)
            if sys.platform == 'darwin':
                # Tk 9 on macOS paints an overrideredirect window as an empty
                # dark pill; the native help-tag style draws its contents.
                tip.tk.call('::tk::unsupported::MacWindowStyle', 'style', tip._w, 'help', 'none')
                from .themes import _palette
                label = tk.Label(tip, text=text, padx=8, pady=4, relief='solid', bd=1, justify='left',
                                 bg=_palette.get('panel', '#0e1b13'), fg=_palette.get('text', '#8cf5a6'),
                                 font=_measure(tree)['font'])
            else:
                tip.overrideredirect(True)
                label = ttk.Label(tip, text=text, padding=(8, 4), relief='solid', borderwidth=1)
            tip.attributes('-topmost', True)
            overlay = getattr(tree, '_row_overlay', None)
            docs = overlay.docs.get(row) if overlay is not None else None
            if docs:
                # Same text, with the real custom emoji pictures (1.5.0.1).
                from .row_emoji import PLACEHOLDER
                label.destroy()
                face = _measure(tree)['font']
                lines = text.split('\n')
                style = ttk.Style(tree)
                box = tk.Text(tip, height=len(lines), width=max(len(line) for line in lines) + 1, bd=1, relief='solid',
                              padx=8, pady=4, font=face, wrap='none', highlightthickness=0,
                              bg=style.lookup('Treeview', 'fieldbackground') or 'black',
                              fg=style.lookup('Treeview', 'foreground') or 'white')
                parts = text.split(PLACEHOLDER)
                size = max(10, min(face.measure(PLACEHOLDER), face.metrics('linespace')) - 1)
                from .row_emoji import photo_for
                for index, part in enumerate(parts):
                    box.insert('end', part)
                    if index < len(parts) - 1:
                        document = docs[index] if index < len(docs) else None
                        picture = photo_for(overlay, document, size)
                        if picture is not None:
                            box.image_create('end', image=picture, padx=2)
                        else:
                            # Not loaded yet (row part off screen): fill in when it arrives.
                            mark = f'emoji{index}'
                            box.mark_set(mark, 'end-1c'); box.mark_gravity(mark, 'left')
                            box.insert('end', PLACEHOLDER)
                            if document is not None:
                                def arrived(picture, box=box, mark=mark):
                                    if box.winfo_exists() and mark in box.mark_names():
                                        box.configure(state='normal')
                                        box.delete(mark, f'{mark}+{len(PLACEHOLDER)}c')
                                        box.image_create(mark, image=picture, padx=2)
                                        box.configure(state='disabled')
                                overlay.load(document, size, arrived)
                box.configure(state='disabled')
                box.pack()
            else:
                label.pack()
            tip.geometry(f'+{x + 14}+{y + 18}')
            state['tip'] = tip
        except tk.TclError:
            state['tip'] = None

    def motion(event):
        row = tree.identify_row(event.y)
        if row == state['row']:
            return
        hide()
        if not row:
            return
        state['row'] = row
        state['job'] = tree.after(delay, lambda: show(row, event.x_root, event.y_root))

    tree.bind('<Motion>', motion, add='+')
    tree.bind('<Leave>', hide, add='+')
    tree.bind('<ButtonPress>', hide, add='+')
    tree.bind('<MouseWheel>', hide, add='+')
