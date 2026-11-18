"""Send / new-line shortcuts in every composer (1.4.1).

Automatic mode follows "Enter sends messages":
- on:  Enter sends; Shift+Enter and ⌘+Enter (Ctrl+Enter on Windows) insert a new line.
- off: Enter and Shift+Enter insert a new line; ⌘+Enter (Ctrl+Enter) sends.
Settings › Chats can assign any other combination to each action instead.
"""
import sys

MOD = 'Mod+Return'
LABELS = {
    '': 'Automatic',
    'Return': 'Enter',
    'Shift+Return': 'Shift+Enter',
    MOD: '⌘+Enter' if sys.platform == 'darwin' else 'Ctrl+Enter',
    'Alt+Return': '⌥+Enter' if sys.platform == 'darwin' else 'Alt+Enter',
    'Ctrl+Return': 'Control+Enter',
}


def combos():
    """Tk sequences for every combination this platform can tell apart."""
    if sys.platform == 'darwin':
        return {'Return': ('<Return>', '<KP_Enter>'), 'Shift+Return': ('<Shift-Return>', '<Shift-KP_Enter>'),
                MOD: ('<Command-Return>', '<Command-KP_Enter>'), 'Alt+Return': ('<Option-Return>', '<Option-KP_Enter>'),
                'Ctrl+Return': ('<Control-Return>', '<Control-KP_Enter>')}
    return {'Return': ('<Return>', '<KP_Enter>'), 'Shift+Return': ('<Shift-Return>', '<Shift-KP_Enter>'),
            MOD: ('<Control-Return>', '<Control-KP_Enter>'), 'Alt+Return': ('<Alt-Return>', '<Alt-KP_Enter>')}


def options():
    """Choices offered in Settings on this platform."""
    return [''] + list(combos())


def keys(values):
    """(send combo, set of new-line combos) for these preferences."""
    send = values.get('shortcut_send') or ''
    newline = values.get('shortcut_newline') or ''
    available = set(combos())
    if not send:
        send = 'Return' if values.get('enter_send', True) else MOD
    if send not in available:
        send = 'Return'
    if newline and newline != send and newline in available:
        lines = {newline}
    else:
        lines = {'Return', 'Shift+Return', MOD} - {send}
    lines.add('Shift+Return') if send != 'Shift+Return' else None  # Always a way to break lines.
    return send, lines


def action(values, combo):
    send, lines = keys(values)
    if combo == send:
        return 'send'
    if combo in lines:
        return 'newline'
    return None


def install(widget, values, send):
    """Bind every Enter combination of ``widget``; ``values`` is a callable."""
    def handler(combo):
        def run(event):
            result = action(values(), combo)
            if result == 'send':
                send()
                return 'break'
            if result == 'newline':
                try:
                    if str(widget.cget('state')) == 'disabled':
                        return 'break'
                    if widget.tag_ranges('sel'):
                        widget.delete('sel.first', 'sel.last')
                    widget.insert('insert', '\n')
                    widget.see('insert')
                except Exception:
                    return None
                return 'break'
            return 'break'
        return run
    for combo, sequences in combos().items():
        for sequence in sequences:
            widget.bind(sequence, handler(combo))
