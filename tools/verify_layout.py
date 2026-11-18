"""Native editor smoke test with temporary demo data; no Telegram connection."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
import traceback
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tg_ascii.desktop import Desktop
from tg_ascii.interface_store import default_layout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = tk.Tk()
    root.geometry('1100x780')
    app = Desktop(root, demo=True)
    outcome = {'success': False, 'platform': sys.platform}
    errors = []
    root.report_callback_exception = lambda kind, error, trace: errors.append(repr(error))

    def finish(error=None):
        if error is not None:
            outcome['error'] = repr(error)
            outcome['traceback'] = traceback.format_exc()
        runtime = app.layout_runtime
        if runtime.editor is not None:
            runtime.editor.close()
        app.close()

    def prepared():
        if not app.chats or app.busy:
            root.after(30, prepared)
            return
        try:
            runtime, store = app.layout_runtime, app.interface_store
            assert not store.document['enabled']
            assert not runtime._bindings and not runtime._image_jobs
            app.open_customization()
            root.update_idletasks()
            editor = runtime.editor
            assert runtime.editing and len(runtime._bindings) == 3
            assert not hasattr(editor, 'profiles') and not hasattr(editor, 'file_list')
            notebook = next(widget for widget in editor.window.winfo_children() if isinstance(widget, ttk.Notebook))
            notebook.select(1)
            root.update()
            assert hasattr(editor, 'profiles') and not hasattr(editor, 'file_list')
            notebook.select(2)
            root.update()
            assert hasattr(editor, 'file_list')
            notebook.select(0)
            root.update()
            protected = app.recovery_bar
            assert protected not in runtime.widgets.values()
            first_key = runtime.add('panel', 'My panel', entries=[
                {'text': 'Send', 'action': 'send'}, {'text': 'Attach', 'action': 'attach'}],
                rect=[.35, .1, .4, .25])
            root.update_idletasks()
            child_key = first_key+'/0'
            assert child_key in runtime.widgets and first_key+'/1' in runtime.widgets
            child = runtime.widgets[child_key]
            child.event_generate('<ButtonPress-1>', x=5, y=5)
            child.event_generate('<B1-Motion>', x=30, y=10)
            child.event_generate('<ButtonRelease-1>', x=30, y=10)
            root.update()
            assert runtime.selected == child_key
            assert child_key in store.document['overrides']
            assert runtime.widgets[child_key].winfo_manager() == 'place'
            runtime.move(child_key, [.1, .1, .45, .35])
            root.update_idletasks()
            with patch('tg_ascii.interface_editor.simpledialog.askstring', return_value='Renamed'):
                editor.rename()
            root.update_idletasks()
            assert str(runtime.widgets[child_key].cget('text')) == 'Renamed'
            editor.to_front()
            duplicate_key = runtime.duplicate(child_key)
            root.update_idletasks()
            assert store.document['items'][-1]['action'] == 'widget:'+child_key
            runtime.hide(child_key)
            root.update_idletasks()
            assert runtime.widgets[child_key].winfo_manager() == ''
            runtime.widgets[child_key].pack(fill='x')
            assert runtime.widgets[child_key].winfo_manager() == ''
            editor.restore_hidden()
            root.update_idletasks()
            assert runtime.widgets[child_key].winfo_manager() == 'place'
            runtime.selected = child_key
            runtime.tile(2)
            root.update_idletasks()
            assert store.document['overrides'][child_key]['rect'] == [0, 0, .5, 1]
            width = runtime.widgets[child_key].winfo_width()
            parent_width = runtime.widgets[first_key].winfo_width()
            root.deiconify()
            root.geometry('800x600')
            # Windows delivers window-manager geometry changes asynchronously.
            resized = tk.BooleanVar(value=False)
            root.after(200, lambda: resized.set(True))
            root.wait_variable(resized)
            root.update_idletasks()
            new_width = runtime.widgets[child_key].winfo_width()
            new_parent_width = runtime.widgets[first_key].winfo_width()
            assert new_width < width and new_parent_width < parent_width, (width, new_width, parent_width, new_parent_width, root.geometry(), root.state(), root.maxsize(), root.winfo_screenwidth(), root.resizable())
            assert abs(new_width / new_parent_width - .5) < .04
            assert app.recovery_bar.winfo_manager() == 'pack'
            editor.close()
            with patch.object(app, 'send') as send:
                runtime.widgets[duplicate_key].invoke()
                send.assert_called_once()
            for _ in range(4):
                app.open_customization()
                root.update()
                runtime.editor.select(child_key)
                root.update()
                runtime.editor.close()
                root.update()
            assert not runtime._bindings
            assert not root.tk.call('info', 'commands', '*LayoutEditor*')
            # Keep the protected recovery action available even when all editable
            # root controls have been hidden and the rest of the layout overlaps.
            document = deepcopy(store.document)
            for key in ('accounts', 'sidebar', 'conversation', 'stories'):
                document['overrides'][key] = {'hidden': True}
            runtime.change(document)
            root.update_idletasks()
            assert app.recovery_bar.winfo_manager() == 'pack'
            app.restore_interface_defaults()
            root.update_idletasks()
            assert store.document == default_layout()
            assert app.chat_sidebar.winfo_manager()
            assert app.chat_conversation.winfo_manager()
            assert not runtime._bindings
            assert not errors, errors
            outcome.update(success=True, nested_controls=True, drag=True, responsive=True,
                           duplicate_actions=True, protected_recovery=True, callback_errors=errors)
            finish()
        except Exception as error:
            finish(error)

    root.after(30, prepared)
    root.after(20000, lambda: finish(TimeoutError('Layout smoke test timed out')) if not outcome['success'] else None)
    root.mainloop()
    if args.output:
        args.output.write_text(json.dumps(outcome, indent=2), encoding='utf-8')
    else:
        print(json.dumps(outcome, indent=2))
    if not outcome['success']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
