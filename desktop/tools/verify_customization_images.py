"""Native Tk regression for async customization images, using isolated demo data.

Run from a graphical desktop:
    python tools/verify_customization_images.py --output result.json
No credentials, account databases, Telegram connection or existing settings are used.
"""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
from unittest.mock import patch

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tg_ascii.appearance import app_palette
from tg_ascii.desktop import Desktop
from tg_ascii.interface_background import _interface_picture
from tg_ascii.interface_store import default_layout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    outcome = {'success': False, 'platform': sys.platform, 'callback_errors': 0}
    with ExitStack() as cleanup:
        data = Path(cleanup.enter_context(tempfile.TemporaryDirectory(prefix='tg-ascii-images-check-')))
        cleanup.enter_context(patch.dict(os.environ, {'TG_ASCII_DATA_DIR': str(data)}))
        fixture = data / 'synthetic-background.png'
        size = (640, 400)
        horizontal = Image.linear_gradient('L').rotate(90).resize(size)
        vertical = Image.linear_gradient('L').resize(size)
        source = Image.merge('RGB', (horizontal, vertical, Image.new('L', size, 83)))
        source.save(fixture)
        main_thread = threading.get_ident()
        preparation_threads = []
        preparing = [0, 0]
        preparation_lock = threading.Lock()
        def prepare(*values):
            with preparation_lock:
                preparation_threads.append(threading.get_ident())
                preparing[0] += 1
                preparing[1] = max(preparing)
            try:
                return _interface_picture(*values)
            finally:
                with preparation_lock:
                    preparing[0] -= 1
        cleanup.enter_context(patch('tg_ascii.interface_background._interface_picture', prepare))
        root = tk.Tk()
        root.geometry('1000x720')
        app = Desktop(root, demo=True)
        painter = app.interface_background
        finished = False
        stage = 'startup'
        custom_key = None
        first_size = None
        first_resource_size = None

        def check(condition, label):
            if not condition:
                raise AssertionError(label)

        def finish(error=None):
            nonlocal finished
            if finished:
                return
            finished = True
            if error is not None:
                outcome.update(success=False, error=type(error).__name__, stage=stage)
                if isinstance(error, AssertionError):
                    outcome['check'] = str(error)
            runtime = getattr(app, 'layout_runtime', None)
            if runtime is not None and runtime.editor is not None:
                runtime.editor.close()
            # Demo watchdog/cleanup must not open a confirmation dialog.
            app.busy = False
            def close_timeout():
                if app.closed:
                    return
                outcome.update(success=False, error='CloseTimeout', stage='closing')
                app.worker.stop()
                root.destroy()
            root.after(5000, close_timeout)
            app.close()

        def callback_error(kind, error, trace):
            outcome['callback_errors'] += 1
            finish(error)
        root.report_callback_exception = callback_error
        app.show_error = finish

        def wait_for(label, ready, next_step, timeout=12):
            nonlocal stage
            stage = label
            deadline = time.monotonic() + timeout
            def poll():
                if finished:
                    return
                try:
                    if ready():
                        next_step()
                    elif time.monotonic() >= deadline:
                        finish(TimeoutError())
                    else:
                        root.after(25, poll)
                except Exception as error:
                    finish(error)
            root.after(25, poll)

        def background_ready():
            return (painter.picture is not None and not painter._preparing
                    and not painter._picture_pending
                    and painter.signature == painter.picture_signature()
                    and bool(painter.entries) and painter.job is None
                    and all(geometry[:4] == painter.signature
                            for _, _, geometry, _ in painter.entries.values()))

        def verify_pixels():
            expected = ImageOps.fit(source, (root.winfo_width(), root.winfo_height()), method=Image.Resampling.LANCZOS)
            color = app_palette(app.preferences.values)['bg']
            expected = Image.blend(expected, Image.new('RGB', expected.size, color), .22)
            check(painter.picture.size == expected.size, 'Fitted background dimensions')
            check(painter.picture.tobytes() == expected.tobytes(), 'Fitted background pixels')
            samples = 0
            for widget, (_, photo, geometry, _) in painter.entries.items():
                if not widget.winfo_exists() or not widget.winfo_ismapped():
                    continue
                x, y, width, height = geometry[-4:]
                check((photo.width(), photo.height()) == (width, height), 'Panel image dimensions')
                for px, py in ((0, 0), (width // 2, height // 2), (width - 1, height - 1)):
                    point = (x + px, y + py)
                    color = expected.getpixel(point) if 0 <= point[0] < expected.width and 0 <= point[1] < expected.height else (0, 0, 0)
                    check(tuple(photo.get(px, py)) == color, 'Native panel pixels')
                    samples += 1
            check(samples > 0, 'Visible background panel samples')
            outcome['checked_panel_pixels'] = outcome.get('checked_panel_pixels', 0) + samples

        def resource_ready():
            widget = app.layout_runtime.widgets.get(custom_key)
            return (widget is not None and getattr(widget, '_layout_photo', None) is not None
                    and getattr(widget, '_layout_photo_size', None)
                    == (max(1, min(2048, widget.winfo_width()-8)), max(1, min(2048, widget.winfo_height()-8))))

        def restored():
            check(app.interface_store.document == default_layout(), 'Default layout restored')
            check(app.recovery_bar.winfo_manager() == 'pack', 'Protected recovery controls')
            check(not painter.entries and painter.picture is None and painter.source is None, 'Background released')
            check(all(photo.width() == photo.height() == 1 for _, photo in painter.free), 'Retired background pixel buffers')
            check(not str(app.container.cget('style')).startswith('InterfaceImage'), 'Default native frame style')
            check(preparation_threads and all(ident != main_thread for ident in preparation_threads), 'Image preparation outside Tk')
            check(preparing[1] == 1, 'At most one background preparation at once')
            check(outcome['callback_errors'] == 0, 'No Tk callback errors')
            outcome.update(success=True, restored_defaults=True, background_off_tk_thread=True,
                           maximum_parallel_background_jobs=preparing[1], background_preparations=len(preparation_threads))
            finish()

        def resized():
            verify_pixels()
            widget = app.layout_runtime.widgets[custom_key]
            check(widget._layout_photo_size != first_resource_size, 'Resource follows resized layout')
            photo = widget._layout_photo
            check(photo.width() <= widget._layout_photo_size[0] and photo.height() <= widget._layout_photo_size[1], 'Resource fits resized control')
            check(abs(photo.width() / photo.height() - source.width / source.height) < .06, 'Resource aspect ratio')
            outcome.update(responsive_resource=True, resized_background_pixels=True)
            app.restore_interface_defaults()
            wait_for('restore', lambda: not painter._preparing and not painter._picture_pending
                     and not painter.entries and painter.picture is None, restored)

        def resource_loaded():
            nonlocal first_size, first_resource_size
            verify_pixels()
            outcome['layout_resource'] = True
            first_size = (root.winfo_width(), root.winfo_height())
            first_resource_size = app.layout_runtime.widgets[custom_key]._layout_photo_size
            # The window manager may apply only the final size; the application
            # must publish the latest geometry regardless of delivered events.
            for geometry in ('940x680', '860x620', '800x560'):
                root.geometry(geometry)
            wait_for('resize', lambda: (root.winfo_width(), root.winfo_height()) != first_size
                     and background_ready() and resource_ready(), resized)

        def background_loaded():
            nonlocal custom_key
            verify_pixels()
            outcome['general_background_pixels'] = True
            app.open_customization()
            app.layout_runtime.editor.close()
            resource = app.interface_store.import_resource(fixture)
            custom_key = app.layout_runtime.add('image', 'Preview', resource=resource, rect=[.1, .2, .25, .2])
            wait_for('layout_resource', lambda: background_ready() and resource_ready(), resource_loaded)

        def ready():
            check(app.preferences.path.is_relative_to(data), 'Isolated demo settings root')
            outcome['isolated_demo_data'] = True
            original = app.request_photo
            def request(path, size, callback, **options):
                def loaded(photo):
                    callback(photo)
                    if str(path) == str(fixture) and size == (320, 130):
                        outcome['settings_preview'] = photo is not None
                return original(path, size, loaded, **options)
            app.request_photo = request
            app.preferences.values['interface_background'] = str(fixture)
            painter.schedule()
            app.open_fixed_settings()
            wait_for('settings_preview', lambda: outcome.get('settings_preview') and background_ready(), background_loaded)

        wait_for('startup', lambda: app.stage == 'ready' and bool(app.chats) and not app.busy, ready)
        root.after(45000, lambda: finish(TimeoutError()))
        root.mainloop()
        app.worker.thread.join(timeout=2)
        outcome['closed_cleanly'] = app.closed and not app.worker.thread.is_alive()
        if not outcome['closed_cleanly']:
            outcome['success'] = False
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(outcome, indent=2), encoding='utf-8')
    print(json.dumps(outcome, indent=2))
    if not outcome['success']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
