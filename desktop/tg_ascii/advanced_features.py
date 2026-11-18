"""Opt-in capabilities. Importing this registry performs no network or GUI work."""
import sys
from .i18n import tr


FEATURES = {
    'polls': ('Encuestas y cuestionarios', 'Crear, votar y consultar resultados.'),
    'checklists': ('Listas de tareas', 'Crear y editar listas compartidas; requiere Premium para crearlas.'),
    'locations': ('Ubicaciones', 'Compartir coordenadas y lugares elegidos explícitamente.'),
    'contacts': ('Compartir contactos', 'Elegir los datos de contacto que se enviarán.'),
    'articles': ('Artículos', 'Crear y abrir publicaciones largas.'),
    'stars_gifts': ('Estrellas y regalos', 'Catálogo, regalos, reacciones de pago y enlaces oficiales de compra.'),
    'links': ('Enlaces, menciones y etiquetas', 'Abrir enlaces de Telegram, perfiles y búsquedas de hashtags.'),
    'stories': ('Historias y publicaciones del perfil', 'Consultar y publicar historias sólo al abrir su sección.'),
    'chat_translation': ('Traducción de chats', 'Traducir el historial del chat seleccionado con Telegram Premium.'),
    'call_history': ('Registro de llamadas', 'Consultar el historial de llamadas al abrir su pestaña.'),
    'calls': ('Calls and video', 'Enable calls in Complex features. Microphone and camera start only when you call or answer.'),
    'chat_list_activity': ('Activity in the chat list', 'Shows ● when a contact is online and ··· while someone is typing, between the chat name and its unread counter.'),
    'contact_list_details': ('Contact list details', 'Shows profile photo, activity status and Premium emoji status in the contact list.'),
    'custom_menus': ('Customizable menus', 'Choose device or app menus for each kind and customize any menu from its own folder. Off: each menu uses its lightest, smoothest version.'),
    'process_decoding': ('Decode in separate processes', 'Stickers, emoji and photos are prepared in separate processes, one per spare core, instead of threads of the app. Off: as in the original version.'),
    'gpu_video': ('GPU video in group calls', 'With the expanded view, the cameras are drawn by the graphics card in their own window, which can be enlarged or made full screen, and each camera is sent bigger and smoother. Off: the grid inside the call window, as in the original version.'),
    'group_video_grid': ('Expanded group video view', 'Shows every camera Telegram allows at once (up to 30) in group video calls, in a grid. Uses more CPU and data. Off: one camera at a time, as before.'),
    'push_notifications': (
        'macOS push notifications' if sys.platform == 'darwin' else 'Windows push notifications',
        'Requires a configured macOS push identity. Normal notifications remain available.' if sys.platform == 'darwin' else 'Requires a configured Windows push identity. Normal notifications remain available.'
    ),
}


# Features on by default (none in the main line; the Beta line turns on
# process_decoding here).
DEFAULT_ON = frozenset()


def validated_features(value):
    value = value if isinstance(value, dict) else {}
    return {key: value.get(key, key in DEFAULT_ON) is True for key in FEATURES}


def feature_enabled(owner, key):
    preferences = getattr(owner, 'preferences', owner)
    values = preferences if isinstance(preferences, dict) else getattr(preferences, 'values', {})
    if not isinstance(values, dict):
        return False
    enabled = values.get('advanced_features', {})
    return key in FEATURES and isinstance(enabled, dict) and enabled.get(key) is True


def profile_feature_enabled(owner,kind):
    feature={'posts':'stories','gifts':'stars_gifts','polls':'polls','links':'links'}.get(kind)
    return feature is None or feature_enabled(owner,feature)


def build_feature_settings(parent, preferences):
    import tkinter as tk
    from tkinter import ttk
    values = validated_features(preferences.values.get('advanced_features'))
    ttk.Label(parent, text=tr('Estas funciones están desactivadas por defecto. Activarlas permite usarlas; los datos se cargan al abrir cada función.'), wraplength=480).pack(fill='x', pady=8)
    variables = {}
    for key, (label, detail) in FEATURES.items():
        variable = tk.BooleanVar(master=parent, value=values[key])
        variables[key] = variable
        ttk.Checkbutton(parent, text=tr(label), variable=variable, style='Settings.TCheckbutton').pack(fill='x', pady=(9, 2))
        ttk.Label(parent, text=tr(detail), wraplength=480).pack(fill='x', padx=20)
    ttk.Button(parent, text=tr('Desactivar todas'), command=lambda: [v.set(False) for v in variables.values()]).pack(fill='x', pady=12)
    return variables
