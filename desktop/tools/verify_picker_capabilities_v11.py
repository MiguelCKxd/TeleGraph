"""Native picker action visibility with synthetic documents; no media/account IO."""
import argparse
import json
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from telethon import types as t

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tg_ascii.desktop import AsyncWorker
from tg_ascii.i18n import tr
from tg_ascii.sticker_picker import StickerGrid, open_picker, show_pack


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = {'success': False, 'synthetic_only': True, 'platform': sys.platform}
    errors, windows, grids = [], [], []
    root = tk.Tk(); root.title('Synthetic sticker permissions'); worker = AsyncWorker()
    root.report_callback_exception = lambda kind, error, trace: errors.append(str(error))
    root.tk.createcommand('bgerror', lambda message: errors.append('Tcl: '+str(message)))
    backend = NS(account_profile=NS(user_id=1, premium=False), sticker_packs=AsyncMock(return_value=[]),
                 sticker_documents=AsyncMock(return_value=[]), install_pack=AsyncMock())
    app = NS(root=root, worker=worker, busy=False, demo=False, ui_account='synthetic', active=42,
             chats=[NS(id=42, kind='user')], service=NS(backend=backend), preferences=NS(values={}),
             show_document_pack=Mock(), editor=Mock(), call=Mock())
    app.editor.tag_ranges.return_value = ()
    def dialog(title, size):
        window = tk.Toplevel(root); window.title(tr(title)); window.geometry(size); windows.append(window)
        frame = ttk.Frame(window); frame.pack(fill='both', expand=True); return window, frame
    app.dialog = dialog
    class Grid(StickerGrid):
        def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs); grids.append(self)
        def load(self, document): pass  # Explicitly no decoding/downloading in this UI contract test.
    paid = NS(id=9, attributes=[t.DocumentAttributeCustomEmoji('😀', t.InputStickerSetID(123, 456))])
    free = NS(id=10, attributes=[t.DocumentAttributeCustomEmoji('😀', t.InputStickerSetID(123, 456), free=True)])
    backend.document_pack = AsyncMock(return_value=NS(set=NS(title='Synthetic pack', emojis=True,
        installed_date=None, archived=False), documents=[paid, free]))
    def pump(condition, timeout=5):
        deadline = time.monotonic()+timeout
        while time.monotonic()<deadline:
            root.update()
            while not worker.events.empty():
                callback, value = worker.events.get_nowait(); callback(value)
            if errors: raise AssertionError(errors)
            if condition(): return
            time.sleep(.005)
        raise TimeoutError('Synthetic picker check timed out')
    def children(widget):
        found = []
        for child in widget.winfo_children(): found.append(child); found.extend(children(child))
        return found
    def button(window, label):
        return next(child for child in children(window) if isinstance(child, ttk.Button) and child.cget('text') == tr(label))
    began = time.monotonic()
    try:
        with patch('tg_ascii.sticker_picker.StickerGrid', Grid), patch('tg_ascii.sticker_picker.popup_menu') as menu:
            open_picker(app, True); window = windows[-1]; grid = grids[-1]
            pump(lambda: not worker.events.empty() or backend.sticker_packs.await_count == 1)
            use = button(window, 'Insert emoji')
            grid.activate(paid)
            assert use.winfo_manager() == ''
            assert [entry[0] for entry in menu.call_args.args[1]] == [tr('View pack')]
            grid.activate(free)
            assert use.winfo_manager() == 'pack'
            assert [entry[0] for entry in menu.call_args.args[1]] == [tr('Insert emoji'), tr('View pack')]
            result['paid_emoji_hidden_free_emoji_visible'] = True
            backend.account_profile.premium = True; grid.activate(paid); assert use.winfo_manager() == 'pack'
            backend.account_profile.premium = False; grid.activate(paid); assert use.winfo_manager() == ''
            result['premium_changes_without_rpc'] = True
            window.destroy(); app.active = 1; app.chats = [NS(id=1, kind='self')]
            open_picker(app, True); window = windows[-1]; grid = grids[-1]; grid.activate(paid)
            assert button(window, 'Insert emoji').winfo_manager() == 'pack'
            window.destroy(); result['saved_messages_exception'] = True
            # A reaction/profile/editor callback is a selector, not a chat send.
            app.active = None; chosen = Mock()
            open_picker(app, True, chosen); window = windows[-1]; grid = grids[-1]; grid.activate(paid)
            button(window, 'Insert emoji').invoke(); chosen.assert_called_once_with(paid)
            result['on_choose_callbacks_unchanged'] = True
            app.active = 42; app.chats = [NS(id=42, kind='channel', member=False)]
            open_picker(app); window = windows[-1]; grid = grids[-1]; grid.activate(NS(id=11, attributes=[]))
            assert button(window, 'Send sticker').winfo_manager() == ''
            assert [entry[0] for entry in menu.call_args.args[1]] == [tr('View pack')]
            window.destroy(); result['read_only_chat_keeps_pack_view_without_send'] = True
            before = len(grids); show_pack(app, paid); window = windows[-1]
            pump(lambda: len(grids)>before)
            grids[-1].activate(paid)
            assert button(window, 'Insert emoji').winfo_manager() == ''
            assert button(window, 'Save pack').winfo_manager() == 'pack'
            result['save_pack_available_without_message_permission'] = True
            window.destroy(); result['success'] = True
    except Exception as error:  # noqa: BLE001 - native QA reports failure and exits nonzero
        result['error'] = repr(error)
    finally:
        for window in windows:
            if window.winfo_exists(): window.destroy()
        worker.stop(); worker.thread.join(timeout=4); root.update(); root.destroy()
        result.update(callback_errors=errors, worker_closed=not worker.thread.is_alive(), seconds=round(time.monotonic()-began, 3))
        if errors or not result['worker_closed']: result['success'] = False
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['success'] else 1


if __name__ == '__main__': raise SystemExit(main())
