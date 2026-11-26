"""Owned, bounded desktop downloads; progress never queues one Tk event per chunk."""
import asyncio
from dataclasses import dataclass, field
import errno
import os
from pathlib import Path
import tempfile
import threading
import tkinter as tk
from tkinter import ttk

from .i18n import tr
from .interface_layout import caption

ACTIVE = {'running', 'cancelling'}
PENDING = ACTIVE | {'queued'}
MAX_ACTIVE = 2
MAX_JOBS = 32


def size_text(value):
    size = float(value)
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if size < 1024 or unit == 'TiB':
            return f'{size:.1f} {unit}' if unit != 'B' else f'{int(size)} B'
        size /= 1024


def download_error(error):
    if isinstance(error, OSError) and error.errno in (errno.ENOSPC, errno.EDQUOT):
        return caption('Not enough storage. Free space and retry.', 'No queda espacio. Libera espacio y vuelve a intentarlo.')
    if isinstance(error, PermissionError) and error.errno is None:
        return tr('Protected content')
    from .auth import error_message
    return error_message(error)


@dataclass
class Download:
    key: tuple
    name: str
    operation: object
    valid: object
    done: object = None
    state: str = 'queued'
    current: int = 0
    total: int = 0
    path: object = None
    error: object = None
    task: object = None
    cancelled: bool = False
    generation: int = 0
    lock: object = field(default_factory=threading.Lock)

    def report(self, current, total):
        # Called on the worker: update just two numbers, never Tk or its queue.
        with self.lock:
            if self.cancelled or not self.valid():
                raise asyncio.CancelledError
            self.current, self.total = max(0, int(current)), max(0, int(total or 0))


class DownloadQueue:
    """The UI owns the queue; the worker owns each active coroutine until cleanup."""
    def __init__(self, worker, changed=lambda: None):
        self.worker, self.changed = worker, changed
        self.jobs = []
        self.closed = False

    def add(self, key, name, operation, valid, done=None):
        if self.closed or not valid():
            return None
        previous = next((job for job in self.jobs if job.key == key and job.state in PENDING), None)
        if previous:
            return previous
        # Bound both retained history and queued work. Never evict active work.
        while len(self.jobs) >= MAX_JOBS:
            old = next((job for job in self.jobs if job.state not in PENDING), None)
            if old is None:
                raise ValueError(caption('The download queue is full. Cancel a download first.',
                                         'La cola está llena. Cancela una descarga primero.'))
            self.jobs.remove(old)
        job = Download(key, Path(name).name, operation, valid, done)
        self.jobs.append(job)
        self.advance()
        return job

    def advance(self):
        if self.closed:
            return
        for job in self.jobs:
            if job.state in PENDING and not job.valid():
                self.cancel(job)
        available = MAX_ACTIVE - sum(job.state in ACTIVE for job in self.jobs)
        for job in self.jobs:
            if available <= 0:
                break
            if job.state != 'queued':
                continue
            available -= 1
            job.state = 'running'
            self.worker.submit(self.run(job), lambda _: None, lambda _: None)
        self.changed()

    async def run(self, job):
        state, result = 'cancelled', None
        try:
            with job.lock:
                job.task = asyncio.current_task()
                cancelled = job.cancelled
            if cancelled or not job.valid():
                return
            result = await job.operation(job.report, job.generation > 0)
            if not job.valid():
                return
            if not result or not Path(result).is_file():
                raise OSError(tr('No hay vista previa disponible. Puedes guardar el archivo.'))
            state = 'done'
        except asyncio.CancelledError:
            pass
        except Exception as error:
            state, result = 'failed', error
        finally:
            with job.lock:
                job.task = None
                if job.cancelled:
                    state, result = 'cancelled', None
            # One completion event per attempt, including cancellation. A slot
            # stays occupied until the backend has actually removed its partial.
            self.worker.events.put((lambda _: self.finish(job, state, result), None))

    def finish(self, job, state, result):
        if self.closed or job not in self.jobs:
            return
        if not job.valid():
            state, result = 'cancelled', None
        job.state = state
        job.path = Path(result) if state == 'done' else None
        job.error = result if state == 'failed' else None
        if state == 'done' and job.done:
            try:
                job.done(job.path)
            except Exception as error:
                job.error = error  # Download succeeded; opening can be retried.
        self.advance()

    def cancel(self, job):
        if job.state not in PENDING or job.cancelled:
            return
        with job.lock:
            job.cancelled = True
            task = job.task
        job.state = 'cancelling' if job.state in ACTIVE else 'cancelled'
        if task is not None:
            try:
                self.worker.loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass  # Worker shutdown already owns cancellation.
        self.changed()

    def retry(self, job):
        if self.closed or job.state not in ('failed', 'cancelled') or not job.valid():
            return
        job.generation += 1
        job.current = job.total = 0
        job.error = job.path = None
        job.cancelled = False
        job.state = 'queued'
        self.advance()

    def close(self):
        if self.closed:
            return
        self.closed = True
        for job in self.jobs:
            self.cancel(job)
        self.jobs.clear()


class DownloadCenter:
    def __init__(self, app):
        self.app, self.window, self.timer = app, None, None
        self.queue = DownloadQueue(app.worker, self.schedule)
        app.root.bind('<Destroy>', lambda event: self.close() if event.widget is app.root else None, add='+')

    def schedule(self):
        if self.timer is None and not self.queue.closed:
            self.timer = self.app.root.after(150, self.refresh)

    def refresh(self):
        if self.timer is not None:
            self.app.root.after_cancel(self.timer)
        self.timer = None
        for job in self.queue.jobs:
            if job.state in PENDING and not job.valid():
                self.queue.cancel(job)
        if self.window is not None and self.window.winfo_exists():
            selected = self.tree.selection()
            keys = {str(id(job)) for job in self.queue.jobs}
            for key in self.tree.get_children():
                if key not in keys:
                    self.tree.delete(key)
            for job in self.queue.jobs:
                with job.lock:
                    current, total = job.current, job.total
                progress = size_text(current) + (f' / {size_text(total)} · {min(100 if job.state == "done" else 99, current * 100 // total)}%' if total else '')
                status = {'queued': caption('Queued', 'En cola'), 'running': tr('Downloading...'),
                          'cancelling': caption('Cancelling…', 'Cancelando…'),
                          'cancelled': caption('Cancelled', 'Cancelada'), 'done': tr('Archivo guardado.'),
                          'failed': caption('Failed', 'Error')}[job.state]
                values = (job.name, status, progress)
                key = str(id(job))
                if self.tree.exists(key):
                    if tuple(self.tree.item(key, 'values')) != values:
                        self.tree.item(key, values=values)
                else:
                    self.tree.insert('', 'end', iid=key, values=values)
            if not set(selected).intersection(keys) and keys:
                key = str(id(self.queue.jobs[-1]))
                self.tree.selection_set(key)
                # ttk arrow navigation starts at the focused item. Selection
                # alone leaves keyboard users unable to move between rows.
                self.tree.focus(key)
            self.selection_changed()
        if any(job.state in PENDING for job in self.queue.jobs):
            self.schedule()

    def show(self):
        from .app_lock import is_locked
        if is_locked(getattr(self.app, 'app', self.app)):
            return
        if self.window is not None and self.window.winfo_exists():
            self.window.deiconify(); self.window.lift()
            return
        self.window, frame = self.app.dialog('Downloads', '760x400')
        self.tree = ttk.Treeview(frame, columns=('name', 'status', 'progress'), show='headings', selectmode='browse',height=7)
        for key, title, width in (('name', tr('Archivo adjunto'), 250), ('status', tr('Status'), 140), ('progress', caption('Progress', 'Progreso'), 230)):
            self.tree.heading(key, text=title); self.tree.column(key, width=width, minwidth=80)
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', lambda _: self.selection_changed())
        self.details = ttk.Label(frame, wraplength=680)
        self.details.pack(fill='x', pady=6)
        actions = ttk.Frame(frame); actions.pack(fill='x')
        self.cancel_button = ttk.Button(actions, text=tr('Cancel'), command=lambda: self.action(self.queue.cancel))
        self.cancel_button.pack(side='left')
        self.retry_button = ttk.Button(actions, text=tr('Retry'), command=lambda: self.action(self.queue.retry))
        self.retry_button.pack(side='left', padx=6)
        self.open_button = ttk.Button(actions, text=tr('Open'), command=lambda: self.action(self.open))
        self.open_button.pack(side='left')
        self.refresh()

    def selected(self):
        keys = self.tree.selection()
        return next((job for job in self.queue.jobs if str(id(job)) in keys), None)

    def selection_changed(self):
        job = self.selected()
        valid = job is not None and job.valid()
        self.cancel_button.configure(state='normal' if job and job.state in PENDING else 'disabled')
        self.retry_button.configure(state='normal' if valid and job.state in ('failed', 'cancelled') else 'disabled')
        self.open_button.configure(state='normal' if valid and job.state == 'done' else 'disabled')
        text = download_error(job.error) if job and job.error else str(job.path) if valid and job.path else ''
        self.details.configure(text=text)

    def action(self, callback):
        job = self.selected()
        if job:
            callback(job)
        self.schedule()

    def open(self, job):
        if job.valid() and job.path is not None:
            from .native_open import open_with_system
            open_with_system(job.path, job.name,
                             on_error=lambda error: self.app.worker.events.put((self.app.show_error, error)))

    def close(self):
        self.queue.close()
        if self.timer is not None:
            self.app.root.after_cancel(self.timer)
            self.timer = None


def center(app):
    current = getattr(app, '_download_center', None)
    if current is None or current.queue.closed:
        current = app._download_center = DownloadCenter(app)
    return current


def stop(app, *, recursive=False):
    manager = getattr(app, '_download_center', None)
    if manager is not None:
        manager.close()
        if manager.window is not None and manager.window.winfo_exists():
            manager.window.destroy()
    if recursive:
        for view in (*getattr(app, '_app_windows', ()), *getattr(app, '_chat_windows', ())):
            stop(view)


def stop_account(app, account):
    for view in (app, *getattr(app, '_app_windows', ()), *getattr(app, '_chat_windows', ())):
        if getattr(view, 'ui_account', None) == account:
            stop(view)


def enqueue(app, message, peer, destination, *, media=None, filename='', done=None):
    """Capture scope once; retry refreshes file references and protected policy."""
    from .app_lock import is_locked
    from .desktop_media_lifetime import export_blocked, source_message
    account, backend = app.ui_account, app.service.backend
    owner = getattr(app, 'app', app)
    def valid():
        return (not getattr(app, 'closed', False) and not getattr(app, 'closing', False)
                and not getattr(owner, 'closing', False) and not is_locked(owner)
                and account not in getattr(owner, '_logging_out_accounts', ())
                and app.ui_account == account and app.service.backend is backend
                and (not hasattr(app, 'valid') or app.valid()))
    async def transfer(progress, retry, temporary):
        current = media if media is not None else message
        ident = getattr(message, 'id', None)
        async def fresh():
            return await asyncio.wait_for(source_message(backend, peer, ident), 30) if ident is not None else current
        if retry:
            current = await fresh()
        from telethon.errors import FileReferenceExpiredError, FileReferenceInvalidError, FileReferenceEmptyError
        for attempt in range(2):
            if not valid():
                raise asyncio.CancelledError
            if export_blocked(message, app, peer) or export_blocked(current, app, peer):
                raise PermissionError(tr('Protected content'))
            try:
                from .media_cache import media_identity
                identity = media_identity(getattr(current, 'media', None) or current)
                result = await backend.download_media(getattr(current, 'media', None) or current, temporary, progress=progress)
                # An export is published only after its source is still allowed.
                # This is one read per completed explicit export, never per chunk.
                if ident is not None:
                    current = await fresh()
                if not valid():
                    raise asyncio.CancelledError
                if current is None or export_blocked(current, app, peer):
                    raise PermissionError(tr('Protected content'))
                if identity is not None and media_identity(getattr(current, 'media', None) or current) != identity:
                    raise ValueError(caption('The attachment changed. Retry to download the current file.',
                                             'El adjunto ha cambiado. Reintenta para descargar el archivo actual.'))
                return result
            except (FileReferenceExpiredError, FileReferenceInvalidError, FileReferenceEmptyError):
                if attempt or ident is None:
                    raise
                current = await fresh()
                progress(0, 0)
    async def operation(progress, retry):
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(prefix='.tg-export-', suffix=target.suffix or '.media', dir=target.parent)
        os.close(descriptor)
        try:
            result = await transfer(progress, retry, Path(temporary))
            if not result or not Path(result).is_file():
                raise OSError(tr('No hay vista previa disponible. Puedes guardar el archivo.'))
            os.replace(result, target)
            return target
        finally:
            Path(temporary).unlink(missing_ok=True)
    if not valid():
        return None
    manager = center(app)
    key = (account, id(backend), str(Path(destination).absolute()))
    try:
        job = manager.queue.add(key, filename or getattr(message, 'filename', '') or Path(destination).name,
                                operation, valid, done)
    except ValueError as error:
        app.show_error(error)
        return None
    manager.show()
    return job
