"""Independent windows you can keep, name, order and reopen (1.5.4).

An independent window is a second TG-ASCII process with its own data folder
(``<data>/windows/<id>``): its own logins, settings, drafts and designs.

``<data>/windows.json`` (0600) lists them:

    {"save": false, "reopen": false,
     "windows": [{"id": "…", "name": "Work", "open_at_start": true}, …]}

* ``save`` off (default): a new independent window is temporary. When it is
  closed it signs out of its accounts in Telegram and its folder is deleted.
* ``save`` on: new windows are kept in the list (Settings › Windows), where
  they can be renamed, reordered, opened, set to open with the app, or
  deleted (signing out of their accounts, then deleting their folder).
* ``reopen`` on: when the main window starts, the windows marked
  ``open_at_start`` open as well, each with its own information.

Folders made by earlier versions (every "Independent app window" used to get
a new folder that was never reused) are listed as "Window N" so their logins
can be opened again or removed.
"""
import json
import os
from pathlib import Path
import re
import shutil
import uuid

from . import APP_NAME

REGISTRY = 'windows.json'
FOLDER = 'windows'
TEMPORARY = '.temporary'
_ID = re.compile(r'[a-f0-9]{32}')


def main_root(root):
    """The main data folder, also when called from inside an independent window."""
    path = Path(root)
    if path.parent.name == FOLDER and _ID.fullmatch(path.name):
        return path.parent.parent
    return path


def is_independent(root):
    return main_root(root) != Path(root)


def window_dir(main, ident):
    if not _ID.fullmatch(str(ident)):
        raise ValueError('Invalid window id')
    return Path(main) / FOLDER / ident


def load(main):
    path = Path(main) / REGISTRY
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    windows = []
    for item in data.get('windows') or []:
        if isinstance(item, dict) and _ID.fullmatch(str(item.get('id', ''))):
            windows.append({'id': item['id'], 'name': str(item.get('name') or '')[:60],
                            'open_at_start': item.get('open_at_start') is True})
    result = {'save': data.get('save') is True, 'reopen': data.get('reopen') is True, 'windows': windows}
    if _adopt_orphans(main, result):
        store(main, result)
    return result


def store(main, data):
    path = Path(main) / REGISTRY
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=1)
    os.replace(temporary, path)


def _adopt_orphans(main, data):
    folder = Path(main) / FOLDER
    known = {item['id'] for item in data['windows']}
    changed = False
    try:
        candidates = sorted(folder.iterdir(), key=lambda item: item.stat().st_mtime)
    except OSError:
        return False
    for item in candidates:
        if not item.is_dir() or not _ID.fullmatch(item.name) or item.name in known:
            continue
        if (item / TEMPORARY).exists():
            continue
        data['windows'].append({'id': item.name, 'name': '', 'open_at_start': False})
        changed = True
    return changed


def display_name(data, item, translate=lambda text: text):
    if item.get('name'):
        return item['name']
    number = next((index for index, other in enumerate(data['windows'], 1) if other['id'] == item['id']), 0)
    return translate('Window {number}').format(number=number)


def find(data, ident):
    return next((item for item in data['windows'] if item['id'] == ident), None)


def update(main, change):
    """Load, let ``change(data)`` edit it, store. Returns the new data."""
    data = load(main)
    change(data)
    store(main, data)
    return data


def rename(main, ident, name):
    def change(data):
        item = find(data, ident)
        if item is not None:
            item['name'] = ' '.join(str(name).split())[:60]
    return update(main, change)


def move(main, ident, offset):
    def change(data):
        items = data['windows']
        index = next((i for i, item in enumerate(items) if item['id'] == ident), None)
        if index is None:
            return
        target = max(0, min(len(items) - 1, index + offset))
        items.insert(target, items.pop(index))
    return update(main, change)


def set_flag(main, key, value):
    def change(data):
        data[key] = bool(value)
    return update(main, change)


def set_open_at_start(main, ident, value):
    def change(data):
        item = find(data, ident)
        if item is not None:
            item['open_at_start'] = bool(value)
    return update(main, change)


def running(main, ident):
    """True while that window's process holds its instance lock."""
    directory = window_dir(main, ident)
    if not (directory / 'desktop.lock').exists():
        return False
    from .instance import InstanceLock
    lock = InstanceLock(directory)
    try:
        return not lock.acquired
    finally:
        lock.close()


def new_window(main, save):
    """Create the folder for a new independent window; returns its id."""
    ident = uuid.uuid4().hex
    directory = window_dir(main, ident)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if save:
        def change(data):
            # load() may already have adopted the new folder: list it once.
            if find(data, ident) is None:
                data['windows'].append({'id': ident, 'name': '', 'open_at_start': False})
        update(main, change)
    else:
        (directory / TEMPORARY).write_text('', encoding='utf-8')
    return ident


def launch(main, ident, demo=False):
    import subprocess
    import sys
    from .interface_windows import independent_command
    command = independent_command(window_dir(main, ident))
    if demo:
        command.append('--demo')
    options = {'cwd': str(Path(__file__).resolve().parents[1]), 'stdin': subprocess.DEVNULL,
               'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
    if sys.platform == 'win32':
        options['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options['start_new_session'] = True
    return subprocess.Popen(command, **options)


def open_window(app, ident=None):
    """Open a saved window (or a new one) as its own process."""
    main = main_root(app.service.root)
    if ident is None:
        ident = new_window(main, load(main)['save'] and not app.demo)
    process = launch(main, ident, app.demo)
    owner = getattr(app, '_linked_owner', None) or app
    owner._independent_windows = [item for item in getattr(owner, '_independent_windows', []) if item.poll() is None]
    owner._independent_windows.append(process)
    return ident


def reopen_at_start(app):
    """Main window only: open the windows chosen to start with the app."""
    if app.demo or getattr(app, '_linked_owner', None) is not None or is_independent(app.service.root):
        return []
    main = main_root(app.service.root)
    data = load(main)
    if not data['reopen']:
        return []
    opened = []
    for item in data['windows']:
        if item['open_at_start'] and not running(main, item['id']):
            try:
                launch(main, item['id'])
                opened.append(item['id'])
            except OSError:
                continue
    return opened


def temporary(root):
    return is_independent(root) and (Path(root) / TEMPORARY).exists()


def remove_folder(main, ident):
    """Delete a window's folder (never anything outside <main>/windows)."""
    directory = window_dir(main, ident)
    resolved = directory.resolve()
    if resolved.parent != (Path(main) / FOLDER).resolve() or directory.is_symlink():
        return False
    shutil.rmtree(resolved, ignore_errors=True)
    return not resolved.exists()


async def sign_out_folder(directory, timeout=15):
    """Sign out every account saved in a window folder (best effort).
    Returns how many could not be signed out in Telegram."""
    import asyncio
    from .accounts import Accounts
    accounts = Accounts(root=directory)
    failed = 0
    for key in list(accounts.entries):
        session = Path(directory) / ('account.session' if key == 'account' else f'accounts/{key}/account.session')
        if not session.exists():
            continue
        try:
            await asyncio.wait_for(accounts.logout(key), timeout)
        except Exception:
            failed += 1
    try:
        await asyncio.wait_for(accounts.close(), 10)
    except Exception:
        pass
    return failed


async def delete_window(main, ident):
    """Sign out of that window's accounts, then delete its folder and entry."""
    if running(main, ident):
        raise RuntimeError('running')
    failed = await sign_out_folder(window_dir(main, ident))
    def change(data):
        data['windows'] = [item for item in data['windows'] if item['id'] != ident]
    update(main, change)
    remove_folder(main, ident)
    return failed


def window_title(root, app_name=APP_NAME):
    """Branded title inside an independent window, else None."""
    if not is_independent(root):
        return None
    from .i18n import tr
    if (Path(root) / TEMPORARY).exists():
        return app_name + ' · ' + tr('Temporary window')
    main = main_root(root)
    try:
        data = load(main)
    except OSError:
        return None
    item = find(data, Path(root).name)
    return app_name + ' · ' + display_name(data, item, tr) if item else None


async def sign_out_services(service, timeout=8):
    """Temporary windows on close: end their sessions in Telegram too."""
    import asyncio
    for child in tuple(getattr(service, 'services', {}).values()):
        client = getattr(child, 'client', None)
        try:
            if client is not None and client.is_connected():
                await asyncio.wait_for(client.log_out(), timeout)
        except Exception:
            pass
