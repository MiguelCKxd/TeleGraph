"""Optional WNS wakeups routed back through authenticated Telegram state.

Runs on the account worker's event loop. Push is a hint, not a second source of
message text or permission decisions. The shared desktop notification router
owns final delivery and deduplication.
"""
import asyncio
from collections import OrderedDict
from dataclasses import dataclass
import json
import sys
import time

from .push_windows import PushUnavailable, WindowsPushChannel
from .push_macos import MacPushChannel


def default_channel_factory():
    return MacPushChannel() if sys.platform == 'darwin' else WindowsPushChannel()


@dataclass(frozen=True)
class PushHint:
    user_id: int
    peer: int | None = None
    message_id: int | None = None


def parse_hint(payload):
    if not isinstance(payload, str) or not payload or len(payload) > 65536:
        return None
    try:
        value = json.loads(payload)
        if not isinstance(value, dict):
            return None
        data = value.get('data', value)
        if not isinstance(data, dict):
            return None
        user = int(data.get('user_id', 0))
        if user <= 0:
            return None
        kind = data.get('loc_key', '')
        # These are maintenance hints, not user-visible messages. Never honor
        # remote logout commands from an unverified platform payload.
        if kind in ('SESSION_REVOKE', 'MESSAGE_MUTED', 'READ_HISTORY', 'DC_UPDATE'):
            return PushHint(user)
        custom = data.get('custom', {})
        if not isinstance(custom, dict):
            return PushHint(user)
        peer = None
        if custom.get('channel_id'):
            peer = -1000000000000 - abs(int(custom['channel_id']))
        elif custom.get('chat_id'):
            peer = -abs(int(custom['chat_id']))
        elif custom.get('from_id'):
            peer = int(custom['from_id'])
        message = int(custom.get('msg_id', 0))
        if not peer or message <= 0:
            return PushHint(user)
        return PushHint(user, peer, message)
    except (ValueError, TypeError, OverflowError, RecursionError):
        return None


class PushController:
    """One channel across all connected accounts; never opens a new session."""
    def __init__(self, accounts, publish, report, *, channel_factory=default_channel_factory, clock=time.monotonic):
        self.accounts = accounts
        self.publish = publish
        self.report = report
        self.channel_factory = channel_factory
        self.clock = clock
        self.enabled = False
        self.channel = None
        self.token = None
        self.registered = {}
        self.status = 'Desactivadas. Se utilizan las notificaciones normales.'
        self._gate = asyncio.Lock()
        self._refresh = None
        self._tasks = set()
        self._pending = set()
        self._seen = OrderedDict()
        self._wakes = {}
        self._slots = asyncio.Semaphore(2)
        self._generation = 0
        self._retry_at = 0.0
        self._registered_fingerprint = None

    def _state(self, text):
        if self.status == text:
            return
        self.status = text
        self.report(text)

    def _fingerprint(self):
        return tuple(sorted((key, self.accounts.identities.get(key), id(service.client))
                     for key, service in tuple(self.accounts.services.items())
                     if key in self.accounts.entries and service.backend is not None and service.client is not None))

    async def configure(self, enabled):
        async with self._gate:
            if not enabled:
                await self._stop()
                self._retry_at = 0.0
                self._state('Desactivadas. Se utilizan las notificaciones normales.')
                return
            if self.accounts.demo:
                self._state('Las pruebas de demostración no registran dispositivos push.')
                return
            self.enabled = True
            if self.clock() < self._retry_at:
                return
            fingerprint = self._fingerprint()
            if not fingerprint:
                self._state('Push espera una cuenta conectada. Se mantienen las notificaciones normales.')
                return
            if self.channel is not None and fingerprint == self._registered_fingerprint:
                return
            if self.channel is None:
                channel = self.channel_factory()
                proto = 'APNs' if sys.platform == 'darwin' else 'WNS'
                try:
                    token = await channel.open(self.receive)
                except PushUnavailable as error:
                    await channel.close()
                    self._retry_at = self.clock() + 60
                    self._state(str(error) + ' Las notificaciones normales siguen activas.')
                    return
                except (ImportError, OSError, RuntimeError, asyncio.TimeoutError):
                    await channel.close()
                    self._retry_at = self.clock() + 60
                    self._state(f'No se pudo abrir el canal {proto}. Las notificaciones normales siguen activas.')
                    return
                self.channel, self.token = channel, token
            proto = 'APNs' if sys.platform == 'darwin' else 'WNS'
            try:
                await self._register()
            except Exception:
                # Never expose channel URIs or RPC request representations.
                self._retry_at = self.clock() + 60
                self._state(f'No se pudo registrar {proto} con Telegram. Se mantienen las notificaciones normales.')
                return
            self._registered_fingerprint = fingerprint
            self._state(f'Canal {proto} registrado (experimental). La entrega remota requiere verificar el emisor; el proceso debe permanecer abierto.')
            if self._refresh is None or self._refresh.done():
                self._refresh = asyncio.create_task(self._renew())

    async def _register(self):
        from telethon import functions
        live = {key: service for key, service in tuple(self.accounts.services.items())
                if key in self.accounts.entries and service.backend is not None and service.client is not None}
        for key in tuple(self.registered):
            if key not in live:
                self.registered.pop(key, None)
        token_type = getattr(self.channel, 'token_type', 8)
        sandbox = bool(getattr(self.channel, 'app_sandbox', False))
        for key, service in live.items():
            if self.registered.get(key) is service.client:
                continue
            others = [ident for other, ident in self.accounts.identities.items()
                      if other != key and other in live and type(ident) is int and ident > 0]
            result = await asyncio.wait_for(service.client(functions.account.RegisterDeviceRequest(
                token_type=token_type, token=self.token, app_sandbox=sandbox, secret=b'', other_uids=others)), 20)
            proto = 'APNs' if sys.platform == 'darwin' else 'WNS'
            if result is not True:
                raise PushUnavailable(f'Telegram no ha aceptado el canal {proto}.')
            self.registered[key] = service.client

    async def _renew(self):
        try:
            while self.enabled:
                await asyncio.sleep(23 * 3600)
                if not self.enabled:
                    break
                # Renew platform tokens as well as Telegram registration. The
                # old channel is unregistered before being closed.
                async with self._gate:
                    await self._unregister()
                    if self.channel is not None:
                        await self.channel.close()
                    self.channel = self.token = None
                await self.configure(True)
        except asyncio.CancelledError:
            raise
        except Exception:
            proto = 'APNs' if sys.platform == 'darwin' else 'WNS'
            self._state(f'La renovación de {proto} falló. Se mantienen las notificaciones normales; vuelve a activar push para reintentar.')

    def note_live(self, account, peer, message_id):
        self._seen[(account, peer, message_id)] = self.clock()
        self._seen.move_to_end((account, peer, message_id))
        while len(self._seen) > 4000:
            self._seen.popitem(last=False)

    def forget_live(self, account, peer, message_id):
        self._seen.pop((account, peer, message_id), None)

    def receive(self, payload):
        if not self.enabled or self.channel is None:
            return
        if payload == '':
            # Legacy toast/tile wakeups carry XML instead of the raw JSON
            # schema. Catch up only the already-registered accounts; no payload
            # text is displayed and this never logs into another account.
            for account in tuple(self.registered):
                identity = self.accounts.identities.get(account)
                if type(identity) is int and identity > 0:
                    self._schedule(account, PushHint(identity))
            return
        hint = parse_hint(payload)
        if hint is None:
            return
        account = next((key for key, ident in self.accounts.identities.items()
                        if ident == hint.user_id and key in self.registered and key in self.accounts.entries), None)
        if account is None:
            return
        self._schedule(account, hint)

    def _schedule(self, account, hint):
        key = (account, hint.peer, hint.message_id)
        if key in self._seen or key in self._pending or len(self._pending) >= 128:
            return
        self._pending.add(key)
        task = asyncio.create_task(self._recover(account, hint, self._generation))
        self._tasks.add(task)
        def done(future):
            self._tasks.discard(future)
            self._pending.discard(key)
            if not future.cancelled():
                future.exception()  # retrieve task failures; no unhandled logs
        task.add_done_callback(done)

    async def _recover(self, account, hint, generation):
        from telethon import functions
        try:
            async with self._slots:
                service = self.accounts.services.get(account)
                if (service is None or service.client is not self.registered.get(account)
                        or account not in self.accounts.entries or generation != self._generation):
                    return
                client, backend = service.client, service.backend
                async with asyncio.timeout(25):
                    if service.recovery is not None:
                        await service.recovery.ensure()
                    # Coalesce wake-only payloads. Catch-up uses Telethon's own
                    # update state, so duplicate network updates stay idempotent.
                    now = self.clock()
                    if now - self._wakes.get(account, -100) >= 5:
                        self._wakes[account] = now
                        await client.catch_up()
                    if hint.peer is None or hint.message_id is None:
                        return
                    peer = await client.get_input_entity(hint.peer)
                    from telethon.types import InputDialogPeer
                    dialogs, raw = await asyncio.gather(
                        client(functions.messages.GetPeerDialogsRequest([InputDialogPeer(peer)])),
                        client.get_messages(peer, ids=hint.message_id))
                    dialog = next(iter(getattr(dialogs, 'dialogs', ())), None)
                    if (raw is None or getattr(raw, 'out', False) or dialog is None
                            or getattr(dialog, 'read_inbox_max_id', 0) >= hint.message_id):
                        return
                    if (not self.enabled or generation != self._generation
                            or self.accounts.services.get(account) is not service
                            or account not in self.accounts.entries):
                        return
                    self.publish(account, hint.peer, backend.message(raw))
        except asyncio.CancelledError:
            raise
        except Exception:
            # Telegram live updates remain authoritative and will recover the
            # message later; no generic or unverified payload notification.
            return

    async def _unregister(self):
        from telethon import functions
        token, registered = self.token, self.registered
        token_type = getattr(self.channel, 'token_type', 8)
        self.registered = {}
        self._registered_fingerprint = None
        if token is None:
            return
        async def remove(client):
            try:
                await asyncio.wait_for(client(functions.account.UnregisterDeviceRequest(
                    token_type=token_type, token=token, other_uids=[])), 2)
            except Exception:
                pass  # Closing the platform channel also invalidates delivery.
        await asyncio.gather(*(remove(client) for client in registered.values()))

    async def _stop(self):
        self.enabled = False
        self._generation += 1
        refresh, self._refresh = self._refresh, None
        if refresh is not None and refresh is not asyncio.current_task():
            refresh.cancel()
            await asyncio.gather(refresh, return_exceptions=True)
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._pending.clear()
        await self._unregister()
        channel, self.channel = self.channel, None
        self.token = None
        if channel is not None:
            await channel.close()

    async def close(self):
        async with self._gate:
            await self._stop()
