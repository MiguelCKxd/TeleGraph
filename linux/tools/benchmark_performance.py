"""Isolated native Tk workloads; no account files or network connections.

Usage: python tools/benchmark_performance.py SOURCE REPORT [--profile PROFILE]
Timing includes Tk's idle geometry/drawing work. Results describe this machine,
not a hardware requirement or a comparison with another Telegram client.
"""
import argparse
import cProfile
import gc
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time
import tkinter as tk


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('report', type=Path)
    parser.add_argument('--profile', type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.source.resolve()))
    with tempfile.TemporaryDirectory(prefix='tg-perf-isolated-') as folder:
        os.environ['TG_ASCII_DATA_DIR'] = folder
        from tg_ascii.backend import Chat, Message
        from tg_ascii.desktop import Desktop
        from tg_ascii import __version__
        from telethon import types
        root = tk.Tk()
        app = Desktop(root, demo=True)
        failures = []
        root.report_callback_exception = lambda kind, exc, trace: failures.append(repr(exc))
        app.show_error = lambda exc: failures.append(repr(exc))
        deadline = time.monotonic() + 15
        while (not app.chats or app.busy) and time.monotonic() < deadline:
            root.update()
            time.sleep(.005)
        if not app.chats or app.busy:
            raise RuntimeError('Demo failed to start')
        app.preferences.values.update(bubbles=False, animated_emoji=False, inline_media=False)
        app.active = 1
        root.update()
        results = {}
        profile = cProfile.Profile() if args.profile else None
        if profile: profile.enable()
        def sample(label, operation, rounds=7):
            cold_start=time.perf_counter()
            operation()
            root.update_idletasks()
            first_ms=(time.perf_counter()-cold_start)*1000
            times = []
            for _ in range(rounds):
                start = time.perf_counter()
                operation()
                root.update_idletasks()
                times.append((time.perf_counter() - start) * 1000)
            results[label] = {'first_frame_ms':round(first_ms,3),'median_ms': round(statistics.median(times), 3),
                              'max_ms': round(max(times), 3), 'rounds': rounds}
        for count in (100, 1000, 5000):
            app.chats = [Chat(i, f'Chat {i} · ejemplo', unread=i % 3) for i in range(1, count + 1)]
            def chats():
                app.chats[len(app.chats)//2].unread += 1
                app.render_chats()
            sample(f'chats_{count}_one_unread_change', chats)
        for bubbles in (False, True):
            app.preferences.values['bubbles'] = bubbles
            for count in (200, 1000):
                app.messages = []
                for i in range(1,count+1):
                    text=f'Message {i}: https://example.com/item/{i} · texto 👋'
                    url=f'https://example.com/item/{i}'
                    app.messages.append(Message(i,'Fixture',text,'12:00',sender_id=20,
                        entities=(types.MessageEntityUrl(text.index(url),len(url)),)))
                def redraw():
                    app.messages[-1].text += '.'
                    app.render_messages(False)
                sample(f'{"bubbles" if bubbles else "classic"}_{count}_one_message_change',redraw,rounds=5)
        # Repeated frames must release callbacks and canvas items.
        app.messages = app.messages[-200:]
        app.render_messages(False)
        root.update_idletasks()
        before = {'tcl_commands':len(root.tk.call('info','commands')),
                  'canvas_items':len(app.bubble_view.find_all()),
                  'images':len(root.tk.call('image','names'))}
        for _ in range(20):
            app.render_messages(False)
            root.update_idletasks()
        gc.collect()
        after = {'tcl_commands':len(root.tk.call('info','commands')),
                 'canvas_items':len(app.bubble_view.find_all()),
                 'images':len(root.tk.call('image','names'))}
        if profile:
            profile.disable()
            profile.dump_stats(str(args.profile))
        # Idle CPU and event-loop heartbeat with no network or animations.
        root.update()
        heartbeat = []
        heartbeat_job = None
        def beat(expected):
            nonlocal heartbeat_job
            heartbeat.append(max(0, (time.perf_counter() - expected) * 1000))
            heartbeat_job=root.after(16, beat, time.perf_counter() + .016)
        heartbeat_job=root.after(16, beat, time.perf_counter() + .016)
        cpu = time.process_time()
        root.after(1200,root.quit)
        root.mainloop()
        root.after_cancel(heartbeat_job)
        idle_cpu = time.process_time() - cpu
        result = {'version':__version__,'platform':platform.platform(),'python':platform.python_version(),
                  'viewport':[root.winfo_width(),root.winfo_height()], 'isolated_demo':True,
                  'multimedia_and_animation_in_timing':False,'profiling_enabled':bool(profile),'timings':results,
                  'resources_before':before,'resources_after':after,
                  'idle_1_2s_cpu_seconds':round(idle_cpu,4),
                  'idle_heartbeat_max_delay_ms':round(max(heartbeat,default=0),3),
                  'callback_errors':failures}
        try:
            import resource
            peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            result['process_peak_rss_mib']=round(peak/(1024*1024 if sys.platform=='darwin' else 1024),2)
        except ImportError:
            pass
        app.close()
        deadline = time.monotonic() + 10
        while not app.closed and time.monotonic() < deadline:
            root.update()
            time.sleep(.005)
        app.worker.thread.join(timeout=3)
        result['worker_stopped']=not app.worker.thread.is_alive()
        args.report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result,indent=2))
        if failures or not result['worker_stopped']:raise RuntimeError('Native workload failed')


if __name__ == '__main__':
    main()
