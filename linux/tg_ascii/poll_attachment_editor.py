"""Lazy poll attachment controls and dialog-owned, cancellable uploads."""
import time
from pathlib import Path
from tkinter import ttk

from .app_dialogs import filedialog
from .chat_capabilities import chat_capabilities
from .i18n import tr
from .scrolling import FlowFrame


class PollAttachmentEditor:
    KEY = 'poll-attachments'

    def __init__(self, dialog):
        self.dialog = dialog
        self.paths, self.labels = {}, {}
        self.pending = False
        self.token = None
        self.disabled = []
        self.cancel_button = None
        self.scope_timer = None
        self.solution_enabled = lambda: True
        dialog.window.bind('<Destroy>', self.closed, add='+')

    def add(self, parent, key):
        capabilities = chat_capabilities(self.dialog.app, self.dialog.peer)
        if not (capabilities.allows('send_photos') or capabilities.allows('send_videos')): return
        row = FlowFrame(parent); row.pack(fill='x', pady=3)
        ttk.Button(row, text=tr('Choose file'), command=lambda: self.choose(key)).pack(side='left')
        ttk.Button(row, text=tr('Remove file'), command=lambda: self.remove(key)).pack(side='left', padx=4)
        self.labels[key] = ttk.Label(row, text=tr('Attachment'), wraplength=440)
        self.labels[key].pack(side='left', fill='x', expand=True)
        return row

    def valid(self):
        if not self.dialog.valid(): return False
        capabilities = chat_capabilities(self.dialog.app, self.dialog.peer)
        return capabilities.allows('poll') and all(capabilities.allows(
            'send_videos' if Path(path).suffix.lower() == '.mp4' else 'send_photos') for path in self.active_files().values())

    def active_files(self):
        return {key: path for key, path in self.paths.items()
                if key != 'solution_media' or self.solution_enabled()}

    def controls(self, parent):
        self.cancel_button = ttk.Button(parent, text=tr('Cancel'), command=self.cancel)
        self.cancel_button.pack(fill='x', pady=4)
        self.cancel_button.configure(state='disabled')

    def choose(self, key):
        if self.pending or not self.valid() or key not in self.labels: return
        if key == 'solution_media' and not self.solution_enabled():return
        capabilities = chat_capabilities(self.dialog.app, self.dialog.peer)
        extensions = ('*.jpg *.jpeg *.png ' if capabilities.allows('send_photos') else '')
        if capabilities.allows('send_videos'): extensions += '*.mp4'
        if not extensions: return
        selected = filedialog.askopenfilename(parent=self.dialog.window,
            title=tr('Choose a JPEG, PNG or MP4 file.'),
            filetypes=[(tr('Attachment'), extensions.strip())])
        # Native file pickers can run account/chat changes in their modal loop.
        if selected and self.valid() and not self.pending:
            permission = 'send_videos' if Path(selected).suffix.lower() == '.mp4' else 'send_photos'
            if not chat_capabilities(self.dialog.app, self.dialog.peer).allows(permission): return
            self.paths[key] = selected
            self.labels[key].configure(text=Path(selected).name)

    def remove(self, key):
        if self.pending or not self.dialog.valid() or key not in self.labels: return
        self.paths.pop(key, None)
        self.labels[key].configure(text=tr('Attachment'))

    def _busy(self, value):
        self.pending = value
        if value:
            stack = list(self.dialog.body.winfo_children())
            while stack:
                widget = stack.pop(); stack.extend(widget.winfo_children())
                if widget is self.cancel_button: continue
                if 'state' in widget.keys():  # noqa: SIM118 - Tk widgets are not mappings
                    self.disabled.append((widget, widget.cget('state')))
                    widget.configure(state='disabled')
        else:
            for widget, previous in self.disabled:
                if widget.winfo_exists(): widget.configure(state=previous)
            self.disabled.clear()
        if self.cancel_button is not None:
            self.cancel_button.configure(state='normal' if value else 'disabled')

    def cancel(self):
        self.token = None
        requests = self.dialog.requests
        future = requests.jobs.pop(self.KEY, None)
        getattr(requests, 'tokens', {}).pop(self.KEY, None)
        if future is not None: future.cancel()
        self.stop_scope_timer()
        if not self.dialog.requests.closed and self.dialog.window.winfo_exists():
            self._busy(False)
            self.dialog.status.set('')

    def stop_scope_timer(self):
        if self.scope_timer is not None:
            self.dialog.window.after_cancel(self.scope_timer)
            self.scope_timer = None

    def check_scope(self):
        self.scope_timer = None
        if not self.pending: return
        if not self.valid(): self.cancel(); return
        self.scope_timer = self.dialog.window.after(200, self.check_scope)

    def closed(self, event):
        if event.widget is not self.dialog.window: return
        self.token = None
        self.stop_scope_timer()
        # AdvancedDialog owns request cancellation; drop widget references on Tk.
        self.disabled.clear(); self.labels.clear(); self.cancel_button = None
        self.solution_enabled = lambda: False

    def send(self, question, answers, options, reply_to):
        dialog = self.dialog
        if self.pending or not self.valid() or dialog.app.busy: return
        files = self.active_files()
        def publish(prepared):
            if not self.valid(): return
            dialog.mutate(lambda: dialog.backend.send_poll(dialog.peer, question, answers,
                reply_to=reply_to, **(options | prepared)), close=True)
        if not files:
            publish({}); return
        self.token = token = object()
        self._busy(True)
        self.check_scope()
        dialog.status.set(tr('Uploading file: ') + ', '.join(Path(path).name for path in files.values()))
        last = [0.0]
        def progress(name, current, total):
            # Worker callback: never call Tk, and keep the UI event queue bounded.
            now = time.monotonic()
            if now-last[0] < .1 and current != total: return
            last[0] = now
            value = min(100, int(current*100/total)) if total else 0
            dialog.app.worker.events.put((display_progress, (name, value)))
        def display_progress(value):
            if self.token is token and self.valid():
                dialog.status.set(tr('Uploading file: ') + value[0] + f' · {value[1]}%')
        def completed(prepared):
            if self.token is not token or not self.valid(): return
            self.token = None
            self.stop_scope_timer()
            self._busy(False)
            dialog.status.set('')
            publish(prepared)
        def failed(error):
            if self.token is not token or not self.valid(): return
            self.token = None
            self.stop_scope_timer()
            self._busy(False)
            dialog.status.set(str(error))
        operation = dialog.backend.prepare_poll_attachments(dialog.peer, question, answers,
            files, progress=progress, **options)
        # Inactivity is bounded by transfer_timeout; a progressing upload is not
        # cut off after the generic dialog read deadline on a slow connection.
        dialog.requests.submit(self.KEY, operation, completed, failed, timeout=None)
