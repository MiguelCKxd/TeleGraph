"""Session-owned account facts, refreshed by Telegram updates rather than each feature."""
import asyncio
from datetime import datetime, timezone
from telethon.types import User

PROFILE_TIMEOUT = 15


class AccountProfile:
    def __init__(self, client, changed=None):
        self.client = client
        self.changed = changed
        self.user = None
        self.premium = False
        self.checked_at = None
        self._stale = False
        self._revision = 0
        self._lock = asyncio.Lock()

    @property
    def user_id(self):
        return getattr(self.user, 'id', None)

    def snapshot(self):
        return {'user_id': self.user_id, 'premium': self.premium,
                'checked_at': self.checked_at, 'verified': self.user is not None and not self._stale}

    def remember(self, user):
        """Accept full self data only; another account must never change this session."""
        if not isinstance(user, User):
            return False
        identity = getattr(user, 'id', None)
        if not isinstance(identity, int) or isinstance(identity, bool) or identity <= 0:
            return False
        if getattr(user, 'min', False) is True:
            return False
        if self.user_id is not None and identity != self.user_id:
            return False
        previous = self.premium if self.user is not None else None
        self.user = user
        self.premium = getattr(user, 'premium', False) is True
        self.checked_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
        self._stale = False
        self._revision += 1
        if previous != self.premium and self.changed:
            self.changed(self.premium)
        return True

    def invalidate(self):
        self._stale = True

    async def ensure(self):
        if self.user is None or self._stale:
            await self.refresh()
        return self.user

    async def refresh(self):
        revision = self._revision
        async with self._lock:
            # Concurrent views/manual refreshes share the first completed request.
            if self._revision != revision and not self._stale:
                return self.user
            user = await asyncio.wait_for(self.client.get_me(), PROFILE_TIMEOUT)
            if self._revision != revision and not self._stale:
                return self.user  # A newer push update arrived during the request.
            if not self.remember(user):
                raise ValueError('Telegram did not return the authorized account profile.')
            return self.user
