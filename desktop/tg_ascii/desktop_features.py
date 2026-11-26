"""Desktop controls for accounts, contacts, profile, folders and media."""
from . import APP_NAME
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
from .scrolling import FlowFrame
from .app_dialogs import filedialog, messagebox, simpledialog, Choice, CheckList, scrollable

from telethon import utils
from .desktop_plus import DesktopPlus
from .backend import display
from .i18n import tr, set_language, get_language, LANGUAGES
from .media_viewer import enable_drop, show_image


from .desktop_folders import DesktopFolders, FolderPicker


from .desktop_settings import DesktopSettings


from .attachments import AttachmentComposer
from .desktop_customization import DesktopCustomization
from .desktop_peer_tools import DesktopPeerTools
from .desktop_calls import DesktopCalls


_DISPLAY_CONTROLS={code:None for code in (*range(32),127) if code not in (9,10)}


class DesktopFeatures(DesktopCalls, DesktopPeerTools, DesktopCustomization, AttachmentComposer, DesktopSettings, DesktopFolders, DesktopPlus):
    def text_display(self, value, one_line=False):
        # Preserve ordinary Unicode/emoji while suppressing control characters.
        text = str(value)
        if getattr(self, 'preferences', None) and self.preferences.values['ascii_text']:
            text = display(text)
        else:
            text = text.translate(_DISPLAY_CONTROLS)
        return text.replace('\n', ' ') if one_line else text

    def stash_account(self):
        if hasattr(self, 'draft_manager'):
            self.draft_manager.snapshot()
        self.save_custom_draft()
        if self.active is not None and hasattr(self, 'editor') and self.editor.winfo_exists():
            self.drafts[self.active] = (self.editor.get('1.0', 'end-1c'), self.attachment)
        self.account_states[self.ui_account] = {
            'active': self.active, 'messages': self.messages, 'drafts': self.drafts,
            'chats': self.chats}

    def account_event(self, event):
        owner = getattr(self, '_linked_owner', None)
        if owner is not None and not getattr(self, '_forwarding_account_event', False):
            owner.account_event(event)
            return
        account, peer, message = event
        if account not in self.service.entries: return
        from .interface_windows import forward_chat_event
        forward_chat_event(self, account, peer, message)
        if getattr(self, '_linked_owner', None) is None and hasattr(self, 'notify_seen'): self.notify_message(account, peer, message)
        if account == self.ui_account and self.stage == 'ready':
            self.incoming((peer, message))
        else:
            self.account_unread[account] = self.account_unread.get(account, 0) + (not message.outgoing)
            state = self.account_states.get(account)
            if state and state['active'] == peer:
                merged = {m.id: m for m in state['messages'] + [message]}
                state['messages'] = sorted(merged.values(), key=lambda m: m.id)[-200:]
            self.update_account_picker()

    def update_account_picker(self):
        if not hasattr(self, 'account_picker') or not self.account_picker.winfo_exists():
            return
        self.account_keys = list(self.service.entries)
        labels = [self.account_label(key) +
                  (' ★' if self.service.entries.get(key, {}).get('premium') else '') +
                  (f' [{self.account_unread.get(key, 0)}]' if self.account_unread.get(key) else '') +
                  (' !' if key in self.service.failures else '') for key in self.account_keys]
        self.account_picker.configure(values=labels)
        if self.ui_account in self.account_keys:
            self.account_picker.current(self.account_keys.index(self.ui_account))

    def account_label(self, key):
        return account_label(self, key)

    def account_selected(self, event=None):
        index = self.account_picker.current()
        if self.busy or index < 0:
            self.update_account_picker()
            return
        key = self.account_keys[index]
        if key != self.ui_account:
            self.switch_account(key)

    def switch_account(self, key=None):
        if getattr(self, '_chat_only', False):
            return
        if self.busy:
            return
        if key is None and getattr(self, '_linked_owner', None) is not None:
            self._linked_owner.root.deiconify()
            self._linked_owner.root.lift()
            self._linked_owner.switch_account()
            return
        menu = getattr(self.root, '_context_menu', None)
        if menu: menu.destroy()
        if getattr(self, '_linked_owner', None) is not None:
            self._view_generation = getattr(self, '_view_generation', 0) + 1
            self.worker.cancel_pending()
        if self.stage == 'ready':
            self.stash_account()
        self.cancel_qr()
        from .preload import stop as stop_preload
        stop_preload(self)
        old = self.ui_account
        for popup in self.popups:
            if popup.winfo_exists():
                popup.destroy()
        self.popups = []
        def switched(stage):
            self.ui_account = self.service.current
            state = self.account_states.get(self.ui_account, {})
            self.active = state.get('active')
            self.messages = state.get('messages', [])
            self.chats = state.get('chats', [])
            self.drafts = state.get('drafts', {})
            if hasattr(self, 'draft_manager'):
                self.draft_manager.restore_account()
            self.attachment = None
            self.account_unread[self.ui_account] = 0
            self.login_stage(stage)
        def failed(exc):
            self.service.current = old
            self.show_error(exc)
            self.update_account_picker()
        operation = self.service.add() if key is None else self.service.select(key)
        self.call(operation, switched, tr('Conectando a Telegram...'), failed)

    def add_language_picker(self, parent):
        codes = list(LANGUAGES)
        picker = Choice(parent, values=list(LANGUAGES.values()), width=18)
        picker.current(codes.index(get_language()))
        picker.pack(anchor='e', pady=(0, 12))
        picker.bind('<<ComboboxSelected>>', lambda _: self.change_language(codes[picker.current()]))
        return picker

    def change_language(self, language):
        if self.busy:
            return
        try:
            self.preferences.save({'language': language})
        except OSError as exc:
            self.show_error(exc)
            return
        phone = self.login_value.get() if self.stage == 'phone' else None
        set_language(language)
        self.rebuild_screen()
        if phone is not None: self.login_value.set(phone)

    def rebuild_screen(self):
        if not getattr(self, '_chat_only', False):
            self.apply_optional_services()
        if hasattr(self,'animation_player'):
            self.animation_player.stop();del self.animation_player
        self.configure_style()
        if self.stage == 'ready':
            selection = (getattr(self, 'selection_kind', None), getattr(self, 'selection_scope', None),
                         set(getattr(self, 'selected_messages', ())), set(getattr(self, 'selected_chats', ())))
            self.stash_account()
            self.build_chats()
            self.selection_kind, self.selection_scope, self.selected_messages, self.selected_chats = selection
            if self.selection_valid(): self.refresh_selection()
            self.restore_draft()
            self.render_chats()
            self.render_messages()
            for window in tuple(getattr(self, '_chat_windows', ())):
                if hasattr(window, 'update_appearance'):
                    window.update_appearance()
        elif self.stage == 'choose_account':
            self.begin_startup()
        else:
            self.login_stage(self.stage)

    def build_account_bar(self, parent):
        bar = FlowFrame(parent)
        self.account_bar=bar
        bar.pack(fill='x', pady=(0, 4))
        self.logo_label = ttk.Label(bar)
        self.logo_label.pack(side='left', padx=(0, 12))
        self.refresh_logo()
        self.account_picker = Choice(bar, state='readonly', width=22)
        self.account_picker.pack(side='left')
        self.account_picker.bind('<<ComboboxSelected>>', self.account_selected)
        self.update_account_picker()
        ttk.Button(bar, text=tr('+ Cuenta'), command=lambda: self.switch_account()).pack(side='left', padx=8)


    def build_feature_controls(self, sidebar, conversation):
        if getattr(self, '_chat_only', False):
            self.drop_available = enable_drop(self.root, [self.editor, self.history], self.dropped_files)
            self.setup_actions(None, conversation)
            return
        self.folder_picker = FolderPicker(sidebar,self)
        self.folder_picker.current(0)
        self.folder_picker.pack(fill='x', before=sidebar.winfo_children()[0], pady=(0, 4))
        self.update_folder_picker()
        from .app_dialogs import popup_menu
        more=ttk.Button(sidebar,text=tr('More')+' ▾')
        more.configure(command=lambda:popup_menu(self.root,[
            # 1.5.5: archived chats have their own list (Telegram's Archive).
            (tr('Todos los chats'),self.show_main_chats) if getattr(self,'archive_view',False) else (tr('Archived chats'),self.show_archived_chats),
            (tr('Contactos'),self.open_contacts),
            (tr('Nuevo chat'),self.new_chat),(tr('Nuevo chat secreto'),self.new_secret_chat),(tr('New channel'),self.new_channel),(tr('Nuevo grupo'),self.new_supergroup),(tr('Carpetas'),self.folder_dialog),
            (tr('Saved Messages'),self.saved_messages)],anchor=more))
        more.pack(fill='x',pady=3)
        self.drop_available = enable_drop(self.root, [self.editor, self.history], self.dropped_files)
        self.setup_actions(sidebar, conversation)
        self.build_story_tab()
        self.build_call_history_tab()
        self.build_settings_tab()

    def show_archived_chats(self):
        """1.5.5: the list shows only archived chats until 'All chats'."""
        self.archive_view=True
        self.render_chats()

    def show_main_chats(self):
        self.archive_view=False
        self.render_chats()

    def selected_folder(self):
        index = self.folder_picker.current() if hasattr(self, 'folder_picker') else 0
        return self.folder_records[index - 1] if index > 0 and index <= len(self.folder_records) else None

    def update_folder_picker(self):
        if hasattr(self, 'folder_picker'):
            self.folder_picker.set_records(self.folder_records)

    def dialog(self, title, size='520x500', unique=True):
        for previous in self.popups:
            if unique and previous.winfo_exists() and previous.title() == tr(title): previous.destroy()
        self.popups = [w for w in self.popups if w.winfo_exists()]
        window = tk.Toplevel(self.root)
        window.title(tr(title))
        window.configure(bg='#08100c')
        width,height=map(int,size.split('x'))
        window.geometry(f'{min(width,window.winfo_screenwidth()-48)}x{min(height,window.winfo_screenheight()-80)}')
        window.minsize(320,260)
        window.transient(self.root)
        window.bind('<Escape>', lambda _: window.destroy())
        from .transitions import fade_in
        fade_in(self, window)
        # 3.2: swipe right (or Command-[ / Alt-Left) closes the dialog, like going back.
        from .back_gesture import install as install_back
        install_back(window, window.destroy)
        from .scrolling import Viewport
        viewport=Viewport(window,minimum=(320,260));viewport.pack(fill='both',expand=True)
        frame=viewport.content;frame.configure(padding=12,style='Surface.TFrame')
        from .scrolling import fit_to_content
        fit_to_content(window,viewport)
        self.popups.append(window)
        from .themes import apply_widget
        # A dialog can close before idle; register the command on its live root.
        self.root._root().after_idle(lambda: apply_widget(window) if window.winfo_exists() else None)
        from .app_lock import hide_locked_dialog
        hide_locked_dialog(self,window)
        return window, frame

    def field(self, frame, label, value='', emoji=False):
        ttk.Label(frame, text=tr(label)).pack(anchor='w', pady=(8, 3))
        variable = tk.StringVar(value=value)
        if emoji:
            from .native_emoji import search_entry
            search_entry(frame,self,variable)
        else:
            variable.entry=ttk.Entry(frame,textvariable=variable);variable.entry.pack(fill='x')
        return variable

    def new_chat(self):
        if self.busy:
            return
        value = simpledialog.askstring(tr('Nuevo chat'), tr('Usuario (@nombre) o telefono (+prefijo):'), parent=self.root)
        if value:
            self.call(self.service.backend.resolve_chat(value), self.open_resolved, tr('Cargando...'))

    def new_secret_chat(self):
        if self.busy:
            return
        value = simpledialog.askstring(tr('Nuevo chat secreto'), tr('Usuario (@nombre) o telefono (+prefijo):'), parent=self.root)
        if value:
            self.start_secret_chat(value.strip())

    def open_resolved(self, chat):
        if getattr(self, '_chat_only', False):
            if chat.id == self._pinned_peer:
                self.refresh()
            else:
                from .interface_windows import navigate_from_chat_window
                navigate_from_chat_window(self, chat=chat)
            return
        if not any(c.id == chat.id for c in self.chats):
            self.chats.append(chat)
        self.notebook.select(self.chat_page)
        self.search.set('')
        self.folder_picker.current(0)
        self.render_chats()
        self.chat_list.selection_set(str(chat.id))
        self.choose_chat()

    def new_channel(self):
        from .desktop_community import create_community
        create_community(self,True)

    def new_supergroup(self):
        from .desktop_community import create_community
        create_community(self,False)

    def open_contacts(self):
        if self.busy:
            return
        def loaded(contacts):
            window, frame = self.dialog('Contactos', '560x660')
            # 1.4.0.1: search box. Filters by name, @username or phone; the
            # selection of hidden contacts is kept while the query changes.
            from .contact_search import contact_matches
            query = tk.StringVar(master=window)
            search_row = ttk.Frame(frame); search_row.pack(fill='x', pady=(0, 6))
            ttk.Label(search_row, text=tr('Search contacts')).pack(side='left', padx=(0, 6))
            search_entry = ttk.Entry(search_row, textvariable=query); search_entry.pack(side='left', fill='x', expand=True)
            from .advanced_features import feature_enabled
            if feature_enabled(self, 'contact_list_details') and not self.demo:
                # 1.4 (Complex features, off by default): photo, activity and
                # Premium emoji status for every contact.
                from .contact_list_view import DetailedContacts
                listing = DetailedContacts(frame, self, contacts)
                shown = list(range(len(contacts)))
                def apply_filter(*_):
                    text = query.get()
                    listing.set_filter([index for index, person in enumerate(contacts) if contact_matches(person, text)])
                def selected_indices(): return list(listing.curselection())
            else:
                listing = CheckList(frame, selectmode='extended', exportselection=False,
                                     bg='#0e1b13', fg='#8cf5a6', selectbackground='#284f35')
                listing.pack(fill='both', expand=True)
                scrollbar = ttk.Scrollbar(frame, command=listing.yview)
                listing.configure(yscrollcommand=scrollbar.set)
                scrollbar.pack(side='right', fill='y')
                shown = list(range(len(contacts)))
                checked = set()
                def apply_filter(*_):
                    # Remember checks by contact, rebuild the visible rows.
                    checked.difference_update(shown[i] for i in range(len(shown)))
                    checked.update(shown[i] for i in listing.checked)
                    text = query.get()
                    shown[:] = [index for index, person in enumerate(contacts) if contact_matches(person, text)]
                    listing.delete(0, 'end'); listing.labels, listing.checked = [], set()
                    for row, index in enumerate(shown):
                        person = contacts[index]
                        listing.insert('end', utils.get_display_name(person) or str(person.id))
                        if index in checked: listing.toggle(row)
                for person in contacts:
                    listing.insert('end', utils.get_display_name(person) or str(person.id))
                def selected_indices():
                    # Checked contacts hidden by the current search still count.
                    visible = {shown[row] for row in listing.checked}
                    return sorted((checked - set(shown)) | visible)
            trace = query.trace_add('write', apply_filter)
            window.bind('<Destroy>', lambda event: query.trace_remove('write', trace) if event.widget is window else None, add='+')
            search_entry.focus_set()
            def selected_people():
                return [contacts[index] for index in selected_indices()]
            def cards(_=None):
                people = selected_people()
                if people:
                    from .contact_tools import open_contact_cards
                    open_contact_cards(self, [person.id for person in people])
                return 'break'
            def share():
                people = selected_people()
                if people:
                    from .contact_tools import share_contacts_dialog
                    share_contacts_dialog(self, people)
            listing.bind('<Double-Button-1>', cards)
            def chat():
                people = selected_people()
                if self.busy or not people: return
                person = people[0]
                window.destroy()
                self.call(self.service.backend.resolve_chat(person.id), self.open_resolved, tr('Cargando...'))
            def group():
                if self.busy: return
                selected = [person.id for person in selected_people()]
                if not selected:
                    messagebox.showinfo(APP_NAME, tr('Selecciona participantes en la lista.'), parent=window)
                    return
                title = simpledialog.askstring(tr('Nuevo grupo'), tr('Nombre del grupo:'), parent=window)
                if not title: return
                def created(result):
                    if window.winfo_exists(): window.destroy()
                    chat, missing = result
                    self.open_resolved(chat)
                    if missing:
                        messagebox.showinfo(APP_NAME, tr('Grupo creado; algunos usuarios no pudieron ser invitados.'), parent=self.root)
                self.call(self.service.backend.create_group(title, selected), created, tr('Creando grupo...'))
            def secret_chat():
                people = selected_people()
                if self.busy or not people: return
                person = people[0]
                window.destroy()
                self.start_secret_chat(person.id)
            ttk.Button(frame, text=tr('Abrir chat'), command=chat).pack(fill='x', pady=6)
            ttk.Button(frame, text=tr('Iniciar chat secreto'), command=secret_chat).pack(fill='x', pady=(0, 6))
            ttk.Button(frame, text=tr('Contact card'), command=cards).pack(fill='x')
            ttk.Button(frame, text=tr('Share contact'), command=share).pack(fill='x', pady=6)
            ttk.Button(frame, text=tr('Nuevo grupo con seleccionados'), command=group).pack(fill='x')
            ttk.Button(frame, text=tr('Añadir contacto'), command=lambda: self.add_contact_dialog(window)).pack(fill='x', pady=6)
            # Checkbox selection is independent of the Open chat action.
        self.call(self.service.backend.contacts(), loaded, tr('Cargando...'))

    def add_contact_dialog(self, previous=None):
        if self.busy: return
        if previous and previous.winfo_exists(): previous.destroy()
        window, frame = self.dialog('Añadir contacto', '500x400')
        first, last, phone = self.field(frame, 'Nombre'), self.field(frame, 'Apellidos'), self.field(frame, 'Telefono internacional')
        # 1.4, like the official apps: optionally also store the person in the
        # operating system's address book. Defaults to the account's sync setting.
        from .device_contacts import native_supported
        device = tk.BooleanVar(master=window, value=False)
        if native_supported() and not self.demo:
            from .contact_sync import load_state
            device.set(load_state(self.service.root, self.ui_account)['enabled'])
            ttk.Checkbutton(frame, text=tr('Also save to this device’s contacts'), variable=device).pack(fill='x', pady=(10, 0))
        def save():
            if self.busy: return
            values = (first.get(), last.get(), phone.get())
            store_on_device = bool(device.get())
            def saved(user):
                if window.winfo_exists(): window.destroy()
                self.status.set(tr('Contacto guardado.'))
                if store_on_device:
                    import asyncio
                    from .device_contacts import save_device_contact
                    self.worker.submit(asyncio.to_thread(save_device_contact, *values),
                        lambda _: self.status.set(tr('Contact saved on Telegram and on this device.')),
                        lambda error: self.show_error(error))
                self.open_contacts()
            self.call(self.service.backend.add_contact(*values), saved, tr('Guardando...'))
        ttk.Button(frame, text=tr('Guardar contacto'), command=save).pack(fill='x', pady=20)
        ttk.Button(frame, text=tr('Add by username'), command=lambda: self.add_username_contact(window)).pack(fill='x')

    def contact_info(self):
        self.show_contact_profile()

    def toggle_pin(self):
        if self.busy or self.active is None: return
        chat = next((c for c in self.chats if c.id == self.active), None)
        if chat:
            self.call(self.service.backend.pin(chat.id, not chat.pinned), lambda _: self.refresh(), tr('Guardando...'))

    def edit_profile(self):
        if self.busy: return
        from .customization_sync import label, sync_enabled
        from .profile_customization import apply_profile_identity, apply_profile_photo, clear_design, refresh_profile_photos
        account, backend = self.ui_account, self.service.backend
        def current():
            return account == self.ui_account and backend is self.service.backend
        def loaded(profile):
            if not current(): return
            window, frame = self.dialog('Mi perfil', '570x650')
            body = scrollable(frame)
            def valid():
                return current() and window.winfo_exists()
            mode = tk.StringVar()
            def update_mode():
                mode.set(label('Name, biography and photo synchronize with Telegram.',
                    'Nombre, biografía y foto se sincronizan con Telegram.') if sync_enabled(self.preferences) else label(
                    'Local only: other people and devices keep seeing your Telegram profile.',
                    'Solo local: otras personas y dispositivos siguen viendo tu perfil de Telegram.'))
            update_mode()
            ttk.Label(body, textvariable=mode, wraplength=480).pack(fill='x', pady=8)
            if profile.get('local_profile_fields'):
                ttk.Label(body, text=label('This profile has local overrides.', 'Este perfil tiene cambios locales.'),
                          wraplength=480).pack(fill='x')
            first = self.field(body, 'Nombre', profile['first_name'])
            last = self.field(body, 'Apellidos', profile['last_name'])
            about = self.field(body, 'Biografia', profile['about'])
            def finished(_, photo_changed=False):
                if not valid(): return
                update_mode()
                self.status.set(tr('Perfil actualizado.'))
                if photo_changed:
                    refresh_profile_photos(self, account, profile['id'])
            def save():
                if valid() and not self.busy:
                    update_mode()
                    operation = backend.update_profile(first.get(), last.get(), about.get()) if self.demo else apply_profile_identity(
                        backend, first.get(), last.get(), about.get(), sync_enabled(self.preferences))
                    self.call(operation, finished, tr('Guardando...'))
            def save_username():
                if valid() and not self.busy:
                    self.call(backend.update_username(username.get()), finished, tr('Guardando...'))
            def photo():
                if self.busy or not valid(): return
                filename = filedialog.askopenfilename(parent=window, filetypes=[(tr('Imagenes'), '*.png *.jpg *.jpeg')])
                if filename and valid() and not self.busy:
                    update_mode()
                    operation = backend.update_photo(filename) if self.demo else apply_profile_photo(backend, filename, sync_enabled(self.preferences))
                    self.call(operation, lambda result: finished(result, photo_changed=True), tr('Guardando...'),timeout=None)
            def restore():
                if not valid() or self.busy: return
                had_photo = 'photo' in getattr(backend, 'local_profile_design', {})
                async def reset():
                    clear_design(backend)
                def done(_):
                    if valid():
                        finished(None, photo_changed=had_photo)
                        window.destroy()
                        self.edit_profile()
                self.call(reset(), done, tr('Guardando...'))
            ttk.Button(body, text=tr('Guardar nombre y biografia'), command=save).pack(fill='x', pady=12)
            ttk.Button(body, text=tr('Cambiar foto'), command=photo).pack(fill='x', pady=6)
            if not self.demo:
                ttk.Button(body, text=label('Use Telegram profile · remove local overrides',
                    'Usar perfil de Telegram · quitar cambios locales'), command=restore).pack(fill='x', pady=6)
            ttk.Separator(body).pack(fill='x', pady=12)
            ttk.Label(body, text=label('Username · always synchronized with Telegram',
                'Nombre de usuario · siempre sincronizado con Telegram'), wraplength=480).pack(fill='x')
            username = self.field(body, 'Nombre de usuario', profile['username'])
            ttk.Label(body, text=label('This is your public address; it cannot be changed only on this device.',
                'Esta es tu dirección pública; no se puede cambiar solo en este dispositivo.'), wraplength=480).pack(fill='x')
            ttk.Button(body, text=tr('Cambiar nombre de usuario'), command=save_username).pack(fill='x', pady=6)
        self.call(backend.profile(), loaded, tr('Cargando...'))

    def dropped_files(self, filenames):
        if self.busy or self.active is None or self.stage != 'ready':
            self.status.set(tr('Primero elige un chat y espera a que termine la operacion.'))
            return
        self.prepare_attachments(filenames)

    def emoji_picker(self):
        if not self.busy and self.active is not None: self.native_emoji()

    def view_message_media(self, message, peer=None):
        if self.busy: return
        peer=self.active if peer is None else peer
        if message.media_kind == 'conference':
            return self.join_conference_message(message, peer=peer)
        if message.media_kind in ('poll','checklist','location','contact','gift','article'):
            return self.open_advanced_message(message,peer)
        from .menu_style import uses_system
        from .desktop_media_lifetime import export_blocked
        kind = {'audio': 'audio_player', 'voice': 'audio_player', 'video': 'video_player', 'gif': 'video_player',
                'video_note': 'video_player', 'image': 'image_viewer', 'photo': 'image_viewer'}.get(message.media_kind, 'file_viewer')
        from .custom_menus import handled
        if handled(kind, self, message, peer):
            return  # 1.5.2: the user's own viewer (menus/<kind>/menu.py)
        if uses_system(kind) and not export_blocked(message,self,peer) and not self.demo and hasattr(self, 'open_message_natively'):
            return self.open_message_natively(message, peer)  # 1.5.1 Settings › Menus
        if message.media_kind == 'audio': return self.play_message_audio(message,peer)
        if message.media_kind == 'video':
            from .media_gallery import open_chat_gallery
            return open_chat_gallery(self,message,peer)
        backend,account = self.service.backend,self.ui_account
        async def fetch():
            from .desktop_media_lifetime import source_message
            return await source_message(backend,peer,message.id)
        def ready(media):
            if account!=self.ui_account or backend is not self.service.backend:return
            self.media_dialog(media, message.filename, message.media_kind, message.text, message.size,message=message,peer=peer)
        self.call(fetch(), ready, tr('Cargando...'))

    def media_dialog(self, media, filename='', kind='file', caption='', size=0, story=None,*,message=None,peer=None):
        backend,account = self.service.backend,self.ui_account
        window, frame = self.dialog('Visor de archivos', '560x340')
        from .contact_profile import ProfileRequests
        from .media_formats import preview_available,thumbnail_preview,download_name
        requests=ProfileRequests(self,window,account,backend)
        from .desktop_media_lifetime import ViewerMedia,export_blocked
        peer=self.active if peer is None else peer
        source=message if message is not None else media
        blocked=export_blocked(source,self,peer) or export_blocked(media,self,peer)
        current_lease=[None];viewer_window=[None]
        window.bind('<Destroy>',lambda event:requests.close() if event.widget is window else None,add='+')
        def valid():return requests.valid()
        ttk.Label(frame, text=filename or tr('Archivo adjunto'), wraplength=510).pack(anchor='w', pady=12)
        ttk.Label(frame, text=caption[:500], wraplength=510).pack(anchor='w')
        if size: ttk.Label(frame, text=f'{size:,} bytes', style='Muted.TLabel').pack(anchor='w', pady=8)
        def preview():
            if not valid() or 'preview' in requests.jobs:return
            thumbnail = thumbnail_preview(media,kind)
            if size > 64 * 1024 * 1024 and not thumbnail:
                self.show_error(ValueError(tr('Archivo demasiado grande para la vista previa. Guardalo primero.')))
                return
            if current_lease[0] is not None:current_lease[0].close()
            if viewer_window[0] is not None and viewer_window[0].winfo_exists():viewer_window[0].destroy()
            def expired():
                requests.reset()
                if viewer_window[0] is not None and viewer_window[0].winfo_exists():viewer_window[0].destroy()
            lease=current_lease[0]=ViewerMedia(self,window,account,backend,peer,getattr(source,'id',0),source,expired)
            try:lease.update(media)
            except PermissionError as error:lease.expire();self.show_error(error);return
            def loaded(path):
                if not valid():return
                lease.check()
                if not lease.restricted and not thumbnail and kind in ('image','photo') and __import__('tg_ascii.menu_style',fromlist=['x']).uses_system('image_viewer'):
                    from .native_open import open_with_system
                    lease.retain_copy()
                    open_with_system(path,filename,on_error=lambda error:self.worker.events.put((self.show_error,error)),
                        on_done=lambda:self.worker.events.put((lambda _:lease.release_copy(close=True),None)))
                    return
                try:
                    viewer = show_image(window, path, caption[:300], thumbnail, name=filename or None,
                                        on_error=lambda error:self.worker.events.put((self.show_error,error)))
                    viewer_window[0]=viewer;lease.attach(viewer);lease.viewed()
                    if lease.export_blocked:viewer._open_native=lambda:self.show_error(PermissionError(tr('Protected content')))
                    if window.winfo_exists(): window.grab_release()
                    self.popups.append(viewer)
                    if story is not None:
                        self.call(backend.view_story(story), lambda _: None, tr('Historia abierta.'))
                except (ImportError, OSError, ValueError) as exc:
                    self.show_error(exc)
            requests.submit('preview',lease.download(media,thumbnail=thumbnail),loaded,self.show_error,timeout=None)
        def save():
            if not valid() or 'save' in requests.jobs:return
            if blocked:self.show_error(PermissionError(tr('Protected content')));return
            # A basename only: never trust a remote attachment's path.
            base = download_name(media,filename)
            destination = filedialog.asksaveasfilename(parent=window, initialfile=base)
            if destination and valid():
                requests.submit('save',backend.download_media(getattr(media,'media',None) or media,Path(destination)),lambda _:self.status.set(tr('Archivo guardado.')),self.show_error,timeout=None)
        if preview_available(media,kind,filename):
            ttk.Button(frame, text=tr('Ver imagen / vista previa'), command=preview).pack(fill='x', pady=12)
        ttk.Button(frame, text=tr('Guardar archivo como...'), command=save,state='disabled' if blocked else 'normal').pack(fill='x', pady=6)

    def build_story_tab(self):
        from .advanced_features import feature_enabled
        if not feature_enabled(self,'stories'):
            self.stories_loaded=False;self.story_records=[]
            ttk.Label(self.story_page,text=tr('Las historias están desactivadas. Puedes activarlas en Funciones complejas.'),wraplength=520).pack(fill='x',pady=20)
            ttk.Button(self.story_page,text=tr('Funciones complejas'),command=self.complex_settings).pack(anchor='w')
            return
        ttk.Button(self.story_page, text=tr('Publish story'), command=self.new_story).pack(anchor='w', pady=6)
        ttk.Button(self.story_page, text=tr('Actualizar historias'), command=self.load_stories).pack(anchor='w', pady=(0, 12))
        self.story_list = ttk.Treeview(self.story_page, columns=('caption',), show='tree headings')
        self.story_list.heading('#0', text=tr('Cuenta'))
        self.story_list.heading('caption', text=tr('Historia'))
        self.story_list.column('#0', width=220)
        self.story_list.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(self.story_page, command=self.story_list.yview)
        self.story_list.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.story_list.bind('<Double-1>', self.open_story)
        self.story_list.bind('<Return>', self.open_story)
        self.stories_loaded = False
        self.story_records = []
        def selected(_):
            if self.notebook.select()==str(self.chat_page):self.adapt_chat_layout()
            else:self.viewport.minimum=(440,420);self.viewport.fit_content()
            if self.notebook.select() == str(self.story_page) and not self.stories_loaded and not self.busy:
                self.load_stories()
        self.notebook.bind('<<NotebookTabChanged>>', selected, add='+')

    def load_stories(self):
        from .advanced_features import feature_enabled
        if self.busy or not feature_enabled(self,'stories'): return
        account=self.ui_account;backend=self.service.backend
        def loaded(stories):
            if account!=self.ui_account or backend is not self.service.backend:return
            self.story_records, self.stories_loaded = stories, True
            self.story_list.delete(*self.story_list.get_children())
            for index, story in enumerate(stories):
                self.story_list.insert('', 'end', iid=str(index), text=story.name, values=(story.caption or tr('Historia'),))
            self.status.set(tr('Doble clic para abrir una historia.'))
        self.call(backend.stories(), loaded, tr('Cargando...'))

    def open_story(self, event=None):
        selected = self.story_list.selection()
        if self.busy or not selected: return
        story = self.story_records[int(selected[0])]
        from telethon import types
        kind = 'image' if isinstance(story.media, types.MessageMediaPhoto) else 'video'
        document = getattr(story.media, 'document', None)
        self.media_dialog(story.media, tr('Historia'), kind, story.name + '\n' + story.caption,
                          getattr(document, 'size', 0) or 0, story=story)


def account_label(app, key, default=None):
    """1.5.4: the alias chosen in this window's settings, else Telegram's name."""
    owner = getattr(app, '_linked_owner', None) or app
    values = getattr(getattr(owner, 'preferences', None), 'values', None)
    aliases = values.get('account_aliases') if isinstance(values, dict) else None
    labels = getattr(getattr(app, 'service', None), 'labels', {}) or {}
    return (aliases or {}).get(key) or labels.get(key, tr('Cuenta') if default is None else default)
