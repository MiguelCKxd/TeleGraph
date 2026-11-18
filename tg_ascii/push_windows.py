"""Optional legacy WNS transport, available only with Windows package identity.

This uses the platform channel API, never a fabricated token. Registering a
channel does not prove Telegram's sender is provisioned for this package.
Background activation requires an additional packaged native component; the
portable Python executable cannot receive raw push after it has terminated.
"""
import asyncio
import ctypes
from dataclasses import dataclass
import sys
from urllib.parse import urlsplit


class PushUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class PushCapability:
    available: bool
    reason: str
    background_activation: bool = False


def capability():
    if sys.platform != 'win32':
        return PushCapability(False, 'El transporte WNS experimental está disponible sólo en Windows.')
    try:
        # APPMODEL_ERROR_NO_PACKAGE (15700) is expected for a portable EXE.
        size = ctypes.c_uint32()
        probe = ctypes.windll.kernel32.GetCurrentPackageFullName
        probe.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_wchar_p]
        probe.restype = ctypes.c_long
        result = probe(ctypes.byref(size), None)
        if result != 122 or not size.value:
            return PushCapability(False, 'WNS necesita una distribución de Windows con identidad de paquete; esta distribución es portable.')
        from importlib.util import find_spec
        if find_spec('winrt.windows.networking.pushnotifications') is None:
            return PushCapability(False, 'Falta el componente opcional WinRT de notificaciones push.')
    except (AttributeError, ImportError, ModuleNotFoundError, OSError):
        return PushCapability(False, 'El servicio WNS no está disponible en esta instalación.')
    return PushCapability(True, 'Canal WNS disponible para pruebas. El emisor de Telegram y la activación con el proceso cerrado requieren validación.')


def valid_channel_uri(uri):
    if not isinstance(uri, str) or len(uri) > 8192:
        return False
    try:
        parsed = urlsplit(uri)
        host = (parsed.hostname or '').lower()
        return (parsed.scheme == 'https' and not parsed.username and not parsed.password
                and parsed.port in (None, 443) and not parsed.fragment
                and (host == 'notify.windows.com' or host.endswith('.notify.windows.com')))
    except ValueError:
        return False


class WindowsPushChannel:
    def __init__(self):
        self.channel = None
        self.event_token = None

    async def open(self, receive):
        status = capability()
        if not status.available:
            raise PushUnavailable(status.reason)
        from winrt.windows.networking.pushnotifications import PushNotificationChannelManager, PushNotificationType
        channel = await asyncio.wait_for(
            PushNotificationChannelManager.create_push_notification_channel_for_application_async(), 30)
        if not valid_channel_uri(channel.uri):
            channel.close()
            raise PushUnavailable('Windows no ha proporcionado un canal WNS válido.')
        self.channel = channel
        loop = asyncio.get_running_loop()

        def arrived(_, event):
            # Suppress OS presentation while this app can apply its own account,
            # mute, read and lock policy. Payload text is never displayed here.
            try:
                event.cancel = True
                payload = event.raw_notification.content if event.notification_type == PushNotificationType.RAW else ''
                if isinstance(payload, str) and len(payload) <= 65536:
                    loop.call_soon_threadsafe(receive, payload)
            except (AttributeError, RuntimeError, OSError):
                return

        self.event_token = channel.add_push_notification_received(arrived)
        return channel.uri

    async def close(self):
        channel, token = self.channel, self.event_token
        self.channel = self.event_token = None
        if channel is None:
            return
        if token is not None:
            channel.remove_push_notification_received(token)
        # No closed-process receiver is shipped: close this experimental
        # channel rather than letting Windows present uncontrolled toasts.
        channel.close()
