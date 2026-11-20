"""Windows window identity and icon synchronization for installed TeleGraph shortcuts."""
import ctypes as C
from contextlib import contextmanager
from hashlib import sha256
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile
from uuid import UUID

from .notifications import APP_ID


def identify_process():
    identify = C.windll.shell32.SetCurrentProcessExplicitAppUserModelID
    identify.argtypes = [C.c_wchar_p]
    identify.restype = C.c_long
    _check(identify(APP_ID))


def icon_file(image_path, cache):
    """A different location for each image lets Explorer invalidate just this icon."""
    from PIL import Image, ImageOps

    contents = Path(image_path).read_bytes()
    destination = Path(cache) / (sha256(contents).hexdigest()[:24] + '.ico')
    if destination.is_file():
        return destination
    from io import BytesIO
    with Image.open(BytesIO(contents)) as image:
        image = ImageOps.contain(image.convert('RGBA'), (256, 256), Image.Resampling.LANCZOS)
        canvas = Image.new('RGBA', (256, 256))
        canvas.paste(image, ((256 - image.width) // 2, (256 - image.height) // 2))
        destination.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=destination.parent, suffix='.ico', delete=False) as f:
            temporary = Path(f.name)
            try:
                canvas.save(f, format='ICO', sizes=[(n, n) for n in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
            except BaseException:
                f.close()
                temporary.unlink(missing_ok=True)
                raise
    try:
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _guid(value):
    return (C.c_byte * 16).from_buffer_copy(UUID(value).bytes_le)


def _check(result):
    if result < 0:
        raise OSError(f'Windows shell HRESULT 0x{result & 0xffffffff:08x}')


def _method(ptr, index, *signature):
    vtable = C.cast(ptr, C.POINTER(C.POINTER(C.c_void_p))).contents
    return C.WINFUNCTYPE(C.c_long, C.c_void_p, *signature)(vtable[index])


@contextmanager
def _interface(ptr, iid=None):
    if iid is not None:
        other = C.c_void_p()
        _check(_method(ptr, 0, C.c_void_p, C.c_void_p)(ptr, C.byref(_guid(iid)), C.byref(other)))
        ptr = other
    try:
        yield ptr
    finally:
        _method(ptr, 2)(ptr)


class _PropertyKey(C.Structure):
    _fields_ = [('fmtid', C.c_byte * 16), ('pid', C.c_uint32)]


class _VariantValue(C.Union):
    _fields_ = [('string', C.c_void_p), ('reserved', C.c_void_p * 2)]


class _Variant(C.Structure):
    _fields_ = [('vt', C.c_ushort), ('reserved', C.c_ushort * 3), ('value', _VariantValue)]


def _update_link(path, executable, icon):
    """Change only a plain shortcut to this exact executable."""
    link = C.c_void_p()
    _check(C.windll.ole32.CoCreateInstance(C.byref(_guid('00021401-0000-0000-c000-000000000046')),
           None, 1, C.byref(_guid('000214f9-0000-0000-c000-000000000046')), C.byref(link)))
    with _interface(link), _interface(link, '0000010b-0000-0000-c000-000000000046') as file:
        _check(_method(file, 5, C.c_wchar_p, C.c_uint32)(file, str(path), 2))
        buffer = C.create_unicode_buffer(32768)
        _check(_method(link, 3, C.c_wchar_p, C.c_int, C.c_void_p, C.c_uint32)(
            link, buffer, len(buffer), None, 0))
        if os.path.normcase(buffer.value) != os.path.normcase(str(executable)):
            return False
        _check(_method(link, 10, C.c_wchar_p, C.c_int)(link, buffer, len(buffer)))
        if buffer.value:
            return False
        index = C.c_int()
        _check(_method(link, 16, C.c_wchar_p, C.c_int, C.c_void_p)(link, buffer, len(buffer), C.byref(index)))
        changed = buffer.value != str(icon) or index.value != 0
        if changed:
            _check(_method(link, 17, C.c_wchar_p, C.c_int)(link, str(icon), 0))
        with _interface(link, '886d8eeb-8cf2-4446-8d02-cdba1dbdcf99') as props:
            key = _PropertyKey(_guid('9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3'), 5)
            previous = _Variant()
            _check(_method(props, 5, C.c_void_p, C.c_void_p)(props, C.byref(key), C.byref(previous)))
            try:
                correct_id = previous.vt == 31 and C.wstring_at(previous.value.string) == APP_ID
            finally:
                C.windll.ole32.PropVariantClear(C.byref(previous))
            if not correct_id:
                owner = C.create_unicode_buffer(APP_ID)
                value = _Variant()
                value.vt = 31  # VT_LPWSTR; owner remains alive until SetValue copies it.
                value.value.string = C.cast(owner, C.c_void_p)
                _check(_method(props, 6, C.c_void_p, C.c_void_p)(props, C.byref(key), C.byref(value)))
                _check(_method(props, 7)(props))
                changed = True
        if changed:
            _check(_method(file, 6, C.c_wchar_p, C.c_int)(file, str(path), 1))
        return changed


def _announce(paths):
    """Explorer gives a shortcut a per-instance icon. Once the pinned button has shown one, a plain
    update notice for that link is ignored until Explorer drops its icon cache, so going back to a
    logo kept the old image for minutes. Dropping the cache first lets the update notices apply."""
    if paths:
        C.windll.shell32.SHChangeNotify(0x08000000, 0x1000, None, None)  # SHCNE_ASSOCCHANGED, SHCNF_FLUSH
    for path in paths:
        C.windll.shell32.SHChangeNotify(0x2000, 0x2005, C.c_wchar_p(str(path)), None)  # SHCNE_UPDATEITEM


def update_shortcuts(executable, icon):
    """Refresh TeleGraph's existing Start, desktop and taskbar links without creating pins."""
    # COM apartment for shell links. The UI may already use a different apartment.
    status = C.windll.ole32.CoInitializeEx(None, 2)
    if status != -2147417850:  # RPC_E_CHANGED_MODE requires no matching CoUninitialize.
        _check(status)
    try:
        folders = []
        for csidl in (2, 16):  # Programs and DesktopDirectory honor redirected user folders.
            path = C.create_unicode_buffer(260)
            if C.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, path) >= 0:
                folders.append(Path(path.value))
        pins = Path(os.environ['APPDATA']) / 'Microsoft/Internet Explorer/Quick Launch/User Pinned/TaskBar'
        shortcuts = [d / name for d in folders for name in ('TeleGraph.lnk', 'TG-ASCII.lnk')]
        if pins.is_dir():
            shortcuts.extend(pins.glob('*.lnk'))
        changed = []
        for path in shortcuts:
            if path.is_file():
                try:
                    if _update_link(path, executable, icon):
                        changed.append(path)
                except OSError:
                    # A removed or read-only shortcut must not block the other surfaces.
                    continue
        _announce(changed)
    finally:
        if status >= 0:
            C.windll.ole32.CoUninitialize()


def set_window_icon(root, image, synchronize):
    cache = Path(os.environ['LOCALAPPDATA']) / 'TeleGraph' / 'LauncherIcons'
    icon = icon_file(image, cache)
    root.iconbitmap(str(icon))
    root.iconbitmap(default=str(icon))
    if synchronize and getattr(sys, 'frozen', False):
        from concurrent.futures import ThreadPoolExecutor
        queue = getattr(root, '_tg_shortcut_worker', None)
        if queue is None:
            queue = root._tg_shortcut_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='TeleGraph-shell')
        queue.submit(update_shortcuts, Path(sys.executable), icon)
