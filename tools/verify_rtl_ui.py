"""Native Tk demo only: direction, resize, composer/clipboard integrity and leaks."""
import json
import os
from pathlib import Path
import tempfile
import time
import tkinter as tk


def main():
    with tempfile.TemporaryDirectory() as directory:
        os.environ['TG_ASCII_DATA_DIR'] = directory
        from tg_ascii import i18n
        from tg_ascii.backend import Chat, Message
        from tg_ascii.desktop import Desktop
        from tg_ascii.rtl_ui import TEXT_TAG
        root = tk.Tk()
        app = Desktop(root, demo=True)
        failures = []
        root.report_callback_exception = lambda kind, exc, trace: failures.append(repr(exc))
        app.show_error = lambda exc: failures.append(repr(exc))
        deadline = time.monotonic() + 8
        while (not app.chats or app.busy) and time.monotonic() < deadline:
            root.update()
            time.sleep(.005)
        assert app.chats and not app.busy
        report = []
        sample = 'مرحبا Hello 123 😀\nשלום · https://example.org/a?b=2'
        for code in ('ar', 'ur', 'he', 'es'):
            # This permits testing layout while a catalogue is being assembled.
            # It changes no application file or saved preference.
            i18n.LANGUAGES.setdefault(code, code)
            i18n.set_language(code)
            app.preferences.values['language'] = code
            app.preferences.values['bubbles'] = False
            app.rebuild_screen()
            app.active = 1
            app.chats = [Chat(1, 'Alice أليس', unread=2)]
            app.messages = [Message(1, 'Alice أليس', sample, '12:00', sender_id=20)]
            app.render_chats()
            app.render_messages(False)
            app.editor.delete('1.0', 'end')
            app.editor.insert('1.0', sample)
            root.geometry('1040x720')
            root.update()
            app.adapt_chat_layout()
            root.update()
            assert app.editor.get('1.0', 'end-1c') == sample, code
            assert sample in app.history.get('1.0', 'end-1c'), code
            rtl = code != 'es'
            assert (app.history.tag_cget(TEXT_TAG, 'justify') == 'right') if rtl else True
            panes = list(map(str, app.chat_panes.panes()))
            assert panes[-1 if rtl else 0] == str(app.chat_sidebar), (code, panes)
            app.editor.tag_add('sel', '1.0', 'end-1c')
            app.editor.copy()
            assert root.clipboard_get() == sample, code
            app.editor.tag_remove('sel', '1.0', 'end')
            root.geometry('620x480')
            root.update()
            app.adapt_chat_layout()
            root.update()
            assert len(app.chat_panes.panes()) == 1, code
            report.append({'language': code, 'mirrored_default_panes': rtl,
                           'font': app.font_family, 'content_and_clipboard_unchanged': True,
                           'compact_view': True})
        app.editor.delete('1.0', 'end')
        app.close()
        deadline = time.monotonic() + 8
        while not app.closed and time.monotonic() < deadline:
            root.update()
            time.sleep(.005)
        app.worker.thread.join(timeout=2)
        result = {'passed': not failures and not app.worker.thread.is_alive(),
                  'local_demo_only': True, 'languages': report, 'callback_errors': failures}
        output = Path('validation/rtl-ui-verification.json')
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + '\n', 'utf-8')
        print(json.dumps(result, indent=2))
        assert result['passed']


if __name__ == '__main__':
    main()
