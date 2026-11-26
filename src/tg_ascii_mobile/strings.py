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
    'Comprobar notificaciones': 'Check notifications',
    'Permiso de notificaciones concedido por el sistema.': 'Notification permission granted by the system.',
    'Permiso del sistema: sin comprobar.': 'System permission: not checked.',
    'Actualizar': 'Refresh',
    'Esta comprobación consulta el registro. No envía una notificación de prueba.':
        'This check reads the registration status. It does not send a test notification.',
    'Las notificaciones están desactivadas en esta app.': 'Notifications are turned off in this app.',
    'Permiso denegado. Activa las notificaciones en Ajustes del sistema.':
        'Permission denied. Enable notifications in system Settings.',
    'Todavía no se ha concedido permiso para las notificaciones.': 'Notification permission has not been granted yet.',
    'Telegram ha aceptado el registro de {count} cuenta(s).': 'Telegram has accepted registration for {count} account(s).',
    'El registro no se ha completado. La app volverá a intentarlo automáticamente.':
        'Registration is incomplete. The app will retry automatically.',
    'Conecta una cuenta para comprobar el registro de notificaciones.':
        'Connect an account to check notification registration.',
    'El sistema no ha podido activar las notificaciones.': 'The system could not enable notifications.',
    'Esperando a que se complete el registro de notificaciones.': 'Waiting for notification registration to complete.',
    'Entorno de Apple: desarrollo.': 'Apple environment: development.',
    'Entorno de Apple: distribución.': 'Apple environment: distribution.',
    'Si no aparecen avisos, revisa el permiso de notificaciones y los modos de concentración en Ajustes del sistema.':
        'If alerts do not appear, check notification permission and Focus modes in system Settings.',
    'No se pudo consultar el estado. Vuelve a intentarlo.': 'Could not check the status. Try again.',
    'Restablecer': 'Reset',
    'Liquid Glass nativo': 'Native Liquid Glass',
    'Usar controles de cristal nativos de Apple en iOS 26 o posterior. Respeta Reducir transparencia y Reducir movimiento. Desactivado por defecto.':
        'Use native Apple glass controls on iOS 26 or later. Respects Reduce Transparency and Reduce Motion. Off by default.',
    'Conéctate para ir al mensaje.': 'Connect to go to the message.',
    'Abrir en el reproductor del sistema': 'Open in system player',
    'Se muestra una vista previa. Reintenta para cargar la calidad seleccionada.':
        'Showing a preview. Retry to load the selected quality.',
    'Tipo de contenido': 'Media type', 'Calidad de las fotos': 'Photo quality',
    'Restablecer ajustes de apariencia': 'Reset appearance settings',
    'Restablecer ajustes de personalización': 'Reset customization settings',
    'Restablecer todos los ajustes': 'Reset all settings',
    'Se restablecerán todos los ajustes de esta app en este dispositivo. Tus cuentas, sesiones, mensajes y bloqueo de seguridad se conservarán. Los ajustes guardados en Telegram no cambiarán.':
        'All settings of this app will be reset on this device. Your accounts, sessions, messages and security lock will be kept. Settings stored in Telegram will not change.',
    'Se restablecerán los ajustes de esta sección en este dispositivo. Tus cuentas, sesiones, mensajes y bloqueo de seguridad se conservarán. Los ajustes guardados en Telegram no cambiarán.':
        'The settings in this section will be reset on this device. Your accounts, sessions, messages and security lock will be kept. Settings stored in Telegram will not change.',
    'Color de controles': 'Control color', 'Decoración de títulos y menús': 'Title and menu decoration',
    'Título de la lista de chats': 'Chat list title', 'Acción de cabecera': 'Header action',
    'Composición de la interfaz': 'Interface layout', 'Estilo de controles': 'Control style',
    'Entre corchetes': 'Bracketed', 'Sin corchetes': 'Plain', 'Iconos': 'Icons',
    'Navegación': 'Navigation', 'Menú': 'Menu', 'Pestañas inferiores': 'Bottom tabs',
    'Navegación principal': 'Main navigation', 'Alineación de cabecera': 'Header alignment',
    'Izquierda': 'Left', 'Centrada': 'Centered', 'Separadores de chats': 'Chat separators',
    'Discontinuos': 'Dashed', 'Continuos': 'Solid', 'Ninguno': 'None',
    'Color de títulos': 'Title color', 'Color secundario': 'Secondary color',
    'Color de paneles': 'Panel color', 'Color de separadores': 'Separator color',
    'Color de contadores': 'Counter color', 'Altura mínima de chats (px)': 'Minimum chat height (px)',
    'Tamaño de fotos en la lista (px)': 'List photo size (px)', 'Margen de separadores (px)': 'Separator inset (px)',
    'Grosor de títulos': 'Title weight', 'Ancho máximo de burbujas (%)': 'Maximum bubble width (%)',
    'Mostrar estado en línea de la conexión': 'Show online connection status',
    'Nombres de remitentes en chats privados': 'Sender names in private chats',
    'Bordes de burbujas': 'Bubble borders', 'Restablecer composición': 'Reset interface layout',
    'Cero mantiene el tamaño habitual. Estas opciones solo cambian el aspecto en este dispositivo.':
        'Zero keeps the usual size. These options only change the appearance on this device.',
    'Compartir con Apple TV': 'Share with Apple TV',
    'Abrir tema': 'Open topic',
    'Activar temas': 'Enable topics',
    'Buscar temas': 'Search topics',
    'Cambiar nombre': 'Rename',
    'Cargar más': 'Load more',
    'Crear tema': 'New topic',
    'Debate vinculado': 'Linked discussion',
    'Desactivar temas': 'Disable topics',
    'Elegir tema': 'Choose a topic',
    'Eliminar tema': 'Delete topic',
    'Eliminar tema y todos sus mensajes': 'Delete this topic and all its messages?',
    'No puedes enviar mensajes a este tema': 'You cannot write in this topic.',
    'Nombre del tema': 'Topic name',
    'Oculto': 'Hidden',
    'Organizar el grupo por temas': 'Organize the group into topics',
    'Organizar este grupo por temas. Un grupo básico se convertirá en supergrupo.': 'Organize this group into topics. A basic group will be upgraded to a supergroup.',
    'Tema cerrado': 'This topic is closed.',
    'Todos los temas': 'All topics',
    'Volver a mostrar todos los mensajes juntos': 'Show all messages together again',
    'Reabrir tema': 'Reopen topic',
    'Cerrar tema': 'Close topic',
    'Mostrar tema': 'Show General',
    'Ocultar tema': 'Hide General',
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
    for feature_script in ('stories.js', 'wallpapers.js', 'media_gallery.js', 'mobile_controls.js', 'forums.js', 'presentation.js'):
        script += (Path(__file__).resolve().parent / 'web' / feature_script).read_text('utf-8')
    start = script.index('const KEYS = [')
    block = script[start:script.index('];', start)]
    explicit = re.findall(r"'([^']*)'", block)
    literals = re.findall(r"\bt\('((?:[^'\\]|\\.)*)'", script)
    return tuple(dict.fromkeys(explicit + list(MOBILE) + [re.sub(r"\\(.)", r"\1", key) for key in literals]))


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
