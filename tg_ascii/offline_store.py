"""Local copy of the chat list and recent messages (1.5.3).

With it the app opens and is usable without a connection: the chat list,
folders and the last messages of recently opened chats come from this copy
until Telegram answers, exactly as the official apps do. It is also used on a
normal start, so the list appears at once and is then refreshed.

One file per account, ``<data>/offline-cache/<account>.json`` (0600, folder
0700). Reading and writing happen on a background thread; the interface only
takes shallow snapshots. Settings › "Clear cache" deletes the folder, logging
out of an account deletes that account's file.
"""
import json
import os
from pathlib import Path
import threading
import time

from .tl_codec import decode, decode_record, encode, encode_record, Unsupported

DIRECTORY = 'offline-cache'
VERSION = 1
MAX_CHATS_WITH_HISTORY = 60
MAX_MESSAGES = 200
SAVE_DELAY_MS = 4000

_write_lock = threading.Lock()


def folder(root):
    return Path(root) / DIRECTORY


def path(root, account):
    return folder(root) / f'{account}.json'


def purge(root, account=None):
    """Delete one account's copy, or every copy when account is None."""
    import shutil
    try:
        if account is None:
            shutil.rmtree(folder(root), ignore_errors=True)
        else:
            path(root, account).unlink(missing_ok=True)
    except OSError:
        pass


def _encode_chats(chats):
    return [encode_record(chat) for chat in chats]


def _encode_messages(messages):
    return [encode_record(message) for message in messages[-MAX_MESSAGES:]]


def write(root, account, chats, folders, histories):
    """Blocking write (background thread). Values are snapshots."""
    from .secret_chats import is_secret_peer
    cloud_chats = [c for c in chats if not is_secret_peer(getattr(c, 'id', 0)) and getattr(c, 'kind', '') != 'secret']
    data = {'version': VERSION, 'saved_at': time.time(), 'chats': _encode_chats(cloud_chats)}
    try:
        data['folders'] = encode(list(folders or ()))
    except Unsupported:
        data['folders'] = None
    data['histories'] = {
        str(peer): _encode_messages(messages)
        for peer, messages in histories.items()
        if messages and not is_secret_peer(peer)
    }
    target = path(root, account)
    with _write_lock:
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = target.with_suffix('.tmp')
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, separators=(',', ':'))
        os.replace(temporary, target)


def read(root, account):
    """(chats, folders or None, {peer: [Message]}) or None."""
    from .backend import Chat, Message
    try:
        with path(root, account).open('r', encoding='utf-8') as stream:
            data = json.load(stream)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get('version') != VERSION:
        return None
    chats, histories = [], {}
    for record in data.get('chats') or ():
        try:
            chats.append(decode_record(Chat, record))
        except Exception:
            continue
    folders = None
    if data.get('folders') is not None:
        try:
            folders = decode(data['folders'])
        except Exception:
            folders = None
    for peer, records in (data.get('histories') or {}).items():
        messages = []
        for record in records:
            try:
                messages.append(decode_record(Message, record))
            except Exception:
                continue
        try:
            histories[int(peer)] = messages
        except ValueError:
            continue
    return chats, folders, histories


# -- interface side ------------------------------------------------------------
def _usable(app):
    return (not getattr(app, 'demo', True) and not getattr(app, '_chat_only', False)
            and getattr(app, '_linked_owner', None) is None and enabled(app))


def enabled(app):
    values = getattr(getattr(app, 'preferences', None), 'values', None)
    return not isinstance(values, dict) or bool(values.get('offline_copy', True))


def snapshot(app):
    account = app.ui_account
    cache = getattr(app, '_history_cache', {})
    histories = {peer: list(messages) for (owner, peer), messages in list(cache.items()) if owner == account}
    if app.active is not None and app.messages:
        histories[app.active] = list(app.messages)
    # The most recently used chats keep their messages.
    keep = list(histories)[-MAX_CHATS_WITH_HISTORY:]
    return account, list(app.chats), list(getattr(app, 'folder_records', None) or ()), {peer: histories[peer] for peer in keep}


def schedule_save(app, delay=SAVE_DELAY_MS):
    if not _usable(app) or not getattr(app, 'chats', None):
        return
    job = getattr(app, '_offline_save_job', None)
    if job is not None:
        return  # One save already pending collects every change until then.

    def run():
        app._offline_save_job = None
        if getattr(app, 'closed', False) or not getattr(app, 'chats', None):
            return
        save_now(app)
    try:
        app._offline_save_job = app.root.after(delay, run)
    except Exception:
        app._offline_save_job = None


def save_now(app, wait=False):
    try:
        if not _usable(app) or not getattr(app, 'chats', None):
            return
        account, chats, folders, histories = snapshot(app)
        root = app.service.root
    except Exception:
        return  # Saving the copy must never stop the app from closing.

    def work():
        try:
            write(root, account, chats, folders, histories)
        except Exception as exc:
            from .recovery import record_failure
            record_failure(root, 'offline_store', exc)
    thread = threading.Thread(target=work, name='tg-offline-save', daemon=not wait)
    thread.start()
    if wait:
        thread.join(5)


def load_into(app, done=None):
    """Read this account's copy in the background and show it if nothing newer
    has arrived yet (the network always wins over the copy)."""
    if not _usable(app):
        return
    account, root = app.ui_account, app.service.root

    def work():
        try:
            result = read(root, account)
        except Exception as exc:
            from .recovery import record_failure
            record_failure(root, 'offline_store', exc)
            result = None
        app.worker.events.put((apply, result))

    def apply(result):
        if result is None or getattr(app, 'closed', False) or account != app.ui_account:
            if done:
                done(False)
            return
        chats, folders, histories = result
        cache = app.__dict__.setdefault('_history_cache', {})
        for peer, messages in histories.items():
            cache.setdefault((account, peer), messages)
        shown = False
        secret_mgr = getattr(getattr(app, 'backend', None), 'secret_chats', None)
        if secret_mgr is not None:
            try:
                chats = secret_mgr.chats() + [c for c in chats if getattr(c, 'kind', '') != 'secret']
            except Exception:
                pass
        if chats and not getattr(app, '_chats_from_network', False) and not app.chats:
            app.chats = chats
            if folders is not None and not getattr(app, 'folder_records', None):
                app.folder_records = folders
            try:
                if hasattr(app, 'update_folder_picker'):
                    app.update_folder_picker()
                app.render_chats()
            except Exception as exc:
                from .recovery import record_failure
                record_failure(root, 'offline_store', exc)
            shown = True
        if done:
            done(shown)
    threading.Thread(target=work, name='tg-offline-load', daemon=True).start()
