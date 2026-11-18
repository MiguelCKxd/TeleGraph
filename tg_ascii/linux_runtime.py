"""Linux startup details for the packaged app (1.5.5).

PyInstaller's GObject hook points GI_TYPELIB_PATH at the bundle only. The
tray icon's AppIndicator typelib comes from the system (the .deb depends on
gir1.2-ayatanaappindicator3-0.1), so the system folders are added after the
bundled one. Nothing here runs on macOS or Windows.
"""
import glob
import os
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
