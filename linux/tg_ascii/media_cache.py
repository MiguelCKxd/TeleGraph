"""Persistent, per-account, content-addressed cache for previews and emoji art.

Before 1.3.2 every preview lived in a per-session temporary directory, so each
launch downloaded again every thumbnail, sticker and custom emoji that became
visible, and re-rendered every animated emoji with rlottie/PyAV. That cost
bandwidth, CPU and, above all, Telegram rate limits (FLOOD_WAIT) at startup.

Entries are keyed by Telegram's immutable media identifiers (photo/document id
plus thumbnail type), never by chat or message, so a cached file can never be
"stale": Telegram never changes the bytes behind an existing photo/document id.
Avatars, wallpapers, themes and other mutable art keep their previous
per-session behaviour and are not routed through this cache.

Location: <data dir>/media-cache/<account key>/v1/. The data directory is
already private (0700) and holds the far more sensitive .session files. The
cache is bounded (oldest files are evicted) and an account's folder is deleted
when that account logs out. All disk work runs off the Tk thread.
"""
import os
from pathlib import Path
import shutil
import tempfile

CACHE_VERSION = 'v1'
MAX_BYTES = 384 * 1024 * 1024
TARGET_BYTES = 256 * 1024 * 1024
_SAFE_SUFFIXES = frozenset(('.jpg', '.jpeg', '.png', '.webp', '.gif', '.mp4', '.webm', '.tgs', '.source'))


def account_directory(root, account):
    return Path(root) / 'media-cache' / str(account)


def cache_directory(root, account):
    return account_directory(root, account) / CACHE_VERSION


def configure(backend, root, account):
    try:
        backend.media_cache_dir = cache_directory(root, account)
    except AttributeError:
        pass


def media_identity(media):
    """('p'|'d', id) for a Telegram Photo/Document (or something wrapping one)."""
    from telethon import types
    source = getattr(media, 'media', None) or media
    item = getattr(source, 'document', None) or getattr(source, 'photo', None) or source
    ident = getattr(item, 'id', None)
    if not isinstance(ident, int):
        return None
    if isinstance(item, types.Document):
        return 'd', ident
    if isinstance(item, types.Photo):
        return 'p', ident
    return None


def preview_entry(backend, media, thumb, suffix):
    """Cache path for one preview of ``media``, or None when it must not be cached."""
    directory = getattr(backend, 'media_cache_dir', None)
    if directory is None or suffix.lower() not in _SAFE_SUFFIXES:
        return None
    identity = media_identity(media)
    if identity is None:
        return None
    kind, ident = identity
    variant = ''.join(ch for ch in str(thumb if thumb is not None else 'o') if ch.isalnum())[:8] or 'o'
    return Path(directory) / 'previews' / f'{kind}{ident}-{variant}{suffix.lower()}'


def avatar_entry(backend, photo_id):
    """Small profile photo keyed by its immutable photo id (1.4)."""
    directory = getattr(backend, 'media_cache_dir', None)
    if directory is None or not isinstance(photo_id, int):
        return None
    return Path(directory) / 'avatars' / f'a{photo_id}.jpg'


def emoji_base(backend, document_id):
    directory = getattr(backend, 'media_cache_dir', None)
    if directory is None or not isinstance(document_id, int):
        return None
    folder = Path(directory) / 'emoji'
    try:
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        return None
    return folder / f'emoji-{document_id}'


def _replace_from(source, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix='.tg-cache-', suffix=target.suffix, dir=target.parent)
    os.close(descriptor)
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def fetch(entry, target):
    """Copy a cached preview to ``target``. True on a hit; never raises."""
    try:
        if not entry.is_file() or entry.stat().st_size <= 0:
            return False
        if Path(target).resolve() != entry.resolve():
            _replace_from(entry, target)
        try:
            os.utime(entry)  # Recently used entries survive eviction.
        except OSError:
            pass
        return True
    except OSError:
        return False


def store(entry, source):
    """Best effort: a full disk or a racing eviction only skips caching."""
    try:
        if Path(source).is_file() and Path(source).stat().st_size > 0:
            _replace_from(source, entry)
    except OSError:
        pass


def touch(path):
    try:
        os.utime(path)
    except OSError:
        pass


def prune(directory, max_bytes=MAX_BYTES, target_bytes=TARGET_BYTES):
    """Evict least recently used files once the account cache exceeds its budget."""
    directory = Path(directory)
    if not directory.is_dir():
        return 0
    files = []
    total = 0
    for path in directory.rglob('*'):
        try:
            if path.is_file() and not path.is_symlink():
                info = path.stat()
                files.append((info.st_mtime, info.st_size, path))
                total += info.st_size
        except OSError:
            continue
    if total <= max_bytes:
        return 0
    removed = 0
    for _, size, path in sorted(files):
        if total <= target_bytes:
            break
        try:
            path.unlink()
            total -= size
            removed += 1
        except OSError:
            continue
    return removed


async def prune_once(backend):
    directory = getattr(backend, 'media_cache_dir', None)
    if directory is None or getattr(backend, '_media_cache_pruned', False):
        return
    backend._media_cache_pruned = True
    import asyncio
    from .resources import disk_cache
    await asyncio.to_thread(prune, directory, *disk_cache(MAX_BYTES, TARGET_BYTES))


def purge(root, account):
    """Delete one account's cache (logout). Never touches another account."""
    shutil.rmtree(account_directory(root, account), ignore_errors=True)
