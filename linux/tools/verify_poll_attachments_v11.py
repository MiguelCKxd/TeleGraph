"""Exercise the real poll editor with synthetic uploads; no accounts or network."""
import argparse
import asyncio
import json
import sys
import tempfile
import threading
import time
import tkinter as tk
from datetime import UTC, datetime
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from telethon import types as t

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tg_ascii.advanced_editor import EntityField
from tg_ascii.backend import Chat
from tg_ascii.desktop import AsyncWorker
from tg_ascii.desktop_advanced import AdvancedDialog, DesktopAdvancedMixin
from tg_ascii.i18n import tr


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = {'success': False, 'synthetic_only': True, 'platform': sys.platform}
    errors, created, calls = [], [], []
    started, cancelled = threading.Event(), threading.Event()
    stall = [True]
    root = tk.Tk(); root.title('Synthetic poll verification'); root.geometry('740x820')
    root.report_callback_exception = lambda kind, error, trace: errors.append(str(error))
    root.tk.createcommand('bgerror', lambda message: errors.append('Tcl: '+str(message)))
    worker = AsyncWorker()
    app = DesktopAdvancedMixin()
    app.root, app.worker = root, worker
    app.ui_account, app.active = 'synthetic', -77
    app.chats = [Chat(-77, 'Synthetic group', kind='group', member=True)]
    app.demo = app.busy = app.closing = app.closed = False
    app.preferences = NS(values={'advanced_features': {'polls': True}})
    app.reply_drafts, app.messages = {}, []
    app.account_event = Mock()
    async def prepare(peer, question, answers, files, progress, **options):
        calls.append((peer, question, answers, files, options))
        started.set(); progress('synthetic.png', 1, 10)
        if stall[0]:
            try: await asyncio.Event().wait()
            except asyncio.CancelledError: cancelled.set(); raise
        return {key: t.InputMediaPhoto(t.InputPhoto(123, 456, b'synthetic')) for key in files}
    backend = NS(prepare_poll_attachments=AsyncMock(side_effect=prepare), send_poll=AsyncMock(return_value=None))
    backend._capability_entities = {-77: t.Chat(77, 'Synthetic group', t.ChatPhotoEmpty(), 2, datetime.now(UTC), 1)}
    app.service = NS(backend=backend)
    def make_window(title, size):
        window = tk.Toplevel(root); window.title(tr(title)); window.geometry(size)
        frame = ttk.Frame(window); frame.pack(fill='both', expand=True)
        return window, frame
    app.dialog = make_window
    def field(parent, label):
        ttk.Label(parent, text=tr(label)).pack()
        entry = ttk.Entry(parent); entry.pack(fill='x'); return entry
    app.field = field
    def call(coroutine, done, status, failed):
        app.busy = True
        def success(value): app.busy = False; done(value)
        def failure(error): app.busy = False; failed(error)
        return worker.submit(coroutine, success, failure)
    app.call = call
    def capture(*args, **kwargs):
        dialog = AdvancedDialog(*args, **kwargs); created.append(dialog); return dialog
    def pump(condition, timeout=5):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            root.update()
            while not worker.events.empty():
                callback, value = worker.events.get_nowait(); callback(value)
            if errors: raise AssertionError(errors)
            if condition(): return
            time.sleep(.005)
        raise TimeoutError('Synthetic poll editor timed out')
    def children(widget):
        result = []
        for child in widget.winfo_children(): result.append(child); result.extend(children(child))
        return result
    def new(quiz=False):
        with patch('tg_ascii.desktop_advanced.AdvancedDialog', side_effect=capture):
            app.new_poll_dialog(reply_to=99, quiz_mode=quiz)
        dialog = created[-1]; editor = dialog.poll_attachments
        fields = [widget for widget in children(dialog.body) if isinstance(widget, EntityField)]
        for field, value in zip(fields, ('Question', 'First', 'Second', 'Explanation' if quiz else '')):
            field.set(value)
        if quiz:
            first = next(widget for widget in children(dialog.body)
                         if isinstance(widget, ttk.Checkbutton) and widget.cget('text') == '1')
            first.invoke()
        submit = next(widget for widget in children(dialog.body)
                      if isinstance(widget, ttk.Button) and widget.cget('text') == tr('Send poll'))
        return dialog, editor, fields, submit
    began = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix='tg-poll-native-') as temporary:
            path = Path(temporary)/'synthetic.png'; path.write_bytes(b'synthetic upload stand-in')
            dialog, editor, fields, submit = new()
            pump(lambda: dialog.window.winfo_ismapped())
            backend.prepare_poll_attachments.assert_not_awaited()
            with patch('tg_ascii.poll_attachment_editor.filedialog.askopenfilename', return_value=str(path)):
                editor.choose('attached_media')
            assert editor.labels['attached_media'].cget('text') == path.name
            backend.prepare_poll_attachments.assert_not_awaited()
            editor.remove('attached_media'); assert not editor.paths
            with patch('tg_ascii.poll_attachment_editor.filedialog.askopenfilename', return_value=str(path)):
                editor.choose('attached_media')
            result['open_select_remove_zero_network'] = True
            submit.invoke(); pump(started.is_set)
            assert all(field.editor.cget('state') == 'disabled' for field in fields)
            assert editor.cancel_button.instate(['!disabled']) and editor.scope_timer is not None
            editor.cancel_button.invoke(); pump(cancelled.is_set)
            assert not editor.pending and editor.scope_timer is None
            assert all(field.editor.cget('state') == 'normal' for field in fields)
            backend.send_poll.assert_not_awaited()
            assert not dialog.requests.jobs
            result['cancel_upload_restores_controls_and_never_sends'] = True
            # A subsequent operation receives its own ownership generation.
            started.clear(); cancelled.clear(); submit.invoke(); pump(started.is_set)
            app.active = -88; pump(cancelled.is_set)
            assert not editor.pending and not dialog.requests.jobs
            backend.send_poll.assert_not_awaited()
            result['chat_change_cancels_upload'] = True
            app.active = -77; started.clear(); cancelled.clear(); submit.invoke(); pump(started.is_set)
            app.ui_account = 'another-synthetic'; pump(cancelled.is_set)
            backend.send_poll.assert_not_awaited()
            result['account_change_cancels_upload'] = True
            app.ui_account = 'synthetic'
            dialog.window.destroy(); pump(lambda: dialog.requests.closed)
            # A modal chooser is also invalidated by an account switch.
            dialog, editor, fields, submit = new(quiz=True)
            def changed(**kwargs): app.ui_account = 'another-synthetic'; return str(path)
            with patch('tg_ascii.poll_attachment_editor.filedialog.askopenfilename', side_effect=changed):
                editor.choose('attached_media')
            assert not editor.paths
            app.ui_account = 'synthetic'
            with patch('tg_ascii.poll_attachment_editor.filedialog.askopenfilename', return_value=str(path)):
                editor.choose('attached_media'); editor.choose('solution_media')
            started.clear(); cancelled.clear(); submit.invoke(); pump(started.is_set)
            dialog.window.destroy(); pump(cancelled.is_set)
            assert editor.scope_timer is None and not dialog.requests.jobs
            backend.send_poll.assert_not_awaited()
            result['close_cancels_and_releases_callbacks'] = True
            stall[0] = False
            dialog, editor, fields, submit = new(quiz=True)
            with patch('tg_ascii.poll_attachment_editor.filedialog.askopenfilename', return_value=str(path)):
                editor.choose('attached_media'); editor.choose('solution_media')
            submit.invoke(); pump(lambda: not dialog.window.winfo_exists())
            backend.send_poll.assert_awaited_once()
            sent = backend.send_poll.await_args
            assert sent.args[0] == -77 and sent.kwargs['reply_to'] == 99 and sent.kwargs['quiz']
            assert sent.kwargs['correct'] == [0]
            assert sent.kwargs['attached_media'] is not None and sent.kwargs['solution_media'] is not None
            assert sent.kwargs['solution'].text == 'Explanation'
            assert editor.scope_timer is None and not dialog.requests.jobs
            result['successful_quiz_preserves_media_text_reply_and_correct_answers'] = True
            result['success'] = True
    except Exception as error:  # noqa: BLE001 - native QA records failure and exits nonzero
        result['error'] = repr(error)
    finally:
        for dialog in created:
            if dialog.window.winfo_exists(): dialog.window.destroy()
        worker.stop(); worker.thread.join(timeout=4)
        root.update(); root.destroy()
        result.update(callback_errors=errors, worker_closed=not worker.thread.is_alive(), seconds=round(time.monotonic()-began, 3))
        if errors or not result['worker_closed']: result['success'] = False
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['success'] else 1


if __name__ == '__main__': raise SystemExit(main())
