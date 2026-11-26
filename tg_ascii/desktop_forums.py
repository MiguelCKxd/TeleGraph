"""Desktop interface for forum topics and channel discussions (3.3).

The Telegram work lives in the shared core (forum_topics.py, owned by the
Codex team). This module only presents it, following the published contract:
``forum_topics``, ``forum_topic``, ``forum_create``, ``forum_edit``,
``forum_pin``, ``forum_delete`` and ``linked_discussion`` on the backend of
one account, and ``on_change('forum_topics', (peer, topic_id_or_None))``.
Topic conversations open in ``LinkedChatWindow`` in topic mode.
"""
import tkinter as tk
from tkinter import ttk

from .i18n import tr
from .interface_layout import caption

GENERAL = 1
SEARCH_DELAY_MS = 300
# The core reports every new forum message; one reload covers a burst.
CHANGE_DELAY_MS = 1500


def topic_label(row):
    """One list line: state marks, title and unread count."""
    marks = ''.join(mark for flag, mark in (('pinned', '📌'), ('closed', '🔒'), ('hidden', '🙈')) if row.get(flag))
    title = row.get('title') or (caption('General', 'General') if row.get('id') == GENERAL else '#' + str(row.get('id')))
    unread = row.get('unread_count') or 0
    return (marks + ' ' if marks else '') + title, (str(unread) if unread else '')


def sort_topics(rows):
    """Pinned first (server order kept), then the rest in server order."""
    rows = list(rows)
    return [row for row in rows if row.get('pinned')] + [row for row in rows if not row.get('pinned')]


def topic_actions(row):
    """[(label, action_name, value)] the user may run on a topic, by can_* rights."""
    actions = []
    if row.get('can_edit'):
        actions.append((caption('Rename topic', 'Renombrar tema'), 'rename', None))
        actions.append((caption('Reopen topic', 'Reabrir tema') if row.get('closed') else caption('Close topic', 'Cerrar tema'),
                        'closed', not row.get('closed')))
    if row.get('can_hide') and row.get('id') == GENERAL:
        actions.append((caption('Show General', 'Mostrar General') if row.get('hidden') else caption('Hide General', 'Ocultar General'),
                        'hidden', not row.get('hidden')))
    if row.get('can_pin'):
        actions.append((caption('Unpin topic', 'Desfijar tema') if row.get('pinned') else caption('Pin topic', 'Fijar tema'),
                        'pinned', not row.get('pinned')))
    if row.get('can_delete') and row.get('id') != GENERAL:
        actions.append((caption('Delete topic', 'Borrar tema'), 'delete', None))
    return actions


class TopicBrowser:
    """The topics of one forum group, for one account, in its own window."""

    def __init__(self, app, account, peer, title):
        self.app, self.account, self.peer = app, account, peer
        self.backend = app.service.backend
        self.rows, self.cursor, self.can_create = [], None, False
        self.loading = False
        self.serial = 0
        self._search_job = None
        self._change_job = None
        self.window, frame = app.dialog(caption('Topics', 'Temas') + ' · ' + title, '520x560')
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.bind('<Destroy>', lambda event: self.forget() if event.widget is self.window else None, add='+')
        from .back_gesture import install as install_back
        install_back(self.window, self.close)
        top = ttk.Frame(frame)
        top.pack(fill='x')
        ttk.Label(top, text=title, style='Title.TLabel').pack(side='left')
        self.query = tk.StringVar(master=self.window)
        search = ttk.Frame(frame)
        search.pack(fill='x', pady=(8, 4))
        ttk.Label(search, text=caption('Search topics', 'Buscar temas'), style='Muted.TLabel').pack(anchor='w')
        self.query.entry = ttk.Entry(search, textvariable=self.query)
        self.query.entry.pack(fill='x')
        self.query.trace_add('write', lambda *_: self.schedule_search())
        self.tree = ttk.Treeview(frame, columns=('unread',), show='tree', selectmode='browse', height=14)
        self.tree.column('#0', stretch=True, width=380)
        self.tree.column('unread', width=60, anchor='e', stretch=False)
        self.tree.pack(fill='both', expand=True, pady=4)
        self.tree.bind('<Double-Button-1>', lambda _: self.open_selected())
        self.tree.bind('<Return>', lambda _: self.open_selected())
        self.tree.bind('<Button-2>' if self.app.root.tk.call('tk', 'windowingsystem') == 'aqua' else '<Button-3>', self.context)
        self.status = tk.StringVar(master=self.window)
        ttk.Label(frame, textvariable=self.status, style='Muted.TLabel').pack(fill='x')
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x', pady=4)
        ttk.Button(buttons, text=tr('Abrir chat'), command=self.open_selected).pack(side='left')
        self.more_button = ttk.Button(buttons, text=caption('More topics', 'Más temas'), command=lambda: self.load(more=True))
        self.create_button = ttk.Button(buttons, text=caption('New topic', 'Nuevo tema'), command=self.create)
        ttk.Button(buttons, text=tr('Actualizar'), command=self.load).pack(side='right')
        app.__dict__.setdefault('_topic_browsers', []).append(self)
        self.load()

    # -- lifetime ----------------------------------------------------------------------
    def valid(self):
        try:
            alive = bool(self.window.winfo_exists())
        except tk.TclError:
            alive = False
        return alive and self.app.ui_account == self.account and self.app.service.backend is self.backend

    def forget(self):
        browsers = getattr(self.app, '_topic_browsers', [])
        if self in browsers:
            browsers.remove(self)

    def close(self):
        self.forget()
        try:
            self.window.destroy()
        except tk.TclError:
            pass

    def change(self, account, kind, payload):
        """Topic changes from Telegram refresh this group's list."""
        if kind != 'forum_topics' or account != self.account or not self.valid():
            return
        try:
            peer = payload[0]
        except (TypeError, IndexError):
            return
        if peer == self.peer and self._change_job is None:
            self._change_job = self.window.after(CHANGE_DELAY_MS, self.changed_reload)

    def changed_reload(self):
        self._change_job = None
        if self.valid():
            self.load()

    # -- loading ---------------------------------------------------------------------
    def schedule_search(self):
        if self._search_job is not None:
            self.window.after_cancel(self._search_job)
        self._search_job = self.window.after(SEARCH_DELAY_MS, self.load)

    def load(self, more=False):
        if not self.valid() or (more and not self.cursor):
            return
        self._search_job = None
        self.serial += 1
        serial, query = self.serial, self.query.get().strip()
        cursor = self.cursor if more else None
        self.status.set(tr('Loading...'))

        def loaded(result):
            if serial != self.serial or not self.valid():
                return
            rows = list(result.get('topics') or ())
            self.rows = merge_topics(self.rows, rows) if more else merge_topics([], rows)
            self.cursor = result.get('next_cursor')
            self.can_create = bool(result.get('can_create'))
            self.status.set('' if self.rows else caption('No topics found', 'No hay temas'))
            self.render()

        def failed(error):
            if serial != self.serial or not self.valid():
                return
            from .auth import error_message
            self.status.set(error_message(error))
        self.app.worker.submit(self.backend.forum_topics(self.peer, query, cursor), loaded, failed)

    def render(self):
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for row in sort_topics(self.rows):
            text, unread = topic_label(row)
            self.tree.insert('', 'end', iid=str(row['id']), text=text, values=(unread,))
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])
        if self.cursor:
            self.more_button.pack(side='left', padx=4)
        else:
            self.more_button.pack_forget()
        if self.can_create:
            self.create_button.pack(side='left', padx=4)
        else:
            self.create_button.pack_forget()

    def row(self, ident):
        return next((row for row in self.rows if str(row.get('id')) == str(ident)), None)

    def selected(self):
        selection = self.tree.selection()
        return self.row(selection[0]) if selection else None

    # -- actions ---------------------------------------------------------------------
    def open_selected(self):
        row = self.selected()
        if row is not None and self.valid():
            open_topic(self.app, self.account, self.peer, row)

    def context(self, event):
        ident = self.tree.identify_row(event.y)
        if not ident:
            return
        self.tree.selection_set(ident)
        row = self.row(ident)
        entries = [(tr('Abrir chat'), self.open_selected)]
        for label, action, value in topic_actions(row):
            entries.append((label, lambda a=action, v=value, r=row: self.run(r, a, v)))
        from .app_dialogs import popup_menu
        popup_menu(self.window, entries, event=event)
        return 'break'

    def run(self, row, action, value):
        if not self.valid():
            return
        from .app_dialogs import messagebox, simpledialog
        peer, ident = self.peer, row['id']
        if action == 'rename':
            title = simpledialog.askstring(caption('Rename topic', 'Renombrar tema'), caption('Title', 'Título'),
                                           initialvalue=row.get('title', ''), parent=self.window)
            if not title or not title.strip() or not self.valid():
                return
            operation = self.backend.forum_edit(peer, ident, title=title.strip()[:128])
        elif action == 'delete':
            if not messagebox.askyesno(caption('Delete topic', 'Borrar tema'),
                                       caption('Delete this topic and all its messages for everyone?',
                                               '¿Borrar este tema y todos sus mensajes para todos?'), parent=self.window):
                return
            if not self.valid():
                return
            operation = self.backend.forum_delete(peer, ident)
        elif action == 'pinned':
            operation = self.backend.forum_pin(peer, ident, value)
        else:
            operation = self.backend.forum_edit(peer, ident, **{action: value})

        def done(result):
            if not self.valid():
                return
            if action == 'delete':
                self.rows = [item for item in self.rows if item.get('id') != ident]
            elif isinstance(result, dict):
                self.rows = [result if item.get('id') == ident else item for item in self.rows]
            self.render()

        def failed(error):
            if self.valid():
                self.app.show_error(error)
        self.app.worker.submit(operation, done, failed)

    def create(self):
        if not self.valid() or not self.can_create:
            return
        from .app_dialogs import simpledialog
        title = simpledialog.askstring(caption('New topic', 'Nuevo tema'), caption('Title', 'Título'), parent=self.window)
        if not title or not title.strip() or not self.valid():
            return

        def created(row):
            if not self.valid() or not isinstance(row, dict):
                return
            self.rows = [row] + [item for item in self.rows if item.get('id') != row.get('id')]
            self.render()
            open_topic(self.app, self.account, self.peer, row)

        self.app.worker.submit(self.backend.forum_create(self.peer, title.strip()[:128]), created,
                               lambda error: self.app.show_error(error) if self.valid() else None)


def open_topics(app, peer=None):
    """Open (or raise) the topic list of the current forum chat."""
    peer = app.active if peer is None else peer
    if peer is None or getattr(app, 'demo', False):
        return None
    for browser in getattr(app, '_topic_browsers', ()):
        if browser.peer == peer and browser.account == app.ui_account and browser.valid():
            browser.window.deiconify()
            browser.window.lift()
            return browser
    chat = getattr(app, '_chat_by_id', {}).get(peer)
    return TopicBrowser(app, app.ui_account, peer, getattr(chat, 'name', str(peer)))


def open_topic(app, account, peer, row, message=None):
    """A topic's conversation in its own window; optionally jump to a message."""
    for window in getattr(app, '_chat_windows', ()):
        if (getattr(window, 'topic_id', None) == row.get('id') and window.peer == peer
                and window.account == account and not window.closed):
            window.window.deiconify()
            window.window.lift()
            if message:
                window.reveal_message(message)
            return window
    from .interface_windows import LinkedChatWindow
    window = LinkedChatWindow(app, account, peer, topic=row)
    app.__dict__.setdefault('_chat_windows', []).append(window)
    if message:
        window.reveal_message(message)
    return window


def open_discussion(app, peer=None):
    """A channel's linked discussion group (a forum opens its topics)."""
    peer = app.active if peer is None else peer
    if peer is None or getattr(app, 'demo', False) or app.busy:
        return
    account, backend = app.ui_account, app.service.backend

    def loaded(link):
        if account != app.ui_account or backend is not app.service.backend:
            return
        if not link:
            app.status.set(caption('This channel has no discussion group.', 'Este canal no tiene grupo de debate.'))
            return
        from .backend import Chat
        chat = next((item for item in app.chats if item.id == link['peer']), None)
        if chat is None:
            chat = Chat(link['peer'], link.get('title') or str(link['peer']), kind=link.get('kind', 'group'))
            try:
                chat.forum = bool(link.get('forum'))
            except AttributeError:
                pass
        app.open_resolved(chat)
        if link.get('forum'):
            open_topics(app, link['peer'])

    app.call(backend.linked_discussion(peer), loaded, tr('Loading...'))


def chat_flags(chat):
    """(forum, has_link) for a Chat, tolerant of cores without the fields."""
    return bool(getattr(chat, 'forum', False)), bool(getattr(chat, 'has_link', False))


def reveal_in_context(app, peer, ident, topic_id=None):
    """Gallery "Go to message": open the right place and highlight the message.

    A message of a forum topic other than General opens in its topic window
    (loading its page when it is not loaded); everything else goes through
    the main window's jump, which loads the surrounding history if needed.
    """
    chat = getattr(app, '_chat_by_id', {}).get(peer)
    forum, _ = chat_flags(chat)
    if forum and topic_id and not getattr(app, 'demo', False):
        account, backend = app.ui_account, app.service.backend

        def loaded(row):
            if account == app.ui_account and backend is app.service.backend and isinstance(row, dict):
                open_topic(app, account, peer, row, message=ident)

        def failed(_):
            # The same scope check as loaded: never jump in another account.
            if account == app.ui_account and backend is app.service.backend:
                app.jump_message(ident, peer)
        app.worker.submit(backend.forum_topic(peer, topic_id), loaded, failed)
        return
    app.jump_message(ident, peer)



# -- 3.3 extension: picking a topic, topic tools, enabling topics ------------------------
def writable_topics(rows):
    """Topics a message can be sent or forwarded to."""
    return [row for row in sort_topics(rows) if row.get('can_send', True) is not False]


def merge_topics(existing, page):
    """Append a page of topics, keeping the first copy of every topic id."""
    seen = {row.get('id') for row in existing}
    merged = list(existing)
    for row in page:
        if row.get('id') not in seen:
            seen.add(row.get('id'))
            merged.append(row)
    return merged


class TopicPicker:
    """Writable topics of a forum, searchable and paged with the core's opaque cursor."""

    def __init__(self, app, account, peer, title, chosen):
        self.app, self.account, self.peer, self.chosen = app, account, peer, chosen
        self.backend = app.service.backend
        self.rows, self.cursor, self.serial, self._search_job = [], None, 0, None
        self.window, frame = app.dialog(caption('Choose a topic', 'Elige un tema') + ' · ' + title, '440x500')
        self.query = tk.StringVar(master=self.window)
        entry = ttk.Entry(frame, textvariable=self.query)
        entry.pack(fill='x', pady=(0, 4))
        self.query.trace_add('write', lambda *_: self.schedule_search())
        self.listing = tk.Listbox(frame, exportselection=False, height=12)
        self.listing.pack(fill='both', expand=True, pady=4)
        self.status = tk.StringVar(master=self.window, value=tr('Loading...'))
        ttk.Label(frame, textvariable=self.status, style='Muted.TLabel').pack(fill='x')
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x', pady=6)
        self.more_button = ttk.Button(buttons, text=caption('More topics', 'Más temas'), command=lambda: self.load(more=True))
        ttk.Button(buttons, text=tr('Enviar >'), command=self.confirm).pack(side='right')
        self.listing.bind('<Double-Button-1>', self.confirm)
        self.listing.bind('<Return>', self.confirm)
        self.load()

    def valid(self):
        try:
            return (bool(self.window.winfo_exists()) and self.app.ui_account == self.account
                    and self.app.service.backend is self.backend)
        except tk.TclError:
            return False

    def schedule_search(self):
        if self._search_job is not None:
            self.window.after_cancel(self._search_job)
        self._search_job = self.window.after(SEARCH_DELAY_MS, self.load)

    def load(self, more=False):
        if not self.valid() or (more and not self.cursor):
            return
        self._search_job = None
        self.serial += 1
        serial, query = self.serial, self.query.get().strip()
        cursor = self.cursor if more else None
        self.status.set(tr('Loading...'))

        def loaded(result):
            # A late page of an older search, another account or backend changes nothing.
            if serial != self.serial or not self.valid():
                return
            page = writable_topics(result.get('topics') or ())
            self.rows = merge_topics(self.rows, page) if more else merge_topics([], page)
            self.cursor = result.get('next_cursor')
            self.render()

        def failed(error):
            if serial == self.serial and self.valid():
                from .auth import error_message
                self.status.set(error_message(error))
        self.app.worker.submit(self.backend.forum_topics(self.peer, query, cursor, 100), loaded, failed)

    def render(self):
        self.listing.delete(0, 'end')
        for row in self.rows:
            self.listing.insert('end', topic_label(row)[0])
        self.status.set('' if self.rows or self.cursor else caption('No topic accepts messages.', 'Ningún tema admite mensajes.'))
        if self.cursor:
            self.more_button.pack(side='left')
        else:
            self.more_button.pack_forget()

    def confirm(self, _=None):
        selection = self.listing.curselection()
        if not selection or not self.valid():
            return
        row = self.rows[selection[0]]
        self.window.destroy()
        self.chosen(row)


def choose_topic(app, account, peer, title, chosen):
    """A picker of a forum's writable topics; ``chosen(row)`` on confirm."""
    return TopicPicker(app, account, peer, title, chosen)


def forward_to(app, account, backend, chat, source, ids, done):
    """Forward ``ids`` from ``source`` to ``chat``, asking for the topic in a forum."""
    forum, _ = chat_flags(chat)
    if not forum:
        return False

    def chosen(row):
        if account != app.ui_account or backend is not app.service.backend:
            return
        app.call(backend.forum_forward(chat.id, row['id'], source, list(ids)), done, tr('Enviando...'))
    choose_topic(app, account, chat.id, chat.name, chosen)
    return True


def topic_search(window):
    """Search inside one topic (text, or pinned only); results jump to the message."""
    if not window.topic_id or not window.valid():
        return
    top = tk.Toplevel(window.window)
    top.title(caption('Search in topic', 'Buscar en el tema') + ' · ' + str((window.topic or {}).get('title', '')))
    top.geometry('480x460')
    from .back_gesture import install as install_back
    install_back(top, top.destroy)
    query = tk.StringVar(master=top)
    pinned = tk.BooleanVar(master=top, value=False)
    entry = ttk.Entry(top, textvariable=query)
    entry.pack(fill='x', padx=8, pady=(8, 4))
    ttk.Checkbutton(top, text=caption('Pinned messages only', 'Solo mensajes fijados'), variable=pinned).pack(anchor='w', padx=8)
    listing = tk.Listbox(top, exportselection=False)
    listing.pack(fill='both', expand=True, padx=8, pady=4)
    status = tk.StringVar(master=top)
    ttk.Label(top, textvariable=status).pack(fill='x', padx=8)
    found = []
    serial = [0]  # only the newest search may fill the list

    def loaded(messages, ticket):
        if ticket != serial[0] or not top.winfo_exists() or not window.valid():
            return
        found[:] = list(messages)
        listing.delete(0, 'end')
        for message in found:
            when = message.date.astimezone().strftime('%Y-%m-%d %H:%M') if getattr(message, 'date', None) else message.time
            listing.insert('end', f'{when} · {message.sender}: ' + (message.raw_text or message.text or '').replace('\n', ' ')[:100])
        status.set('' if found else caption('No results.', 'Sin resultados.'))

    def search(_=None):
        if not window.valid() or not top.winfo_exists():
            return
        status.set(tr('Loading...'))
        serial[0] += 1
        ticket = serial[0]
        window.call(window.backend.forum_search(window.peer, window.topic_id, query.get().strip(), pinned.get()),
                    lambda messages: loaded(messages, ticket),
                    lambda error: status.set(str(error)) if ticket == serial[0] and top.winfo_exists() else None)

    def open_selected(_=None):
        selection = listing.curselection()
        if selection and window.valid():
            window.reveal_message(found[selection[0]].id)
    entry.bind('<Return>', search)
    listing.bind('<Double-Button-1>', open_selected)
    listing.bind('<Return>', open_selected)
    buttons = ttk.Frame(top)
    buttons.pack(fill='x', padx=8, pady=6)
    ttk.Button(buttons, text=tr('Search'), command=search).pack(side='left')
    ttk.Button(buttons, text=tr('Go to message'), command=open_selected).pack(side='left', padx=4)
    entry.focus_set()
    return top


def topic_scheduled(window):
    """Scheduled messages of one topic: send now or delete, as for a whole chat."""
    if not window.topic_id or not window.valid():
        return
    from .app_dialogs import messagebox
    top = tk.Toplevel(window.window)
    top.title(tr('Scheduled messages') + ' · ' + str((window.topic or {}).get('title', '')))
    top.geometry('520x420')
    from .back_gesture import install as install_back
    install_back(top, top.destroy)
    listing = tk.Listbox(top, exportselection=False)
    listing.pack(fill='both', expand=True, padx=8, pady=8)
    records = []

    def loaded(items):
        if not top.winfo_exists():
            return
        records[:] = list(items)
        listing.delete(0, 'end')
        for item in records:
            listing.insert('end', item.date.astimezone().strftime('%Y-%m-%d %H:%M') + ' · ' +
                           (item.raw_text or tr('Archivo adjunto')).replace('\n', ' ')[:100])
        if not records:
            listing.insert('end', caption('No scheduled messages in this topic.', 'No hay mensajes programados en este tema.'))

    def refresh():
        if window.valid() and top.winfo_exists():
            window.call(window.backend.forum_scheduled(window.peer, window.topic_id), loaded, lambda _: None)

    def apply(send_now):
        selection = listing.curselection()
        if not selection or selection[0] >= len(records) or not window.valid():
            return
        label = tr('Send now') if send_now else tr('Delete message')
        if not messagebox.askyesno(tr('Scheduled messages'), label + '?', parent=top) or not window.valid():
            return
        window.call(window.backend.change_scheduled(window.peer, records[selection[0]].id, send_now), lambda _: refresh())
    buttons = ttk.Frame(top)
    buttons.pack(fill='x', padx=8, pady=(0, 8))
    ttk.Button(buttons, text=tr('Send now'), command=lambda: apply(True)).pack(side='left')
    ttk.Button(buttons, text=tr('Delete message'), command=lambda: apply(False)).pack(side='left', padx=4)
    ttk.Button(buttons, text=tr('Actualizar'), command=refresh).pack(side='right')
    refresh()
    return top


def topics_toggle_entry(app, peer):
    """(label, callback) for the ⋯ menu when the account owns this group, else None."""
    if getattr(app, 'demo', False):
        return None
    entity = getattr(app.service.backend, '_capability_entities', {}).get(peer)
    if entity is None or not getattr(entity, 'creator', False) or getattr(entity, 'broadcast', False):
        return None
    enabled = bool(getattr(entity, 'forum', False))
    label = caption('Disable topics', 'Desactivar temas') if enabled else caption('Enable topics', 'Activar temas')
    return label, lambda: toggle_topics(app, peer, not enabled, basic=not getattr(entity, 'megagroup', False))


def toggle_confirmation(enabled, basic):
    """The question asked before Telegram changes the group (None: not possible)."""
    if enabled and basic:
        return caption('To enable topics Telegram converts this group into a supergroup. '
                       'This cannot be undone. Continue?',
                       'Para activar los temas, Telegram convierte este grupo en supergrupo. '
                       'No se puede deshacer. ¿Continuar?')
    if enabled:
        return caption('Enable topics in this group?', '¿Activar los temas en este grupo?')
    return caption('Disable topics? Messages are kept; the group shows one conversation again.',
                   '¿Desactivar los temas? Los mensajes se conservan y el grupo vuelve a ser una sola conversación.')


def toggle_topics(app, peer, enabled, basic=False):
    if app.busy or getattr(app, 'demo', False):
        return
    from .app_dialogs import messagebox
    if not messagebox.askyesno(caption('Topics', 'Temas'), toggle_confirmation(enabled, basic), parent=app.root):
        return
    account, backend = app.ui_account, app.service.backend

    def done(chat):
        if account != app.ui_account or backend is not app.service.backend or chat is None:
            return
        # A converted basic group comes back with a new (supergroup) peer.
        app.chats = [item for item in app.chats if item.id not in (peer, chat.id)] + [chat]
        app.open_resolved(chat)
        if hasattr(app, 'update_chat_capabilities'):
            app.update_chat_capabilities()
        if chat_flags(chat)[0]:
            open_topics(app, chat.id)
    app.call(backend.forum_toggle(peer, enabled, migrate=bool(enabled and basic)), done, tr('Guardando...'))
