"""Optional interface motion, editable as data and idle when not animating."""
from . import APP_NAME
from copy import deepcopy
import hashlib
import math
from pathlib import Path
import shutil
import tkinter as tk
from tkinter import ttk

from .preferences import read_json, write_json

EASINGS = ('linear', 'ease-out', 'ease-in-out')
SWIPE_DEFAULT = {'enabled': True, 'gesture_enabled': True, 'duration_ms': 96,
                 'distance': 80, 'threshold': 65, 'easing': 'linear', 'asset': ''}


def defaults():
    return {'schema': 1, 'enabled': True, 'events': {'swipe_reply': SWIPE_DEFAULT.copy()}}


def validate_event(value):
    result = SWIPE_DEFAULT.copy()
    if not isinstance(value, dict):
        return result
    for key in ('enabled', 'gesture_enabled'):
        if type(value.get(key)) is bool:
            result[key] = value[key]
    for key, low, high in (('duration_ms', 0, 5000), ('distance', 20, 400), ('threshold', 20, 250)):
        if type(value.get(key)) is int and low <= value[key] <= high:
            result[key] = value[key]
    if value.get('easing') in EASINGS:
        result['easing'] = value['easing']
    asset = value.get('asset', '')
    if isinstance(asset, str) and len(asset) <= 500 and not any(ord(char) < 32 for char in asset):
        candidate = Path(asset)
        if asset and not candidate.is_absolute() and '..' not in candidate.parts and candidate.parts[0] == 'animations':
            result['asset'] = candidate.as_posix()
    return result


def validate_motion(value):
    result = defaults()
    if not isinstance(value, dict) or value.get('schema', 1) != 1:
        return result
    if type(value.get('enabled')) is bool:
        result['enabled'] = value['enabled']
    events = value.get('events', {})
    if isinstance(events, dict):
        result['events']['swipe_reply'] = validate_event(events.get('swipe_reply'))
    return result


def motion_root(app):
    store = getattr(app, 'interface_store', None)
    return Path(store.root) if store is not None else app.preferences.path.parent / 'interface'


def get_motion(app):
    value = getattr(app, '_motion_settings', None)
    if value is None:
        value = app._motion_settings = validate_motion(read_json(motion_root(app) / 'motion.json', defaults()))
    return value


def motion_event(app, name='swipe_reply'):
    values = get_motion(app)
    event = values['events'].get(name, SWIPE_DEFAULT).copy()
    event['enabled'] = values['enabled'] and event['enabled']
    return event


def save_motion(app, value):
    value = validate_motion(value)
    write_json(motion_root(app) / 'motion.json', value)
    app._motion_settings = value
    return value


def reload_motion(app):
    app._motion_settings = None
    return get_motion(app)


def restore_motion(app):
    return save_motion(app, defaults())


def resource_path(app, asset):
    base = (motion_root(app) / 'resources').resolve()
    path = (base / asset).resolve()
    if not path.is_relative_to(base) or not asset:
        raise ValueError('Animation must be inside interface/resources')
    return path


def import_animation(app, source):
    """Copy an ordinary image/animation; imported files never execute code."""
    from PIL import Image
    source = Path(source)
    if source.stat().st_size > 20 * 1024 * 1024:
        raise ValueError('Animation is too large (20 MB maximum).')
    with Image.open(source) as image:
        if image.format not in ('GIF', 'PNG', 'WEBP') or image.width * image.height > 4_000_000:
            raise ValueError('Choose a GIF, APNG, PNG or WebP image up to 4 megapixels.')
        suffix = {'GIF': '.gif', 'PNG': '.png', 'WEBP': '.webp'}[image.format]
        image.seek(0)
        image.load()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
    relative = 'animations/' + digest + suffix
    destination = resource_path(app, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copyfile(source, destination)
    return relative


def resource_photo(app, path, size):
    from .animation import AnimationPlayer
    if not hasattr(app, 'animation_player'):
        app.animation_player = AnimationPlayer(app.root)
    return app.animation_player.photo(path, size, enabled=get_motion(app)['enabled'])


def indicator_photo(app, event):
    if not event['asset']:
        return None
    try:
        return resource_photo(app, resource_path(app, event['asset']), (26, 26))
    except (OSError, ValueError, ImportError, tk.TclError):
        return None


def easing(value, kind):
    value = max(0, min(1, value))
    if kind == 'ease-out':
        return 1 - (1 - value) ** 3
    if kind == 'ease-in-out':
        return value * value * (3 - 2 * value)
    return value


class ReturnMotion:
    """A finite, cancellable clock. Disabled effects allocate no Tk timer."""
    def __init__(self, widget, start, update, finish, event, valid=lambda: True):
        self.widget, self.start, self.update, self.finish = widget, start, update, finish
        self.event, self.valid = event, valid
        self.job = None
        self.cancelled = False
        from .resources import frame_interval, frame_limit
        step_ms = 16 if frame_limit() is None else frame_interval()  # 1.5.0.1 frame limit
        self.steps = max(1, math.ceil(event['duration_ms'] / step_ms))
        if not event['enabled'] or not event['duration_ms'] or not start:
            self.update(0)
            self.finish()
        else:
            self.step(1)

    def step(self, number):
        self.job = None
        if self.cancelled:
            return
        if not self.widget.winfo_exists():
            self.cancel()
            return
        if not self.valid():
            self.cancel()
            self.finish()
            return
        fraction = easing(min(1, number / self.steps), self.event['easing'])
        self.update(self.start * (1 - fraction))
        if number >= self.steps:
            self.finish()
        else:
            self.job = self.widget.after(max(1, round(self.event['duration_ms'] / self.steps)), lambda: self.step(number + 1))

    def cancel(self):
        self.cancelled = True
        if self.job is not None:
            try:
                self.widget.after_cancel(self.job)
            except tk.TclError:
                pass
        self.job = None


def open_motion_settings(app):
    from .app_dialogs import Choice, filedialog, messagebox
    from .interface_layout import caption
    window, frame = app.dialog(caption('Motion and animations', 'Movimiento y animaciones'), '510x570')
    current = deepcopy(get_motion(app));event = current['events']['swipe_reply']
    enabled = tk.BooleanVar(master=window, value=current['enabled'])
    swipe = tk.BooleanVar(master=window, value=event['enabled'])
    gesture = tk.BooleanVar(master=window, value=event['gesture_enabled'])
    asset = tk.StringVar(master=window, value=event['asset'])
    ttk.Checkbutton(frame, text=caption('Animate the interface', 'Animar la interfaz'), variable=enabled).pack(anchor='w', pady=5)
    ttk.Checkbutton(frame, text=caption('Swipe to reply', 'Deslizar para responder'), variable=gesture).pack(anchor='w')
    ttk.Checkbutton(frame, text=caption('Animate reply swipe', 'Animar el gesto de respuesta'), variable=swipe).pack(anchor='w')
    values = {}
    for key, en, es, maximum in (('duration_ms', 'Return duration (ms)', 'Duración del regreso (ms)', 5000),
            ('distance', 'Visual distance (px)', 'Distancia visual (px)', 400),
            ('threshold', 'Gesture distance (px)', 'Distancia del gesto (px)', 250)):
        row = ttk.Frame(frame);row.pack(fill='x', pady=4)
        ttk.Label(row, text=caption(en, es)).pack(side='left')
        variable = values[key] = tk.StringVar(master=window, value=str(event[key]))
        ttk.Spinbox(row, from_=0 if key=='duration_ms' else 20, to=maximum, textvariable=variable, width=8).pack(side='right')
    ttk.Label(frame, text=caption('Movement curve', 'Curva del movimiento')).pack(anchor='w', pady=(8, 0))
    curve = Choice(frame, values=list(EASINGS));curve.set(event['easing']);curve.pack(fill='x')
    ttk.Label(frame, text=caption('Reply indicator · GIF / APNG / WebP', 'Indicador de respuesta · GIF / APNG / WebP')).pack(anchor='w', pady=(12, 0))
    ttk.Entry(frame, textvariable=asset).pack(fill='x')
    preview = ttk.Label(frame, text='↩');preview.pack(pady=8)
    def show():
        try:
            preview.image = resource_photo(app, resource_path(app, asset.get()), (48, 48)) if asset.get() else None
            preview.configure(image=preview.image or '', text='' if preview.image else '↩')
        except (OSError, ValueError, ImportError, tk.TclError) as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=window)
    def imported():
        path = filedialog.askopenfilename(parent=window, filetypes=[('GIF / APNG / WebP', '*.gif *.png *.apng *.webp')])
        if not path:return
        try:
            asset.set(import_animation(app, path));show()
        except (OSError, ValueError) as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=window)
    ttk.Button(frame, text=caption('Import animation…', 'Importar animación…'), command=imported).pack(fill='x')
    ttk.Button(frame, text=caption('Preview file', 'Previsualizar archivo'), command=show).pack(fill='x', pady=3)
    ttk.Label(frame, text=caption('Edit interface/motion.json or resources/animations, then reload. Original movement is enabled by default.',
        'Edita interface/motion.json o resources/animations y recarga. El movimiento original está activado por defecto.'), wraplength=430).pack(fill='x', pady=8)
    def apply():
        try:
            chosen = {key: int(variable.get()) for key, variable in values.items()}
            chosen.update(enabled=swipe.get(), gesture_enabled=gesture.get(), easing=curve.get(), asset=asset.get().strip())
            if validate_event(chosen) != chosen:raise ValueError(caption('Check the values and resource path.', 'Revisa los valores y la ruta del recurso.'))
            save_motion(app, {'schema': 1, 'enabled': enabled.get(), 'events': {'swipe_reply': chosen}})
            window.destroy()
        except (OSError, ValueError) as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=window)
    def reset():
        restore_motion(app);window.destroy();open_motion_settings(app)
    def reload():
        reload_motion(app);window.destroy();open_motion_settings(app)
    row = ttk.Frame(frame);row.pack(fill='x', pady=8)
    ttk.Button(row, text=caption('Restore defaults', 'Restaurar valores iniciales'), command=reset).pack(side='left')
    ttk.Button(row, text=caption('Reload files', 'Recargar archivos'), command=reload).pack(side='left', padx=3)
    ttk.Button(row, text=caption('Apply', 'Aplicar'), command=apply).pack(side='right')
    return window
