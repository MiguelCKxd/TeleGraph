"""Telegram operations, all owned by the desktop application's asyncio thread."""
import asyncio
import os
from pathlib import Path
import re
import sys

from telethon import TelegramClient, errors

from . import APP_NAME, __version__
from .auth import (SetupError, bundled_credentials, load_credentials,
                   normalize_phone, save_credentials, validate_credentials)
from .backend import DemoBackend, TelegramBackend
from .i18n import tr

CONNECT_TIMEOUT = 30
AUTH_TIMEOUT = 30
DISCONNECT_TIMEOUT = 10
RECONNECT_TIMEOUT = 45
OFFLINE_START_TIMEOUT = 8  # 1.5.3: a signed-in device opens offline after this


class DesktopService:
    def __init__(self, demo=False, root=None, client_factory=TelegramClient, session_path=None):
        self.demo = demo
        self.root = Path(root or os.environ.get('TG_ASCII_DATA_DIR', str(Path.home() / '.tg-ascii'))).expanduser()
        self.client_factory = client_factory
        self.client = None
        self.recovery = None
        self.backend = None
        self.phone = None
        self.code_hash = None
        self.credentials = None
        self.remember = False
        self.on_message = None
        self.on_change = None
        self.config_warning = False
        self.session_path = Path(session_path) if session_path else self.root / 'account'

    async def connect(self, credentials=None, remember=False, configure=False):
        if self.demo:
            self.backend = DemoBackend()
            return 'ready'
        await self.close()
        self.phone = self.code_hash = None
        if credentials is None:
            credentials = bundled_credentials()
            if credentials is None and getattr(sys, 'frozen', False):
                raise SetupError(tr('Esta compilacion no contiene la configuracion de TG-ASCII. Pide una version completa al desarrollador.'))
            if credentials is None:
                env_id, env_hash = os.environ.get('TG_API_ID'), os.environ.get('TG_API_HASH')
                if env_id or env_hash:
                    credentials = validate_credentials(env_id, env_hash)
                elif not configure:
                    try:
                        credentials = load_credentials(self.root)
                    except SetupError:
                        # A damaged developer config can be replaced through
                        # the window, without requiring a terminal flag.
                        return 'credentials'
            if credentials is None:
                return 'credentials'
        self.credentials = validate_credentials(*credentials)
        self.remember = remember
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.session_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.client = self.client_factory(str(self.session_path), *self.credentials,
            device_model=f'{APP_NAME} Desktop', app_version=__version__,
            connection_retries=2, request_retries=1, flood_sleep_threshold=0)
        self.offline_start = False
        try:
            # Include authorization in the deadline: a connected socket does
            # not imply that Telegram is answering requests.
            async with asyncio.timeout(OFFLINE_START_TIMEOUT if self.saved_session() else CONNECT_TIMEOUT):
                await self.client.connect()
                authorized = await self.client.is_user_authorized()
            if authorized:
                return self.ready()
            return 'phone'
        except (OSError, ConnectionError, TimeoutError, asyncio.TimeoutError) as error:
            # 1.5.3: no network, but this device is already signed in. Open
            # the app with its local copy; Recovery connects in the background
            # and everything done meanwhile waits in the pending queues.
            if self.saved_session():
                from .recovery import record_failure
                record_failure(self.root, 'offline_start', error)
                self.offline_start = True
                state = self.ready()
                self.recovery.emit('offline')
                return state
            try:
                await self.close()
            except Exception as cleanup_error:
                from .recovery import record_failure
                record_failure(self.root, 'connect_cleanup', cleanup_error)
            raise
        except BaseException:
            try:
                await self.close()
            except Exception as cleanup_error:
                # Keep the original connection/cancellation error visible.
                from .recovery import record_failure
                record_failure(self.root, 'connect_cleanup', cleanup_error)
            raise

    def saved_session(self):
        """True when this device already holds an authorization key."""
        session = getattr(self.client, 'session', None)
        key = getattr(getattr(session, 'auth_key', None), 'key', None)
        return isinstance(key, (bytes, bytearray)) and len(key) == 256

    def ready(self, user=None):
        if self.backend is not None:
            if user is not None:
                self.backend.account_profile.remember(user)
            return 'ready'
        self.backend = TelegramBackend(self.client)
        from .profile_customization import configure_design
        account = 'account' if self.session_path.parent == self.root else self.session_path.parent.name
        configure_design(self.backend, self.root, account)
        from .media_cache import configure as configure_media_cache
        configure_media_cache(self.backend, self.root, account)
        if hasattr(self.backend, 'secret_chats'):
            self.backend.secret_chats.configure(self.root, account)
        self.backend.callback = self.on_message
        self.backend.on_change = self.on_change
        if user is not None:
            self.backend.account_profile.remember(user)
        from .pending_actions import attach as attach_pending
        attach_pending(self, account)
        from .recovery import Recovery
        self.recovery=Recovery(self);self.recovery.start()
        pending = getattr(self, 'pending', None)
        if pending is not None and pending.records:
            # Actions saved before the last close go out now if Telegram answers.
            try:
                asyncio.get_running_loop().create_task(pending.flush())
            except RuntimeError:
                pass
        if self.remember:
            try:
                save_credentials(self.root, self.credentials)
            except OSError:
                self.config_warning = True
        return 'ready'

    async def request_code(self, phone):
        phone = normalize_phone(phone)
        try:
            sent = await asyncio.wait_for(self.client.send_code_request(phone), AUTH_TIMEOUT)
        except (errors.PhoneNumberUnoccupiedError, errors.PhoneNumberAppSignupForbiddenError):
            self.phone = self.code_hash = None
            return 'signup'
        self.phone, self.code_hash = phone, sent.phone_code_hash
        return 'code'

    async def verify_code(self, code):
        code = re.sub(r'[\s-]', '', code)
        if not code:
            raise ValueError(tr('Introduce el codigo de Telegram.'))
        try:
            user = await asyncio.wait_for(self.client.sign_in(
                phone=self.phone, code=code, phone_code_hash=self.code_hash), AUTH_TIMEOUT)
        except errors.SessionPasswordNeededError:
            return 'password'
        except (errors.PhoneNumberUnoccupiedError, errors.PhoneNumberAppSignupForbiddenError):
            self.phone = self.code_hash = None
            return 'signup'
        return self.ready(user)

    async def verify_password(self, password):
        user = await asyncio.wait_for(self.client.sign_in(password=password), AUTH_TIMEOUT)
        return self.ready(user)

    async def refresh_profile(self):
        if self.backend is not None and not self.demo:
            self.backend.account_profile.invalidate()
            return await self.backend.refresh_account()

    async def reconnect(self):
        """Explicit transport reset; keep one backend, handlers and saved session."""
        if self.demo:
            return
        if self.backend is None or self.recovery is None:
            raise ValueError(tr('Inicia sesion de nuevo'))
        async with asyncio.timeout(RECONNECT_TIMEOUT):
            await self.recovery.ensure(force=True)

    async def close(self):
        if self.recovery:
            await self.recovery.stop()
            self.recovery = None
        backend, client = self.backend, self.client
        self.backend = self.client = None
        self.phone = self.code_hash = None
        if backend:
            await asyncio.wait_for(backend.close(), DISCONNECT_TIMEOUT)
        elif client:
            await asyncio.wait_for(client.disconnect(), DISCONNECT_TIMEOUT)
