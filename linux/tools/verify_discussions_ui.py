"""Real Tk thread window with synthetic server pages; no account or network."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import tkinter as tk
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tg_ascii.accounts import Accounts
from tg_ascii.backend import Message
from tg_ascii.desktop import Desktop
from tg_ascii.interface_windows import LinkedChatWindow
from tg_ascii.peer_tools import HistoryPage
from verify_calls_ui import pump


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = dict(success=False, synthetic_only=True, checks=[], errors=[])
    previous = os.environ.get('TG_ASCII_DATA_DIR')
    root = app = None
    with tempfile.TemporaryDirectory(prefix='tg-discussion-ui-') as directory:
        os.environ['TG_ASCII_DATA_DIR'] = directory
        try:
            root = tk.Tk()
            app = Desktop(root, demo=True, service=Accounts(demo=True, root=Path(directory)))
            root.report_callback_exception = lambda kind, error, trace: result['errors'].append(repr(error))
            app.show_error = lambda error: result['errors'].append(repr(error))
            pump(root, lambda: app.chats and not app.busy, result['errors'])
            account, peer = app.ui_account, -1000000000041
            backend = app.service.backend
            backend.discussion_history = AsyncMock(side_effect=[
                HistoryPage([Message(110, 'Commenter', 'First comment', '', reply_to_id=99)], next_offset=110, more=True),
                HistoryPage([Message(105, 'Earlier', 'Earlier comment', '', reply_to_id=99)], next_offset=105, more=False)])
            backend.history = AsyncMock(side_effect=AssertionError('Unfiltered group history requested'))
            backend.send_formatted = AsyncMock(return_value=Message(120, 'Me', 'Reply', '', outgoing=True, thread_id=99))
            backend.read_discussion = AsyncMock()
            thread = dict(root_id=99, root=Message(99, 'Channel', 'Channel post', ''))
            window = LinkedChatWindow(app, account, peer, thread=thread)
            app._chat_windows = [window]
            pump(root, lambda: not window.loading and len(window.messages) == 2, result['errors'])
            assert [m.id for m in window.messages] == [99, 110]
            window.older_comments()
            pump(root, lambda: not window.loading and len(window.messages) == 3, result['errors'])
            assert [m.id for m in window.messages] == [99, 105, 110]
            result['checks'].append('thread pages render in chronological order without unfiltered group history')
            window.receive(account, peer, Message(121, 'Other thread', 'Hidden', '', thread_id=88))
            window.receive(account, peer, Message(122, 'Nested reply', 'Visible', '', thread_id=99))
            assert [m.id for m in window.messages] == [99, 105, 110, 122]
            result['checks'].append('live unrelated messages stay outside the thread')
            window.editor.insert('1.0', 'Reply')
            app.demo = False
            try:
                window.send()
            finally:
                app.demo = True
            pump(root, lambda: not window.busy, result['errors'])
            call = backend.send_formatted.call_args
            assert call.args[:2] == (peer, 'Reply') and call.kwargs['reply_to'] == 99
            result['checks'].append('send targets the discussion group and forwarded post root')
            window.editor.insert('1.0', 'Retained local comment draft')
            window.persist_draft(capture_only=True)
            assert window.draft_store.get(window.draft_account, peer)['text'] == 'Retained local comment draft'
            assert window.draft_account.startswith('thread:' + account + ':99')
            window.close()
            pump(root, lambda: window.closed, result['errors'])
            result['checks'].append('thread draft is retained separately and close releases the window')
            result['success'] = True
        finally:
            if app is not None and not app.closed:
                app.close()
                pump(root, lambda: app.closed, result['errors'])
            if previous is None:
                os.environ.pop('TG_ASCII_DATA_DIR', None)
            else:
                os.environ['TG_ASCII_DATA_DIR'] = previous
            text = json.dumps(result, indent=2)
            if args.output:
                args.output.write_text(text + '\n', encoding='utf-8')
            print(text)


if __name__ == '__main__':
    main()
