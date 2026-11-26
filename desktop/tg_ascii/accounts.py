"""Multiple independent Telethon sessions on one worker event loop."""
import asyncio
import re
import uuid
from copy import deepcopy
from pathlib import Path

from .desktop_service import DesktopService
from .preferences import data_root, read_json, write_json
from .i18n import tr

ACCOUNT_RPC_TIMEOUT = 30


class Accounts:
    def __init__(self, demo=False, root=None, factory=DesktopService):
        self.root = Path(root) if root else data_root()
        self.demo, self.factory = demo, factory
        self.on_message = None
        self.on_change = None
        self.on_registry = None
        self.services, self.labels, self.identities = {}, {}, {}
        self._photo_tasks, self._photo_ids = {}, {}
        self._closing = False
        self._leaving_accounts = set()
        self.current = 'account'
        self.credentials = None
        self.failures = {}
        self.registry = {'active': 'account', 'accounts': {'account': {}}}
        if not demo:
            self.registry = read_json(self.root / 'accounts.json', self.registry)
        self._persisted_registry = deepcopy(self.registry)
        self._restore_slots = asyncio.Semaphore(3)
        entries = self.registry.get('accounts', {})
        if not isinstance(entries, dict):
            entries = {}
        self.entries = {k: v for k, v in entries.items()
                        if re.fullmatch(r'account|[a-f0-9]{32}', k) and isinstance(v, dict)}
        if not self.entries:
            # An explicitly empty registry follows logout. Never reuse the
            # legacy account slot and its old local data for a different login.
            active = self.registry.get('active')
            fresh = active if isinstance(active, str) and re.fullmatch(r'[a-f0-9]{32}', active) else uuid.uuid4().hex
            self.entries = {fresh: {}}
        active = self.registry.get('active')
        self.current = active if isinstance(active, str) and active in self.entries else next(iter(self.entries))
        for key, value in self.entries.items():
            self.labels[key] = str(value.get('label', tr('Cuenta')))
            self.identities[key] = value.get('user_id')

    def service(self, key):
        if key not in self.services:
            session = self.root / 'account' if key == 'account' else self.root / 'accounts' / key / 'account'
            service = self.factory(demo=self.demo, root=self.root, session_path=session)
            service.on_message = lambda peer, msg: self.on_message(key, peer, msg) if self.on_message else None
            service.on_change = lambda kind, payload: self.changed(key, kind, payload)
            self.services[key] = service
        return self.services[key]

    def changed(self, key, kind, payload):
        if kind == 'premium' and key in self.entries:
            self.entries[key]['premium'] = payload is True
            self.persist()
        if self.on_change:
            self.on_change(key, kind, payload)

    @property
    def backend(self):
        return self.service(self.current).backend

    @property
    def config_warning(self):
        return self.service(self.current).config_warning

    async def connect(self, credentials=None, remember=False, configure=False):
        key = self.current
        state = await self.service(key).connect(credentials or self.credentials, remember, configure)
        self.credentials = self.service(key).credentials or self.credentials
        if state == 'ready':
            await self.register(key)
            # Each saved session stays connected, including background accounts.
            await self.restore_saved()
        return state

    async def register(self, key):
        service = self.service(key)
        known = self.entries.get(key) or {}
        if not self.demo and getattr(service, 'offline_start', False) and known.get('user_id'):
            # 1.5.3: opened without a connection; the saved name and id are
            # enough until Recovery connects (then the profile refreshes).
            self.labels[key], self.identities[key] = str(known.get('label') or tr('Cuenta')), known['user_id']
            self.failures[key] = tr('Sin conexion')
            return
        if self.demo:
            label, identity = 'Demo', key
        else:
            profile = getattr(getattr(service, 'backend', None), 'account_profile', None)
            me = await asyncio.wait_for(profile.ensure() if profile is not None else service.client.get_me(), ACCOUNT_RPC_TIMEOUT)
            identity = me.id
            label = ' '.join(filter(None, [me.first_name, me.last_name])) or str(me.id)
            duplicate = next((k for k, ident in self.identities.items()
                              if ident == identity and k != key), None)
            if duplicate:
                await service.close()
                self.services.pop(key, None)
                raise ValueError(tr('Esta cuenta ya esta añadida. Vuelve y seleccionala.'))
        if self._closing or key in self._leaving_accounts:
            return
        self.labels[key], self.identities[key] = label, identity
        self.entries[key] = {'label': label, 'user_id': identity}
        if not self.demo:
            self.entries[key]['premium'] = getattr(me, 'premium', False) is True
            # 3.2: the startup chooser shows each account's own picture.
            self._remember_photo(key, service.client, me)
        self.failures.pop(key, None)
        self.persist()

    def _remember_photo(self, key, client, me):
        from .account_photos import has_photo, photo_path, remember
        identity = getattr(getattr(me, 'photo', None), 'photo_id', None)
        signature = (getattr(me, 'id', None), identity, has_photo(me))
        previous = self._photo_tasks.get(key)
        if previous is not None:
            if previous[0] == signature:
                return
            previous[1].cancel()
        if self._photo_ids.get(key) == signature and (not has_photo(me) or photo_path(self.root, key).is_file()):
            return
        task = asyncio.get_running_loop().create_task(remember(self.root, key, client, me))
        self._photo_tasks[key] = (signature, task)

        def finished(done):
            if self._photo_tasks.get(key) != (signature, done):
                return
            self._photo_tasks.pop(key, None)
            if not done.cancelled() and done.exception() is None and (done.result() or not signature[2]):
                self._photo_ids[key] = signature
        task.add_done_callback(finished)

    async def _cancel_photos(self, key=None):
        keys = list(self._photo_tasks) if key is None else [key]
        tasks = [value[1] for name in keys if (value := self._photo_tasks.pop(name, None)) is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if key is not None:
            self._photo_ids.pop(key, None)

    def reorder(self, keys):
        """1.5.4: the order of the account picker (this window's data only)."""
        ordered = [key for key in keys if key in self.entries]
        ordered += [key for key in self.entries if key not in ordered]
        self.entries = {key: self.entries[key] for key in ordered}
        self.persist()

    def persist(self):
        snapshot = {'active': self.current, 'accounts': self.entries}
        reordered = list(self.entries) != list((self._persisted_registry or {}).get('accounts') or {})
        if not self.demo and (snapshot != self._persisted_registry or reordered):
            write_json(self.root / 'accounts.json', snapshot)
            self._persisted_registry = deepcopy(snapshot)
        if self.on_registry:
            self.on_registry()

    async def add(self):
        self.current = uuid.uuid4().hex
        self.labels[self.current] = tr('Nueva cuenta')
        state = await self.service(self.current).connect(self.credentials)
        if state == 'ready':
            await self.register(self.current)
        return state

    async def select(self, key):
        if key not in self.entries:
            raise ValueError(tr('Cuenta desconocida'))
        if self.current not in self.entries and self.current != key:
            pending = self.services.pop(self.current, None)
            if pending:
                await pending.close()
        service = self.service(key)
        if service.backend is None:
            state = await service.connect(self.credentials)
        else:
            if getattr(service,'recovery',None):await service.recovery.ensure()
            state = 'ready'
        self.current = key
        if state == 'ready':
            await self.register(key)
        return state

    async def request_code(self, phone):
        return await self.service(self.current).request_code(phone)

    async def login_qr(self, publish):
        """Expiring tokens remain in memory; cancellation removes Telethon's waiter."""
        from telethon import errors
        key = self.current
        service = self.service(key)
        ignored = [identity for identity in self.identities.values() if isinstance(identity, int)]
        while self.current == key:
            qr = await asyncio.wait_for(service.client.qr_login(ignored_ids=ignored), ACCOUNT_RPC_TIMEOUT)
            publish(qr.url)
            try:
                user = await qr.wait()
            except asyncio.TimeoutError:
                continue
            except errors.SessionPasswordNeededError:
                return 'password'
            if self.current != key: raise asyncio.CancelledError()
            state = service.ready(user)
            await self.register(key)
            await self.restore_saved()
            return state
        raise asyncio.CancelledError()

    async def verify_code(self, code):
        state = await self.service(self.current).verify_code(code)
        if state == 'ready':
            await self.register(self.current)
            await self.restore_saved()
        return state

    async def verify_password(self, password):
        state = await self.service(self.current).verify_password(password)
        if state == 'ready':
            await self.register(self.current)
            await self.restore_saved()
        return state

    async def restore_saved(self):
        async def restore(key):
            async with self._restore_slots:
                # Another restore/select may already have opened this session.
                if key == self.current or key in self.services:
                    return
                try:
                    state = await self.service(key).connect(self.credentials)
                    if state == 'ready':
                        await self.register(key)
                    else:
                        self.failures[key] = tr('Inicia sesion de nuevo')
                except Exception:
                    self.failures[key] = tr('Sin conexion')
        await asyncio.gather(*(restore(key) for key in list(self.entries)
                               if key != self.current and key not in self.services))

    async def recover(self,key=None):
        key=self.current if key is None else key
        if self.demo:return
        if key not in self.entries:raise ValueError(tr('Cuenta desconocida'))
        service=self.service(key)
        if service.backend is None or service.recovery is None:raise ValueError(tr('Inicia sesion de nuevo'))
        await service.recovery.ensure()

    async def refresh_account(self, key=None):
        key = self.current if key is None else key
        if self.demo:
            return {'user_id': key, 'premium': False, 'verified': True, 'checked_at': None}
        if key not in self.entries:
            raise ValueError(tr('Cuenta desconocida'))
        service = self.service(key)
        if service.backend is None:
            raise ValueError(tr('Inicia sesion de nuevo'))
        result = await service.backend.refresh_account()
        await self.register(key)
        return result

    async def reconnect(self, key=None):
        key = self.current if key is None else key
        if self.demo:
            return
        if key not in self.entries:
            raise ValueError(tr('Cuenta desconocida'))
        await self.service(key).reconnect()

    async def close(self):
        # Disconnect saves SQLite sessions; log_out would revoke them.
        self._closing = True
        await self._cancel_photos()
        await asyncio.gather(*(service.close() for service in self.services.values()), return_exceptions=True)

    async def logout(self, key):
        """Revoke exactly the chosen authorization; never touch another session."""
        if key not in self.entries:
            raise ValueError(tr('Cuenta desconocida'))
        service = self.service(key)
        if not self.demo:
            if getattr(service,'recovery',None):await service.recovery.stop()
            if service.client is None:
                await service.connect(self.credentials)
            try:
                if not await service.client.log_out():
                    raise ValueError(tr('Logout failed. The account has been kept.'))
            except Exception:
                if getattr(service,'recovery',None):
                    from .recovery import Recovery
                    service.recovery=Recovery(service);service.recovery.start()
                raise
        self._leaving_accounts.add(key)
        await self._cancel_photos(key)
        await service.close()
        if not self.demo:
            # Cached previews belong to the account that is leaving.
            from .media_cache import purge
            await asyncio.to_thread(purge, self.root, key)
            from . import offline_store, pending_actions, secret_chats
            await asyncio.to_thread(offline_store.purge, self.root, key)
            await asyncio.to_thread(pending_actions.purge, self.root, key)
            await asyncio.to_thread(secret_chats.purge, self.root, key)
            from .account_photos import photo_path
            await asyncio.to_thread(photo_path(self.root, key).unlink, missing_ok=True)
            from .recent_searches import RecentSearches
            await asyncio.to_thread(RecentSearches(self.root).forget_account, key)
        self.services.pop(key, None)
        self.entries.pop(key, None)
        self.labels.pop(key, None)
        self.identities.pop(key, None)
        self.failures.pop(key, None)
        if self.current == key:
            self.current = next(iter(self.entries), uuid.uuid4().hex)
        self.persist()
        if self.current in self.entries:
            return await self.select(self.current)
        return await self.service(self.current).connect(self.credentials)


class AccountsView(Accounts):
    """A window selection over one live registry, never a second session owner.

    Registry methods run on the shared asyncio worker. Each view selects its own
    key; connect/login/logout reuse the original DesktopService instances.
    """
    _SHARED = frozenset(('root', 'demo', 'factory', 'services', 'labels', 'identities',
                         'entries', 'failures', 'credentials', '_restore_slots',
                         '_photo_tasks', '_photo_ids', '_closing', '_leaving_accounts',
                         'registry', '_persisted_registry', 'on_registry'))

    def __init__(self, owner, current=None, pinned=False):
        self._pinned_account = current if pinned else None
        if pinned and current not in owner.entries:
            raise ValueError(tr('Inicia sesion de nuevo'))
        self.owner = owner.owner if isinstance(owner, AccountsView) else owner
        self.current = current if current in self.owner.entries else self.owner.current

    def __getattr__(self, name):
        if name in self._SHARED:
            return getattr(self.owner, name)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if name in self._SHARED and 'owner' in self.__dict__:
            setattr(self.owner, name, value)
        else:
            object.__setattr__(self, name, value)

    def service(self, key):
        if self._pinned_account is not None:
            service = self.owner.services.get(key)
            if key != self._pinned_account or key not in self.owner.entries or service is None or service.backend is None:
                raise ValueError(tr('Inicia sesion de nuevo'))
            return service
        return self.owner.service(key)

    def persist(self):
        self.owner.persist()

    async def close(self):
        # Closing a view is not permission to disconnect shared authorizations.
        return None

    async def restore_saved(self):
        await self.owner.restore_saved()

    async def select(self, key):
        if key not in self.entries:
            raise ValueError(tr('Cuenta desconocida'))
        service = self.service(key)
        if service.backend is None:
            # A saved but disconnected account is reauthenticated in the main
            # window, so two linked views cannot race the same login challenge.
            raise ValueError(tr('Inicia sesion de nuevo'))
        if getattr(service, 'recovery', None):
            await service.recovery.ensure()
        self.current = key
        return 'ready'

    async def add(self):
        raise ValueError(tr('Añade cuentas desde la ventana principal.'))

    async def connect(self, credentials=None, remember=False, configure=False):
        return await self.select(self.current)

    async def logout(self, key):
        raise ValueError(tr('Cierra sesiones desde la ventana principal.'))
