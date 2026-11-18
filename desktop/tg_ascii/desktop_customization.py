"""Protected recovery controls and entry points for optional local design tools."""
from . import APP_NAME
import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk

from .interface_layout import LayoutRuntime, caption
from .interface_store import InterfaceStore, default_layout, appearance


class DesktopCustomization:
    def init_customization(self):
        root = self.preview_dir if self.demo else self.preferences.path.parent
        owner = getattr(self, '_linked_owner', None)
        self.interface_store = owner.interface_store if owner is not None else InterfaceStore(root, demo=self.demo)
        self.layout_runtime = LayoutRuntime(self, self.interface_store)
        if getattr(self, '_chat_only', False):
            return
        # This bar belongs to the root, outside every editable subtree.
        self.recovery_bar = ttk.Frame(self.root, padding=(6, 2))
        self.recovery_bar.pack(side='top', fill='x')
        ttk.Button(self.recovery_bar, text=caption('Settings / recovery', 'Ajustes / recuperar'), command=self.open_fixed_settings).pack(side='left')
        ttk.Button(self.recovery_bar, text=caption('Customize', 'Personalizar'), command=self.open_customization).pack(side='left', padx=3)
        more = ttk.Button(self.recovery_bar, text='⋯')
        more.pack(side='right')
        def menu():
            from .app_dialogs import popup_menu
            from .app_lock import lock_app
            from .i18n import tr
            from .saved_windows import load, main_root, display_name
            entries = [
                (tr('Lock now'),lambda:lock_app(self)),
                (caption('Restore defaults', 'Restaurar valores iniciales'), self.restore_interface_defaults),
                (caption('Open design folder', 'Abrir carpeta de diseños'), self.open_interface_folder),
                None,
                # 1.5.4: a normal window shows the same accounts and chats as this one.
                (tr('New window'), self.open_new_window),
                (tr('New independent window'), self.open_independent_window),
            ]
            try:
                saved = load(main_root(self.service.root)) if not self.demo else {'windows': []}
            except OSError:
                saved = {'windows': []}
            for item in saved['windows'][:12]:
                entries.append(('▸ ' + display_name(saved, item, tr), lambda ident=item['id']: self.open_independent_window(ident)))
            entries += [None,
                (caption('Restart app', 'Reiniciar la app'), self.restart_app),
                (caption('Quit completely', 'Salir por completo'), self.quit_completely),
            ]
            popup_menu(self.root, entries, anchor=more)
        more.configure(command=menu)
        self.root.bind('<Control-Shift-F12>', lambda _: self.open_fixed_settings())

    def _lifecycle_close(self, mode, question):
        from .app_dialogs import messagebox
        from . import app_lifecycle
        owner = getattr(self, '_linked_owner', None) or self
        if owner.closing or owner.closed:
            return
        if not messagebox.askyesno(APP_NAME, question, parent=self.root):
            return
        app_lifecycle.request(mode)
        owner.close()
        if not owner.closing:
            app_lifecycle.request(None)  # The user kept the app open (busy prompt).

    def restart_app(self):
        self._lifecycle_close('restart', caption(
            'Restart TG-ASCII now? Drafts are saved and sessions are kept.',
            '¿Reiniciar TG-ASCII ahora? Se guardan los borradores y se conservan las sesiones.'))

    def quit_completely(self):
        self._lifecycle_close('quit', caption(
            'Quit TG-ASCII completely? Notifications, calls and background activity stop until you open it again.',
            '¿Salir por completo de TG-ASCII? Las notificaciones, llamadas y la actividad en segundo plano se detienen hasta que vuelvas a abrirla.'))

    def open_fixed_settings(self):
        if getattr(self, '_chat_only', False):
            self._linked_owner.open_fixed_settings()
            return
        from .app_lock import show_locked
        if show_locked(self):return
        if getattr(self, 'stage', None) == 'ready' and self.settings_page.winfo_exists():
            self.notebook.select(self.settings_page)
            self.root.deiconify()
        else:
            from .app_dialogs import messagebox
            if messagebox.askyesno(APP_NAME, caption('Restore the default interface? Accounts and messages are kept.',
                    '¿Restaurar la interfaz predeterminada? Se conservan cuentas y mensajes.'), parent=self.root):
                self.restore_interface_defaults()

    def open_customization(self):
        if getattr(self, '_chat_only', False):
            self._linked_owner.open_customization()
            return
        if getattr(self, 'stage', None) != 'ready':
            self.open_fixed_settings()
            return
        runtime = self.layout_runtime
        if runtime.editor is not None and runtime.editor.window.winfo_exists():
            runtime.editor.window.lift()
            return
        from .interface_editor import InterfaceEditor
        self.notebook.select(self.chat_page)
        self.root.update_idletasks()
        if not runtime.widgets:
            runtime.attach(force=True)
        InterfaceEditor(runtime)

    def restore_interface_defaults(self):
        from .preferences import DEFAULTS
        try:
            self.interface_store.archive()
            self.interface_store.commit(default_layout())
            values = appearance(DEFAULTS)
            values.update(custom_icon='', official_icon_label='', logo_theme=DEFAULTS['logo_theme'], logo_variant=DEFAULTS['logo_variant'], logo_color=DEFAULTS['logo_color'])
            self.preferences.save(values)
            from .motion import restore_motion
            restore_motion(self)
            if hasattr(self, 'stage'):
                self.rebuild_screen()
        except (OSError, ValueError) as exc:
            self.show_error(exc)

    def open_interface_folder(self):
        try:
            self.interface_store.ensure()
            path = str(self.interface_store.root)
            if sys.platform == 'win32':
                os.startfile(path)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', path])
            else:
                subprocess.Popen(['xdg-open', path])
        except OSError as exc:
            self.show_error(exc)

    def open_chat_window(self):
        from .interface_windows import open_chat_window
        open_chat_window(self)

    def open_chat_in_new_window(self,peer=None,chat=None,account=None):
        from .app_lock import show_locked
        from .interface_windows import open_linked_app_window
        if getattr(self, '_chat_only', False) or show_locked(self) or self.closed or self.closing:return
        account=self.ui_account if account is None else account
        if account!=self.ui_account:return
        peer=self.active if peer is None else peer
        if peer is None:
            from .i18n import tr
            self.show_error(ValueError(tr('Primero elige un chat.')));return
        backend=self.service.backend
        chat=chat or next((item for item in self.chats if item.id==peer),None)
        def opened(item):
            if (not self.closed and not self.closing and account==self.ui_account
                    and backend is self.service.backend and not show_locked(self)):
                return open_linked_app_window(self,initial_chat=item)
        if chat is not None:return opened(chat)
        from .i18n import tr
        self.call(backend.resolve_chat(peer),opened,tr('Cargando...'))

    def open_linked_app_window(self):
        from .interface_windows import open_linked_app_window
        return open_linked_app_window(self)

    def open_independent_window(self, ident=None):
        from .interface_windows import open_independent_window
        try:
            open_independent_window(self, ident)
        except (OSError, ValueError) as exc:
            self.show_error(exc)

    def open_new_window(self):
        from .interface_windows import open_linked_app_window
        try:
            open_linked_app_window(self)
        except (ValueError, tk.TclError) as exc:
            self.show_error(exc)

    def refresh_premium_status(self):
        if self.demo:
            return
        def loaded(snapshot):
            self.update_account_picker()
            self.status.set('Telegram Premium' if snapshot.get('premium') else caption('Standard account', 'Cuenta estándar'))
        self.call(self.service.refresh_account(), loaded, caption('Updating account status…', 'Actualizando estado de cuenta…'))
