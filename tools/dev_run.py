"""Run the mobile core + interface on the Mac (no Toga) for quick testing.

Usage: dev_run.py DATA_DIR [locale] [voice-sample.ogg|.caf]   -> prints the URL to open.
"""
import sys
import time
from pathlib import Path

here = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(here / 'src'))
from tg_ascii_mobile.core import Core  # noqa: E402

core = Core(Path(sys.argv[1]), 'macOS-dev', sys.argv[2] if len(sys.argv) > 2 else 'es-ES')


def show_notification(account, peer, title, body, count, sound, **details):
    if account == core.account:
        core.emit('toast', {'text': f'{title} · {body}'})


core.native_notify = show_notification
if len(sys.argv) > 3:
    # Fake microphone for testing voice messages: "records" this Ogg or CAF file.
    import os
    import shutil
    sample, recording = Path(sys.argv[3]), {}

    def start(base, done):
        recording['path'] = base + sample.suffix
        done({'path': recording['path']})

    def stop():
        path = recording.pop('path', None)
        if path:
            shutil.copy(sample, path)
        return path
    core.native_voice = {'start': start, 'stop': stop, 'cancel': lambda: recording.pop('path', None),
                         'level': lambda: (time.time() % 1)}
port = core.start()
print(f'http://127.0.0.1:{port}/?t={core.token}&platform=dev', flush=True)
while True:
    time.sleep(3600)
