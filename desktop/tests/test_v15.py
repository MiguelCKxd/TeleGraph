"""1.4.1 / 1.5: offline robustness, send queue, read receipts, shortcuts,
line breaking, resource profiles and startup preparation."""
import asyncio
import json
import os
from pathlib import Path
import queue
import tempfile
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

from telethon import errors
from telethon.tl import functions, types

from tg_ascii import composer_keys, line_breaking, outbox, read_visibility, resources
from tg_ascii.desktop import AsyncWorker, Desktop, TransportReset, transport_safe
from tg_ascii.preferences import Preferences


class TransportCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_from_inside_becomes_an_error_but_real_cancel_propagates(self):
        loop = asyncio.get_running_loop()
        inner = loop.create_future()

        async def request():
            return await inner  # Telethon cancels this future on disconnect.
        task = asyncio.ensure_future(transport_safe(request()))
        await asyncio.sleep(0)
        inner.cancel()
        with self.assertRaises(TransportReset):
            await task
        blocked = asyncio.ensure_future(transport_safe(asyncio.sleep(10)))
        await asyncio.sleep(0)
        blocked.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await blocked

    def test_worker_delivers_failure_when_the_connection_reset_cancels_a_request(self):
        worker = AsyncWorker()
        try:
            async def request():
                future = asyncio.get_running_loop().create_future()
                asyncio.get_running_loop().call_later(0.01, future.cancel)
                return await future
            worker.submit(request(), lambda _: None, lambda _: None)
            callback, value = worker.events.get(timeout=3)
            self.assertIsInstance(value, TransportReset)  # Before 1.4.1: nothing, UI locked forever.
        finally:
            worker.stop()


class BusyTokenTests(unittest.TestCase):
    def make(self):
        app = object.__new__(Desktop)
        app.closed = app.closing = False
        app.status = Mock()
        app.update_controls = Mock()
        app.root = Mock()
        app.service = NS(failures={})
        app.ui_account = 'a'
        submitted = []
        app.worker = NS(submit=lambda coroutine, done, failed: (coroutine.close(), submitted.append((done, failed)))[1] or None,
                        events=queue.SimpleQueue(), _stopping=False)
        return app, submitted

    def test_one_call_finishing_does_not_unlock_another_and_grace_releases(self):
        app, submitted = self.make()

        async def never():
            await asyncio.sleep(3600)
        app.call(never(), lambda _: None, 'one')
        app.call(never(), lambda _: None, 'two')
        self.assertTrue(app.busy)
        submitted[0][0](None)
        self.assertTrue(app.busy)  # The second operation still holds its token.
        grace = app.root.after.call_args_list[1].args[1]
        grace()
        self.assertFalse(app.busy)
        submitted[1][0](None)  # A late completion still runs and stays unlocked.
        self.assertFalse(app.busy)


class OutboxTests(unittest.IsolatedAsyncioTestCase):
    def test_retries_reuse_the_same_random_ids(self):
        outbox.install()
        ids = []

        async def build():
            return functions.messages.SendMessageRequest(types.InputPeerSelf(), 'hola').random_id
        first = asyncio.run(outbox.with_random_ids(ids, build()))
        second = asyncio.run(outbox.with_random_ids(ids, build()))
        self.assertEqual(first, second)
        self.assertEqual(ids, [first])
        other = functions.messages.SendMessageRequest(types.InputPeerSelf(), 'hola').random_id
        self.assertNotEqual(other, first)  # Outside the queue nothing changes.

    def test_only_transport_problems_are_retried_alone(self):
        self.assertTrue(outbox.transient(ConnectionError()))
        self.assertTrue(outbox.transient(TimeoutError()))
        self.assertTrue(outbox.transient(TransportReset()))
        self.assertTrue(outbox.transient(errors.FloodWaitError(None, capture=3)))
        self.assertFalse(outbox.transient(errors.ChatWriteForbiddenError(None)))
        self.assertFalse(outbox.transient(ValueError('too long')))

    async def test_build_operation_matches_the_old_send_paths(self):
        backend = Mock()
        item = outbox.Pending('a', 5, 'hi')
        outbox.build_operation(backend, item)
        backend.send.assert_called_once_with(5, 'hi')
        item = outbox.Pending('a', 5, 'hi', format_spans=[[0, 2, 'bold', None]], reply_to=9)
        outbox.build_operation(backend, item)
        self.assertEqual(backend.send_formatted.call_args.args[2], [(0, 2, 'bold', None)])
        self.assertEqual(backend.send_formatted.call_args.kwargs['reply_to'], 9)
        item = outbox.Pending('a', 5, 'cap', paths=['/x/a.txt', '/x/b.txt'])
        outbox.build_operation(backend, item)
        backend.send_batch.assert_called_once()

    def test_queue_survives_a_restart_with_its_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            app = NS(service=NS(root=folder), demo=False, root=Mock(), closed=False, closing=False)
            box = outbox.Outbox(app)
            item = outbox.Pending('a', 7, 'sin red', random_ids=[123])
            box.items.append(item)
            box.save()
            if os.name != 'nt':  # POSIX permissions; Windows uses the profile ACL.
                self.assertEqual(oct(Path(folder, 'outbox.json').stat().st_mode & 0o777), '0o600')
            again = outbox.Outbox(app)
            self.assertEqual([(i.peer, i.text, i.random_ids, i.state) for i in again.items], [(7, 'sin red', [123], 'waiting')])
            again.items.clear()
            again.save()
            self.assertFalse(Path(folder, 'outbox.json').exists())


class ShortcutTests(unittest.TestCase):
    def test_automatic_mode_follows_enter_sends(self):
        on, off = {'enter_send': True}, {'enter_send': False}
        self.assertEqual(composer_keys.action(on, 'Return'), 'send')
        self.assertEqual(composer_keys.action(on, composer_keys.MOD), 'newline')
        self.assertEqual(composer_keys.action(on, 'Shift+Return'), 'newline')
        self.assertEqual(composer_keys.action(off, 'Return'), 'newline')
        self.assertEqual(composer_keys.action(off, composer_keys.MOD), 'send')

    def test_custom_shortcuts(self):
        values = {'enter_send': True, 'shortcut_send': 'Alt+Return', 'shortcut_newline': 'Return'}
        self.assertEqual(composer_keys.action(values, 'Alt+Return'), 'send')
        self.assertEqual(composer_keys.action(values, 'Return'), 'newline')
        self.assertEqual(composer_keys.action(values, 'Shift+Return'), 'newline')

    def test_preferences_accept_only_known_choices(self):
        values = Preferences.validated({'shortcut_send': 'Return', 'line_breaking': 'syllable',
                                        'resource_cpu': 'unlimited', 'resource_ram': 'huge', 'preload_startup': True})
        self.assertEqual((values['shortcut_send'], values['line_breaking'], values['resource_cpu'], values['resource_ram'],
                          values['preload_startup']), ('Return', 'syllable', 'unlimited', 'normal', True))
        defaults = Preferences.validated({})
        self.assertEqual((defaults['line_breaking'], defaults['resource_gpu'], defaults['preload_startup']), ('auto', 'normal', False))


class LineBreakTests(unittest.TestCase):
    measure = staticmethod(lambda text: len(text) * 10)

    def lines(self, text, mode, width=200, language='es'):
        chunks, _, _ = line_breaking.layout(text, 0, 0, 0, width, 20, self.measure, mode, language)
        rows = {}
        for _, y, chunk in chunks:
            rows[y] = rows.get(y, '') + chunk
        return [row.rstrip() for _, row in sorted(rows.items())]

    def test_modes(self):
        text = 'Esto es un mensaje extraordinariamente largo para probar los cortes de palabra'
        self.assertEqual(self.lines(text, 'word')[3], 'los cortes de')
        self.assertTrue(all(len(line) == 20 for line in self.lines(text, 'char')[:-1]))
        self.assertTrue(self.lines(text, 'hyphen')[3].endswith('-'))
        syllable = self.lines(text, 'syllable')
        self.assertIn('pala-', syllable[3])  # pa-la-bra (Spanish dictionary)
        self.assertEqual(''.join(self.lines(text, 'syllable')).replace('-', '').replace(' ', ''), text.replace(' ', ''))

    def test_writing_systems_keep_their_rules(self):
        cjk = self.lines('这是一个很长的中文句子用于测试换行规则是否正确', 'syllable', 100)
        self.assertTrue(all('-' not in line for line in cjk))
        arabic = self.lines('هذه رسالة طويلة جدا لاختبار الالتفاف', 'hyphen', 100)
        self.assertTrue(all('-' not in line for line in arabic))
        self.assertEqual(line_breaking.effective('syllable', 'שלום'), 'word')
        self.assertEqual(line_breaking.effective('hyphen', 'สวัสดี'), 'char')

    def test_auto_keeps_old_behaviour_and_text_widgets(self):
        self.assertEqual(line_breaking.mode({}), 'auto')
        self.assertEqual(line_breaking.text_wrap({'line_breaking': 'hyphen'}), 'char')
        self.assertTrue(line_breaking.needs_canvas({'line_breaking': 'syllable'}))
        self.assertFalse(line_breaking.needs_canvas({'line_breaking': 'word'}))


class ReadVisibilityTests(unittest.TestCase):
    def test_first_unread_is_the_oldest_of_the_unread_incoming_messages(self):
        messages = [NS(id=i, outgoing=i == 4, service=False) for i in range(1, 8)]
        self.assertEqual(read_visibility.first_unread_id(messages, 2), 6)
        self.assertEqual(read_visibility.first_unread_id(messages, 0), None)
        self.assertEqual(read_visibility.first_unread_id(messages, 40), 1)

    def test_only_visible_messages_are_acknowledged(self):
        app = object.__new__(Desktop)
        app.stage, app.active, app.demo, app.ui_account = 'ready', 5, False, 'a'
        app.messages = [NS(id=i, outgoing=False) for i in (10, 11, 12)]
        app.chats = [NS(id=5, unread=2)]
        app.chat_visible = lambda: True
        from unittest.mock import AsyncMock
        app.service = NS(backend=NS(mark_read=AsyncMock(return_value=None)))
        submitted = []
        app.worker = NS(submit=lambda coroutine, done, failed: (asyncio.run(coroutine), submitted.append((done, failed))))
        app.render_chats = Mock()
        from unittest.mock import patch
        with patch('tg_ascii.read_visibility.visible_message_ids', return_value=[10, 11]):
            app.acknowledge_visible()
        app.service.backend.mark_read.assert_called_once_with(5, 11)
        with patch('tg_ascii.read_visibility.visible_message_ids', return_value=[]):
            submitted[0][0](None)
        self.assertEqual(app.chats[0].unread, 1)  # Message 12 is below the viewport: still unread.
        app.mark = None
        app._preview_only = True
        app.service.backend.mark_read.reset_mock()
        app.acknowledge_visible()
        app.service.backend.mark_read.assert_not_called()


class ResourceTests(unittest.TestCase):
    def tearDown(self):
        resources.configure({})

    def test_normal_is_the_previous_behaviour(self):
        resources.configure({})
        self.assertEqual(resources.network_slots(4), 4)
        self.assertEqual(resources.cache_entries(512), 512)
        self.assertEqual(resources.animated_entries(32), 32)
        self.assertEqual(resources.frame_interval(), 33)
        self.assertIsNone(resources.worker_threads())

    def test_limited_and_unlimited(self):
        resources.configure({'resource_network': 'limited', 'resource_ram': 'unlimited', 'resource_gpu': 'limited'})
        self.assertEqual(resources.network_slots(4), 2)
        self.assertEqual(resources.cache_entries(512), 2048)
        self.assertEqual(resources.frame_interval(), 66)
        self.assertEqual(resources.animated_entries(32), 8)


class ChatListFitTests(unittest.TestCase):
    def test_long_rows_wrap_instead_of_being_cut(self):
        from tg_ascii import tree_fit
        tree = Mock()
        tree._fit_cache = {'font': NS(measure=lambda text: len(text) * 10, metrics=lambda _: 16), 'widths': {}}
        label = 'Proyecto TG-ASCII con un nombre larguísimo [12] · Trabajo · Amigos'
        wrapped = tree_fit.wrap_label(tree, label, 260)
        self.assertTrue(all(len(line) * 10 <= 260 for line in wrapped.split('\n')))
        self.assertLessEqual(wrapped.count('\n'), 2)
        self.assertEqual(wrapped.replace('\n', ' '), label)
        self.assertEqual(tree_fit.wrap_label(tree, 'Corto', 200), 'Corto')
        squeezed = tree_fit.wrap_label(tree, label, 120)
        self.assertEqual(squeezed.count('\n'), 2)
        self.assertTrue(squeezed.endswith('…'))  # Hover shows the full text.
        kept = tree_fit.wrap_label(tree, label, 120, keep=' [12] · Trabajo · Amigos')
        self.assertTrue(kept.replace('\n', ' ').endswith('[12] · Trabajo · Amigos'))  # Counter never hidden.
        self.assertIn('…', kept)

    def test_large_column_measures_only_changed_lines_and_forgets_removed_labels(self):
        from tg_ascii import tree_fit
        tree = Mock()
        tree.winfo_width.return_value = 200
        tree.__getitem__ = Mock(return_value=())
        tree.get_children.return_value = ()
        measure = Mock(side_effect=len)
        tree._fit_cache = {'font': NS(measure=measure), 'widths': {}}
        labels = [f'Chat {i}' for i in range(5000)]
        tree_fit.fit_column(tree, labels)
        self.assertEqual(measure.call_count, len(labels))

        measure.reset_mock()
        labels[2500] = 'Chat 2500 [1]'
        tree_fit.fit_column(tree, labels)
        measure.assert_called_once_with('Chat 2500 [1]')
        tree_fit.fit_column(tree, ['One\nTwo', 'Two'])
        self.assertEqual(tree._fit_cache['widths'], {'One': 3, 'Two': 3})
        self.assertEqual(measure.call_count, 3)

    def test_column_grows_to_the_widest_row(self):
        from tg_ascii import tree_fit
        tree = Mock()
        tree.winfo_width.return_value = 200
        tree.__getitem__ = Mock(return_value=())
        tree.get_children.return_value = ()
        tree._fit_cache = {'font': NS(measure=lambda text: len(text) * 8), 'widths': {}}
        tree_fit.fit_column(tree, ['short', 'A very long chat title [12] · Work · Friends'])
        width = len('A very long chat title [12] · Work · Friends') * 8 + tree_fit.TEXT_INSET
        tree.column.assert_called_with('#0', width=width, minwidth=width, stretch=False)
        tree_fit.fit_column(tree, ['short'])
        tree.column.assert_called_with('#0', width=tree_fit.BASE_WIDTH, minwidth=160, stretch=True)


if __name__ == '__main__':
    unittest.main()


class Version15PointOneTests(unittest.TestCase):
    """1.5.0.1: list width memory, frame rate limit, custom emoji in folder tags."""

    def tearDown(self):
        resources.configure({})

    def test_frame_limit(self):
        resources.configure({})
        self.assertEqual((resources.decode_fps(), resources.frame_tag(), resources.frame_limit()), (30, '', None))
        resources.configure({'frame_limit': '60'})
        self.assertEqual((resources.decode_fps(), resources.frame_interval(), resources.frame_tag()), (60, 17, '-60fps'))
        self.assertEqual(resources.max_frames(90), 180)
        resources.configure({'frame_limit': 'unlimited'})
        self.assertEqual((resources.frame_limit(), resources.frame_interval()), (0, 4))
        resources.configure({'frame_limit': '15'})
        self.assertEqual((resources.decode_fps(), resources.frame_interval()), (15, 67))
        resources.configure({'frame_limit': 'bogus'})
        self.assertIsNone(resources.frame_limit())

    def test_list_share_is_remembered_and_scaled(self):
        from tg_ascii import pane_memory
        with tempfile.TemporaryDirectory() as folder:
            sidebar = 'sidebar'
            state = {'pos': 400, 'width': 1000}

            class Panes:
                def panes(self): return (sidebar, 'conversation')
                def winfo_width(self): return state['width']
                def sashpos(self, index, value=None):
                    if value is not None: state['pos'] = value
                    return state['pos']
            app = NS(service=NS(root=Path(folder)), demo=False, chat_sidebar=sidebar)
            panes = Panes()
            self.assertEqual(pane_memory.stored(app), 0.0)
            pane_memory.remember(app, panes)
            self.assertAlmostEqual(pane_memory.stored(app), 0.4)
            state['width'] = 1500
            pane_memory.restore(app, panes)
            self.assertEqual(state['pos'], 600)
            fresh = NS(service=NS(root=Path(folder)), demo=False, chat_sidebar=sidebar)
            self.assertAlmostEqual(pane_memory.stored(fresh), 0.4)  # Survives a restart.

    def test_folder_tags_keep_a_gap_per_custom_emoji(self):
        from tg_ascii.desktop_folders import DesktopFolders
        from tg_ascii.row_emoji import PLACEHOLDER
        folder = types.DialogFilter(id=2, title=types.TextWithEntities('Fav ⭐', [types.MessageEntityCustomEmoji(4, 1, 777)]),
                                    pinned_peers=[], include_peers=[], exclude_peers=[], contacts=True)
        app = NS(service=NS(backend=NS(folder_tags_enabled=True)), folder_records=[folder])
        DesktopFolders.prepare_folder_tags(app)
        chat = NS(id=1, kind='user', contact=True, archived=False, muted=False, unread=0, unread_mark=False, pinned=False, bot=False)
        from unittest.mock import patch
        with patch('tg_ascii.desktop_folders.matches_folder', return_value=True):
            text = DesktopFolders.folder_tags_text(app, chat)
            docs = DesktopFolders.folder_tag_docs(app, chat)
        self.assertIn('[Fav ' + PLACEHOLDER + ']', text)
        self.assertEqual(docs, [777])


class Version15PointTwoTests(unittest.TestCase):
    """1.5.0.2: reading when coming back to an open chat; no early reading."""

    def test_open_chat_with_new_messages_needs_a_check(self):
        app = NS(active=5, ui_account='a', messages=[NS(id=10, outgoing=False), NS(id=11, outgoing=True)],
                 chats=[NS(id=5, unread=0, unread_mark=False)], _read_ack={('a', 5): 10})
        self.assertFalse(read_visibility.needs_check(app))
        app.messages.append(NS(id=12, outgoing=False))
        self.assertTrue(read_visibility.needs_check(app))  # Arrived while on another tab.
        app._read_ack[('a', 5)] = 12
        app.chats[0].unread = 2
        self.assertTrue(read_visibility.needs_check(app))

    def test_reading_waits_for_the_jump_to_the_first_unread(self):
        import time as clock
        app = object.__new__(Desktop)
        app.stage, app.active, app.demo, app.ui_account = 'ready', 5, False, 'a'
        app.messages = [NS(id=10, outgoing=False)]
        app.chat_visible = lambda: True
        app._read_hold_until = clock.monotonic() + 5
        app.root = Mock()
        from unittest.mock import patch
        with patch('tg_ascii.read_visibility.visible_message_ids') as visible:
            app.acknowledge_visible()
            visible.assert_not_called()
        app.root.after.assert_called()  # Looks again once the view is in place.
