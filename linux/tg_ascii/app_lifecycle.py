"""'Restart app' and 'Quit completely' (tools menu ⋯, 1.4).

Both reuse the normal Quit sequence (drafts flushed, sessions disconnected,
push channels released) and then make sure nothing keeps running:

* helper processes of the call engine still alive are terminated;
* if the interpreter does not finish within ``EXIT_GRACE`` seconds (a blocked
  worker thread, a tray thread, a native library), the process is ended;
* for a restart, a fresh instance is launched after the single-instance lock
  has been released, so the new process becomes the primary instance.
"""
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

EXIT_GRACE = 4.0
_mode = None
_children = set()
_children_lock = threading.Lock()


_wipe_root = None


def request(mode):
    """'restart', 'quit' or None (cancelled)."""
    global _mode, _wipe_root
    if mode not in ('restart', 'quit', None):
        raise ValueError('Unknown lifecycle mode')
    _mode = mode
    if mode is None:
        _wipe_root = None


def request_wipe(root):
    """1.5.3, Settings › Delete all app data: after the app has closed and
    released its files, delete the data folder and start again empty."""
    global _mode, _wipe_root
    _mode, _wipe_root = 'restart', root


def requested():
    return _mode


def register_child(pid):
    if isinstance(pid, int) and pid > 0:
        with _children_lock:
            _children.add(pid)


def unregister_child(pid):
    with _children_lock:
        _children.discard(pid)


def terminate_children():
    with _children_lock:
        pids = tuple(_children)
        _children.clear()
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM if sys.platform == 'win32' else signal.SIGKILL)
        except (OSError, ValueError):
            pass  # Already finished.
    return pids


def relaunch_command(argv=None, executable=None, frozen=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    executable = executable or sys.executable
    frozen = getattr(sys, 'frozen', False) if frozen is None else frozen
    if not frozen:
        return [executable, '-m', 'tg_ascii', *argv]
    path = Path(executable)
    bundle = next((parent for parent in path.parents if parent.suffix == '.app'), None)
    if sys.platform == 'darwin' and bundle is not None:
        # A new instance of the same bundle keeps Dock, notifications and TCC identity.
        return ['/usr/bin/open', '-n', str(bundle), *(['--args', *argv] if argv else [])]
    return [str(path), *argv]


def relaunch():
    command = relaunch_command()
    options = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL,
               'close_fds': True}
    if sys.platform == 'win32':
        options['creationflags'] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        options['start_new_session'] = True
    subprocess.Popen(command, **options)


def finish():
    """Called once Tk's mainloop has ended and the instance lock is released."""
    mode = _mode
    if mode is None:
        return None
    terminate_children()
    if _wipe_root is not None:
        try:
            from .app_data import wipe
            wipe(_wipe_root)
        except Exception:
            pass  # Never block the exit; whatever is left stays on disk.
    if mode == 'restart':
        try:
            relaunch()
        except OSError:
            pass  # The old instance still exits; the user can open the app again.
    def watchdog():
        import time
        time.sleep(EXIT_GRACE)
        os._exit(0)
    threading.Thread(target=watchdog, name='tg-exit-watchdog', daemon=True).start()
    return mode


def windows_fast_exit(grace=1.5):
    """Windows only (1.4.1). After a normal close, everything is already saved
    and disconnected; let the tray thread remove its icon, then end the process
    without interpreter finalisation. Windows logged real TG-ASCII.exe crashes
    (0xc0000409 in the x64 emulator, 0xc0000005 in ntdll) consistent with
    teardown races between Tcl and still-running worker/tray threads.
    macOS keeps its current exit path unchanged."""
    if sys.platform != 'win32':
        return
    import time
    deadline = time.monotonic() + grace
    for thread in threading.enumerate():
        if thread is threading.current_thread() or thread.daemon:
            continue
        thread.join(max(0.0, deadline - time.monotonic()))
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None:
                stream.flush()
        except Exception:
            pass
    try:
        import atexit
        atexit._run_exitfuncs()  # e.g. native_open's temporary folder cleanup.
    except Exception:
        pass
    try:
        import logging
        logging.shutdown()
    except Exception:
        pass
    os._exit(0)
