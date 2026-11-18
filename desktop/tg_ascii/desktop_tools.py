"""Composer formatting, audio dialogs, Telegram translation/AI and background mode."""
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk, font as tkfont
from .scrolling import FlowFrame
from .app_dialogs import Choice, messagebox, simpledialog, filedialog
from .i18n import tr, LANGUAGES
from .preferences import read_json, write_json
from .message_tools import formatted_entities, entity_spans
from .audio_engine import AudioJob


class DesktopTools:
    def init_tools(self):
        self.format_tags, self.format_drafts = {}, {}
        self.audio_jobs = []
        self.translated, self.translation_pending, self.translation_failed = {}, set(), set()
        self.translation_path = self.preferences.path.with_name('translations.json')
        owner = getattr(self, '_linked_owner', None)
        self.chat_translations = owner.chat_translations if owner is not None else {} if self.demo else read_json(self.translation_path, {})
        self.background = None

    def setup_tools(self, parent):
        from .app_dialogs import popup_menu
        row = self.composer_controls
        emoji = ttk.Button(row, text='☺', width=3, command=self.emoji_picker)
        emoji.pack(side='left',padx=3)
        self.media_controls=FlowFrame(parent)
        self.media_controls.pack(fill='x',before=self.editor,pady=2)
        for label,custom in [('Stickers',False),('Emojis',True)]:
            button=ttk.Button(self.media_controls,text=tr(label),command=lambda c=custom:self.telegram_picker(c))
            if custom:self.custom_emoji_button=button
            else:self.sticker_button=button
            button.pack(side='left',padx=2);self.buttons.append(button)
        more = ttk.Button(row,text='⋯',width=3)
        more.configure(command=lambda:popup_menu(self.root,self.composer_tool_actions(),anchor=more))
        more.pack(side='left')
        self.buttons.extend([emoji,more])
        for key, style in [('b', 'bold'), ('i', 'italic'), ('u', 'underline')]:
            self.editor.bind('<Control-' + key + '>', lambda e, s=style: self.apply_format(s))
        self.format_tags = {}

    def composer_tool_actions(self):
        from .advanced_features import feature_enabled
        from .chat_capabilities import chat_capabilities
        capabilities = chat_capabilities(self)
        actions = []
        if capabilities.allows('send'):
            actions.extend([(tr('Format'), self.format_dialog),
                            (tr('Send without sound'), lambda: self.send(silent=True))])
            if capabilities.allows('schedule'):
                actions.append((tr('Schedule message'), self.schedule_message))
            if self.editor.get('1.0', 'end-1c').strip():
                actions.append((tr('Telegram AI'), self.ai_dialog))
        if capabilities.allows('send_voices') or capabilities.allows('send_audios'):
            actions.append((tr('Audio'), self.audio_menu))
        if capabilities.allows('translate'):
            enabled = feature_enabled(self, 'chat_translation')
            label = tr('Translate chat') + ('' if enabled else ' · ' + tr('Disabled'))
            actions.append((label, self.translation_dialog if enabled else self.complex_settings))
        return actions

    def index_for(self, offset):
        from .composer import Composer
        if isinstance(self.editor,Composer):return self.editor.logical_index(offset)
        text = self.editor.get('1.0', 'end-1c')
        return f'1.0 + {self.editor.tk.call("string", "length", text[:offset])} chars'

    def snapshot_formats(self):
        spans = []
        for tag, (style, argument) in getattr(self, 'format_tags', {}).items():
            ranges = self.editor.tag_ranges(tag)
            for start, end in zip(ranges[::2], ranges[1::2]):
                spans.append((len(self.editor.get('1.0', start)), len(self.editor.get('1.0', end)), style, argument))
        return sorted(spans)

    def restore_formats(self, spans=None):
        for tag in self.editor.tag_names():
            if tag.startswith('format_'): self.editor.tag_delete(tag)
        self.format_tags = {}
        if spans is None: spans = getattr(self, 'format_drafts', {}).get((self.ui_account, self.active), [])
        for start, end, style, argument in spans:
            self.add_format(self.index_for(start), self.index_for(end), style, argument)

    def add_format(self, start, end, style, argument=''):
        from .desktop import FONT
        tag = f'format_{len(self.format_tags)}'
        self.format_tags[tag] = (style, argument)
        options = {'underline': style in ('underline', 'link'), 'overstrike': style == 'strike'}
        if style in ('bold', 'italic'): options['font'] = (*FONT, style)
        if style == 'code': options['font'] = tkfont.nametofont('TkFixedFont')
        if style == 'spoiler': options['underline'] = True
        if style in ('quote','collapsed_quote'):options.update(lmargin1=18,lmargin2=18)
        self.editor.tag_configure(tag, **options)
        self.editor.tag_add(tag, start, end)
        self.refresh_format_preview()

    def refresh_format_preview(self):
        from .desktop import FONT
        from .themes import _palette
        for tag in self.editor.tag_names():
            if tag.startswith('format_preview_'): self.editor.tag_delete(tag)
        self._format_fonts = []
        spans = self.snapshot_formats()
        boundaries = sorted({point for start, end, _, _ in spans for point in (start, end)})
        for index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
            styles = {style for a, b, style, _ in spans if a <= start and b >= end}
            if not styles: continue
            family = tkfont.nametofont('TkFixedFont').actual('family') if 'code' in styles else FONT[0]
            font = tkfont.Font(root=self.root, family=family, size=FONT[1],
                               weight='bold' if 'bold' in styles else 'normal',
                               slant='italic' if 'italic' in styles else 'roman')
            self._format_fonts.append(font)
            tag = f'format_preview_{index}'
            self.editor.tag_configure(tag, font=font, underline=bool(styles & {'underline', 'link'}),
                overstrike='strike' in styles, background=_palette['selected'] if 'spoiler' in styles else self.editor.cget('bg'))
            self.editor.tag_add(tag, self.index_for(start), self.index_for(end))
            self.editor.tag_raise(tag)
        self.editor.tag_raise('sel')

    def apply_format(self, style, selection=None):
        if self.busy: return 'break'
        try: start, end = selection or self.editor.tag_ranges('sel')
        except (ValueError, tk.TclError):
            self.status.set(tr('Select text first.'))
            return 'break'
        if style == 'clear':
            for tag in self.format_tags: self.editor.tag_remove(tag, start, end)
        else:
            if style != 'link':
                for tag, (existing, _) in self.format_tags.items():
                    ranges = self.editor.tag_ranges(tag)
                    if existing == style and any(self.editor.compare(a, '<=', start) and self.editor.compare(b, '>=', end)
                                                  for a, b in zip(ranges[::2], ranges[1::2])):
                        for name, (kind, _) in self.format_tags.items():
                            if kind == style: self.editor.tag_remove(name, start, end)
                        self.refresh_format_preview()
                        self.editor.focus_set()
                        return 'break'
            argument = ''
            if style == 'link':
                argument = simpledialog.askstring(tr('Link'), 'https://', parent=self.root)
                if not argument: return 'break'
            text = self.editor.get('1.0', 'end-1c')
            candidate = (len(self.editor.get('1.0', start)), len(self.editor.get('1.0', end)), style, argument)
            try: formatted_entities(text, self.snapshot_formats() + [candidate], self.snapshot_custom())
            except ValueError as exc: self.show_error(exc); return 'break'
            self.add_format(start, end, style, argument)
        self.refresh_format_preview()
        self.editor.focus_set()
        return 'break'

    def format_dialog(self):
        if self.busy: return
        selection = self.editor.tag_ranges('sel')
        if len(selection) != 2:
            self.status.set(tr('Select text first.')); return
        from .app_dialogs import popup_menu
        entries=[]
        for style,label in [('bold','Bold'),('italic','Italic'),('underline','Underline'),
            ('strike','Strikethrough'),('spoiler','Spoiler'),('code','Monospace'),('link','Link'),('quote','Cita'),('collapsed_quote','Texto desplegable'),('clear','Clear formatting')]:
            entries.append((tr(label),lambda s=style:self.apply_format(s,selection)))
        popup_menu(self.root,entries,anchor=self.composer_controls)

    def font_picker(self, parent):
        ttk.Label(parent, text=tr('App font')).pack(anchor='w')
        families = sorted(set(tkfont.families(self.root)), key=str.casefold)
        # Opening the selector refreshes installed fonts, including ones added
        # while the app was running. Layout-only rebuilds can reuse the setup.
        self.root._font_configuration = None
        from .typography import terminal_family
        picker = Choice(parent, values=[tr('Default') + ' — ' + terminal_family(self.root, families)] + families, width=30)
        current = self.preferences.values['font_family']
        picker.current(families.index(current) + 1 if current in families else 0)
        picker.pack(anchor='w', pady=5)
        return picker, families

    def logout_account(self, key=None):
        if self.busy: return
        if getattr(self, '_linked_owner', None) is not None:
            from .interface_layout import caption
            self.status.set(caption('Manage shared logins in the main window.', 'Gestiona las sesiones compartidas en la ventana principal.'))
            self._linked_owner.root.deiconify()
            self._linked_owner.root.lift()
            return
        import asyncio
        from .customization_sync import label as caption
        from .profile_customization import purge_account_customization
        key = self.ui_account if key is None else key
        if key not in self.service.entries:
            return
        if key != self.ui_account:
            # 1.5.4: signing out another account from Settings keeps this one as it is.
            self.stash_account()
        from .desktop_features import account_label
        label = account_label(self, key, key)
        detail = tr('Log out {account}? Other accounts stay connected.').format(account=label)
        detail += '\n\n' + caption(
            'Pending text drafts will be saved to Telegram first; if that fails, logout is cancelled. Local profile changes, chat appearance and local draft copies (including attachments and linked windows) for this account will be removed.',
            'Primero se guardan los borradores de texto pendientes en Telegram; si falla, se cancela el cierre de sesión. Se quitarán los cambios locales de perfil, apariencia de chats y copias locales de borradores de esta cuenta, incluidos adjuntos y ventanas vinculadas.')
        if not messagebox.askyesno(tr('Log out this account'), detail, parent=self.root): return
        manager = getattr(self, 'draft_manager', None)
        linked = [window for window in getattr(self, '_chat_windows', ()) if window.account == key]
        full_views = [view for view in getattr(self, '_app_windows', ()) if not view.closed and not view.closing]
        try:
            if manager is not None:
                manager.snapshot()
            for window in linked:
                window.persist_draft(capture_only=True)
            for view in full_views:
                if view.ui_account == key:
                    view.draft_manager.snapshot()
        except (OSError, ValueError, tk.TclError) as exc:
            self.show_error(exc)
            return
        if not hasattr(self, '_logging_out_accounts'):
            self._logging_out_accounts = set()
        self._logging_out_accounts.add(key)
        for popup in self.popups:
            if popup.winfo_exists(): popup.destroy()
        logout_stage = None
        async def operation():
            nonlocal logout_stage
            if manager is not None:
                await asyncio.to_thread(manager.store.flush)
                await manager.sync_pending(account=key, allow_logout=True)
            for view in full_views:
                await view.draft_manager.sync_pending(account=key, allow_logout=True)
            try:
                logout_stage = await self.service.logout(key)
                return logout_stage
            finally:
                if key not in self.service.entries:
                    if manager is not None:
                        manager.store.remove_account(key)
                        await asyncio.to_thread(manager.store.flush)
                    from .interface_windows import purge_window_drafts
                    await asyncio.to_thread(purge_window_drafts, self, key)
                    if not self.demo:
                        await asyncio.to_thread(purge_account_customization, self.preferences.path.parent, key)
        def done(stage):
            self._logging_out_accounts.discard(key)
            for window in linked:
                window.close(discard_draft=True)
            self.account_states.pop(key, None)
            self.account_unread.pop(key, None)
            for name in ('rich_drafts', 'format_drafts', 'reply_drafts', 'preview_cache', 'avatar_images',
                         'translated', 'reply_cache', '_emoji_files', '_standard_emoji_documents',
                         '_emoji_text_color', '_avatar_status', '_avatar_displayed'):
                mapping = getattr(self, name, {})
                for item in list(mapping):
                    if isinstance(item, tuple) and item[0] == key: mapping.pop(item, None)
            for name in ('preview_pending', 'preview_failed', 'translation_pending', 'translation_failed'):
                values = getattr(self, name, set())
                values.difference_update(item for item in list(values) if isinstance(item, tuple) and item[0] == key)
            for name in ('_standard_emoji_packs','_standard_emoji_retry'):
                getattr(self,name,{}).pop(key,None)
            getattr(self,'_standard_emoji_pending',set()).discard(key)
            for name in ('wallpapers', 'chat_translations'):
                values = getattr(self, name, {})
                for item in list(values):
                    if item.startswith(key + ':'): values.pop(item, None)
            if hasattr(self, 'local_pins'): self.local_pins.values.pop(key, None)
            themes = getattr(self, '_chat_theme_overrides', None)
            if themes is not None:
                themes.values = {item: value for item, value in themes.values.items()
                                 if not item.startswith(key + ':') and not item.startswith('wallpaper:' + key + ':')}
            if manager is not None:
                manager.loaded = {item for item in manager.loaded if item[0] != key}
                manager._remote_versions = {item: value for item, value in manager._remote_versions.items() if item[0] != key}
            self.ui_account = self.service.current
            state = self.account_states.get(self.ui_account, {})
            self.active, self.messages = state.get('active'), state.get('messages', [])
            self.chats, self.drafts = state.get('chats', []), state.get('drafts', {})
            if manager is not None:
                manager.restore_account()
            self.attachment = None
            self.login_stage(stage)
        def failed(exc):
            self._logging_out_accounts.discard(key)
            if key not in self.service.entries:
                done(logout_stage if logout_stage is not None else
                     'ready' if self.service.backend is not None else 'connecting')
            self.show_error(exc)
        self.call(operation(), done, tr('Cerrando...'), failed)

    def audio_menu(self):
        if self.busy or self.active is None: return
        from .app_dialogs import popup_menu
        from .chat_capabilities import chat_capabilities
        capabilities = chat_capabilities(self)
        def choose():
            if not chat_capabilities(self).allows('send_audios'):return
            path=filedialog.askopenfilename(parent=self.root,title=tr('Audio'))
            if path: self.audio_dialog(Path(path),voice=False)
        actions = []
        if capabilities.allows('send_voices'):actions.append((tr('Record voice message'),self.record_audio))
        if capabilities.allows('send_audios'):actions.append((tr('Send audio file'),choose))
        if actions:popup_menu(self.root,actions,anchor=self.composer_controls)

    def record_audio(self):
        if self.busy or self.active is None: return
        from .chat_capabilities import chat_capabilities
        if not chat_capabilities(self).allows('send_voices'):return
        directory = tempfile.TemporaryDirectory(prefix='tg-as-voice-', ignore_cleanup_errors=True)
        self.media_temps.append(directory)
        path = Path(directory.name) / 'voice.ogg'
        self.audio_dialog(path, voice=True, recording=True)

    def audio_dialog(self, path, voice=False, recording=False, sending=True, filename=None):
        from .chat_capabilities import chat_capabilities
        permission = 'send_voices' if voice else 'send_audios'
        if sending and not chat_capabilities(self).allows(permission):return
        self.audio_jobs = [job for job in self.audio_jobs if not job.done.is_set()]
        account, peer, backend = self.ui_account, self.active, self.service.backend
        window, frame = self.dialog('Audio', '520x360')
        ttk.Label(frame, text=path.name, wraplength=460).pack(anchor='w', pady=8)
        status = tk.StringVar(value=tr('Recording...') if recording else tr('Ready'))
        ttk.Label(frame, textvariable=status, wraplength=460).pack(anchor='w', pady=8)
        if recording: ttk.Label(frame, text=tr('Maximum recording: 10 minutes. Stop, preview, then send.'), wraplength=460).pack(anchor='w')
        job = [AudioJob().record(path) if recording else None]
        duration, sent = [0], [False]
        if job[0]: self.audio_jobs.append(job[0])
        def alive(): return window.winfo_exists() and not self.closed
        def stop():
            if job[0]: job[0].stop()
        def play():
            if recording and duration[0] <= 0: return
            if job[0] and not job[0].done.is_set(): return
            job[0] = AudioJob().play(path)
            self.audio_jobs.append(job[0])
            status.set(tr('Playing...'))
            poll(False)
        def poll(is_record):
            if not alive(): return
            active = job[0]
            if active and not active.done.is_set():
                status.set((tr('Recording...') if is_record else tr('Playing...')) + f' {active.seconds:.1f}s')
                window.after(150, lambda: poll(is_record))
            else:
                if active and active.error:
                    status.set(str(active.error))
                    if is_record: send.configure(state='disabled')
                else:
                    if is_record: duration[0] = active.seconds
                    status.set(tr('Ready'))
                    if sending: send.configure(state='normal')
        def transmit():
            if self.busy or self.ui_account != account or self.active != peer or sent[0]: return
            if not chat_capabilities(self).allows(permission):
                send.pack_forget()
                return
            if job[0] and not job[0].done.is_set(): stop(); return
            if voice and (not path.exists() or duration[0] <= 0): return
            send.configure(state='disabled')
            reply_to = getattr(self, 'reply_drafts', {}).get((account, peer))
            def done(message):
                self.clear_sent_reply(account, peer, reply_to)
                sent[0] = True
                if alive(): window.destroy()
                from .interface_windows import publish_local_message
                publish_local_message(self, account, peer, message)
            def failed(exc):
                if alive(): send.configure(state='normal')
                self.show_error(exc)
            operation = backend.send_audio(peer, path, voice, duration[0], reply_to=reply_to) if not self.demo else backend.send_attachment(peer, path)
            self.call(operation, done, tr('Enviando...'), failed,timeout=None)
        ttk.Button(frame, text=tr('Stop'), command=stop).pack(fill='x', pady=4)
        ttk.Button(frame, text=tr('Play'), command=play).pack(fill='x', pady=4)
        send = ttk.Button(frame, text=tr('Enviar >'), command=transmit, state='disabled' if recording else 'normal')
        if sending: send.pack(fill='x', pady=4)
        else:
            def save_audio():
                import shutil
                destination = filedialog.asksaveasfilename(parent=window, initialfile=Path(filename).name if filename else 'audio.ogg')
                if destination:
                    try: shutil.copyfile(path, destination)
                    except OSError as exc: self.show_error(exc)
            ttk.Button(frame, text=tr('Save'), command=save_audio).pack(fill='x', pady=4)
        def destroyed(event):
            if event.widget == window: stop()
        window.bind('<Destroy>', destroyed)
        if recording: poll(True)

    def play_message_audio(self, message, peer=None):
        if self.busy: return
        peer=self.active if peer is None else peer
        backend, account = self.service.backend, self.ui_account
        directory = tempfile.TemporaryDirectory(prefix='tg-as-audio-', ignore_cleanup_errors=True)
        self.media_temps.append(directory)
        async def fetch():
            media = await backend.media_message(peer, message.id)
            return await backend.download_media(media, Path(directory.name) / 'audio')
        def ready(path):
            if self.ui_account == account and backend is self.service.backend: self.audio_dialog(Path(path), sending=False, filename=message.filename)
        self.call(fetch(), ready, tr('Descargando...'),timeout=None)

    def language_target(self, frame):
        codes = list(LANGUAGES)
        choice = Choice(frame, values=list(LANGUAGES.values()))
        choice.current(codes.index(self.preferences.values['language']))
        choice.pack(fill='x', pady=8)
        return lambda: codes[choice.current()].split('-')[0]

    def translation_key(self):
        return f'{self.ui_account}:{self.active}'

    def translation_dialog(self):
        from .advanced_features import feature_enabled
        from .chat_capabilities import chat_capabilities
        can_translate = chat_capabilities(self).allows('translate') or (getattr(self, 'thread', None) is not None and getattr(self, 'account_premium', lambda: True)())
        if not can_translate:
            return
        if not feature_enabled(self, 'chat_translation'):
            return self.complex_settings()
        if self.busy or self.active is None or self.demo: return
        window, frame = self.dialog('Translate chat', '540x330')
        target = self.language_target(frame)
        enabled = tk.BooleanVar(value=bool(self.chat_translations.get(self.translation_key())))
        ttk.Checkbutton(frame, text=tr('Automatic translation (Premium)'), variable=enabled).pack(anchor='w', pady=8)
        ttk.Label(frame, text=tr('Translates loaded and incoming messages. Originals are preserved.'), wraplength=480).pack(anchor='w', pady=8)
        key, backend = self.translation_key(), self.service.backend
        scope = (self.ui_account, self.active)
        def save():
            if self.busy:return
            if (scope != (self.ui_account, self.active) or backend is not self.service.backend
                    or not (chat_capabilities(self).allows('translate') or getattr(self, 'thread', None) is not None)):
                if window.winfo_exists():window.destroy()
                return
            value = target() if enabled.get() else None
            updated = dict(self.chat_translations)
            if value: updated[key] = value
            else: updated.pop(key, None)
            try:
                write_json(self.translation_path, updated)
            except OSError as exc:
                self.show_error(exc)
                return
            from .interface_windows import share_view_value
            share_view_value(self, 'chat_translations', updated)
            self.translation_failed.clear()
            self._translation_scope=None
            if window.winfo_exists():window.destroy()
            self.render_messages(False)
        save_button=ttk.Button(frame, text=tr('Guardar ajustes'), command=save)
        save_button.pack(anchor='e', pady=8)

    def schedule_translations(self):
        from .translation_queue import schedule
        schedule(self)

    def result_dialog(self, title, result, apply=None):
        window, frame = self.dialog(title, '640x510')
        text = tk.Text(frame, wrap='word', height=15)
        text.pack(fill='both', expand=True)
        text.insert('1.0', result.text)
        text.configure(state='disabled')
        if apply:
            ttk.Button(frame, text=tr('Use in draft'), command=lambda: (apply(result), window.destroy())).pack(anchor='e', pady=8)

    def message_actions(self, message):
        if self.busy or self.demo: return
        kinds = DesktopTools.message_tool_kinds(self, message)
        if not kinds:return
        backend, account, peer = self.service.backend, self.ui_account, self.active
        window, frame = self.dialog('Message tools', '450x350')
        target = self.language_target(frame)
        def perform(kind):
            if self.busy or (account, peer) != (self.ui_account, self.active) or kind not in DesktopTools.message_tool_kinds(self, message): return
            language = target()
            window.destroy()
            async def operation():
                if kind == 'translate': return (await backend.translate_messages(peer, [message.id], language)).get(message.id)
                if kind == 'summary': return await backend.summarize_message(peer, message.id, language)
                return await backend.transcribe_audio(peer, message.id)
            def done(result):
                if account != self.ui_account or result is None: return
                self.result_dialog('Translation' if kind == 'translate' else 'Telegram AI', result)
                if getattr(result, 'pending', False): self.status.set(tr('Transcription pending. Open this action again later.'))
            self.call(operation(), done, tr('Cargando...'))
        for kind, label in (('translate', 'Translation'), ('summary', 'Summarize with Telegram AI'), ('transcribe', 'Transcribe audio')):
            if kind in kinds:ttk.Button(frame, text=tr(label), command=lambda k=kind: perform(k)).pack(fill='x', pady=4)

    def message_tool_kinds(self, message):
        from .chat_capabilities import chat_capabilities
        from telethon import types
        readable = getattr(self, 'thread', None) is not None or chat_capabilities(self).readable
        if (not readable or getattr(message, 'service', False)
                or type(getattr(message, 'id', None)) is not int or message.id <= 0):
            return ()
        text = getattr(message, 'raw_text', None)
        if text is None:text = getattr(message, 'text', '')
        kinds = ['translate', 'summary'] if text.strip() else []
        document = getattr(getattr(message, 'media', None), 'document', None)
        attributes = getattr(document, 'attributes', ())
        if any(isinstance(item, types.DocumentAttributeAudio) and item.voice
               or isinstance(item, types.DocumentAttributeVideo) and item.round_message for item in attributes):
            kinds.append('transcribe')
        return tuple(kinds)

    def ai_dialog(self):
        if self.busy or self.demo or self.active is None: return
        original = self.editor.get('1.0', 'end-1c')
        if not original.strip(): return
        spans, emojis = self.snapshot_formats(), self.snapshot_custom()
        backend, account, peer = self.service.backend, self.ui_account, self.active
        window, frame = self.dialog('Telegram AI', '500x330')
        target = self.language_target(frame)
        ttk.Label(frame, text=tr('Telegram processes this text. Availability and quotas depend on your account.'), wraplength=440).pack(anchor='w', pady=8)
        def request(mode):
            if self.busy: return
            language = target()
            window.destroy()
            def apply(result):
                if self.busy or account != self.ui_account or peer != self.active or self.editor.get('1.0', 'end-1c') != original:
                    self.status.set(tr('Draft changed. The result was not applied.')); return
                self.editor.delete('1.0', 'end')
                self.editor.insert('1.0', result.text)
                formats, custom = entity_spans(result.text, result.entities)
                self.rich_drafts[(account, peer)] = custom
                self.restore_custom_draft()
                self.restore_formats(formats)
            self.call(backend.compose_ai(original, spans, emojis, mode, language),
                      lambda result: self.result_dialog('Telegram AI', result, apply), tr('Cargando...'))
        for mode, label in [('proofread', 'Proofread'), ('emojify', 'Add emojis'), ('translate', 'Translation')]:
            ttk.Button(frame, text=tr(label), command=lambda m=mode: request(m)).pack(fill='x', pady=4)

    def _install_macos_dock_handler(self):
        # 1.5.0.1: Tk's own application delegate already implements
        # applicationShouldHandleReopen:, so adding that method below fails
        # silently and reopening the app (Dock, Finder, Desktop icon) showed
        # nothing while the window was hidden. Tk calls this documented hook.
        try:
            self.root.createcommand('::tk::mac::ReopenApplication', lambda *_: self.root.after(0, self.reopen_window))
        except tk.TclError:
            pass
        try:
            import AppKit, objc
            app = AppKit.NSApplication.sharedApplication()
            delegate = app.delegate()
            if delegate is not None:
                cls = delegate.__class__
                def handle_reopen(s, application, has_visible_windows):
                    self.root.after(0, self.reopen_window)
                    return True
                sel = objc.selector(handle_reopen, selector=b'applicationShouldHandleReopen:hasVisibleWindows:', signature=b'B@:@B')
                try:
                    objc.classAddMethod(cls, b'applicationShouldHandleReopen:hasVisibleWindows:', sel)
                except Exception:
                    try:
                        setattr(cls, 'applicationShouldHandleReopen:hasVisibleWindows:', sel)
                    except Exception:
                        pass
        except Exception:
            pass

    def reopen_window(self):
        from .app_lock import show_locked
        if show_locked(self, after=self.reopen_window):return
        self.root.deiconify()
        for window,state in getattr(self,'_hidden_windows',()):
            try:
                if window.winfo_exists():
                    window.deiconify()
                    if state=='zoomed':window.state('zoomed')
            except tk.TclError:pass
        self._hidden_windows=[]
        try:
            self.root.attributes('-topmost', True)
            self.root.update_idletasks()
            self.root.lift()
            self.root.focus_force()
            self.root.attributes('-topmost', False)
        except Exception:
            self.root.lift()
            self.root.focus_force()

    def window_close(self):
        if self.preferences.values['background_notifications'] and self.stage == 'ready':
            if self.background is None:
                from .background import Background
                from .themes import resolve_theme
                icon = self.selected_logo_path(resolve_theme(self.preferences.values['logo_theme']))
                self.background = Background(lambda action: self.worker.events.put((lambda _: action(), None)), self.reopen_window, self.close, icon_path=icon)
            # run_detached signals visibility asynchronously on some platforms.
            self.root.after(300, self.hide_if_tray_ready)
        else: self.close()

    def hide_if_tray_ready(self):
        if self.closed or self.closing: return
        from .app_lock import lock_on_hide,is_locked
        lock_on_hide(self)
        if self.background and self.background.ready:
            # 1.5.0.1: keep dialogs and chat windows as they were; hide them
            # with the main window and bring them back on reopen.
            hidden=[]
            for window in [*self.popups,*(view.root for view in getattr(self,'_app_windows',()) if not view.closed)]:
                try:
                    if window.winfo_exists() and window.state()!='withdrawn':
                        hidden.append((window,window.state()));window.withdraw()
                except tk.TclError:pass
            self._hidden_windows=hidden
            self.root.withdraw()
        else:
            if is_locked(self):
                from .app_lock import lock_owner
                panel=getattr(lock_owner(self),'_app_lock_panel',None)
                if panel is not None:panel.window.iconify()
            else:self.root.iconify()
            self.status.set(tr('Tray unavailable. The app is minimized and remains connected.'))
