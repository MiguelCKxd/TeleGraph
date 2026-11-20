"""The notification extension shares only thumbnail images and preview preferences."""
import os
from pathlib import Path
import plistlib
import shutil


class NoticeCache:
    def __init__(self, container):
        self.root = Path(container) / 'NoticePreviews'
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.allowed = set()

    def sync(self, core):
        from tg_ascii.i18n import tr
        accounts = core.accounts
        if accounts is None or core.prefs is None:
            return
        values = core.prefs.values
        allowed = set()
        if values.get('notifications', True) and values.get('notify_preview', True) and not core.lock_record():
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
            for folder in self.root.iterdir():
                if folder.is_dir() and folder.name.isdigit() and int(folder.name) not in allowed:
                    shutil.rmtree(folder, ignore_errors=True)

    def thumbnail(self, account_id, sender_id, source):
        if account_id not in self.allowed or not sender_id:
            return
        folder = self.root / str(account_id)
        folder.mkdir(exist_ok=True, mode=0o700)
        destination = folder / f'{int(sender_id)}.jpg'
        if source is None:
            destination.unlink(missing_ok=True)
            return
        temporary = destination.with_suffix('.tmp')
        if isinstance(source, bytes):
            temporary.write_bytes(source)
        else:
            if destination.exists() and destination.stat().st_mtime_ns == source.stat().st_mtime_ns:
                return
            shutil.copy2(source, temporary)
        os.replace(temporary, destination)
