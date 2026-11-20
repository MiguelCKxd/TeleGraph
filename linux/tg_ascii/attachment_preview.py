"""Before sending (1.4): file preview, and editing with the system's own editor.

Defaults keep TG-ASCII's own tools: photos open in the built-in editor, other
files get an in-app preview card. Two settings (off by default) switch to the
operating system instead:

* "Always edit photos and videos with the system editor"
* "Always preview files with the system app"

System editing works on a private copy (``native_open.editable_copy``): the
user edits and saves in Preview/QuickTime (macOS) or Paint/Photos (Windows),
then confirms "Use edited file". The original file is never modified.
"""
import asyncio
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from .i18n import tr


def readable_size(value):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if value < 1024 or unit == 'GB':
            return f'{value:.0f} {unit}' if unit == 'B' else f'{value:.1f} {unit}'
        value /= 1024
    return f'{value:.1f} GB'


def route_attachment(app, path, accepted, interactive=False):
    """Entry point when a file is attached (``interactive=False``) or when the
    user asks for 'Preview / edit' (``interactive=True``).

    Attaching never adds a modal step for ordinary files: they are attached at
    once, as before; their preview card is one click away in the attachment
    bar. Photos keep opening the built-in editor."""
    from .native_open import media_kind
    values = getattr(getattr(app, 'preferences', None), 'values', {})
    kind = media_kind(path)
    from .custom_menus import handled
    if kind in ('image', 'video') and handled('media_editor', app, Path(path), accepted):
        return None  # 1.5.2: the user's own editor (menus/media_editor/menu.py)
    if kind not in ('image', 'video') and handled('file_preview', app, Path(path), accepted):
        return None  # 1.5.2: the user's own preview (menus/file_preview/menu.py)
    if kind in ('image', 'video') and __import__('tg_ascii.menu_style',fromlist=['x']).uses_system('media_editor'):
        return edit_natively(app, path, accepted)
    if Path(path).suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp'):
        from .image_tools import image_editor
        import uuid
        try:
            image_editor(app.root, path, app.preview_dir / (uuid.uuid4().hex + '.jpg'), accepted,
                         native=lambda: edit_natively(app, path, accepted))
        except (OSError, ValueError, ImportError) as exc:
            app.show_error(exc)
        return None
    if interactive:
        return preview_file(app, path, accepted, system=__import__('tg_ascii.menu_style',fromlist=['x']).uses_system('file_preview'))
    if __import__('tg_ascii.menu_style',fromlist=['x']).uses_system('file_preview'):
        from .native_open import quick_look
        try:
            quick_look(path)
        except OSError as exc:
            app.show_error(exc)
    accepted(Path(path))
    return None


def _report(app):
    return lambda error: app.worker.events.put((app.show_error, error))


def edit_natively(app, path, accepted):
    window, frame = app.dialog('Edit with system editor', '520x300')
    message = tk.StringVar(master=window, value=tr('Preparing a private copy...'))
    ttk.Label(frame, textvariable=message, wraplength=470).pack(fill='x', pady=10)
    copy = [None]
    controls = ttk.Frame(frame)
    controls.pack(fill='x', side='bottom', pady=8)

    def valid():
        return window.winfo_exists()

    def use_copy():
        if copy[0] is not None and valid():
            window.destroy()
            accepted(Path(copy[0]))

    def choose_exported():
        from .app_dialogs import filedialog
        chosen = filedialog.askopenfilename(parent=window, title=tr('Choose the edited file'))
        if chosen and valid():
            window.destroy()
            from .backend import attachment_path
            try:
                accepted(attachment_path(chosen))
            except (OSError, ValueError) as exc:
                app.show_error(exc)

    use = ttk.Button(controls, text=tr('Use edited file'), command=use_copy, state='disabled')
    use.pack(side='right')
    ttk.Button(controls, text=tr('Choose the edited file'), command=choose_exported).pack(side='right', padx=4)
    ttk.Button(controls, text=tr('Cancel'), command=window.destroy).pack(side='left')

    async def prepare():
        from .native_open import editable_copy, launch_editor
        target = await asyncio.to_thread(editable_copy, path)
        await asyncio.to_thread(launch_editor, target)
        return target

    def ready(target):
        if not valid():
            return
        copy[0] = target
        use.configure(state='normal')
        message.set(tr('Edit the file in the system editor, save your changes there, then press “Use edited file”. If the editor exported a new file, choose it instead.'))

    def failed(error):
        if valid():
            message.set(tr('The system editor could not be opened: ') + str(error))

    app.worker.submit(prepare(), ready, failed)
    return window


def preview_file(app, path, accepted, *, system=False):
    from .native_open import media_kind, open_with_system, quick_look
    path = Path(path)
    kind = media_kind(path)
    window, frame = app.dialog('Attachment preview', '560x520')
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    ttk.Label(frame, text=path.name, wraplength=500, style='Title.TLabel').pack(anchor='w', pady=(8, 2))
    kind_label = {'image': tr('Image'), 'video': tr('Video'), 'file': tr('File')}[kind]
    ttk.Label(frame, text=f'{kind_label} · {readable_size(size)}', style='Muted.TLabel').pack(anchor='w')
    picture = ttk.Label(frame, anchor='center')
    picture.pack(fill='both', expand=True, pady=10)

    def valid():
        try:
            return bool(window.winfo_exists())
        except tk.TclError:
            return False

    controls = ttk.Frame(frame)
    controls.pack(fill='x', side='bottom', pady=8)

    def attach():
        if valid():
            window.destroy()
            accepted(path)

    ttk.Button(controls, text=tr('Attach'), command=attach).pack(side='right')
    ttk.Button(controls, text=tr('Cancel'), command=window.destroy).pack(side='right', padx=4)
    actions = ttk.Frame(frame)
    actions.pack(fill='x', side='bottom')
    ttk.Button(actions, text=tr('Open with system app'),
               command=lambda: open_with_system(path, path.name, on_error=_report(app))).pack(side='left', pady=4)
    if kind in ('image', 'video'):
        ttk.Button(actions, text=tr('Edit with system editor'),
                   command=lambda: (window.destroy(), edit_natively(app, path, accepted))).pack(side='left', padx=4, pady=4)
    if system:
        # Setting on: show the operating system's preview right away.
        try:
            quick_look(path)
        except OSError as exc:
            app.show_error(exc)
        picture.configure(text=tr('Shown in the system preview.'))
        return window
    if kind == 'image':
        def painted(photo):
            if valid():
                picture.image = photo
                picture.configure(image=photo or '')
        app.request_photo(path, (480, 300), painted, owner=picture, valid=valid)
    elif kind == 'video':
        target = app.preview_dir / f'attachment-{abs(hash(str(path)))}-poster.jpg'

        def poster():
            from .video_frames import VideoFrames
            frames = VideoFrames(path)
            try:
                image = frames.get(0).convert('RGB')
                image.thumbnail((480, 300))
                image.save(target, format='JPEG', quality=85)
            finally:
                frames.close()
            return target

        def shown(result):
            if valid():
                app.request_photo(result, (480, 300), lambda photo: (setattr(picture, 'image', photo),
                                  picture.configure(image=photo or '')) if valid() else None, owner=picture, valid=valid)

        app.worker.submit(asyncio.to_thread(poster), shown, lambda _: picture.configure(text='▶') if valid() else None)
    else:
        picture.configure(text='📄')
    return window
