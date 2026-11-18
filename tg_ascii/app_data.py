"""Settings › Account › App data: clear the cache, delete all data (1.5.3)."""
import shutil
import threading
from pathlib import Path

from .i18n import tr

# Folders under the data folder that only hold things the app can download or
# build again. Sessions, drafts, settings, pending actions and designs stay.
CACHE_FOLDERS = ('media-cache', 'offline-cache')


def folder_size(path):
    total = 0
    try:
        for item in Path(path).rglob('*'):
            try:
                if item.is_file() and not item.is_symlink():
                    total += item.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


def human_size(size):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return f'{size:.0f} {unit}' if unit == 'B' else f'{size:.1f} {unit}'
        size /= 1024


def cache_size(root):
    return sum(folder_size(Path(root) / name) for name in CACHE_FOLDERS)


def remove_cache(root):
    freed = 0
    for name in CACHE_FOLDERS:
        path = Path(root) / name
        if not path.exists() or path.is_symlink():
            continue
        freed += folder_size(path)
        shutil.rmtree(path, ignore_errors=True)
    return freed


def _demo(owner):
    """The demo has no data of its own: never touch the real data folder."""
    if getattr(owner, 'demo', False):
        owner.status.set(tr('Not available in the demo.'))
        return True
    return False


def clear_cache(app):
    from .app_dialogs import messagebox
    owner = getattr(app, '_linked_owner', None) or app
    if _demo(owner):
        return
    root = owner.service.root
    if not messagebox.askyesno(tr('Clear cache'), tr('Delete downloaded photos, videos and files, previews and the offline copy of your chats? Accounts, drafts, settings and pending actions are kept, and everything can be downloaded again.'), parent=app.root):
        return
    owner.__dict__.get('_history_cache', {}).clear()
    for name in ('preview_cache', 'image_cache', 'thumbnail_cache'):
        cache = getattr(owner, name, None)
        if hasattr(cache, 'clear'):
            try:
                cache.clear()
            except Exception:
                pass

    def work():
        freed = remove_cache(root)
        owner.worker.events.put((done, freed))

    def done(freed):
        owner.status.set(tr('Cache cleared: {size} freed.').format(size=human_size(freed)))
        # The chats on screen are saved again, so the app keeps opening offline.
        from .offline_store import schedule_save
        schedule_save(owner, 1500)
    owner.status.set(tr('Clearing cache...'))
    threading.Thread(target=work, name='tg-clear-cache', daemon=True).start()


def safe_to_wipe(root):
    """Only a real TG-ASCII data folder is ever deleted."""
    try:
        path = Path(root).expanduser().resolve()
    except OSError:
        return False
    home = Path.home().resolve()
    if path in (home, Path(path.anchor)) or len(path.parts) < 3 or path in home.parents:
        return False
    if not path.is_dir() or path.is_symlink():
        return False
    markers = ('preferences.json', 'accounts.json', 'account.session', 'accounts', 'diagnostics.log')
    return any((path / marker).exists() for marker in markers)


def wipe(root):
    """Delete the data folder (called after the app has closed)."""
    if not safe_to_wipe(root):
        return False
    shutil.rmtree(root, ignore_errors=True)
    return not Path(root).exists()


def delete_all_data(app):
    from .app_dialogs import messagebox
    from . import app_lifecycle
    owner = getattr(app, '_linked_owner', None) or app
    if _demo(owner):
        return
    root = owner.service.root
    if not messagebox.askyesno(tr('Delete all app data'), tr('This signs out every account on this device and deletes all TG-ASCII data here: sessions, drafts, settings, designs, pending actions and cache. Your chats stay in Telegram. The app then restarts empty.'), parent=app.root):
        return
    if not messagebox.askyesno(tr('Delete all app data'), tr('This cannot be undone. Delete everything now?'), parent=app.root):
        return
    if not safe_to_wipe(root):
        owner.show_error(ValueError(tr('This folder does not look like TG-ASCII data, so nothing was deleted.')))
        return
    owner.status.set(tr('Signing out and deleting data...'))

    async def sign_out():
        # End each session in Telegram too, so none is left in Settings ›
        # Devices. Offline accounts are only removed from this device.
        import asyncio
        results = []
        for key in list(getattr(owner.service, 'entries', {})):
            service = getattr(owner.service, 'services', {}).get(key)
            client = getattr(service, 'client', None)
            try:
                if client is not None and client.is_connected():
                    results.append(bool(await asyncio.wait_for(client.log_out(), 10)))
                else:
                    results.append(False)
            except Exception:
                results.append(False)
        return results

    def finish(results):
        from .autostart import apply as apply_autostart
        apply_autostart(False)  # 1.5.4: no login entry left behind.
        if results and not all(results):
            messagebox.showinfo(tr('Delete all app data'), tr('Some accounts could not be signed out from Telegram (no connection). Their data on this device is deleted anyway; you can end those sessions from Telegram › Settings › Devices.'), parent=app.root)
        app_lifecycle.request_wipe(root)
        owner._parent_close = True
        owner.close()
        if not owner.closing:
            app_lifecycle.request(None)
    owner.worker.submit(sign_out(), finish, lambda _: finish([False]))
