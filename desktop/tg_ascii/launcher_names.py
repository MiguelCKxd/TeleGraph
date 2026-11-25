"""The chosen app name on the system's launchers (3.2).

Windows: TeleGraph's own Start-menu and desktop shortcuts are renamed (the
label under a shortcut is its file name). Pinned taskbar links are never
renamed, so pins keep working. Linux: the managed desktop entry's Name=.
macOS: the Dock label belongs to the signed bundle and cannot change while
the app runs; the name is used for windows and screens instead.
"""
import json
import os
from pathlib import Path

from . import APP_NAME

STATE = 'launcher-name.json'
LEGACY = ('TeleGraph', 'TG-ASCII')
_INVALID = '<>:"/\\|?*'


def safe_file_name(name):
    """A Windows-safe shortcut name; the product name when nothing remains."""
    text = ''.join(' ' if ord(ch) < 32 or ch in _INVALID else ch for ch in str(name or ''))
    text = ' '.join(text.split()).strip(' .')[:80]
    if not text or text.upper().split('.')[0] in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
                                                  *(f'LPT{i}' for i in range(1, 10))}:
        return APP_NAME
    return text


def chosen_name(values):
    name = values.get('app_display_name') if isinstance(values, dict) else ''
    return name.strip() if isinstance(name, str) and name.strip() else APP_NAME


def remembered(root):
    try:
        data = json.loads((Path(root) / STATE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    names = data.get('names') if isinstance(data, dict) else None
    return [n for n in names if isinstance(n, str)][:16] if isinstance(names, list) else []


def remember(root, name):
    names = [name] + [n for n in remembered(root) if n != name]
    target = Path(root) / STATE
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps({'names': names[:16]}), encoding='utf-8')
        os.replace(temporary, target)
    except OSError:
        pass


def shortcut_names(name, previous=()):
    """Every file name one of our shortcuts may currently have."""
    result = []
    for value in (*LEGACY, *previous, name):
        file = safe_file_name(value) + '.lnk'
        if file not in result:
            result.append(file)
    return result


def plan_renames(folders, name, previous=()):
    """[(old, new)] so each folder's TeleGraph shortcut carries ``name``."""
    target_file = safe_file_name(name) + '.lnk'
    moves = []
    for folder in folders:
        folder = Path(folder)
        target = folder / target_file
        if target.exists():
            continue
        for candidate in shortcut_names(name, previous):
            source = folder / candidate
            if candidate != target_file and source.is_file() and not source.is_symlink():
                moves.append((source, target))
                break
    return moves


def apply_renames(moves):
    done = []
    for source, target in moves:
        try:
            os.rename(source, target)
            done.append(target)
        except OSError:
            continue
    return done
