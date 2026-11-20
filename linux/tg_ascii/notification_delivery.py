"""One bounded delivery ledger for MTProto and optional push wakeups.

Only hashed event identifiers are stored, never names, text, tokens or sessions.
Reservations expire after a crash. A failed native delivery may release its own
reservation, including after commit, without deleting a newer owner's claim.
"""
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
from pathlib import Path
import sqlite3
import threading
import time
import uuid


@dataclass(frozen=True)
class DeliveryClaim:
    key: str
    owner: str


class DeliveryLedger:
    RETENTION = 7 * 86400
    RESERVATION = 120
    LIMIT = 20000

    def __init__(self, path=None, *, clock=time.time):
        self.path = Path(path) if path else None
        self.clock = clock
        self._lock = threading.RLock()
        self._connection = None
        self._memory = OrderedDict()
        self._pruned_at = 0.0
        self._claims_since_prune = 0
        self.storage_error = False

    @staticmethod
    def event_key(account, peer, message_id):
        return hashlib.sha256(f'{account}:{int(peer)}:{int(message_id)}'.encode()).hexdigest()

    def _database(self):
        if self.path is None:
            return None
        if self._connection is None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                # Open only on first use, on the notification worker, not at startup.
                self._connection = sqlite3.connect(self.path, timeout=1, check_same_thread=False)
                self._connection.execute('PRAGMA journal_mode=DELETE')
                self._connection.execute('PRAGMA synchronous=NORMAL')
                self._connection.execute('CREATE TABLE IF NOT EXISTS delivery '
                    '(key TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL, committed INTEGER NOT NULL)')
                self._connection.execute('CREATE INDEX IF NOT EXISTS delivery_expiry ON delivery(expires)')
                self._connection.commit()
                try:
                    self.path.chmod(0o600)
                except OSError:
                    pass
            except (OSError, sqlite3.Error):
                self._degrade()
        return self._connection

    def _degrade(self):
        # A damaged or unwritable cache must never disable normal notifications.
        # Leave the file untouched for inspection; this process deduplicates in
        # memory and reports that persistence is unavailable through the flag.
        self.storage_error = True
        if self._connection is not None:
            try:
                self._connection.close()
            except sqlite3.Error:
                pass
        self._connection = None
        self.path = None

    def claim(self, account, peer, message_id):
        key = self.event_key(account, peer, message_id)
        owner, now = uuid.uuid4().hex, self.clock()
        with self._lock:
            db = self._database()
            if db is not None:
                try:
                    with db:
                        # Atomic conflict predicate also coordinates another process.
                        result = db.execute('INSERT INTO delivery VALUES (?, ?, ?, 0) '
                            'ON CONFLICT(key) DO UPDATE SET owner=excluded.owner, expires=excluded.expires, committed=0 '
                            'WHERE delivery.expires <= ?', (key, owner, now + self.RESERVATION, now))
                        if result.rowcount == 0:
                            return None
                        self._claims_since_prune += 1
                        if now - self._pruned_at >= 60 or self._claims_since_prune >= 128:
                            db.execute('DELETE FROM delivery WHERE expires <= ?', (now,))
                            db.execute('DELETE FROM delivery WHERE key IN '
                                '(SELECT key FROM delivery WHERE committed=1 ORDER BY expires DESC LIMIT -1 OFFSET ?)', (self.LIMIT,))
                            self._pruned_at = now
                            self._claims_since_prune = 0
                except sqlite3.Error:
                    self._degrade()
                    db = None
            if db is None:
                current = self._memory.get(key)
                if current is not None and current[1] > now:
                    return None
            # A bounded shadow retains this process's delivery ownership if the
            # filesystem becomes unavailable after the database was opened.
            self._memory[key] = (owner, now + self.RESERVATION, False)
            self._memory.move_to_end(key)
            self._prune_memory(now)
            return DeliveryClaim(key, owner)

    def commit(self, claim):
        if claim is None:
            return False
        with self._lock:
            expiry = self.clock() + self.RETENTION
            db = self._database()
            if db is not None:
                try:
                    with db:
                        updated = bool(db.execute('UPDATE delivery SET expires=?, committed=1 WHERE key=? AND owner=?',
                            (expiry, claim.key, claim.owner)).rowcount)
                    if not updated:
                        return False
                except sqlite3.Error:
                    self._degrade()
            row = self._memory.get(claim.key)
            if row is None or row[0] != claim.owner:
                return False
            self._memory[claim.key] = (claim.owner, expiry, True)
            self._memory.move_to_end(claim.key)
            return True

    def release(self, claim):
        if claim is None:
            return
        with self._lock:
            db = self._database()
            if db is not None:
                try:
                    with db:
                        db.execute('DELETE FROM delivery WHERE key=? AND owner=?', (claim.key, claim.owner))
                except sqlite3.Error:
                    self._degrade()
            row = self._memory.get(claim.key)
            if row is not None and row[0] == claim.owner:
                self._memory.pop(claim.key, None)

    def _prune_memory(self, now):
        while self._memory:
            key, (_, expiry, _) = next(iter(self._memory.items()))
            if len(self._memory) <= self.LIMIT and expiry > now:
                break
            self._memory.pop(key)

    def close(self):
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
