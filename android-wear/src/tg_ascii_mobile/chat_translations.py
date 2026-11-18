"""Per-account language settings and indexed translations for offline history."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3


def digest(text):
    return hashlib.sha256(str(text or '').encode('utf-8')).hexdigest()[:16]


class ChatTranslations:
    def __init__(self, folder, account):
        folder = Path(folder)
        self.path = folder / f'translations-{account}.sqlite3'
        if self.path.exists() or self.path.with_suffix('.json').exists():
            self._initialize()

    def _initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        legacy = self.path.with_suffix('.json')
        os.close(os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('PRAGMA user_version').fetchone()[0]:
                db.execute('CREATE TABLE chats (peer TEXT PRIMARY KEY, language TEXT NOT NULL)')
                db.execute('CREATE TABLE texts (peer TEXT, language TEXT, message INTEGER, '
                           'digest TEXT, value TEXT NOT NULL, PRIMARY KEY(peer, language, message, digest)) WITHOUT ROWID')
                if legacy.is_file():
                    self._import_legacy(db, legacy)
                db.execute('PRAGMA user_version = 1')
        # A crash after commit can leave both files. The version marker prevents reimport.
        legacy.unlink(missing_ok=True)

    @staticmethod
    def _import_legacy(db, path):
        try:
            data = json.loads(path.read_text('utf-8'))
            if not isinstance(data, dict) or any(not isinstance(data.get(k, {}), dict) for k in ('chats', 'texts')):
                raise ValueError('invalid translations file')
        except (UnicodeError, ValueError):
            # Preserve a damaged legacy file separately without blocking chat startup.
            path.replace(path.with_suffix('.invalid.json'))
            return
        for peer, language in data.get('chats', {}).items():
            if isinstance(language, str) and 0 < len(language) <= 12:
                db.execute('INSERT INTO chats VALUES (?,?)', (peer, language))
        for key, value in data.get('texts', {}).items():
            fields = key.rsplit(':', 3)
            if len(fields) != 4 or not isinstance(value, dict) or not isinstance(value.get('text'), str):
                continue
            peer, language, ident, fingerprint = fields
            try:
                ident = int(ident)
            except ValueError:
                continue
            db.execute('INSERT OR REPLACE INTO texts VALUES (?,?,?,?,?)',
                       (peer, language, ident, fingerprint, json.dumps(value, ensure_ascii=False)))

    def language(self, peer):
        if not self.path.is_file():
            return None
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute('SELECT language FROM chats WHERE peer=?', (str(peer),)).fetchone()
        return row[0] if row else None

    def set_language(self, peer, language):
        if not self.path.is_file():
            if not language:
                return
            self._initialize()
        with closing(sqlite3.connect(self.path)) as db, db:
            if language:
                db.execute('INSERT OR REPLACE INTO chats VALUES (?,?)', (str(peer), str(language)[:12]))
            else:
                db.execute('DELETE FROM chats WHERE peer=?', (str(peer),))

    def discard(self, peer, ids=None):
        if not self.path.is_file():
            return
        # Telegram omits the peer for deletions in private chats and basic groups.
        # Channel and supergroup message IDs are independent of those IDs.
        if peer is None:
            scope, params = 'CAST(peer AS INTEGER) > -1000000000000', ()
        else:
            scope, params = '(peer=? OR peer GLOB ?)', (str(int(peer)), f'{int(peer)}/*')
        with closing(sqlite3.connect(self.path)) as db, db:
            if ids is None:
                db.execute('DELETE FROM texts WHERE ' + scope, params)
            else:
                db.executemany('DELETE FROM texts WHERE ' + scope + ' AND message=?',
                               ((*params, ident) for ident in ids))

    def lookup(self, peer, language, messages):
        found = {}
        if not self.path.is_file():
            return found
        with closing(sqlite3.connect(self.path)) as db:
            for ident, text in messages:
                row = db.execute('SELECT value FROM texts WHERE peer=? AND language=? AND message=? AND digest=?',
                                 (str(peer), language, ident, digest(text))).fetchone()
                if row:
                    found[ident] = json.loads(row[0])
        return found

    def store(self, peer, language, rows):
        if not self.path.is_file():
            self._initialize()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executemany('INSERT OR REPLACE INTO texts VALUES (?,?,?,?,?)', (
                (str(peer), language, ident, digest(text), json.dumps(value, ensure_ascii=False, separators=(',', ':')))
                for ident, text, value in rows))
