"""1.5.3 offline E2E with a temporary copy of the QA account session.
Usage: e2e153.py DATA PHASE   (PHASE: online | offline | back)"""
import json, os, sqlite3, sys, time, tkinter as tk
sys.path.insert(0, os.getcwd())
DATA, PHASE = sys.argv[1], sys.argv[2]
KEY = sys.argv[3]
QA_CHANNEL = -1004379610053
os.environ['TG_ASCII_DATA_DIR'] = DATA
from tg_ascii.desktop import Desktop
root = tk.Tk(); root.geometry('1000x700+60+60')
app = Desktop(root, demo=False)
out = {'phase': PHASE}
t0 = time.monotonic()
def log(k, v): out[k] = v
def finish():
    out['status_end'] = app.status.get()
    print('RESULT ' + json.dumps(out, default=str)); sys.stdout.flush()
    app._parent_close = True
    app.close()
    root.after(4000, lambda: os._exit(0))
def wait(cond, then, limit, name):
    start = time.monotonic()
    def tick():
        try: ok = cond()
        except Exception as e: ok = False
        if ok: log(name, round(time.monotonic() - start, 2)); then(); return
        if time.monotonic() - start > limit: log(name, 'TIMEOUT'); finish(); return
        root.after(200, tick)
    tick()
def ready(): return getattr(app, 'stage', None) == 'ready' and hasattr(app, 'chat_list')
def pending_count():
    from tg_ascii.pending_actions import queue_for
    q = queue_for(app); return len(q.records) if q else -1
def chat(peer): return next((c for c in app.chats if c.id == peer), None)

if PHASE == 'online':
    def opened():
        app.chat_list.selection_set(str(QA_CHANNEL)); app.chat_list.see(str(QA_CHANNEL))
        wait(lambda: app.active == QA_CHANNEL and len(app.messages) > 0 and app._history_key is None, finish, 30, 'history_loaded')
    wait(lambda: ready() and getattr(app, '_chats_from_network', False) and chat(QA_CHANNEL) is not None, opened, 60, 'chats_from_network')
elif PHASE == 'offline':
    def act():
        log('startup_seconds', round(time.monotonic() - t0, 1))
        log('chats_shown', len(app.chats)); log('status_ready', app.status.get())
        log('offline_flag', app.connection_offline())
        c = chat(QA_CHANNEL); log('pinned_before', c.pinned if c else None)
        results = []
        app.call(app.service.backend.pin(QA_CHANNEL, not c.pinned), lambda v: results.append(type(v).__name__), 'Saving...')
        app.call(app.service.backend.mute_chat(QA_CHANNEL, not c.muted), lambda v: results.append(type(v).__name__), 'Saving...')
        def check():
            log('results', results); log('pending', pending_count())
            log('local_pinned', chat(QA_CHANNEL).pinned); log('local_muted', chat(QA_CHANNEL).muted)
            log('indicator', app.pending_button.cget('text') if app.pending_button.winfo_ismapped() else None)
            log('status_after', app.status.get())
            # Open the QA channel offline: messages from the local copy.
            app.chat_list.selection_set(str(QA_CHANNEL))
            def opened():
                log('offline_messages', len(app.messages))
                root.update(); x, y = root.winfo_rootx(), root.winfo_rooty()
                import subprocess
                subprocess.run(['screencapture', '-x', '-R', f'{x},{y},{root.winfo_width()},{root.winfo_height()}', sys.argv[4]])
                finish()
            root.after(2500, opened)
        root.after(1500, check)
    wait(lambda: ready() and len(app.chats) > 0, act, 40, 'ready_with_copy')
elif PHASE == 'back':
    def verify():
        c = chat(QA_CHANNEL); log('pinned_now', c.pinned if c else None); log('muted_now', c.muted if c else None)
        log('pending_file', os.path.exists(os.path.join(DATA, 'pending-actions', KEY + '.json')))
        # Put the QA channel back as it was (online, direct).
        restored = []
        app.call(app.service.backend.pin(QA_CHANNEL, not c.pinned), lambda v: restored.append(type(v).__name__), 'x')
        app.call(app.service.backend.mute_chat(QA_CHANNEL, not c.muted), lambda v: restored.append(type(v).__name__), 'x')
        def done():
            log('restored', restored); finish()
        root.after(5000, done)
    wait(lambda: ready() and pending_count() == 0 and getattr(app, '_chats_from_network', False) and app.status.get() != '', lambda: root.after(4000, verify), 60, 'flushed')
if PHASE == 'live':
    # A local proxy stands for the network: unplugged at start, plugged in
    # later. The session points at it the whole time (same address, as in a
    # real outage). argv[4] = "real_host:real_port", argv[5] = proxy port.
    import asyncio, threading
    real_host, real_port = sys.argv[4].rsplit(':', 1)
    proxy_port = int(sys.argv[5])
    proxy = {'server': None, 'loop': asyncio.new_event_loop()}
    threading.Thread(target=proxy['loop'].run_forever, daemon=True).start()
    async def pipe(reader, writer):
        try:
            while data := await reader.read(65536):
                writer.write(data); await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()
    async def handle(reader, writer):
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(real_host, int(real_port))
        except Exception:
            writer.close(); return
        await asyncio.gather(pipe(reader, upstream_writer), pipe(upstream_reader, writer))
    async def plug():
        proxy['server'] = await asyncio.start_server(handle, '127.0.0.1', proxy_port)
    def act():
        log('startup_seconds', round(time.monotonic() - t0, 1)); log('chats_shown', len(app.chats))
        c = chat(QA_CHANNEL); log('pinned_before', c.pinned)
        app.call(app.service.backend.pin(QA_CHANNEL, not c.pinned), lambda v: log('result', type(v).__name__), 'x')
        def network_back():
            log('pending_offline', pending_count())
            asyncio.run_coroutine_threadsafe(plug(), proxy['loop']).result(5)
            plugged = time.monotonic()
            def sent():
                log('sent_after_network_back_s', round(time.monotonic() - plugged, 1))
                def verify():
                    c2 = chat(QA_CHANNEL); log('pinned_after', c2.pinned); log('status_after', app.status.get())
                    app.call(app.service.backend.pin(QA_CHANNEL, not c2.pinned), lambda v: (log('restored', type(v).__name__), finish()), 'x')
                root.after(4000, verify)
            wait(lambda: pending_count() == 0, sent, 120, 'flushed_live')
        root.after(3000, network_back)
    wait(lambda: ready() and len(app.chats) > 0, act, 40, 'ready_offline')
root.mainloop()
