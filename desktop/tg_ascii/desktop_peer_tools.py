from .timestamps import date_text
"""Explicit membership actions, timed mute and lazy call history."""
import asyncio
import tkinter as tk
from tkinter import ttk
from .app_dialogs import Choice, messagebox
from .i18n import tr
from .advanced_features import feature_enabled
from .peer_tools import MUTE_PRESETS


class DesktopPeerTools:
    def complex_settings(self):
        if getattr(self, '_chat_only', False):
            self._linked_owner.complex_settings()
            return
        self._settings_category = 7
        self.open_fixed_settings()
        if hasattr(self, 'settings_page'):
            self.notebook.select(self.settings_page)
        picker=getattr(self,'_settings_picker',None)
        if picker is not None and picker.winfo_exists():
            picker.current(7)
            self._settings_choose()

    def show_my_profile(self):
        if self.busy or self.demo:
            return
        backend, account = self.service.backend, self.ui_account
        ident = backend.account_profile.user_id
        if ident is not None:
            return self.show_contact_profile(ident)
        def loaded(profile):
            if account == self.ui_account and backend is self.service.backend:
                self.show_contact_profile(profile['id'])
        self.call(backend.profile(), loaded, tr('Cargando...'))

    def membership_action(self, peer, leave=False, profile=None):
        if self.busy or self.demo:
            return
        backend, account = self.service.backend, self.ui_account
        def valid():
            return not self.busy and account == self.ui_account and backend is self.service.backend
        def ready(current):
            if not valid():
                return
            if current.get('kind') not in ('group', 'channel'):
                return
            if not leave and current.get('member'):
                self.status.set(tr('Ya perteneces a este grupo o canal.'));return
            label = 'Salir del grupo o canal' if leave else ('Solicitar unirse' if current.get('join_request') else 'Unirse')
            if not messagebox.askyesno(tr(label), tr(label) + '?\n' + current['name'], parent=self.root) or not valid():
                return
            def done(result):
                if account != self.ui_account or backend is not self.service.backend:
                    return
                if isinstance(result, dict) and result.get('requested'):
                    self.status.set(tr('Solicitud enviada. Un administrador debe aprobarla.'))
                    return
                if leave and self.active == peer:
                    if getattr(self, '_chat_only', False):
                        self.close()
                        return
                    self.stash_account()
                    self.active = None
                    self.messages = []
                    self.render_messages(False)
                self.refresh()
            self.call(backend.leave_chat(peer) if leave else backend.join_chat(peer), done, tr('Guardando...'))
        if profile is None:
            self.call(backend.profile(peer), ready, tr('Cargando...'))
        else:
            ready(profile)

    def invite_dialog(self, token):
        if self.demo or self.busy:
            return
        backend, account = self.service.backend, self.ui_account
        def valid():
            return account == self.ui_account and backend is self.service.backend and not self.busy
        def loaded(invite):
            if not valid():
                return
            from telethon import types, utils
            if isinstance(invite, types.ChatInviteAlready):
                self.call(backend.resolve_chat(utils.get_peer_id(invite.chat)), self.open_resolved, tr('Cargando...'))
                return
            title = getattr(invite, 'title', tr('Grupo o canal'))
            label = tr('Solicitar unirse') if getattr(invite, 'request_needed', False) else tr('Unirse')
            if not messagebox.askyesno(label, label + '?\n' + title, parent=self.root) or not valid():
                return
            def joined(result):
                if not valid():
                    return
                if result.get('requested'):
                    self.status.set(tr('Solicitud enviada. Un administrador debe aprobarla.'))
                elif result.get('peer') is not None:
                    self.call(backend.resolve_chat(result['peer']), self.open_resolved, tr('Cargando...'))
                else:
                    self.refresh()
            self.call(backend.join_invite(token), joined, tr('Guardando...'))
        self.call(backend.inspect_invite(token), loaded, tr('Cargando...'))

    def mute_menu(self, peer):
        if self.busy or self.demo:
            return
        from .app_dialogs import popup_menu
        backend, account = self.service.backend, self.ui_account
        def valid():
            return not self.busy and account == self.ui_account and backend is self.service.backend
        def save(seconds):
            if not valid():
                return
            self.call(backend.mute_chat(peer, seconds != 0, duration=seconds),
                      lambda _: self.refresh() if account == self.ui_account and backend is self.service.backend else None,
                      tr('Guardando...'))
        def custom():
            if not valid():
                return
            window, body = self.dialog('Duración del silenciado', '420x260')
            value = self.field(body, 'Duración', '1')
            unit = Choice(body, values=[tr('Minutos'), tr('Horas'), tr('Días')]); unit.current(1); unit.pack(fill='x', pady=8)
            def apply():
                if not valid() or not window.winfo_exists():
                    return
                try:
                    count = int(value.get())
                    if not 1 <= count <= 36500 or unit.current() not in (0, 1, 2):
                        raise ValueError(tr('Duración no válida.'))
                    seconds = count * (60, 3600, 86400)[unit.current()]
                except ValueError as exc:
                    self.show_error(exc); return
                window.destroy(); save(seconds)
            ttk.Button(body, text=tr('Silenciar'), command=apply).pack(fill='x', pady=12)
        popup_menu(self.root, [(tr('Activar sonido'), lambda: save(0)), None,
            *[(tr(label), lambda seconds=seconds: save(seconds)) for seconds, label in MUTE_PRESETS],
            (tr('Duración personalizada…'), custom)])

    def build_call_history_tab(self):
        page = ttk.Frame(self.notebook, padding=12)
        self.call_page = page
        self.notebook.insert(1, page, text=tr('Llamadas'))
        if not feature_enabled(self, 'call_history'):
            ttk.Label(page, text=tr('El registro de llamadas está desactivado. Puedes activarlo en Funciones complejas.'), wraplength=520).pack(fill='x', pady=20)
            ttk.Button(page, text=tr('Funciones complejas'), command=self.complex_settings).pack(anchor='w')
            return
        ttk.Label(page, text=tr('Registro de llamadas de Telegram. Las llamadas de voz y vídeo requieren un motor de llamadas compatible.'), wraplength=600).pack(fill='x', pady=8)
        missed = tk.BooleanVar(master=page)
        rows, state = [], {'cursor': None, 'more': True, 'loaded': False, 'future': None, 'serial': 0}
        backend, account = self.service.backend, self.ui_account
        listing = ttk.Treeview(page, columns=('date', 'kind', 'duration'), show='tree headings')
        for key, title in [('#0', 'Contacto'), ('date', 'Fecha'), ('kind', 'Tipo'), ('duration', 'Duración')]:
            listing.heading(key, text=tr(title))
            listing.column(key, width=150 if key in ('#0', 'date') else 100)
        listing.pack(fill='both', expand=True)
        status = ttk.Label(page); status.pack(fill='x')
        controls = ttk.Frame(page); controls.pack(fill='x', pady=8)
        def valid():
            return page.winfo_exists() and account == self.ui_account and backend is self.service.backend and feature_enabled(self, 'call_history')
        def fetch(more=False):
            if not valid() or self.demo or state['future'] is not None or more and not state['more']:
                return
            state['serial'] += 1
            serial = state['serial']; cursor = state['cursor'] if more else None
            status.configure(text=tr('Cargando...'))
            def ready(result):
                state['future'] = None
                if not valid() or serial != state['serial']:
                    return
                # A filter click during the request must not leave the table
                # showing the previous filter under the new checkbox value.
                if missed.get() != missed_value:
                    fetch()
                    return
                if not more:
                    rows.clear(); listing.delete(*listing.get_children())
                seen = {(item['peer'], item['id']) for item in rows}
                for item in result['items']:
                    if (item['peer'], item['id']) in seen:
                        continue
                    key = str(len(rows)); rows.append(item)
                    kind = tr('Perdida') if item['missed'] else tr('Saliente' if item['outgoing'] else 'Entrante')
                    from .call_outcomes import LABELS
                    if item.get('outcome') and item['outcome']!='ended':kind=tr(LABELS[item['outcome']])+' · '+kind
                    if item['video']: kind += ' · ' + tr('Vídeo')
                    listing.insert('', 'end', iid=key, text=item['name'], values=(date_text(item['date'],self.preferences.values), kind, str(item['duration'] or 0) + ' s'))
                state.update(cursor=result['next'], more=result['more'], loaded=True)
                status.configure(text=str(len(rows)) if rows else tr('No results.'))
            def failed(exc):
                state['future'] = None
                if valid():
                    if missed.get() != missed_value: fetch()
                    else: status.configure(text=str(exc))
            # Read Tk variables on its thread before submitting the coroutine.
            missed_value = missed.get()
            async def safe_request():
                return await asyncio.wait_for(backend.call_history(cursor, missed_value), 30)
            state['future'] = self.worker.submit(safe_request(), ready, failed)
        def open_chat(_=None):
            if not valid() or self.busy or not listing.selection(): return
            item = rows[int(listing.selection()[0])]
            self.call(backend.resolve_chat(item['peer']), self.open_resolved, tr('Cargando...'))
        ttk.Checkbutton(controls, text=tr('Solo perdidas'), variable=missed, command=fetch).pack(side='left')
        ttk.Button(controls, text=tr('Actualizar'), command=fetch).pack(side='left')
        ttk.Button(controls, text=tr('More'), command=lambda: fetch(True)).pack(side='left')
        ttk.Button(controls, text=tr('Abrir chat'), command=open_chat).pack(side='right')
        def open_record(event=None):
            if not valid() or not listing.selection():return
            item=rows[int(listing.selection()[0])]
            if item.get('conference') and feature_enabled(self,'calls'):
                from .desktop_conference import open_invitation
                open_invitation(self,item['peer'],item['id'])
            else:open_chat()
        listing.bind('<Double-Button-1>', open_record)
        def selected(_=None):
            if valid() and self.notebook.select() == str(page) and not state['loaded']: fetch()
        self.notebook.bind('<<NotebookTabChanged>>', selected, add='+')
        def closed(event):
            if event.widget is page and state['future'] is not None: state['future'].cancel()
        page.bind('<Destroy>', closed, add='+')
