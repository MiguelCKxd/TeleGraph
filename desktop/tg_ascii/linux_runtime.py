"""Linux startup details for the packaged app (1.5.5).

PyInstaller's GObject hook points GI_TYPELIB_PATH at the bundle only. The
tray icon's AppIndicator typelib comes from the system (the .deb depends on
gir1.2-ayatanaappindicator3-0.1), so the system folders are added after the
bundled one. Nothing here runs on macOS or Windows.
"""
from configparser import ConfigParser, Error as ConfigError
import glob
from pathlib import Path
from tempfile import NamedTemporaryFile
import os
from io import StringIO
import sys

SYSTEM_TYPELIBS = ('/usr/lib/*-linux-gnu/girepository-1.0', '/usr/lib/girepository-1.0',
                   '/usr/lib64/girepository-1.0')


def prepare():
    if not sys.platform.startswith('linux'):
        return
    current = [part for part in os.environ.get('GI_TYPELIB_PATH', '').split(os.pathsep) if part]
    for pattern in SYSTEM_TYPELIBS:
        for folder in sorted(glob.glob(pattern)):
            if folder not in current and os.path.isdir(folder):
                current.append(folder)
    if current:
        os.environ['GI_TYPELIB_PATH'] = os.pathsep.join(current)


DESKTOP_ID = 'tg-ascii.desktop'
ICON_NAME = 'org.tgas.desktop.selected'
SYSTEM_DESKTOP = Path('/usr/share/applications') / DESKTOP_ID
DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=TeleGraph
GenericName=Telegram client
Comment=Unofficial Telegram client with an ASCII look
Exec={command} %U
Icon={icon}
Terminal=false
Categories=Network;InstantMessaging;Chat;
Keywords=telegram;chat;messages;
StartupWMClass=Tg-ascii
"""


def _write_new(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(content)
            handle.flush()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def _desktop_string(value):
    return str(value).replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')


def sync_launcher_icon(asset, name=None):
    """Update the user's existing desktop ID, including its pinned GNOME icon."""
    if not getattr(sys, 'frozen', False):
        return
    executable = Path(sys.executable).resolve()
    installed = Path('/opt/tg-ascii/TG-ASCII')
    if executable.name != 'TG-ASCII' or (installed.is_file() and executable != installed.resolve()):
        return
    base = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
    try:
        import fcntl
        folder = base / 'telegraph' / 'launcher-icons'
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / '.update.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            _sync_desktop_entry(executable, Path(asset), base, folder, name)
    except (OSError, UnicodeError, ConfigError, KeyError):
        # An invalid or read-only desktop override must not break the window icon.
        return


def _sync_desktop_entry(executable, asset, base, folder, name=None):
    name = ' '.join(str(name or 'TeleGraph').split())[:64] or 'TeleGraph'
    launcher = base / 'applications' / DESKTOP_ID
    if launcher.is_symlink() or (launcher.exists() and not launcher.is_file()):
        return
    old = launcher.read_text(encoding='utf-8') if launcher.exists() else ''
    marker = 'X-TeleGraph-Managed'
    entry = None
    if old:
        entry = ConfigParser(interpolation=None, strict=False, delimiters=('=',))
        entry.optionxform = str
        entry.read_string(old)
        main = entry['Desktop Entry']
        if main.get(marker) == 'true':
            entry = None
        elif main.get('Exec') not in ('/opt/tg-ascii/TG-ASCII %U', '/usr/bin/tg-ascii %U', 'tg-ascii %U'):
            return
    # Keep a stable GIcon. Replacing the Icon key makes GNOME detach a
    # running window from the object used by the pinned launcher.
    theme = base / 'icons' / 'hicolor'
    themed = theme / '512x512' / 'apps' / (ICON_NAME + '.png')
    selected = folder / 'selected.png'
    if themed.is_symlink():
        if themed.readlink() != selected:
            return
    elif themed.exists():
        return
    if selected.is_symlink() or (selected.exists() and not selected.is_file()):
        return
    image = asset.read_bytes()
    changed = not selected.exists() or image != selected.read_bytes()
    if changed:
        _write_new(selected, image)
    if not themed.is_symlink():
        themed.parent.mkdir(parents=True, exist_ok=True)
        themed.symlink_to(selected)
        changed = True
    # Exec is a desktop-entry argument list, not a shell command. A filename
    # containing % must survive field-code expansion and reserved characters
    # inside the double quotes need a second escaping layer in the key file.
    quoted = str(executable).replace('%', '%%')
    for char in ('\\', '"', '`', '$'):
        quoted = quoted.replace(char, '\\' + char)
    content = DESKTOP_ENTRY.format(command=_desktop_string('"' + quoted + '"'), icon=ICON_NAME).replace(
        '\nName=TeleGraph\n', '\nName=' + _desktop_string(name) + '\n', 1) + marker + '=true\n'
    if entry is not None:
        # An older same-app user entry may also have custom keys or desktop actions.
        main.update({'Name': _desktop_string(name), 'Icon': ICON_NAME, 'StartupWMClass': 'Tg-ascii'})
        for key in tuple(main):
            if key.startswith('Name[') and main[key] in ('TG-ASCII', 'Tg-As'):
                main[key] = 'TeleGraph'
        buffer = StringIO()
        entry.write(buffer, space_around_delimiters=False)
        content = buffer.getvalue()
    # Debian already supplies the canonical entry. Leave its path and
    # identity in place on the first launch as well as on later launches.
    use_system = not old and executable == Path('/opt/tg-ascii/TG-ASCII') and SYSTEM_DESKTOP.is_file()
    if not use_system and content != old:
        _write_new(launcher, content.encode('utf-8'))
        changed = True
    if changed:
        # GNOME rescans icon themes on desktop changes. Announce the icon
        # without modifying any launcher fields or leaving a second entry.
        os.utime(themed.parent)
        os.utime(theme)
        launcher.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=launcher.parent, prefix='telegraph-icon-', suffix='.desktop') as notice:
            notice.write(b'[Desktop Entry]\nHidden=true\n')
            notice.flush()
