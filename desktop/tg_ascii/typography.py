"""One terminal-style default for the interface, composer and message canvas."""
import sys
from tkinter import font as tkfont


def terminal_family(root, families=None):
    """Resolve a real installed fixed-width font, never a silent GUI substitution."""
    available = {name.casefold(): name for name in (tkfont.families(root) if families is None else families)}
    preferred = ('Menlo', 'Monaco', 'Consolas') if sys.platform == 'darwin' else ('Consolas', 'Cascadia Mono', 'Lucida Console')
    fallback = tkfont.nametofont('TkFixedFont', root=root).actual('family')
    candidates = (*preferred, 'DejaVu Sans Mono', 'Liberation Mono', 'Courier New', fallback, *sorted(available.values()))
    checked = set()
    for candidate in candidates:
        family = available.get(candidate.casefold())
        if not family or family in checked:
            continue
        checked.add(family)
        probe = tkfont.Font(root=root, family=family, size=12)
        # Verify the rendered ASCII cells, not only the family's advertised name.
        if probe.metrics('fixed') and len({probe.measure(chr(code)) for code in range(32, 127)}) == 1:
            return probe.actual('family')
    return fallback  # Tk's platform fixed-font contract on unusual installations.


def configure_fonts(root, requested, size):
    key = (requested.casefold(), size)
    configured = getattr(root, '_font_configuration', None)
    if isinstance(configured, tuple) and configured[:2] == key:
        return configured[2]
    families = tkfont.families(root)
    fixed = terminal_family(root, families)
    available = {name.casefold(): name for name in families}
    family = available.get(requested.casefold(), fixed)
    for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont',
                 'TkCaptionFont', 'TkSmallCaptionFont', 'TkIconFont', 'TkTooltipFont'):
        tkfont.nametofont(name, root=root).configure(family=family, size=size)
    # Explicit code formatting remains monospaced even after a custom UI choice.
    tkfont.nametofont('TkFixedFont', root=root).configure(family=fixed, size=size)
    for pattern in ('*Font', '*TCombobox*Listbox.font'):
        root.option_add(pattern, 'TkDefaultFont')
    root._font_configuration = (*key, family)
    return family
