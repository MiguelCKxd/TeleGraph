"""Local native-Tk smoke check; demo data only, no Telegram credentials/network."""
import argparse
import json
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tg_ascii.desktop import Desktop
from tg_ascii.interface_windows import open_chat_window


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = tk.Tk()
    root.withdraw()
    app = Desktop(root, demo=True)
    outcome = {'success': False, 'platform': sys.platform}
    windows = []
    def fail(error):
        outcome['error'] = repr(error)
        app.busy = False  # A demo watchdog must never open a confirmation dialog.
        app.close()
    root.report_callback_exception = lambda kind, error, trace: fail(error)
    def prepared():
        if not app.chats or app.busy:
            root.after(30, prepared)
            return
        try:
            app.active = app.chats[0].id
            app.messages = list(app.service.backend.messages[app.active])
            app.editor.insert('1.0', 'main draft')
            main_text = app.editor.get('1.0', 'end-1c')
            first, second = open_chat_window(app), open_chat_window(app)
            windows.extend((first, second))
            root.update_idletasks()
            assert first.backend is second.backend is app.service.backend
            assert first.draft_account != second.draft_account
            first.editor.delete('1.0', 'end')
            first.editor.insert('1.0', 'Bold 😀 ')
            first.editor.insert_custom(12345, '👨‍👩‍👧', 'end-1c')
            first.editor.tag_add('sel', '1.0', '1.4')
            first.apply_format('bold')
            assert first.editor.get('1.0', 'end-1c') == 'Bold 😀 👨‍👩‍👧'
            assert first.snapshot_custom()[0][2] == 12345
            assert first.snapshot_formats()[0][:3] == (0, 4, 'bold')
            first.persist_draft(capture_only=True)
            assert app.editor.get('1.0', 'end-1c') == main_text
            # Native element/photo counts must plateau across theme changes.
            probe = ttk.Button(root, text='Geometry test')
            before = probe.winfo_reqheight()
            app.preferences.save({'button_radius': 8})
            app.configure_style()
            root.update_idletasks()
            assert probe.winfo_reqheight() <= before + 4
            app.preferences.save({'button_radius': 8, 'menu_radius': 8,
                'button_border_width': 2, 'menu_border_width': 2,
                'button_shadow_size': 3, 'text_border_width': 1})
            app.configure_style()
            count = len(ttk.Style(root).element_names())
            for index in range(8):
                app.preferences.save({'button_radius': index + 1, 'theme': 'light' if index % 2 else 'dark'})
                app.configure_style()
            assert len(ttk.Style(root).element_names()) == count
            assert len(root._shape_images) < 20
            probe.destroy()
            root.update_idletasks()
            first.send()
            def sent():
                if first.busy:
                    root.after(30, sent)
                    return
                try:
                    assert first.editor.get('1.0', 'end-1c') == ''
                    assert first.messages[-1].text == 'Bold 😀 👨‍👩‍👧'
                    assert second.messages[-1].text == first.messages[-1].text
                    first.close()
                    assert not second.closed
                    assert app.service.backend is second.backend
                    second.close()
                    assert not app._chat_windows
                    outcome.update(success=True, linked_windows=2, native_styles=count,
                                   shape_photos=len(root._shape_images), custom_emoji=True, drafts=True)
                    app.close()
                except Exception as error:
                    fail(error)
            root.after(30, sent)
        except Exception as error:
            fail(error)
    root.after(30, prepared)
    root.after(15000, lambda: fail(TimeoutError('Native window smoke test timed out')) if not outcome['success'] else None)
    root.mainloop()
    if args.output:
        args.output.write_text(json.dumps(outcome, indent=2), encoding='utf-8')
    else:
        print(json.dumps(outcome, indent=2))
    if not outcome['success']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
