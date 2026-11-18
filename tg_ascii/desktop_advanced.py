"""Opt-in message tools. Dialogs load data only after an explicit user action."""
import tkinter as tk
import weakref
from copy import copy, deepcopy
from tkinter import ttk

from telethon import types as t
from telethon import utils

from .advanced_editor import EntityField
from .advanced_features import feature_enabled
from .advanced_messaging import advanced_media_summary, plain, todo_fingerprint
from .app_dialogs import Choice, messagebox, popup_menu, simpledialog
from .chat_capabilities import chat_capabilities, gift_action_available
from .contact_profile import ProfileRequests
from .i18n import tr
from .scrolling import FlowFrame


class AdvancedDialog:
    """Read ownership and stale account/chat protection shared by these panels."""
    def __init__(self, app, feature, title, size='620x680', *, peer=None):
        self.app, self.feature = app, feature
        self.account, self.backend = app.ui_account, app.service.backend
        self.peer = app.active if peer is None else peer
        self.origin = app.active
        self.window, self.frame = app.dialog(title, size)
        self.requests = ProfileRequests(app, self.window, self.account, self.backend)
        self.requests.valid = self.valid
        self.window.bind('<Destroy>', self.closed, add='+')
        self.status = tk.StringVar(master=self.window)
        ttk.Label(self.frame, textvariable=self.status, wraplength=560).pack(fill='x', pady=4)
        self.body = ttk.Frame(self.frame)
        self.body.pack(fill='both', expand=True)

    def closed(self, event):
        if event.widget is not self.window: return
        self.requests.close()
        # Break UI callback cycles on Tk's thread. Otherwise cyclic GC in the
        # network worker could run a tkinter.Variable finalizer off-thread.
        self.requests.valid = lambda: False
        self.status = None
        self.pending_message = None
        self.updated = None
        self._poll_selection = None
        job = getattr(self, 'update_job', None)
        if job is not None:
            job.cancel()
            job.callback = lambda: None
        listeners = getattr(self.app, '_advanced_inspectors', None)
        if listeners is not None: listeners.discard(self)

    def valid(self):
        return (not self.requests.closed and not getattr(self.app, 'closing', False)
                and not getattr(self.app, 'closed', False) and bool(self.window.winfo_exists())
                and self.account == self.app.ui_account and self.backend is self.app.service.backend
                and self.origin == self.app.active and feature_enabled(self.app, self.feature))

    def read(self, key, coroutine, done):
        self.status.set(tr('Loading...'))
        def loaded(value):
            self.status.set('')
            done(value)
        self.requests.submit(key, coroutine, loaded, lambda error: self.status.set(str(error)))

    def refresh_message(self, message):
        if not self.valid(): return
        if message is not None and hasattr(message, 'id'):
            # Mutations already return an authoritative message. Reuse it in the
            # inspector and every window, including profiles for another chat.
            watched = getattr(self, 'message_id', None) == message.id
            if watched and getattr(self, 'update_job', None) is not None:
                self.pending_message = message
                self.update_job.request()
            owner = getattr(self.app, '_linked_owner', None) or self.app
            existing = watched or (self.peer == self.app.active and any(item.id == message.id for item in self.app.messages))
            if existing and callable(getattr(owner, 'account_change', None)):
                owner.account_change((self.account, 'advanced_media', (self.peer, message)))
                return
            publish = getattr(self.app, 'account_event', None)
            if not existing and callable(publish):
                publish((self.account, self.peer, message))
                return
            if self.peer != self.app.active: return
            messages = {item.id: item for item in self.app.messages}
            messages[message.id] = message
            self.app.messages = sorted(messages.values(), key=lambda item: item.id)[-200:]
            self.app.render_messages(False)

    def mutate(self, factory, done=None, *, confirm=None, close=False, capability=None, message=None):
        def allowed():
            if not self.valid() or self.app.busy: return False
            if capability is None: return True
            caps = chat_capabilities(self.app, self.peer)
            return caps.allows_message(capability, message) if message is not None else caps.allows(capability)
        if not allowed(): return
        if confirm and not messagebox.askyesno(tr('Confirm'), confirm, parent=self.window): return
        # Native modal dialogs may run event callbacks that switch/logout accounts.
        if not allowed(): return
        def completed(result):
            if not self.valid(): return
            self.refresh_message(result)
            self.status.set(tr('Saved.'))
            if done: done(result)
            if close and self.window.winfo_exists(): self.window.destroy()
        def failed(error):
            if self.valid(): self.status.set(str(error))
        try: operation = factory()
        except (ValueError, TypeError) as exc: failed(exc); return
        self.app.call(operation, completed, tr('Saving...'), failed)

    def button(self, parent, label, command):
        button = ttk.Button(parent, text=tr(label), command=command)
        button.pack(fill='x', pady=4)
        return button

    def watch(self, ident, callback):
        """Open inspectors consume push events without polling Telegram."""
        from .ui_work import FrameJob
        self.message_id, self.updated = ident, callback
        self.pending_message = None
        def render():
            value, self.pending_message = self.pending_message, None
            if value is not None and self.valid(): self.updated(value)
        self.update_job = FrameJob(self.window, render, 32)
        listeners = getattr(self.app, '_advanced_inspectors', None)
        if listeners is None: listeners = self.app._advanced_inspectors = weakref.WeakSet()
        listeners.add(self)
        self.window.bind('<Destroy>', lambda event: self.update_job.cancel() if event.widget is self.window else None, add='+')


def _read_only(parent, text, height=8):
    widget = tk.Text(parent, height=height, wrap='word')
    widget.insert('1.0', text)
    widget.configure(state='disabled')
    widget.pack(fill='both', expand=True, pady=6)
    return widget


def _entity_field(parent, app, label, value='', height=2):
    ttk.Label(parent, text=tr(label)).pack(anchor='w', pady=(8, 2))
    field = EntityField(parent, app, value, height=height)
    field.pack(fill='x')
    return field


def _check(parent, label, value=False):
    variable = tk.BooleanVar(master=parent, value=value)
    ttk.Checkbutton(parent, text=tr(label), variable=variable).pack(anchor='w', pady=3)
    return variable


class DesktopAdvancedMixin:
    def advanced_media_changed(self, account, peer, message):
        for dialog in tuple(getattr(self, '_advanced_inspectors', ())):
            if (dialog.account, dialog.peer, dialog.message_id) == (account, peer, message.id) and dialog.valid():
                dialog.pending_message = message
                dialog.update_job.request()

    def _advanced_available(self, feature, *, chat=True):
        return (feature_enabled(self, feature) and not self.demo and not self.busy
                and not getattr(self, 'closed', False) and not getattr(self, 'closing', False)
                and (not chat or self.active is not None))

    def open_advanced_menu(self):
        entries = []
        caps = chat_capabilities(self)
        for feature, action, title, callback in (
            ('polls', 'poll', 'Poll / quiz', self.new_poll_dialog),
            ('checklists', 'checklist', 'Checklist', self.new_checklist_dialog),
            ('locations', 'location', 'Share location', self.location_dialog),
            ('contacts', 'contact', 'Share contact', self.share_contact_dialog),
            ('articles', 'article', 'Article', self.article_composer),
            ('stars_gifts', 'gift', 'Stars, gifts and Premium', self.gifts_dialog)):
            if not self.demo and feature_enabled(self, feature) and caps.allows(action):
                entries.append((tr(title), callback, True))
        if not entries: return
        popup_menu(self.root, entries, anchor=getattr(self, 'composer_controls', None))

    def advanced_message_actions(self, message):
        if self.demo: return []
        caps = chat_capabilities(self)
        if not caps.readable: return []
        kind = getattr(message, 'media_kind', '')
        feature = {'poll': 'polls', 'checklist': 'checklists', 'location': 'locations',
                   'contact': 'contacts', 'gift': 'stars_gifts', 'article': 'articles'}.get(kind)
        entries = []
        if feature and feature_enabled(self, feature):
            callback = {'poll': self.poll_dialog, 'checklist': self.checklist_dialog,
                        'location': self.location_details, 'contact': self.contact_card_dialog,
                        'gift': self.received_gift_dialog, 'article': self.article_dialog}[kind]
            account, peer, backend = self.ui_account, self.active, self.service.backend
            def open_scoped():
                if (account, peer) == (self.ui_account, self.active) and backend is self.service.backend:
                    callback(message)
            entries.append((tr('Open') + ' · ' + tr({'poll': 'Poll', 'checklist': 'Checklist', 'location': 'Location',
                'contact': 'Contact', 'gift': 'Gift', 'article': 'Article'}[kind]), open_scoped))
        if feature_enabled(self, 'stars_gifts') and caps.allows_message('star_react', message):
            account, peer, backend = self.ui_account, self.active, self.service.backend
            def paid():
                if (account, peer) == (self.ui_account, self.active) and backend is self.service.backend and chat_capabilities(self).allows_message('star_react', message):
                    self.paid_reaction_dialog(message)
            entries.append((tr('Send Star reaction'), paid))
        return entries

    def open_advanced_message(self, message, peer=None):
        kind = getattr(message, 'media_kind', '')
        callbacks = {'poll': self.poll_dialog, 'checklist': self.checklist_dialog,
                     'location': self.location_details, 'contact': self.contact_card_dialog,
                     'gift': self.received_gift_dialog, 'article': self.article_dialog}
        callback = callbacks.get(kind)
        if callback is not None: callback(message, peer=peer)

    def compose_bot_request(self, kind, reply_to, quiz=None):
        if kind == 'locations' and self._advanced_available('locations'):
            self.location_dialog(reply_to=reply_to)
        elif kind == 'polls' and self._advanced_available('polls'):
            self.new_poll_dialog(reply_to=reply_to, quiz_mode=quiz)

    def new_poll_dialog(self, *, reply_to=None, quiz_mode=None):
        if not self._advanced_available('polls'): return
        from .chat_capabilities import chat_capabilities
        if not chat_capabilities(self).allows('poll'): return
        dialog = AdvancedDialog(self, 'polls', 'New poll / quiz', '680x820')
        dialog.reply_to = reply_to
        from .poll_attachment_editor import PollAttachmentEditor
        attachments = PollAttachmentEditor(dialog)
        dialog.poll_attachments = attachments
        question = _entity_field(dialog.body, self, 'Question', height=3)
        attachments.add(dialog.body, 'attached_media')
        rows = ttk.Frame(dialog.body); rows.pack(fill='x')
        answers = []
        def add_answer(value=''):
            row = ttk.Frame(rows); row.pack(fill='x', pady=3)
            correct = tk.BooleanVar(master=row)
            ttk.Checkbutton(row, text=str(len(answers) + 1), variable=correct).pack(side='left')
            editor = EntityField(row, self, value, height=1); editor.pack(side='left', fill='x', expand=True)
            answers.append((row, editor, correct))
        for _ in range(2): add_answer()
        actions = FlowFrame(dialog.body); actions.pack(fill='x')
        ttk.Button(actions, text=tr('Add answer'), command=add_answer).pack(side='left', pady=4)
        def remove_answer():
            if len(answers) > 2: answers.pop()[0].destroy()
        ttk.Button(actions, text=tr('Remove last answer'), command=remove_answer).pack(side='left', padx=4)
        ttk.Label(dialog.body, text=tr('For a quiz, tick the correct answer numbers. Right-click text to format it or insert custom emoji.'), wraplength=600).pack(fill='x', pady=5)
        anonymous = _check(dialog.body, 'Anonymous votes', True)
        multiple = _check(dialog.body, 'Multiple answers')
        quiz = _check(dialog.body, 'Quiz')
        if quiz_mode is not None:
            quiz.set(bool(quiz_mode))
            for child in dialog.body.winfo_children():
                if isinstance(child, ttk.Checkbutton) and str(child.cget('variable')) == str(quiz):
                    child.configure(state='disabled')
        open_answers = _check(dialog.body, 'Participants can add answers')
        revoting = _check(dialog.body, 'Allow changing the vote', True)
        shuffle = _check(dialog.body, 'Shuffle answer order')
        hidden = _check(dialog.body, 'Hide results until the poll closes')
        subscribers = _check(dialog.body, 'Only eligible subscribers can vote')
        countries = self.field(dialog.body, 'Allowed country codes, comma-separated (optional)')
        duration = self.field(dialog.body, 'Close after this many seconds (optional)')
        solution_group = ttk.Frame(dialog.body)
        solution = _entity_field(solution_group, self, 'Quiz explanation', height=2)
        attachments.add(solution_group, 'solution_media')
        attachments.solution_enabled = quiz.get
        def send():
            try:
                options = {'anonymous': anonymous.get(), 'multiple': multiple.get(), 'quiz': quiz.get(),
                    'correct': [index for index, (_, _, correct) in enumerate(answers) if correct.get()] if quiz.get() else [],
                    'solution': solution.value() if quiz.get() else '', 'open_answers': open_answers.get(), 'revoting': revoting.get(),
                    'shuffle': shuffle.get(), 'hidden_results': hidden.get(), 'subscribers_only': subscribers.get(),
                    'countries': [value.strip() for value in countries.get().split(',') if value.strip()],
                    'close_period': int(duration.get()) if duration.get().strip() else None}
            except ValueError as exc: dialog.status.set(str(exc)); return
            attachments.send(question.value(), [editor.value() for _, editor, _ in answers],
                             options, self._advanced_reply(dialog))
        send_button = dialog.button(dialog.body, 'Send poll', send)
        attachments.controls(dialog.body)
        def show_solution(*_):
            if quiz.get(): solution_group.pack(fill='x', before=send_button)
            else: solution_group.pack_forget()
        trace = quiz.trace_add('write', show_solution)
        show_solution()
        dialog.window.bind('<Destroy>', lambda event: quiz.trace_remove('write', trace)
            if event.widget is dialog.window else None, add='+')

    def _advanced_reply(self, dialog):
        if getattr(dialog, 'reply_to', None) is not None: return dialog.reply_to
        return getattr(self, 'reply_drafts', {}).get((dialog.account, dialog.peer))

    def poll_dialog(self, message, peer=None):
        if not self._advanced_available('polls', chat=peer is None): return
        dialog = AdvancedDialog(self, 'polls', 'Poll / quiz', '620x720', peer=peer)
        def refresh():
            if dialog.valid(): dialog.read('poll', dialog.backend.poll_state(dialog.peer, message.id), show)
        def show(state):
            media, own = state
            observed = copy(message); observed.media = media
            caps = chat_capabilities(self, dialog.peer)
            can_vote = caps.allows_message('vote', observed)
            selected_before = getattr(dialog, '_poll_selection', lambda: set())()
            pending_choice = selected_before if selected_before != getattr(dialog, '_poll_chosen', set()) else None
            for child in dialog.body.winfo_children(): child.destroy()
            poll, results = media.poll, media.results
            _read_only(dialog.body, plain(poll.question), 3)
            counts = {item.option: item for item in results.results or ()}
            order = list(poll.answers)
            if poll.shuffle_answers:
                # Stable within a dialog; no timer or repeated reshuffle while voting.
                import random
                random.Random(str(dialog.account) + ':' + str(poll.id)).shuffle(order)
            single = tk.StringVar(master=dialog.window)
            selected = {}
            for index, answer in enumerate(order):
                result = counts.get(answer.option)
                count = getattr(result, 'voters', None)
                label = plain(answer.text) + (f' — {count}' if count is not None else '')
                if getattr(result, 'correct', False): label += ' ✓'
                if not can_vote:
                    ttk.Label(dialog.body, text=('☑ ' if getattr(result, 'chosen', False) else '') + label, wraplength=560).pack(fill='x', pady=3)
                    continue
                if poll.multiple_choice:
                    variable = tk.BooleanVar(master=dialog.window, value=bool(getattr(result, 'chosen', False)))
                    ttk.Checkbutton(dialog.body, text=label, variable=variable).pack(fill='x', pady=3)
                else:
                    variable = str(index)
                    if getattr(result, 'chosen', False): single.set(variable)
                    ttk.Radiobutton(dialog.body, text=label, variable=single, value=variable).pack(fill='x', pady=3)
                selected[answer.option] = variable
            dialog._poll_selection = lambda: ({option for option, value in selected.items() if value.get()}
                if poll.multiple_choice else {option for option, value in selected.items() if value == single.get()})
            dialog._poll_chosen = {item.option for item in results.results or () if item.chosen}
            if pending_choice is not None and can_vote:
                if poll.multiple_choice:
                    for option, variable in selected.items(): variable.set(option in pending_choice)
                else:
                    single.set(next((value for option, value in selected.items() if option in pending_choice), ''))
            if results.total_voters is not None:
                ttk.Label(dialog.body, text=tr('{count} votes').format(count=results.total_voters)).pack(pady=5)
            if results.solution: _read_only(dialog.body, results.solution, 3)
            if can_vote:
                def vote():
                    options = [option for option, value in selected.items()
                               if value.get()] if poll.multiple_choice else [
                                   option for option, value in selected.items() if value == single.get()]
                    if not options: dialog.status.set(tr('Choose an answer.')); return
                    dialog.mutate(lambda: dialog.backend.vote_poll(dialog.peer, message.id, options), capability='vote', message=observed)
                dialog.button(dialog.body, 'Vote', vote)
                if caps.allows_message('retract_vote', observed):
                    dialog.button(dialog.body, 'Retract vote', lambda: dialog.mutate(
                        lambda: dialog.backend.vote_poll(dialog.peer, message.id, []), capability='retract_vote', message=observed))
            if poll.public_voters:
                dialog.button(dialog.body, 'View voters', lambda: self.poll_voters_dialog(message, peer=dialog.peer))
            if caps.allows_message('append_poll_answer', observed):
                def add():
                    value = simpledialog.askstring(tr('Add answer'), tr('Answer'), parent=dialog.window)
                    if value and dialog.valid(): dialog.mutate(lambda: dialog.backend.append_poll_answer(dialog.peer, message.id, value), capability='append_poll_answer', message=observed)
                dialog.button(dialog.body, 'Add answer', add)
                identity = getattr(getattr(dialog.backend, 'account_profile', None), 'user_id', None)
                removable = [answer for answer in poll.answers if own or caps.creator or
                             isinstance(getattr(answer, 'added_by', None), t.PeerUser) and answer.added_by.user_id == identity]
                def remove():
                    entries = [(plain(answer.text), lambda option=answer.option: dialog.mutate(
                        lambda: dialog.backend.delete_poll_answer(dialog.peer, message.id, option),
                        confirm=tr('Remove this answer? Telegram checks whether you can remove it.'),
                        capability='delete_poll_answer', message=observed)) for answer in removable]
                    popup_menu(dialog.window, entries)
                if removable: dialog.button(dialog.body, 'Remove answer', remove)
            if caps.allows_message('close_poll', observed):
                dialog.button(dialog.body, 'Close poll', lambda: dialog.mutate(
                    lambda: dialog.backend.close_poll(dialog.peer, message.id), confirm=tr('Close this poll permanently?'),
                    capability='close_poll', message=observed))
            if poll.closed: ttk.Label(dialog.body, text=tr('Closed poll')).pack(pady=6)
            dialog.button(dialog.body, 'Refresh', refresh)
        dialog.watch(message.id, lambda value: show((value.media, bool(value.outgoing or value.media.poll.creator)))
                     if isinstance(value.media, t.MessageMediaPoll) else None)
        refresh()

    def poll_voters_dialog(self, message, peer=None):
        if not self._advanced_available('polls', chat=peer is None): return
        dialog = AdvancedDialog(self, 'polls', 'Poll voters', '560x560', peer=peer)
        listing = tk.Listbox(dialog.body, height=16); listing.pack(fill='both', expand=True)
        offset, pending = [''], [False]
        def load():
            if pending[0] or not dialog.valid(): return
            pending[0] = True
            async def fetch():
                try: return await dialog.backend.poll_voters(dialog.peer, message.id, offset=offset[0])
                finally: pending[0] = False
            def loaded(result):
                rows, next_offset = result
                for _, name, choices in rows: listing.insert('end', name + ' — ' + ', '.join(choices))
                offset[0] = next_offset
                more.configure(state='normal' if next_offset else 'disabled')
            dialog.read('voters', fetch(), loaded)
        more = dialog.button(dialog.body, 'Load more', load)
        load()

    def new_checklist_dialog(self, message=None, state=None, peer=None):
        if not self._advanced_available('checklists', chat=peer is None): return
        caps = chat_capabilities(self, peer)
        if not (caps.allows_message('edit_checklist', message) if message else caps.allows('checklist')): return
        dialog = AdvancedDialog(self, 'checklists', 'Edit checklist' if message else 'New checklist', '650x760', peer=peer)
        if message is not None: dialog.message_id = message.id
        existing = state.todo if state is not None else None
        snapshot = todo_fingerprint(existing) if existing else None
        title = _entity_field(dialog.body, self, 'Title', existing.title if existing else '')
        rows = ttk.Frame(dialog.body); rows.pack(fill='x')
        items = []
        def add(ident=None, value=''):
            import secrets
            used = {item[0] for item in items}
            if ident is None:
                ident = secrets.randbelow(2 ** 31 - 1) + 1
                while ident in used: ident = secrets.randbelow(2 ** 31 - 1) + 1
            row = ttk.Frame(rows); row.pack(fill='x', pady=3)
            field = EntityField(row, self, value, height=2); field.pack(side='left', fill='x', expand=True)
            record = (ident, field, row); items.append(record)
            def remove():
                if record in items: items.remove(record); row.destroy()
            ttk.Button(row, text='−', width=3, command=remove).pack(side='right')
        for item in existing.list if existing else (): add(item.id, item.title)
        if not items: add()
        dialog.button(dialog.body, 'Add task', add)
        append = _check(dialog.body, 'Others can add tasks', bool(existing and existing.others_can_append))
        complete = _check(dialog.body, 'Others can complete tasks', bool(existing and existing.others_can_complete))
        def save():
            data = [(ident, field.value()) for ident, field, _ in items]
            options = {'others_can_append': append.get(), 'others_can_complete': complete.get()}
            operation = lambda: dialog.backend.edit_checklist(dialog.peer, message.id, title.value(), data, snapshot, **options) if message else dialog.backend.send_checklist(dialog.peer, title.value(), data, reply_to=self._advanced_reply(dialog), **options)
            dialog.mutate(operation, close=True, capability='edit_checklist' if message else 'checklist', message=message)
        dialog.button(dialog.body, 'Save' if message else 'Send checklist', save)

    def checklist_dialog(self, message, peer=None):
        if not self._advanced_available('checklists', chat=peer is None): return
        dialog = AdvancedDialog(self, 'checklists', 'Checklist', '600x680', peer=peer)
        def refresh():
            if dialog.valid(): dialog.read('checklist', dialog.backend.checklist_state(dialog.peer, message.id), show)
        def show(state):
            media, own = state
            observed = copy(message); observed.media = media; observed.outgoing = own
            caps = chat_capabilities(self, dialog.peer)
            for child in dialog.body.winfo_children(): child.destroy()
            _read_only(dialog.body, plain(media.todo.title), 2)
            completed = {item.id: item for item in media.completions or ()}
            for item in media.todo.list:
                if not caps.allows_message('toggle_checklist', observed):
                    ttk.Label(dialog.body, text=('☑ ' if item.id in completed else '☐ ') + plain(item.title), wraplength=540).pack(fill='x', pady=4)
                    continue
                variable = tk.BooleanVar(master=dialog.window, value=item.id in completed)
                def toggle(ident=item.id, variable=variable):
                    target = variable.get()
                    dialog.mutate(lambda: dialog.backend.toggle_checklist(dialog.peer, message.id, ident, target), capability='toggle_checklist', message=observed)
                button = ttk.Checkbutton(dialog.body, text=plain(item.title), variable=variable, command=toggle)
                button.pack(fill='x', pady=4)
            if caps.allows_message('append_checklist', observed):
                def append():
                    value = simpledialog.askstring(tr('Add task'), tr('Task'), parent=dialog.window)
                    if value and dialog.valid(): dialog.mutate(lambda: dialog.backend.append_checklist(dialog.peer, message.id, [value]), capability='append_checklist', message=observed)
                dialog.button(dialog.body, 'Add task', append)
            if caps.allows_message('edit_checklist', observed):
                dialog.button(dialog.body, 'Edit checklist', lambda: self.new_checklist_dialog(observed, media, dialog.peer))
            dialog.button(dialog.body, 'Refresh', refresh)
        dialog.watch(message.id, lambda value: show((value.media, value.outgoing))
                     if isinstance(value.media, t.MessageMediaToDo) else None)
        refresh()

    def location_dialog(self, message=None, peer=None, *, reply_to=None):
        if not self._advanced_available('locations', chat=peer is None): return
        if not chat_capabilities(self, peer).allows('location'): return
        dialog = AdvancedDialog(self, 'locations', 'Share location', '560x620', peer=peer)
        if message is not None: dialog.message_id = message.id
        dialog.reply_to = reply_to
        current = getattr(getattr(message, 'media', None), 'geo', None)
        lat = self.field(dialog.body, 'Latitude', str(current.lat) if isinstance(current, t.GeoPoint) else '')
        lon = self.field(dialog.body, 'Longitude', str(current.long) if isinstance(current, t.GeoPoint) else '')
        title = self.field(dialog.body, 'Place name (optional)')
        address = self.field(dialog.body, 'Address (optional)')
        periods = [None, 900, 3600, 28800, 2 ** 31 - 1]
        picker = Choice(dialog.body, values=[tr(value) for value in ('Static location', 'Live · 15 minutes', 'Live · 1 hour', 'Live · 8 hours', 'Live · until stopped')])
        picker.current(0); picker.pack(fill='x', pady=8)
        ttk.Label(dialog.body, text=tr('Coordinates are entered manually. A live location changes only when you explicitly update it here; this app does not track your device.'), wraplength=490).pack(fill='x', pady=8)
        def send():
            factory = lambda: dialog.backend.edit_location(dialog.peer, message.id, lat.get(), lon.get()) if message else dialog.backend.send_location(dialog.peer, lat.get(), lon.get(), title=title.get(), address=address.get(), period=periods[picker.current()], reply_to=self._advanced_reply(dialog))
            dialog.mutate(factory, close=True, confirm=tr('Share these coordinates with this chat?'), capability='location')
        dialog.button(dialog.body, 'Update location' if message else 'Share location', send)

    def location_details(self, message, peer=None):
        if not self._advanced_available('locations', chat=peer is None): return
        dialog = AdvancedDialog(self, 'locations', 'Location', '540x400', peer=peer)
        dialog.message_id = message.id
        media = message.media
        _read_only(dialog.body, advanced_media_summary(media)[1], 5)
        if isinstance(getattr(media, 'geo', None), t.GeoPoint):
            geo = media.geo
            dialog.button(dialog.body, 'Open map', lambda: self.open_link(f'https://www.openstreetmap.org/?mlat={geo.lat:.6f}&mlon={geo.long:.6f}#map=16/{geo.lat:.6f}/{geo.long:.6f}') if dialog.valid() else None)
        if message.outgoing and isinstance(media, t.MessageMediaGeoLive):
            dialog.button(dialog.body, 'Update location', lambda: self.location_dialog(message, dialog.peer))
            dialog.button(dialog.body, 'Stop live location', lambda: dialog.mutate(
                lambda: dialog.backend.edit_location(dialog.peer, message.id, stop=True), close=True,
                confirm=tr('Stop sharing this live location?')))

    def share_contact_dialog(self):
        if not self._advanced_available('contacts'): return
        if not chat_capabilities(self).allows('contact'): return
        dialog = AdvancedDialog(self, 'contacts', 'Share contact', '560x620')
        first = self.field(dialog.body, 'Nombre')
        last = self.field(dialog.body, 'Apellidos')
        phone = self.field(dialog.body, 'Telefono internacional')
        vcard = self.field(dialog.body, 'vCard (optional)')
        listing = tk.Listbox(dialog.body, height=7); listing.pack(fill='both', expand=True, pady=8)
        records = []
        def loaded(contacts):
            records[:] = [contact for contact in contacts if getattr(contact, 'phone', None)]
            listing.delete(0, 'end')
            for contact in records: listing.insert('end', utils.get_display_name(contact))
        def selected(_):
            selection = listing.curselection()
            if not selection: return
            contact = records[selection[0]]
            first.set(contact.first_name or ''); last.set(contact.last_name or ''); phone.set('+' + contact.phone.lstrip('+'))
        listing.bind('<<ListboxSelect>>', selected)
        dialog.button(dialog.body, 'Choose from contacts', lambda: dialog.read('contacts', dialog.backend.contacts(), loaded))
        dialog.button(dialog.body, 'Share contact', lambda: dialog.mutate(lambda: dialog.backend.send_contact_card(
            dialog.peer, first.get(), last.get(), phone.get(), vcard=vcard.get(), reply_to=self._advanced_reply(dialog)),
            close=True, confirm=tr('Share this name, phone number and contact card with the chat?'), capability='contact'))

    def contact_card_dialog(self, message, peer=None):
        if not self._advanced_available('contacts', chat=peer is None): return
        dialog = AdvancedDialog(self, 'contacts', 'Contact', '520x480', peer=peer)
        card = message.media
        _read_only(dialog.body, advanced_media_summary(card)[1], 5)
        if card.vcard: _read_only(dialog.body, card.vcard, 5)
        dialog.button(dialog.body, 'Guardar contacto', lambda: dialog.mutate(
            lambda: dialog.backend.add_contact(card.first_name, card.last_name, '+' + card.phone_number.lstrip('+')),
            confirm=tr('Add this phone number to your Telegram contacts?')))
        if card.user_id:
            dialog.button(dialog.body, 'Informacion', lambda: self.show_contact_profile(card.user_id) if dialog.valid() else None)

    def gifts_dialog(self, peer=None):
        if not self._advanced_available('stars_gifts', chat=peer is None): return
        if not chat_capabilities(self, peer).allows('gift'): return
        dialog = AdvancedDialog(self, 'stars_gifts', 'Stars, gifts and Premium', '650x760', peer=peer)
        ttk.Label(dialog.body, text=tr('Purchases are optional. The exact recipient and price are shown before any Stars are spent.'), wraplength=580).pack(fill='x', pady=8)
        actions = FlowFrame(dialog.body); actions.pack(fill='x')
        for label, url in [('Buy Stars / Premium · Telegram', 'https://t.me/PremiumBot'), ('Buy or gift Stars · Fragment', 'https://fragment.com/stars'), ('Premium · Fragment', 'https://fragment.com/premium')]:
            ttk.Button(actions, text=tr(label), command=lambda url=url: self.open_link(url, browser_only=True) if dialog.valid() else None).pack(side='left', padx=3, pady=3)
        balance = tk.StringVar(master=dialog.window)
        ttk.Label(dialog.body, textvariable=balance).pack(fill='x')
        dialog.button(dialog.body, 'Check Stars balance', lambda: dialog.read('balance', dialog.backend.stars_balance(),
            lambda result: balance.set(str(result.balance.amount) + ' ★')) if dialog.valid() else None)
        from .gift_picker import GiftGrid, gift_title, gift_price, gift_status
        filters = ttk.Frame(dialog.body); filters.pack(fill='x', pady=(8, 0))
        query = tk.StringVar(master=dialog.window)
        search = ttk.Entry(filters, textvariable=query)
        search.pack(side='left', fill='x', expand=True, padx=(0, 6))
        modes = ('all', 'available', 'auction', 'sold_out')
        mode = Choice(filters, values=[tr(label) for label in ('All gifts', 'Available', 'Auction', 'Sold out')])
        mode.current(0); mode.pack(side='right')
        listing = GiftGrid(dialog.body, self, dialog.account, dialog.backend, lambda _: show(None))
        listing.pack(fill='both', expand=True, pady=8)
        def filtered(*_):
            if dialog.valid(): listing.set_filter(query.get(), modes[max(0, mode.current())])
        trace = query.trace_add('write', filtered)
        mode.bind('<<ComboboxSelected>>', filtered)
        def release_filter(event):
            if event.widget is dialog.window:
                query.trace_remove('write', trace)
        dialog.window.bind('<Destroy>', release_filter, add='+')
        description = tk.StringVar(master=dialog.window)
        ttk.Label(dialog.body, textvariable=description, wraplength=580).pack(fill='x')
        message = _entity_field(dialog.body, self, 'Gift message')
        hide = _check(dialog.body, 'Hide my name on the recipient’s profile')
        upgrade = _check(dialog.body, 'Include an upgrade when available')
        upgrade_widget = next(widget for widget in dialog.body.winfo_children()
                              if isinstance(widget, ttk.Checkbutton) and str(widget.cget('variable')) == str(upgrade))
        upgrade_widget.pack_forget()
        gift_actions = ttk.Frame(dialog.body); gift_actions.pack(fill='x')
        def loaded(catalogue):
            listing.set_gifts(catalogue.gifts)
        def selection():
            return listing.selection()
        def show(_):
            gift = selection()
            for button in (preview_button, purchase, resale_button, auction_button): button.pack_forget()
            upgrade_widget.pack_forget(); upgrade.set(False)
            if gift is None: description.set(''); return
            fields = [gift_title(gift), gift_price(gift), gift_status(gift)]
            for name, label in [('availability_remains', 'Available'), ('availability_total', 'Total'), ('upgrade_stars', 'Upgrade Stars'), ('per_user_remains', 'Remaining for this account')]:
                value = getattr(gift, name, None)
                if value is not None: fields.append(tr(label) + ': ' + str(value))
            description.set(' · '.join(fields))
            caps = chat_capabilities(self, dialog.peer)
            preview_button.pack(fill='x', pady=4)
            if caps.allows_gift(gift): purchase.pack(fill='x', pady=4)
            if getattr(gift, 'availability_resale', 0) and caps.allows_gift(gift, resale=True): resale_button.pack(fill='x', pady=4)
            if getattr(gift, 'auction_slug', None): auction_button.pack(fill='x', pady=4)
            if getattr(gift, 'upgrade_stars', None) is not None and caps.allows_gift(gift):
                upgrade_widget.pack(anchor='w', pady=3, before=gift_actions)
        def preview():
            gift = selection()
            if gift is not None and dialog.valid():
                from .gift_preview import open_gift_preview
                open_gift_preview(self, gift, account=dialog.account, backend=dialog.backend)
        preview_button = dialog.button(gift_actions, 'Preview gift', preview)
        def buy():
            gift = selection()
            if gift is None or not dialog.valid() or not chat_capabilities(self, dialog.peer).allows_gift(gift): return
            self._review_stars(dialog, dialog.backend.prepare_gift(dialog.peer, gift.id,
                message=message.value(), hide_name=hide.get(), include_upgrade=upgrade.get()), capability='gift', gift=gift)
        purchase = dialog.button(gift_actions, 'Review gift purchase', buy)
        def resale():
            gift = selection()
            if gift is not None and dialog.valid(): self.resale_gifts_dialog(gift.id, dialog.peer)
        resale_button = dialog.button(gift_actions, 'Browse collectible gifts for resale', resale)
        def auction():
            gift = selection()
            slug = getattr(gift, 'auction_slug', None)
            if slug and dialog.valid(): self.open_link('https://t.me/auction/' + slug, browser_only=True)
        auction_button = dialog.button(gift_actions, 'Open official gift auction', auction)
        show(None)
        if chat_capabilities(self, dialog.peer).allows('gift_premium'):
            months = Choice(dialog.body, values=['3', '6', '12']); months.current(0); months.pack(fill='x', pady=4)
            dialog.button(dialog.body, 'Gift Premium with Stars', lambda: self._review_stars(dialog,
                dialog.backend.prepare_premium_gift(dialog.peer, int(months.get()), message.value()), capability='gift_premium') if dialog.valid() else None)
        dialog.button(dialog.body, 'Refresh catalogue', lambda: dialog.read('gifts', dialog.backend.gift_catalogue(), loaded))
        dialog.read('gifts', dialog.backend.gift_catalogue(), loaded)

    def resale_gifts_dialog(self, gift_id, peer=None):
        if not self._advanced_available('stars_gifts', chat=peer is None): return
        if not chat_capabilities(self, peer).allows('gift'): return
        dialog = AdvancedDialog(self, 'stars_gifts', 'Collectible gifts for resale', '600x600', peer=peer)
        listing = tk.Listbox(dialog.body, height=16); listing.pack(fill='both', expand=True, pady=8)
        gifts, offset, history = [], [''], []
        next_offset, loading = [None], [False]
        def page(target, back=False):
            if not dialog.valid() or loading[0]: return
            loading[0] = True
            async def fetch():
                try: return await dialog.backend.resale_gifts(gift_id, target)
                finally: loading[0] = False
            def loaded(result):
                if back: history.pop()
                elif target != offset[0]: history.append(offset[0])
                offset[0], next_offset[0] = target, result.next_offset
                gifts[:] = result.gifts
                listing.delete(0, 'end')
                for gift in gifts:
                    price = next((amount.amount for amount in gift.resell_amount or () if isinstance(amount, t.StarsAmount)), None)
                    listing.insert('end', f'{gift.title} #{gift.num}' + (f' · {price} ★' if price is not None else ''))
                previous.configure(state='normal' if history else 'disabled')
                more.configure(state='normal' if next_offset[0] and next_offset[0] != offset[0] else 'disabled')
            dialog.read('resale', fetch(), loaded)
        def selected():
            rows = listing.curselection()
            return gifts[rows[0]] if rows else None
        def preview():
            gift = selected()
            if gift is not None and dialog.valid(): self.open_link('https://t.me/nft/' + gift.slug, browser_only=True)
        def buy():
            gift = selected()
            if gift is not None and dialog.valid() and chat_capabilities(self, dialog.peer).allows_gift(gift, resale=True):
                self._review_stars(dialog, dialog.backend.prepare_resale_gift(gift.slug, dialog.peer), capability='gift', gift=gift, resale=True)
        dialog.button(dialog.body, 'View collectible on Telegram', preview)
        purchase = dialog.button(dialog.body, 'Review gift purchase', buy); purchase.pack_forget()
        def selected_changed(_):
            purchase.pack_forget()
            gift = selected()
            if gift is not None and chat_capabilities(self, dialog.peer).allows_gift(gift, resale=True):
                purchase.pack(fill='x', pady=4, before=previous)
        listing.bind('<<ListboxSelect>>', selected_changed)
        previous = dialog.button(dialog.body, 'Previous page', lambda: page(history[-1], True) if history else None)
        more = dialog.button(dialog.body, 'Next page', lambda: page(next_offset[0]) if next_offset[0] else None)
        page('')

    def _review_stars(self, dialog, operation, *, capability=None, gift=None, resale=False):
        def allowed():
            if not dialog.valid() or self.busy: return False
            if capability is None: return True
            caps = chat_capabilities(self, dialog.peer)
            return caps.allows(capability) and (gift is None or caps.allows_gift(gift, resale=resale))
        if not allowed(): operation.close(); return
        def quoted(quote):
            if not allowed(): dialog.backend.discard_stars_quote(quote.token); return
            prompt = tr('{title}\nRecipient: {recipient}\nTotal: {amount} Telegram Stars\n\nConfirm this purchase?').format(
                title=quote.title, recipient=quote.recipient, amount=quote.amount)
            confirmed = messagebox.askyesno(tr('Confirm Stars payment'), prompt, parent=dialog.window)
            if not confirmed or not allowed():
                dialog.backend.discard_stars_quote(quote.token); return
            def paid(result):
                if isinstance(result, t.payments.PaymentVerificationNeeded):
                    dialog.status.set(tr('Telegram requires an additional verification step.'))
                    if messagebox.askyesno(tr('Verification'), tr('Open Telegram’s payment verification page?'), parent=dialog.window) and dialog.valid(): self.open_link(result.url)
                else: dialog.status.set(tr('Telegram confirmed the payment.'))
            dialog.mutate(lambda: dialog.backend.commit_stars_payment(quote.token, confirmed_amount=quote.amount), paid, capability=capability)
        dialog.read('quote', operation, quoted)

    def paid_reaction_dialog(self, message):
        if not self._advanced_available('stars_gifts'): return
        if not chat_capabilities(self).allows_message('star_react', message): return
        dialog = AdvancedDialog(self, 'stars_gifts', 'Star reaction', '480x360')
        count = self.field(dialog.body, 'Telegram Stars', '1')
        anonymous = _check(dialog.body, 'Hide my name on the leaderboard')
        def review():
            try: amount = int(count.get())
            except ValueError: dialog.status.set(tr('Enter a whole number.')); return
            if dialog.valid(): self._review_stars(dialog, dialog.backend.prepare_paid_reaction(
                dialog.peer, message.id, amount, anonymous=anonymous.get()), capability='star_react')
        dialog.button(dialog.body, 'Review Star reaction', review)

    def received_gift_dialog(self, message, peer=None):
        if not self._advanced_available('stars_gifts', chat=peer is None): return
        dialog = AdvancedDialog(self, 'stars_gifts', 'Gift', '560x560', peer=peer)
        action = message.media
        _read_only(dialog.body, advanced_media_summary(action)[1], 4)
        gift = getattr(action, 'gift', None)
        if gift is not None:
            from .gift_preview import open_gift_preview
            dialog.button(dialog.body, 'Preview gift', lambda: open_gift_preview(self, gift, account=dialog.account, backend=dialog.backend) if dialog.valid() else None)
        slug = getattr(gift, 'slug', None)
        if slug: dialog.button(dialog.body, 'View collectible on Telegram', lambda: self.open_link('https://t.me/nft/' + slug) if dialog.valid() else None)
        caps = chat_capabilities(self, dialog.peer)
        target = getattr(action, 'to_id', None) or getattr(action, 'peer', None)
        identity = getattr(getattr(dialog.backend, 'account_profile', None), 'user_id', None)
        owned = not message.outgoing and (caps.kind in ('self', 'user') or caps.can_manage)
        if isinstance(target, t.PeerUser) and target.user_id != identity: owned = False
        if isinstance(action, (t.MessageActionStarGift, t.MessageActionStarGiftUnique)) and owned and gift_action_available(action, 'visibility'):
            if getattr(action, 'peer', None) is not None and getattr(action, 'saved_id', None) is not None:
                async def saved_reference(): return t.InputSavedStarGiftChat(await dialog.backend.client.get_input_entity(action.peer), action.saved_id)
            else:
                async def saved_reference(): return t.InputSavedStarGiftUser(message.id)
            async def visibility(visible): return await dialog.backend.gift_visibility(await saved_reference(), visible)
            show = not bool(getattr(action, 'saved', False))
            dialog.button(dialog.body, 'Show on my profile' if show else 'Hide from my profile',
                          lambda: dialog.mutate(lambda: visibility(show), close=True))
            convert = getattr(action, 'convert_stars', None)
            if gift_action_available(action, 'convert', config=caps.config, date=getattr(message, 'date', None)):
                async def convert_gift(): return await dialog.backend.convert_received_gift(await saved_reference())
                dialog.button(dialog.body, 'Convert gift to Stars', lambda: dialog.mutate(convert_gift, close=True,
                    confirm=tr('Permanently convert this gift into {amount} Stars?').format(amount=convert)))

    def open_saved_gift(self, record, peer, own=False):
        if not self._advanced_available('stars_gifts', chat=False): return
        dialog = AdvancedDialog(self, 'stars_gifts', 'Profile gift', '580x660', peer=peer)
        gift = record.gift
        title = getattr(gift, 'title', None) or tr('Telegram gift')
        number = getattr(gift, 'num', None)
        if number is not None: title += f' #{number}'
        details = [title, str(record.date), plain(getattr(record, 'message', None))]
        for attribute in getattr(gift, 'attributes', ()):
            name = getattr(attribute, 'name', None)
            rarity = getattr(getattr(attribute, 'rarity', None), 'permille', None)
            if rarity is None: rarity = getattr(attribute, 'rarity_permille', None)
            if name: details.append(name + (f' · {rarity / 10:g}%' if rarity is not None else ''))
        _read_only(dialog.body, '\n'.join(value for value in details if value), 8)
        if gift is not None:
            from .gift_preview import open_gift_preview
            dialog.button(dialog.body, 'Preview gift', lambda: open_gift_preview(self, gift, account=dialog.account, backend=dialog.backend, title=title) if dialog.valid() else None)
        slug = getattr(gift, 'slug', None)
        if slug:
            dialog.button(dialog.body, 'View collectible on Telegram', lambda: self.open_link('https://t.me/nft/' + slug) if dialog.valid() else None)
        if not own or record.msg_id is None and record.saved_id is None or not gift_action_available(record, 'visibility'): return
        async def visibility(visible):
            reference = await dialog.backend.saved_gift_reference(record, peer)
            return await dialog.backend.gift_visibility(reference, visible)
        show = bool(record.unsaved)
        dialog.button(dialog.body, 'Show on my profile' if show else 'Hide from my profile',
                      lambda: dialog.mutate(lambda: visibility(show), close=True))
        if gift_action_available(record, 'convert', config=chat_capabilities(self, peer).config):
            async def convert():
                return await dialog.backend.convert_received_gift(await dialog.backend.saved_gift_reference(record, peer))
            dialog.button(dialog.body, 'Convert gift to Stars', lambda: dialog.mutate(convert, close=True,
                confirm=tr('Permanently convert this gift into {amount} Stars?').format(amount=record.convert_stars)))
        if gift_action_available(record, 'upgrade'):
            keep = _check(dialog.body, 'Keep original sender, recipient and message', True)
            def upgrade():
                if not dialog.valid(): return
                if record.upgrade_stars in (None, 0):
                    dialog.mutate(lambda: dialog.backend.upgrade_prepaid_gift(record, peer, keep_original=keep.get()), close=True,
                                  confirm=tr('Use the prepaid upgrade for this gift?'))
                else:
                    self._review_stars(dialog, dialog.backend.prepare_gift_upgrade(record, peer, keep_original=keep.get()))
            dialog.button(dialog.body, 'Upgrade gift', upgrade)
        if gift_action_available(record, 'transfer'):
            target = self.field(dialog.body, 'Transfer to @username')
            def transfer():
                destination = target.get().strip()
                if not destination or not dialog.valid(): return
                if record.transfer_stars in (None, 0):
                    dialog.mutate(lambda: dialog.backend.transfer_free_gift(record, destination, peer), close=True,
                        confirm=tr('Transfer this collectible gift to {recipient}? This changes its owner.').format(recipient=destination))
                else:
                    self._review_stars(dialog, dialog.backend.prepare_gift_transfer(record, destination, peer))
            dialog.button(dialog.body, 'Review transfer', transfer)

    def article_composer(self):
        if not self._advanced_available('articles'): return
        if not chat_capabilities(self).allows('article'): return
        dialog = AdvancedDialog(self, 'articles', 'Article', '720x760')
        ttk.Label(dialog.body, text=tr('Send a native Telegram article to this chat or channel. Markdown and HTML are parsed by Telegram.'), wraplength=640).pack(fill='x', pady=6)
        format = Choice(dialog.body, values=['Markdown', 'HTML']); format.current(0); format.pack(fill='x')
        editor = tk.Text(dialog.body, height=20, wrap='word', undo=True); editor.pack(fill='both', expand=True, pady=8)
        editor.insert('1.0', '# ' + tr('Title') + '\n\n')
        rtl = _check(dialog.body, 'Right-to-left article')
        noautolink = _check(dialog.body, 'Disable automatic links')
        dialog.button(dialog.body, 'Telegram formatting guide', lambda: self.open_link('https://core.telegram.org/bots/api#rich-message-formatting-options') if dialog.valid() else None)
        dialog.button(dialog.body, 'Send article', lambda: dialog.mutate(lambda: dialog.backend.send_article(
            dialog.peer, editor.get('1.0', 'end-1c'), format=format.get().lower(), rtl=rtl.get(),
            noautolink=noautolink.get(), reply_to=self._advanced_reply(dialog)), close=True, capability='article'))
        ttk.Separator(dialog.body).pack(fill='x', pady=10)
        ttk.Label(dialog.body, text=tr('Telegraph articles are public web pages, separate from native Telegram articles. Create or edit them in the official web editor, then share their link here.'), wraplength=640).pack(fill='x')
        dialog.button(dialog.body, 'Create / edit on Telegraph', lambda: self.open_link('https://telegra.ph/') if dialog.valid() else None)
        url = self.field(dialog.body, 'Telegraph article link')
        def share():
            from urllib.parse import urlsplit
            value = url.get().strip(); parsed = urlsplit(value)
            if parsed.scheme != 'https' or parsed.hostname not in ('telegra.ph', 'www.telegra.ph') or len(parsed.path) < 2:
                dialog.status.set(tr('Enter an https://telegra.ph/ article link.')); return
            dialog.mutate(lambda: dialog.backend.send(dialog.peer, value), close=True, capability='send_text')
        dialog.button(dialog.body, 'Share Telegraph article', share)

    def article_dialog(self, message, peer=None):
        if not self._advanced_available('articles', chat=peer is None): return
        from .article_view import ArticleView
        from .rich_articles import article_media
        dialog = AdvancedDialog(self, 'articles', 'Read article', '720x760', peer=peer)
        def show(state):
            rich, own = state
            view = ArticleView(dialog.body, self, rich, backend=dialog.backend)
            view.pack(fill='both', expand=True, pady=6)
            for title, media in article_media(rich):
                doc = getattr(media, 'document', None)
                kind = 'image' if isinstance(media, t.MessageMediaPhoto) else 'video' if getattr(doc, 'mime_type', '').startswith('video/') else 'file'
                dialog.button(dialog.body, title, lambda media=media, title=title, kind=kind: self.media_dialog(media, title, kind) if dialog.valid() else None)
            if own and chat_capabilities(self, dialog.peer).allows_message('edit_article', message):
                dialog.button(dialog.body, 'Edit article', lambda: self.article_editor(message, rich, dialog.peer))
        dialog.read('article', dialog.backend.article_state(dialog.peer, message.id), show)

    def article_editor(self, message, rich, peer=None):
        if not self._advanced_available('articles', chat=peer is None): return
        if not chat_capabilities(self, peer).allows_message('edit_article', message): return
        from .rich_articles import article_fields, replace_article_field
        dialog = AdvancedDialog(self, 'articles', 'Edit article', '720x760', peer=peer)
        dialog.message_id = message.id
        working, snapshot = deepcopy(rich), bytes(rich)
        ttk.Label(dialog.body, text=tr('Edit text fields without removing formatting, tables, links or media from the original article.'), wraplength=640).pack(fill='x', pady=6)
        listing = tk.Listbox(dialog.body, height=10); listing.pack(fill='both', expand=True)
        editor = tk.Text(dialog.body, height=8, wrap='word', undo=True); editor.pack(fill='both', expand=True, pady=8)
        fields, selected = [], [None]
        def refill():
            fields[:] = article_fields(working.blocks)
            listing.delete(0, 'end')
            for _, label, text in fields: listing.insert('end', label + ' · ' + text[:70].replace('\n', ' '))
        def choose(_):
            indices = listing.curselection()
            if not indices: return
            index = indices[0]
            if selected[0] is not None:
                try: replace_article_field(working, selected[0], editor.get('1.0', 'end-1c'))
                except ValueError as exc: dialog.status.set(str(exc)); return
            selected[0] = fields[index][0]
            current = {path: text for path, _, text in article_fields(working.blocks)}
            editor.delete('1.0', 'end'); editor.insert('1.0', current[selected[0]])
        listing.bind('<<ListboxSelect>>', choose)
        def apply():
            if selected[0] is None: return
            try: replace_article_field(working, selected[0], editor.get('1.0', 'end-1c'))
            except ValueError as exc: dialog.status.set(str(exc)); return
            selected[0] = None; refill()
        dialog.button(dialog.body, 'Apply field change', apply)
        def append():
            working.blocks.append(t.PageBlockParagraph(t.TextPlain(editor.get('1.0', 'end-1c')))); refill()
        dialog.button(dialog.body, 'Add paragraph', append)
        def remove():
            if selected[0] is None: return
            index = selected[0][0]
            if type(index) is int and messagebox.askyesno(tr('Remove block'), tr('Remove the entire selected block from this article?'), parent=dialog.window) and dialog.valid():
                working.blocks.pop(index); selected[0] = None; refill()
        dialog.button(dialog.body, 'Remove selected block', remove)
        def save():
            apply()
            dialog.mutate(lambda: dialog.backend.edit_article(dialog.peer, message.id, working, snapshot), close=True,
                          capability='edit_article', message=message)
        dialog.button(dialog.body, 'Save article', save)
        refill()
