"""Open TG-ASCII when you log in to the computer (1.5.4, off by default).

- macOS: a LaunchAgent in ~/Library/LaunchAgents that runs ``open`` on this
  app bundle (the same as double-clicking it).
- Windows: a value under HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run.
- Linux: an XDG ``~/.config/autostart`` entry.

Only the current user is affected, nothing needs administrator rights, and
turning the option off (or "Delete all app data") removes the entry.
"""
from . import APP_NAME
import os
from pathlib import Path
import plistlib
import sys

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE_NAME = 'TG-ASCII'


def bundle_path():
    """The .app bundle when running from one (macOS), else None."""
    if not getattr(sys, 'frozen', False):
        return None
    return next((parent for parent in Path(sys.executable).resolve().parents if parent.suffix == '.app'), None)


def bundle_identifier():
    bundle = bundle_path()
    if bundle is not None:
        try:
            with (bundle / 'Contents' / 'Info.plist').open('rb') as stream:
                value = plistlib.load(stream).get('CFBundleIdentifier')
            if isinstance(value, str) and value:
                return value
        except (OSError, ValueError):
            pass
    return 'org.tgas.desktop' if getattr(sys, 'frozen', False) else 'org.tgas.desktop.dev'


def command():
    """What the system runs at login."""
    bundle = bundle_path()
    if sys.platform == 'darwin' and bundle is not None:
        return ['/usr/bin/open', str(bundle)]
    if getattr(sys, 'frozen', False):
        return [sys.executable]
    return [sys.executable, '-m', 'tg_ascii']


def _agent_path(home=None):
    return Path(home or Path.home()) / 'Library' / 'LaunchAgents' / f'{bundle_identifier()}.login.plist'


def _desktop_path(home=None):
    base = os.environ.get('XDG_CONFIG_HOME') or str(Path(home or Path.home()) / '.config')
    return Path(base) / 'autostart' / 'tg-ascii.desktop'


def _windows_value():
    return ' '.join(f'"{part}"' for part in command())


def is_enabled(home=None):
    try:
        if sys.platform == 'darwin':
            return _agent_path(home).is_file()
        if sys.platform == 'win32':
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.QueryValueEx(key, VALUE_NAME)
            return True
        return _desktop_path(home).is_file()
    except OSError:
        return False


def set_enabled(enabled, home=None):
    """Create or remove the login entry. Raises OSError if the system refuses."""
    if sys.platform == 'darwin':
        path = _agent_path(home)
        if not enabled:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        agent = {'Label': f'{bundle_identifier()}.login', 'ProgramArguments': command(),
                 'RunAtLoad': True, 'ProcessType': 'Interactive'}
        if not getattr(sys, 'frozen', False):
            agent['WorkingDirectory'] = str(Path(__file__).resolve().parents[1])
        temporary = path.with_suffix('.tmp')
        with temporary.open('wb') as stream:
            plistlib.dump(agent, stream)
        os.replace(temporary, path)
        return
    if sys.platform == 'win32':
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if enabled:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _windows_value())
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
        return
    path = _desktop_path(home)
    if not enabled:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    exec_line = ' '.join(f'"{part}"' for part in command())
    path.write_text(f'[Desktop Entry]\nType=Application\nName={APP_NAME}\nExec={exec_line}\nX-GNOME-Autostart-enabled=true\n',
                    encoding='utf-8')


def apply(enabled):
    """Bring the system in line with the setting; returns an error or None."""
    try:
        if enabled:
            set_enabled(True)  # Rewritten each time: follows the app if it was moved.
        elif is_enabled():
            set_enabled(False)
        return None
    except OSError as exc:
        return exc
