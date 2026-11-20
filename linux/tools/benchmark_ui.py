"""Local deterministic Tk workload. Uses demo data, never Telegram sessions."""
import json
from pathlib import Path
import statistics
import sys
import time
import tkinter as tk

sys.path.insert(0, sys.argv[1])
from tg_ascii.backend import Chat, Message
from tg_ascii.desktop import Desktop

root = tk.Tk()
root.withdraw()
app = Desktop(root, demo=True)
failures = []
root.report_callback_exception = lambda kind, exc, trace: failures.append(repr(exc))
app.show_error = lambda exc: failures.append(repr(exc))
deadline = time.monotonic() + 10
while (not app.chats or app.busy) and time.monotonic() < deadline:
    root.update()
    time.sleep(.005)
if not app.chats or app.busy:
    raise RuntimeError('Demo failed to start')
app.preferences.values.update(bubbles=False, animated_emoji=False, inline_media=False)
app.active = 1
app.chats = [Chat(i, f'Chat {i}', unread=i % 3) for i in range(1, 1001)]
app.messages = [Message(i, 'Fixture', f'Message {i}: https://example.com/item/{i}',
                        '12:00', sender_id=20) for i in range(1, 101)]
app.render_chats()
app.render_messages(False)
root.update_idletasks()
commands_before = len(app.history._tclCommands or [])
render_samples = []
for _ in range(40):
    started = time.perf_counter()
    app.render_messages(False)
    render_samples.append(time.perf_counter() - started)
commands_after = len(app.history._tclCommands or [])
chat_samples = []
for _ in range(100):
    app.chats[500].unread += 1
    started = time.perf_counter()
    app.render_chats()
    chat_samples.append(time.perf_counter() - started)
report = {
    'chat_count': len(app.chats), 'message_count': len(app.messages),
    'history_redraws': 40, 'history_tcl_commands_before': commands_before,
    'history_tcl_commands_after': commands_after,
    'history_tcl_command_growth': commands_after - commands_before,
    'history_render_median_ms': round(statistics.median(render_samples)*1000, 3),
    'chat_refreshes': 100, 'chat_refresh_median_ms': round(statistics.median(chat_samples)*1000, 3),
    'callback_errors': failures,
}
app.close()
deadline = time.monotonic() + 10
while not app.closed and time.monotonic() < deadline:
    root.update()
    time.sleep(.005)
app.worker.thread.join(timeout=3)
report['worker_stopped'] = not app.worker.thread.is_alive()
Path(sys.argv[2]).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report))
