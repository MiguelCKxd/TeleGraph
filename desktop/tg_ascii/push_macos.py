"""Optional APNs transport, available only with a signed and provisioned macOS app bundle.

Uses platform remote-notification registration, never a fabricated token.
Registering an APNs token does not prove Telegram's server has the bundle's
APNs certificate configured. Portable or ad-hoc signed builds report their
provisioning requirement and keep normal notifications active.
"""
import asyncio
import json
from pathlib import Path
import re
import subprocess
import sys

from .push_windows import PushCapability, PushUnavailable

APP_ID = 'org.tgas.desktop'
ENTITLEMENT_KEYS = (
    'com.apple.developer.aps-environment',
    'aps-environment',
)


def valid_apns_token(token):
    return isinstance(token, str) and bool(re.fullmatch(r'[0-9a-fA-F]{64,512}', token))


def _bundle_path():
    try:
        import Foundation
        bundle = Foundation.NSBundle.mainBundle()
        if bundle is not None and str(bundle.bundleIdentifier()) == APP_ID:
            path = bundle.bundlePath()
            if path:
                return Path(str(path))
    except Exception:
        pass
    try:
        exe = Path(sys.executable).resolve()
        for candidate in exe.parents:
            if (candidate / 'Contents/Info.plist').is_file():
                import plistlib
                with (candidate / 'Contents/Info.plist').open('rb') as f:
                    info = plistlib.load(f)
                if info.get('CFBundleIdentifier') == APP_ID:
                    return candidate
    except Exception:
        pass
    return None


def _entitlement_environment(bundle_path):
    if bundle_path is None:
        return None
    try:
        result = subprocess.run(
            ['/usr/bin/codesign', '-d', '--entitlements', '-', '--xml', str(bundle_path)],
            capture_output=True, timeout=5, check=False,
        )
        if result.returncode == 0 and result.stdout:
            import plistlib
            entitlements = plistlib.loads(result.stdout)
            if isinstance(entitlements, dict):
                for key in ENTITLEMENT_KEYS:
                    value = entitlements.get(key)
                    if value in ('development', 'production'):
                        return value
    except Exception:
        pass
    return None


def capability(bundle_path=None):
    if sys.platform != 'darwin':
        return PushCapability(False, 'El transporte APNs experimental está disponible sólo en macOS.')
    bundle = Path(bundle_path) if bundle_path is not None else _bundle_path()
    if bundle is None:
        return PushCapability(False, 'APNs necesita el paquete TG-ASCII.app compilado.')
    env = _entitlement_environment(bundle)
    if env is None:
        return PushCapability(False, 'APNs necesita un perfil de aprovisionamiento de Apple Developer con capacidad push; esta compilación usa firma local.')
    return PushCapability(True, 'Canal APNs disponible para pruebas (' + env + '). El certificado APNs del servidor de Telegram requiere validación.')


class MacPushChannel:
    token_type = 1

    def __init__(self):
        self.app_sandbox = False
        self._receive = None
        self._loop = None
        self._observer = None

    async def open(self, receive):
        status = capability()
        if not status.available:
            raise PushUnavailable(status.reason)
        bundle = _bundle_path()
        self.app_sandbox = _entitlement_environment(bundle) == 'development'
        self._receive = receive
        self._loop = asyncio.get_running_loop()
        token = await self._request_token()
        if not valid_apns_token(token):
            raise PushUnavailable('macOS no ha proporcionado un token APNs válido.')
        return token.lower()

    async def _request_token(self):
        try:
            import AppKit, objc
        except ImportError:
            raise PushUnavailable('macOS no cuenta con las bibliotecas del sistema necesarias para APNs.')

        app = AppKit.NSApplication.sharedApplication()
        delegate = app.delegate()
        if delegate is None:
            try:
                from Foundation import NSObject
                class PushAppDelegate(NSObject):
                    pass
                delegate = PushAppDelegate.new()
                app.setDelegate_(delegate)
            except Exception:
                pass
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def did_register(s, application, token_data):
            try:
                raw_bytes = bytes(token_data)
                token_hex = raw_bytes.hex()
                if not future.done():
                    loop.call_soon_threadsafe(future.set_result, token_hex)
            except Exception as e:
                if not future.done():
                    loop.call_soon_threadsafe(future.set_exception, PushUnavailable(str(e)))

        def did_fail(s, application, error):
            desc = str(error.localizedDescription()) if error else 'Fallo al registrar APNs'
            if not future.done():
                loop.call_soon_threadsafe(future.set_exception, PushUnavailable(desc))

        def did_receive(s, application, user_info):
            try:
                self.deliver_user_info(user_info)
            except Exception:
                pass

        if delegate is not None:
            cls = delegate.__class__
            for sel_name, func in [
                (b'application:didRegisterForRemoteNotificationsWithDeviceToken:', did_register),
                (b'application:didFailToRegisterForRemoteNotificationsWithError:', did_fail),
                (b'application:didReceiveRemoteNotification:', did_receive),
            ]:
                try:
                    objc.classAddMethod(cls, sel_name, func)
                except Exception:
                    try:
                        setattr(cls, sel_name.decode('ascii'), func)
                    except Exception:
                        pass

        def register_call():
            try:
                try:
                    import UserNotifications
                    center = UserNotifications.UNUserNotificationCenter.currentNotificationCenter()
                    options = (UserNotifications.UNAuthorizationOptionBadge |
                               UserNotifications.UNAuthorizationOptionSound |
                               UserNotifications.UNAuthorizationOptionAlert)
                    def auth_cb(granted, error):
                        pass
                    center.requestAuthorizationWithOptions_completionHandler_(options, auth_cb)
                except BaseException:
                    pass
                app.registerForRemoteNotifications()
            except BaseException as e:
                if not future.done():
                    loop.call_soon_threadsafe(future.set_exception, PushUnavailable(str(e)))

        try:
            from Foundation import NSObject
            class CallbackHelper(NSObject):
                def runRegistration_(self, _):
                    register_call()
            helper = CallbackHelper.new()
            helper.performSelectorOnMainThread_withObject_waitUntilDone_('runRegistration:', None, False)
        except Exception:
            register_call()

        try:
            return await asyncio.wait_for(future, 15)
        except asyncio.TimeoutError:
            raise PushUnavailable('Tiempo de espera agotado al registrar APNs en macOS.')

    def deliver_user_info(self, user_info):
        if self._receive is None or self._loop is None:
            return
        if hasattr(user_info, 'items'):
            user_info = dict(user_info)
        if not isinstance(user_info, dict):
            return
        try:
            payload = json.dumps(user_info, separators=(',', ':'))
        except (TypeError, ValueError):
            return
        if len(payload) <= 65536:
            self._loop.call_soon_threadsafe(self._receive, payload)

    async def close(self):
        self._receive = None
        self._loop = None
        self._observer = None
