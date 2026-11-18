"""Resource regressions for optional styling, layout history and linked views."""
import asyncio
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from telethon import types

from tg_ascii.backend import Message
from tg_ascii.interface_background import InterfaceBackground, request_chat_background, reuse_canvas_background
from tg_ascii.interface_editor import InterfaceEditor
from tg_ascii.interface_layout import LayoutRuntime
from tg_ascii.interface_store import InterfaceStore, default_layout
from tg_ascii.interface_windows import LinkedChatWindow
from tg_ascii.preferences import DEFAULTS
from tg_ascii.visual_effects import _wrapped_lines, apply_text_effects


class LayoutWorkTests(unittest.TestCase):
    def test_default_layout_does_not_visit_native_widgets_until_editor_is_needed(self):
        runtime = LayoutRuntime(NS(), NS(document=default_layout()))
        runtime.attach()  # No root/control handles are required in this path.
        self.assertEqual(runtime.widgets, {})
        widget = Mock()
        runtime.widgets['any'] = widget
        runtime.set_editing(False)
        widget.bindtags.assert_not_called()

    def test_noop_change_does_not_rebuild_or_save_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            store = InterfaceStore(directory, demo=True)
            app = NS(rebuild_screen=Mock())
            runtime = LayoutRuntime(app, store)
            runtime.change(default_layout())
            runtime.change(deepcopy(store.document))
            self.assertEqual(len(store.undo_stack), 1)
            app.rebuild_screen.assert_called_once()

    def test_layout_history_shares_unchanged_controls_but_edits_and_undo_stay_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            store = InterfaceStore(directory, demo=True)
            store.commit({**default_layout(), 'items': [{'id': str(i), 'kind': 'label', 'text': 'unchanged'} for i in range(100)]})
            for step in range(40):
                changed = deepcopy(store.document)
                changed['items'][0]['text'] = str(step)
                store.commit(changed)
                changed['items'][1]['text'] = 'caller mutated its own copy'
            snapshots = [*store.undo_stack[1:], store.document]
            # Forty changes should not retain forty copies of 99 untouched controls.
            objects = {id(item) for snapshot in snapshots for item in snapshot['items']}
            self.assertLess(len(objects), 150)
            self.assertEqual(store.document['items'][1]['text'], 'unchanged')
            self.assertTrue(store.undo())
            self.assertEqual(store.document['items'][0]['text'], '38')
            self.assertTrue(store.redo())
            self.assertEqual(store.document['items'][0]['text'], '39')

    def test_position_only_editor_refresh_preserves_tree_rows(self):
        editor = object.__new__(InterfaceEditor)
        editor.items = Mock()
        editor.runtime = NS(names={'a': 'A', 'b': 'B'}, selected=None, widgets={})
        editor.populate()
        editor.items.reset_mock()
        editor.populate()
        editor.items.insert.assert_not_called()
        editor.items.delete.assert_not_called()
        editor.items.item.assert_not_called()
        editor.items.set_children.assert_not_called()
        editor.runtime.names = {'a': 'Renamed', 'b': 'B'}
        editor.populate()
        editor.items.item.assert_called_once_with('a', text='Renamed  [a]')
        editor.items.insert.assert_not_called()

    def test_file_lists_are_not_scanned_before_the_file_tab_exists(self):
        editor = object.__new__(InterfaceEditor)
        editor.store = Mock()
        editor.load_files()
        editor.store.ensure.assert_not_called()

    def test_old_image_decode_cannot_replace_latest_size_and_returning_size_cancels_pending_work(self):
        with tempfile.TemporaryDirectory() as directory:
            app = NS(request_photo=Mock())
            runtime = LayoutRuntime(app, InterfaceStore(directory, demo=True))
            widget = Mock()
            widget._layout_photo_size = None
            widget.winfo_exists.return_value = True
            widget.after.side_effect = ('timer1', 'timer2', 'timer3')
            with patch('tg_ascii.motion.get_motion', return_value={'enabled': True}):
                runtime.resize_image(widget, 'images/a.png', 300, 200)
                widget.after.call_args.args[1]()
                first = app.request_photo.call_args
                runtime.resize_image(widget, 'images/a.png', 500, 200)
                widget.after.call_args.args[1]()
                second = app.request_photo.call_args
            self.assertFalse(first.kwargs['valid']())
            first.args[2]('old')
            widget.configure.assert_not_called()
            second.args[2]('current')
            widget.configure.assert_called_once_with(image='current', compound='center')
            runtime.resize_image(widget, 'images/a.png', 600, 200)
            pending = widget.after.call_args.args[1]
            runtime.resize_image(widget, 'images/a.png', 500, 200)
            widget.after_cancel.assert_called_with('timer3')
            pending()
            self.assertEqual(app.request_photo.call_count, 2)
            self.assertEqual(runtime._image_jobs, {})


class CosmeticWorkTests(unittest.TestCase):
    def background(self):
        root = Mock()
        root.winfo_exists.return_value = True
        root.winfo_width.return_value = root.winfo_height.return_value = 200
        app = NS(root=root, preferences=NS(values={'interface_background': 'first.png'}), worker=Mock())
        return app, InterfaceBackground(app)

    def test_interface_background_coalesces_sizes_and_keeps_old_frame_until_latest_fit_is_ready(self):
        app, painter = self.background()
        old_frame, source, first, final = object(), object(), object(), object()
        painter.picture, painter.signature = old_frame, ('previous', 200, 200, '#000000')
        self.assertIs(painter.fitted_picture(), old_frame)
        for width in range(201, 301):
            app.root.winfo_width.return_value = width
            with patch('tg_ascii.interface_background.ttk.Style') as style:
                painter.paint()
                style.assert_not_called()
        app.worker.submit.assert_called_once()
        operation, loaded, _ = app.worker.submit.call_args.args
        with patch('tg_ascii.interface_background._interface_picture', return_value=(source, first)) as prepare:
            loaded(asyncio.run(operation))
            self.assertFalse(prepare.call_args.args[2])
        self.assertIs(painter.picture, old_frame)
        self.assertEqual(app.worker.submit.call_count, 2)
        operation, loaded, _ = app.worker.submit.call_args.args
        with patch('tg_ascii.interface_background._interface_picture', return_value=(source, final)) as prepare:
            loaded(asyncio.run(operation))
            self.assertIs(prepare.call_args.args[1], source)
            self.assertTrue(prepare.call_args.args[2])
            self.assertEqual(prepare.call_args.args[0][1:3], (300, 200))
        self.assertIs(painter.fitted_picture(), final)
        self.assertFalse(painter._picture_pending)
        self.assertEqual(app.worker.submit.call_count, 2)

    def test_interface_background_changed_path_never_reuses_previous_source_or_publishes_it(self):
        app, painter = self.background()
        painter.fitted_picture()
        operation, loaded, _ = app.worker.submit.call_args.args
        self.addCleanup(operation.close)
        app.preferences.values['interface_background'] = 'second.png'
        painter.fitted_picture()
        loaded((object(), object()))
        self.assertIsNone(painter.source)
        self.assertIsNone(painter.picture)
        operation, loaded, _ = app.worker.submit.call_args.args
        with patch('tg_ascii.interface_background._interface_picture', return_value=(None, None)) as prepare:
            loaded(asyncio.run(operation))
            self.assertEqual(prepare.call_args.args[0][0], 'second.png')
            self.assertIsNone(prepare.call_args.args[1])
            self.assertFalse(prepare.call_args.args[2])

    def test_disabling_interface_background_while_loading_does_not_restore_it_later(self):
        app, painter = self.background()
        painter.fitted_picture()
        operation, loaded, _ = app.worker.submit.call_args.args
        self.addCleanup(operation.close)
        app.preferences.values['interface_background'] = ''
        self.assertIsNone(painter.fitted_picture())
        loaded((object(), object()))
        self.assertIsNone(painter.picture)
        self.assertIsNone(painter.source)
        self.assertIsNone(painter.signature)
        self.assertFalse(painter._picture_pending)
        app.worker.submit.assert_called_once()

    def test_reused_wallpaper_is_lowered_below_new_incremental_bubbles(self):
        canvas = Mock()
        canvas._wallpaper_key = ('same',)
        canvas.wallpaper = object()
        canvas.find_withtag.return_value = (1,)
        self.assertTrue(reuse_canvas_background(canvas, ('same',)))
        canvas.create_image.assert_not_called()
        canvas.tag_lower.assert_called_once_with('wallpaper')

    def test_wallpaper_resizes_keep_one_crop_running_and_only_latest_geometry_is_published(self):
        app = NS(root=Mock(), wallpaper_path='fixture.png', worker=Mock())
        canvas = Mock()
        canvas._wallpaper_key = None
        canvas.winfo_exists.return_value = True
        first = ('chat', 'fixture.png', 1, 100, 100)
        request_chat_background(app, canvas, first)
        operation, loaded, _ = app.worker.submit.call_args.args
        self.addCleanup(operation.close)
        for size in range(101, 201):
            request_chat_background(app, canvas, ('chat', 'fixture.png', 1, size, size))
        app.worker.submit.assert_called_once()
        canvas.winfo_width.return_value = canvas.winfo_height.return_value = 200
        with patch('tg_ascii.interface_background.canvas_background') as draw:
            loaded(object())
            draw.assert_not_called()
            self.assertEqual(app.worker.submit.call_count, 2)
            operation, final_loaded, _ = app.worker.submit.call_args.args
            self.addCleanup(operation.close)
            picture = object()
            final_loaded(picture)
            draw.assert_called_once_with(canvas, picture, app.root, ('chat', 'fixture.png', 1, 200, 200))

    def test_wallpaper_work_ignores_closed_view_or_changed_chat_and_failed_crop_does_not_retry_on_every_render(self):
        for changed in ('closed', 'chat', 'failed'):
            app = NS(root=Mock(), wallpaper_path='fixture.png', worker=Mock())
            canvas = Mock()
            canvas._wallpaper_key = None
            canvas.winfo_exists.return_value = True
            canvas.winfo_width.return_value = canvas.winfo_height.return_value = 100
            key = ('chat', 'fixture.png', 1, 100, 100)
            request_chat_background(app, canvas, key)
            operation, loaded, _ = app.worker.submit.call_args.args
            self.addCleanup(operation.close)
            if changed == 'closed': canvas.winfo_exists.return_value = False
            elif changed == 'chat': canvas._wallpaper_requested = None
            with patch('tg_ascii.interface_background.canvas_background') as draw:
                loaded(None if changed == 'failed' else object())
                draw.assert_not_called()
            if changed == 'failed':
                for _ in range(20): request_chat_background(app, canvas, key)
            app.worker.submit.assert_called_once()

    def test_disabled_background_and_underline_do_not_query_tcl_on_child_events(self):
        app = NS(root=Mock(), preferences=NS(values={'interface_background': ''}))
        painter = InterfaceBackground(app)
        widget = Mock()
        for _ in range(100):
            painter.schedule(NS(widget=widget))
        widget.winfo_toplevel.assert_not_called()
        app.root.after.assert_not_called()
        with patch('tkinter.font.nametofont') as font:
            apply_text_effects(NS(), DEFAULTS)
        font.assert_not_called()

    def test_background_retires_a_photo_without_retaining_its_old_pixels_or_widget(self):
        app = NS(root=Mock(), preferences=NS(values={'interface_background': ''}))
        painter = InterfaceBackground(app)
        widget, photo = Mock(), Mock()
        widget.winfo_exists.return_value = False
        painter.retire(widget, ('Reusable.TFrame', photo, (900, 700), 'TFrame'))
        photo.configure.assert_called_once_with(width=1, height=1)
        self.assertEqual(painter.free, [('Reusable.TFrame', photo)])
        widget.configure.assert_not_called()

    def test_long_underline_wrap_measures_bounded_prefixes_not_every_remaining_tail(self):
        text = 'abcdefghij ' * 500
        work = []
        def measure(value):
            work.append(len(value))
            return len(value)
        lines = _wrapped_lines(text, measure, 24)
        self.assertEqual(' '.join(line for line in lines if line).strip(), text.strip())
        self.assertLess(sum(work), len(text) * 30)
        self.assertLess(max(work), 65)

    def test_profile_noop_preserves_cache_without_opening_or_rewriting_disk(self):
        from tg_ascii.profile_customization import save_design
        birthday = {'day': 1, 'month': 1, 'year': None}
        backend = NS(local_profile_design={'birthday': birthday}, profile_design_path=Path('/unused.json'))
        with patch('tg_ascii.profile_customization.read_json') as read, patch('tg_ascii.profile_customization.write_json') as write:
            save_design(backend, 'birthday', birthday)
            save_design(backend, 'emoji_status', None, remove=True)
        read.assert_not_called()
        write.assert_not_called()

    def test_profile_photo_change_invalidates_disk_preview_and_ready_marker_only_for_self(self):
        from tg_ascii.profile_customization import refresh_profile_photos
        app = NS(ui_account='a', avatar_images={('a', 10, 'avatar'): 'self', ('a', 20, 'avatar'): 'other'},
            preview_cache={('a', 10, 'avatar'): 'self-path', ('a', 20, 'avatar'): 'other-path'},
            _avatar_status={('a', 10): 'ready', ('a', 20): 'ready'}, load_avatars=Mock())
        refresh_profile_photos(app, 'a', 10)
        self.assertEqual(app.avatar_images, {('a', 20, 'avatar'): 'other'})
        self.assertEqual(app.preview_cache, {('a', 20, 'avatar'): 'other-path'})
        self.assertEqual(app._avatar_status, {('a', 20): 'ready'})
        app.load_avatars.assert_called_once()


class LinkedViewWorkTests(unittest.TestCase):
    def model(self):
        window = object.__new__(LinkedChatWindow)
        window.account, window.peer, window.closed = 'a', 41, False
        window.loading = False
        window.history_changes = []
        window.messages = [Message(1, 'A', 'sent', '', outgoing=True)]
        window.history = Mock()
        window.history.yview.return_value = (0., 1.)
        window.request_render = Mock()
        return window

    def test_duplicate_messages_and_read_receipts_do_not_redraw_unchanged_history(self):
        window = self.model()
        window.receive('a', 41, deepcopy(window.messages[0]))
        window.request_render.assert_not_called()
        window.change('a', 'read', (41, 1))
        window.request_render.assert_called_once()
        self.assertTrue(window.messages[0].read)
        window.request_render.reset_mock()
        for _ in range(50):
            window.change('a', 'read', (41, 1))
        window.request_render.assert_not_called()

    def test_many_custom_emoji_in_one_message_decode_entities_only_once_for_fallbacks(self):
        from tg_ascii.message_tools import entity_spans
        window = self.model()
        text = '😀'*20
        window.messages = [Message(1, 'A', text, '', raw_text=text,
            entities=tuple(types.MessageEntityCustomEmoji(index*2, 2, 100+index) for index in range(20)))]
        window.app = NS(preferences=NS(values=DEFAULTS), text_display=lambda value: value)
        window.visible = Mock(return_value=True)
        window.acknowledge = Mock()
        window.generation, window.follow = 0, False
        window.history.index.return_value = '1.0'
        window.history.mark_names.return_value = ()
        window.history.tag_names.return_value = ()
        with patch('tg_ascii.message_tools.entity_spans', wraps=entity_spans) as decode:
            window.render()
        # One segmentation pass + one fallback map, independent of emoji count.
        self.assertEqual(decode.call_count, 2)
        self.assertEqual(window.history.insert_custom.call_count, 20)

    def test_photo_decode_is_async_and_stale_result_cannot_change_another_render(self):
        window = self.model()
        window.app = NS(request_photo=Mock())
        window.window = Mock()
        window.valid = Mock(return_value=True)
        window.generation, window.photos = 7, []
        window.history.mark_names.return_value = ('media_1',)
        window.insert_photo('/unused.png', 'media_1', 'msg_1', 7, (280, 180))
        requested = window.app.request_photo.call_args
        self.assertEqual(requested.args[:2], ('/unused.png', (280, 180)))
        self.assertIs(requested.kwargs['owner'], window.window)
        window.history.image_create.assert_not_called()
        window.generation = 8
        requested.args[2](object())
        self.assertFalse(requested.kwargs['valid']())
        self.assertEqual(window.photos, [])
        window.history.image_create.assert_not_called()
        window.generation = 7
        photo = object()
        requested.args[2](photo)
        self.assertEqual(window.photos, [photo])
        window.history.image_create.assert_called_once_with('media_1', image=photo, align='center')


if __name__ == '__main__':
    unittest.main()
