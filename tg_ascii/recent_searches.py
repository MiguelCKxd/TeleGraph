"""Submitted searches on this device, and Telegram's frequent-peer suggestions."""
from contextlib import closing, contextmanager
import sqlite3


class RecentSearches:
    def __init__(self, root):
        self.path = root / 'recent-searches.sqlite3'

    @contextmanager
    def database(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=3)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS searches (account TEXT NOT NULL, scope TEXT NOT NULL, '
                       'normalized TEXT NOT NULL, query TEXT NOT NULL, UNIQUE(account, scope, normalized))')
            yield db

    def list(self, account, scope):
        if not self.path.exists():
            return []
        with self.database() as db:
            return [row[0] for row in db.execute('SELECT query FROM searches WHERE account=? AND scope=? '
                                                'ORDER BY rowid DESC LIMIT 20', (account, scope))]

    def remember(self, account, scope, query):
        query = ' '.join(str(query).split())[:160]
        if query and account and scope:
            with self.database() as db:
                db.execute('INSERT OR REPLACE INTO searches VALUES (?, ?, ?, ?)',
                           (account, scope, query.casefold(), query))
                db.execute('DELETE FROM searches WHERE rowid IN (SELECT rowid FROM searches '
                           'WHERE account=? AND scope=? ORDER BY rowid DESC LIMIT -1 OFFSET 20)', (account, scope))
        return self.list(account, scope)

    def clear(self, account, scope):
        if self.path.exists():
            with self.database() as db:
                db.execute('DELETE FROM searches WHERE account=? AND scope=?', (account, scope))
        return []

    def forget_account(self, account):
        if self.path.exists():
            with self.database() as db:
                db.execute('DELETE FROM searches WHERE account=?', (account,))


async def frequent_peers(backend):
    """Return the server's ranked global-search suggestions, when enabled."""
    from telethon import functions, utils

    client = getattr(backend, 'client', None)
    if client is None:
        return []
    result = await client(functions.contacts.GetTopPeersRequest(
        offset=0, limit=12, hash=0, correspondents=True, bots_pm=True, groups=True, channels=True))
    entities = {utils.get_peer_id(entity): entity for entity in
                [*getattr(result, 'users', ()), *getattr(result, 'chats', ())]}
    ranked = sorted((peer for category in getattr(result, 'categories', ()) for peer in category.peers),
                    key=lambda peer: peer.rating, reverse=True)
    found = {}
    for peer in ranked:
        ident = utils.get_peer_id(peer.peer)
        if ident in entities and ident not in found:
            found[ident] = {'id': ident, 'name': utils.get_display_name(entities[ident])}
    return list(found.values())[:12]
