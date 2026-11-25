"""Account-pinned call controls. Only this module's UI thread touches Tk.

The native engine lives on the existing Telegram worker. Video uses a single
latest-frame slot: a slow window never queues old frames or network callbacks.
"""
import asyncio
import sys
import tkinter as tk
from tkinter import ttk

from .advanced_features import feature_enabled
from .app_dialogs import Choice
from .i18n import tr
from .scrolling import FlowFrame


def root_owner(app):
    return getattr(app, '_linked_owner', None) or app


def call_allowed(app, peer=None, account=None, *, video=False):
    """Use cached permissions; opening a menu never starts a network request."""
    if getattr(app, 'demo', False) or not feature_enabled(app, 'calls'):
        return False
    from .calls import engine_available
    if not engine_available():
        return False
    peer = app.active if peer is None else peer
    account = app.ui_account if account is None else account
    service = root_owner(app).service.services.get(account)
    backend = getattr(service, 'backend', None)
    if backend is None or peer is None:
        return False
    entity = getattr(backend, '_capability_entities', {}).get(peer)
    if entity is None and account == app.ui_account:
        entity = next((getattr(chat, 'entity', None) for chat in app.chats if chat.id == peer), None)
    from telethon import types
    if not isinstance(entity, types.User) or entity.bot or entity.deleted or entity.is_self:
        return False
    if peer == getattr(backend.account_profile, 'user_id', None):
        return False
    full = getattr(backend, '_capability_full', {}).get(peer)
    if full is not None:
        if getattr(full, 'blocked', False) or getattr(full, 'phone_calls_private', False):
            return False
        if getattr(full, 'phone_calls_available', None) is False:
            return False
        if video and getattr(full, 'video_calls_available', None) is False:
            return False
    return True


async def configure_calls(accounts, enabled):
    """Called on the Telegram loop; never create or open another session."""
    from .calls import CallManager, engine_available
    for service in tuple(accounts.services.values()):
        backend = service.backend
        if backend is None or getattr(backend, 'demo', False):
            continue
        manager = getattr(backend, 'call_manager', None)
        if enabled and engine_available():
            if manager is None:
                manager = CallManager(service.client, lambda snapshot, b=backend:
                    b.on_change('call', snapshot) if b.on_change else None)
                backend.call_manager = manager
            await manager.enable()
        elif manager is not None:
            await manager.close()
            backend.call_manager = None
        if not enabled:
            group = getattr(backend, 'group_call_manager', None)
            if group is not None:
                await group.close()
                backend.group_call_manager = None


class DesktopCalls:
    def channel_call_settings(self):
        from .desktop_channel_calls import open_channel_calls
        return open_channel_calls(self)

    def join_conference_message(self, message, peer=None):
        from telethon import types
        action = message.media
        if not isinstance(action, types.MessageActionConferenceCall):
            return
        from .desktop_conference import open_invitation
        return open_invitation(self,self.active if peer is None else peer,message.id)

    def start_group_call(self, *, conference=False, video=False, peer=None, create=False, view_only=False):
        peer = self.active if peer is None else peer
        if self.demo or peer is None or not feature_enabled(self, 'calls'):
            return
        owner, account = root_owner(self), self.ui_account
        backend = self.service.backend
        if create:
            from .app_dialogs import messagebox
            if not messagebox.askyesno(tr('Group call'), tr('Start a new group call?'), parent=self.root):
                return
        async def begin():
            service = owner.service.services.get(account)
            if service is None or service.backend is not backend:
                return
            from .calls_group import GroupCallManager
            manager = getattr(backend, 'group_call_manager', None)
            if manager is None:
                manager = GroupCallManager(service.client, lambda snapshot:
                    backend.on_change('group_call', snapshot) if backend.on_change else None)
                standard = getattr(backend, 'call_manager', None)
                manager._selected = {key: value for key, value in getattr(standard, '_selected', {}).items()
                                     if key in ('microphone', 'speaker', 'camera')}
                backend.group_call_manager = manager
            from .advanced_features import feature_enabled
            manager.video_grid = feature_enabled(self, 'group_video_grid')
            await manager.start(peer, video=video, conference=conference, create=create, view_only=view_only)
        owner.worker.submit(begin(), lambda _: None, owner.show_error)

    def account_registry_changed(self, _=None):
        from .interface_windows import sync_window_accounts
        sync_window_accounts(self)
        self.apply_optional_services()

    def apply_optional_services(self):
        owner = root_owner(self)
        if owner is not self:
            return owner.apply_optional_services()
        if getattr(owner, 'closed', False) or getattr(owner, 'closing', False) or owner.demo:
            return
        owner.configure_push_notifications()
        desired = feature_enabled(owner, 'calls')
        owner._calls_desired = desired
        running = getattr(owner, '_calls_configuration', None)
        if running is not None and not running.done():
            return

        def completed(_):
            if owner.closed or owner.closing:
                return
            if not desired:
                windows = (*getattr(owner, '_call_windows', {}).values(), *getattr(owner, '_group_call_windows', {}).values())
                for window in windows:
                    if window.alive():
                        window.update(window.manager.snapshot)
            # Preference changes while configuring are applied, not dropped.
            if owner._calls_desired != desired:
                owner.apply_optional_services()
            for view in (owner, *getattr(owner, '_app_windows', ())):
                if not view.closed and getattr(view, 'stage', '') == 'ready':
                    view.update_chat_capabilities()

        owner._calls_configuration = owner.worker.submit(
            configure_calls(owner.service, desired), completed,
            lambda error: owner.status.set(str(error)) if not owner.closed else None)

    def start_call(self, peer=None, *, account=None, video=False):
        account = self.ui_account if account is None else account
        peer = self.active if peer is None else peer
        if not call_allowed(self, peer, account, video=video):
            return
        owner = root_owner(self)
        from .app_lock import is_locked
        if is_locked(owner) or owner.closing:
            return
        service = owner.service.services.get(account)
        backend = getattr(service, 'backend', None)
        if backend is None:
            return
        # Capture the service and destination now, before any await or switch.
        async def begin():
            await configure_calls(owner.service, True)
            if service.backend is not backend or not feature_enabled(owner, 'calls'):
                return
            manager = backend.call_manager
            await manager.start(peer, video=video)
        owner.worker.submit(begin(), lambda _: None, owner.show_error)

    def call_contact(self):
        self.start_call()

    def call_event(self, account, snapshot, *, group=False):
        owner = root_owner(self)
        if owner is not self or owner.closed or owner.closing:
            return
        service = owner.service.services.get(account)
        manager = getattr(getattr(service, 'backend', None), 'group_call_manager' if group else 'call_manager', None)
        if manager is None:
            return
        if snapshot.get('token') != manager.snapshot.get('token'):
            return
        attribute = '_group_call_windows' if group else '_call_windows'
        windows = getattr(owner, attribute, None)
        if windows is None:
            windows = {}
            setattr(owner, attribute, windows)
        window = windows.get(account)
        if window is None or not window.alive():
            if snapshot.get('state') in ('idle', 'ended', 'closed', 'failed'):
                if snapshot.get('error'):
                    owner.status.set(str(snapshot['error']))
                return
            window = windows[account] = CallWindow(owner, account, manager)
        window.update(snapshot)

    def call_settings(self, account=None):
        from .calls import engine_available
        window, frame = self.dialog('Calls and video', '540x440')
        available = engine_available()
        ttk.Label(frame, text=tr('Call engine ready' if available else 'Call engine is not installed.'),
                  wraplength=460).pack(fill='x', pady=10)
        ttk.Label(frame, text=tr('Enable calls in Complex features. Microphone and camera start only when you call or answer.'),
                  wraplength=460).pack(fill='x', pady=10)
        if available and feature_enabled(self, 'calls') and not self.demo:
            owner = root_owner(self)
            account = self.ui_account if account is None else account
            service = owner.service.services.get(account)
            backend = getattr(service, 'backend', None)
            if backend is not None:
                async def devices():
                    await configure_calls(owner.service, True)
                    return await backend.call_manager.devices()
                def loaded(values):
                    if window.winfo_exists() and getattr(owner.service.services.get(account), 'backend', None) is backend:
                        def save(choices):
                            if getattr(owner.service.services.get(account), 'backend', None) is backend:
                                owner.worker.submit(select_call_devices(backend, choices), lambda _: None, self.show_error)
                        device_controls(frame, values, save, getattr(backend.call_manager, '_selected', {}))
                owner.worker.submit(devices(), loaded, self.show_error)


async def select_call_devices(backend, choices):
    """Share account-specific device choices with its normal and group manager."""
    for name in ('call_manager', 'group_call_manager'):
        manager = getattr(backend, name, None)
        if manager is not None and not getattr(manager, '_closed', False):
            await manager.select_devices(**choices, token=manager.snapshot.get('token'))


def device_controls(frame, devices, save, selected=None):
    fields = {}
    for kind, label in (('microphone', 'Microphone'), ('speaker', 'Speaker'), ('camera', 'Camera')):
        entries = devices.get(kind, [])
        ttk.Label(frame, text=tr(label)).pack(anchor='w', pady=(8, 2))
        choice = Choice(frame, values=[tr('Default'), *[item['name'] for item in entries]])
        initial = next((index for index, item in enumerate(entries, 1)
                        if item['id'] == (selected or {}).get(kind)), 0)
        choice.current(initial)
        choice.pack(fill='x')
        fields[kind] = (choice, entries)
    def apply():
        save({key: entries[choice.current()-1]['id'] if choice.current() > 0 else ''
              for key, (choice, entries) in fields.items()})
    ttk.Button(frame, text=tr('Apply'), command=apply).pack(fill='x', pady=12)


class CallWindow:
    def __init__(self, owner, account, manager):
        self.owner, self.account, self.manager = owner, account, manager
        self.snapshot, self.pending, self.photo = {}, False, None
        self.pip = None
        self.window = tk.Toplevel(owner.root)
        self.window.title(tr('Calls and video'))
        self.window.geometry('600x440')
        self.window.minsize(360, 280)
        self.window._lock_app_owner = owner
        # 1.4.1: scrolls instead of clipping the controls on small windows.
        from .scrolling import Viewport, fit_to_content
        viewport = Viewport(self.window, minimum=(340, 260))
        viewport.pack(fill='both', expand=True)
        body = viewport.content
        body.configure(padding=14)
        fit_to_content(self.window, viewport)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(3, weight=1)
        self.heading = ttk.Label(body, text=owner.service.labels.get(account, tr('Account')))
        self.heading.grid(row=0, column=0, sticky='ew')
        self.status = ttk.Label(body, wraplength=540)
        self.status.grid(row=1, column=0, sticky='ew', pady=8)
        self.fingerprint = ttk.Label(body, font=(getattr(owner, 'font_family', 'Arial'), 20))
        self.fingerprint.grid(row=2, column=0, sticky='ew', pady=6)
        # Images must never contribute an intrinsic size to the window layout.
        # Only this viewport shrinks; the toolbar keeps its requested height.
        self.viewport = ttk.Frame(body, width=1, height=1)
        self.viewport.grid(row=3, column=0, sticky='nsew')
        self.viewport.grid_propagate(False)
        self.picture = ttk.Label(self.viewport, anchor='center')
        self.picture.place(x=0, y=0, relwidth=1, relheight=1)
        self.local_picture = ttk.Label(self.viewport, anchor='center', relief='solid', borderwidth=1)
        self.local_photo = None
        row = FlowFrame(body)
        self.controls = row
        row.grid(row=4, column=0, sticky='ew', pady=8)
        row.bind('<Configure>', self.fit_controls, add='+')
        self.buttons = {}
        for key, label, action in (
            ('accept', 'Answer', lambda: self.perform('accept', video=False)),
            ('accept_video', 'Answer with video', lambda: self.perform('accept', video=True)),
            ('mute', 'Mute microphone', lambda: self.perform('mute', not self.snapshot.get('muted', False))),
            ('camera', 'Camera', lambda: self.perform('set_camera', not self.snapshot.get('video', False))),
            ('screen', 'Share screen', self.share_screen),
            ('pip', 'Imagen dentro de imagen', self.show_call_pip),
            ('devices', 'Calls and video', self.device_settings),
            ('hangup', 'Hang up', self.hangup)):
            button = ttk.Button(row, text=tr(label), command=action)
            self.buttons[key] = button
        if getattr(manager, 'group_call', False):
            self.buttons['group_settings'] = ttk.Button(row, text=tr('Settings'), command=self.group_settings)
            self.buttons['members'] = ttk.Button(row, text=tr('Members'), command=self.members)
            self.buttons['invite'] = ttk.Button(row, text=tr('Add members'), command=self.invite)
            self.buttons['end_all'] = ttk.Button(row, text=tr('End call for everyone'), command=self.end_for_everyone)
        if sys.platform == 'darwin':
            import importlib.util
            import platform
            if int(platform.mac_ver()[0].split('.')[0] or 0) >= 14 and importlib.util.find_spec('AVFoundation'):
                self.buttons['effects'] = ttk.Button(row, text=tr('Camera effects'), command=lambda: self.perform('camera_effects'))
        self.window.protocol('WM_DELETE_WINDOW', self.dismiss)
        self.window.bind('<Unmap>', self.background_status, add='+')
        self.window.bind('<Map>', self.foreground_status, add='+')
        self.window.bind('<Destroy>', self.destroyed, add='+')
        from .app_lock import hide_locked_dialog
        hide_locked_dialog(owner, self.window)
        self.timer = self.window.after(50, self.poll_frame)

    def alive(self):
        return bool(self.window.winfo_exists())

    def fit_controls(self, event=None):
        # Group actions and translated labels can require additional rows.
        # Keep their full height reserved even at the narrowest window size.
        required = (self.heading.winfo_reqheight() + self.status.winfo_reqheight()
                    + self.fingerprint.winfo_reqheight()
                    + self.controls.winfo_reqheight() + 80)
        self.window.minsize(360, max(280, required))

    def update(self, snapshot):
        if snapshot.get('token') != self.snapshot.get('token'):
            # This account can reuse its window for a new call before an old
            # worker callback reaches Tk. Actions belong to a call, not a window.
            self.pending = False
            self._dismiss_when_ended = False
            self.close_call_pip()
            if hasattr(self, 'local_picture'):
                self.local_picture.place_forget()
                self.local_picture.configure(image='')
                self.local_photo = None
        self.snapshot = dict(snapshot)
        state = snapshot.get('state', '')
        service = self.owner.service.services.get(self.account)
        backend = getattr(service, 'backend', None)
        peer = snapshot.get('peer')
        name = getattr(backend, 'names', {}).get(peer, str(peer or ''))
        self.heading.configure(text=self.owner.service.labels.get(self.account, tr('Account')) + ' · ' + name)
        from .call_outcomes import LABELS
        outcome=LABELS.get(snapshot.get('outcome')) if state in ('ended','closed') else None
        self.status.configure(text=str(snapshot.get('error') or (tr(outcome) if outcome else None) or tr({
            'incoming':'Incoming call', 'outgoing':'Calling…', 'requesting':'Calling…',
            'ringing':'Ringing…', 'connecting':'Connecting…', 'active':'Connected',
            'connected':'Connected', 'reconnecting':'Reconnecting…', 'ended':'Call ended',
            'failed':'Call failed', 'idle':'Call ended', 'closed':'Call ended',
        }.get(state, state))))
        emojis = snapshot.get('emojis') or ''
        self.fingerprint.configure(text=emojis if isinstance(emojis, str) else ' '.join(emojis))
        incoming = snapshot.get('incoming') and state in ('incoming', 'ringing')
        ended = state in ('ended', 'closed', 'failed', 'idle')
        if (ended or not snapshot.get('video')) and hasattr(self, 'local_picture'):
            self.local_picture.place_forget()
            self.local_picture.configure(image='')
            self.local_photo = None
        for key, button in self.buttons.items():
            visible = key in ('accept', 'accept_video') if incoming else key in ('mute', 'camera', 'screen', 'devices', 'hangup', 'members', 'invite') and not ended
            if snapshot.get('view_only') and key in ('mute','camera','screen','effects'):
                visible = False
            if key == 'effects':
                visible = not incoming and not ended and bool(snapshot.get('video')) and not snapshot.get('view_only')
            if key == 'group_settings':
                visible = not incoming and not ended and bool(self.manager.can_manage) and not getattr(self.manager, 'conference', False)
            if key == 'end_all':
                visible = not incoming and not ended and bool(self.manager.can_manage)
            if key == 'pip':
                visible = state == 'active' and bool(snapshot.get('video') or snapshot.get('remote_video') or snapshot.get('screen'))
            if key == 'hangup' and incoming:
                visible = True
            button.flow_hidden = not visible
            button.configure(state='disabled' if self.pending or key in ('mute', 'camera', 'screen', 'devices', 'members', 'invite', 'effects', 'end_all', 'group_settings') and state != 'active' else 'normal')
        self.buttons['mute'].configure(text=tr('Unmute microphone' if snapshot.get('muted') else 'Mute microphone'))
        self.buttons['camera'].configure(text=tr('Stop camera' if snapshot.get('video') else 'Start camera'))
        self.buttons['screen'].configure(text=tr('Stop sharing screen' if snapshot.get('screen') else 'Share screen'))
        self.buttons['hangup'].configure(text=tr('Decline' if incoming else 'Hang up'))
        self.controls.arrange()
        if ended or snapshot.get('remote_video') is False:
            self.picture.configure(image='')
            self.photo = None
        if ended:
            self.close_call_pip()
            background_notice = getattr(self, '_background_notice', None)
            if background_notice and self.owner.status.get() == background_notice:
                self.owner.status.set(tr('Call ended'))
            self._background_notice = None
            if getattr(self, '_dismiss_when_ended', False):
                self.window.destroy()
        elif getattr(self, 'timer', None) is None:
            self.timer = self.window.after(50 if snapshot.get('remote_video') else 250, self.poll_frame)

    def perform(self, method, *args, **kwargs):
        if self.pending or not self.alive() or self.owner.closing:
            return
        from .app_lock import is_locked
        if is_locked(self.owner):
            return
        if method in ('accept', 'decline', 'hangup'):
            kwargs['peer'] = self.snapshot.get('peer')
        if method in ('accept', 'decline', 'hangup', 'mute', 'set_camera', 'set_screen', 'invite', 'participant_action', 'local_participant_volume', 'edit_title', 'set_join_muted', 'set_recording', 'view_participant', 'camera_effects', 'end_for_everyone'):
            kwargs['token'] = self.snapshot.get('token')
        token = self.snapshot.get('token')
        self.pending = True
        self.update(self.snapshot)
        def done(_):
            if token != self.snapshot.get('token'):
                return
            self.pending = False
            if self.alive():
                self.update(self.snapshot)
        def failed(error):
            if token != self.snapshot.get('token'):
                return
            done(None)
            if self.alive():
                self.status.configure(text=str(error))
        self.owner.worker.submit(getattr(self.manager, method)(*args, **kwargs), done, failed)

    def group_settings(self):
        from .app_lock import is_locked
        if self.pending or not self.alive() or is_locked(self.owner):
            return
        token = self.snapshot.get('token')
        self.pending = True
        self.update(self.snapshot)
        def loaded(info):
            if token != self.snapshot.get('token') or not self.alive():
                return
            self.pending = False
            self.update(self.snapshot)
            if is_locked(self.owner) or not info.get('active'):
                return
            from .app_dialogs import popup_menu
            entries = []
            if info.get('can_edit_title'):
                entries.append((tr('Title'), lambda: self.edit_group_title(info.get('title', ''), token)))
            if info.get('can_change_join_muted'):
                entries.append((tr('Unmute new participants' if info.get('join_muted') else 'Mute new participants'),
                    lambda: self.group_perform(token, 'set_join_muted', not info.get('join_muted'))))
            if info.get('can_record'):
                if info.get('recording'):
                    entries.append((tr('Stop recording'), lambda: self.group_perform(token, 'set_recording', False)))
                else:
                    for label, video, portrait in (('Record audio', False, False),
                            ('Record landscape video', True, False), ('Record portrait video', True, True)):
                        entries.append((tr(label), lambda v=video, p=portrait: self.start_group_recording(v, p, token)))
            if entries:
                popup_menu(self.window, entries, anchor=self.buttons['group_settings'])
        def failed(error):
            if token == self.snapshot.get('token') and self.alive():
                self.pending = False
                self.update(self.snapshot)
                self.status.configure(text=str(error))
        self.owner.worker.submit(self.manager.control_info(token=token), loaded, failed)

    def group_perform(self, token, method, *args, **kwargs):
        if token == self.snapshot.get('token'):
            self.perform(method, *args, **kwargs)

    def edit_group_title(self, previous, token):
        from .app_dialogs import simpledialog
        from .app_lock import is_locked
        if token != self.snapshot.get('token') or not self.alive() or is_locked(self.owner):
            return
        title = simpledialog.askstring(tr('Title'), tr('Title'), initialvalue=previous, parent=self.window)
        if title is not None and token == self.snapshot.get('token') and not is_locked(self.owner):
            self.perform('edit_title', title)

    def start_group_recording(self, video, portrait, token):
        from .app_dialogs import messagebox
        from .app_lock import is_locked
        if token != self.snapshot.get('token') or not self.alive() or is_locked(self.owner):
            return
        if messagebox.askyesno(tr('Record call'), tr('Telegram will record this call and send the recording to Saved Messages. Start recording?'), parent=self.window):
            if token == self.snapshot.get('token') and not is_locked(self.owner):
                self.perform('set_recording', True, video=video, portrait=portrait)

    def invite(self):
        from .app_lock import is_locked
        if self.pending or not self.alive() or is_locked(self.owner):
            return
        from .app_dialogs import simpledialog
        token = self.snapshot.get('token')
        value = simpledialog.askstring(tr('Add members'), '@username', parent=self.window)
        if value and token == self.snapshot.get('token'):
            self.perform('invite', value.strip())

    def device_settings(self):
        from .app_lock import is_locked
        if self.pending or not self.alive() or is_locked(self.owner):
            return
        self.owner.call_settings(account=self.account)

    def end_for_everyone(self):
        from .app_dialogs import messagebox
        from .app_lock import is_locked
        if self.pending or not self.alive() or is_locked(self.owner):
            return
        token = self.snapshot.get('token')
        if messagebox.askyesno(tr('End call for everyone'), tr('End call for everyone') + '?', parent=self.window):
            if token == self.snapshot.get('token'):
                self.perform('end_for_everyone')

    def members(self, offset=0):
        from .app_lock import is_locked
        if self.pending or not self.alive() or is_locked(self.owner):
            return
        token = self.snapshot.get('token')
        self.pending = True
        self.update(self.snapshot)
        def loaded(page):
            from .app_lock import is_locked
            if not self.alive() or token != self.snapshot.get('token'):
                return
            self.pending = False
            self.update(self.snapshot)
            if is_locked(self.owner):
                return
            from .app_dialogs import popup_menu
            backend = self.owner.service.services[self.account].backend
            rows = page['items']
            def actions(row):
                if token != self.snapshot.get('token'):
                    return
                entries = []
                if row.get('invitation'):
                    popup_menu(self.window,[(tr('Send invitation again'),lambda:self.perform('invite',row['id']))],anchor=self.buttons['members'])
                    return
                if row['video'] and not row.get('is_self'):
                    entries.append((tr('Video call'), lambda: self.perform('view_participant', row['id'])))
                if row['screen'] and not row.get('is_self'):
                    entries.append((tr('View screen'), lambda: self.perform('view_participant', row['id'], screen=True)))
                if row.get('is_self'):
                    if not row.get('muted_by_admin') and not self.snapshot.get('view_only'):
                        entries.append((tr('Unmute microphone' if row['muted'] else 'Mute microphone'),
                            lambda: self.perform('mute', not row['muted'])))
                    if row.get('can_raise_hand'):
                        entries.append((tr('Lower hand' if row.get('raised_hand') else 'Raise hand'),
                            lambda: self.perform('participant_action', row['id'], raise_hand=not row.get('raised_hand', False))))
                else:
                    if row.get('can_set_volume'):
                        label = 'Volume (%)'
                        entries.append((tr(label), lambda: self.participant_volume(row)))
                    if self.manager.can_manage:
                        entries.append((tr('Allow to speak' if row.get('muted_by_admin') else 'Mute microphone'),
                            lambda: self.perform('participant_action', row['id'], muted=not row.get('muted_by_admin', False))))
                        if row.get('can_raise_hand') and row.get('raised_hand'):
                            entries.append((tr('Lower hand'), lambda: self.perform('participant_action', row['id'], raise_hand=False)))
                if entries:
                    popup_menu(self.window, entries, anchor=self.buttons['members'])
            entries = [((row.get('name') or getattr(backend, 'names', {}).get(row['id'], str(row['id']))) + (' · '+tr('Invited') if row.get('invitation') else '') + (' 🔇' if row['muted'] else ''),
                        lambda row=row: actions(row)) for row in rows]
            if offset:
                entries.append((tr('Previous page'), lambda: self.members(max(0, offset - 100)) if token == self.snapshot.get('token') else None))
            if page['next'] is not None:
                entries.append((tr('Next page'), lambda: self.members(page['next']) if token == self.snapshot.get('token') else None))
            popup_menu(self.window, entries, anchor=self.buttons['members'])
        def failed(error):
            if self.alive() and token == self.snapshot.get('token'):
                self.pending = False
                self.update(self.snapshot)
                self.status.configure(text=str(error))
        self.owner.worker.submit(self.manager.participants(token=token, offset=offset), loaded, failed)

    def participant_volume(self, row):
        from .app_lock import is_locked
        if self.pending or not self.alive() or is_locked(self.owner):
            return
        from .app_dialogs import simpledialog
        token = self.snapshot.get('token')
        label = tr('Volume (%)')
        value = simpledialog.askinteger(label, label, initialvalue=max(0, min(200, row.get('volume', 100))),
            minvalue=0, maxvalue=200, parent=self.window)
        if value is not None and token == self.snapshot.get('token') and not is_locked(self.owner):
            self.perform('local_participant_volume', row['id'], volume=value * 100)

    def share_screen(self):
        if self.pending or self.snapshot.get('state') != 'active':
            return
        if self.snapshot.get('screen'):
            return self.perform('set_screen', '')
        from .app_lock import is_locked
        if is_locked(self.owner):
            return
        token = self.snapshot.get('token')
        self.pending = True
        self.update(self.snapshot)
        def loaded(devices):
            if not self.alive() or token != self.snapshot.get('token'):
                return
            self.pending = False
            self.update(self.snapshot)
            if is_locked(self.owner):
                return
            sources = devices.get('screen', ())
            from .app_dialogs import popup_menu
            if not sources:
                self.status.configure(text=tr('Screen capture unavailable'))
                return
            def select(source):
                if token == self.snapshot.get('token'):
                    self.perform('set_screen', source)
            popup_menu(self.window, [(item['name'], lambda ident=item['id']: select(ident)) for item in sources], anchor=self.buttons['screen'])
        def failed(error):
            if self.alive() and token == self.snapshot.get('token'):
                self.pending = False
                self.update(self.snapshot)
                self.status.configure(text=str(error))
        self.owner.worker.submit(self.manager.devices(), loaded, failed)

    def hangup(self):
        self.perform('decline' if self.snapshot.get('state') in ('incoming', 'ringing') and self.snapshot.get('incoming') else 'hangup')

    def dismiss(self):
        if self.snapshot.get('state') not in ('idle', 'ended', 'closed', 'failed'):
            self._dismiss_when_ended = True
            self.window.iconify()
            self.background_status()
        else:
            self.window.destroy()

    def background_status(self, event=None):
        if event is not None and (event.widget is not self.window or self.window.state() != 'iconic'):
            return
        if self.snapshot.get('state') in ('idle', 'ended', 'closed', 'failed'):
            return
        self._background_notice = tr('La llamada continúa en segundo plano.')
        self.owner.status.set(self._background_notice)

    def foreground_status(self, event):
        notice = getattr(self, '_background_notice', None)
        if event.widget is self.window and notice:
            if self.owner.status.get() == notice:
                self.owner.status.set(self.status.cget('text'))
            self._background_notice = None

    def show_call_pip(self):
        from .app_lock import is_locked
        from .desktop_call_pip import open_call_pip
        if self.snapshot.get('state') != 'active' or is_locked(self.owner):
            return
        self.close_call_pip()
        try:
            self.pip = open_call_pip(self)
            self._pip_last_remote = self._pip_last_shown = 0
        except (RuntimeError, AttributeError, tk.TclError) as error:
            self.close_call_pip()
            self.status.configure(text=str(error))

    def close_call_pip(self):
        pip, self.pip = getattr(self, 'pip', None), None
        if pip:
            pip.close()

    def poll_call_pip(self):
        from time import monotonic
        from .app_lock import is_locked
        pip = self.pip
        if is_locked(self.owner):
            self.close_call_pip()
            return False
        if not pip.displaying():
            failed = getattr(pip, 'failed_to_open', False) is True
            self.close_call_pip()
            if not failed:
                return False
            from .desktop_call_pip import CompactCallWindow
            self.pip = pip = CompactCallWindow(self)
        if getattr(self, '_pip_decoding', False):
            return True
        token = self.snapshot.get('token')
        remote = self.manager.take_frame()
        local = self.manager.take_local_frame()
        now = monotonic()
        if remote:
            self._pip_last_remote = now
        if remote is None and now - self._pip_last_remote > 1.2 and self.snapshot.get('video'):
            remote = local
        if not remote or remote.get('token') != token:
            if self._pip_last_shown and now - self._pip_last_shown > 2:
                pip.clear()
                self._pip_last_shown = 0
            return True
        from .calls_native import frame_image
        self._pip_decoding = True
        def done(image):
            self._pip_decoding = False
            if self.pip is pip and self.snapshot.get('token') == token and not is_locked(self.owner) and image is not None:
                pip.show(image)
                self._pip_last_shown = monotonic()
        def failed(_):
            self._pip_decoding = False
        self.owner.worker.submit(asyncio.to_thread(frame_image, remote, (480, 270)), done, failed)
        return True

    def poll_frame(self):
        self.timer = None
        if not self.alive() or self.owner.closed:
            return
        from .app_lock import is_locked
        if getattr(self, 'pip', None) and self.poll_call_pip():
            self.timer = self.window.after(85, self.poll_frame)
            return
        self.poll_local_frame()
        if getattr(self.manager, 'group_call', False) and getattr(self.manager, 'video_grid', False) is True and hasattr(self.manager, 'take_frames'):
            self.poll_tiles()
            if self.snapshot.get('state') not in ('ended', 'failed', 'closed', 'idle'):
                visible_video = (self.snapshot.get('remote_video') or self.snapshot.get('video')) and self.window.winfo_viewable() and not is_locked(self.owner)
                self.timer = self.window.after(50 if visible_video else 250, self.poll_frame)
            return
        frame = None if getattr(self, '_decoding', False) else self.manager.take_frame()
        if frame is not None and self.window.winfo_viewable() and not is_locked(self.owner):
            self._decoding = True
            token = self.snapshot.get('token')
            size = (max(1, self.picture.winfo_width()), max(1, self.picture.winfo_height()))
            def decode():
                from .calls_native import frame_image
                picture = frame_image(frame)
                if picture is not None:
                    picture.thumbnail(size)
                return picture
            def decoded(picture):
                self._decoding = False
                if (picture is None or not self.alive() or token != self.snapshot.get('token')
                        or is_locked(self.owner) or self.snapshot.get('remote_video') is False
                        or self.snapshot.get('state') in ('ended', 'failed', 'closed', 'idle')):
                    return
                from PIL import ImageTk
                if self.photo is not None and self.photo.width() == picture.width and self.photo.height() == picture.height:
                    self.photo.paste(picture)
                else:
                    self.photo = ImageTk.PhotoImage(picture, master=self.window)
                    self.picture.configure(image=self.photo)
            def failed(_):
                self._decoding = False
            self.owner.worker.submit(asyncio.to_thread(decode), decoded, failed)
        if self.snapshot.get('state') not in ('ended', 'failed', 'closed', 'idle'):
            visible_video = (self.snapshot.get('remote_video') or self.snapshot.get('video')) and self.window.winfo_viewable() and not is_locked(self.owner)
            self.timer = self.window.after(50 if visible_video else 250, self.poll_frame)

    # ---- 1.4: grid of participant cameras in group calls --------------------
    @staticmethod
    def tile_layout(count):
        """(relx, rely, relwidth, relheight) per tile in a near-square grid."""
        import math
        if count <= 0:
            return []
        columns = math.ceil(math.sqrt(count))
        rows = math.ceil(count / columns)
        return [((index % columns) / columns, (index // columns) / rows, 1 / columns, 1 / rows)
                for index in range(count)]

    def poll_tiles(self):
        from .app_lock import is_locked
        tiles = getattr(self, 'tiles', None)
        if tiles is None:
            tiles = self.tiles = {}
        if getattr(self, '_decoding', False):
            return
        ended = self.snapshot.get('state') in ('ended', 'failed', 'closed', 'idle')
        from .calls_group_native import MAX_INCOMING_VIDEOS
        active = [] if ended or self.snapshot.get('remote_video') is False else self.manager.active_tiles()[:MAX_INCOMING_VIDEOS]
        for ssrc in [ssrc for ssrc in tiles if ssrc not in active]:
            tiles.pop(ssrc)['label'].destroy()
        frames = {} if not active else self.manager.take_frames()
        if self.gpu_grid(active, frames, tiles, ended):
            return  # gpu_video: the GPU window shows the cameras.
        layout = self.tile_layout(len(active))
        if active:
            self.picture.place_forget()
        else:
            self.picture.place(x=0, y=0, relwidth=1, relheight=1)
        width, height = max(1, self.viewport.winfo_width()), max(1, self.viewport.winfo_height())
        wanted = {}
        for ssrc, (relx, rely, relw, relh) in zip(active, layout):
            tile = tiles.get(ssrc)
            if tile is None:
                tile = tiles[ssrc] = {'label': ttk.Label(self.viewport, anchor='center'), 'photo': None}
            tile['label'].place(relx=relx, rely=rely, relwidth=relw, relheight=relh)
            if ssrc in frames:
                wanted[ssrc] = (frames[ssrc], (max(1, int(width * relw) - 4), max(1, int(height * relh) - 4)))
        if hasattr(self, 'local_picture'):
            self.local_picture.lift()
        if not wanted or not self.window.winfo_viewable() or is_locked(self.owner):
            return
        self._decoding = True
        token = self.snapshot.get('token')
        def decode():
            from .calls_native import frame_image
            pictures = {}
            for ssrc, (frame, size) in wanted.items():
                picture = frame_image(frame, size)
                if picture is not None:
                    pictures[ssrc] = picture
            return pictures
        def decoded(pictures):
            self._decoding = False
            if not self.alive() or token != self.snapshot.get('token') or is_locked(self.owner):
                return
            from PIL import ImageTk
            for ssrc, picture in pictures.items():
                tile = tiles.get(ssrc)
                if tile is None:
                    continue
                photo = tile['photo']
                if photo is not None and photo.width() == picture.width and photo.height() == picture.height:
                    photo.paste(picture)
                else:
                    tile['photo'] = ImageTk.PhotoImage(picture, master=self.window)
                    tile['label'].configure(image=tile['photo'])
        def failed(_):
            self._decoding = False
        self.owner.worker.submit(asyncio.to_thread(decode), decoded, failed)

    def gpu_grid(self, active, frames, tiles, ended):
        """gpu_video: draw the cameras in the GPU window when possible."""
        from .advanced_features import feature_enabled
        from .app_lock import is_locked
        gpu = getattr(self, 'gpu', None)
        if ended or not active or not feature_enabled(self.owner, 'gpu_video') or getattr(self, '_gpu_declined', False):
            if gpu is not None and (ended or not active):
                gpu.close()
                self.gpu = None
            return False
        if gpu is None:
            from .gpu_video import GpuVideoWindow
            gpu = self.gpu = GpuVideoWindow.open()
            if gpu is None:
                self._gpu_declined = True  # No GPU here: keep the normal grid for this call.
                return False
        if not gpu.alive():
            # The user closed the GPU window: cameras come back to this window.
            self.gpu = None
            self._gpu_declined = True
            self.picture.configure(text='')
            return False
        for ssrc in list(tiles):
            tiles.pop(ssrc)['label'].destroy()
        from .i18n import tr
        self.picture.configure(image='', text=tr('The cameras are shown in the "TG-ASCII · Video" window (GPU). Close it to see them here.'),
                               wraplength=max(200, self.viewport.winfo_width() - 40), justify='center')
        self.picture.place(x=0, y=0, relwidth=1, relheight=1)
        if not is_locked(self.owner):
            try:
                gpu.show(active, frames)
            except Exception as error:
                from .recovery import record_failure
                record_failure(self.owner.service.root, 'gpu_video', error)
                gpu.close()
                self.gpu = None
                self._gpu_declined = True
                return False
        if hasattr(self, 'local_picture'):
            self.local_picture.lift()
        return True

    def poll_local_frame(self):
        from .app_lock import is_locked
        if (getattr(self, '_decoding_local', False) or not self.snapshot.get('video')
                or not self.window.winfo_viewable() or is_locked(self.owner)):
            return
        take = getattr(self.manager, 'take_local_frame', None)
        frame = take() if take else None
        if frame is None:
            return
        size = (min(168, self.viewport.winfo_width() - 16), min(112, self.viewport.winfo_height() - 16))
        if min(size) < 32:
            self.local_picture.place_forget()
            return
        token = self.snapshot.get('token')
        self._decoding_local = True
        def decode():
            from PIL import ImageOps
            from .calls_native import frame_image
            image = frame_image(frame)
            image.thumbnail(size)
            return ImageOps.mirror(image)
        def decoded(image):
            self._decoding_local = False
            if (not self.alive() or token != self.snapshot.get('token')
                    or not self.snapshot.get('video') or is_locked(self.owner)):
                return
            from PIL import ImageTk
            if self.local_photo is not None and (self.local_photo.width(), self.local_photo.height()) == image.size:
                self.local_photo.paste(image)
            else:
                self.local_photo = ImageTk.PhotoImage(image, master=self.window)
                self.local_picture.configure(image=self.local_photo)
            self.local_picture.place(relx=1, rely=1, x=-8, y=-8, anchor='se',
                                     width=image.width + 2, height=image.height + 2)
            self.local_picture.lift()
        def failed(_):
            self._decoding_local = False
        self.owner.worker.submit(asyncio.to_thread(decode), decoded, failed)

    def destroyed(self, event):
        if event.widget is not self.window:
            return
        self.close_call_pip()
        if self.timer is not None:
            self.window.after_cancel(self.timer)
            self.timer = None
        self.photo = None
        self.local_photo = None
        gpu = getattr(self, 'gpu', None)
        if gpu is not None:
            gpu.close()
            self.gpu = None
        if getattr(self.owner, '_call_windows', {}).get(self.account) is self:
            self.owner._call_windows.pop(self.account, None)
