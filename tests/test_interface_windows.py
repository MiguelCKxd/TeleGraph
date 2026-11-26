"""Additional windows keep their connection, peer and drafts independent."""
import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

from tg_ascii.backend import Message
from tg_ascii.drafts import DraftStore
from tg_ascii.interface_windows import (
    LinkedChatWindow, pinned_backend, independent_command, open_independent_window,
    forward_chat_event, forward_chat_change, close_chat_windows,
)


def window_model():
    owner = object.__new__(LinkedChatWindow)
    owner.account, owner.peer, owner.closed = 'a', 41, False
    owner.backend = NS()
    owner.app = NS(service=NS(entries={'a': {}}, services={'a': NS(backend=owner.backend)}), closing=False, demo=True)
    owner.messages, owner.pending, owner.history_changes = [], set(), []
    owner.loading = owner.busy = False
    owner._draft_edited = owner._draft_applying = owner._draft_saving = False
    owner._draft_again = None
    owner.format_tags = {}
    owner.history = Mock()
    owner.history.yview.return_value = (0., 1.)
    owner.request_render = Mock()
    owner.status = Mock()
    return owner


class WindowModelTests(unittest.TestCase):
    def test_real_poll_inspector_reads_its_pinned_backend(self):
        import tkinter as tk
        from tkinter import ttk
        from concurrent.futures import Future
        root = tk.Tk()
        root.withdraw()
        window = window_model()
        window.app.demo = window.demo = False
        window.app.ui_account = 'b'
        window.app.preferences = NS(values={'advanced_features': {'polls': True}})
        window.service = NS(backend=window.backend)
        window.root = root
        window.backend.poll_state = AsyncMock()
        window.popups = []
        def dialog(*_):
            popup = tk.Toplevel(root)
            frame = ttk.Frame(popup)
            frame.pack()
            window.popups.append(popup)
            return popup, frame
        def submit(operation, *_):
            operation.close()
            return Future()
        window.dialog = dialog
        window.worker = NS(submit=submit)
        try:
            message = Message(7, 'Author', '', '', media_kind='poll')
            window.view_message_media(message)
            window.backend.poll_state.assert_called_once_with(41, 7)
            self.assertEqual(len(window.popups), 1)
            inspector = next(iter(window._advanced_inspectors))
            self.assertEqual(inspector.account, 'a')
            self.assertIs(inspector.backend, window.backend)
        finally:
            root.destroy()

    def test_advanced_and_conference_messages_keep_the_linked_context(self):
        window = window_model()
        window.app.ui_account = 'b'
        window.open_advanced_message = Mock()
        for kind in ('poll', 'checklist', 'location', 'contact', 'gift', 'article'):
            message = Message(7, 'Author', '', '', media_kind=kind)
            window.view_message_media(message)
            window.open_advanced_message.assert_called_with(message, 41)
        message = Message(7, 'Author', '', '', media_kind='conference')
        with patch('tg_ascii.desktop_calls.DesktopCalls.join_conference_message') as opened:
            window.view_message_media(message)
        opened.assert_called_once_with(window, message, 41)

    def test_reaction_uses_selected_value_and_pinned_account(self):
        window = window_model()
        window.app.demo = False
        window.app.ui_account = 'b'
        window.app.send_reaction = Mock()
        message = Message(7, 'Author', 'text', '')
        result = Message(7, 'Author', 'text', '', reactions='chosen')
        window.messages = [message]
        operation = object()
        window.backend.react = Mock(return_value=operation)
        window.call = Mock()
        with patch('tg_ascii.chat_capabilities.chat_capabilities') as caps:
            caps.return_value.allows_message.return_value = True
            window.send_reaction(message, '👍')
        window.backend.react.assert_called_once_with(41, 7, '👍')
        window.app.send_reaction.assert_not_called()
        window.call.call_args.args[1](result)
        self.assertEqual(window.messages, [result])
        window.request_render.assert_called_once()

    def test_gallery_keeps_linked_account_after_main_window_switch(self):
        window = window_model()
        window.app.ui_account = 'b'
        window.ui_account, window.active = 'a', 41
        window.service = NS(backend=window.backend)
        for kind in ('image', 'video'):
            message = Message(7, 'Author', 'caption', '', media=object(), media_kind=kind)
            with patch('tg_ascii.custom_menus.handled', return_value=False), \
                 patch('tg_ascii.menu_style.uses_system', return_value=False), \
                 patch('tg_ascii.media_gallery.open_chat_gallery') as opened:
                window.view_message_media(message)
            opened.assert_called_once_with(window, message, 41)
            self.assertEqual(opened.call_args.args[0].ui_account, 'a')
            self.assertIs(opened.call_args.args[0].service.backend, window.backend)

    def test_canvas_previews_receive_linked_context(self):
        window = window_model()
        canvas, message = object(), object()
        with patch('tg_ascii.desktop_modern.DesktopModern.canvas_media') as media, \
             patch('tg_ascii.desktop_modern.DesktopModern.canvas_emoji') as emoji:
            window.canvas_media(canvas, 5, message, 4, 64)
            window.canvas_emoji(canvas, 5, 123, 4, 64)
        media.assert_called_once_with(window, canvas, 5, message, 4, 64)
        emoji.assert_called_once_with(window, canvas, 5, 123, 4, 64, keep_text=False)

    def test_file_viewer_receives_linked_backend_instead_of_main(self):
        window = window_model()
        window.service = NS(backend=window.backend)
        window.call = Mock()
        window.backend.media_message = AsyncMock(return_value='fresh media')
        message = Message(7, 'Author', 'caption', '', media=object(), media_kind='file')
        with patch('tg_ascii.custom_menus.handled', return_value=False), \
             patch('tg_ascii.menu_style.uses_system', return_value=False), \
             patch('tg_ascii.desktop_features.DesktopFeatures.media_dialog') as shown:
            window.view_message_media(message)
            operation, ready, _ = window.call.call_args.args
            ready(asyncio.run(operation))
        window.backend.media_message.assert_awaited_once_with(41, 7)
        self.assertIs(shown.call_args.args[0], window)
        self.assertEqual(shown.call_args.args[1], 'fresh media')

    def test_gallery_jump_loads_the_message_in_its_pinned_peer(self):
        window = window_model()
        window.reveal_message = Mock()
        window.jump_message(7, 41)
        window.reveal_message.assert_called_once_with(7)
        self.assertFalse(window.jump_message(8, 99))

    def test_new_linked_draft_inherits_quality_with_its_main_attachments(self):
        from tg_ascii.attachments import photo_quality_for
        with tempfile.TemporaryDirectory() as folder:
            store = DraftStore(Path(folder))
            store.put('a', 41, {'text': 'caption', 'files': ['photo.jpg'], 'photo_quality': 'hd'})
            window = window_model()
            window.draft_store, window.draft_account = store, 'linked:a'
            self.assertEqual(photo_quality_for(window), 'hd')
            store.put('linked:a', 41, {'text': 'local', 'photo_quality': 'original'})
            self.assertEqual(photo_quality_for(window), 'original')

    def test_pinned_backend_does_not_follow_account_switch_or_create_sessions(self):
        backend = object()
        app = NS(service=NS(current='b', services={'a': NS(backend=backend), 'b': NS(backend=object())}))
        self.assertIs(pinned_backend(app, 'a'), backend)
        with self.assertRaises(ValueError):
            pinned_backend(app, 'absent')
        self.assertEqual(set(app.service.services), {'a', 'b'})

    def test_foreign_account_peer_and_duplicate_events_do_not_duplicate_messages(self):
        window = window_model()
        message = Message(4, 'A', 'hi', '')
        window.receive('b', 41, message)
        window.receive('a', 42, message)
        self.assertEqual(window.messages, [])
        window.receive('a', 41, message)
        window.receive('a', 41, message)
        self.assertEqual(window.messages, [message])
        changed = Message(4, 'A', 'changed', '')
        window.change('a', 'edit', (41, changed))
        self.assertEqual(window.messages[0].text, 'changed')
        window.change('a', 'delete', (42, [4]))
        self.assertEqual(len(window.messages), 1)
        window.change('a', 'delete', (None, [4]))
        self.assertEqual(window.messages, [])

    def test_unscoped_delete_never_removes_channel_message(self):
        window = window_model()
        window.peer = -1000000000123
        window.messages = [Message(4, 'Channel', 'keep', '')]
        window.change('a', 'delete', (None, [4]))
        self.assertEqual(len(window.messages), 1)

    def test_hidden_windows_keep_data_without_scheduling_redraws(self):
        window = window_model()
        del window.request_render
        window.visible = Mock(return_value=False)
        window.job = Mock()
        window.follow = False
        window.request_render(follow=True)
        self.assertTrue(window.dirty)
        self.assertTrue(window.follow)
        window.job.request.assert_not_called()

    def test_close_cancels_only_owned_work_and_flushes_private_draft(self):
        window = window_model()
        window.app._chat_windows = [window]
        window.job, window.draft_job, window.window = Mock(), Mock(), Mock()
        window.persist_draft = Mock()
        window.draft_store = None
        own = Mock()
        window.pending = {own}
        window.close()
        self.assertTrue(window.closed)
        own.cancel.assert_called_once()
        window.persist_draft.assert_called_once_with(capture_only=True)
        window.window.destroy.assert_called_once()
        self.assertEqual(window.app._chat_windows, [])

    def test_duplicate_windows_use_separate_draft_namespaces(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DraftStore(directory)
            store.put('a', 41, {'text': 'main'})
            for namespace, text in (('linked:a', 'window one'), ('linked:a:1', 'window two')):
                window = window_model()
                window.draft_store, window.draft_account = store, namespace
                window.editor, window.draft_job = Mock(), Mock()
                window.editor.get.return_value = text
                window.editor.snapshot_custom.return_value = []
                window.attachment, window.reply_to = None, 7
                window.persist_draft(capture_only=True)
            store.flush()
            loaded = DraftStore(directory)
            self.assertEqual(loaded.get('a', 41)['text'], 'main')
            self.assertEqual(loaded.get('linked:a', 41)['text'], 'window one')
            self.assertEqual(loaded.get('linked:a:1', 41)['text'], 'window two')

    def test_logout_cancels_window_without_recapturing_or_syncing_purged_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            window = window_model()
            window.app.demo = False
            window.app.worker = Mock()
            window.app._chat_windows = [window]
            window.app._logging_out_accounts = {'a'}
            window.draft_store, window.draft_account = DraftStore(directory), 'linked:a'
            window.job, window.draft_job, window.window = Mock(), Mock(), Mock()
            window.editor = Mock()
            window.editor.get.return_value = 'late modified event'
            window.persist_draft()
            self.assertIsNone(window.draft_store.get('linked:a', 41))
            self.assertFalse(window.valid())
            window.persist_draft = Mock()
            window.close(discard_draft=True)
            window.persist_draft.assert_not_called()
            window.app.worker.submit.assert_not_called()
            window.window.destroy.assert_called_once()
            self.assertTrue(window.closed)

    def test_independent_process_has_unique_profile_and_never_uses_a_shell(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            app = NS(service=NS(root=Path(folder)), demo=True)
            process = Mock()
            with patch('subprocess.Popen', return_value=process) as launch:
                ident = open_independent_window(app)
            command = launch.call_args.args[0]
            # 1.5.4: a demo window is always temporary and gets its own folder.
            self.assertEqual(command[-3:], ['--data-dir', str((Path(folder) / 'windows' / ident).resolve()), '--demo'])
            self.assertTrue((Path(folder) / 'windows' / ident / '.temporary').exists())
            self.assertNotIn('shell', launch.call_args.kwargs)
            self.assertEqual(app._independent_windows, [process])
        with patch('tg_ascii.interface_windows.sys.frozen', True, create=True):
            self.assertNotIn('-m', independent_command('/tmp/other'))

    def test_dispatch_uses_snapshot_while_a_window_closes(self):
        first, second = Mock(), Mock()
        app = NS(_chat_windows=[first, second])
        first.receive.side_effect = lambda *args: app._chat_windows.remove(first)
        forward_chat_event(app, 'a', 41, 'message')
        second.receive.assert_called_once_with('a', 41, 'message')
        forward_chat_change(app, 'a', 'read', (41, 4))
        second.change.assert_called_once_with('a', 'read', (41, 4))
        close_chat_windows(app)
        second.close.assert_called_once()


class WindowRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_closing_linked_window_saves_on_worker_instead_of_blocking_tk(self):
        with tempfile.TemporaryDirectory() as directory:
            window = window_model()
            window.draft_store = DraftStore(directory)
            window.draft_account = 'linked:a'
            window.job, window.draft_job, window.window = Mock(), Mock(), Mock()
            window.editor = Mock()
            window.editor.get.return_value = 'keep after closing'
            window.editor.snapshot_custom.return_value = []
            window.attachment, window.reply_to = None, None
            window.app.worker, window.app.show_error = Mock(), Mock()
            window.close()
            self.assertFalse(window.draft_store.path.exists())
            operation, _, failed = window.app.worker.submit.call_args.args
            self.assertIs(failed, window.app.show_error)
            await operation
            self.assertEqual(DraftStore(directory).get('linked:a', 41)['text'], 'keep after closing')

    async def test_main_app_exit_captures_linked_draft_for_shared_durable_flush(self):
        with tempfile.TemporaryDirectory() as directory:
            window = window_model()
            window.draft_store = DraftStore(directory)
            window.draft_account = 'linked:a'
            window.job, window.draft_job, window.window = Mock(), Mock(), Mock()
            window.editor = Mock()
            window.editor.get.return_value = 'preserve linked draft'
            window.editor.snapshot_custom.return_value = []
            window.attachment, window.reply_to = None, None
            window.app.closing = True
            window.app.worker = Mock()
            with patch.object(window.draft_store, 'flush') as flush:
                window.close()
                flush.assert_not_called()
            window.app.worker.submit.assert_not_called()
            self.assertEqual(window.draft_store.get('linked:a', 41)['text'], 'preserve linked draft')
            await asyncio.to_thread(window.draft_store.flush)
            self.assertEqual(DraftStore(directory).get('linked:a', 41)['text'], 'preserve linked draft')

    async def test_only_focused_changed_composer_publishes_telegram_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            window = window_model()
            window.app.demo = False
            window.draft_store = DraftStore(directory)
            window.draft_account = 'linked:a'
            record = {'text': 'draft', 'custom': [], 'formats': [], 'reply': None}
            window.draft_store.put(window.draft_account, 41, record, pending=True)
            window._draft_edited = True
            window.backend.save_draft = AsyncMock(return_value=True)
            window.composer_focused = Mock(return_value=False)
            queued = []
            window.call = lambda operation, done, failed=None: queued.append((operation, done))
            window.sync_draft(record)
            self.assertEqual(queued, [])
            window.composer_focused.return_value = True
            window.sync_draft(record)
            operation, done = queued.pop()
            done(await operation)
            window.backend.save_draft.assert_awaited_once_with(41, 'draft', [], [], None)
            self.assertFalse(window._draft_edited)
            self.assertFalse(window.draft_store.get(window.draft_account, 41)['pending'])
            window.sync_draft(record)
            self.assertEqual(queued, [])

    async def test_remote_draft_never_overwrites_unsent_linked_composer(self):
        window = window_model()
        window.editor = Mock()
        window.editor.edit_modified.return_value = False
        window.composer_focused = Mock(return_value=False)
        window._draft_edited = True
        window.remote_draft({'text': 'remote'})
        window.editor.delete.assert_not_called()
        window._draft_edited = False
        window.remote_draft({'text': 'remote media', 'unsupported': True})
        window.editor.delete.assert_not_called()
        window.restore_formats = Mock()
        window.reply_label = Mock()
        window.draft_store = None
        window.remote_draft({'text': 'remote', 'formats': [(0, 6, 'bold', '')]})
        window.editor.insert.assert_called_once_with('1.0', 'remote')
        window.restore_formats.assert_called_once_with([(0, 6, 'bold', '')])

    async def test_remote_text_draft_keeps_local_album_paths_and_quality(self):
        with tempfile.TemporaryDirectory() as directory:
            window = window_model()
            window.editor = Mock()
            window.editor.edit_modified.return_value = False
            window.composer_focused = Mock(return_value=False)
            window.restore_formats, window.reply_label = Mock(), Mock()
            window.draft_store, window.draft_account = DraftStore(directory), 'linked:a'
            window.attachment = (Path(directory)/'one.jpg', Path(directory)/'two.mp4')
            window._photo_qualities = {('a', 41, None, None): 'hd'}
            window.remote_draft({'text': 'From another device'})
            record = window.draft_store.get('linked:a', 41)
            self.assertEqual(record['files'], [str(p) for p in window.attachment])
            self.assertEqual(record['photo_quality'], 'hd')
            self.assertFalse(record['pending'])

    async def test_send_stays_on_original_account_and_peer_after_main_switch(self):
        window = window_model()
        message = Message(5, 'Me', 'hello', '', True)
        window.backend.send_formatted = AsyncMock(return_value=message)
        other = NS(send_formatted=AsyncMock())
        window.app.demo = False
        window.app.service.current = 'b'
        window.app.service.services['b'] = NS(backend=other)
        window.app.account_event = Mock()
        window.editor, window.send_button, window.attach_button = Mock(), Mock(), Mock()
        window.editor.get.return_value = 'hello'
        window.editor.snapshot_custom.return_value = [(0, 1, 4, 'h')]
        window.reply_to, window.attachment = 3, None
        window.reply = Mock()
        window.persist_draft = Mock()
        queued = []
        window.call = lambda operation, done, failed=None, **kwargs: queued.append((operation, done))
        window.send()
        operation, done = queued.pop()
        done(await operation)
        window.backend.send_formatted.assert_awaited_once_with(41, 'hello', [], [(0, 1, 4, 'h')], path=None, reply_to=3, as_photo=False)
        other.send_formatted.assert_not_called()
        window.app.account_event.assert_called_once_with(('a', 41, message))

    async def test_cancel_before_request_start_closes_nested_coroutine(self):
        window = window_model()
        def submit(coroutine, done, failed):
            return asyncio.create_task(coroutine)
        window.app.worker = NS(submit=submit)
        completed = []
        async def operation():
            completed.append(True)
        coroutine = operation()
        future = window.call(coroutine, Mock())
        future.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.assertEqual(completed, [])
        self.assertIsNone(coroutine.cr_frame)

    async def test_history_refresh_preserves_new_messages_and_deletions_in_flight(self):
        window = window_model()
        old, new = Message(1, 'A', 'old', ''), Message(2, 'A', 'new', '')
        window.backend.history = AsyncMock(return_value=[old])
        queued = []
        window.call = lambda operation, done, failed=None: queued.append((operation, done))
        window.refresh()
        window.receive('a', 41, new)
        window.change('a', 'delete', (41, [1]))
        operation, done = queued.pop()
        done(await operation)
        self.assertEqual([message.id for message in window.messages], [2])

    def test_linked_chat_window_delegates_request_photo_and_custom_emoji_rendering(self):
        backend = NS(history=AsyncMock(return_value=[]), discussion_history=AsyncMock(return_value=[]))
        app = NS(
            root=Mock(), demo=False, preferences=NS(values={}),
            load_photo=Mock(), emoji_art=Mock(), emoji_tint=Mock(return_value=None),
            request_photo=Mock(), fetch_art=Mock(), text_display=lambda t: t,
            open_link=Mock(), preview_dir=Path('/tmp'), show_error=Mock(),
            chats=[], service=NS(labels={'a': 'Demo Account'}, entries={'a': {}}, services={'a': NS(backend=backend)}),
            messages=[], ui_account='a', active=41, worker=NS(submit=lambda coro, *a: (coro.close(), Mock())[1])
        )
        with patch('tkinter.Toplevel') as mock_toplevel, patch('tg_ascii.composer.Composer') as mock_composer, \
             patch('tg_ascii.interface_windows.ttk'):
            mock_toplevel.return_value = Mock()
            mock_composer.return_value = Mock()
            window = LinkedChatWindow(app, 'a', 41)
            self.assertIs(window.request_photo, app.request_photo)
            self.assertIs(window.load_photo, app.load_photo)
            self.assertIs(window.emoji_art, app.emoji_art)
            self.assertIs(window.emoji_tint, app.emoji_tint)


    def test_linked_chat_window_thread_capabilities_and_suppression(self):
        backend = NS(history=AsyncMock(return_value=[]), discussion_history=AsyncMock(return_value=[]))
        app = NS(
            root=Mock(), demo=False, preferences=NS(values={'font_family': 'Menlo', 'font_size': 12, 'theme': 'dark', 'bubbles': True}),
            load_photo=Mock(), emoji_art=Mock(), emoji_tint=Mock(return_value=None),
            request_photo=Mock(), fetch_art=Mock(), text_display=lambda t, *_: t,
            open_link=Mock(), preview_dir=Path('/tmp'), show_error=Mock(),
            chats=[], service=NS(labels={'a': 'Demo'}, entries={'a': {}}, services={'a': NS(backend=backend)}),
            messages=[], ui_account='a', active=41, worker=NS(submit=lambda coro, *a: (coro.close(), Mock())[1]),
            _suppressed_thread_peers={999}
        )
        with patch('tkinter.Toplevel') as mock_toplevel, patch('tg_ascii.composer.Composer') as mock_composer, \
             patch('tg_ascii.bubbles.BubbleView') as mock_bubble, patch('tg_ascii.interface_windows.ttk'):
            mock_toplevel.return_value = Mock(winfo_viewable=Mock(return_value=True))
            mock_composer.return_value = Mock()
            mock_bubble.return_value = Mock()
            thread = {'peer': 999, 'root_id': 10, 'root': Message(10, 'Admin', 'Root post', '')}
            window = LinkedChatWindow(app, 'a', 999, thread=thread)
            # Re-opening unsuppresses
            self.assertNotIn(999, app._suppressed_thread_peers)
            self.assertTrue(window.chat_visible())

            # Attachments permitted for threads
            with patch('tg_ascii.app_dialogs.filedialog.askopenfilenames', return_value=['/tmp/test.jpg']), \
                 patch.object(window, 'prepare_attachments') as mock_prep:
                window.attach()
                mock_prep.assert_called_once_with(['/tmp/test.jpg'])

            # Closing suppresses thread peer
            window.close(destroy=False)
            self.assertIn(999, app._suppressed_thread_peers)

    def test_linked_chat_window_update_appearance(self):
        backend = NS(history=AsyncMock(return_value=[]), discussion_history=AsyncMock(return_value=[]))
        app = NS(
            root=Mock(), demo=False, preferences=NS(values={'font_family': 'Menlo', 'font_size': 14, 'theme': 'dark', 'bubbles': True}),
            load_photo=Mock(), emoji_art=Mock(), emoji_tint=Mock(return_value=None),
            request_photo=Mock(), fetch_art=Mock(), text_display=lambda t, *_: t,
            open_link=Mock(), preview_dir=Path('/tmp'), show_error=Mock(),
            chats=[], service=NS(labels={'a': 'Demo'}, entries={'a': {}}, services={'a': NS(backend=backend)}),
            messages=[], ui_account='a', active=41, worker=NS(submit=lambda coro, *a: (coro.close(), Mock())[1])
        )
        with patch('tkinter.Toplevel') as mock_toplevel, patch('tg_ascii.composer.Composer') as mock_composer, \
             patch('tg_ascii.bubbles.BubbleView') as mock_bubble, patch('tg_ascii.interface_windows.ttk'):
            mock_top = Mock(winfo_viewable=Mock(return_value=True), winfo_exists=Mock(return_value=True))
            mock_toplevel.return_value = mock_top
            mock_comp = Mock()
            mock_composer.return_value = mock_comp
            mock_b = Mock(winfo_exists=Mock(return_value=True))
            mock_bubble.return_value = mock_b
            window = LinkedChatWindow(app, 'a', 41)
            window.request_render = Mock()
            app.preferences.values['font_size'] = 16
            window.update_appearance()
            self.assertEqual(window.font[1], 16)
            window.request_render.assert_called_once()


if __name__ == '__main__':
    unittest.main()
