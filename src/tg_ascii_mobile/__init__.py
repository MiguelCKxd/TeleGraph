"""TeleGraph for Android and iOS."""
import platform
import sys

# SiriKit imports Telethon before Toga calls startup(). On Apple silicon the
# iPad sandbox can stat the Mac's Apache MIME database but cannot read it.
# Install Python's built-in MIME table before *any* mobile entry point runs.
if sys.platform == 'ios' or (sys.platform == 'darwin' and platform.system() == 'iOS'):
    import mimetypes
    mimetypes.knownfiles = []

from tg_ascii import __version__ as CORE_VERSION

__version__ = '3.4.0'
