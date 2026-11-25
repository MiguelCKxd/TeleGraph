"""Call video in the system PiP controller on macOS, or a window-manager-owned compact window."""
import sys
import tkinter as tk

from .i18n import tr


class CompactCallWindow:
    def __init__(self, call):
        self.call = call
        self.window = tk.Toplevel(call.window)
        self.window.title(tr('Video call'))
        self.window.geometry('320x180')
        self.window.minsize(160, 90)
        self.windows_runtime = None
        self.app_window = None
        self.window.attributes('-topmost', True)
        if sys.platform == 'win32':
            self.window.attributes('-toolwindow', True)
        elif self.window.tk.call('tk', 'windowingsystem') == 'x11':
            self.window.attributes('-type', 'utility')
        self.picture = tk.Label(self.window, background='black', borderwidth=0)
        self.picture.pack(fill='both', expand=True)
        self.picture.bind('<Double-Button-1>', lambda event: self.restore())
        self.window.protocol('WM_DELETE_WINDOW', self.restore)
        self.window._lock_app_owner = call.owner
        self.photo = None
        if sys.platform == 'win32':
            self.window.update_idletasks()
            self.use_windows_presenter()

    def use_windows_presenter(self):
        # The Windows App SDK's compact overlay is associated with the actual
        # top-level HWND. Preserve the native floating window on older systems.
        try:
            import ctypes
            from ctypes import wintypes
            from winui3.microsoft.windows.applicationmodel.dynamicdependency import bootstrap
            self.windows_runtime = bootstrap.initialize()
            from winui3.microsoft.ui.interop import get_window_id_from_window
            from winui3.microsoft.ui.windowing import AppWindow, AppWindowPresenterKind
            user = ctypes.WinDLL('user32')
            user.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
            user.GetAncestor.restype = wintypes.HWND
            hwnd = user.GetAncestor(self.window.winfo_id(), 2)  # GA_ROOT
            self.app_window = AppWindow.get_from_window_id(get_window_id_from_window(hwnd))
            self.app_window.set_presenter_by_kind(AppWindowPresenterKind.COMPACT_OVERLAY)
        except (ImportError, OSError, RuntimeError, AttributeError):
            self.app_window = None
            if self.windows_runtime:
                self.windows_runtime()
                self.windows_runtime = None

    def restore(self):
        self.close()
        if self.call.alive():
            self.call.window.deiconify()
            self.call.window.lift()

    def displaying(self):
        return bool(self.window.winfo_exists())

    def show(self, image):
        from PIL import ImageTk
        self.photo = ImageTk.PhotoImage(image, master=self.window)
        self.picture.configure(image=self.photo)

    def clear(self):
        self.picture.configure(image='')
        self.photo = None

    def close(self):
        if self.window.winfo_exists():
            self.window.destroy()
        self.photo = self.app_window = None
        if self.windows_runtime:
            self.windows_runtime()
            self.windows_runtime = None


def open_call_pip(call):
    if sys.platform == 'darwin':
        try:
            from .mac_call_pip import MacCallPiP
            if MacCallPiP.supported():
                return MacCallPiP(call)
        except (ImportError, OSError, RuntimeError, AttributeError, tk.TclError):
            pass
    return CompactCallWindow(call)
