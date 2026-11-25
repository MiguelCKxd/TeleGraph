"""Interface texts of the mobile app, wired into the desktop i18n.

The desktop translates Spanish keys to English (``TRANSLATIONS``) and English
to every other language (``CATALOGUES``). Mobile texts use the same scheme:
each Spanish key points at an English text; when that English text already
exists in the desktop catalogues it is translated into all languages, and
otherwise English is shown (Spanish keeps the key itself).
"""
from functools import lru_cache
import unicodedata

MOBILE = {
    'Menú del chat': 'Chat menu',
    'Archivo de audio': 'Audio file',
    'Marcar como leído o no leído': 'Mark as read or unread',
    'Archivar o desarchivar': 'Archive or unarchive',
    'Fijar o desfijar': 'Pin or unpin',
    'Sin acción': 'No action',
    'Buscar en ajustes': 'Search settings',
    'SF Compact (si está instalada)': 'SF Compact (when installed)', 'Política de privacidad': 'Privacy policy', 'Eliminar mi cuenta de Telegram': 'Delete my Telegram account',
    'Continuar en Telegram para confirmar la eliminación definitiva': 'Continue to Telegram to confirm permanent deletion',
    'Denunciar mensaje': 'Report message', 'Denuncia enviada a Telegram.': 'Report sent to Telegram.',
    'Comentario': 'Comment', 'Búsquedas recientes': 'Recent searches',
    'Borrar búsquedas recientes': 'Clear recent searches',
    'Chats frecuentes': 'Frequent chats',
    'Restablecer nombre': 'Reset app name',
    'Editado el': 'Edited on',
    'Previsualizar las fotos': 'Preview photos',
    'Al deslizar un chat hacia la izquierda': 'Swipe a chat to the left',
    'Al deslizar un chat hacia la derecha': 'Swipe a chat to the right',
    'Nombres de chats para Siri': 'Chat names for Siri',
    'Siri podrá usar los nombres de los chats que selecciones en esta cuenta.': 'Siri can use the names of the chats you select in this account.',
    'Desmarcar todos': 'Deselect all',
    'Nombre visible de la app': 'App display name',
    'Color de burbujas recibidas': 'Incoming bubble color',
    'Color de burbujas enviadas': 'Outgoing bubble color',
    'Iniciar sesion': 'Sign in',
    'Entrar con codigo QR': 'Sign in with QR code',
    'Te hemos enviado el codigo a Telegram o por SMS.': 'The code was sent to your Telegram app or by SMS.',
    'Escanea este codigo desde Telegram en otro dispositivo: Ajustes > Dispositivos > Vincular dispositivo.':
        'Scan this code with Telegram on another device: Settings > Devices > Link Desktop Device.',
    'Volver': 'Back',
    'Archivados': 'Archived chats',
    'Cuentas': 'Accounts',
    'No hay chats.': 'No chats.',
    'Escribe un mensaje': 'Write a message…',
    'Enviar': 'Send',
    'Eliminar para todos': 'Delete for everyone',
    'Fijar': 'Pin',
    'Desfijar': 'Unpin',
    'Editando mensaje': 'Editing message',
    'Respondiendo a': 'Replying to',
    'Chat': 'Chat',
    'Entrante': 'Incoming',
    'Saliente': 'Outgoing',
    'Reenviar a...': 'Forward to…',
    'Pendiente de envio': 'Waiting to send',
    'Mensajes anteriores': 'Older messages',
    'Idioma': 'Language',
    'Tema': 'Theme',
    'Tamaño de letra': 'Font size',
    'Mostrar el texto solo en ASCII': 'Show text as ASCII only',
    'Mostrar segundos en la hora': 'Show seconds in timestamps',
    'Guardar una copia para usar sin conexion': 'Keep a copy to use offline',
    'Burbujas': 'Bubbles',
    'Unirse / salir': 'Join / leave',
    'Diseño del perfil': 'Profile design',
    'Secciones': 'Sections',
    'Botones': 'Buttons',
    'Densidad': 'Density',
    'Compacta': 'Compact',
    'Normal': 'Normal',
    'Amplia': 'Spacious',
    'Alineación': 'Alignment',
    'Al inicio': 'Start alignment',
    'Centrada': 'Centered',
    'Ancho de la tarjeta (px)': 'Card width (px)',
    'Tamaño del avatar (px)': 'Avatar size (px)',
    'Grosor del borde (px)': 'Border width (px)',
    'Avatar circular': 'Round avatar',
    'Fondo de cabecera': 'Header background',
    'Texto de cabecera': 'Header text',
    'Acento del avatar': 'Avatar accent',
    'Borde de cabecera': 'Header border',
    'Restaurar ficha predeterminada': 'Restore contact card defaults',
    'Borrar todos los datos': 'Delete all app data',
    'Caché': 'Cache',
    'Liberado: {size}': 'Freed: {size}',
    'Añadir cuenta': 'Add account',
    'Alias': 'Alias',
    'Usar': 'Use',
    'Acerca de': 'About',
    'Version': 'Version',
    '¿Cerrar la sesion de esta cuenta en este dispositivo?': 'Sign this account out on this device?',
    '¿Borrar todos los datos? Se cerraran todas las sesiones de este dispositivo.':
        'Delete all data? Every account on this device will be signed out.',
    'reenviado': 'Forwarded',
    'Error': 'Error',
    'Accion guardada; se enviara al volver la conexion.': '◷ Saved offline: it will be sent when the connection returns.',
    'Nombre visible solo en este dispositivo': 'Name shown only on this device',
    'Este chat es de solo lectura.': 'This chat is read-only.',
    'Reaccionar': 'React',
    'PIN o contraseña': 'App password',
    'Repetir': 'Confirm',
    'Contraseña incorrecta': 'Incorrect app password.',
}


def _norm(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.lower())
                   if not unicodedata.combining(c)).strip(' .:…')


_installed = False


@lru_cache(maxsize=1)
def web_keys():
    """Return explicit and directly referenced translation keys in app.js."""
    import re
    from pathlib import Path
    script = (Path(__file__).resolve().parent / 'web' / 'app.js').read_text('utf-8')
    for feature_script in ('stories.js', 'wallpapers.js', 'media_gallery.js', 'mobile_controls.js'):
        script += (Path(__file__).resolve().parent / 'web' / feature_script).read_text('utf-8')
    start = script.index('const KEYS = [')
    block = script[start:script.index('];', start)]
    explicit = re.findall(r"'([^']*)'", block)
    literals = re.findall(r"\bt\('((?:[^'\\]|\\.)*)'", script)
    return tuple(dict.fromkeys(explicit + [re.sub(r"\\(.)", r"\1", key) for key in literals]))


def install():
    """Register mobile keys (and reuse desktop translations by meaning)."""
    global _installed
    if _installed:
        return
    from tg_ascii import i18n
    from tg_ascii.translations import CATALOGUES
    from . import translations_mobile
    translations_mobile.install(CATALOGUES)
    for english, spanish in {
        'Use Telegram chat backgrounds when available': 'Usar los fondos de los chats de Telegram cuando estén disponibles',
        'Color / gradient': 'Color o degradado', 'All chats in this app': 'Todos los chats de esta app',
        'Preview and edit': 'Previsualizar y editar', 'No active stories.': 'No hay historias activas.',
        'Media unavailable.': 'El contenido ya no está disponible.', 'Intensity': 'Intensidad',
        'Restore default': 'Restaurar el fondo predeterminado', 'Audience': 'Audiencia',
        'Also in Telegram': 'También en Telegram', 'Apply to': 'Aplicar en',
        'Telegram keeps global solid and gradient backgrounds on this device.':
            'Telegram guarda los colores y degradados generales solo en este dispositivo.',
    }.items():
        CATALOGUES['es'].setdefault(english, spanish)
    # Desktop hint whose Spanish catalogue entry is missing (shown unaccented).
    CATALOGUES['es'].setdefault('Use + and your country calling code: +34 (Spain), +56 (Chile), +1 (US/Canada), etc.',
                                'Usa + y el prefijo de tu país: +34 (España), +56 (Chile), +1 (EE. UU./Canadá), etc.')
    index = {}
    for english, spanish in CATALOGUES.get('es', {}).items():
        index.setdefault(_norm(spanish), english)
    for spanish, english in i18n.TRANSLATIONS.items():
        index.setdefault(_norm(spanish), english)
    for key in web_keys():
        if key in i18n.TRANSLATIONS:
            continue
        english = MOBILE.get(key) or index.get(_norm(key))
        if english:
            i18n.TRANSLATIONS[key] = english
            i18n._SPANISH_FALLBACK.setdefault(english, key)
    _installed = True
