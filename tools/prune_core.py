"""Drop the desktop-only (Tk) modules from the mobile copy of the shared core.

Android and iOS Python have no tkinter, so a module that imports it when it is
loaded, or loads such a module itself, can never run on a phone or a watch.
They only made the app bigger. The list is computed from the code each time,
so it follows the desktop repository.

Usage: prune_core.py SRC/tg_ascii   (prints how many modules were removed)
"""
import ast
from pathlib import Path
import sys

TK = ('tkinter', '_tkinter')
# Replaced on mobile by a shim (tg_ascii_mobile.core._install_window_shim).
SHIMMED = {'interface_windows'}


def module_imports(path, modules):
    """Names of tg_ascii modules and whether tkinter are imported at load time."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    found, uses_tk = set(), False
    for statement in tree.body:
        nodes = ast.walk(statement) if isinstance(statement, (ast.If, ast.Try, ast.With)) else (statement,)
        for node in nodes:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    head = alias.name.split('.')
                    uses_tk |= head[0] in TK
                    if head[0] == 'tg_ascii' and len(head) > 1:
                        found.add(head[1])
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                uses_tk |= module.split('.')[0] in TK
                if node.level == 1:
                    found.update([module.split('.')[0]] if module else
                                 [alias.name for alias in node.names if alias.name in modules])
                elif module.startswith('tg_ascii.'):
                    found.add(module.split('.')[1])
    return found, uses_tk


def desktop_only(package):
    modules = {path.stem: path for path in package.glob('*.py')}
    imports, dead = {}, set()
    for name, path in modules.items():
        imports[name], uses_tk = module_imports(path, modules)
        if uses_tk:
            dead.add(name)
    changed = True
    while changed:
        changed = False
        for name, needed in imports.items():
            if name not in dead and needed & (dead - SHIMMED):
                dead.add(name)
                changed = True
    return dead


def main(package):
    package = Path(package)
    dead = desktop_only(package)
    for name in sorted(dead):
        (package / f'{name}.py').unlink()
    print(f'{len(dead)} desktop-only modules removed')


if __name__ == '__main__':
    main(sys.argv[1])
