"""Local Telegram configuration and user-facing errors."""
import json
import os
from pathlib import Path
import re
import tempfile

from telethon import errors
from .i18n import tr


try:
    from ._user_api import ENABLED as USER_API
except ModuleNotFoundError as exc:
    if exc.name != 'tg_ascii._user_api':
        raise
    USER_API = False


class SetupError(Exception):
    pass


def validate_credentials(api_id, api_hash):
    try:
        number = int(api_id)
    except (TypeError, ValueError):
        raise ValueError(tr('El API ID debe ser un numero entero positivo.')) from None
    if number <= 0:
        raise ValueError(tr('El API ID debe ser un numero entero positivo.'))
    secret = str(api_hash).strip()
    if not re.fullmatch(r'[0-9a-fA-F]{32}', secret):
        raise ValueError(tr('El API hash debe tener 32 caracteres hexadecimales. Copialo completo.'))
    return number, secret


def normalize_phone(value):
    phone = re.sub(r'[\s()\-]', '', value)
    if phone.startswith('00'):
        phone = '+' + phone[2:]
    if not re.fullmatch(r'\+[1-9][0-9]{6,14}', phone):
        raise ValueError(tr('Usa + y el prefijo de tu pais: +34 (Espana), +56 (Chile), +1 (EE.UU./Canada), etc.'))
    return phone


def load_credentials(root):
    path = root / 'config.json'
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return validate_credentials(data['api_id'], data['api_hash'])
    except (OSError, ValueError, TypeError, KeyError):
        raise SetupError('No se pudo leer config.json. Usa --configure para introducir los datos de nuevo.') from None


def save_credentials(root, credentials):
    """Explicit opt-in only. Atomic, private file; no phone, OTP or 2FA."""
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix='config-', suffix='.tmp', dir=root)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({'api_id': credentials[0], 'api_hash': credentials[1]}, stream)
            stream.write('\n')
        os.replace(name, root / 'config.json')
    finally:
        Path(name).unlink(missing_ok=True)


def bundled_credentials():
    """App identity supplied by the publisher at build time, never a user session."""
    if USER_API:
        return None
    try:
        from ._app_credentials import API_ID, API_HASH
    except ModuleNotFoundError as exc:
        if exc.name == 'tg_ascii._app_credentials':
            return None
        raise
    try:
        return validate_credentials(API_ID, API_HASH)
    except ValueError:
        raise SetupError(tr('La configuracion incluida en la app no es valida. Contacta con el desarrollador.')) from None


def error_message(exc):
    if isinstance(exc, (SetupError, ValueError)):
        return str(exc)
    if isinstance(exc, errors.FloodWaitError):
        return tr('Telegram pide esperar {seconds} segundos antes de reintentar.').format(seconds=exc.seconds)
    if isinstance(exc, errors.ApiIdInvalidError):
        return tr('API ID o hash incorrectos. Revisa las claves de la app.')
    if isinstance(exc, (errors.SessionRevokedError, errors.AuthKeyUnregisteredError)):
        return tr('La sesion ha caducado o ha sido revocada. Reinicia para entrar de nuevo.')
    if isinstance(exc, errors.AuthKeyDuplicatedError):
        return tr('Telegram ha invalidado esta sesion. Revisa Ajustes > Dispositivos en Telegram.')
    if isinstance(exc, (errors.ChatWriteForbiddenError, errors.UserBannedInChannelError)):
        return tr('No tienes permiso para escribir en este chat.')
    if isinstance(exc, errors.MessageTooLongError):
        return tr('El mensaje supera el limite de Telegram.')
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return tr('Fallo de conexion o acceso local. Comprueba la red y los permisos.')
    return tr('No se pudo completar la operacion ({error}).').format(error=type(exc).__name__)
