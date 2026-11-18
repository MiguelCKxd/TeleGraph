"""Open the operating-system emoji palette in response to an explicit click."""
import sys

def open_palette():
    if sys.platform=='darwin':
        import ctypes
        objc=ctypes.CDLL('/usr/lib/libobjc.A.dylib')
        objc.objc_getClass.argtypes=[ctypes.c_char_p]; objc.objc_getClass.restype=ctypes.c_void_p
        objc.sel_registerName.argtypes=[ctypes.c_char_p]; objc.sel_registerName.restype=ctypes.c_void_p
        send=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p)(('objc_msgSend',objc))
        app=send(objc.objc_getClass(b'NSApplication'),objc.sel_registerName(b'sharedApplication'))
        action=ctypes.CFUNCTYPE(None,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p)(('objc_msgSend',objc))
        action(app,objc.sel_registerName(b'orderFrontCharacterPalette:'),None)
    elif sys.platform=='win32':
        import ctypes
        user=ctypes.WinDLL('user32',use_last_error=True)
        # Win+. invokes the Windows picker; key-up is guaranteed in finally.
        try:
            user.keybd_event(0x5B,0,0,0); user.keybd_event(0xBE,0,0,0)
        finally:
            user.keybd_event(0xBE,0,2,0); user.keybd_event(0x5B,0,2,0)
    else: raise RuntimeError('Use your system emoji keyboard shortcut.')


def open_for(entry,on_error):
    """Keep the insertion target; open the system palette after the button event finishes."""
    if not entry.winfo_exists():return
    entry.focus_set()
    from .menu_style import choice
    if choice('emoji_picker')=='app':  # 1.5.1 Settings › Menus
        from .app_menus import open_emoji_picker
        entry.after_idle(lambda:open_emoji_picker(entry) if entry.winfo_exists() else None)
        return
    def show():
        if not entry.winfo_exists():return
        try:open_palette()
        except (OSError,RuntimeError,ImportError,AttributeError) as exc:on_error(exc)
    entry.after_idle(show)


def search_entry(parent,app,variable):
    from tkinter import ttk
    from .i18n import tr
    row=ttk.Frame(parent);row.pack(fill='x',pady=(2,6))
    entry=ttk.Entry(row,textvariable=variable)
    ttk.Button(row,text=tr('Emojis'),width=5,takefocus=False,
               command=lambda:open_for(entry,app.show_error)).pack(side='right',padx=(4,0))
    entry.pack(side='left',fill='x',expand=True)
    variable.entry=entry
    return entry
