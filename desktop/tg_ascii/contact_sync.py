"""Device → Telegram contact synchronization ("Sync contacts", like the official apps).

Per account state lives in ``<data dir>/contacts-sync/<account>.json``:
``{"enabled": bool, "imported": {phone: fingerprint}, "last": {...}}``.
Only *changed* device entries are uploaded on later syncs. Turning sync off
keeps what Telegram already has; "Delete synced contacts" calls
``contacts.resetSaved`` (the official equivalent).
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time

from telethon import functions, types

BATCH = 100
_lock = threading.Lock()


def state_path(root, account):
    safe = ''.join(ch for ch in str(account) if ch.isalnum() or ch in '-_') or 'account'
    return Path(root) / 'contacts-sync' / f'{safe}.json'


def load_state(root, account):
    try:
        data = json.loads(state_path(root, account).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    imported = data.get('imported') if isinstance(data.get('imported'), dict) else {}
    return {'enabled': data.get('enabled') is True, 'imported': {str(k): str(v) for k, v in imported.items()},
            'last': data.get('last') if isinstance(data.get('last'), dict) else {}}


def save_state(root, account, state, *, preserve_enabled=False):
    path = state_path(root, account)
    with _lock:
        if preserve_enabled:
            # A slow import must not overwrite a newer user decision to turn
            # synchronization off while its last Telegram batch was in flight.
            state = {**state, 'enabled': load_state(root, account)['enabled']}
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(prefix='.contacts-', dir=path.parent)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(state, stream, ensure_ascii=False)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        try:
            path.chmod(0o600)
        except OSError:
            pass


def fingerprint(contact, phone):
    return hashlib.sha256(f'{contact.first}\0{contact.last}\0{phone}'.encode('utf-8')).hexdigest()[:20]


def pending_entries(contacts, imported):
    """(phone, contact) pairs that Telegram does not have in this exact form."""
    seen, result = set(), []
    for contact in contacts:
        for phone in contact.phones:
            if phone in seen:
                continue
            seen.add(phone)
            if imported.get(phone) != fingerprint(contact, phone):
                result.append((phone, contact))
    return result


async def import_contacts(backend, contacts, state, progress=None):
    """Upload changed device contacts. Returns a summary; FLOOD_WAIT propagates."""
    pending = pending_entries(contacts, state['imported'])
    on_telegram, retry, sent = 0, 0, 0
    for start in range(0, len(pending), BATCH):
        chunk = pending[start:start + BATCH]
        request = [types.InputPhoneContact(client_id=index, phone=phone, first_name=contact.first,
                                           last_name=contact.last) for index, (phone, contact) in enumerate(chunk)]
        result = await backend.client(functions.contacts.ImportContactsRequest(request))
        retry_ids = set(getattr(result, 'retry_contacts', None) or ())
        on_telegram += len(getattr(result, 'users', None) or ())
        for index, (phone, contact) in enumerate(chunk):
            if index in retry_ids:
                retry += 1
            else:
                state['imported'][phone] = fingerprint(contact, phone)
                sent += 1
        if progress is not None:
            progress(min(len(pending), start + len(chunk)), len(pending))
        if retry_ids:
            break  # Telegram asks to slow down: keep the rest for the next sync.
        await asyncio.sleep(0.5)  # Gentle pacing between batches.
    state['last'] = {'at': int(time.time()), 'device': len(contacts), 'sent': sent,
                     'on_telegram': on_telegram, 'retry': retry}
    if hasattr(backend, 'invalidate_contacts'):
        backend.invalidate_contacts()
    return dict(state['last'])


async def reset_synced(backend, state):
    """Remove every imported phone contact from Telegram's servers."""
    await backend.client(functions.contacts.ResetSavedRequest())
    state['imported'] = {}
    state['last'] = {'at': int(time.time()), 'reset': True}
    return True
