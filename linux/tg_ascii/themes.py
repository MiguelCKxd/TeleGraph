"""Independent interface and logo appearance, with native system preference detection."""
import subprocess
import sys
import tkinter as tk
import re

DARK = {'bg': '#08100c', 'panel': '#0e1b13', 'text': '#8cf5a6', 'muted': '#80a98c', 'line': '#294d34', 'selected': '#284f35', 'strong': '#bdffcd'}
LIGHT = {'bg': '#f4f8f3', 'panel': '#ffffff', 'text': '#14532d', 'muted': '#4a6854', 'line': '#b2c9b7', 'selected': '#d4ebd9', 'strong': '#0b4521'}
_palette = DARK
_font_family = None
_system_palette = 'dark'


def set_font(family):
    global _font_family
    _font_family = family


def system_theme(refresh=False):
    global _system_palette
    if not refresh:return _system_palette
    _system_palette=_read_system_theme()
    return _system_palette


def _read_system_theme():
    if sys.platform == 'win32':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
                return 'light' if winreg.QueryValueEx(key, 'AppsUseLightTheme')[0] else 'dark'
        except OSError: return 'dark'
    if sys.platform == 'darwin':
        native = _mac_native_theme()
        if native is not None:
            return native
        try:
            result = subprocess.run(['/usr/bin/defaults', 'read', '-g', 'AppleInterfaceStyle'], capture_output=True, text=True, timeout=2)
            return 'dark' if result.stdout.strip().lower() == 'dark' else 'light'
        except (OSError, subprocess.SubprocessError): return 'dark'
    return 'dark'


_mac_preferences = None


def _mac_native_theme():
    """Read AppleInterfaceStyle through CoreFoundation, without a subprocess.

    With the "system" theme this runs every 5 s. Spawning /usr/bin/defaults
    each time cost a process launch; CFPreferences is an in-process call to
    cfprefsd. Any ctypes problem returns None and the old path is used.
    """
    global _mac_preferences
    try:
        if _mac_preferences is None:
            import ctypes
            import ctypes.util
            cf = ctypes.CDLL(ctypes.util.find_library('CoreFoundation'))
            cf.CFStringCreateWithCString.restype = ctypes.c_void_p
            cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
            cf.CFPreferencesCopyAppValue.restype = ctypes.c_void_p
            cf.CFPreferencesCopyAppValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            cf.CFPreferencesAppSynchronize.argtypes = [ctypes.c_void_p]
            cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
            cf.CFGetTypeID.argtypes = [ctypes.c_void_p]
            cf.CFGetTypeID.restype = ctypes.c_ulong
            cf.CFStringGetTypeID.restype = ctypes.c_ulong
            cf.CFRelease.argtypes = [ctypes.c_void_p]
            any_application = ctypes.c_void_p.in_dll(cf, 'kCFPreferencesAnyApplication')
            key = cf.CFStringCreateWithCString(None, b'AppleInterfaceStyle', 0x08000100)
            if not key:
                _mac_preferences = False
                return None
            _mac_preferences = (ctypes, cf, any_application, key)
        if _mac_preferences is False:
            return None
        ctypes, cf, any_application, key = _mac_preferences
        cf.CFPreferencesAppSynchronize(any_application)
        value = cf.CFPreferencesCopyAppValue(key, any_application)
        if not value:
            return 'light'  # Key absent: macOS is in light appearance.
        try:
            if cf.CFGetTypeID(value) != cf.CFStringGetTypeID():
                return 'light'
            buffer = ctypes.create_string_buffer(64)
            if not cf.CFStringGetCString(value, buffer, 64, 0x08000100):
                return None
            return 'dark' if buffer.value.strip().lower() == b'dark' else 'light'
        finally:
            cf.CFRelease(value)
    except Exception:
        _mac_preferences = False
        return None


def resolve_theme(choice, system=None):
    return (system or system_theme()) if choice == 'system' else choice if choice in ('dark', 'light') else 'dark'


def palette(choice):
    return LIGHT if choice == 'light' else DARK


def set_palette(value):
    global _palette
    _palette = value


def apply_local_appearance(widget):
    """Restore explicitly styled native surfaces after the general theme pass."""
    values = getattr(widget, '_local_appearance', None)
    if not isinstance(values, dict):
        return
    options = {}
    for key in ('background', 'foreground', 'highlightbackground', 'highlightcolor'):
        color = values.get(key)
        if isinstance(color, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            options[key] = color
    width = values.get('highlightthickness')
    if type(width) is int and 0 <= width <= 8:
        options['highlightthickness'] = width
    if options:
        widget.configure(**options)


def apply_widget(widget):
    """Restyle existing controls without rebuilding a message draft or login form."""
    if isinstance(widget, tk.Menu) or getattr(widget,'_corner_overlay',False): return
    p = _palette
    try:
        if _font_family and 'font' in widget.keys():
            from tkinter import font as tkfont
            current = widget.cget('font')
            if current:
                value = tkfont.Font(root=widget, font=current)
                value.configure(family=_font_family)
                widget._tg_font = value
                widget.configure(font=value)
        if isinstance(widget, (tk.Tk, tk.Toplevel, tk.Frame, tk.Canvas)):
            widget.configure(background=p['bg'])
        if isinstance(widget, (tk.Text, tk.Listbox, tk.Entry)):
            widget.configure(background=p['panel'], foreground=p['text'], selectbackground=p['selected'], selectforeground=p['text'], highlightbackground=p['line'])
            if isinstance(widget, (tk.Text, tk.Entry)): widget.configure(insertbackground=p['text'])
        if isinstance(widget, tk.Text):
            for tag in widget.tag_names():
                if tag == 'sender': widget.tag_configure(tag, foreground=p['muted'])
                elif tag == 'outgoing' or tag.startswith('media_'): widget.tag_configure(tag, foreground=p['strong'])
        if isinstance(widget, tk.Label): widget.configure(background=p['bg'], foreground=p['text'])
        from .appearance import shape_widget
        shape_widget(widget)
        apply_local_appearance(widget)
        for child in widget.winfo_children(): apply_widget(child)
    except tk.TclError: pass


def set_app_icon(root, path, *, windows_shortcuts=True):
    """Window icon on Windows; application Dock icon on macOS."""
    if sys.platform == 'win32':
        from .windows_launcher import set_window_icon
        set_window_icon(root, path, windows_shortcuts)
        return
    if sys.platform != 'darwin':
        image = tk.PhotoImage(master=root, file=str(path))
        scale = max(1, image.width() // 256)
        root._tg_icon = image.subsample(scale)
        root.iconphoto(True, root._tg_icon)
        return
    import ctypes
    import ctypes.util
    library = ctypes.util.find_library('objc')
    if not library: return
    objc = ctypes.CDLL(library)
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    address = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value
    def send(receiver, selector, argument=None, text=False, returns=True):
        arguments = [ctypes.c_void_p, ctypes.c_void_p]
        if argument is not None: arguments.append(ctypes.c_char_p if text else ctypes.c_void_p)
        method = ctypes.CFUNCTYPE(ctypes.c_void_p if returns else None, *arguments)(address)
        args = [receiver, objc.sel_registerName(selector)]
        if argument is not None: args.append(argument)
        return method(*args)
    string = send(objc.objc_getClass(b'NSString'), b'stringWithUTF8String:', str(path).encode('utf-8'), text=True)
    image = send(objc.objc_getClass(b'NSImage'), b'alloc')
    image = send(image, b'initWithContentsOfFile:', string)
    if not image: return
    application = send(objc.objc_getClass(b'NSApplication'), b'sharedApplication')
    send(application, b'setApplicationIconImage:', image, returns=False)
    send(image, b'release', returns=False)
    if not any(flag in sys.argv for flag in ('--demo', '--self-test')):
        _save_dock_image(path)


def _save_dock_image(path):
    # Only the packaged app owns a Dock tile. An isolated test bundle gets its own cache.
    from pathlib import Path
    import os
    import tempfile
    import Foundation
    from PIL import Image
    bundle = Foundation.NSBundle.mainBundle()
    if not bundle.objectForInfoDictionaryKey_('NSDockTilePlugIn'):
        return
    identifier = str(bundle.bundleIdentifier())
    base = Path.home() / 'Library/Application Support' / identifier
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    # The plug-in needs only this bounded PNG, independent of Telegram profiles.
    with Image.open(path) as source:
        if source.width > 2048 or source.height > 2048:
            return
        source.thumbnail((1024, 1024))
        icon = source.convert('RGBA')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=base, delete=False) as stream:
            temporary = Path(stream.name)
            icon.save(stream, 'PNG')
        os.replace(temporary, base / 'DockIcon.png')
    finally:
        icon.close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    Foundation.NSDistributedNotificationCenter.defaultCenter().postNotificationName_object_userInfo_deliverImmediately_(
        identifier + '.dock-icon-changed', None, None, True)
