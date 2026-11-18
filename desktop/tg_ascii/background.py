"""Tray integration. Failure never leaves an invisible, unreachable window."""
from . import APP_NAME
from pathlib import Path
import sys
from .i18n import tr


class Background:
    def __init__(self, dispatch, show, quit_app, icon_path=None):
        self.icon = None
        self.error = None
        self._gtk_context = None
        try:
            import pystray
            from PIL import Image
            options = {}
            if sys.platform == 'darwin':
                from AppKit import NSApplication
                options['darwin_nsapplication'] = NSApplication.sharedApplication()
            with Image.open(icon_path or Path(__file__).parent / 'assets' / 'logo-title-short-dark.png') as source:
                picture = source.copy()
                picture.thumbnail((64, 64))
            def reopen(icon, item): dispatch(show)
            def quit_now(icon, item): dispatch(quit_app)
            self.icon = pystray.Icon('TG-ASCII', picture, APP_NAME,
                menu=pystray.Menu(pystray.MenuItem(tr('Open Tg-As'), reopen, default=True),
                                  pystray.MenuItem(tr('Quit Tg-As'), quit_now)), **options)
            if sys.platform.startswith('linux') and type(self.icon).__module__ in ('pystray._appindicator', 'pystray._gtk'):
                from gi.repository import GLib
                self._gtk_context = GLib.MainContext.default()
            self.icon.run_detached()
        except Exception as exc:
            self.error = exc
            self.stop()

    def update_icon(self, path):
        if self.icon is None: return
        try:
            from PIL import Image
            with Image.open(path) as source:
                picture = source.copy()
                picture.thumbnail((64, 64))
            self.icon.icon = picture
        except (OSError, ValueError): pass

    @property
    def ready(self):
        return self.icon is not None and self.icon.visible and visible_backend(self.icon)

    def process_events(self):
        # Tk owns the GUI thread. Detached GTK tray icons queue registration and
        # menu actions on the default GLib context, which Tk does not dispatch.
        if self._gtk_context is not None:
            for _ in range(8):
                if not self._gtk_context.iteration(False):
                    break

    def stop(self):
        if self.icon is not None:
            try: self.icon.stop()
            except Exception: pass
            self.icon = None
        self._gtk_context = None


def visible_backend(icon):
    """1.5.5, Linux: only a tray the desktop really shows counts. GNOME on
    Wayland ignores old X11 (XEmbed) tray icons; with that backend the window
    must stay reachable (minimised) instead of hiding into an invisible icon."""
    if not sys.platform.startswith('linux'):
        return True
    import os
    backend = type(icon).__module__.rsplit('.', 1)[-1]
    if backend == '_appindicator':
        indicator = getattr(icon, '_appindicator', None)
        return indicator is not None and indicator.get_property('connected')
    if backend == '_gtk':
        status_icon = getattr(icon, '_status_icon', None)
        return status_icon is not None and status_icon.is_embedded()
    return backend == '_xorg' and not os.environ.get('WAYLAND_DISPLAY')
