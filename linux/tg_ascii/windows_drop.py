"""Windows shell drops using pointer-sized APIs on x86, x64 and ARM64."""
import ctypes as c
from ctypes import wintypes as w


def install(root, callback):
    if getattr(root, '_tg_shell_drop', None):
        return True
    root.update_idletasks()
    shell = c.WinDLL('shell32', use_last_error=True)
    common = c.WinDLL('comctl32', use_last_error=True)
    user = c.WinDLL('user32', use_last_error=True)
    pointer, result = c.c_size_t, c.c_ssize_t
    proc_type = c.WINFUNCTYPE(result, w.HWND, w.UINT, w.WPARAM, w.LPARAM, pointer, pointer)
    user.GetParent.argtypes, user.GetParent.restype = [w.HWND], w.HWND
    common.SetWindowSubclass.argtypes = [w.HWND, proc_type, pointer, pointer]
    common.SetWindowSubclass.restype = w.BOOL
    common.RemoveWindowSubclass.argtypes = [w.HWND, proc_type, pointer]
    common.RemoveWindowSubclass.restype = w.BOOL
    common.DefSubclassProc.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    common.DefSubclassProc.restype = result
    shell.DragAcceptFiles.argtypes = [w.HWND, w.BOOL]
    shell.DragAcceptFiles.restype = None
    shell.DragQueryFileW.argtypes = [w.HANDLE, w.UINT, w.LPWSTR, w.UINT]
    shell.DragQueryFileW.restype = w.UINT
    shell.DragFinish.argtypes = [w.HANDLE]
    shell.DragFinish.restype = None
    hwnd = user.GetParent(root.winfo_id()) or root.winfo_id()
    identifier = 0x544741

    @proc_type
    def procedure(handle, message, wp, lp, subclass, data):
        if message == 0x0233:  # WM_DROPFILES
            paths = []
            try:
                count = shell.DragQueryFileW(wp, 0xFFFFFFFF, None, 0)
                for index in range(min(count, 100)):
                    length = shell.DragQueryFileW(wp, index, None, 0)
                    buffer = c.create_unicode_buffer(length + 1)
                    shell.DragQueryFileW(wp, index, buffer, length + 1)
                    paths.append(buffer.value)
            finally:
                shell.DragFinish(wp)
            root.after_idle(callback, paths)
            return 0
        if message == 0x0082:  # WM_NCDESTROY
            common.RemoveWindowSubclass(handle, procedure, identifier)
        return common.DefSubclassProc(handle, message, wp, lp)

    if not common.SetWindowSubclass(hwnd, procedure, identifier, 0):
        return False
    shell.DragAcceptFiles(hwnd, True)
    # Keep the callback and libraries alive for the entire native window lifetime.
    root._tg_shell_drop = (procedure, shell, common, user)
    return True
