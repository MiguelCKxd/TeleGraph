"""Layout persistence, nested controls and editing lifecycle regressions."""
from copy import deepcopy
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from tg_ascii.interface_layout import LayoutRuntime
from tg_ascii.interface_store import (
    InterfaceStore, default_layout, rectangle, snapped_rect, tile_rectangles, validate_layout,
)
from tg_ascii.preferences import write_json


def fake_widget(parent=None, rect=(10, 20, 100, 50)):
    widget = Mock()
    widget.master = parent or NS(winfo_width=lambda: 500, winfo_height=lambda: 200)
    widget.winfo_x.return_value, widget.winfo_y.return_value = rect[:2]
    widget.winfo_width.return_value, widget.winfo_height.return_value = rect[2:]
    widget.winfo_manager.return_value = 'pack'
    widget.winfo_exists.return_value = True
    return widget


class StoreTests(unittest.TestCase):
    def test_default_initialization_creates_no_directories_or_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            store = InterfaceStore(directory)
            self.assertEqual(store.document, default_layout())
            self.assertEqual(list(Path(directory).iterdir()), [])
            with patch('tg_ascii.interface_store.read_json') as read:
                self.assertEqual(InterfaceStore(directory, demo=True).document, default_layout())
            read.assert_not_called()

    def test_validation_sanitizes_coordinates_and_never_keeps_executable_fields(self):
        invalid = {'schema': 1, 'enabled': 'yes', 'columns': math.inf, 'gap': -1,
                   'items': [{'id': '../x', 'kind': 'button'}, {'id': 'a', 'kind': 'button',
                             'text': 'Hi\x00👍', 'rect': [math.nan, -2, 2, 0], 'script': 'danger'},
                             {'id': 'a', 'kind': 'button'}, {'id': 'b', 'kind': 'python'}],
                   'overrides': {'custom/a/0': {'rect': [0, 0, .4, .4], 'front': True, 'script': 'danger'}},
                   'appearance': {'theme': 'light', 'api_hash': 'secret', 'text_border_width': 2},
                   'motion': {'enabled': False}}
        result = validate_layout(invalid)
        self.assertFalse(result['enabled'])
        self.assertEqual((result['columns'], result['gap']), (12, 4))
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['text'], 'Hi👍')
        self.assertNotIn('script', result['items'][0])
        self.assertNotIn('script', result['overrides']['custom/a/0'])
        self.assertNotIn('api_hash', result['appearance'])
        self.assertEqual(result['appearance']['text_border_width'], 2)
        self.assertFalse(result['motion']['enabled'])
        with self.assertRaises(ValueError):
            validate_layout({'schema': 999})

    def test_rectangles_remain_relative_and_tile_without_overlap(self):
        self.assertEqual(rectangle([.9, .9, .5, .5]), [.9, .9, 1-.9, 1-.9])
        self.assertEqual(snapped_rect([.13, .21, .30, .20], 4, 4), [.25, .25, .25, .25])
        self.assertEqual(tile_rectangles(4, 2), [[0, 0, .5, .5], [.5, 0, .5, .5], [0, .5, .5, .5], [.5, .5, .5, .5]])
        for invalid in (0, 101, True, '2'):
            with self.assertRaises(ValueError):
                tile_rectangles(2, invalid)

    def test_huge_json_numbers_cannot_crash_startup_or_imported_design(self):
        huge = 10**400
        document = {'schema': 1, 'enabled': True, 'name': 'Recoverable',
            'columns': huge, 'rows': -huge, 'gap': huge,
            'items': [{'id': 'button', 'kind': 'button', 'rect': [huge, -huge, huge, huge]}],
            'appearance': {'font_size': huge, 'text_border_width': huge, 'menu_shadow_size': huge},
            'motion': {'events': {'swipe_reply': {'duration_ms': huge, 'distance': huge, 'threshold': huge}}}}
        with tempfile.TemporaryDirectory() as directory:
            active = Path(directory)/'interface'/'active.json'
            write_json(active, document)
            store = InterfaceStore(directory)
            checked = store.document
            self.assertEqual(checked['name'], 'Recoverable')
            self.assertEqual((checked['columns'], checked['rows'], checked['gap']), (12, 12, 4))
            self.assertEqual(checked['items'][0]['rect'], [.05, .05, .2, .2])
            self.assertEqual(checked['appearance'], {'font_size': 12, 'text_border_width': 0, 'menu_shadow_size': 0})
            self.assertEqual(checked['motion']['events']['swipe_reply']['duration_ms'], 96)
            self.assertEqual(checked['motion']['events']['swipe_reply']['distance'], 80)
            self.assertEqual(checked['motion']['events']['swipe_reply']['threshold'], 65)
            self.assertEqual(store.load(active), checked)
            store.commit(default_layout())
            self.assertEqual(InterfaceStore(directory).document, default_layout())

    def test_undo_redo_and_restart_restore_exact_design(self):
        with tempfile.TemporaryDirectory() as directory:
            store = InterfaceStore(directory)
            document = {**default_layout(), 'enabled': True, 'name': 'Wide 👍', 'columns': 5}
            store.commit(document)
            self.assertEqual(InterfaceStore(directory).document, store.document)
            self.assertTrue(store.undo())
            self.assertEqual(store.document, default_layout())
            self.assertTrue(store.redo())
            self.assertEqual(store.document['name'], 'Wide 👍')
            previous = deepcopy(store.document)
            with patch('tg_ascii.interface_store.write_json', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    store.undo()
            self.assertEqual(store.document, previous)
            self.assertTrue(store.undo())
            store.commit({**default_layout(), 'gap': 8})
            self.assertFalse(store.redo())

    def test_oversize_generated_design_never_overwrites_readable_active_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            store = InterfaceStore(directory)
            store.commit({**default_layout(), 'enabled': True, 'name': 'Keep this design'})
            path = store.root/'active.json'
            previous_bytes = path.read_bytes()
            previous_document = deepcopy(store.document)
            previous_undo = deepcopy(store.undo_stack)
            oversized = {**default_layout(), 'enabled': True, 'items': [
                {'id': str(index), 'kind': 'label', 'text': 'x'*240} for index in range(6000)]}
            with self.assertRaisesRegex(ValueError, 'No changes were saved'):
                store.commit(oversized)
            self.assertEqual(path.read_bytes(), previous_bytes)
            self.assertEqual(store.document, previous_document)
            self.assertEqual(store.undo_stack, previous_undo)
            self.assertEqual(InterfaceStore(directory).document, previous_document)

    def test_oversize_profile_and_archive_fail_without_unreadable_files(self):
        with tempfile.TemporaryDirectory() as directory:
            store = InterfaceStore(directory, demo=True)
            store.commit({**default_layout(), 'items': [
                {'id': str(index), 'kind': 'label', 'text': '😀'*240} for index in range(2000)]})
            for save in (lambda: store.save_profile('Big', {}), store.archive):
                with self.assertRaisesRegex(ValueError, 'No changes were saved'):
                    save()
            self.assertEqual(store.profiles(), [])
            self.assertEqual(store.profiles(history=True), [])
            self.assertEqual(len(store.document['items']), 2000)

    def test_undo_memory_is_bounded_without_limiting_layout_items(self):
        with tempfile.TemporaryDirectory() as directory:
            store = InterfaceStore(directory, demo=True)
            for number in range(120):
                store.commit({**default_layout(), 'name': str(number)})
            self.assertEqual(len(store.undo_stack), 100)
            self.assertEqual(store.undo_stack[0]['name'], '19')
            self.assertTrue(store.undo())
            self.assertEqual(store.document['name'], '118')
            self.assertTrue(store.redo())
            self.assertEqual(store.document['name'], '119')

    def test_profiles_archive_motion_and_restore_without_account_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            store = InterfaceStore(directory)
            store.commit({**default_layout(), 'enabled': True, 'name': 'Personal'})
            path = store.save_profile('My style', {'theme': 'light', 'api_hash': 'secret'}, {'enabled': False})
            archived = store.archive()
            store.commit(default_layout())
            profile = store.load(path)
            self.assertEqual(profile['name'], 'My style')
            self.assertEqual(profile['appearance'], {'theme': 'light'})
            self.assertFalse(profile['motion']['enabled'])
            self.assertEqual(store.load(archived)['name'], 'Personal')

    def test_resources_cannot_escape_customization_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            store = InterfaceStore(directory)
            for path in ('..', '../../sessions.sqlite', str(Path(directory) / 'outside.png'), ''):
                with self.assertRaises(ValueError):
                    store.resource(path)
            self.assertTrue(store.resource('images/picture.png').is_relative_to((store.root/'resources').resolve()))

    def test_import_resource_handles_a_resolved_customization_root(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = base/'real'
            target.mkdir()
            link = base/'link'
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError:
                self.skipTest('Directory symlinks are unavailable on this platform')
            source = base/'picture.png'
            source.write_bytes(b'fixture')
            store = InterfaceStore(link, demo=True)
            resource = store.import_resource(source)
            self.assertTrue(resource.startswith('images/'))
            self.assertEqual(store.resource(resource).read_bytes(), b'fixture')

    def test_recoverable_trash_never_overwrites_resources_or_removes_core_files(self):
        with tempfile.TemporaryDirectory() as directory:
            store = InterfaceStore(directory)
            store.ensure()
            picture = store.resource('images/a.png')
            picture.write_bytes(b'original')
            entry = store.trash(picture)
            self.assertFalse(picture.exists())
            picture.write_bytes(b'new')
            with self.assertRaises(FileExistsError):
                store.restore(entry)
            self.assertEqual(picture.read_bytes(), b'new')
            picture.unlink()
            self.assertEqual(store.restore(entry).read_bytes(), b'original')
            self.assertFalse(entry.exists())
            core = store.root / 'active.json'
            write_json(core, default_layout())
            with self.assertRaises(ValueError):
                store.trash(core)
            self.assertTrue(core.exists())

    def test_tampered_trash_metadata_cannot_restore_outside_resource_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            store = InterfaceStore(directory)
            store.ensure()
            entry = store.root/'trash'/'entry'
            entry.mkdir()
            (entry/'content').write_bytes(b'resource')
            for path in ('../../escape', 'resources/../../escape', 'active.json', '/absolute', ''):
                write_json(entry/'metadata.json', {'path': path})
                with self.assertRaises(ValueError):
                    store.restore(entry)
                self.assertTrue((entry/'content').exists())
            with self.assertRaises(ValueError):
                store.restore(store.root/'resources')


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = InterfaceStore(self.directory.name, demo=True)
        self.app = NS(rebuild_screen=Mock(), closed=False, closing=False, root=Mock())
        self.runtime = LayoutRuntime(self.app, self.store)
        document = default_layout()
        document['items'] = [{'id': 'panel', 'kind': 'panel', 'text': 'Actions',
                              'rect': [.2, .2, .3, .3], 'entries': [{'text': 'Send', 'action': 'send'}]}]
        self.store.commit(document)

    def test_nested_panel_controls_move_hide_and_duplicate_independently(self):
        panel = fake_widget()
        first, second = fake_widget(panel), fake_widget(panel)
        self.runtime.widgets = {'custom/panel': panel, 'custom/panel/0': first, 'custom/panel/1': second}
        self.runtime.names = {'custom/panel': 'Actions', 'custom/panel/0': 'Send', 'custom/panel/1': 'Attach'}
        original_rect = self.store.document['items'][0]['rect'][:]
        self.runtime.move('custom/panel/0', [.1, .2, .4, .3])
        self.assertEqual(self.store.document['items'][0]['rect'], original_rect)
        self.assertEqual(self.store.document['overrides']['custom/panel/0']['rect'], [.1, .2, .4, .3])
        self.assertIn('custom/panel/1', self.store.document['overrides'])
        duplicate = self.runtime.duplicate('custom/panel/0')
        item = next(item for item in self.store.document['items'] if duplicate == 'custom/'+item['id'])
        self.assertEqual(item['action'], 'widget:custom/panel/0')
        self.runtime.hide('custom/panel/0')
        self.assertTrue(self.store.document['overrides']['custom/panel/0']['hidden'])
        self.assertFalse(self.store.document['items'][0]['hidden'])

    def test_duplicate_panel_preserves_customized_children(self):
        document = deepcopy(self.store.document)
        document['overrides']['custom/panel/0'] = {'text': 'Write', 'rect': [.2, .1, .4, .5], 'hidden': True}
        self.store.commit(document)
        key = self.runtime.duplicate('custom/panel')
        self.assertEqual(self.store.document['overrides'][key+'/0'], self.store.document['overrides']['custom/panel/0'])
        self.assertEqual(len(self.store.document['items']), 2)

    def test_duplicate_action_survives_hiding_original_custom_panel(self):
        from contextlib import ExitStack
        names = ('open_fixed_settings', 'open_customization', 'refresh', 'saved_messages', 'open_contacts',
                 'folder_dialog', 'telegram_picker', 'pick_attachment', 'send', 'open_chat_window')
        with ExitStack() as stack:
            for name in names:
                stack.enter_context(patch.object(self.app, name, Mock(), create=True))
            self.runtime.invoke('widget:custom/panel/0')
            self.app.send.assert_called_once()
            self.runtime.invoke('refresh')
            self.app.refresh.assert_called_once_with(reconnect=True)

    def test_tiles_preserve_panel_root_and_use_child_overrides(self):
        panel = fake_widget()
        self.runtime.widgets = {'custom/panel': panel, 'custom/panel/0': fake_widget(panel), 'custom/panel/1': fake_widget(panel)}
        self.runtime.selected = 'custom/panel/0'
        self.runtime.tile(2)
        self.assertEqual(self.store.document['overrides']['custom/panel/0']['rect'], [0, 0, .5, 1])
        self.assertEqual(self.store.document['overrides']['custom/panel/1']['rect'], [.5, 0, .5, 1])
        self.assertEqual(self.store.document['items'][0]['rect'], [.2, .2, .3, .3])

    def test_geometry_guards_keep_hidden_or_moved_widgets_from_native_repacking(self):
        widget = NS(pack=Mock(), grid=Mock(), place=Mock())
        original = widget.pack
        self.runtime.guard_geometry(widget, {'hidden': True})
        widget.pack(fill='x')
        original.assert_not_called()
        self.runtime.guard_geometry(widget, {})
        widget.pack(fill='x')
        original.assert_called_once_with(fill='x')
        self.runtime.guard_geometry(widget, {'rect': [0, 0, .2, .2]})
        self.runtime.place(widget, [0, 0, .2, .2])
        widget._layout_geometry['place'].assert_called_once()

    def test_editing_pauses_actions_and_cyclic_duplicates_do_not_recurse(self):
        widget = fake_widget()
        self.runtime.widgets['custom/panel/0'] = widget
        widget.invoke.side_effect = lambda: self.runtime.invoke('widget:custom/panel/0')
        self.runtime.editing = True
        self.runtime.invoke('widget:custom/panel/0')
        widget.invoke.assert_not_called()
        self.runtime.editing = False
        self.runtime.invoke('widget:custom/panel/0')
        widget.invoke.assert_called_once()
        self.assertEqual(self.runtime._invoking, set())

    def test_image_resize_coalesces_events_and_detach_cancels_callbacks(self):
        widget = fake_widget()
        widget._layout_photo_size = None
        widget.after.side_effect = ('timer1', 'timer2', 'timer3')
        self.runtime.resize_image(widget, 'images/a.png', 300, 200)
        self.runtime.resize_image(widget, 'images/a.png', 600, 300)
        widget.after_cancel.assert_called_once_with('timer1')
        callback = widget.after.call_args.args[1]
        self.app.request_photo = Mock()
        with patch('tg_ascii.motion.get_motion', return_value={'enabled': False}):
            callback()
        request = self.app.request_photo.call_args
        self.assertEqual(request.args[:2], (self.store.resource('images/a.png'), (592, 292)))
        self.assertFalse(request.kwargs['enabled'])
        self.assertIs(request.kwargs['owner'], widget)
        widget.configure.assert_not_called()
        request.args[2]('photo')
        widget.configure.assert_called_once_with(image='photo', compound='center')
        self.runtime.resize_image(widget, 'images/a.png', 600, 300)
        self.assertEqual(widget.after.call_count, 2)
        self.runtime.resize_image(widget, 'images/a.png', 700, 300)
        self.runtime.detach()
        widget.after_cancel.assert_called_with('timer3')
        self.assertEqual(self.runtime._image_jobs, {})


if __name__ == '__main__':
    unittest.main()
