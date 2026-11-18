"""Optional desktop features. All Tk mutations stay on the UI thread."""
from pathlib import Path
from collections import OrderedDict
from datetime import datetime, timezone
import asyncio
import sys
import tempfile
import tkinter as tk
from tkinter import ttk
from telethon import types
from . import APP_NAME
from .i18n import tr
from .app_dialogs import messagebox
from .local_state import LocalPins
from .notification_history import record_notice


from .desktop_modern import DesktopModern
from .resources import cache_entries, network_slots

# Visible avatars fetched at once (1.3: 2). Downloads share the backend's own
# DOWNLOAD_CONCURRENCY=4 slots and FLOOD_WAIT gate.
AVATAR_CONCURRENCY = 4


class DesktopPlus(DesktopModern):
    def init_plus(self):
        self.init_tools()
        owner = getattr(self, '_linked_owner', None)
        self.local_pins = owner.local_pins if owner is not None else LocalPins(root=self.preferences.path.parent, demo=self.demo)
        self.rich_drafts, self.custom_tags = {}, {}
        self.preview_cache, self.preview_images, self.avatar_images = {}, {}, OrderedDict()
        self._avatar_pending=set(); self._avatar_displayed={}; self._avatar_status={}
        self.preview_pending, self.preview_failed = set(), set()
        self.preview_generation = 0
        self.notify_seen = set()
        from .notification_delivery import DeliveryLedger
        self.notification_ledger = (owner.notification_ledger if owner is not None else
            DeliveryLedger(None if self.demo else self.preferences.path.parent / 'notification-delivery.sqlite'))
        from .notification_history import NotificationHistory
        self.notification_history=(owner.notification_history if owner is not None else NotificationHistory(None if self.demo else self.preferences.path.parent/'notification-history.sqlite'))
        self.push_status = 'Desactivadas. Se utilizan las notificaciones normales.'
        from .notifications import NotificationCenter, InlineNotice
        self.notification_error = ''
        def report(error):
            self.worker.events.put((self.notification_failed, error))
        self.notification_center = NotificationCenter(report)
        self.inline_notice = InlineNotice(self.root)
        self.preview_slots = None
        directory = tempfile.TemporaryDirectory(prefix='tg-ascii-preview-', ignore_cleanup_errors=True)
        self.media_temps.append(directory)
        self.preview_dir = Path(directory.name)
        self.init_modern()

    def local_pin_ids(self):
        return self.local_pins.get(self.ui_account, self.preferences.values['local_pins']) if hasattr(self, 'local_pins') else set()

    def toggle_local_pin(self):
        if self.busy or self.active is None: return
        self.local_pins.toggle(self.ui_account, self.active, self.preferences.values['local_pins'])
        owner = getattr(self, '_linked_owner', None) or self
        for view in (owner, *tuple(getattr(owner, '_app_windows', ()))):
            if not view.closed and view.stage == 'ready':
                view.render_chats()

    def snapshot_custom(self):
        from .composer import Composer
        if isinstance(self.editor,Composer):return self.editor.snapshot_custom()
        spans = []
        if not hasattr(self, 'custom_tags'): return spans
        for tag, (docid, alt) in self.custom_tags.items():
            ranges = self.editor.tag_ranges(tag)
            if len(ranges) != 2: continue
            start, end = ranges
            if self.editor.get(start, end) != alt: continue
            spans.append((len(self.editor.get('1.0', start)), len(self.editor.get('1.0', end)), docid, alt))
        return sorted(spans)

    def save_custom_draft(self):
        if hasattr(self, 'rich_drafts') and self.active is not None:
            self.rich_drafts[(self.ui_account, self.active)] = self.snapshot_custom()
            self.format_drafts[(self.ui_account, self.active)] = self.snapshot_formats()

    def restore_custom_draft(self):
        if not hasattr(self, 'rich_drafts'): return
        self.custom_tags = {}
        from .composer import Composer
        if isinstance(self.editor,Composer):
            self.editor.restore_custom(self.rich_drafts.get((self.ui_account,self.active),[]))
            self.restore_formats()
            return
        self.restore_formats()
        for start, end, docid, alt in self.rich_drafts.get((self.ui_account, self.active), []):
            # Tcl counts supplementary Unicode differently on some runtimes.
            text = self.editor.get('1.0', 'end-1c')
            prefix = text[:start]
            index = f'1.0 + {self.editor.tk.call("string", "length", prefix)} chars'
            finish = f'{index} + {self.editor.tk.call("string", "length", alt)} chars'
            if text[start:end] == alt:
                tag = f'custom_{len(self.custom_tags)}'
                self.editor.tag_add(tag, index, finish)
                self.editor.tag_configure(tag, underline=True)
                self.custom_tags[tag] = (docid, alt)

    def telegram_picker(self, custom=False, on_choose=None):
        from .sticker_picker import open_picker
        open_picker(self,custom,on_choose)

    def show_document_pack(self,document):
        from .sticker_picker import show_pack
        if isinstance(document,int):document=getattr(self,'_standard_emoji_documents',{}).get((self.ui_account,document),document)
        show_pack(self,document)

    def load_photo(self, path, size, tint=None):
        try:
            from .animation import AnimationPlayer
            if not hasattr(self, 'animation_player'): self.animation_player=AnimationPlayer(self.root)
            return self.animation_player.photo(path,size,self.preferences.values.get('animated_emoji',True),tint=tint)
        except (ImportError, OSError, ValueError, tk.TclError): return None

    def request_photo(self,path,size,callback,*,owner=None,tint=None,valid=None,enabled=None):
        """Decode shared preview art outside Tk, then publish to a still-current view."""
        if not path or getattr(self,'closed',False) or getattr(self,'closing',False):return
        from .animation import AnimationPlayer
        if not hasattr(self,'animation_player'):self.animation_player=AnimationPlayer(self.root)
        follows_setting=enabled is None
        enabled=self.preferences.values.get('animated_emoji',True) if follows_setting else bool(enabled)
        valid=valid or (lambda:owner is None or bool(owner.winfo_exists()))
        if follows_setting:
            target_valid=valid
            valid=lambda:enabled==self.preferences.values.get('animated_emoji',True) and target_valid()
        try:
            if not valid():return
        except tk.TclError:return
        jobs=getattr(self,'_photo_requests',None)
        if jobs is None:jobs=self._photo_requests={}
        key=(str(path),tuple(size),enabled,tint)
        listener=(callback,owner,valid)
        if key in jobs:
            current=[]
            for entry in jobs[key]:
                try:
                    if entry[2]():current.append(entry)
                except tk.TclError:pass
            jobs[key][:]=current
            jobs[key].append(listener)
            return
        jobs[key]=[listener]
        self.start_photo_requests()

    def start_photo_requests(self):
        """Only two decodes exist at once; discard obsolete queued views in Tk."""
        if getattr(self,'closed',False) or getattr(self,'closing',False):return
        jobs=self._photo_requests
        active=getattr(self,'_photo_active',None)
        if active is None:active=self._photo_active=set()
        player=self.animation_player
        for key in list(jobs):
            from .decode_pool import parallelism
            if len(active)>=parallelism(2):break  # process_decoding: one per spare core
            if key in active:continue
            listeners=[]
            for listener in jobs[key]:
                try:
                    if listener[2]():listeners.append(listener)
                except tk.TclError:pass
            if not listeners:jobs.pop(key,None);continue
            jobs[key]=listeners;active.add(key)
            path,size,enabled,tint=key
            async def prepare(path=path,size=size,enabled=enabled,tint=tint):
                from . import decode_pool
                prepared=None
                if decode_pool.active() and not player.has(path,size,enabled,tint):
                    try:prepared=await decode_pool.decode_frames(path,size,enabled)  # process_decoding: another core
                    except (OSError,ValueError):prepared=None
                if prepared is None:return await asyncio.to_thread(player.prepare,path,size,enabled,tint)
                return await asyncio.to_thread(player.prepare,path,size,enabled,tint,prepared)
            def loaded(prepared,key=key,path=path,size=size,enabled=enabled,tint=tint):
                listeners=jobs.pop(key,[]);active.discard(key)
                if getattr(self,'closed',False) or getattr(self,'closing',False):return
                for callback,owner,valid in listeners:
                    try:
                        if valid():
                            photo=player.photo(path,size,enabled,prepared=prepared,tint=tint,owner=owner)
                            callback(photo)
                    except (ImportError,OSError,ValueError,tk.TclError):pass
                self.start_photo_requests()
            def failed(_,key=key):
                jobs.pop(key,None);active.discard(key);self.start_photo_requests()
            self.worker.submit(prepare(),loaded,failed)

    def schedule_preview(self, message, mark, epoch):
        from .media_retry import failed_recently,remember_failure,clear_failure
        if not self.preferences.values['inline_media'] or self.demo: return
        account, peer, backend = self.ui_account, self.active, self.service.backend
        key = (account, peer, message.id)
        if key in self.preview_cache:
            self.insert_preview((epoch, mark, self.preview_cache[key]))
            return
        if failed_recently(self,key) or key in self.preview_pending: return
        self.preview_pending.add(key)
        async def fetch():
            if self.preview_slots is None: self.preview_slots = asyncio.Semaphore(network_slots(2))
            async with self.preview_slots:
                path = self.preview_dir / f'{account}-{peer}-{message.id}.jpg'
                # Only Telegram-provided thumbnails are fetched automatically.
                await backend.download_media(message.media, path, thumbnail=True)
                return path
        def loaded(path):
            self.preview_pending.discard(key)
            clear_failure(self,key)
            self.preview_cache[key] = path
            while len(self.preview_cache)>cache_entries(512):self.preview_cache.pop(next(iter(self.preview_cache)))
            if epoch != self.preview_generation:
                # A new rendering may still contain this message.
                if account == self.ui_account and peer == self.active:
                    self.insert_preview((self.preview_generation, mark, path))
            else: self.insert_preview((epoch, mark, path))
        def failed(_):
            self.preview_pending.discard(key)
            remember_failure(self,key)
        self.worker.submit(fetch(), loaded, failed)

    def insert_preview(self, data):
        epoch, mark, path = data
        if epoch != self.preview_generation or not self.history.winfo_exists() or mark not in self.history.mark_names(): return
        if mark in self.preview_images: return
        def current():
            return epoch==self.preview_generation and self.history.winfo_exists() and mark in self.history.mark_names() and mark not in self.preview_images
        def loaded(photo):
            self.preview_images[mark]=photo
            follow=self.history.yview()[1]>=.98
            self.history.configure(state='normal')
            self.history.image_create(mark,image=photo,padx=8,pady=8)
            self.history.configure(state='disabled')
            self.link_inline_preview(mark)
            if follow:self.history.see('end')
        self.request_photo(path,(360,260),loaded,owner=self.history,valid=current)

    def request_avatars(self):
        if self.demo or getattr(self,'closed',False) or getattr(self,'closing',False):return
        from .ui_work import FrameJob
        widget=getattr(self,'chat_list',None)
        if widget is None:return
        job=getattr(self,'_avatar_job',None)
        if job is None or job.widget is not widget:
            if job is not None:job.cancel()
            self._avatar_job=job=FrameJob(widget,self.load_avatars,32)
        job.request()

    def remember_avatar(self,key,photo):
        self.avatar_images[key]=photo
        self.avatar_images.move_to_end(key)
        # 256 small native bitmaps, shared by the rows currently on screen.
        while len(self.avatar_images)>256:
            old,_=self.avatar_images.popitem(last=False)
            self._avatar_status.pop(old[:2],None)

    def show_avatar(self,widget,peer,photo):
        key=(self.ui_account,peer)
        if self._avatar_displayed.get(key)==(widget,str(photo)):return
        widget.item(str(peer),image=photo or '')
        self._avatar_displayed[key]=(widget,str(photo))
        while len(self._avatar_displayed)>256:
            self._avatar_displayed.pop(next(iter(self._avatar_displayed)))

    def load_avatars(self):
        from .media_retry import failed_recently,remember_failure,clear_failure
        if self.demo or getattr(self,'closed',False) or getattr(self,'closing',False):return
        from .ui_work import visible_tree_rows
        from .animation import AnimationPlayer
        account,backend,widget=self.ui_account,self.service.backend,self.chat_list
        visible=visible_tree_rows(widget)
        if not visible:return
        chats=getattr(self,'_chat_by_id',None)
        if chats is None:chats={chat.id:chat for chat in self.chats}
        if not hasattr(self,'animation_player'):self.animation_player=AnimationPlayer(self.root)
        player=self.animation_player
        enabled=self.preferences.values.get('animated_emoji',True)
        for ident in visible:
            chat=chats.get(int(ident))
            if chat is None:continue
            key=(account,chat.id,'avatar')
            if key in self.avatar_images:
                self.avatar_images.move_to_end(key)
                composite=self.avatar_images.get((account,chat.id,'status-composite'))
                current_status=self._avatar_status.get((account,chat.id))
                photo=composite if composite and current_status==(chat.emoji_status_id,id(self.avatar_images[key])) else self.avatar_images[key]
                self.show_avatar(widget,chat.id,photo)
                self.decorate_chat_status(chat.id,chat)
                continue
            if failed_recently(self,key):
                self.decorate_chat_status(chat.id,chat)
                continue
            if key in self._avatar_pending or len(self._avatar_pending)>=network_slots(AVATAR_CONCURRENCY):continue
            self._avatar_pending.add(key);self.preview_pending.add(key)
            async def fetch(peer=chat.id,entity=chat.entity):
                path=self.preview_dir/f'{account}-{peer}-avatar.jpg'
                if (account,peer,'avatar') not in self.preview_cache or not path.is_file():path=await backend.avatar(peer,path,entity=entity)
                if path:await asyncio.to_thread(player.prepare,path,(30,30),enabled)
                return path
            def completed(key=key):
                self._avatar_pending.discard(key);self.preview_pending.discard(key)
                self.request_avatars()
            def loaded(path,key=key,peer=chat.id,chat=chat,completed=completed):
                completed()
                if not path:
                    remember_failure(self,key)
                    return
                if account!=self.ui_account or widget is not self.chat_list or not widget.winfo_exists():return
                clear_failure(self,key)
                self.preview_cache[key]=path
                while len(self.preview_cache)>cache_entries(512):self.preview_cache.pop(next(iter(self.preview_cache)))
                photo=self.load_photo(path,(30,30))
                if not photo:return
                self.remember_avatar(key,photo)
                if str(peer) in visible_tree_rows(widget):
                    self.show_avatar(widget,peer,photo)
                    self.decorate_chat_status(peer,chat)
            def failed(_,key=key,completed=completed):
                completed();remember_failure(self,key)
            self.worker.submit(fetch(),loaded,failed)

    def sync_contacts(self):
        if self.busy: return
        def loaded(contacts):
            self.synced_contacts = (self.ui_account, contacts)
            self.status.set(tr('Contacts synchronized: {count}').format(count=len(contacts)))
        # Refresh the account's Telegram contacts. Never upload an OS address book silently.
        self.call(self.service.backend.contacts(), loaded, tr('Syncing Telegram contacts...'))

    def notification_dialog(self):
        if self.busy: return
        def loaded(settings):
            window, outer = self.dialog('Notifications', '700x670')
            from .app_dialogs import scrollable
            frame = scrollable(outer)
            local = {}
            ttk.Label(frame, text=tr('On this computer'), style='Title.TLabel').pack(anchor='w')
            ttk.Label(frame, text=tr('Outside the app: system notifications. Inside: a notice in the active window.'), wraplength=600).pack(anchor='w', pady=6)
            ttk.Label(frame, text=tr('System settings control banners and permission. Keep TG-ASCII running in the background to receive new messages; push while the process is stopped is not configured in this build.').replace('TG-ASCII', APP_NAME), wraplength=600).pack(anchor='w', pady=6)
            ttk.Label(frame, text=tr(getattr(self, 'push_status', '')), wraplength=600).pack(anchor='w', pady=6)
            ttk.Button(frame, text=tr('Configurar push en funciones complejas'), command=self.complex_settings).pack(anchor='w', pady=4)
            if self.notification_error:
                ttk.Label(frame, text=tr('Notification center unavailable. Check system notification settings.') + '\n' + self.notification_error, wraplength=600).pack(anchor='w', pady=6)
            for key, label in [('notifications', 'Show notifications while the app is running'), ('notify_preview', 'Show message previews'),
                               ('notify_sound', 'Play a sound'), ('notify_active', 'Notify for the open chat')]:
                local[key] = tk.BooleanVar(value=self.preferences.values[key])
                ttk.Checkbutton(frame, text=tr(label), variable=local[key]).pack(anchor='w', pady=3)
            from .advanced_features import feature_enabled
            push_var = tk.BooleanVar(value=feature_enabled(self, 'push_notifications'))
            push_label = tr('macOS push notifications' if sys.platform == 'darwin' else 'Windows push notifications')
            ttk.Checkbutton(frame, text=push_label, variable=push_var).pack(anchor='w', pady=3)
            ttk.Label(frame, text=tr('Telegram settings (synchronized)'), style='Title.TLabel').pack(anchor='w', pady=12)
            rows = {}
            for category, label in [('private', 'Private chats'), ('groups', 'Groups'), ('channels', 'Channels')]:
                current = settings[category]
                until = getattr(current, 'mute_until', None)
                enabled = not bool(until and until.timestamp() > datetime.now(timezone.utc).timestamp())
                row = ttk.LabelFrame(frame, text=tr(label), padding=5)
                row.pack(fill='x', pady=3)
                values = {'enabled': enabled, 'show_previews': getattr(current, 'show_previews', None) is not False,
                          'sound': not isinstance(getattr(current, 'other_sound', None), types.NotificationSoundNone),
                          'stories_muted': bool(getattr(current, 'stories_muted', False))}
                rows[category] = (values, {})
                for key, text in [('enabled', 'Enabled'), ('show_previews', 'Preview'), ('sound', 'Sound'), ('stories_muted', 'Mute stories')]:
                    variable = tk.BooleanVar(value=values[key]); rows[category][1][key] = variable
                    ttk.Checkbutton(row, text=tr(text), variable=variable).pack(side='left', padx=3)
            ttk.Label(frame, text=tr('Quit stops notifications. Closing the window keeps the app running.'), wraplength=600).pack(anchor='w', pady=8)
            def save():
                if self.busy: return
                changes = []
                for category, (before, variables) in rows.items():
                    update = {}
                    for key, variable in variables.items():
                        value = variable.get()
                        if value == before[key]: continue
                        if key == 'enabled': update['mute_until'] = datetime.fromtimestamp(0 if value else 2147483647, timezone.utc)
                        elif key == 'sound': update['sound'] = types.NotificationSoundDefault() if value else types.NotificationSoundNone()
                        else: update[key] = value
                    if update: changes.append((category, update))
                async def apply():
                    if not self.demo:
                        for category, values in changes: await self.service.backend.save_notification_settings(category, values)
                def done(_):
                    prefs = {key: value.get() for key, value in local.items()}
                    adv = dict(self.preferences.values.get('advanced_features') or {})
                    adv['push_notifications'] = push_var.get()
                    prefs['advanced_features'] = adv
                    self.preferences.save(prefs)
                    self.configure_push_notifications()
                    window.destroy()
                    self.status.set(tr('Ajustes guardados.'))
                self.call(apply(), done, tr('Guardando...'))
            ttk.Button(frame, text=tr('Guardar ajustes'), command=save).pack(anchor='e', pady=10)
        if self.demo:
            loaded({key: types.PeerNotifySettings() for key in ('private', 'groups', 'channels')})
        else: self.call(self.service.backend.notification_settings(), loaded, tr('Cargando...'))

    def notification_open_callback(self, account, peer, message_id, backend):
        # OS callbacks may run outside Tk's thread, just like reply callbacks.
        import threading
        lock,used=threading.Lock(),[False]
        def activate():
            with lock:
                if used[0]:return
                used[0]=True
            self.worker.events.put((self.open_from_notification,(account,peer,message_id,backend)))
        return activate

    def open_from_notification(self, context):
        if self.closed or self.closing or self.demo:return
        from .app_lock import show_locked
        if show_locked(self,lambda:self.open_from_notification(context)):return
        self._notification_target=context
        self.reopen_window()
        self.continue_notification_open(context)

    def continue_notification_open(self, context, switched=False):
        if self.closed or self.closing or getattr(self,'_notification_target',None) is not context:return
        from .app_lock import show_locked
        if show_locked(self,lambda:self.continue_notification_open(context,switched)):return
        account,peer,message_id,backend=context
        service=self.service.services.get(account)
        if account not in self.service.entries or service is None or service.backend is not backend:
            self._notification_target=None;self.status.set(tr('Inicia sesion de nuevo'));return
        if self.busy:
            self.root.after(100,lambda:self.continue_notification_open(context,switched));return
        if account!=self.ui_account:
            if switched:
                self._notification_target=None;self.status.set(tr('Inicia sesion de nuevo'));return
            self.switch_account(account)
            self.root.after_idle(lambda:self.continue_notification_open(context,True));return
        if self.stage!='ready':
            self._notification_target=None;self.status.set(tr('Inicia sesion de nuevo'));return
        self._notification_target=None
        self.notebook.select(self.chat_page)
        self.clear_selection();self._preview_only=False
        self.compact_conversation=True;self.adapt_chat_layout()
        self.jump_message(message_id,peer)

    def notification_reply_callback(self, account, peer, message_id, backend):
        # The OS can invoke this on a background thread. Only queue Tk work.
        import threading
        lock, used = threading.Lock(), [False]
        def reply(text):
            if not isinstance(text, str) or not text.strip(): return
            with lock:
                if used[0]: return
                used[0] = True
            context = (account, peer, message_id, backend, text)
            self.worker.events.put((self.reply_from_notification, context))
        return reply

    def reply_from_notification(self, context):
        if self.closed or self.closing or self.demo: return
        from .app_lock import show_locked
        if show_locked(self,lambda:self.reply_from_notification(context)):return
        account, peer, message_id, backend, text = context
        def current():
            service = self.service.services.get(account)
            return account in self.service.entries and service is not None and service.backend is backend
        def failed(error):
            if self.closed or self.closing: return
            self.reopen_window()
            window, frame = self.dialog('Reply', '480x320')
            ttk.Label(frame, text=tr('Reply not sent. You can copy your text below.'), wraplength=420).pack(fill='x')
            ttk.Label(frame, text=str(error), wraplength=420).pack(fill='x', pady=6)
            editor = tk.Text(frame, height=6, wrap='word')
            editor.insert('1.0', text)
            editor.pack(fill='both', expand=True)
        if not current():
            failed(tr('Inicia sesion de nuevo')); return
        async def send():
            if not current(): raise ValueError(tr('Inicia sesion de nuevo'))
            return await backend.send_formatted(peer, text, [], reply_to=message_id)
        def sent(message):
            if current() and not self.closed and not self.closing:
                self.account_event((account, peer, message))
                self.status.set(tr('Reply sent.'))
        self.worker.submit(send(), sent, failed)

    def notification_failed(self, error):
        record_notice(self,'failed',content=str(error))
        if self.closed or self.closing: return
        self.notification_error = str(error)
        self.status.set(tr('Notification center unavailable. Check system notification settings.'))

    def configure_push_notifications(self):
        """UI hook after account readiness or preference changes; lazy import."""
        owner = getattr(self, '_linked_owner', None) or self
        if owner is not self:
            return owner.configure_push_notifications()
        if self.demo or getattr(self, 'closed', False) or getattr(self, 'closing', False):
            return
        from .advanced_features import feature_enabled
        enabled = feature_enabled(self, 'push_notifications') and self.preferences.values['notifications']
        if not enabled and not hasattr(self, 'push_controller'):
            return
        if not hasattr(self, 'push_controller'):
            from .push_notifications import PushController
            def publish(account, peer, message):
                self.worker.events.put((self.push_message, (account, peer, message)))
            def report(text):
                self.worker.events.put((self.push_state_changed, text))
            self.push_controller = PushController(self.service, publish, report)
        self.worker.submit(self.push_controller.configure(enabled), lambda _: None,
                           lambda _: self.push_state_changed('No se pudo configurar push. Se mantienen las notificaciones normales.'))

    def push_state_changed(self, text):
        self.push_status = str(text)
        if not getattr(self, 'closed', False) and not getattr(self, 'closing', False):
            self.status.set(tr(self.push_status))

    def push_message(self, event):
        if getattr(self, 'closed', False) or getattr(self, 'closing', False):
            return
        account, peer, message = event
        self.notify_message(account, peer, message, source='push')

    async def close_push_notifications(self):
        if getattr(self, '_linked_owner', None) is not None:
            return
        controller = getattr(self, 'push_controller', None)
        if controller is not None:
            await controller.close()
        ledger = getattr(self, 'notification_ledger', None)
        if ledger is not None:
            await asyncio.to_thread(ledger.close)
        journal=getattr(self,'notification_history',None)
        if journal is not None:await asyncio.to_thread(journal.close)

    def notify_message(self, account, peer, message, *, source='live'):
        if message.outgoing or not self.preferences.values['notifications'] or self.demo: return
        owner = getattr(self, '_linked_owner', None)
        if owner is not None:
            return owner.notify_message(account, peer, message, source=source)
        key = (account, peer, message.id)
        msg_summary = f'{message.sender}: {message.text[:160]}' if getattr(message, 'text', None) else (message.sender or '')
        if peer in getattr(self, '_suppressed_thread_peers', ()):
            record_notice(self, 'suppressed', source, key, content=msg_summary)
            return
        record_notice(self,'received',source,key,content=msg_summary)
        if key in self.notify_seen:
            record_notice(self,'duplicate',source,key,content=msg_summary);return
        self.notify_seen.add(key)
        if len(self.notify_seen) > 4000:
            # The persistent ledger keeps older IDs. Do not clear all recent
            # events at once and replay thousands after a reconnect.
            self.notify_seen.discard(next(item for item in self.notify_seen if item != key))
        controller = getattr(self, 'push_controller', None)
        ledger = getattr(self, 'notification_ledger', None)
        claim_holder = [None]
        released = [False]
        def release():
            # Native adapters may call this on an OS thread. Queue cleanup on
            # the worker and never access Tk from that callback.
            if released[0]:
                return
            released[0] = True
            claim = claim_holder[0]
            async def forget():
                if controller is not None:
                    controller.forget_live(account, peer, message.id)
                if ledger is not None and claim is not None:
                    await asyncio.to_thread(ledger.release, claim)
            if controller is not None or (ledger is not None and claim is not None):
                self.worker.submit(forget(), lambda _: None, lambda _: None)
            self.notify_seen.discard(key)
        def commit():
            if ledger is not None and claim_holder[0] is not None and not released[0]:
                self.worker.submit(asyncio.to_thread(ledger.commit, claim_holder[0]), lambda _: None, lambda _: None)
        from .notifications import foreground_view, notification_key
        def reading_chat(view):
            if view is not None and account == view.ui_account and peer == view.active and getattr(view, 'chat_visible', lambda: False)():
                return True
            for window in getattr(self, '_chat_windows', ()):
                if getattr(window, 'valid', lambda: False)() and getattr(window, 'chat_visible', lambda: False)() and (window.account, window.peer) == (account, peer):
                    return True
            return False
        if reading_chat(foreground_view(self)) and not self.preferences.values['notify_active']: return
        backend = self.service.service(account).backend
        def loaded(policy):
            if policy.get('_duplicate'):
                record_notice(self,'duplicate',source,key,content=msg_summary);return
            if getattr(self, 'closed', False) or getattr(self, 'closing', False):
                release();return
            if account not in self.service.entries:
                release();return
            if not policy['enabled'] or not self.preferences.values['notifications']:
                record_notice(self,'suppressed',source,key,content=msg_summary);commit();return
            view = foreground_view(self)
            if reading_chat(view) and not self.preferences.values['notify_active']:
                commit();return
            from .desktop_features import account_label
            label = account_label(self, account)
            title = label + ' · ' + message.sender
            body = message.text[:160] if policy['preview'] and self.preferences.values['notify_preview'] else tr('New message')
            notice_content = f'{title}: {body}'
            activate = self.notification_open_callback(account, peer, message.id, backend)
            reply = self.notification_reply_callback(account, peer, message.id, backend)
            from .app_lock import is_locked
            if is_locked(self):
                title=APP_NAME;body=tr('New message');reply=None;view=None
                notice_content = APP_NAME + ': ' + tr('New message')
            if view is not None:
                try:
                    if policy['sound'] and self.preferences.values['notify_sound']: view.root.bell()
                    view.inline_notice.show(title, body, activate, reply)
                    record_notice(self,'in_app',source,key,content=notice_content)
                    commit()
                except (tk.TclError, RuntimeError):
                    release()
            else:
                accepted = self.notification_center.show(title, body, notification_key(account, peer), reply, activate,
                    sound=bool(policy['sound'] and self.preferences.values['notify_sound']), on_failed=release)
                if accepted is not False:
                    record_notice(self,'submitted',source,key,content=notice_content);commit()
        async def policy():
            from telethon import errors
            try:
                if controller is not None and source == 'live':
                    controller.note_live(account, peer, message.id)
                if ledger is not None:
                    claim_holder[0] = await asyncio.to_thread(ledger.claim, account, peer, message.id)
                    if claim_holder[0] is None:
                        return {'_duplicate': True}
                try:
                    result = await backend.notification_policy(peer)
                except (OSError, TimeoutError, errors.ServerError):
                    await asyncio.sleep(.5)
                    result = await backend.notification_policy(peer)
                return result
            except BaseException:
                if ledger is not None and claim_holder[0] is not None:
                    await asyncio.to_thread(ledger.release, claim_holder[0])
                raise
        def failed(_):
            release()
        self.worker.submit(policy(), loaded, failed)

    def update_dialog(self):
        from . import __version__, updater
        from zipfile import BadZipFile
        from .app_dialogs import filedialog
        if self.busy: return
        window, frame = self.dialog('Updates', '610x380')
        ttk.Label(frame, text=APP_NAME + ' ' + __version__, style='Title.TLabel').pack(anchor='w', pady=12)
        status = tk.StringVar(value=tr('Choose a release ZIP or check the publisher channel.'))
        ttk.Label(frame, textvariable=status, wraplength=550).pack(anchor='w', pady=12)
        def install(path):
            try:
                manifest, _, _ = updater.validate_archive(path)
                updater.application_directory()
            except (OSError, ValueError, KeyError, BadZipFile) as exc: self.show_error(exc); return
            if not messagebox.askyesno(APP_NAME, tr('Install {version} and restart? Your accounts and settings will be kept.').format(version=manifest['version']), parent=window): return
            async def prepare(): return await asyncio.to_thread(updater.prepare_install, path)
            self.call(prepare(), lambda _: self.close(), tr('Preparing update...'))
        def from_file():
            if self.busy: return
            path = filedialog.askopenfilename(parent=window, title=tr('Choose update ZIP'), filetypes=[('ZIP', '*.zip')])
            if path: install(path)
        def checked(item):
            if not window.winfo_exists(): return
            if item is None: status.set(tr('You are up to date.')); return
            status.set(tr('Version available: {version}').format(version=item['version']))
            def fetch():
                if self.busy: return
                async def operation():
                    return await asyncio.to_thread(updater.download, item, self.preview_dir / 'update.zip')
                self.call(operation(), install, tr('Descargando...'))
            ttk.Button(frame, text=tr('Download and install'), command=fetch).pack(fill='x', pady=8)
        def check():
            if self.busy: return
            async def operation(): return await asyncio.to_thread(updater.check)
            self.call(operation(), checked, tr('Checking for updates...'))
        ttk.Button(frame, text=tr('Check for updates'), command=check).pack(fill='x', pady=6)
        ttk.Button(frame, text=tr('Install release ZIP'), command=from_file).pack(fill='x', pady=6)

    def refresh_logo(self, system=None):
        from .themes import resolve_theme, palette
        theme = resolve_theme(self.preferences.values['logo_theme'], system)
        if not hasattr(self, 'logo_label') or not self.logo_label.winfo_exists(): return
        colors = palette(theme)
        from .logos import VARIANTS
        variant = self.preferences.values['logo_variant']
        asset = self.selected_logo_path(theme)
        icon_key = (str(asset), variant, theme)
        photo = self.load_photo(asset, (32, 32) if self.stage == 'ready' else (72, 72)) if asset.exists() else None
        if asset.exists() and getattr(self, '_icon_theme', None) != icon_key:
            try:
                from .themes import set_app_icon
                set_app_icon(self.root, asset)
                self._icon_theme = icon_key
                if getattr(self, 'background', None): self.background.update_icon(asset)
            except (OSError, AttributeError, tk.TclError): pass
        if photo:
            self.logo_image = photo
            self.logo_label.configure(image=photo, text='', background=colors['bg'])
        else:
            self.logo_label.configure(text='[ ' + VARIANTS[variant] + ' ]', font=('Courier', 18, 'bold'), foreground=colors['text'], background=colors['bg'])

    def selected_logo_path(self, theme):
        from .logos import asset_path, brand_asset_path, custom_icon_path
        values = self.preferences.values
        custom = custom_icon_path(values['custom_icon'])
        if custom is not None:
            return custom
        try:
            return brand_asset_path(self.preferences.path.parent, values['logo_variant'], theme, values['logo_color'])
        except OSError:
            return asset_path('title-short', theme)

    def watch_theme(self):
        if self.closed: return
        from .themes import system_theme, apply_widget
        needs_system = any(self.preferences.values[key] == 'system' for key in ('theme', 'logo_theme'))
        def apply(system):
            if self.closed:return
            state = (self.preferences.values['theme'], self.preferences.values['logo_theme'], system)
            if getattr(self, '_theme_state', None) != state:
                self._theme_state = state;self.configure_style();apply_widget(self.root)
                if hasattr(self, 'editor') and self.editor.winfo_exists(): self.refresh_format_preview()
                self.refresh_logo(system)
            self.root.after(5000,self.watch_theme)
        if needs_system:self.worker.submit(asyncio.to_thread(system_theme,True),apply,lambda _:apply(system_theme()))
        else:apply('dark')

    def custom_previews(self, message):
        """Legacy history preview entry point, sharing the inline artwork loader."""
        if not getattr(message, 'custom_emojis', ()) or not self.preferences.values['inline_media'] or self.demo: return
        for index,(document_id, _) in enumerate(message.custom_emojis):
            mark = f'preview_emoji_{message.id}_{document_id}_{index}'
            self.history.mark_set(mark, 'end-1c')
            self.history.mark_gravity(mark, 'left')
            self.history.insert('end', '◇')
            self.emoji_at(document_id,mark,self.preview_generation)

    def acknowledge_visible(self):
        if self.stage != 'ready' or self.active is None or not self.messages or self.demo or getattr(self, '_preview_only', False): return
        if not self.chat_visible(): return
        import time as _time
        if _time.monotonic() < getattr(self, '_read_hold_until', 0):
            # 1.5.0.2: the chat is still moving to its first unread message;
            # reading now would mark the bottom of the chat that is never seen.
            from .read_visibility import schedule
            schedule(self, 150)
            return
        peer, account, backend = self.active, self.ui_account, self.service.backend
        # 1.4.1: read only what is on screen. Unread messages below the
        # viewport stay unread until they are scrolled into view.
        from .read_visibility import visible_message_ids
        visible = visible_message_ids(self)
        if not visible:
            # 1.5.0.1: the chat may still be drawing (media, long histories).
            # Look again shortly instead of giving up until the next scroll.
            tries = getattr(self, '_read_retry', (None, 0))
            count = tries[1] + 1 if tries[0] == (self.ui_account, self.active) else 1
            if count <= 12:
                self._read_retry = ((self.ui_account, self.active), count)
                from .read_visibility import schedule
                schedule(self, 250)
            return
        self._read_retry = (None, 0)
        message_id = max(visible)
        from .read_visibility import at_bottom
        bottom = at_bottom(self)
        if bottom:
            # The end of the chat is on screen: everything loaded is read, even
            # items the overlap test missed (1.5.0.2).
            message_id = max(message_id, max((m.id for m in self.messages if m.id > 0), default=0))
        key = (account, peer)
        if not hasattr(self, '_read_ack'): self._read_ack, self._read_pending = {}, set()
        if key in self._read_pending: return
        clear_mark = False
        if self._read_ack.get(key, 0) >= message_id:
            # Already sent. If the list still shows this chat as unread while
            # its end is on screen, Telegram's count came back stale (a dialog
            # refresh raced the read) or the chat carries a manual "unread"
            # mark: send the read again and ask Telegram for the real count,
            # at most every 10 s per chat (1.5.0.2).
            import time as _time
            chat = next((item for item in self.chats if item.id == peer), None)
            stale = chat is not None and (chat.unread or getattr(chat, 'unread_mark', False))
            forced = getattr(self, '_read_forced', {})
            if not (bottom and stale and _time.monotonic() - forced.get(key, 0) > 10):
                return
            forced[key] = _time.monotonic(); self._read_forced = forced
            clear_mark = bool(getattr(chat, 'unread_mark', False))
            noted = self.__dict__.setdefault('_read_resend_noted', set())
            if key not in noted:  # Once per chat and session: evidence, not noise.
                noted.add(key)
                from .recovery import record_failure
                record_failure(self.service.root, 'read_resend', RuntimeError('stale unread count with the chat end on screen'))
        self._read_pending.add(key)
        def done(_):
            self._read_pending.discard(key)
            self._read_ack[key] = message_id
            if account != self.ui_account: return
            for chat in self.chats:
                if chat.id == peer:
                    if peer != self.active or max((m.id for m in self.messages), default=0) <= message_id:
                        chat.unread = 0
                    else:
                        # Unread messages still below the viewport keep counting.
                        chat.unread = min(chat.unread, sum(1 for m in self.messages if m.id > message_id and not m.outgoing))
            self.render_chats()
            if peer == self.active: self.acknowledge_visible()
            if getattr(self, '_read_forced', {}).get(key) and not getattr(self, '_chat_only', False):
                # Fetch Telegram's real count after a resend.
                self.root.after(1500, self.refresh)
        async def mark():
            # Bounded: a request hanging on a dead socket used to keep this chat
            # "pending" forever, so nothing in it was ever marked read again.
            result = await asyncio.wait_for(backend.mark_read(peer, message_id), 20)
            if clear_mark:
                await asyncio.wait_for(backend.set_chat_unread(peer, False), 20)
            return result
        def failed(_):
            self._read_pending.discard(key)
            if peer == self.active and account == self.ui_account:
                from .read_visibility import schedule
                schedule(self, 3000)
        self.worker.submit(mark(), done, failed)

    def chat_visible(self):
        if getattr(self, '_chat_only', False):
            focus = self.root.focus_displayof()
            return self.root.winfo_viewable() and focus is not None and focus.winfo_toplevel() == self.root
        focus = self.root.focus_displayof()
        return (self.root.winfo_viewable() and focus is not None and focus.winfo_toplevel() == self.root
                and hasattr(self, 'notebook') and self.notebook.winfo_exists()
                and self.notebook.select() == str(self.chat_page))

    def account_change(self, event):
        account, kind, payload = event
        if account not in self.service.entries or account in getattr(self, '_logging_out_accounts', ()):
            return
        if kind in ('call', 'group_call'):
            self.call_event(account, payload, **({'group': True} if kind == 'group_call' else {}))
            return
        from .interface_windows import forward_chat_change
        forward_chat_change(self, account, kind, payload)
        if kind in ('edit', 'advanced_media'):
            observer = getattr(self, 'advanced_media_changed', None)
            if observer: observer(account, *payload)
        if kind=='premium':
            self.update_account_picker()
            if account == self.ui_account and self.stage == 'ready':
                self.update_chat_capabilities()
                self.render_messages(False)
                self.refresh_bot_keyboard(force=True)
            return
        if kind=='capabilities':
            if account == self.ui_account and payload == self.active and self.stage == 'ready':
                self.update_chat_capabilities()
                self.refresh_bot_keyboard(force=True)
            return
        if kind=='draft':
            if hasattr(self, 'draft_manager'):
                self.draft_manager.remote(account, *payload)
            return
        if kind=='pending':
            from .pending_actions import on_change as pending_change
            pending_change(self,account,payload)
            return
        if kind=='connection':
            if account not in self.service.entries:return
            if payload=='online':self.service.failures.pop(account,None)
            else:self.service.failures[account]=tr('Inicia sesion de nuevo' if payload=='auth' else 'Sin conexion')
            if account==self.ui_account and self.stage=='ready':
                self.status.set(tr('Connected' if payload=='online' else 'Inicia sesion de nuevo' if payload=='auth' else 'Conectando a Telegram...' if payload=='reconnecting' else 'Sin conexion'))
                if payload=='online':self.refresh()
            if payload=='online' and getattr(self,'outbox',None) is not None and getattr(self,'_linked_owner',None) is None:
                self.outbox.online(account)
            if payload=='online' and account==self.ui_account:
                from .media_retry import retry_now
                retry_now(self)
                manager=getattr(self,'draft_manager',None)
                if manager is not None and not getattr(self,'_chat_only',False):
                    manager.persist_async()  # 1.5.3: drafts written offline reach Telegram.
            return
        if kind in ('activity','reaction','wallpaper','chat_theme','pins','accents'):
            self.modern_update(account,kind,payload)
            return
        if kind == 'secret_chat':
            if account == self.ui_account and payload == self.active and self.stage == 'ready':
                self.load_chat_header(payload)
            return
        if kind in ('edit', 'advanced_media', 'delete') and getattr(self, '_history_key', None) == (account, self.active):
            self._history_changes.append((kind, payload))
        if kind == 'dialogs':
            if getattr(self, '_chat_only', False):
                return
            if account != self.ui_account or self.stage != 'ready': return
            if getattr(self, '_sync_timer', None): self.root.after_cancel(self._sync_timer)
            def refresh():
                self._sync_timer = None
                if self.closed or self.closing or account != self.ui_account or self.stage != 'ready': return
                if self.busy:
                    self._sync_timer = self.root.after(700, refresh)
                else: self.refresh()
            self._sync_timer = self.root.after(700, refresh)
            return
        foreground = account == self.ui_account and self.stage == 'ready'
        state = {'active': self.active, 'messages': self.messages} if foreground else self.account_states.get(account)
        if not state: return
        peer, item = payload
        messages = state['messages']
        if kind in ('edit', 'advanced_media'):
            if peer != state['active']: return
            if not any(message.id == item.id for message in messages): return
            messages = [item if message.id == item.id else message for message in messages]
        elif kind == 'read':
            if peer != state['active']: return
            for message in messages:
                if message.outgoing and message.id <= item: message.read = True
        elif kind == 'delete':
            from telethon.utils import resolve_id
            if peer is not None and peer != state['active']: return
            if peer is None and (state['active'] is None or resolve_id(state['active'])[1] is types.PeerChannel): return
            messages = [message for message in messages if message.id not in item]
        if foreground:
            self.messages = messages
            self.request_message_render(False)
        else: state['messages'] = messages
