"""Explicit user downloads, independent of the lifetime of an HTTP request.

Transfers stream through the existing backend; retries start at byte zero.
Only metadata crosses the UI bridge. Each job owns its temporary directory,
never a shared preview/cache entry or a copy exported by the system.
"""
import asyncio
from collections import OrderedDict
from dataclasses import dataclass
import errno
import os
from pathlib import Path
import shutil
import time
import uuid
from telethon.errors import RPCError

from tg_ascii.media_cache import has_expiry, media_identity
from tg_ascii.secret_chats import is_secret_peer

FOLDER = 'mobile-downloads'
CONCURRENCY = 2
MAX_PENDING = 12
MAX_HISTORY = 24
RETAINED_BYTES = 512 * 1024 * 1024
ACTIVE = frozenset(('queued', 'downloading', 'cancelling', 'opening'))


def filename(value):
    name = str(value or '').replace('\\', '/').rsplit('/', 1)[-1]
    name = ''.join(char for char in name if ord(char) >= 32 and ord(char) != 127).strip()
    name = name.encode('utf-8')[:200].decode('utf-8', errors='ignore')
    return name if name not in ('', '.', '..') else 'file'


def failure(error):
    if isinstance(error, RPCError):
        name = type(error).__name__
        if name in ('FloodWaitError', 'FloodPremiumWaitError'):
            return 'rate_limited'
        if name in ('FileReferenceExpiredError', 'FileReferenceEmptyError', 'FilerefUpgradeNeededError',
                    'MessageIdInvalidError', 'MediaEmptyError'):
            return 'unavailable'
    if isinstance(error, PermissionError):
        return 'permission'
    if isinstance(error, TimeoutError):
        return 'timeout'
    if isinstance(error, OSError) and error.errno in (errno.ENOSPC, errno.EDQUOT):
        return 'storage_full'
    if isinstance(error, (ConnectionError, OSError)):
        return 'network'
    if isinstance(error, (LookupError, ValueError)):
        return 'unavailable'
    return 'unexpected'


@dataclass
class Download:
    id: str
    account: str
    backend: object
    peer: int
    ident: int
    name: str = 'file'
    state: str = 'queued'
    current: int = 0
    total: int | None = None
    expected: int | None = None
    error: str | None = None
    attempt: int = 0
    path: Path | None = None
    directory: Path | None = None
    task: object = None
    last_emit: float = 0
    exports: int = 0
    released: bool = False
    revision: int = 0
    identity: object = None
    action: str | None = None
    cancel_requested: bool = False

    def snapshot(self):
        percent = None
        if self.total:
            # A full callback is not yet a verified, atomically published file.
            percent = 100 if self.state in ('ready', 'opening') else min(99, self.current * 100 // self.total)
        return {'id': self.id, 'account': self.account, 'peer': self.peer, 'message_id': self.ident,
                'name': self.name, 'state': self.state, 'bytes': self.current, 'total': self.total,
                'percent': percent, 'error': self.error, 'attempt': self.attempt,
                'revision': self.revision, 'action': self.action}


class DownloadManager:
    def __init__(self, core, *, concurrency=CONCURRENCY, max_pending=MAX_PENDING,
                 max_history=MAX_HISTORY, retained_bytes=RETAINED_BYTES):
        self.core = core
        self.jobs = OrderedDict()
        self.slots = asyncio.Semaphore(concurrency)
        self.max_pending, self.max_history = max_pending, max_history
        self.retained_bytes = retained_bytes
        self.closed = False
        self.opening = {}
        self.cancelling_open = set()
        self.revision = 0

    def active_account(self, account):
        if self.closed or self.core.locked or account != self.core.account:
            raise PermissionError('The active account changed.')
        return account

    def check(self, job):
        service = getattr(self.core.accounts, 'services', {}).get(job.account)
        if (self.closed or self.core.locked or job.released or service is None
                or service.backend is not job.backend):
            raise PermissionError('The account is no longer available.')

    def get(self, ident, account):
        self.active_account(account)
        job = self.jobs.get(str(ident))
        if job is None or job.account != account:
            raise LookupError('download')
        return job

    def snapshot(self, account):
        self.active_account(account)
        return [job.snapshot() for job in reversed(self.jobs.values()) if job.account == account]

    def publish(self, job, *, force=True):
        self.revision += 1
        job.revision = self.revision
        if self.closed or self.core.locked or job.account != self.core.account or job.released:
            return
        now = time.monotonic()
        if force or now - job.last_emit >= .2:
            job.last_emit = now
            self.core.emit('downloads', self.status(job.account))

    def status(self, account):
        return {'account': account, 'revision': self.revision, 'items': self.snapshot(account)}

    def start(self, peer, ident, account, request_id=None):
        self.active_account(account)
        peer, ident = int(peer), int(ident)
        backend = self.core.backend
        if backend is None:
            raise ConnectionError('offline')
        # Repeated POSTs/taps reuse one job, including a completed or failed one.
        # Retrying a failed attempt is an explicit separate operation.
        for job in self.jobs.values():
            if (job.account, job.backend, job.peer, job.ident) == (account, backend, peer, ident):
                return job.snapshot()
        if sum(job.state in ACTIVE for job in self.jobs.values()) >= self.max_pending:
            raise ValueError('Download queue is full.')
        job = Download(uuid.uuid4().hex, account, backend, peer, ident)
        self.jobs[job.id] = job
        self.launch(job)
        self.trim(job)
        return job.snapshot()

    def launch(self, job):
        job.state, job.current, job.total, job.expected, job.error = 'queued', 0, None, None, None
        job.attempt += 1
        job.cancel_requested = False
        job.task = asyncio.create_task(self.run(job))
        self.publish(job)

    async def checked_source(self, job):
        self.check(job)
        if is_secret_peer(job.peer):
            manager = getattr(job.backend, 'secret_chats', None)
            if manager is None:
                raise LookupError('media')
            messages = manager.message_context(job.peer, job.ident)  # Prunes expired records.
            message = next((item for item in messages if item.id == job.ident), None)
            session = manager.session_for_peer(job.peer)
            record = next((item for item in session.messages if item['id'] == job.ident), None)
            if record is None or message is None:
                raise LookupError('media')
            # Secret messages use protected=True to prevent forwarding; that
            # alone does not prohibit a legitimate export without a TTL.
            if record.get('ttl', 0) or record.get('expires_at'):
                raise PermissionError('Protected content')
        else:
            message = await asyncio.wait_for(job.backend.checked_message(job.peer, job.ident), 30)
            entity = await asyncio.wait_for(job.backend.client.get_entity(job.peer), 30)
            if (getattr(entity, 'noforwards', False) or getattr(message, 'noforwards', False)
                    or getattr(message, 'protected', False) or has_expiry(message)):
                raise PermissionError('Protected content')
        self.check(job)
        media = getattr(message, 'media', None)
        if media is None:
            raise LookupError('media')
        return message, media

    async def cached(self, job, message):
        if is_secret_peer(job.peer):
            return None
        folder = self.core.root / 'mobile-media' / job.account
        index = await self.core._media_index(folder)
        self.check(job)
        name = index.get(f'{job.peer}-{job.ident}')
        if not name or Path(name).name != name:
            return None
        path = folder / name
        try:
            stat = path.stat()
            edited = getattr(message, 'edit_date', None) or getattr(message, 'edited_at', None)
            edited = edited.timestamp() if hasattr(edited, 'timestamp') else edited
            if (not path.is_file() or path.is_symlink() or not stat.st_size
                    or (job.expected and stat.st_size != job.expected)
                    or (isinstance(edited, (float, int)) and stat.st_mtime < edited)):
                return None
            return path
        except OSError:
            return None

    async def run(self, job):
        try:
            async with self.slots:
                self.check(job)
                job.state = 'downloading'
                self.publish(job)
                message, media = await self.checked_source(job)
                identity = media_identity(media)
                job.identity = identity
                details = getattr(message, 'file', None)
                job.name = filename(getattr(details, 'name', None) or getattr(message, 'filename', None)
                                    or getattr(media, 'file_name', None))
                total = getattr(details, 'size', None) or getattr(message, 'size', None) or getattr(media, 'size', None)
                if isinstance(total, int) and total > 0:
                    job.total = job.expected = total
                job.path = await self.cached(job, message)
                if job.path is None:
                    job.directory = self.core.root / FOLDER / job.id
                    job.directory.mkdir(parents=True, exist_ok=False, mode=0o700)
                    def progress(current, total):
                        self.check(job)
                        if job.state != 'downloading':
                            raise asyncio.CancelledError()
                        # Absolute bytes of the current attempt, including a
                        # transport retry reset; never add successive callbacks.
                        job.current = max(0, int(current))
                        if job.expected:
                            # Encrypted files may report padded transport bytes;
                            # the known final plaintext size stays authoritative.
                            job.current = min(job.current, job.expected)
                        elif isinstance(total, int) and total > 0:
                            job.total = total
                        self.publish(job, force=False)
                    path = await job.backend.download_media(media, job.directory / job.name,
                                                            progress=progress, quality='original')
                    if not path:
                        raise LookupError('media')
                    job.path = Path(path)
                    if not job.path.resolve().is_relative_to(job.directory.resolve()) or job.path.is_symlink():
                        raise PermissionError('Unexpected download path')
                    if job.name == 'file':
                        job.name = job.path.name
                self.check(job)
                # Revalidate protection/expiration before exposing a completed
                # file, including transfers that refreshed their FileReference.
                _, current_media = await self.checked_source(job)
                if identity is not None and media_identity(current_media) != identity:
                    raise LookupError('The attachment changed.')
                size = job.path.stat().st_size
                if job.expected and size != job.expected:
                    raise OSError('Incomplete download')
                job.current, job.total = size, size or None
                job.state = 'ready'
                self.trim(job)
                self.publish(job)
        except asyncio.CancelledError:
            job.state, job.error = 'cancelled', None
            self.cleanup(job)
            self.publish(job)
        except Exception as error:
            job.state, job.error = 'failed', failure(error)
            self.cleanup(job)
            self.publish(job)

    def cleanup(self, job):
        # A native viewer may still own a lease after its presentation callback.
        if job.directory is not None and not job.exports:
            shutil.rmtree(job.directory, ignore_errors=True)
            job.directory = None
        job.path = None

    def trim(self, newest):
        completed = [job for job in self.jobs.values() if job.state not in ACTIVE and job is not newest and not job.exports]
        retained = sum(job.current for job in self.jobs.values() if job.directory is not None)
        for old in completed:
            if len(self.jobs) <= self.max_history and retained <= self.retained_bytes:
                break
            retained -= old.current if old.directory is not None else 0
            self.cleanup(old)
            self.jobs.pop(old.id, None)
        # One explicitly requested large result may exceed the cache budget.
        # Older completed results are evicted; active downloads are never deleted.

    async def cancel(self, ident, account, attempt=None):
        job = self.get(ident, account)
        if attempt is not None and attempt != job.attempt:
            return job.snapshot()
        if job.state in ('queued', 'downloading'):
            task, generation = job.task, job.attempt
            job.state = 'cancelling'
            self.request_cancel(job)
            self.publish(job)
            await asyncio.gather(task, return_exceptions=True)
            if job.task is not task or job.attempt != generation:
                return job.snapshot()
            # A task cancelled before its first bytecode never enters run().
            job.state, job.error = 'cancelled', None
            self.cleanup(job)
            self.publish(job)
        return job.snapshot()

    @staticmethod
    def request_cancel(job):
        # A second CancelledError could interrupt the backend's first cleanup
        # while it waits for an already-started file writer to finish.
        if job.task is not None and not job.cancel_requested:
            job.cancel_requested = True
            job.task.cancel()

    def retry(self, ident, account, attempt=None):
        job = self.get(ident, account)
        if attempt is not None and attempt != job.attempt:
            return job.snapshot()
        self.check(job)
        if job.state in ('failed', 'cancelled'):
            if sum(item.state in ACTIVE for item in self.jobs.values()) >= self.max_pending:
                raise ValueError('Download queue is full.')
            self.launch(job)
        return job.snapshot()

    async def open(self, ident, action, account):
        if action not in ('file', 'save', 'share'):
            raise ValueError('action')
        job = self.get(ident, account)
        self.check(job)
        if job.state != 'ready' or job.path is None:
            raise ValueError('The download is not ready.')
        job.state, job.error = 'opening', None
        job.action = action
        self.opening[job.id] = asyncio.current_task()
        self.publish(job)
        released, native_started, native_owned, invalid = False, False, False, False
        def release():
            nonlocal released
            if released:
                return
            released = True
            job.exports -= 1
            if job.released:
                self.cleanup(job)
        job.exports += 1
        try:
            _, media = await self.checked_source(job)
            if job.identity is not None and media_identity(media) != job.identity:
                raise LookupError('The attachment changed.')
            if not job.path.is_file():
                raise LookupError('The file is no longer available.')
            self.active_account(account)
            if job.path.name != job.name:
                if job.directory is None:
                    job.directory = self.core.root / FOLDER / job.id
                    job.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                target = job.directory / job.name
                # Prefer a link to immutable cached bytes; no second large copy
                # and cache pruning cannot remove the view's named path.
                try:
                    os.link(job.path, target)
                except OSError:
                    copy = asyncio.create_task(asyncio.to_thread(shutil.copyfile, job.path, target))
                    try:
                        await asyncio.shield(copy)
                    except asyncio.CancelledError:
                        await copy  # Never unlink while the worker still writes.
                        raise
                job.path = target
            self.check(job)
            self.active_account(account)
            native_started = True
            result = await self.core.open_file_with_system(job.path, action,
                release=release if self.core.system == 'iOS' else None)
            native_owned = self.core.system == 'iOS' and bool(result.get('opened'))
            self.active_account(account)
            self.check(job)
            if not result.get('opened'):
                job.error = 'open_failed'
            if self.core.system != 'iOS' or not result.get('opened'):
                release()
            return {'opened': bool(result.get('opened')), 'name': job.name}
        except asyncio.CancelledError:
            if not native_started or self.core.system != 'iOS':
                release()
            raise
        except Exception as error:
            if native_owned:
                # Presentation succeeded before the account changed. Discard
                # the old UI response, but only UIKit's real dismissal may
                # release the file it already owns.
                return {'opened': False, 'name': job.name}
            job.error = failure(error)
            release()
            invalid = isinstance(error, (PermissionError, LookupError, ValueError))
            if invalid:
                self.cleanup(job)
            return {'opened': False, 'name': job.name}
        finally:
            self.opening.pop(job.id, None)
            self.cancelling_open.discard(job.id)
            job.state = 'failed' if invalid else 'ready'
            job.action = None
            self.publish(job)

    async def release_account(self, account=None):
        jobs = [job for job in self.jobs.values() if account is None or job.account == account]
        for job in jobs:
            job.released = True
            self.request_cancel(job)
            if job.id in self.opening and job.id not in self.cancelling_open:
                self.cancelling_open.add(job.id)
                self.opening[job.id].cancel()
        tasks = [task for job in jobs for task in (job.task, self.opening.get(job.id)) if task is not None]
        await asyncio.gather(*tasks, return_exceptions=True)
        for job in jobs:
            self.cleanup(job)
            self.jobs.pop(job.id, None)

    async def close(self):
        self.closed = True
        await self.release_account()


class MobileDownloads:
    """Small Core mixin; lifecycle hooks are explicit in the integration patch."""
    def downloads(self):
        manager = self.__dict__.get('_downloads')
        if manager is None or manager.closed:
            manager = self._downloads = DownloadManager(self)
        return manager

    async def api_download_start(self, peer, id, account, request_id=None):
        return self.downloads().start(peer, id, account, request_id)

    async def api_download_status(self, account):
        return self.downloads().status(account)

    async def api_download_cancel(self, id, account, attempt=None):
        return await self.downloads().cancel(id, account, attempt)

    async def api_download_retry(self, id, account, attempt=None):
        return self.downloads().retry(id, account, attempt)

    async def api_download_open(self, id, action, account):
        return await self.downloads().open(id, action, account)

    async def close_downloads(self, account=None):
        manager = self.__dict__.get('_downloads')
        if manager is not None:
            if account is None:
                await manager.close()
            else:
                await manager.release_account(account)
