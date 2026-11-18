"""Offline interface translations. English is the default language."""
import os

_language = 'en'
# 1.5.4: Latin American Spanish right after Spanish (see spanish_latam.py).
LANGUAGES = {'en': 'English', 'es': 'Español', 'es-419': 'Español (Latinoamérica)', 'ru': 'Русский', 'pl': 'Polski', 'ca': 'Català', 'ca-valencia': 'Valencià', 'uk': 'Українська'}

from .translations_extra import EXTRA_LANGUAGES
LANGUAGES.update(EXTRA_LANGUAGES)
from .translations_extended import NEW_LANGUAGES, RTL_LANGUAGES
LANGUAGES.update(NEW_LANGUAGES)

def is_rtl(language=None):
    return (language or _language) in RTL_LANGUAGES

TRANSLATIONS = {
    'El API ID debe ser un numero entero positivo.': 'The API ID must be a positive integer.',
    'El API hash debe tener 32 caracteres hexadecimales. Copialo completo.': 'The API hash must contain 32 hexadecimal characters. Copy it in full.', 
    'Doble clic para abrir una historia.': 'Double-click to open a story.',
    'Historia abierta.': 'Story opened.',
    'Telegram pide esperar {seconds} segundos antes de reintentar.': 'Telegram asks you to wait {seconds} seconds before retrying.',
    'API ID o hash incorrectos. Revisa las claves de la app.': 'Incorrect API ID or hash. Check the app credentials.',
    'No se pudo completar la operacion ({error}).': 'Could not complete the operation ({error}).',
    '+ Cuenta': '+ Account',
    'Cuenta': 'Account',
    'Cuenta desconocida': 'Unknown account',
    'Nueva cuenta': 'New account',
    'Inicia sesion de nuevo': 'Sign in again',
    'Sin conexion': 'Offline',
    'Esta cuenta ya esta añadida. Vuelve y seleccionala.': 'This account is already added. Go back and select it.',
    'Volver a otra cuenta': 'Back to another account',
    'Sesion guardada automaticamente': 'Session saved automatically',
    'Las cuentas permanecen conectadas al alternar. Cerrar la app conserva las sesiones.': 'Accounts stay connected when switching. Closing the app keeps your sessions.',
    'Chats': 'Chats',
    'Historias': 'Stories',
    'Ajustes': 'Settings',
    'Apariencia': 'Appearance',
    'Tamaño del texto': 'Text size',
    'Mostrar texto en ASCII (oculta emojis)': 'Display text as ASCII (hides emoji)',
    'Enter envia mensajes': 'Enter sends messages',
    'Lista de chats compacta': 'Compact chat list',
    'Guardar ajustes': 'Save settings',
    'Ajustes guardados.': 'Settings saved.',
    'Mi perfil': 'My profile',
    'Editar perfil de Telegram': 'Edit Telegram profile',
    'Nombre': 'First name',
    'Apellidos': 'Last name',
    'Biografia': 'Bio',
    'Nombre de usuario': 'Username',
    'Guardar nombre y biografia': 'Save name and bio',
    'Cambiar nombre de usuario': 'Change username',
    'Cambiar foto': 'Change photo',
    'Perfil actualizado.': 'Profile updated.',
    'El nombre es obligatorio.': 'A first name is required.',
    'El usuario debe tener de 5 a 32 letras, numeros o guiones bajos.': 'The username must contain 5–32 letters, numbers or underscores.',
    'Elige una imagen PNG o JPEG.': 'Choose a PNG or JPEG image.',
    'Imagenes': 'Images',
    'Contactos': 'Contacts',
    'Añadir contacto': 'Add contact',
    'Telefono internacional': 'Phone with country code',
    'Guardar contacto': 'Save contact',
    'Contacto guardado.': 'Contact saved.',
    'Telegram pide reintentar mas tarde.': 'Telegram asks you to try again later.',
    'No se encontro una cuenta accesible con ese numero.': 'No accessible account was found for that number.',
    'Nuevo chat': 'New chat',
    'Abrir chat': 'Open chat',
    'Usuario (@nombre) o telefono (+prefijo):': 'Username (@name) or phone (+country code):',
    'Introduce un @usuario o telefono internacional.': 'Enter a @username or phone with country code.',
    'Nuevo grupo': 'New group',
    'Nuevo grupo con seleccionados': 'New group with selected contacts',
    'Nombre del grupo:': 'Group name:',
    'Selecciona participantes en la lista.': 'Select participants from the list.',
    'Escribe un titulo y selecciona participantes.': 'Enter a title and select participants.',
    'Creando grupo...': 'Creating group...',
    'Grupo creado; algunos usuarios no pudieron ser invitados.': 'Group created; some users could not be invited.',
    'Telegram no devolvio el grupo. Actualiza antes de reintentar.': 'Telegram did not return the group. Refresh before retrying.',
    'Informacion': 'Information',
    'Fijar / Desfijar': 'Pin / Unpin',
    'Carpetas': 'Folders',
    'Todos los chats': 'All chats',
    'Nueva carpeta': 'New folder',
    'Nueva carpeta con este chat': 'New folder with this chat',
    'Nombre de carpeta (max. 12):': 'Folder name (max. 12):',
    'El nombre de carpeta debe tener entre 1 y 12 caracteres.': 'The folder name must contain 1–12 characters.',
    'No hay identificadores de carpeta disponibles.': 'No folder identifiers are available.',
    'Selecciona al menos un chat.': 'Select at least one chat.',
    'Renombrar': 'Rename',
    'Añadir chat actual': 'Add current chat',
    'Quitar chat actual': 'Remove current chat',
    'Eliminar carpeta': 'Delete folder',
    'Eliminar esta carpeta de Telegram? Los chats se conservan.': 'Delete this Telegram folder? Chats will be kept.',
    'Esta carpeta no se puede eliminar.': 'This folder cannot be deleted.',
    'Arrastra un archivo al chat para adjuntarlo.': 'Drop a file onto the chat to attach it.',
    'Arrastrar no esta disponible en este equipo; usa Adjuntar.': 'Drag and drop is unavailable on this computer; use Attach.',
    'Primero elige un chat y espera a que termine la operacion.': 'Choose a chat first and wait for the current operation to finish.',
    'Arrastra un solo archivo por envio.': 'Drop one file per message.',
    'Emojis': 'Emoji',
    '[Ver / guardar archivo]': '[View / save file]',
    'Visor de archivos': 'File viewer',
    'Ver imagen / vista previa': 'View image / preview',
    'Guardar archivo como...': 'Save file as...',
    'Archivo guardado.': 'File saved.',
    'Descargando...': 'Downloading...',
    'El archivo ya no esta disponible.': 'This file is no longer available.',
    'No hay vista previa disponible. Puedes guardar el archivo.': 'No preview is available. You can save the file.',
    'Archivo demasiado grande para la vista previa. Guardalo primero.': 'This file is too large to preview. Save it first.',
    'Imagen demasiado grande para la vista previa.': 'This image is too large to preview.',
    'Vista previa estatica del sticker o video.': 'Static preview of the sticker or video.',
    'Actualizar historias': 'Refresh stories',
    'Historia': 'Story',
    'Doble clic para abrir. Las historias no se marcan como vistas.': 'Double-click to open. Stories are not marked as viewed.',
    'Llamadas': 'Calls',
    'Las llamadas de voz y video dentro de TG-ASCII aun no estan implementadas. Puedes abrir este contacto en Telegram y llamar alli. Comprueba la cuenta activa en Telegram.': 'Voice and video calls inside TG-ASCII are not implemented yet. You can open this contact in Telegram and call there. Check the active account in Telegram.',
    'Abrir Telegram': 'Open Telegram',
    'Abrir el contacto en Telegram?': 'Open this contact in Telegram?',
    'Cargando...': 'Loading...',
    'Guardando...': 'Saving...',
    'Demo local': 'Local demo',
    'Mensajes guardados': 'Saved Messages',
    'Ideas de diseno': 'Design ideas',
    'Tu Telegram. A tu gusto.': 'Your Telegram. Your way.',
    'Configurar aplicacion (desarrollador)': 'Configure application (developer)',
    'Tu numero de telefono': 'Your phone number',
    'Codigo de Telegram': 'Telegram code',
    'Contrasena de verificacion en dos pasos': 'Two-step verification password',
    'Recordar claves de app en este equipo (sin cifrar)': 'Remember app keys on this computer (unencrypted)',
    'Incluye + y el prefijo de tu pais. Ejemplo: +34 612 345 678': 'Include + and your country calling code. Example: +1 202 555 0123',
    'Introduce el codigo que te ha enviado Telegram.': 'Enter the code sent to you by Telegram.',
    'Introduce el codigo de Telegram.': 'Enter your Telegram code.',
    'Continuar': 'Continue',
    'Cambiar numero': 'Change number',
    'Inicia sesion con tu propia cuenta.': 'Sign in with your own account.',
    'El codigo ha caducado. Solicita uno nuevo.': 'The code has expired. Request a new one.',
    'Reintentar': 'Retry',
    'CONVERSACIONES': 'CONVERSATIONS',
    'Buscar chats': 'Search chats',
    'Actualizar': 'Refresh',
    'Elige un chat': 'Choose a chat',
    'Quitar archivo': 'Remove file',
    '[+] Adjuntar': '[+] Attach',
    'Enviar >': 'Send >',
    'Enter: enviar  /  Shift+Enter: nueva linea': 'Enter: send  /  Shift+Enter: new line',
    'Haz clic en un chat para abrirlo.': 'Click a chat to open it.',
    'Chat abierto. Escribe o adjunta un archivo.': 'Chat open. Type a message or attach a file.',
    'Cargando mensajes...': 'Loading messages...',
    'Primero elige un chat.': 'Choose a chat first.',
    'Elegir archivo': 'Choose file',
    'Archivo preparado. Pulsa Enviar para enviarlo al chat indicado.': 'File ready. Click Send to send it to the chat shown above.',
    '[Archivo] ': '[File] ',
    'Archivo adjunto': 'Attachment',
    'Subiendo archivo: ': 'Uploading file: ',
    'Texto demasiado largo. Limite: ': 'Text too long. Limit: ',
    'Elige un archivo normal, no una carpeta.': 'Choose a regular file, not a folder.',
    'Hay una operacion en curso. Cerrar la app?': 'An operation is in progress. Close the app?',
    'Cerrando...': 'Closing...',
    'Cargando chats...': 'Loading chats...',
    'Ningun chat abierto': 'No chat open',
    ' Sin chats. F5: actualizar': ' No chats. F5: refresh',
    'No hay mensajes en este chat.': 'No messages in this chat.',
    'Flechas: elegir chat. Enter: abrir. Tab: escribir comandos.': 'Arrows: choose chat. Enter: open. Tab: type commands.',
    'Elige un chat de la lista.': 'Choose a chat from the list.',
    'Chat abierto. Enter envia al chat indicado arriba. Esc: lista.': 'Chat open. Enter sends to the chat named above. Esc: chat list.',
    'Hay una operacion en curso. Espera un momento.': 'An operation is in progress. Please wait.',
    'Usa /open seguido del numero del chat.': 'Use /open followed by the chat number.',
    '/open N | /chats | /quit | //texto para enviar /texto | Tab: panel': '/open N | /chats | /quit | //text to send /text | Tab: switch panel',
    'Comando desconocido. /help para ayuda; // para enviar una barra inicial.': 'Unknown command. /help for help; // to send a leading slash.',
    'Primero elige un chat con las flechas y Enter.': 'First choose a chat with the arrow keys and Enter.',
    'Mensaje demasiado largo para Telegram (4096 unidades UTF-16).': 'Message too long for Telegram (4096 UTF-16 units).',
    'Enviando...': 'Sending...',
    'Enviado.': 'Sent.',
    ' Borrador conservado; revisa el chat antes de reintentar.': ' Draft kept; check the chat before retrying.',
    'Elige un chat con las flechas y pulsa Enter.\n\nTab: cambiar de panel\nEsc: volver a los chats\nF5: actualizar lista\nPgUp/PgDn: historial\nCtrl-Q: salir': 'Choose a chat with the arrow keys and press Enter.\n\nTab: switch panel\nEsc: back to chats\nF5: refresh list\nPgUp/PgDn: history\nCtrl-Q: exit',
    ' Tab: panel | Esc: chats | Enter: abrir/enviar | F5: actualizar | Ctrl-Q: salir': ' Tab: panel | Esc: chats | Enter: open/send | F5: refresh | Ctrl-Q: exit',
    'DEMO LOCAL': 'LOCAL DEMO',
    'Cargando ': 'Loading ',
    'Tu': 'You',
    '[Adjunto / mensaje de servicio]': '[Attachment / service message]',
    'Conectando a Telegram...': 'Connecting to Telegram...',
    'Configuracion guardada en este equipo.': 'Configuration saved on this computer.',
    'No se pudo guardar la configuracion; puedes continuar esta sesion.': 'Configuration could not be saved; you can continue this session.',
    '\nTG-ASCII cerrado.': '\nTG-ASCII closed.',
    'Pulsa Enter para cerrar...': 'Press Enter to close...',
    'Telefono con prefijo internacional (+34..., +56..., +1...): ': 'Phone with country calling code (+34..., +56..., +1...): ',
    'Usa + y el prefijo de tu pais: +34 (Espana), +56 (Chile), +1 (EE.UU./Canada), etc.': 'Use + and your country calling code: +34 (Spain), +56 (Chile), +1 (US/Canada), etc.',
    'Telegram no reconoce ese numero. Revisa el numero y su prefijo.': 'Telegram does not recognize this number. Check the number and country code.',
    'No se pudo validar el telefono tras tres intentos.': 'Could not validate the phone number after three attempts.',
    'Introduce el codigo enviado por Telegram. No aparecera al escribir.': 'Enter the code sent by Telegram. It will not be visible while typing.',
    'Codigo de Telegram: ': 'Telegram code: ',
    'Codigo incorrecto. Prueba de nuevo.': 'Incorrect code. Try again.',
    'El codigo ha caducado. Reinicia para solicitar uno nuevo.': 'The code has expired. Restart to request a new one.',
    'Contrasena 2FA (invisible): ': 'Two-step verification password (hidden): ',
    'Contrasena incorrecta. Prueba de nuevo.': 'Incorrect password. Try again.',
    'No se pudo verificar la contrasena tras tres intentos.': 'Could not verify the password after three attempts.',
    'No se pudo verificar el codigo tras tres intentos.': 'Could not verify the code after three attempts.',
    'No tienes permiso para escribir en este chat.': 'You cannot write to this chat.',
    'El mensaje supera el limite de Telegram.': 'The message exceeds the Telegram limit.',
    'Fallo de conexion o acceso local. Comprueba la red y los permisos.': 'Connection or local access failed. Check your network and permissions.',
    'La sesion ha caducado o ha sido revocada. Reinicia para entrar de nuevo.': 'The session has expired or was revoked. Restart to sign in again.',
    'Telegram ha invalidado esta sesion. Revisa Ajustes > Dispositivos en Telegram.': 'Telegram invalidated this session. Check Settings > Devices in Telegram.',
    'Esta compilacion no contiene la configuracion de TG-ASCII. Pide una version completa al desarrollador.': 'This build is missing the TG-ASCII app configuration. Ask the developer for a complete release.',
    'La configuracion incluida en la app no es valida. Contacta con el desarrollador.': 'The bundled app configuration is invalid. Contact the developer.',
}


from .translations_profiles import KEYS as PROFILE_KEYS
from .translations_customization import KEYS as CUSTOMIZATION_KEYS
from .translations_visual import KEYS as VISUAL_KEYS
from .translations_editing import KEYS as EDITING_KEYS
from .translations_search import KEYS as SEARCH_KEYS
from .translations_effects import KEYS as EFFECT_KEYS
for key in SEARCH_KEYS+PROFILE_KEYS+CUSTOMIZATION_KEYS+VISUAL_KEYS+EDITING_KEYS+EFFECT_KEYS:TRANSLATIONS.setdefault(key,key)

from .translations_v11 import ALIASES as V11_ALIASES, KEYS as V11_KEYS
TRANSLATIONS.update(V11_ALIASES)
for key in V11_KEYS:
    TRANSLATIONS.setdefault(key, key)

from .translations_v12 import ALIASES as V12_ALIASES, KEYS as V12_KEYS
TRANSLATIONS.update(V12_ALIASES)
for key in V12_KEYS:
    TRANSLATIONS.setdefault(key, key)

from .translations_v13 import ALIASES as V13_ALIASES, KEYS as V13_KEYS
TRANSLATIONS.update(V13_ALIASES)
for key in V13_KEYS:
    TRANSLATIONS.setdefault(key, key)

from .translations_v30 import ALIASES as V30_ALIASES, KEYS as V30_KEYS
TRANSLATIONS.update(V30_ALIASES)
for key in V30_KEYS:
    TRANSLATIONS.setdefault(key, key)

# Preserve the first spelling when several legacy Spanish keys share a label.
_SPANISH_FALLBACK = {}
for _source, _english in TRANSLATIONS.items():
    _SPANISH_FALLBACK.setdefault(_english, _source)


def set_language(value):
    global _language
    if value not in LANGUAGES:
        raise ValueError('Unsupported language')
    _language = value


def get_language():
    return _language


def detect_language():
    configured = os.environ.get('TG_ASCII_LANGUAGE', '')
    return configured if configured in LANGUAGES else 'en'


_BRAND = None


def brand(text):
    """3.0: the app's public name is TeleGraph (logo Tg-Gr) in every language.
    Older labels keep their keys; folder paths (…/TG-ASCII) stay as they are."""
    global _BRAND
    if not isinstance(text, str) or ('TG-ASCII' not in text and 'Tg-As' not in text):
        return text
    if _BRAND is None:
        import re
        _BRAND = (re.compile(r'(?<![/\\\w])TG-ASCII(?![/\\\w])'), re.compile(r'(?<![/\\\w])Tg-As(?![\w-])'))
    return _BRAND[1].sub('Tg-Gr', _BRAND[0].sub('TeleGraph', text))


def tr(value):
    from .translations import CATALOGUES
    english = TRANSLATIONS.get(value, value)
    if _language == 'en': return brand(english)
    if _language == 'es':
        return brand(CATALOGUES.get('es', {}).get(english, _SPANISH_FALLBACK.get(english, value)))
    if _language == 'es-419':
        from .spanish_latam import latam
        return brand(latam(CATALOGUES.get('es', {}).get(english, _SPANISH_FALLBACK.get(english, value))))
    return brand(CATALOGUES.get(_language, {}).get(english, english))
