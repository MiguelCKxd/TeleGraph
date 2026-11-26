import tkinter as tk
import unittest
from types import SimpleNamespace as NS
from unittest import mock

from tg_ascii import desktop_forums as forums
from tg_ascii.interface_windows import LinkedChatWindow
from tg_ascii import transitions


def row(ident, **values):
    base = dict(id=ident, title=f'Tema {ident}', icon_color=0, icon_emoji_id=None, closed=False, hidden=False,
                pinned=False, unread_count=0, top_message=0, can_edit=False, can_delete=False, can_pin=False,
                can_hide=False, can_send=True)
    base.update(values)
    return base


class Worker:
    """Runs contract coroutines at once, like the app worker would."""
    def __init__(self): self.calls = []

    def submit(self, coroutine, success, failure):
        import asyncio
        self.calls.append(coroutine.cr_code.co_name)
        try:
            success(asyncio.run(coroutine))
        except Exception as error:  # pragma: no cover - surfaced by tests
            failure(error)


class ForumBackend:
    """Implements only the published forum contract."""
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    async def forum_topics(self, peer, query='', cursor=None, limit=50):
        self.queries.append((peer, query, cursor))
        found = [r for r in self.rows if query.casefold() in r['title'].casefold()]
        if cursor is None and len(found) > 2:
            return {'topics': found[:2], 'next_cursor': {'offset': 2}, 'can_create': True}
        return {'topics': found[2:] if cursor else found, 'next_cursor': None, 'can_create': True}

    async def forum_topic(self, peer, topic_id):
        return next(r for r in self.rows if r['id'] == topic_id)

    async def forum_pin(self, peer, topic_id, pinned):
        return row(topic_id, pinned=pinned, title=f'Tema {topic_id}')

    async def forum_delete(self, peer, topic_id):
        return True


class TopicHelperTests(unittest.TestCase):
    def test_labels_marks_and_order(self):
        rows = [row(5, title='Normal'), row(1, title='General', pinned=True, unread_count=3), row(9, closed=True, hidden=True)]
        self.assertEqual(forums.topic_label(rows[1]), ('📌 General', '3'))
        self.assertEqual(forums.topic_label(rows[2])[0], '🔒🙈 Tema 9')
        self.assertEqual([r['id'] for r in forums.sort_topics(rows)], [1, 5, 9])

    def test_actions_follow_telegram_rights(self):
        self.assertEqual(forums.topic_actions(row(5)), [])
        names = [a[1] for a in forums.topic_actions(row(5, can_edit=True, can_pin=True, can_delete=True, can_hide=True))]
        self.assertEqual(names, ['rename', 'closed', 'pinned', 'delete'])  # only General can be hidden
        general = [a[1] for a in forums.topic_actions(row(1, can_hide=True, can_delete=True))]
        self.assertEqual(general, ['hidden'])  # General is never deleted

    def test_flags_tolerate_cores_without_fields(self):
        self.assertEqual(forums.chat_flags(NS()), (False, False))
        self.assertEqual(forums.chat_flags(NS(forum=True, has_link=False)), (True, False))


class TopicBrowserTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest('no display')
        self.root.withdraw()
        self.backend = ForumBackend([row(1, title='General'), row(2, title='Avisos', can_pin=True), row(3, title='Fotos')])
        self.service = NS(backend=self.backend)
        self.app = NS(root=self.root, ui_account='a', service=self.service, worker=Worker(), demo=False,
                      show_error=mock.Mock(), _chat_windows=[], preferences=NS(values={'reduce_animations': True}))

        def dialog(title, size):
            window = tk.Toplevel(self.root)
            frame = tk.Frame(window); frame.pack()
            return window, frame
        self.app.dialog = dialog

    def tearDown(self):
        self.root.destroy()

    def test_pages_search_and_change_events(self):
        browser = forums.TopicBrowser(self.app, 'a', -100, 'Grupo')
        self.assertEqual(browser.tree.get_children(), ('1', '2'))
        browser.load(more=True)
        self.assertEqual(browser.tree.get_children(), ('1', '2', '3'))
        browser.query.set('fot'); browser.load()
        self.assertEqual(browser.tree.get_children(), ('3',))
        self.assertEqual(self.backend.queries[-1], (-100, 'fot', None))
        before = len(self.backend.queries)
        browser.change('a', 'forum_topics', (-999, None)); browser.change('b', 'forum_topics', (-100, None))
        self.assertIsNone(browser._change_job)
        for topic in (2, 3, None):  # a burst of forum messages
            browser.change('a', 'forum_topics', (-100, topic))
        self.assertEqual(len(self.backend.queries), before)  # coalesced, not yet requested
        browser.window.after_cancel(browser._change_job); browser.changed_reload()
        self.assertEqual(len(self.backend.queries), before + 1)

    def test_pin_updates_row_and_switching_account_invalidates(self):
        browser = forums.TopicBrowser(self.app, 'a', -100, 'Grupo')
        browser.run(browser.row(2), 'pinned', True)
        self.assertTrue(browser.row(2)['pinned'])
        self.assertEqual(browser.tree.get_children()[0], '2')
        self.app.ui_account = 'b'
        self.assertFalse(browser.valid())


class TopicWindowTests(unittest.TestCase):
    def window(self, topic):
        window = LinkedChatWindow.__new__(LinkedChatWindow)
        window.topic = topic
        window.topic_id = topic['id'] if topic else None
        window.thread, window.thread_id, window.peer = None, None, -100
        window.backend = NS(forum_history=mock.Mock(return_value='page'), discussion_history=mock.Mock())
        return window

    def test_topic_messages_and_paging(self):
        window = self.window(row(7))
        self.assertTrue(window.belongs(NS(topic_id=7)))
        self.assertFalse(window.belongs(NS(topic_id=1)))
        self.assertEqual(window.history_page(41), 'page')
        window.backend.forum_history.assert_called_once_with(-100, 7, 41)
        general = self.window(row(1))
        self.assertTrue(general.belongs(NS()))  # messages without topic_id are General


class RevealTests(unittest.TestCase):
    def test_forum_message_opens_its_topic_and_others_jump(self):
        backend = ForumBackend([row(4, title='Viajes')])
        app = NS(ui_account='a', service=NS(backend=backend), worker=Worker(), demo=False, jump_message=mock.Mock(),
                 _chat_by_id={-100: NS(forum=True), -200: NS(forum=False)})
        with mock.patch.object(forums, 'open_topic') as opened:
            forums.reveal_in_context(app, -100, 55, 4)
            opened.assert_called_once()
            self.assertEqual(opened.call_args.kwargs['message'], 55)
            forums.reveal_in_context(app, -100, 56, None)
            forums.reveal_in_context(app, -200, 57, 4)
        self.assertEqual([c.args for c in app.jump_message.call_args_list], [(56, -100), (57, -200)])


class TransitionTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest('no display')
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()

    def test_disabled_motion_applies_end_state_at_once(self):
        app = NS(preferences=NS(values={'reduce_animations': True}))
        self.assertFalse(transitions.motion_allowed(app))
        top = tk.Toplevel(self.root)
        transitions.fade_in(app, top)
        self.assertEqual(float(top.attributes('-alpha')), 1.0)
        canvas = tk.Canvas(self.root); item = canvas.create_text(10, 10, text='x')
        self.assertIsNone(transitions.slide_in(app, canvas))
        self.assertEqual(canvas.coords(item), [10.0, 10.0])

    def test_slide_returns_items_and_spares_wallpaper_and_new_items(self):
        app = NS(preferences=NS(values={}))
        with mock.patch.object(transitions, 'system_reduces_motion', return_value=False):
            canvas = tk.Canvas(self.root)
            text = canvas.create_text(10, 10, text='x')
            wall = canvas.create_image(0, 0, tags='wallpaper')
            tween = transitions.slide_in(app, canvas)
            self.assertEqual(canvas.coords(text)[0], 10 + transitions.SLIDE_PX)
            late = canvas.create_text(50, 50, text='y')
            tween.cancel(); tween.finish()
            self.assertEqual(canvas.coords(text), [10.0, 10.0])
            self.assertEqual(canvas.coords(wall), [0.0, 0.0])
            self.assertEqual(canvas.coords(late), [50.0, 50.0])

    def test_flash_marks_the_message_and_cleans_up(self):
        app = NS(preferences=NS(values={'bubbles': True, 'reduce_animations': True}))
        canvas = tk.Canvas(self.root)
        canvas.create_rectangle(0, 0, 20, 20, tags='message:9')
        view = NS(preferences=app.preferences, bubble_view=canvas, _canvas_chat_view=True, app=app)
        transitions.flash_message(view, 9)
        self.assertTrue(canvas.find_withtag('jump_highlight'))
        self.assertIsNone(transitions.flash_message(view, 404))


if __name__ == '__main__':
    unittest.main()


class RevealOperationTests(unittest.TestCase):
    def test_reveal_requests_a_page_around_the_message(self):
        window = LinkedChatWindow.__new__(LinkedChatWindow)
        window.topic, window.topic_id, window.thread, window.thread_id, window.peer = row(7), 7, None, None, -100
        window.backend = NS(forum_history=mock.Mock(return_value='around'))
        window.valid = lambda: True
        window.jump = lambda ident: False
        window.call = mock.Mock()
        window.reveal_message(55)
        window.backend.forum_history.assert_called_once_with(-100, 7, 0, around=55)
        self.assertEqual(window.call.call_args.args[0], 'around')
        window.topic, window.topic_id, window.thread, window.thread_id = None, None, {'root': NS(id=3)}, 3
        window.backend = NS(discussion_around=mock.Mock(return_value='thread'))
        window.reveal_message(56)
        window.backend.discussion_around.assert_called_once_with(-100, 3, 56)


class DeletedTopicTests(unittest.TestCase):
    def test_deleted_topic_blocks_sending_but_network_errors_do_not(self):
        from tg_ascii.forum_topics import ForumTopicUnavailable
        window = LinkedChatWindow.__new__(LinkedChatWindow)
        window.topic, window.topic_id = row(7), 7
        window.valid = lambda: True
        window.update_topic_state = mock.Mock()
        window.status = mock.Mock()
        window.topic_failed(ConnectionError('offline'))
        self.assertTrue(window.topic['can_send'])
        window.topic_failed(ForumTopicUnavailable('gone'))
        self.assertFalse(window.topic['can_send'])
        window.update_topic_state.assert_called_once()



class HistoryRaceTests(unittest.TestCase):
    """A late initial page must never replace the page of a jump (and vice versa)."""

    def window(self):
        from tg_ascii.peer_tools import HistoryPage
        window = LinkedChatWindow.__new__(LinkedChatWindow)
        window.topic, window.topic_id, window.thread, window.thread_id, window.peer = row(7), 7, None, None, -100
        window.loading, window.history_changes, window.messages, window.closed = False, [], [], False
        window.backend = NS(forum_history=mock.Mock(side_effect=lambda *a, **k: ('history', a, k)))
        window.valid = lambda: True
        window.jump = lambda ident: False
        window.request_render = mock.Mock()
        window.schedule_translations = mock.Mock()
        window.update_topic_state = mock.Mock()
        window.status = mock.Mock()
        window.window = NS(after=lambda delay, callback: None)
        window.calls = []
        window.call = lambda operation, done, failed=None: window.calls.append((operation, done, failed))
        window.page = lambda ids: HistoryPage([NS(id=i, topic_id=7, outgoing=False) for i in ids], next_offset=min(ids), more=True)
        return window

    def test_late_initial_page_does_not_replace_the_jump(self):
        window = self.window()
        window.refresh()                      # initial load (window opened)
        window.reveal_message(500)            # jump from the gallery
        (_, initial, _), (_, jumped, _) = window.calls
        jumped(window.page([499, 500, 501]))  # the jump answers first
        initial(window.page([900, 901]))      # the initial page arrives late
        self.assertEqual([m.id for m in window.messages], [499, 500, 501])
        self.assertFalse(window.loading)

    def test_in_order_answers_still_end_on_the_jump(self):
        window = self.window()
        window.refresh(); window.reveal_message(500)
        (_, initial, _), (_, jumped, _) = window.calls
        initial(window.page([900, 901]))      # stale: ignored, loading stays for the jump
        self.assertTrue(window.loading)
        jumped(window.page([499, 500]))
        self.assertEqual([m.id for m in window.messages], [499, 500])
        self.assertFalse(window.loading)

    def test_stale_failure_does_not_clear_a_newer_load(self):
        window = self.window()
        window.refresh(); window.reveal_message(500)
        (_, _, initial_failed), (_, jumped, _) = window.calls
        window.status.reset_mock()
        initial_failed(ConnectionError('late'))
        self.assertTrue(window.loading)
        window.status.set.assert_not_called()

    def test_existing_window_jump_beats_its_own_refresh(self):
        window = self.window()
        window.messages = [NS(id=1, topic_id=7, outgoing=False)]
        window.reveal_message(500)            # existing window: jump first...
        window.loading = False
        window.refresh()                      # ...then an update triggers a refresh
        (_, jumped, _), (_, refreshed, _) = window.calls
        refreshed(window.page([900]))
        jumped(window.page([500]))            # the jump's answer arrives after: it is stale now
        self.assertEqual([m.id for m in window.messages], [900])


class RevealScopeTests(unittest.TestCase):
    def test_fallback_jump_is_dropped_after_switching_account(self):
        backend = NS(forum_topic=mock.AsyncMock(side_effect=ConnectionError('offline')))
        app = NS(ui_account='a', service=NS(backend=backend), demo=False, jump_message=mock.Mock(),
                 _chat_by_id={-100: NS(forum=True)})

        class LateWorker:
            def submit(self, coroutine, success, failure):
                coroutine.close(); self.failure = failure
        app.worker = LateWorker()
        forums.reveal_in_context(app, -100, 55, 4)
        app.ui_account = 'b'
        app.worker.failure(ConnectionError('offline'))
        app.jump_message.assert_not_called()
        app.ui_account = 'a'
        app.worker.failure(ConnectionError('offline'))
        app.jump_message.assert_called_once_with(55, -100)


class ExtensionTests(unittest.TestCase):
    def test_only_writable_topics_can_be_chosen(self):
        rows = [row(1), row(2, can_send=False), row(3, pinned=True)]
        self.assertEqual([r['id'] for r in forums.writable_topics(rows)], [3, 1])

    def test_forward_asks_for_topic_only_in_forums(self):
        backend = NS(forum_forward=mock.Mock(return_value='fwd'))
        app = NS(ui_account='a', service=NS(backend=backend), call=mock.Mock())
        with mock.patch.object(forums, 'choose_topic') as picker:
            self.assertFalse(forums.forward_to(app, 'a', backend, NS(id=-5, name='Chat', forum=False), -1, [9], None))
            picker.assert_not_called()
            self.assertTrue(forums.forward_to(app, 'a', backend, NS(id=-7, name='Foro', forum=True), -1, [9, 10], 'done'))
            chosen = picker.call_args.args[4]
        chosen(row(4))
        backend.forum_forward.assert_called_once_with(-7, 4, -1, [9, 10])
        self.assertEqual(app.call.call_args.args[:2], ('fwd', 'done'))
        app.ui_account = 'b'
        chosen(row(4))
        self.assertEqual(backend.forum_forward.call_count, 1)  # another account: dropped

    def test_toggle_entry_only_for_group_owners(self):
        def app_with(entity):
            return NS(demo=False, service=NS(backend=NS(_capability_entities={-9: entity})))
        self.assertIsNone(forums.topics_toggle_entry(app_with(NS(creator=False, forum=False)), -9))
        self.assertIsNone(forums.topics_toggle_entry(app_with(NS(creator=True, broadcast=True)), -9))
        label, action = forums.topics_toggle_entry(app_with(NS(creator=True, forum=False, megagroup=True)), -9)
        self.assertEqual(label, forums.caption('Enable topics', 'Activar temas'))
        label, _ = forums.topics_toggle_entry(app_with(NS(creator=True, forum=True, megagroup=True)), -9)
        self.assertEqual(label, forums.caption('Disable topics', 'Desactivar temas'))
        # Only converting a basic group warns that it cannot be undone.
        self.assertNotEqual(forums.toggle_confirmation(True, True), forums.toggle_confirmation(True, False))
        self.assertNotEqual(forums.toggle_confirmation(True, False), forums.toggle_confirmation(False, False))

    def test_toggle_converts_basic_group_and_replaces_its_chat(self):
        new_chat = NS(id=-1000000000077, name='Club', forum=True)
        backend = NS(forum_toggle=mock.Mock(return_value='toggle'))
        app = NS(busy=False, demo=False, ui_account='a', root=None, service=NS(backend=backend),
                 chats=[NS(id=-77, name='Club'), NS(id=-3, name='Otro')], open_resolved=mock.Mock(),
                 update_chat_capabilities=mock.Mock(), call=mock.Mock())
        with mock.patch('tg_ascii.app_dialogs.messagebox') as box, mock.patch.object(forums, 'open_topics') as topics:
            box.askyesno.return_value = True
            forums.toggle_topics(app, -77, True, basic=True)
            backend.forum_toggle.assert_called_once_with(-77, True, migrate=True)
            app.call.call_args.args[1](new_chat)
            topics.assert_called_once_with(app, new_chat.id)
        self.assertEqual([c.id for c in app.chats], [-3, new_chat.id])
        app.open_resolved.assert_called_once_with(new_chat)

    def test_declined_confirmation_changes_nothing(self):
        backend = NS(forum_toggle=mock.Mock())
        app = NS(busy=False, demo=False, ui_account='a', root=None, service=NS(backend=backend), call=mock.Mock())
        with mock.patch('tg_ascii.app_dialogs.messagebox') as box:
            box.askyesno.return_value = False
            forums.toggle_topics(app, -77, False)
        backend.forum_toggle.assert_not_called()


class TopicToolTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest('no display')
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()

    def window(self):
        window = LinkedChatWindow.__new__(LinkedChatWindow)
        window.topic, window.topic_id, window.peer = row(7, title='Viajes'), 7, -100
        window.window = tk.Toplevel(self.root)
        window.valid = lambda: True
        window.backend = NS(forum_search=mock.Mock(return_value='search'), forum_scheduled=mock.Mock(return_value='scheduled'))
        window.calls = []
        window.call = lambda operation, done, failed=None: window.calls.append((operation, done))
        window.reveal_message = mock.Mock()
        return window

    def test_search_uses_topic_and_jumps_to_result(self):
        from datetime import datetime, timezone
        window = self.window()
        top = forums.topic_search(window)
        top.children  # built
        query = next(w for w in top.winfo_children() if isinstance(w, tk.ttk.Entry))
        query.insert(0, 'billetes'); query.event_generate('<Return>')
        window.calls.clear()
        forums_search = [w for w in top.winfo_children() if isinstance(w, tk.Listbox)][0]
        # run the search through the button path
        next(b for f in top.winfo_children() if isinstance(f, tk.ttk.Frame) for b in f.winfo_children()
             if str(b.cget('text')) == forums.tr('Search')).invoke()
        operation, done = window.calls[-1]
        window.backend.forum_search.assert_called_with(-100, 7, 'billetes', False)
        done([NS(id=31, date=datetime(2026, 11, 26, tzinfo=timezone.utc), time='', sender='Ana', raw_text='Billetes', text='')])
        forums_search.selection_set(0)
        forums_search.event_generate('<Return>')
        next(b for f in top.winfo_children() if isinstance(f, tk.ttk.Frame) for b in f.winfo_children()
             if str(b.cget('text')) == forums.tr('Go to message')).invoke()
        window.reveal_message.assert_called_with(31)

    def test_scheduled_lists_only_the_topic(self):
        window = self.window()
        forums.topic_scheduled(window)
        operation, done = window.calls[-1]
        window.backend.forum_scheduled.assert_called_once_with(-100, 7)
        self.assertEqual(operation, 'scheduled')


class TopicPickerTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest('no display')
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()

    def picker(self, worker):
        backend = NS()
        app = NS(ui_account='a', service=NS(backend=backend), worker=worker)

        def dialog(title, size):
            window = tk.Toplevel(self.root); frame = tk.Frame(window); frame.pack()
            return window, frame
        app.dialog = dialog
        chosen = []
        backend.forum_topics = mock.Mock(side_effect=lambda peer, query, cursor, limit: (query, cursor))
        picker = forums.TopicPicker(app, 'a', -100, 'Foro', chosen.append)
        return app, backend, picker, chosen

    class Deferred:
        def __init__(self): self.jobs = []
        def submit(self, operation, success, failure): self.jobs.append((operation, success, failure))

    def test_second_page_is_reachable_deduplicated_and_forwardable(self):
        worker = self.Deferred()
        app, backend, picker, chosen = self.picker(worker)
        _, first, _ = worker.jobs[-1]
        first({'topics': [row(1, pinned=True), row(2), row(3, can_send=False)], 'next_cursor': {'opaque': 1}})
        self.assertEqual(picker.listing.size(), 2)
        self.assertTrue(picker.more_button.winfo_manager())
        picker.load(more=True)
        self.assertEqual(backend.forum_topics.call_args.args[2], {'opaque': 1})  # cursor passed back untouched
        _, second, _ = worker.jobs[-1]
        second({'topics': [row(1, pinned=True), row(150, title='Tema lejano')], 'next_cursor': None})
        self.assertEqual([r['id'] for r in picker.rows], [1, 2, 150])  # pinned 1 not repeated
        self.assertFalse(picker.more_button.winfo_manager())
        picker.listing.selection_set(2)
        picker.confirm()
        self.assertEqual(chosen[0]['id'], 150)

    def test_newer_search_wins_and_other_accounts_are_ignored(self):
        worker = self.Deferred()
        app, backend, picker, chosen = self.picker(worker)
        _, initial, _ = worker.jobs[-1]
        picker.query.set('via'); picker.load()
        _, searched, _ = worker.jobs[-1]
        searched({'topics': [row(9, title='Viajes')], 'next_cursor': None})
        initial({'topics': [row(1), row(2)], 'next_cursor': {'x': 1}})  # late, older request
        self.assertEqual([r['id'] for r in picker.rows], [9])
        picker.load()
        _, latest, _ = worker.jobs[-1]
        app.ui_account = 'b'
        latest({'topics': [row(5)], 'next_cursor': None})
        self.assertEqual([r['id'] for r in picker.rows], [9])
        self.assertEqual(forums.merge_topics([row(1)], [row(1), row(2)])[1]['id'], 2)


class TopicSearchOrderTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest('no display')
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()

    def test_older_search_answer_does_not_replace_the_newer_one(self):
        window = LinkedChatWindow.__new__(LinkedChatWindow)
        window.topic, window.topic_id, window.peer = row(7), 7, -100
        window.window = tk.Toplevel(self.root)
        window.valid = lambda: True
        window.backend = NS(forum_search=mock.Mock(side_effect=lambda peer, topic, query, pinned: query))
        window.calls = []
        window.call = lambda operation, done, failed=None: window.calls.append((operation, done))
        top = forums.topic_search(window)
        entry = next(w for w in top.winfo_children() if isinstance(w, tk.ttk.Entry))
        button = next(b for f in top.winfo_children() if isinstance(f, tk.ttk.Frame) for b in f.winfo_children()
                      if str(b.cget('text')) == forums.tr('Search'))
        entry.insert(0, 'uno'); button.invoke()
        entry.delete(0, 'end'); entry.insert(0, 'dos'); button.invoke()
        (_, first), (_, second) = window.calls
        msg = lambda ident, text: NS(id=ident, date=None, time='10:00', sender='Ana', raw_text=text, text=text)
        second([msg(2, 'dos')])
        first([msg(1, 'uno')])  # late answer of the first search
        listing = next(w for w in top.winfo_children() if isinstance(w, tk.Listbox))
        self.assertEqual(listing.size(), 1)
        self.assertIn('dos', listing.get(0))
