"""Bounded local notification diagnostics, without message text or raw identities."""
from collections import deque
from datetime import datetime,timezone
import asyncio,hashlib,sqlite3,threading,time
from pathlib import Path

PHASES={'received','duplicate','suppressed','in_app','submitted','failed'}
SOURCES={'live','push','system'}
LIMIT=500
RETENTION=7*86400

class NotificationHistory:
    def __init__(self,path=None,clock=time.time):
        self.path=Path(path) if path else None;self.clock=clock
        self.lock=threading.RLock();self.db=None;self.memory=deque(maxlen=LIMIT);self.closed=False
    def _database(self):
        if self.path is None or self.closed:return None
        if self.db is None:
            try:
                self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                self.db=sqlite3.connect(self.path,timeout=1,check_same_thread=False)
                self.db.execute('CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY, stamp REAL, phase TEXT, source TEXT, event TEXT, content TEXT)')
                try:
                    self.db.execute('ALTER TABLE history ADD COLUMN content TEXT')
                except sqlite3.OperationalError:
                    pass
                self.db.commit();self.path.chmod(0o600)
            except (OSError,sqlite3.Error):self._fallback()
        return self.db
    def _fallback(self):
        if self.db is not None:
            try:self.db.close()
            except sqlite3.Error:pass
        self.db=None;self.path=None
    def record(self,phase,source='system',event='',content=''):
        if phase not in PHASES or source not in SOURCES:raise ValueError('Invalid notification history event')
        # Only a fixed digest of the opaque event key is retained.
        digest=hashlib.sha256(str(event).encode()).hexdigest()[:16] if event else ''
        text_content=str(content)[:256] if content else ''
        row=(self.clock(),phase,source,digest,text_content)
        with self.lock:
            if self.closed:return
            self.memory.append(row);db=self._database()
            if db is None:return
            try:
                with db:
                    db.execute('INSERT INTO history(stamp,phase,source,event,content) VALUES (?,?,?,?,?)',row)
                    db.execute('DELETE FROM history WHERE stamp<? OR id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT ?)',(row[0]-RETENTION,LIMIT))
            except sqlite3.Error:self._fallback()
    def rows(self):
        with self.lock:
            db=self._database()
            if db is not None:
                try:return list(db.execute('SELECT stamp,phase,source,event,coalesce(content,"") FROM history WHERE stamp>=? ORDER BY id DESC LIMIT ?',(self.clock()-RETENTION,LIMIT)))
                except sqlite3.Error:self._fallback()
            return [(r[0],r[1],r[2],r[3],r[4] if len(r)>4 else '') for r in reversed(self.memory) if r[0]>=self.clock()-RETENTION]
    def close(self):
        with self.lock:
            self.closed=True
            if self.db is not None:self.db.close();self.db=None


def record_notice(app,phase,source='system',event='',content=''):
    journal=getattr(app,'notification_history',None)
    if journal is not None:
        app.worker.submit(asyncio.to_thread(journal.record,phase,source,event,content),lambda _:None,lambda _:None)


def open_history(app):
    from tkinter import ttk
    from .app_lock import is_locked
    from .i18n import tr
    from .timestamps import date_text
    if is_locked(app):return
    owner=getattr(app,'_linked_owner',None) or app
    journal=getattr(owner,'notification_history',None)
    if journal is None:return
    window,frame=app.dialog('Notification history','800x480')
    footer=ttk.Frame(frame);footer.pack(side='bottom',fill='x')
    ttk.Label(frame,text=tr('Up to 500 events from the last 7 days. Message contents and account names are not stored.'),wraplength=760).pack(fill='x',pady=5)
    table=ttk.Treeview(frame,columns=('time','event','source','content','key'),show='headings')
    columns_config = [
        ('time', 'Date', 150),
        ('event', 'Status', 120),
        ('source', 'Source', 65),
        ('content', 'Content', 365),
        ('key', 'Event', 100),
    ]
    for key,label,width in columns_config:
        table.heading(key,text=tr(label));table.column(key,width=width,stretch=(key=='content'))
    bar=ttk.Scrollbar(frame,command=table.yview);bar.pack(side='right',fill='y');table.configure(yscrollcommand=bar.set);table.pack(fill='both',expand=True)
    pending=[False]
    def valid():return window.winfo_exists() and not is_locked(app) and not getattr(app,'closing',False)
    def refresh():
        if not valid() or pending[0]:return
        pending[0]=True
        def loaded(rows):
            pending[0]=False
            if not valid():return
            table.delete(*table.get_children())
            labels={'received':'Received','duplicate':'Duplicate suppressed','suppressed':'Not shown','in_app':'Shown in app','submitted':'Submitted to system','failed':'Delivery failed'}
            for row in rows:
                stamp, phase, source, event = row[0], row[1], row[2], row[3]
                content = row[4] if len(row) > 4 else ''
                table.insert('','end',values=(date_text(datetime.fromtimestamp(stamp,timezone.utc),app.preferences.values,seconds=True),tr(labels[phase]),source,content,event))
        owner.worker.submit(asyncio.to_thread(journal.rows),loaded,lambda _:pending.__setitem__(0,False))
    ttk.Button(footer,text=tr('Refresh'),command=refresh).pack(fill='x',pady=5);refresh()
