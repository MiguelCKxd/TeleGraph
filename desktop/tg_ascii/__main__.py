"""Default entry point: standalone desktop application."""
import argparse
import json
import os
from pathlib import Path
import sys

from . import APP_NAME, __version__
from .i18n import detect_language, set_language


def main():
    from .linux_runtime import prepare as prepare_linux
    prepare_linux()  # 1.5.5: system typelibs for the tray icon (Linux only).
    if len(sys.argv) > 1 and sys.argv[1] == '--group-calls-worker':
        from .calls_group_worker import main as group_worker
        group_worker()
        return
    if len(sys.argv) > 1 and sys.argv[1] == '--calls-worker':
        from .calls_worker import main as media_worker
        media_worker()
        return
    parser = argparse.ArgumentParser(description=f'{APP_NAME} Desktop')
    parser.add_argument('--demo', action='store_true', help='Demo local sin cuenta ni conexion')
    parser.add_argument('--configure', action='store_true', help='Reconfigurar claves de desarrollador')
    parser.add_argument('--data-dir', type=Path, help='Carpeta independiente para sesiones, ajustes y diseños')
    parser.add_argument('--version', action='store_true')
    parser.add_argument('--language', choices=list(__import__('tg_ascii.i18n', fromlist=['LANGUAGES']).LANGUAGES))
    parser.add_argument('--apply-update', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--self-test', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.data_dir:
        os.environ['TG_ASCII_DATA_DIR'] = str(args.data_dir.expanduser().resolve())
    if args.apply_update:
        from .updater import apply_update
        apply_update(args.apply_update)
        return
    if args.version:
        if sys.stdout is not None:
            print(f'{APP_NAME} {__version__}')
        return
    from .preferences import Preferences
    preferences = Preferences(demo=args.demo or bool(args.self_test))
    set_language(args.language or preferences.values['language'] or detect_language())
    os.umask(0o077)
    if args.self_test:
        import tkinter as tk
        from .desktop import Desktop
        args.self_test.unlink(missing_ok=True)
        root = tk.Tk()
        root.withdraw()
        app = Desktop(root, demo=True)
        def check():
            if app.chats and not app.busy:
                from .translations_extra import load_catalogues
                assert len(load_catalogues()) == 10
                import qrcode
                assert qrcode.make('tg-ascii-packaging-check').size
                from PIL import Image, ImageTk
                sample = Image.new('RGB', (2, 2), '#8cf5a6')
                ImageTk.PhotoImage(sample, master=root)
                from .app_dialogs import CheckList
                checks = CheckList(root)
                checks.insert('end', 'One', 'Two')
                checks.toggle(0); checks.toggle(1)
                assert checks.curselection() == (0, 1)
                checks.destroy()
                app.preferences.save({'theme': 'light'})
                app.rebuild_screen()
                root.update_idletasks()
                assert root.cget('background') == '#f4f8f3'
                app.preferences.save({'theme': 'dark'})
                app.rebuild_screen()
                assert app.logo_image is not None
                app.preferences.save({'bubbles': True})
                app.rebuild_screen()
                root.update_idletasks()
                assert app.bubble_view.winfo_exists()
                assert app.bubble_view.messages == app.messages
                app.preferences.save({'bubbles': False})
                app.rebuild_screen()
                from .audio_engine import libraries
                _, sf = libraries()
                assert sf.check_format('OGG', 'OPUS')
                import tempfile
                with tempfile.TemporaryDirectory(prefix='tg-as-codec-test-') as folder:
                    target = Path(folder) / 'silent.ogg'
                    with sf.SoundFile(str(target), mode='w', samplerate=48000, channels=1, format='OGG', subtype='OPUS') as output:
                        output.buffer_write(bytes(48000), dtype='int16')
                    with sf.SoundFile(str(target)) as source:
                        assert source.frames > 0
                app.editor.insert('1.0', 'Bold 😀')
                app.editor.tag_add('sel', '1.0', '1.4')
                app.apply_format('bold')
                assert app.snapshot_formats()[0][:3] == (0, 4, 'bold')
                from .calls_native import engine_available
                args.self_test.write_text(json.dumps({'version': __version__, 'gui': True, 'demo_chats': len(app.chats), 'drag_drop': app.drop_available, 'audio_codec': True, 'calls_available': engine_available()}), encoding='utf-8')
                app.close()
            else:
                root.after(50, check)
        root.after(50, check)
        def timed_out():
            app.busy = False  # Demo-only watchdog; never wait for a modal prompt.
            app.close()
        root.after(10000, timed_out)
        root.mainloop()
        if not args.self_test.exists():
            raise SystemExit(1)
        return
    from .desktop import run_desktop
    run_desktop(args.demo, args.configure)


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()  # process_decoding: decoder processes in the packaged app.
    main()
