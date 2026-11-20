"""User-selected chat names that this device may share with Siri."""
from contextlib import contextmanager
from functools import wraps
import json

from tg_ascii.preferences import read_json, write_json
from tg_ascii.secret_chats import is_secret_peer

from .siri import identifier


def suspend_vocabulary(action):
    @wraps(action)
    async def wrapped(core, *args, **kwargs):
        with core.siri_vocabulary.changing_account(core):
            return await action(core, *args, **kwargs)
    return wrapped


class SiriVocabulary:
    def __init__(self, root):
        self.path = root / 'mobile' / 'siri-chats.json'
        stored = read_json(self.path, {})
        self.accounts = {account: [peer for peer in peers if type(peer) is int]
                         for account, peers in stored.items() if isinstance(peers, list)}
        self.native = None
        self.last = None
        self.suspended = 0

    def attach(self, native, core):
        self.native = native
        self.last = None
        self.sync(core)

    def choices(self, core):
        selected = self.accounts.get(core.account, [])
        return [{'id': chat.id, 'name': chat.name, 'selected': chat.id in selected}
                for chat in core.chats if chat.name and not is_secret_peer(chat.id)]

    def configure(self, core, account, peers):
        if not self.native or core.locked or core.stage != 'ready' or account != core.account or self.suspended:
            raise PermissionError('Open and unlock the active account.')
        choices = self.choices(core)
        if peers is None:
            return choices
        allowed = {chat['id'] for chat in choices}
        if not isinstance(peers, list) or any(type(p) is not int or p not in allowed for p in peers):
            raise ValueError('Choose conversations from the active account.')
        updates = dict(self.accounts)
        if peers:
            updates[account] = list(dict.fromkeys(peers))
        else:
            updates.pop(account, None)
        write_json(self.path, updates)
        self.accounts = updates
        self.sync(core)
        return True

    def forget(self, key):
        if key in self.accounts:
            updates = dict(self.accounts)
            del updates[key]
            write_json(self.path, updates)
            self.accounts = updates

    @contextmanager
    def changing_account(self, core):
        self.suspended += 1
        self.sync(core)
        try:
            yield
        finally:
            self.suspended -= 1
            self.sync(core)

    def sync(self, core, force=False):
        if not self.native:
            return
        entries = []
        if not self.suspended and core.stage == 'ready' and not core.locked:
            selected = set(self.accounts.get(core.account, []))
            if selected:
                entries = [(identifier(core.account, chat.id), chat.name, chat.kind in ('group', 'channel'))
                           for chat in core.chats if chat.id in selected and chat.name and not is_secret_peer(chat.id)]
        if force or entries != self.last:
            self.native.replaceJSON_(json.dumps(entries, ensure_ascii=False))
            self.last = entries
