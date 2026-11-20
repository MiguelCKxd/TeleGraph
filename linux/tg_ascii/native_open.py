"""Open downloaded media with the operating system's own viewer.

Telegram previews are often saved without a meaningful extension
(``…-gallery.media``). System viewers choose an application by extension, so
the file is copied to a private temporary folder with the extension that
matches its real content. The folder is removed when TG-ASCII exits; a viewer
that is still open keeps its own handle on macOS (Windows viewers usually
load the whole image).
"""
from . import APP_NAME
import atexit
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading

_folder = None
_lock = threading.Lock()
_IMAGE_EXTENSIONS = {'JPEG': '.jpg', 'PNG': '.png', 'GIF': '.gif', 'WEBP': '.webp', 'BMP': '.bmp',
                     'TIFF': '.tiff', 'HEIF': '.heic', 'AVIF': '.avif'}


def _private_folder():
    global _folder
    with _lock:
        if _folder is None or not Path(_folder).is_dir():
            _folder = tempfile.mkdtemp(prefix='tg-ascii-open-')
            atexit.register(shutil.rmtree, _folder, True)
        return Path(_folder)


def detected_extension(path):
    path = Path(path)
    try:
        from PIL import Image
        with Image.open(path) as image:
            extension = _IMAGE_EXTENSIONS.get(image.format or '')
            if extension:
                return extension
    except Exception:
        pass
    try:
        with path.open('rb') as stream:
            head = stream.read(16)
    except OSError:
        return path.suffix or '.bin'
    if head[4:8] == b'ftyp':
        return '.mp4'
    if head.startswith(b'\x1aE\xdf\xa3'):
        return '.webm'
    if head.startswith(b'%PDF'):
        return '.pdf'
    return path.suffix if path.suffix and path.suffix != '.media' else '.bin'


def viewable_copy(path, name=APP_NAME):
    source = Path(path)
    stem = ''.join(ch for ch in Path(name or APP_NAME).stem if ch.isalnum() or ch in ' -_')[:60].strip() or APP_NAME
    folder = _private_folder()
    target = folder / (stem + detected_extension(source))
    number = 1
    while target.exists():
        target = folder / f'{stem} ({number}){target.suffix}'
        number += 1
    shutil.copyfile(source, target)
    return target


def launch(path):
    path = str(path)
    if sys.platform == 'darwin':
        subprocess.Popen(['/usr/bin/open', path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)
    elif sys.platform == 'win32':
        os.startfile(path)  # Default app registered for the extension (Photos, etc.).
    else:
        subprocess.Popen(['xdg-open', path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)


def open_with_system(path, name=APP_NAME, on_error=None):
    """Copy + launch in a background thread so Tk never waits on disk or the OS."""
    def work():
        try:
            launch(viewable_copy(path, name))
        except Exception as error:  # Reported to the caller's Tk-safe handler.
            if on_error is not None:
                on_error(error)
    threading.Thread(target=work, name='tg-open-native', daemon=True).start()


# ---------------------------------------------------------------- 1.4 editing
IMAGE_SUFFIXES = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.heic', '.tiff')
VIDEO_SUFFIXES = ('.mp4', '.mov', '.m4v', '.webm', '.mkv', '.avi')


def media_kind(path):
    suffix = Path(path).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return 'image'
    if suffix in VIDEO_SUFFIXES:
        return 'video'
    return 'file'


def editable_copy(path):
    """Private copy the system editor may overwrite; the original stays intact."""
    source = Path(path)
    folder = _private_folder()
    target = folder / source.name
    number = 1
    while target.exists():
        target = folder / f'{source.stem} ({number}){source.suffix}'
        number += 1
    shutil.copyfile(source, target)
    return target


def launch_editor(path):
    path = str(path)
    kind = media_kind(path)
    if sys.platform == 'darwin':
        application = {'image': 'Preview', 'video': 'QuickTime Player'}.get(kind)
        command = ['/usr/bin/open', *(['-a', application] if application else []), path]
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)
    elif sys.platform == 'win32':
        try:
            os.startfile(path, 'edit')  # Paint / Photos for images when registered.
        except OSError:
            os.startfile(path)  # Videos: the default app (Photos/Clipchamp).
    else:
        launch(path)


def quick_look(path):
    """System preview without editing: Quick Look on macOS, default app elsewhere."""
    if sys.platform == 'darwin' and Path('/usr/bin/qlmanage').exists():
        subprocess.Popen(['/usr/bin/qlmanage', '-p', str(path)], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    else:
        launch(path)
