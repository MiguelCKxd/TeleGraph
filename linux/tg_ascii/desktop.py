from .timestamps import message_time
"""Standalone Tk desktop interface. Only the main thread touches widgets."""
import asyncio
from concurrent.futures import CancelledError, Future
import inspect
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
from .app_dialogs import filedialog, messagebox

from telethon import errors, types

from . import APP_NAME, __edition__
from .auth import error_message
from .backend import single_line
from .i18n import tr
from .accounts import Accounts
from .preferences import Preferences, data_root
from .desktop_features import DesktopFeatures
from .telegram_features import matches_folder, compile_folder, in_chat_list
from .ui_work import bind_text_action, clear_text_actions, sync_tree_rows
from .tk_safety import drain as drain_deferred_images

BG = '#08100c'
PANEL = '#0e1b13'
GREEN = '#8cf5a6'
MUTED = '#80a98c'
LINE = '#294d34'
FONT = ('Menlo' if sys.platform == 'darwin' else 'Consolas', 12)
BUSY_UI_GRACE = 12


class TransportReset(ConnectionError):
    """A request whose connection was torn down (Telethon cancels it)."""


async def transport_safe(coroutine):
    """Turn a cancellation that came from *inside* the operation into an error.

    Telethon cancels every pending request when the connection is reset
    (``MTProtoSender._disconnect`` with no error), e.g. when Recovery
    reconnects after a network loss. Before 1.4.1 that CancelledError made the
    worker drop the result silently: no success/failure callback ran, so
    ``busy`` and ``_refresh_pending`` stayed set forever and the whole UI
    (composer, send, menus, refresh) stayed locked until restart. A real
    cancellation of this task (UI cancel, wait_for timeout, shutdown) has
    ``cancelling() > 0`` and still propagates unchanged.
    """
    try:
        return await coroutine
    except asyncio.CancelledError:
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise
        raise TransportReset('Connection reset while the request was pending') from None


class AsyncWorker:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.events = queue.SimpleQueue()
        self._state_lock = threading.Lock()
        self._stopping = False
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        asyncio.set_event_loop(self.loop)
        from .resources import worker_threads
        workers = worker_threads()
        if workers:
            # 1.5 CPU profile: decoding/thumbnail thread pool size.
            from concurrent.futures import ThreadPoolExecutor
            self.loop.set_default_executor(ThreadPoolExecutor(max_workers=workers, thread_name_prefix='tg-work'))
        try:
            self.loop.run_forever()
        finally:
            tasks = asyncio.all_tasks(self.loop)
            for task in tasks:
                task.cancel()
            if tasks:
                self.loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.close()

    def submit(self, coroutine, success, failure):
        # A late UI callback can race shutdown. Never enqueue work on a loop
        # which is about to stop, or leave its coroutine unawaited.
        future = Future()
        started = False

        async def run_operation():
            nonlocal started
            started = True
            return await transport_safe(coroutine)

        def start():
            if future.cancelled():
                coroutine.close()
                return
            task = self.loop.create_task(run_operation())

            def finish(operation):
                if not started:
                    coroutine.close()
                if operation.cancelled():
                    future.cancel()
                elif future.set_running_or_notify_cancel():
                    error = operation.exception()
                    if error is None:
                        future.set_result(operation.result())
                    else:
                        future.set_exception(error)
                else:
                    operation.exception()

            def cancel_if_requested(result):
                if result.cancelled():
                    try:
                        self.loop.call_soon_threadsafe(task.cancel)
                    except RuntimeError:
                        pass  # The loop has already completed shutdown.

            task.add_done_callback(finish)
            future.add_done_callback(cancel_if_requested)

        with self._state_lock:
            if self._stopping or self.loop.is_closed():
                coroutine.close()
                future.cancel()
                return future
            self.loop.call_soon_threadsafe(start)
        def complete(result):
            try:
                value = result.result()
            except CancelledError:
                return
            except Exception as exc:
                try:
                    if getattr(self,'diagnostic',None):self.diagnostic(exc)
                except Exception:pass  # Diagnostics must never prevent delivery of a failure.
                self.events.put((failure, exc))
            else:
                self.events.put((success, value))
        future.add_done_callback(complete)
        return future

    def stop(self):
        with self._state_lock:
            if self._stopping:return
            self._stopping=True
            if not self.loop.is_closed():self.loop.call_soon_threadsafe(self.loop.stop)


class Desktop(DesktopFeatures):
    def __init__(self, root, demo=False, configure=False, service=None, linked_owner=None, window_slot=None, chat_target=None):
        self._linked_owner = linked_owner
        # Before any image exists: GC on the asyncio thread must never run
        # Tk's "image delete" there (SIGSEGV seen in real 1.3.1 crash logs).
        from .tk_safety import install as install_tk_image_guard
        install_tk_image_guard()
        self._chat_only = chat_target is not None
        self._pinned_account = service.current if self._chat_only else None
        self._pinned_peer = chat_target.id if self._chat_only else None
        self.window_slot = window_slot
        self.root = root
        self.root._lock_app_owner = linked_owner or self
        self.root._app_instance = self
        self.root.geometry('680x720' if self._chat_only else '1040x720')
        self.root.minsize(360 if self._chat_only else 480, 360)
        self.root.configure(bg=BG)
        self.root.report_callback_exception = lambda kind, exc, trace: messagebox.showerror('TeleGraph', error_message(exc), parent=self.root)
        self.preferences = linked_owner.preferences if linked_owner is not None else Preferences(demo=demo)
        self._title_chat = chat_target
        if linked_owner is None:
            self.update_window_titles()
            self.preferences.listeners.append(self.update_window_titles)
            from . import resources, menu_style, decode_pool, gpu_video
            resources.configure(self.preferences.values)
            decode_pool.configure(self.preferences.values)
            self.preferences.listeners.append(lambda: decode_pool.configure(self.preferences.values))
            gpu_video.configure(self.preferences.values)
            self.preferences.listeners.append(lambda: gpu_video.configure(self.preferences.values))
            menu_style.configure(self.preferences.values)
            self.preferences.listeners.append(lambda: resources.configure(self.preferences.values))
            self.preferences.listeners.append(lambda: menu_style.configure(self.preferences.values, self.service.root))
        if linked_owner is not None:
            from .interface_windows import WindowWorker
            self.worker = WindowWorker(self, linked_owner.worker)
            self._logging_out_accounts = linked_owner._logging_out_accounts
        else:
            self.worker = AsyncWorker()
            self._logging_out_accounts = set()
        self.service = service or Accounts(demo=demo)
        if linked_owner is None:
            # 1.5.2: menu folders live in this service's data folder.
            from . import menu_style
            menu_style.configure(self.preferences.values, self.service.root)
        from .recovery import record_failure
        if linked_owner is None:
            self.worker.diagnostic=lambda exc:record_failure(self.service.root,'request',exc)
        def callback_error(kind,exc,trace):
            record_failure(self.service.root,'interface',exc)
            self.show_error(exc)
        self.root.report_callback_exception=callback_error
        self.ui_account = self.service.current
        self.account_states, self.account_unread = {}, {}
        self.popups, self.media_temps, self.folder_records = [], [], []
        self.drop_available = False
        if linked_owner is None:
            self.service.on_message = lambda account, peer, message: self.worker.events.put((self.account_event, (account, peer, message)))
            self.service.on_change = lambda account, kind, payload: self.worker.events.put((self.account_change, (account, kind, payload)))
            self.service.on_registry = lambda: self.worker.events.put((self.account_registry_changed, None))
        self.demo = demo
        if linked_owner is not None:
            self.outbox = getattr(linked_owner, 'outbox', None)
        else:
            from .outbox import Outbox
            self.outbox = Outbox(self)
        if self.outbox is not None:
            self.outbox.subscribe(self.outbox_changed)
        self.init_plus()
        self.closed = False
        self.closing = False
        self.busy = False
        from copy import copy
        self.chats = [copy(chat_target)] if self._chat_only else []
        self.active = self._pinned_peer
        self.messages = []
        self.drafts = {}
        from .drafts import DraftManager, DraftStore
        # Separate durable draft copies, with the same live Telegram backend.
        # Telegram itself has one cloud draft per chat; local view edits stay
        # independent until the user edits/sends in that view.
        store = None
        if linked_owner is not None:
            store = DraftStore(self.service.root / 'window-drafts' / window_slot, demo=demo)
        self.draft_manager = DraftManager(self, store=store)
        self.draft_manager.restore_account()
        self.attachment = None
        self.progress_value = -1
        self.status = tk.StringVar(value=tr('Conectando a Telegram...'))
        self.configure_style()
        self.init_customization()
        from .scrolling import Viewport, WheelRouter
        self.viewport = Viewport(root)
        self.viewport.pack(fill='both', expand=True)
        self.container = self.viewport.content
        from .interface_background import InterfaceBackground
        self.interface_background = InterfaceBackground(self)
        self.wheel_router = linked_owner.wheel_router if linked_owner is not None else WheelRouter(root)
        from .back_gesture import install as install_back
        install_back(root, self.go_back)
        if linked_owner is not None:
            self.wheel_router.install(root)
        self.status_label = ttk.Label(root, textvariable=self.status, padding=(8, 3), style='Muted.TLabel')
        self.status_label.pack(fill='x')
        from .pending_actions import install_indicator
        install_indicator(self)
        root.protocol('WM_DELETE_WINDOW', self.close if linked_owner is not None else self.window_close)
        root.bind('<Control-q>', lambda _: self.close())
        from .read_visibility import schedule as schedule_read, watch as watch_reading
        root.bind('<FocusIn>', lambda _: schedule_read(self, 0), add='+')
        # 1.5.0.2: also after reopening the window and as a periodic safety net.
        root.bind('<Map>', lambda event: schedule_read(self, 200) if event.widget is root else None, add='+')
        watch_reading(self)
        if sys.platform == 'darwin':
            root.bind('<Command-q>', lambda _: self.close())
            root.bind('<Command-w>', lambda _: self.close() if linked_owner is not None else self.window_close())
            if linked_owner is None:
                self._install_macos_dock_handler()
        if linked_owner is None:
            root.after(50, self.pump)
            root.after(200, self.watch_theme)
            from .interface_windows import watch_shared_design
            watch_shared_design(self)
            self.begin_startup(configure)
        else:
            self.login_stage('ready')

    def update_window_titles(self):
        from .saved_windows import window_title
        name = self.preferences.values.get('app_display_name') or APP_NAME
        self.root.title(window_title(data_root(), name) or f'{name} {__edition__}')
        for view in getattr(self, '_app_windows', []):
            if view.closed:
                continue
            if view._title_chat is None:
                from .interface_layout import caption
                view.root.title(name + ' · ' + caption('Linked window', 'Ventana vinculada'))
            else:
                labels = getattr(self.service, 'labels', {})
                view.root.title(view._title_chat.name + ' · ' + labels.get(view.ui_account, tr('Cuenta')) + ' · ' + name)

    def begin_startup(self, configure=False):
        if (not getattr(self, '_window_startup_done', False) and getattr(self, '_linked_owner', None) is None
                and hasattr(self, 'root') and hasattr(self, 'preferences') and not getattr(self, 'demo', True)):
            self._window_startup_done = True
            from .saved_windows import reopen_at_start, is_independent
            if not is_independent(self.service.root):
                if self.preferences.values.get('open_at_login'):
                    from .autostart import apply
                    apply(True)  # Keeps the login entry pointing at this copy of the app.
                self.root.after(1500, lambda: reopen_at_start(self) if not self.closed else None)
        if len(self.service.entries)>1 and self.preferences.values.get('ask_account_startup', True):
            from .startup_accounts import show_account_chooser
            show_account_chooser(self, configure)
        else:
            self.start_chosen_account(self.service.current, configure)

    def start_chosen_account(self, account, configure=False):
        self.service.current = account
        self.ui_account = account
        self.drafts = {}
        self.draft_manager.restore_account()
        self.login_stage('connecting')
        self.call(self.service.connect(configure=configure), self.login_stage, tr('Conectando a Telegram...'))

    def configure_style(self):
        global FONT, BG, PANEL, GREEN, MUTED, LINE
        from .themes import set_palette
        from .appearance import app_palette,configure_shapes
        colors = app_palette(self.preferences.values)
        set_palette(colors)
        BG, PANEL, GREEN, MUTED, LINE = [colors[k] for k in ("bg", "panel", "text", "muted", "line")]
        from .typography import configure_fonts
        from .rtl_ui import install, ui_font_family
        style_root = self._linked_owner.root if self._linked_owner is not None else self.root
        install(style_root)
        requested_family = ui_font_family(style_root, self.preferences.values['font_family'])
        family = configure_fonts(style_root, requested_family, self.preferences.values['font_size'])
        self.font_family = family
        FONT = (family, self.preferences.values['font_size'])
        from .themes import set_font
        set_font(family)
        style = ttk.Style(style_root)
        style.theme_use('clam')
        style.configure('.', font=FONT, background=BG, foreground=GREEN)
        style.configure('TFrame', background=BG)
        style.configure('TLabel', background=BG, foreground=GREEN)
        style.configure('Muted.TLabel', foreground=MUTED)
        style.configure('Title.TLabel', font=(FONT[0], 22, 'bold'))
        style.configure('TButton', background=PANEL, foreground=GREEN,
                        bordercolor=LINE, focuscolor=GREEN, padding=(7, 4))
        style.map('TButton', background=[('active', colors['selected']), ('disabled', BG)],
                  foreground=[('disabled', '#496652')])
        style.configure('TEntry', fieldbackground=PANEL, foreground=GREEN,
                        insertcolor=GREEN, bordercolor=LINE, padding=5)
        style.configure('TCombobox', fieldbackground=PANEL, foreground=GREEN, padding=4)
        style.map('TCombobox', fieldbackground=[('readonly',PANEL)],foreground=[('readonly',GREEN)])
        style.configure('TCheckbutton', background=BG, foreground=GREEN)
        # Clam otherwise keeps pale native tab/number-field backgrounds while
        # inheriting the app's light text, making dark-theme controls unreadable.
        style.configure('TNotebook', background=BG, bordercolor=LINE)
        style.configure('TNotebook.Tab', background=PANEL, foreground=GREEN)
        style.map('TNotebook.Tab', background=[('selected', colors['selected']), ('active', PANEL)],
                  foreground=[('disabled', MUTED), ('selected', GREEN)])
        style.configure('TSpinbox', fieldbackground=PANEL, foreground=GREEN,
                        insertcolor=GREEN, arrowcolor=GREEN, bordercolor=LINE)
        style.configure('Treeview', background=PANEL, fieldbackground=PANEL,
                        foreground=GREEN, rowheight=26 if self.preferences.values['compact'] else 38, bordercolor=LINE)
        style.map('Treeview', background=[('selected', colors['selected'])], foreground=[('selected', colors['text'])])
        style.configure('Vertical.TScrollbar', background=LINE, troughcolor=BG,
                        bordercolor=BG, arrowcolor=GREEN)
        style.configure('TProgressbar', background=GREEN, troughcolor=PANEL)
        configure_shapes(style_root,style,self.preferences.values,colors)

    def pump(self):
        if self.closed:
            return
        drain_deferred_images()
        if getattr(self, 'background', None):
            self.background.process_events()
        started=time.monotonic();processed=0
        for _ in range(100):
            try:
                callback, value = self.worker.events.get_nowait()
            except queue.Empty:
                break
            if not self.closing:
                try:
                    callback(value)
                except Exception as exc:
                    self.show_error(exc)
            elif callback == self.finish_close:
                callback(value)
            if self.closed:
                return
            processed+=1
            if time.monotonic()-started>=.008:break
        # Idle backoff: 30 ms polls while recently active, 50 ms after ~1 s of
        # silence. Saves ~13 wakeups/s per window while idle (laptops, VMs);
        # any event drops straight back to the 8 ms busy cadence.
        idle=0 if processed else getattr(self,'_idle_pumps',0)+1
        self._idle_pumps=idle
        self.root.after(8 if processed else 30 if idle<34 else 50, self.pump)

    def call(self, coroutine, success, status, failure=None, timeout=90):
        if getattr(self,'closed',False) or getattr(self,'closing',False) or getattr(self.worker,'_stopping',False) is True:
            # Do this before creating bounded(): closing that wrapper without
            # starting it would otherwise leave the captured coroutine unawaited.
            coroutine.close()
            future=Future();future.cancel();return future
        # 1.4.1: every blocking call holds its own token. One call finishing no
        # longer clears another's lock, a cancelled call always releases its
        # token, and after BUSY_UI_GRACE seconds the UI is unlocked even if the
        # network never answers (the operation keeps running; its callbacks
        # still arrive and still check that their chat/account is current).
        tokens=self.__dict__.setdefault('_busy_tokens',set())
        token=object();tokens.add(token)
        self.busy = True
        self.status.set(status)
        self.update_controls()
        def release():
            if token not in tokens:return
            tokens.discard(token)
            self.busy = bool(tokens)
            if not getattr(self,'closed',False):self.update_controls()
        def done(value):
            release()
            from .pending_actions import handle
            if handle(self, value, success, failure):
                return  # 1.5.3: stored offline; finishes now or when it is sent.
            success(value)
        def failed(exc):
            release()
            if failure:
                failure(exc)
            else:
                self.show_error(exc)
        async def bounded():return await asyncio.wait_for(coroutine,timeout)
        future=self.worker.submit(bounded(), done, failed)
        def grace():
            if token in tokens and not getattr(self,'closed',False):
                release()
                try:self.status.set(tr('Sin conexion') if self.connection_offline() else status)
                except Exception:pass
        try:self.root.after(int(BUSY_UI_GRACE*1000),grace)
        except (tk.TclError,RuntimeError,AttributeError):pass
        def release_unstarted(result):
            # Shutdown may cancel bounded before it first runs, so its body or
            # finally block cannot release the inner operation in that case.
            if result.cancelled():
                # A cancelled future delivers no callback: release from Tk.
                try:self.worker.events.put((lambda _:release(),None))
                except Exception:pass
                if inspect.getcoroutinestate(coroutine)==inspect.CORO_CREATED:
                    try:coroutine.close()
                    except RuntimeError:pass  # It started concurrently; task cancellation owns it.
        if future is not None:future.add_done_callback(release_unstarted)
        return future

    def connection_offline(self):
        failures=getattr(getattr(self,'service',None),'failures',None) or {}
        return getattr(self,'ui_account',None) in failures

    def update_controls(self):
        for widget in getattr(self, 'buttons', []):
            if widget.winfo_exists():
                widget.configure(state='disabled' if self.busy else 'normal')
        if hasattr(self, 'editor') and self.editor.winfo_exists():
            self.editor.configure(state='disabled' if self.busy else 'normal')
        for widget in getattr(self, 'login_entries', []):
            if widget.winfo_exists():
                widget.configure(state='disabled' if self.busy else 'normal')
        if hasattr(self, 'composer_controls') and self.composer_controls.winfo_exists():
            self.update_chat_capabilities()

    def clear(self):
        runtime = getattr(self, 'layout_runtime', None)
        if runtime is not None:
            runtime.detach()
        self.cancel_global_search()
        job=getattr(self,'_message_render_job',None)
        if job is not None:job.cancel()
        self._message_render_follow=False
        self.viewport.fit_to_window = False
        from .interface_windows import cancel_view_timers
        cancel_view_timers(self.container)
        for widget in self.container.winfo_children():
            widget.destroy()
        self.buttons = []
        self.login_entries = []

    def login_stage(self, stage):
        if stage == 'ready':
            if not getattr(self, '_chat_only', False):
                self.apply_optional_services()
            self.build_chats()
            self.restore_draft()
            self.render_messages()
            if not getattr(self, '_chat_only', False):
                # 1.5.3: the copy saved on this device appears at once (and is
                # all there is while offline); Telegram's list replaces it.
                self._chats_from_network = False
                from .offline_store import load_into
                def shown(applied):
                    if applied and self.connection_offline():
                        self.status.set(tr('Offline: showing the copy saved on this device.'))
                load_into(self, shown)
                from .pending_actions import update_indicator
                update_indicator(self)
            self.refresh()
            from .desktop_contacts import auto_sync
            auto_sync(self)
            if hasattr(self, 'draft_manager') and not self._chat_only:
                self.draft_manager.pull()
            if getattr(self, 'outbox', None) is not None and not self._chat_only:
                self.outbox.kick()
            return
        self.clear()
        self.stage = stage
        self.add_language_picker(self.container)
        if self.service.entries and (len(self.service.entries) > 1 or self.ui_account not in self.service.entries):
            back = ttk.Button(self.container, text=tr('Volver a otra cuenta'),
                              command=lambda: self.switch_account(next((k for k in self.service.entries if k != self.ui_account), next(iter(self.service.entries)))))
            back.pack(anchor='w')
        card = ttk.Frame(self.container, padding=30)
        card.place(relx=0.5, rely=0.45, anchor='center', relwidth=0.8)
        self.logo_label = ttk.Label(card)
        self.logo_label.pack(anchor='w', pady=(0, 12))
        self.refresh_logo()
        from .startup_look import display_name
        ttk.Label(card, text=display_name(self.preferences.values), style='Title.TLabel', font=(self.font_family, 22, 'bold'),
                  foreground=self.preferences.values.get('accent_color') or GREEN).pack(anchor='w', pady=(0, 4))
        ttk.Label(card, text=tr('Tu Telegram. A tu gusto.'), style='Muted.TLabel').pack(anchor='w', pady=(0, 26))
        self.login_value = tk.StringVar()
        self.login_hash = tk.StringVar()
        self.remember = tk.BooleanVar(value=False)
        if stage == 'connecting':
            ttk.Label(card, text=tr('Conectando a Telegram...')).pack(anchor='w')
            return
        if stage == 'signup':
            from webbrowser import open as open_browser
            ttk.Label(card, text=tr('New account')).pack(anchor='w', pady=(0, 10))
            ttk.Label(card, text=tr('Create your account in the official Telegram app for iPhone or Android, then return here to sign in.'),
                      style='Muted.TLabel', wraplength=420, justify='left').pack(anchor='w')
            ttk.Button(card, text=tr('Open') + ' Telegram (Android / iOS)',
                       command=lambda: open_browser('https://telegram.org/apps')).pack(anchor='w', pady=8)
            ttk.Button(card, text=tr('Sign in again'), command=lambda: self.login_stage('phone')).pack(anchor='w', pady=8)
            return
        from .auth import USER_API
        titles = {'credentials': 'Telegram API' if USER_API else tr('Configurar aplicacion (desarrollador)'),
                  'phone': tr('Tu numero de telefono'), 'code': tr('Codigo de Telegram'),
                  'password': tr('Contrasena de verificacion en dos pasos')}
        ttk.Label(card, text=titles[stage]).pack(anchor='w', pady=(0, 10))
        if stage == 'credentials':
            if USER_API:
                from webbrowser import open as open_browser
                ttk.Button(card, text='my.telegram.org/apps',
                           command=lambda: open_browser('https://my.telegram.org/apps')).pack(anchor='w', pady=(0, 8))
            ttk.Label(card, text='API ID').pack(anchor='w')
        entry = ttk.Entry(card, textvariable=self.login_value, show='*' if stage in ('code', 'password') else '')
        entry.pack(fill='x', pady=(0, 12))
        entry.bind('<Return>', lambda _: self.login_submit())
        self.login_entries = [entry]
        if stage == 'credentials':
            ttk.Label(card, text='API hash').pack(anchor='w')
            secret = ttk.Entry(card, textvariable=self.login_hash, show='*')
            secret.pack(fill='x', pady=(0, 12))
            secret.bind('<Return>', lambda _: self.login_submit())
            self.login_entries.append(secret)
            ttk.Checkbutton(card, text=tr('Recordar claves de app en este equipo (sin cifrar)'), variable=self.remember).pack(anchor='w')
        elif stage == 'phone':
            ttk.Button(card, text=tr('Log in with QR'), command=self.qr_login).pack(anchor='w', pady=8)
            ttk.Button(card, text=tr('New account'), command=lambda: self.login_stage('signup')).pack(anchor='w', pady=8)
            ttk.Label(card, text=tr('Incluye + y el prefijo de tu pais. Ejemplo: +34 612 345 678'), style='Muted.TLabel', wraplength=620).pack(anchor='w')
        elif stage == 'code':
            ttk.Label(card, text=tr('Introduce el codigo que te ha enviado Telegram.'), style='Muted.TLabel').pack(anchor='w')
        button = ttk.Button(card, text=tr('Continuar'), command=self.login_submit)
        button.pack(anchor='e', pady=(24, 0))
        self.buttons = [button]
        if stage in ('code', 'password'):
            back = ttk.Button(card, text=tr('Cambiar numero'), command=lambda: self.login_stage('phone'))
            back.pack(anchor='w', pady=(12, 0))
            self.buttons.append(back)
        self.status.set(tr('Inicia sesion con tu propia cuenta.'))
        entry.focus_set()

    def login_submit(self):
        if self.busy:
            return
        value = self.login_value.get()
        if self.stage == 'credentials':
            operation = self.service.connect((value, self.login_hash.get()), self.remember.get())
            self.login_hash.set('')
        elif self.stage == 'phone':
            operation = self.service.request_code(value)
        elif self.stage == 'code':
            operation = self.service.verify_code(value)
            self.login_value.set('')
        else:
            operation = self.service.verify_password(value)
            self.login_value.set('')
        self.call(operation, self.login_stage, tr('Conectando a Telegram...'))

    def show_error(self, exc):
        from .app_lock import is_locked,lock_owner
        if is_locked(self):
            owner=lock_owner(self)
            owner._lock_errors=(getattr(owner,'_lock_errors',[])+[exc])[-3:]
            return
        messages = {
            errors.PhoneNumberInvalidError: tr('Telegram no reconoce ese numero. Revisa el numero y su prefijo.'),
            errors.PhoneCodeInvalidError: tr('Codigo incorrecto. Prueba de nuevo.'),
            errors.PasswordHashInvalidError: tr('Contrasena incorrecta. Prueba de nuevo.'),
            errors.PhoneCodeExpiredError: tr('El codigo ha caducado. Solicita uno nuevo.'),
            errors.ApiIdInvalidError: tr('La configuracion incluida en la app no es valida. Contacta con el desarrollador.'),
        }
        from .auth import USER_API
        if USER_API and isinstance(exc, errors.ApiIdInvalidError):
            self.login_stage('credentials')
            messages[errors.ApiIdInvalidError] = tr('API ID o hash incorrectos. Revisa las claves de la app.')
        text = messages.get(type(exc), error_message(exc))
        from .pending_actions import transport_failure
        if transport_failure(exc) and getattr(self, 'stage', None) == 'ready':
            # 1.5.3: no pop-up for every action while offline; the status bar
            # says it, and changes made meanwhile wait in the pending queue.
            self.status.set(tr('No connection: this needs Telegram. Your changes wait and are sent later.'))
            return
        if isinstance(exc, errors.PhoneCodeExpiredError):
            self.login_stage('phone')
        elif getattr(self, 'stage', None) == 'connecting':
            self.clear()
            ttk.Label(self.container, text='TeleGraph', style='Title.TLabel').pack(pady=30)
            ttk.Label(self.container, text=text, wraplength=650).pack(pady=20)
            retry = ttk.Button(self.container, text=tr('Reintentar'), command=lambda: self.call(self.service.connect(), self.login_stage, tr('Conectando a Telegram...')))
            retry.pack()
            self.buttons = [retry]
            if len(self.service.entries) > 1:
                other = next(k for k in self.service.entries if k != self.ui_account)
                ttk.Button(self.container, text=tr('Volver a otra cuenta'),
                           command=lambda: self.switch_account(other)).pack(pady=10)
        self.status.set(text)
        messagebox.showerror('TeleGraph', text, parent=self.root)

    def fit_initial_window(self, attempt=0):
        """1.5.0.1: open at a size where the whole interface fits, so the
        outer scrollbar is idle by default. Done once per window; after the
        user resizes, the scrollbar appears only when it is really needed."""
        if not getattr(self, '_auto_fit', True) or self.closed or self.closing:
            return
        try:
            self.root.update_idletasks()
            canvas = self.viewport.canvas
            if canvas.winfo_height() <= 1 and attempt < 10:
                self.root.after(150, lambda: self.fit_initial_window(attempt + 1))
                return
            if not getattr(self, '_auto_fit_watch', False):
                # Toolbars appear after the first draw (header, bot rows…): keep
                # growing to fit until the user resizes the window by hand.
                self._auto_fit_watch = True
                self._expected_size = (self.root.winfo_width(), self.root.winfo_height())
                def resized(event):
                    if event.widget is not self.root or not getattr(self, '_auto_fit', True):
                        return
                    expected = getattr(self, '_expected_size', None)
                    if expected and (abs(event.width - expected[0]) > 2 or abs(event.height - expected[1]) > 2):
                        self._auto_fit = False
                self.root.bind('<Configure>', resized, add='+')
            if self.root.state() in ('zoomed', 'withdrawn', 'iconic'):
                return
            content = self.viewport.content
            chrome_h = self.root.winfo_height() - canvas.winfo_height()
            chrome_w = self.root.winfo_width() - canvas.winfo_width()
            # The chat layout also keeps a minimum message area (viewport.minimum).
            need_h = max(content.winfo_reqheight(), self.viewport.minimum[1]) + chrome_h + 2
            need_w = max(self.root.winfo_width(), min(content.winfo_reqwidth(), self.viewport.minimum[0]) + chrome_w)
            limit_h = self.root.winfo_screenheight() - 90
            limit_w = self.root.winfo_screenwidth() - 40
            height = min(limit_h, max(self.root.winfo_height(), need_h))
            width = min(limit_w, need_w)
            if (width, height) == (self.root.winfo_width(), self.root.winfo_height()):
                return
            self._expected_size = (width, height)
            x = min(max(0, self.root.winfo_x()), max(0, self.root.winfo_screenwidth() - width - 8))
            y = min(max(0, self.root.winfo_y()), max(0, self.root.winfo_screenheight() - height - 60))
            self.root.geometry(f'{width}x{height}+{x}+{y}')
        except tk.TclError:
            pass

    def build_chats(self):
        self.clear()
        self.stage = 'ready'
        self.viewport.fit_to_window = True
        self.root.after(400, self.fit_initial_window)
        if getattr(self, '_chat_only', False):
            self.chat_page = ttk.Frame(self.container, padding=(4, 4))
            self.chat_page.pack(fill='both', expand=True)
            sidebar = None
            conversation = ttk.Frame(self.chat_page)
            conversation.pack(fill='both', expand=True)
            self.chat_conversation = conversation
            self.chat_page.bind('<Configure>', self.adapt_chat_layout)
        else:
            self.build_account_bar(self.container)
            self.notebook = ttk.Notebook(self.container)
            # Back on the Chats tab: messages that arrived meanwhile are now on screen.
            from .read_visibility import schedule as schedule_read
            self.notebook.bind('<<NotebookTabChanged>>', lambda _: schedule_read(self, 120), add='+')
            self.notebook.pack(fill='both', expand=True)
            self.chat_page = ttk.Frame(self.notebook, padding=(0, 4))
            self.story_page = ttk.Frame(self.notebook, padding=16)
            self.settings_page = ttk.Frame(self.notebook, padding=16)
            for page, label in [(self.chat_page, 'Chats'), (self.story_page, 'Historias'), (self.settings_page, 'Ajustes')]:
                self.notebook.add(page, text=tr(label))
            panes = ttk.Panedwindow(self.chat_page, orient='horizontal')
            panes.pack(fill='both', expand=True)
            self.chat_panes = panes
            from .pane_memory import install as remember_pane_share
            remember_pane_share(self, panes)
            sidebar = ttk.Frame(panes, width=280)
            panes.add(sidebar, weight=1)
            ttk.Label(sidebar, text=tr('Buscar chats'), style='Muted.TLabel').pack(anchor='w', pady=(0, 3))
            self.search = tk.StringVar()
            from .native_emoji import search_entry
            search_entry(sidebar,self,self.search)
            self.search.trace_add('write', lambda *_: self.render_chats())
            list_frame = ttk.Frame(sidebar)
            list_frame.pack(fill='both', expand=True)
            # 3.2: recent chat searches of this account under the field.
            from .recent_search_ui import RecentStrip, remember as remember_search
            self.recent_chat_searches = RecentStrip(self, sidebar, self.search, 'chats', before=list_frame)
            self.search.entry.bind('<Return>', lambda _: remember_search(self, 'chats', self.search.get()), add='+')
            self.chat_list = ttk.Treeview(list_frame, height=6, show='tree', selectmode='browse')
            self.chat_list.column('#0', width=245, minwidth=160, stretch=True)
            bar = ttk.Scrollbar(list_frame, orient='vertical', command=self.chat_list.yview)
            from .row_emoji import RowEmoji
            self.row_emoji = RowEmoji(self, self.chat_list)
            def scrolled(first,last):
                bar.set(first,last)
                self.request_avatars()
                self.row_emoji.refresh()
            self.chat_list.configure(yscrollcommand=scrolled)
            self.chat_list.bind('<Configure>',lambda _:self.request_avatars(),add='+')
            bar.pack(side='right', fill='y')
            # 1.4.1: long rows scroll horizontally and show a full-text hint.
            from .tree_fit import horizontal_bar, hover_full_text, fit_column
            self.chat_list_hbar = horizontal_bar(list_frame, self.chat_list)
            hover_full_text(self.chat_list)
            def rewrap(_=None):
                # Re-wrap rows once the list width settles (pane drag / resize).
                job = getattr(self, '_rewrap_job', None)
                if job is not None:
                    try: self.root.after_cancel(job)
                    except tk.TclError: pass
                def run():
                    self._rewrap_job = None
                    from .tree_fit import text_width
                    if text_width(self.chat_list) != getattr(self, '_chat_list_wrap_width', None):
                        self.render_chats()
                self._rewrap_job = self.root.after(120, run)
            self.chat_list.bind('<Configure>', rewrap, add='+')
            self.chat_list.pack(fill='both', expand=True)
            # 1.5.0.2: the list's frame keeps the size it asked for in 1.4.
            # A widened text column (long rows, horizontal scrolling) used to
            # raise this request and Tk moved the divider on every relayout
            # (tab switch, resize), so the list "changed size by itself".
            list_frame.configure(width=self.chat_list.winfo_reqwidth()+bar.winfo_reqwidth(),
                                 height=self.chat_list.winfo_reqheight())
            list_frame.pack_propagate(False)
            self.chat_list.bind('<<TreeviewSelect>>', self.choose_chat)
            self.chat_list.bind('<<TreeviewSelect>>', self.row_emoji.refresh, add='+')
            self.chat_list.bind('<Configure>', self.row_emoji.refresh, add='+')
            refresh = ttk.Button(sidebar, text=tr('Actualizar'), command=lambda: self.refresh(reconnect=True))
            refresh.pack(fill='x', pady=(10, 0))
            conversation = ttk.Frame(panes, padding=(8, 0, 0, 0))
            panes.add(conversation, weight=3)
            self.chat_sidebar, self.chat_conversation = sidebar, conversation
            self.compact_conversation = self.active is not None
            self.compact_button = ttk.Button(self.chat_page, text=tr('Chats / Conversation'), command=self.toggle_compact_panel)
            self.chat_page.bind('<Configure>', self.adapt_chat_layout)
        self.title = tk.StringVar(value=tr('Elige un chat'))
        self.chat_title_label=ttk.Label(conversation, textvariable=self.title, font=(FONT[0], 15, 'bold'))
        self.chat_title_label.pack(anchor='w', pady=(0, 12))
        history_frame = tk.Canvas(conversation, bg=BG, highlightthickness=0)
        self.history_canvas = history_frame
        history_frame.pack(fill='both', expand=True)
        self.pending_strip = ttk.Frame(conversation)
        self.history = tk.Text(history_frame, height=3, bg=BG, fg=GREEN, font=FONT, wrap='word',
            state='disabled', relief='flat', padx=8, pady=8, selectbackground=LINE,
            insertbackground=GREEN, borderwidth=1, highlightbackground=LINE, highlightthickness=1)
        history_bar = ttk.Scrollbar(history_frame, orient='vertical', command=self.history.yview)
        self.history_bar = history_bar
        self.history.configure(yscrollcommand=history_bar.set)
        history_bar.pack(side='right', fill='y')
        self.history.pack(fill='both', expand=True, padx=4, pady=4)
        self.history.tag_configure('sender', foreground=MUTED, font=(FONT[0], 10, 'bold'))
        self.history.tag_configure('outgoing', foreground=GREEN)
        self.attachment_text = tk.StringVar(value='')
        from .scrolling import FlowFrame
        attachment_bar = FlowFrame(conversation)
        self.attachment_bar = attachment_bar
        ttk.Button(attachment_bar, textvariable=self.attachment_text, command=self.attachment_manager).pack(side='left')
        if hasattr(self, 'preview_current_attachment'):
            ttk.Button(attachment_bar, text=tr('Preview'), command=self.preview_current_attachment).pack(side='left', padx=3)
        self.remove_button = ttk.Button(attachment_bar, text=tr('Quitar archivo'), command=self.remove_attachment)
        from .composer import Composer
        self.editor = Composer(conversation, self, height=2, bg=PANEL, fg=GREEN, font=FONT,
            insertbackground=GREEN, wrap='word', relief='flat', padx=8, pady=5,
            highlightbackground=LINE, highlightthickness=1, selectbackground=LINE)
        self.editor.pack(fill='x', pady=(4, 4))
        from .rtl_ui import align_composer
        align_composer(self.editor)
        self.draft_manager.bind()
        from .composer_keys import install as install_composer_keys
        install_composer_keys(self.editor, lambda: self.preferences.values, self.send)
        self.editor.bind('<Escape>', lambda _: self.history.focus_set() if self._chat_only else self.chat_list.focus_set())
        controls = ttk.Frame(conversation)
        self.composer_controls = controls
        controls.pack(fill='x')
        attach = ttk.Button(controls, text=tr('[+] Adjuntar'), command=self.pick_attachment)
        self.attach_button = attach
        attach.pack(side='left')
        self.advanced_button = ttk.Button(controls,text=tr('Más opciones'),command=self.open_advanced_menu)
        self.advanced_button.pack(side='left')
        self.progress = ttk.Progressbar(controls, length=110, mode='determinate', maximum=100)
        send = ttk.Button(controls, text=tr('Enviar >'), command=self.send)
        self.send_button = send
        send.pack(side='right')
        self.buttons = [attach, send, self.remove_button]
        self.setup_tools(conversation)
        self.build_feature_controls(sidebar, conversation)
        self.root.bind('<Control-o>', lambda _: self.pick_attachment())
        if sys.platform == 'darwin':
            self.root.bind('<Command-o>', lambda _: self.pick_attachment())
        self.root.bind('<F5>', lambda _: self.refresh(reconnect=True))
        self.render_messages()
        from .themes import apply_widget
        apply_widget(self.root)
        from .visual_effects import apply_text_effects
        apply_text_effects(self.root, self.preferences.values, {'text': GREEN})
        if hasattr(self, 'layout_runtime'):
            self.root.update_idletasks()
            self.layout_runtime.attach()

    def refresh_chat_window(self, reconnect=False):
        if self.closed or self.closing or getattr(self, '_refresh_pending', False):
            return
        account, peer = self._pinned_account, self._pinned_peer
        if account not in self.service.entries:
            self._parent_close = True
            self.active = None
            self.close()
            return
        backend = self.service.backend
        self._refresh_pending = True
        self._history_key, self._history_changes = (account, peer), []
        self._history_incoming = {}
        async def fetch():
            if not self.demo:
                if reconnect:
                    await self.service.reconnect(account)
                else:
                    await self.service.recover(account)
            return await asyncio.wait_for(backend.history(peer), 45)
        def current():
            return (not self.closed and not self.closing and account in self.service.entries
                    and (self.ui_account, self.active) == (account, peer)
                    and self.service.backend is backend)
        def loaded(messages):
            self._refresh_pending = False
            if not current(): return
            from .telegram_extras import reconcile_history
            # The server is authoritative after reconnect. Only merge push
            # messages received during this request, never the old UI snapshot.
            merged = {message.id: message for message in messages}
            merged.update(self._history_incoming)
            self.messages = reconcile_history(merged.values(), self._history_changes, peer)[-200:]
            self._history_incoming = {}
            self._history_key, self._history_changes = None, []
            self.render_messages()
            self.refresh_wallpaper()
            self.status.set(tr('Connected'))
            from .read_visibility import schedule as schedule_read
            schedule_read(self, 300)
            getattr(self, 'preview_failed', set()).clear()
        def failed(error):
            self._refresh_pending = False
            self._history_key, self._history_changes = None, []
            if current(): self.show_error(error)
        self.worker.submit(fetch(), loaded, failed)

    def refresh(self, reconnect=False):
        if getattr(self, '_chat_only', False):
            self.refresh_chat_window(reconnect)
            return
        if getattr(self,'_refresh_pending',False):return
        account=self.ui_account;backend=self.service.backend
        self._refresh_pending=True
        async def fetch():
            if not self.demo:
                if reconnect:
                    await self.service.reconnect(account)
                else:
                    await self.service.recover(account)
            return await asyncio.gather(asyncio.wait_for(backend.chats(),45),asyncio.wait_for(backend.folders(),15))
        def current():return account==self.ui_account and backend is self.service.backend and getattr(self,'stage','ready')=='ready' and not self.closed and not self.closing
        def loaded(result):
            self._refresh_pending=False
            if not current():return
            selected=next((item for item in self.chats if item.id==self.active),None)
            self.chats,self.folder_records=result
            self._chats_from_network=True
            # A public preview or a newly opened chat may not be a joined dialog.
            if selected is not None and not any(item.id==selected.id for item in self.chats):
                self.chats.append(selected)
            self.update_folder_picker();self.render_chats()
            self.status.set(tr('Connected'))
            from .preload import maybe_start
            maybe_start(self)
            if hasattr(self, 'draft_manager') and reconnect:
                self.draft_manager.pull(force=True)
            # Retrying failed previews is safe; never resend a user mutation.
            getattr(self,'preview_failed',set()).clear()
            from .offline_store import schedule_save
            schedule_save(self)
        def failed(exc):
            self._refresh_pending=False
            if not current():return
            from .pending_actions import transport_failure
            if transport_failure(exc) or self.connection_offline():
                # 1.5.3: keep showing the local copy; Recovery refreshes when back.
                self.status.set(tr('Offline: showing the copy saved on this device.') if self.chats else tr('Sin conexion'))
                return
            self.show_error(exc)
        self.status.set(tr('Cargando chats...'))
        self.worker.submit(fetch(),loaded,failed)

    def render_chats(self):
        if getattr(self, '_chat_only', False):
            return
        from .offline_store import schedule_save
        schedule_save(self)  # 1.5.3: at most one background save every few seconds.
        term = self.search.get().casefold()
        rows=[]
        self._chat_by_id={chat.id:chat for chat in self.chats}
        archive_view = bool(getattr(self, 'archive_view', False))
        folder = None if archive_view else self.selected_folder()
        compiled=compile_folder(folder)
        self.prepare_folder_tags()
        local_pins = self.local_pin_ids()
        from telethon import utils
        pins={utils.get_peer_id(p):i for i,p in enumerate(folder.pinned_peers)} if folder else {}
        local_rank = {peer: i for i, peer in enumerate(self.local_pins.values.get(self.ui_account, ())) if peer in local_pins}
        tails, emoji_rows = {}, {}
        for chat in sorted(self.chats, key=lambda c: (local_rank.get(c.id, len(local_rank)), pins.get(c.id,len(pins)) if folder else not c.pinned)):
            if not in_chat_list(chat, folder, compiled, archive_view):
                continue
            if term and term not in chat.name.casefold() and term not in single_line(chat.name).casefold():
                continue
            badge = f' [{chat.unread}]' if chat.unread else ''
            if self.drafts.get(chat.id, ('', None))[0]:
                from .interface_layout import caption
                badge += caption(' [Draft]', ' [Borrador]')
            from .chat_activity import mark as activity_mark
            tail = activity_mark(self, chat) + badge + self.folder_tags_text(chat)
            if hasattr(self, 'folder_tag_docs'):
                emoji_rows[str(chat.id)] = self.folder_tag_docs(chat)
            rows.append((str(chat.id),self.chat_selection_prefix(chat.id)+('[L] ' if chat.id in local_pins else '[*] ' if (chat.id in pins if folder else chat.pinned) else '') + self.text_display(chat.name, True) + tail))
            tails[str(chat.id)] = tail
        from .tree_fit import fit_column, wrap_label, text_width, fit_row_height
        width=text_width(self.chat_list)
        self.chat_list._full_labels={ident:label for ident,label in rows}
        compact=bool(self.preferences.values.get('compact'))
        laid_out=self.chat_list.winfo_width()>1
        if compact and laid_out:
            # Compact list: long rows continue on more lines (counter kept).
            rows=[(ident,wrap_label(self.chat_list,label,width,keep=tails.get(ident,''))) for ident,label in rows]
        # Normal list: one line; the column grows and scrolls left/right.
        # Not laid out yet: draw plain rows; <Configure> re-wraps at the real
        # width. Wrapping at 1 px changed the list's requested width and moved
        # the divider (compact list looked resized in 1.5.0).
        self._chat_list_wrap_width=width if laid_out else None
        fit_row_height(self.chat_list,[label for _,label in rows],26 if compact else 38,'Chats.Treeview')
        sync_tree_rows(self.chat_list,rows)
        if laid_out:fit_column(self.chat_list,(label for _,label in rows))
        if getattr(self, 'row_emoji', None) is not None:
            self.row_emoji.set_rows(emoji_rows)
        displayed=getattr(self,'_avatar_displayed',{})
        present={int(ident) for ident,_ in rows}
        for key in list(displayed):
            if key[0]==self.ui_account and key[1] not in present:displayed.pop(key,None)
        if self.active is not None and self.chat_list.exists(str(self.active)) and self.chat_list.selection()!=(str(self.active),):
            self.chat_list.selection_set(str(self.active))

        if hasattr(self.folder_picker, "paint"): self.folder_picker.paint()
        if hasattr(self, "preview_cache"): self.request_avatars()

    def choose_chat(self, event=None):
        if getattr(self,'selection_kind',None)=='chats':return
        selected = self.chat_list.selection()
        if not selected:
            return
        chat_id = int(selected[0])
        if getattr(self, 'search', None) is not None and self.search.get().strip():
            from .recent_search_ui import remember as remember_search
            remember_search(self, 'chats', self.search.get())
        if chat_id == self.active:
            # Clicking the chat that is already open: look again (1.5.0.2).
            if hasattr(self, 'preview_cache'):
                from .read_visibility import schedule as schedule_read
                schedule_read(self, 50)
            return
        if self.busy:
            if self.active is not None and self.chat_list.exists(str(self.active)):
                self.chat_list.selection_set(str(self.active))
            else:
                self.chat_list.selection_remove(*selected)
            return
        self.save_custom_draft()
        if hasattr(self, 'draft_manager'):
            self.draft_manager.snapshot()
            self.draft_manager.persist_async()
        if self.active is not None:
            self.drafts[self.active] = (self.editor.get('1.0', 'end-1c'), self.attachment)
        old_id, old_messages = self.active, self.messages
        # 1.4.1: the last messages of each chat stay in memory, so reopening a
        # chat is instant and still shows its messages while offline.
        cache = self.__dict__.setdefault('_history_cache', {})
        account = self.ui_account
        if old_id is not None and old_messages:
            cache[(account, old_id)] = list(old_messages)[-200:]
            from .resources import history_chats
            while len(cache) > history_chats(40): cache.pop(next(iter(cache)))
        cached = cache.get((account, chat_id))
        opening = next((item for item in getattr(self, 'chats', ()) if item.id == chat_id), None)
        if getattr(opening, 'unread', 0):
            # Unread messages: wait for the fresh history and the jump to the
            # first unread before reading anything (released in loaded/failed).
            self._read_hold_until = time.monotonic() + 8.0
        self.active, self.messages = chat_id, list(cached) if cached else []
        self._history_key, self._history_changes = (self.ui_account, chat_id), []
        self.restore_draft()
        self.render_messages()
        def loaded(messages):
            if self.active != chat_id or self.ui_account != account:
                return  # The user moved on while this chat was loading.
            merged = {m.id: m for m in messages + [m for m in self.messages if not cached or m.id > max((c.id for c in messages), default=0)]}
            from .telegram_extras import reconcile_history
            self.messages = reconcile_history(merged.values(), self._history_changes, chat_id)[-200:]
            from .offline_store import schedule_save
            schedule_save(self)
            self._history_key, self._history_changes = None, []
            self._read_hold_until = 0
            self.render_messages()
            if getattr(self, '_canvas_chat_view', False) and hasattr(self, 'bubble_view'):
                from .transitions import slide_in
                slide_in(self, self.bubble_view)
            # 3.3: a forum opens its topics, as Telegram does.
            from .desktop_forums import chat_flags, open_topics
            if chat_flags(next((item for item in getattr(self, 'chats', ()) if item.id == chat_id), None))[0]:
                self.root.after_idle(lambda: open_topics(self, chat_id) if self.active == chat_id else None)
            # 1.4.1: open at the first unread message, as the official apps do,
            # so unread messages below the viewport are not marked as read.
            chat = next((item for item in getattr(self, 'chats', ()) if item.id == chat_id), None)
            from .read_visibility import first_unread_id, open_at_first_unread
            first = first_unread_id(self.messages, getattr(chat, 'unread', 0)) if chat is not None else None
            if first is not None and first != (self.messages[-1].id if self.messages else None):
                self._read_hold_until = time.monotonic() + 1.0  # Released once the view is in place.
                def jump():
                    if self.active == chat_id:
                        open_at_first_unread(self, first)
                    self._read_hold_until = 0
                    from .read_visibility import schedule as schedule_read
                    schedule_read(self, 120)
                try:self.root.after_idle(jump)
                except (tk.TclError, AttributeError):self._read_hold_until = 0
            self.refresh_wallpaper()
            self.compact_conversation = True
            self.adapt_chat_layout()
            self.status.set(tr('Chat abierto. Escribe o adjunta un archivo.'))
            if hasattr(self, 'preview_cache'):
                from .read_visibility import schedule as schedule_read
                schedule_read(self, 300)
            self.editor.focus_set()
        def failed(exc):
            self._history_key, self._history_changes = None, []
            self._read_hold_until = 0
            if cached and self.active == chat_id and self.ui_account == account:
                # Keep the chat open on what we already have; writing still works
                # (messages wait in the send queue) and Refresh reloads it.
                from .auth import error_message
                self.status.set(error_message(exc) + ' ' + tr('Showing saved messages.'))
                return
            if self.active != chat_id or self.ui_account != account:
                return
            self.active, self.messages = old_id, old_messages
            self.restore_draft()
            self.render_chats()
            self.render_messages()
            self.show_error(exc)
        self.call(self.service.backend.history(chat_id), loaded, tr('Cargando mensajes...'), failed, timeout=45)

    def restore_draft(self):
        manager = getattr(self, 'draft_manager', None)
        if manager is not None:
            manager._remote_applying = True
        try:
            text, self.attachment = self.drafts.get(self.active, ('', None))
            self.editor.configure(state='normal')
            self.editor.delete('1.0', 'end')
            self.editor.insert('1.0', text)
            self.restore_custom_draft()
            if hasattr(self, 'update_reply'): self.update_reply()
            self.update_attachment()
            self.update_chat_capabilities()
            chat = next((c for c in self.chats if c.id == self.active), None)
            self.title.set(self.text_display(chat.name, True) if chat else tr('Elige un chat'))
            if hasattr(self.editor, 'edit_modified'):
                self.editor.edit_modified(False)
            if hasattr(self, 'pending_strip'): self.render_pending()
        finally:
            if manager is not None:
                manager._remote_applying = False

    def incoming(self, item):
        chat_id, message = item
        if (getattr(self, '_chat_only', False) and
                getattr(self, '_history_key', None) == (self.ui_account, chat_id)):
            self._history_incoming[message.id] = message
        duplicate = chat_id == self.active and any(m.id == message.id for m in self.messages)
        if chat_id == self.active and not duplicate:
            follow = (self.bubble_view if getattr(self,'_canvas_chat_view',self.preferences.values['bubbles']) and hasattr(self,'bubble_view') else self.history).yview()[1] >= 0.98
            window_size=max(200,len(self.messages))
            self.messages = sorted(self.messages + [message], key=lambda m: m.id)
            # Keep the live tail bounded while preserving extra pages explicitly
            # loaded by the user. Do not evict history being read above the tail.
            if follow:self.messages=self.messages[-window_size:]
            self.request_message_render(follow)
            if hasattr(self, 'preview_cache'):
                from .read_visibility import schedule as schedule_read
                schedule_read(self, 300)
        if not message.outgoing and not duplicate:
            for chat in self.chats:
                if chat.id == chat_id:
                    chat.unread += 1
                    if hasattr(self, 'chat_list') and self.chat_list.exists(str(chat.id)):
                        from .chat_activity import mark as activity_mark
                        self.render_chats()
                    break

    def request_message_render(self,follow=False):
        """Collapse bursts of Telegram updates into one frame without dropping data."""
        from .ui_work import FrameJob
        if getattr(self,'closed',False) or getattr(self,'closing',False):return
        self._message_render_follow=getattr(self,'_message_render_follow',False) or follow
        if getattr(self,'_message_render_job',None) is None:
            def flush():
                follow=self._message_render_follow
                self._message_render_follow=False
                self.render_messages(follow)
            self._message_render_job=FrameJob(self.root,flush)
        self._message_render_job.request()

    def render_plain_history(self,follow):
        """Retain unchanged native-text messages; redraw the changed suffix only."""
        if not isinstance(self.history,tk.Text) or not self.messages or getattr(self,'selection_kind',None):return False
        from .translated_view import presentation, clear_buttons
        from .animated_emojis import animated_content, ensure_pack
        from .bubbles import message_signature
        from .advanced_features import feature_enabled
        plain_entities=(types.MessageEntityUrl,types.MessageEntityTextUrl,types.MessageEntityMention,
                        types.MessageEntityMentionName,types.MessageEntityHashtag,types.MessageEntityCashtag)
        for message in self.messages:
            if message.media or message.reply_to_id or message.reply_markup:return False
            if any(not isinstance(entity,plain_entities) for entity in message.entities):return False
            content,key,_=presentation(self,message)
            if key or any(isinstance(entity,types.MessageEntityCustomEmoji)
                          for entity in animated_content(self,content).entities):return False
        context=(self.history,self.ui_account,self.active,self.font_family,feature_enabled(self,'links'),
                 tuple(sorted(self.preferences.values.items())))
        state=getattr(self,'_plain_render_state',None)
        position=self.history.yview()[0]
        self.history.configure(state='normal')
        from .day_separators import day_headers
        headers=day_headers(self.messages)
        # The day divider drawn before a message is part of its node: if the
        # previous message changes day (or "Today" becomes "Yesterday") that
        # node is redrawn, every other retained node stays untouched.
        signatures=[(message_signature(message),header) for message,header in zip(self.messages,headers)]
        ids=[message.id for message in self.messages]
        if state is None or state['context']!=context:
            clear_text_actions(self.history);clear_buttons(self);self.clear_inline_buttons()
            self.preview_generation=getattr(self,'preview_generation',0)+1;self.preview_images={}
            self.history.delete('1.0','end')
            for mark in self.history.mark_names():
                if mark.startswith(('preview_','message_')):self.history.mark_unset(mark)
            for tag in self.history.tag_names():
                if tag.startswith(('link_','tools_','media_','msg_','lightbox_','quote_','emoji_pack_','sender_profile_')):self.history.tag_delete(tag)
            nodes=[]
        else:
            nodes=state['nodes']
            old_ids=[node[0] for node in nodes]
            trim=old_ids.index(ids[0]) if ids[0] in old_ids else len(nodes)
            keep=0
            while trim+keep<len(nodes) and keep<len(ids) and nodes[trim+keep][:2]==(ids[keep],signatures[keep]):keep+=1
            retained=nodes[trim:trim+keep]
            removed=nodes[:trim]+nodes[trim+keep:]
            if keep:
                if trim:self.history.delete('1.0',f'message_{retained[0][0]}')
                # Keep Tk's mandatory final newline; deleting through ``end``
                # also consumes the preceding separator when this is a line start.
                if trim+keep<len(nodes):self.history.delete(f'message_{nodes[trim+keep][0]}','end-1c')
            else:self.history.delete('1.0','end')
            bindings=vars(self.history).get('_text_action_bindings',{})
            for ident,_,links in removed:
                for tag in (*links,f'msg_{ident}',f'sender_profile_{ident}'):
                    binding=bindings.pop((tag,'<Button-1>'),None)
                    if binding:self.history.tag_unbind(tag,'<Button-1>',binding)
                    self.history.tag_delete(tag)
                self.history.mark_unset(f'message_{ident}')
            nodes=retained
        for message,signature in zip(self.messages[len(nodes):],signatures[len(nodes):]):
            start=self.history.index('end-1c')
            mark=f'message_{message.id}'
            self.history.mark_set(mark,start);self.history.mark_gravity(mark,'left')
            if signature[1]:self.insert_day_divider(signature[1])
            self.history.insert('end',f'[{message_time(message,self.preferences.values)}] ','sender',self.text_display(message.sender,True),
                ('sender',f'sender_profile_{message.id}'),
                (' ✓✓' if message.read else ' ✓' if message.outgoing else '')+'\n','sender')
            before=getattr(self,'_link_counter',0)
            self.insert_message_content(message)
            self.history.insert('end','\n')
            self.history.tag_add(f'msg_{message.id}',start,'end-1c')
            links=tuple(f'link_{number}' for number in range(before+1,getattr(self,'_link_counter',0)+1))
            nodes.append((message.id,signature,links))
        self._plain_render_state={'context':context,'nodes':nodes}
        self._classic_rendered=True
        from .rtl_ui import align_text
        align_text(self.history)
        self.history.configure(state='disabled')
        if follow:self.history.see('end')
        else:self.history.yview_moveto(position)
        self.schedule_translations();self.update_modern_view(follow);ensure_pack(self)
        return True

    def insert_day_divider(self,label):
        """Centred date divider (official clients show it between days)."""
        if 'day_divider' not in self.history.tag_names():
            self.history.tag_configure('day_divider',justify='center',foreground=MUTED,spacing1=6,spacing3=6)
        self.history.insert('end',f'— {label} —\n','day_divider')

    def render_messages(self, follow=True):
        if hasattr(self, 'preview_cache') and getattr(self, 'active', None) is not None and not getattr(self, 'closing', False):
            # Every draw (classic, incremental or canvas) re-checks what is on
            # screen once it has settled (1.5.0.1).
            from .read_visibility import schedule as schedule_read
            schedule_read(self, 250)
        from .translated_view import presentation, clear_buttons, insert_button
        from .animated_emojis import animated_content, ensure_pack
        job=getattr(self,'_message_render_job',None)
        if job is not None:job.cancel()
        self._message_render_follow=False
        from .interface_background import chat_backdrop
        from .visual_effects import text_effects_enabled
        from .line_breaking import needs_canvas
        canvas_view=bool(self.preferences.values['bubbles'] or chat_backdrop(self) or text_effects_enabled(self.preferences.values) or needs_canvas(self.preferences.values)) if hasattr(self,'preferences') else False
        if not canvas_view and isinstance(self.history,tk.Text) and self.render_plain_history(follow):return
        self._plain_render_state=None
        clear_text_actions(self.history)
        clear_buttons(self)
        if hasattr(self, 'clear_inline_buttons'): self.clear_inline_buttons()
        self.preview_generation = getattr(self, "preview_generation", 0) + 1
        self.preview_images = {}
        if hasattr(self,'bubble_view') and hasattr(self,'preferences'):
            from .interface_background import chat_backdrop
            from .visual_effects import text_effects_enabled
            from .line_breaking import needs_canvas
            if self.preferences.values['bubbles'] or chat_backdrop(self) or text_effects_enabled(self.preferences.values) or needs_canvas(self.preferences.values):
                if getattr(self,'_classic_rendered',False):
                    self.history.configure(state='normal');self.history.delete('1.0','end');self.history.configure(state='disabled')
                    self._classic_rendered=False
                self.schedule_translations();self.update_modern_view(follow);ensure_pack(self)
                return
        self._classic_rendered=True
        previews = []
        if hasattr(self.history, 'mark_names'):
            for mark in self.history.mark_names():
                if mark.startswith(('preview_', 'message_')): self.history.mark_unset(mark)
        position = self.history.yview()[0]
        self.history.configure(state='normal')
        self.history.delete('1.0', 'end')
        if hasattr(self.history, 'tag_names'):
            for tag in self.history.tag_names():
                if tag.startswith(('link_', 'tools_', 'media_', 'msg_', 'lightbox_', 'quote_', 'emoji_pack_', 'sender_profile_')): self.history.tag_delete(tag)
        if not self.messages:
            self.history.insert('end', tr('Haz clic en un chat para abrirlo.') if self.active is None else tr('No hay mensajes en este chat.'))
        by_id={message.id:message for message in self.messages}
        from .day_separators import day_headers
        for message,day_header in zip(self.messages,day_headers(self.messages)):
            message_start=self.history.index('end-1c')
            self.history.mark_set(f'message_{message.id}',message_start)
            self.history.mark_gravity(f'message_{message.id}','left')
            if day_header:self.insert_day_divider(day_header)
            if message.reply_to_id:
                quote=by_id.get(message.reply_to_id) or getattr(self,'reply_cache',{}).get((self.ui_account,self.active,message.reply_to_id))
                tag=f'quote_{message.id}'
                self.history.tag_configure(tag,foreground=MUTED,underline=True)
                bind_text_action(self.history,tag,'<Button-1>',lambda e,mid=message.reply_to_id:self.jump_message(mid))
                self.history.insert('end','↪ ',tag)
                from .rich_preview import preview_runs
                text=(quote.raw_text if quote.raw_text is not None else quote.text) if quote else '#'+str(message.reply_to_id)
                for index,(value,doc) in enumerate(preview_runs(text,getattr(quote,'entities',()),90)):
                    if doc:
                        mark=f'preview_quote_{message.id}_{index}'
                        self.history.mark_set(mark,'end-1c'); self.history.mark_gravity(mark,'left')
                        self.history.insert('end','◇',tag)
                        self.emoji_at(doc,mark,self.preview_generation)
                    else:self.history.insert('end',value,tag)
                self.history.insert('end','\n')
            marker=('☑ ' if self.message_selected(message.id) else '☐ ') if getattr(self,'selection_kind',None)=='messages' else ''
            self.history.insert('end', marker+f'[{message_time(message,self.preferences.values)}] ', 'sender')
            self.history.insert('end', self.text_display(message.sender, True), ('sender',f'sender_profile_{message.id}'))
            self.history.insert('end', (' ✓✓' if message.read else ' ✓' if message.outgoing else '') + (' ↪ #' + str(message.reply_to_id) if message.reply_to_id else '') + '\n', 'sender')
            body, translation_key, translation_label = presentation(self, message)
            body=animated_content(self,body) if hasattr(self,'preferences') else body
            if hasattr(self, 'insert_message_content'): self.insert_message_content(body)
            else: self.history.insert('end', self.text_display(body.text) + '\n', 'outgoing' if message.outgoing else '')
            insert_button(self, translation_key, translation_label)
            if message.media:
                tag = f'media_{message.id}'
                self.history.tag_configure(tag, foreground=GREEN, underline=True)
                bind_text_action(self.history,tag, '<Button-1>', lambda event, item=message: self.view_message_media(item))
                self.history.insert('end', (tr('Play') if message.media_kind == 'audio' else tr('[Ver / guardar archivo]')) + '\n', tag)
                from .preferences import shows_preview
                if hasattr(self, 'preview_cache') and shows_preview(self.preferences.values, message.media_kind) and message.media_kind != 'audio':
                    mark = f'preview_{message.id}'
                    self.history.mark_set(mark, 'end-1c')
                    self.history.mark_gravity(mark, 'left')
                    self.history.insert('end', '\n')
                    previews.append((message, mark, self.preview_generation))
            if hasattr(self, 'insert_bot_buttons'): self.insert_bot_buttons(message)
            self.history.insert('end', '\n')
            self.history.tag_add(f'msg_{message.id}',message_start,'end-1c')
            if self.message_selected(message.id):
                self.history.tag_configure(f'msg_{message.id}',background=LINE)
        if getattr(self,'selection_kind',None)=='messages':
            for tag in self.history.tag_names():
                if tag.startswith(('link_','quote_','media_','lightbox_','emoji_pack_')):self.history.tag_unbind(tag,'<Button-1>')
        from .rtl_ui import align_text
        align_text(self.history)
        self.history.configure(state='disabled')
        if follow:
            self.history.see('end')
        else:
            self.history.yview_moveto(position)
        for item in previews: self.schedule_preview(*item)
        if hasattr(self, 'chat_translations'): self.schedule_translations()
        if hasattr(self,'bubble_view'): self.update_modern_view(follow)
        if hasattr(self,'preferences') and hasattr(self,'demo'):ensure_pack(self)

    def enter_send(self, event):
        if event.state & 0x1 or not self.preferences.values['enter_send']:
            return None
        self.send()
        return 'break'

    def pick_attachment(self):
        if self.busy:
            return
        from .chat_capabilities import chat_capabilities
        caps=chat_capabilities(self)
        if not self.demo and not any(caps.allows('send_' + kind) for kind in ('photos','videos','docs','audios','gifs')):
            return
        if self.active is None:
            self.status.set(tr('Primero elige un chat.'))
            return
        chat_id, account = self.active, self.ui_account
        options={}
        if not self.demo and not caps.allows('send_docs'):
            options['filetypes']=[(tr(title),extensions) for action,title,extensions in (
                ('send_photos','Photos','*.jpg *.jpeg *.png *.webp'),
                ('send_videos','Videos','*.mp4 *.webm *.mov *.mkv *.avi'),
                ('send_gifs','GIF','*.gif'),('send_audios','Audio','*.mp3 *.m4a *.ogg *.flac *.wav *.aac')) if caps.allows(action)]
        filenames = filedialog.askopenfilenames(parent=self.root, title=tr('Elegir archivo'),**options)
        if filenames and not self.busy and (self.ui_account,self.active)==(account,chat_id):
            self.prepare_attachments(filenames)

    def update_attachment(self):
        if hasattr(self, 'draft_manager'):
            self.draft_manager.changed()
        from .attachments import paths_in
        paths=paths_in(self.attachment)
        self.attachment_text.set((tr('[Archivo] ')+single_line(paths[0].name)) if len(paths)==1 else tr('Attachments')+f' ({len(paths)})' if paths else '')
        if self.attachment:
            if hasattr(self, 'attachment_bar'): self.attachment_bar.pack(fill='x', before=self.editor, pady=2)
            self.remove_button.pack(side='right')
        else:
            self.remove_button.pack_forget()
            if hasattr(self, 'attachment_bar'): self.attachment_bar.pack_forget()

    def remove_attachment(self):
        if not self.busy:
            self.attachment = None
            self.update_attachment()

    def upload_progress(self, value):
        if self.closing or self.closed:
            return
        self.progress['value'] = value
        self.status.set(tr('Subiendo archivo: ') + f'{value}%')

    def send(self, silent=False, schedule=None):
        if self.busy or self.active is None:
            return
        account=getattr(self,'ui_account',None)
        text, path, chat_id = self.editor.get('1.0', 'end-1c'), self.attachment, self.active
        from .chat_capabilities import chat_capabilities
        if not self.demo:
            caps = chat_capabilities(self)
            if not caps.writable or not path and not caps.allows('send_text') or schedule is not None and not caps.allows('schedule'):
                self.update_chat_capabilities()
                return
        custom_spans = self.snapshot_custom()
        format_spans = self.snapshot_formats()
        if not text.strip() and path is None:
            return
        limit = 1024 if path else 4096
        if len(text.encode('utf-16-le')) // 2 > limit:
            self.status.set(tr('Texto demasiado largo. Limite: ') + str(limit))
            return
        from .attachments import paths_in
        paths=paths_in(path)
        from .attachments import attachments_allowed
        if paths and not attachments_allowed(self,paths):return
        if getattr(self, 'outbox', None) is not None:
            # 1.4.1: accept instantly; the queue delivers when Telegram answers.
            self.queue_send(account, chat_id, text, paths, format_spans, custom_spans, silent, schedule)
            return
        if path:
            self.progress_value = -1
            self.progress['value'] = 0
            self.progress.pack(side='left', padx=12)
            def progress(sent, total):
                value = min(100, int(sent * 100 / total)) if total else 0
                if value != self.progress_value:
                    self.progress_value = value
                    self.worker.events.put((self.upload_progress, value))
            operation = self.service.backend.send_batch(chat_id,paths,text,format_spans,custom_spans,progress,reply_to=getattr(self,'reply_drafts',{}).get((self.ui_account,chat_id)),silent=silent,schedule=schedule) if len(paths)>1 else self.service.backend.send_custom(chat_id, text, custom_spans, path, progress) if custom_spans else self.service.backend.send_attachment(chat_id, path, progress, caption=text)
        else:
            operation = self.service.backend.send_custom(chat_id, text, custom_spans) if custom_spans else self.service.backend.send(chat_id, text)
        reply_to = getattr(self, 'reply_drafts', {}).get((getattr(self, 'ui_account', None), chat_id))
        photo = len(paths)==1 and paths[0].suffix.lower() in ('.jpg','.jpeg','.png','.webp')
        if len(paths)<=1 and (format_spans or reply_to or photo or silent or schedule) and not self.demo:
            operation.close()
            operation = self.service.backend.send_formatted(chat_id, text, format_spans, custom_spans, path, progress if path else None, reply_to=reply_to, as_photo=bool(photo), silent=silent, schedule=schedule)
        def done(message):
            if getattr(self,'ui_account',None)!=account:
                self.progress.pack_forget();return
            self.stop_typing()
            getattr(self, 'reply_drafts', {}).pop((self.ui_account, chat_id), None)
            if hasattr(self, 'update_reply'): self.update_reply()
            self.progress.pack_forget()
            if hasattr(self, 'format_drafts'): self.format_drafts.pop((self.ui_account, chat_id), None)
            self.format_tags = {}
            if self.active == chat_id:
                self.editor.delete('1.0', 'end')
                if hasattr(self.editor, 'edit_modified'):
                    self.editor.edit_modified(False)
                self.attachment = None
                self.update_attachment()
            self.drafts.pop(chat_id, None)
            if hasattr(self, 'draft_manager'):
                self.draft_manager.sent(account, chat_id)
            if hasattr(self, "rich_drafts"): self.rich_drafts.pop((self.ui_account, chat_id), None)
            self.custom_tags = {}
            if self.active == chat_id:
                if schedule is None:
                    from .interface_windows import publish_local_message
                    for item in message if isinstance(message,list) else [message]:
                        publish_local_message(self, account, chat_id, item)
                    self.history.see('end')
            self.status.set(tr('Scheduled messages') if schedule is not None else tr('Enviado.'))
        def failed(exc):
            self.progress.pack_forget()
            self.status.set(error_message(exc) + tr(' Borrador conservado; revisa el chat antes de reintentar.'))
        self.call(operation, done, tr('Enviando...'), failed,timeout=None if path else 90)

    def queue_send(self, account, chat_id, text, paths, format_spans, custom_spans, silent=False, schedule=None):
        from .outbox import Pending
        reply_to = getattr(self, 'reply_drafts', {}).get((account, chat_id))
        item = Pending(account=account, peer=chat_id, text=text, paths=[str(value) for value in paths],
                       format_spans=[list(span) for span in format_spans],
                       custom_spans=[list(span) for span in custom_spans], reply_to=reply_to,
                       silent=bool(silent), schedule=schedule.isoformat() if schedule is not None else None)
        # Same composer reset a successful send performed before 1.4.1.
        self.stop_typing()
        getattr(self, 'reply_drafts', {}).pop((account, chat_id), None)
        if hasattr(self, 'update_reply'): self.update_reply()
        if hasattr(self, 'format_drafts'): self.format_drafts.pop((account, chat_id), None)
        self.format_tags = {}
        if self.active == chat_id:
            self.editor.delete('1.0', 'end')
            if hasattr(self.editor, 'edit_modified'):
                self.editor.edit_modified(False)
            self.attachment = None
            self.update_attachment()
        self.drafts.pop(chat_id, None)
        if hasattr(self, 'draft_manager'):
            self.draft_manager.sent(account, chat_id)
        if hasattr(self, "rich_drafts"): self.rich_drafts.pop((account, chat_id), None)
        self.custom_tags = {}
        self.outbox.add(item)
        self.status.set(tr('Sin conexion') + ' · ' + tr('Pending: it will be sent when the connection returns.') if self.connection_offline() else tr('Enviando...'))
        try:self.history.see('end')
        except (tk.TclError, AttributeError):pass

    def outbox_changed(self, account, peer):
        if self.closed or self.closing:return
        if account == getattr(self, 'ui_account', None) and peer == self.active:
            if not getattr(self, '_pending_render_job', None):
                def run():
                    self._pending_render_job = None
                    self.render_pending()
                self._pending_render_job = self.root.after_idle(run)

    def render_pending(self):
        strip = getattr(self, 'pending_strip', None)
        if strip is None or not strip.winfo_exists():return
        for child in strip.winfo_children():child.destroy()
        outbox = getattr(self, 'outbox', None)
        items = outbox.pending(self.ui_account, self.active) if outbox is not None and self.active is not None else []
        if not items:
            strip.pack_forget();return
        from .outbox import CLOCK, FAILED
        for item in items:
            row = ttk.Frame(strip);row.pack(fill='x', pady=1)
            when = time.strftime('%H:%M', time.localtime(item.created))
            if item.state == 'failed':
                mark = f'{FAILED} ' + tr('Not sent') + (f' · {item.error}' if item.error else '')
            elif item.state == 'sending':
                mark = CLOCK + (f' {item.progress}%' if item.paths and item.progress >= 0 else '')
            else:
                mark = CLOCK + ' ' + tr('Pending')
            label = ttk.Label(row, text=f'{tr("Tu")} · {when} {mark}\n{self.text_display(item.preview(), False)}',
                              style='Muted.TLabel' if item.state != 'failed' else 'TLabel', justify='left')
            label.pack(side='left', fill='x', expand=True)
            def wrap(event, label=label):
                try:label.configure(wraplength=max(120, event.width - 20))
                except tk.TclError:pass
            row.bind('<Configure>', wrap, add='+')
            buttons = ttk.Frame(row);buttons.pack(side='right')
            if item.state == 'failed':
                ttk.Button(buttons, text=tr('Reintentar'), command=lambda item=item: self.outbox.retry(item)).pack(side='left')
                ttk.Button(buttons, text=tr('Edit'), command=lambda item=item: self.edit_pending(item)).pack(side='left')
            if item.state != 'sending':
                ttk.Button(buttons, text=tr('Delete'), command=lambda item=item: self.outbox.remove(item)).pack(side='left')
        try:
            strip.pack(fill='x', pady=(2, 0), after=self.history_canvas)
        except (tk.TclError, AttributeError):
            strip.pack(fill='x', pady=(2, 0))

    def edit_pending(self, item):
        if item.state != 'failed' or self.active != item.peer or item.account != self.ui_account:return
        self.outbox.remove(item)
        if not self.editor.get('1.0', 'end-1c').strip():
            self.editor.delete('1.0', 'end')
            self.editor.insert('1.0', item.text)
        else:
            self.editor.insert('end', '\n' + item.text)
        if item.paths and self.attachment is None:
            from pathlib import Path
            self.attachment = Path(item.paths[0]) if len(item.paths) == 1 else [Path(value) for value in item.paths]
            self.update_attachment()
        self.editor.focus_set()

    def refresh_open_history(self, account, peer):
        if account != self.ui_account or peer != self.active or self.closed:return
        backend = self.service.backend
        def loaded(messages):
            if account != self.ui_account or peer != self.active:return
            merged = {m.id: m for m in self.messages}
            merged.update({m.id: m for m in messages})
            self.messages = sorted(merged.values(), key=lambda m: m.id)[-max(200, len(self.messages)):]
            self.request_message_render(True)
        self.worker.submit(asyncio.wait_for(backend.history(peer), 30), loaded, lambda _: None)

    def close(self):
        if self.closing:
            return
        if not getattr(self, '_parent_close', False) and (self.busy or any(view.busy for view in getattr(self, '_app_windows', ()))) and self.stage == 'ready':
            panel=getattr(self,'_app_lock_panel',None)
            parent=panel.window if panel is not None else self.root
            if not messagebox.askyesno(APP_NAME, tr('Hay una operacion en curso. Cerrar la app?'), parent=parent):
                return
        if hasattr(self, 'draft_manager'):
            try:
                self.draft_manager.capture_close()
                for view in tuple(getattr(self, '_app_windows', ())):
                    if not view.closed:
                        view.draft_manager.capture_close()
            except (OSError, ValueError) as exc:
                self.show_error(exc)
                return
        if self.stage == 'ready' and not getattr(self, '_chat_only', False):
            from .offline_store import save_now
            save_now(self, wait=True)
        self.closing = True
        self._close_started = time.monotonic()
        if getattr(self, 'outbox', None) is not None:
            self.outbox.unsubscribe(self.outbox_changed)
            self.outbox.save()
        if getattr(self, '_linked_owner', None) is not None:
            self._view_generation = getattr(self, '_view_generation', 0) + 1
            self.worker.cancel_pending()
        from .interface_windows import close_chat_windows
        close_chat_windows(self)
        self.cancel_global_search()
        job=getattr(self,'_message_render_job',None)
        if job is not None:job.cancel()
        self.inline_notice.close()
        self.cancel_qr()
        self.stop_typing()
        for job in getattr(self, 'audio_jobs', []): job.stop()
        if getattr(self, 'background', None): self.background.stop()
        self.status.set(tr('Cerrando...'))
        async def close_connections():
            if hasattr(self, 'draft_manager'):
                await self.draft_manager.flush_close()
                try:
                    await asyncio.wait_for(self.draft_manager.sync_pending(), 2)
                except Exception:
                    pass  # Atomic local backup will retry on the next login.
            for window in tuple(getattr(self, '_app_windows', ())):
                future = getattr(window, '_shutdown_future', None)
                if future is not None:
                    await asyncio.wrap_future(future)
            try:
                if getattr(self, '_linked_owner', None) is None:
                    cleanup = getattr(self, 'close_push_notifications', None)
                    if cleanup is not None:
                        await asyncio.wait_for(cleanup(), 5)
            finally:
                if getattr(self, '_linked_owner', None) is None and not getattr(self, 'demo', True):
                    # 1.5.4: a temporary independent window forgets its logins.
                    from .saved_windows import temporary, sign_out_services
                    if getattr(self.service, 'root', None) is not None and temporary(self.service.root):
                        await sign_out_services(self.service)
                # Persist/disconnect sessions even if push deregistration fails.
                await self.service.close()
        self._shutdown_future = self.worker.submit(close_connections(), self.finish_close, self.finish_close)
        # Allow bounded draft sync, push deregistration and media shutdown.
        self.root.after(15000, lambda: self.finish_close(None))

    def finish_close(self, _):
        if self.closed or not self.closing:
            return
        manager = getattr(self, 'draft_manager', None)
        # Windows only (1.4.1): a draft write that never completes must not keep
        # the app open forever; its atomic local backup is retried at login.
        stuck = sys.platform == 'win32' and time.monotonic() - getattr(self, '_close_started', time.monotonic()) > 25
        if not stuck and any(view.draft_manager.close_pending for view in getattr(self, '_app_windows', ())):
            self.root.after(100, lambda:self.finish_close(None))
            return
        if not stuck and manager is not None and manager.close_pending:
            self.root.after(100, lambda:self.finish_close(None))
            return
        children = tuple(getattr(self, '_app_windows', ()))
        child_error = next((view.draft_manager.close_error for view in children
                            if view.draft_manager.close_error is not None), None)
        if child_error is not None:
            self.closing = False
            for view in children:
                view.closing = False
                view._parent_close = False
            self.show_error(child_error)
            return
        if manager is not None and manager.close_error is not None:
            error, manager.close_error = manager.close_error, None
            self.closing = False
            self.show_error(error)
            return  # Retain temporary media so the user can retry or save it.
        for view in children:
            view.finish_close(None)
        self.closed = True
        from .read_visibility import stop as stop_reading
        stop_reading(self)
        if getattr(self, '_linked_owner', None) is not None:
            windows = getattr(self._linked_owner, '_app_windows', [])
            if self in windows:
                windows.remove(self)
        if hasattr(self,'animation_player'):self.animation_player.stop()
        self.worker.stop()
        if getattr(self, '_linked_owner', None) is not None:
            from .interface_windows import cancel_view_timers
            cancel_view_timers(self.root)
        self.root.destroy()
        for directory in self.media_temps:
            directory.cleanup()


def _wake_existing_instance(data_dir):
    from pathlib import Path
    import os
    port_path = Path(data_dir) / 'desktop.port'
    if not port_path.is_file():
        return False
    try:
        if os.name == 'nt':
            try:
                import ctypes
                ctypes.windll.user32.AllowSetForegroundWindow(-1)
            except Exception:
                pass
        port = int(port_path.read_text(encoding='utf-8').strip())
        import socket
        with socket.create_connection(('127.0.0.1', port), timeout=1.5) as s:
            s.sendall(b'reopen\n')
            resp = s.recv(1024)
            return b'ok' in resp
    except Exception:
        return False


def _start_instance_server(root, data_dir):
    from pathlib import Path
    import socket
    import threading
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        server.bind(('127.0.0.1', 0))
        server.listen(5)
        port = server.getsockname()[1]
        port_path = Path(data_dir) / 'desktop.port'
        port_path.write_text(str(port), encoding='utf-8')
    except Exception:
        server.close()
        return lambda: None

    def _serve():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                break
            try:
                data = conn.recv(1024)
                if b'reopen' in data:
                    def _wake():
                        app = getattr(root, '_app_instance', None)
                        if app is not None and hasattr(app, 'reopen_window'):
                            app.reopen_window()
                        else:
                            try:
                                root.deiconify()
                                root.attributes('-topmost', True)
                                root.update_idletasks()
                                root.lift()
                                root.focus_force()
                                root.attributes('-topmost', False)
                            except Exception:
                                pass
                    # 1.5.0.1: answer at once and hand the wake-up to Tk's own
                    # thread through the app's event queue. Calling root.after
                    # from this thread blocked until Tk was idle, so a second
                    # launch could time out and report failure.
                    conn.sendall(b'ok\n')
                    app = getattr(root, '_app_instance', None)
                    worker = getattr(app, 'worker', None)
                    if worker is not None and hasattr(worker, 'events'):
                        worker.events.put((lambda _: _wake(), None))
                    else:
                        root.after(0, _wake)
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    thread = threading.Thread(target=_serve, daemon=True, name="InstanceServer")
    thread.start()

    def _cleanup():
        try:
            server.close()
        except Exception:
            pass
        try:
            port_path.unlink(missing_ok=True)
        except Exception:
            pass

    return _cleanup


def run_desktop(demo=False, configure=False):
    # Linux: a stable window class, so docks group the window with tg-ascii.desktop.
    if sys.platform == 'win32':
        from .windows_launcher import identify_process
        identify_process()
    root = tk.Tk(className='tg-ascii') if sys.platform.startswith('linux') else tk.Tk()
    # 3.2: the saved look and name apply from the first frame (start/lock screens).
    from .startup_look import apply as apply_startup_look
    apply_startup_look(root)
    from .instance import InstanceLock
    from .preferences import data_root
    lock = None if demo else InstanceLock(data_root())
    if lock is not None and not lock.acquired:
        if _wake_existing_instance(data_root()):
            root.destroy()
            return
        root.withdraw()
        message = tr('TeleGraph is already running. Open it from the tray or taskbar.')
        messagebox.showinfo(APP_NAME, message, parent=root)
        root.destroy()
        return
    server_cleanup = None if demo else _start_instance_server(root, data_root())
    try:
        if demo:Desktop(root,demo=True,configure=configure)
        else:
            from .app_lock import LockStore,startup_gate
            startup_gate(root,LockStore(data_root()),lambda:Desktop(root,demo=False,configure=configure))
        root.mainloop()
    finally:
        if server_cleanup is not None: server_cleanup()
        if lock is not None: lock.close()
        # 1.5.4: a temporary independent window leaves nothing behind.
        from .saved_windows import temporary, main_root, remove_folder
        if temporary(data_root()):
            remove_folder(main_root(data_root()), data_root().name)
        # 'Restart app' / 'Quit completely': end leftovers, relaunch if asked.
        from .decode_pool import shutdown as stop_decoders
        stop_decoders()
        from .app_lifecycle import finish
        finish()
    if sys.platform == 'win32' and not demo:
        from .app_lifecycle import windows_fast_exit
        windows_fast_exit()
