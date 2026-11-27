"""The notification extension shares only thumbnail images and preview preferences."""
import os
import asyncio
from pathlib import Path
import plistlib
import shutil
import time

MAX_PHOTO_BYTES = 512 * 1024
PHOTO_LIFETIME = 3 * 86400


class NoticeCache:
    def __init__(self, container):
        self.root = Path(container) / 'NoticePreviews'
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.allowed = set()
        self.jobs = {}
        self.slots = None
        self.closed = False

    def sync(self, core):
        from tg_ascii.i18n import tr
        accounts = core.accounts
        values = core.prefs.values if core.prefs else {}
        allowed = set()
        if accounts and core.prefs and values.get('notifications', True) and values.get('notify_preview', True) and not core.lock_record():
            allowed = {uid for key, uid in getattr(accounts, 'identities', {}).items()
                       if key in accounts.entries and key not in core._push_logging_out and type(uid) is int and uid > 0}
        policy = {'accounts': sorted(allowed), 'generic': tr('New message')}
        destination = self.root / 'policy.plist'
        if self.allowed != allowed or getattr(self, '_policy', None) != policy:
            temporary = destination.with_suffix('.tmp')
            try:
                temporary.write_bytes(plistlib.dumps(policy))
                os.replace(temporary, destination)
            except OSError as error:
                self.allowed, self._policy = set(), None
                try:
                    destination.unlink(missing_ok=True)
                except OSError:
                    pass
                print('notification preview policy:', type(error).__name__)
                return
            self.allowed, self._policy = allowed, policy
            for (account, _sender), task in tuple(self.jobs.items()):
                if account not in allowed:
                    task.cancel()
            for folder in self.root.iterdir():
                if folder.is_dir() and folder.name.isdigit() and int(folder.name) not in allowed:
                    shutil.rmtree(folder, ignore_errors=True)

    def thumbnail(self, account_id, sender_id, source):
        if account_id not in self.allowed or type(sender_id) is not int or not 0 < abs(sender_id) < 2 ** 53:
            return
        pending = self.jobs.get((account_id, sender_id))
        if pending is not None:
            try:
                current = asyncio.current_task()
            except RuntimeError:
                current = None
            if pending is not current:
                pending.cancel()
        folder = self.root / str(account_id)
        folder.mkdir(exist_ok=True, mode=0o700)
        destination = folder / f'{int(sender_id)}.jpg'
        if source is None:
            destination.unlink(missing_ok=True)
            return
        temporary = destination.with_suffix('.tmp')
        if isinstance(source, bytes):
            if len(source) > MAX_PHOTO_BYTES:
                return
            temporary.write_bytes(source)
        else:
            if source.stat().st_size > MAX_PHOTO_BYTES:
                return
            if destination.exists() and destination.stat().st_mtime_ns == source.stat().st_mtime_ns:
                return
            shutil.copy2(source, temporary)
        os.replace(temporary, destination)
        destination.with_suffix('.none').unlink(missing_ok=True)

    def forget(self, account_id, sender_id):
        """A removed/changed photo must not survive in the extension's copy."""
        task = self.jobs.get((account_id, sender_id))
        if task is not None:
            task.cancel()
        self.thumbnail(account_id, sender_id, None)
        if account_id in self.allowed:
            (self.root / str(account_id) / f'{sender_id}.none').unlink(missing_ok=True)

    @staticmethod
    def read_photo(path):
        try:
            age = time.time() - path.stat().st_mtime
            if not 0 <= age < PHOTO_LIFETIME:
                return None
            with path.open('rb') as stream:
                picture = stream.read(MAX_PHOTO_BYTES + 1)
            return picture if 0 < len(picture) <= MAX_PHOTO_BYTES else None
        except OSError:
            return None

    async def picture(self, core, key, sender, backend):
        """Use a bounded local copy now; prepare a future alert without delaying this one."""
        self.sync(core)
        accounts = core.accounts
        account = getattr(accounts, 'identities', {}).get(key)

        def current():
            service = getattr(core.accounts, 'services', {}).get(key)
            return (not self.closed and not core._push_stopped and core.accounts is accounts
                    and account in self.allowed and key not in core._push_logging_out
                    and core.prefs and core.prefs.values.get('notifications', True)
                    and core.prefs.values.get('notify_preview', True) and not core.lock_record()
                    and getattr(service, 'backend', None) is backend
                    and accounts.identities.get(key) == account)

        if not current():
            return None
        folder = core.root / 'mobile-avatars' / key
        known_photo = core.photo_id(sender) if key == core.account else None
        if known_photo == 0:
            self.forget(account, sender)
            return None
        # A cached 'no photo' result wins over an older JPG left by the image viewer.
        none = folder / f'{sender}.none'
        if not known_photo and self.read_marker(none):
            self.forget(account, sender)
            return None
        if not known_photo and self.read_marker(self.root / str(account) / f'{sender}.none'):
            return None
        source = folder / f'{sender}.jpg'
        picture = await asyncio.to_thread(self.read_photo, source)
        from_viewer = picture is not None
        if picture is None:
            picture = await asyncio.to_thread(self.read_photo, self.root / str(account) / f'{sender}.jpg')
        if not current():
            return None
        if from_viewer:
            self.thumbnail(account, sender, source)  # Preserve the original age, not the alert's date.
        elif picture is None:
            self.prepare(account, sender, backend, current)
        return picture

    @staticmethod
    def read_marker(path):
        try:
            return 0 <= time.time() - path.stat().st_mtime < PHOTO_LIFETIME
        except OSError:
            return False

    def prepare(self, account, sender, backend, current):
        identity = (account, sender)
        if identity in self.jobs or len(self.jobs) >= 16:
            return
        if self.slots is None:
            self.slots = asyncio.Semaphore(2)

        async def load():
            try:
                async with self.slots:
                    if not current():
                        return
                    photo = await asyncio.wait_for(backend.client.download_profile_photo(
                        sender, file=bytes, download_big=False), 2)
                    if current() and not asyncio.current_task().cancelling():
                        self.thumbnail(account, sender, photo or None)
                        if not photo:
                            (self.root / str(account) / f'{sender}.none').touch()
            except (Exception, asyncio.CancelledError):
                pass  # A missing/slow photo never suppresses the already delivered alert.
            finally:
                if self.jobs.get(identity) is asyncio.current_task():
                    self.jobs.pop(identity, None)
        self.jobs[identity] = asyncio.create_task(load())
        # Cancellation before the first coroutine step does not execute its finally.
        def finished(task):
            if self.jobs.get(identity) is task:
                self.jobs.pop(identity, None)
        self.jobs[identity].add_done_callback(finished)

    def close(self):
        self.closed = True
        for task in tuple(self.jobs.values()):
            task.cancel()
