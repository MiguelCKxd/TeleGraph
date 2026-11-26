"""Media that may be viewed, but must not become a durable local copy.

An HTTP response owns a lease. Concurrent readers share one download; the
last reader removes the entire private directory, including playback muxes.
Callers without a response (startup preloading, exporting) cannot retain it.
"""
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
import shutil
import tempfile
import time

from tg_ascii.media_cache import has_expiry

TEMP_FOLDER = 'temporary-media'
MAX_TRANSIENT_DOWNLOADS = 8
_response = ContextVar('mobile_media_response', default=None)


def expiry_date(message):
    ttl = getattr(message, 'ttl_period', 0)
    date = getattr(message, 'date', None) or getattr(message, 'timestamp', None)
    if not isinstance(ttl, (int, float)) or ttl <= 0:
        return None
    if hasattr(date, 'timestamp'):
        date = date.timestamp()
    return float(date) + ttl if isinstance(date, (int, float)) else None


def transient(message, chat=None):
    return bool(has_expiry(message) or getattr(message, 'protected', False)
                or getattr(message, 'noforwards', False)
                or getattr(getattr(chat, 'entity', None), 'noforwards', False))


def purge_cached(core, account, peer, ident):
    """Remove older-version copies and their derived thumbnail/audio variants."""
    folder = core.root / 'mobile-media' / account
    prefix = f'{int(peer)}-{int(ident)}'
    for (owner, stem), job in list(core.__dict__.get('media_jobs', {}).items()):
        if owner == folder and (stem == prefix or stem.startswith(prefix + '-')):
            job.cancel()
    for path in folder.glob(prefix + '*'):
        suffix = path.name[len(prefix):]
        if not suffix or suffix[0] in '.-':
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    known = core.__dict__.get('media_indexes', {}).get(folder, {})
    for stem in list(known):
        if stem == prefix or stem.startswith(prefix + '-'):
            known.pop(stem, None)


@dataclass(eq=False)
class Lease:
    account: str
    backend: object
    peer: int
    ident: int
    directory: Path
    deadline: float | None
    task: object = None
    readers: int = 0
    revoked: bool = False
    expiry: object = None

    def check(self, core):
        if (self.revoked or core.locked or core.account != self.account
                or core.backend is not self.backend
                or (self.deadline is not None and time.time() >= self.deadline)):
            raise PermissionError('The media is no longer available.')


@dataclass
class Response:
    core: object
    leases: set = field(default_factory=set)
    messages: dict = field(default_factory=dict)

    def check(self):
        for lease in self.leases:
            lease.check(self.core)

    @property
    def temporary(self):
        return bool(self.leases)


def current_response(core):
    response = _response.get()
    return response if response is not None and response.core is core else None


@asynccontextmanager
async def media_response(core):
    response = Response(core)
    token = _response.set(response)
    try:
        yield response
    finally:
        _response.reset(token)
        manager = core.__dict__.get('_transient_media')
        if manager is not None:
            for lease in response.leases:
                await manager.release(lease)


class TransientMedia:
    def __init__(self, core):
        self.core, self.entries = core, {}

    async def file(self, account, backend, peer, ident, message, thumbnail, quality, *, media=None, variant=None):
        response = current_response(self.core)
        if response is None:
            raise PermissionError('Temporary media requires an active viewer.')
        key = (account, id(backend), peer, ident, thumbnail, quality, variant)
        lease = self.entries.get(key)
        if lease is None:
            if len(self.entries) >= MAX_TRANSIENT_DOWNLOADS:
                raise ConnectionError('Too many active media downloads')
            folder = self.core.root / TEMP_FOLDER
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            lease = Lease(account, backend, peer, ident,
                          Path(tempfile.mkdtemp(dir=folder)), expiry_date(message))
            self.entries[key] = lease
            lease.task = asyncio.create_task(self.download(
                lease, message.media if media is None else media, thumbnail, quality))
            if lease.deadline is not None:
                lease.expiry = asyncio.get_running_loop().call_later(
                    max(0, lease.deadline - time.time()), self.expire, lease)
        if lease not in response.leases:
            response.leases.add(lease)
            lease.readers += 1
        lease.check(self.core)
        path = await asyncio.shield(lease.task)
        lease.check(self.core)
        return path

    async def download(self, lease, media, thumbnail, quality):
        lease.check(self.core)
        # An extensionless, unique destination skips the shared preview cache.
        # Telegram still supplies the original bytes and infers their format.
        result = await lease.backend.download_media(media, lease.directory / 'media',
                                                    thumbnail=thumbnail, quality=quality)
        lease.check(self.core)
        return Path(result) if result else None

    async def release(self, lease):
        lease.readers -= 1
        if lease.readers > 0:
            return
        for key, value in list(self.entries.items()):
            if value is lease:
                self.entries.pop(key, None)
        if lease.expiry is not None:
            lease.expiry.cancel()
        lease.task.cancel()
        await asyncio.gather(lease.task, return_exceptions=True)
        shutil.rmtree(lease.directory, ignore_errors=True)

    def expire(self, lease):
        lease.revoked = True
        lease.task.cancel()
        shutil.rmtree(lease.directory, ignore_errors=True)

    def revoke(self, account, peer, identifiers):
        for lease in list(self.entries.values()):
            if lease.account == account and (peer is None or lease.peer == peer) and lease.ident in identifiers:
                self.expire(lease)

    async def close(self):
        leases = list(self.entries.values())
        self.entries.clear()
        for lease in leases:
            lease.revoked = True
            lease.task.cancel()
            if lease.expiry is not None:
                lease.expiry.cancel()
        await asyncio.gather(*(lease.task for lease in leases), return_exceptions=True)
        for lease in leases:
            shutil.rmtree(lease.directory, ignore_errors=True)
