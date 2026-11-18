"""Playful Spanish interface variants, never applied to user-generated text.

These are readable comic voices, not a claim that a region has one accent.
Generate the bundled catalogues at build time; no rewriting occurs while typing.
"""
import re

LANGUAGES = {'es-x-chileno': 'Chileno', 'es-x-andaluz': 'Andaluz'}

_CHILEAN = {
    'Settings': 'Ajustes, po', 'Appearance': 'La pinta', 'Text size': 'Porte de la letra',
    'Chats': 'Chats', 'Stories': 'Historias', 'My profile': 'Mi perfil, po',
    'Save settings': 'Guardar los ajustes', 'Settings saved.': 'Ya, quedaron guardaos los ajustes.',
    'New chat': 'Armar un chat', 'New group': 'Armar un grupo', 'New folder': 'Armar una carpeta',
    'Search chats': 'Buscar chats, po', 'Choose a chat': 'Elige un chat, po',
    'Click a chat to open it.': 'Haz clic en un chat pa abrirlo, po.',
    'Your Telegram. Your way.': 'Tu Telegram. A tu pinta.',
    'Loading...': 'Cargando, al tiro...', 'Saving...': 'Guardando, al tiro...',
    'Sending...': 'Mandando...', 'Sent.': 'Ya, salió el mensaje.',
    'Continue': 'Dale', 'Cancel': 'Ya no', 'Close': 'Cerrar', 'Retry': 'Probar de nuevo, po',
    'Refresh': 'Reconectar, al tiro', 'Send >': 'Mandar >', '[+] Attach': '[+] Adjuntar',
    'Choose file': 'Elige el archivo, po', 'File saved.': 'Listo, archivo guardao.',
    'No messages in this chat.': 'Todavía no hay mensajes por acá, po.',
    'Connecting to Telegram...': 'Conectando con Telegram, al tiro...',
    'Your phone number': 'El número de tu celu', 'Your phone number:': 'El número de tu celu:',
    'Unknown account': 'No cacho esta cuenta', 'New account': 'Otra cuenta, po',
    'Offline': 'Sin conexión, po', 'Information': 'La info', 'Back': 'Pa atrás',
    'More': 'Más cositas', 'Default': 'Como venía', 'Restore defaults': 'Dejarlo como venía',
    'Reset to defaults': 'Dejarlo como venía', 'Apply': 'Dale, aplicar',
    'Complex features': 'Funciones más cuáticas', 'Help': 'Una ayudita',
    'Calls and video': 'Llamás y video', 'Incoming call': 'Te tan llamando, po',
    'Calling…': 'Llamando…', 'Ringing…': 'Sonando…', 'Connected': 'Ya, conectao',
    'Call ended': 'Terminó la llamá', 'Call failed': 'No resultó la llamá',
    'Answer': 'Contestar', 'Answer with video': 'Contestar con video',
    'Hang up': 'Cortar', 'Decline': 'Ahora no, po',
    'Mute microphone': 'Dejar el micro callao', 'Unmute microphone': 'Prender el micro',
    'Start camera': 'Prender la cámara', 'Stop camera': 'Apagar la cámara',
    'Delete': 'Borrar', 'Saved Messages': 'Mensajes guardaos', 'You': 'Tú',
}
_ANDALUSIAN = {
    'Settings': 'Ajujteh', 'Appearance': 'La pinta', 'Text size': 'Tamaño de la letra',
    'Chats': 'Chah', 'Stories': 'Hijtoriah', 'My profile': 'Mi perfí',
    'Save settings': 'Guardá loh ajujteh', 'Settings saved.': 'Ea, ajujteh guardaoh.',
    'New chat': 'Abrí un chah', 'New group': 'Montá un grupo', 'New folder': 'Otra carpeta',
    'Search chats': 'Buscá chah', 'Choose a chat': 'Elige un chah, miarma',
    'Click a chat to open it.': 'Dale a un chah pa abrirlo, miarma.',
    'Your Telegram. Your way.': 'Tu Telegram. A tu gusto.',
    'Loading...': 'Cargando, miarma...', 'Saving...': 'Guardando...',
    'Sending...': 'Mandando...', 'Sent.': 'Ea, mandao.',
    'Continue': 'Vamo allá', 'Cancel': 'Déjalo', 'Close': 'Cerrá', 'Retry': 'Prueba otra vé',
    'Refresh': 'Conectá otra vé', 'Send >': 'Mandá >', '[+] Attach': '[+] Adjuntá',
    'Choose file': 'Elige er archivo', 'File saved.': 'Ea, archivo guardao.',
    'No messages in this chat.': 'Por aquí no hay mensajeh todavía.',
    'Connecting to Telegram...': 'Conectando con Telegram, miarma...',
    'Your phone number': 'Er número de tu móvi', 'Your phone number:': 'Er número de tu móvi:',
    'Unknown account': 'Cuenta desconocía', 'New account': 'Otra cuenta',
    'Offline': 'Sin conexión', 'Information': 'La información', 'Back': 'Pa trá',
    'More': 'Má cosillah', 'Default': 'Como venía', 'Restore defaults': 'Dejarlo como venía',
    'Reset to defaults': 'Dejarlo como venía', 'Apply': 'Ea, aplícalo',
    'Complex features': 'Cosillah má complicáh', 'Help': 'Una ayudita',
    'Calls and video': 'Llamáh y vídeo', 'Incoming call': 'Te tan llamando, quillo',
    'Calling…': 'Llamando…', 'Ringing…': 'Sonando…', 'Connected': 'Ea, conectao',
    'Call ended': 'Se acabó la llamá', 'Call failed': 'La llamá no ha salío',
    'Answer': 'Contestá', 'Answer with video': 'Contestá con vídeo',
    'Hang up': 'Colgá', 'Decline': 'Ahora no, miarma',
    'Mute microphone': 'Callá er micro', 'Unmute microphone': 'Dale vó ar micro',
    'Start camera': 'Encendé la cámara', 'Stop camera': 'Apagá la cámara',
    'Delete': 'Borrá', 'Saved Messages': 'Mensajeh guardaoh', 'You': 'Tú',
}
_COMMON = {'para': 'pa', 'nada': 'ná', 'todo': 'to', 'todos': 'toos', 'todas': 'toas'}
_WORDS = {
    'es-x-chileno': {**_COMMON, 'puedes': 'podís', 'quieres': 'querís', 'tienes': 'tenís',
        'sabes': 'sabís', 'estás': 'tai', 'está': 'ta', 'están': 'tan', 'aquí': 'acá',
        'ordenador': 'computador', 'móvil': 'celu', 'pulsa': 'aprieta', 'vale': 'ya',
        'bonito': 'bacán', 'bonita': 'bacán'},
    'es-x-andaluz': {**_COMMON, 'todos': 'toh', 'todas': 'toah', 'los': 'loh', 'las': 'lah',
        'el': 'er', 'del': 'der', 'al': 'ar', 'más': 'má', 'estás': 'táh', 'está': 'ta',
        'están': 'tan', 'estas': 'ehtah', 'estos': 'ehtoh', 'esto': 'ehto',
        'mensajes': 'mensajeh', 'ajustes': 'ajujteh', 'opciones': 'opcioneh',
        'botones': 'botoneh', 'archivos': 'archivoh', 'fotos': 'fotoh', 'cuentas': 'cuentah',
        'seleccionados': 'seleccionaoh', 'seleccionadas': 'seleccionáh', 'vez': 'vé',
        'puedes': 'puedeh', 'quieres': 'quiereh', 'tienes': 'tieneh', 'vale': 'ea',
        'guardar': 'guardá', 'borrar': 'borrá', 'cerrar': 'cerrá', 'abrir': 'abrí',
        'enviar': 'mandá', 'restaurar': 'restaurá', 'seleccionar': 'seleccioná',
        'descargar': 'descargá', 'conectar': 'conectá', 'volver': 'volvé'},
}
# Protected technical tokens never acquire phonetic spelling or lose format braces.
_PROTECTED = re.compile(r'(\{[^{}]*\}|https?://\S+|tg://\S+|@[\w]+|/[\w-]+|'
    r'`[^`]*`|\b(?:TG-ASCII|Telegram|Premium|Windows|macOS|Linux|Android|iOS|'
    r'API|ID|ASCII|GIF|PNG|JPEG|JPG|MP4|ZIP|HTML|Markdown|Enter|Shift|Ctrl|Alt|Esc|Tab|F\d+)\b)')
_WORD = re.compile(r'[^\W\d_]+', re.UNICODE)

def render_variant(key, spanish, code):
    if code not in LANGUAGES:
        raise ValueError('Unknown playful language')
    explicit = (_CHILEAN if code == 'es-x-chileno' else _ANDALUSIAN).get(key)
    if explicit is not None:
        return explicit
    words = _WORDS[code]
    def replace(match):
        original = match.group()
        lower = original.lower()
        value = words.get(lower, lower)
        if value == lower and len(lower) > 5:
            value = re.sub(r'ado(s?)$', r'ao\1', lower)
            value = re.sub(r'ada(s?)$', r'á\1', value)
            value = re.sub(r'ido(s?)$', r'ío\1', value)
            value = re.sub(r'ida(s?)$', r'ía\1', value)
        if original.isupper():
            return value.upper()
        return value.capitalize() if original[0].isupper() else value
    pieces = _PROTECTED.split(spanish)
    for i in range(0, len(pieces), 2):
        pieces[i] = _WORD.sub(replace, pieces[i])
    return ''.join(pieces)

def build_catalogue(spanish, code):
    return {key: render_variant(key, value, code) for key, value in spanish.items()}
