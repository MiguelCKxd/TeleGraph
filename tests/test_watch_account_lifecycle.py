"""Watch UI callbacks must stay on their originating account."""
import asyncio
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from tg_ascii_watch.app import TgAsciiWatch


class WatchAccountTests(IsolatedAsyncioTestCase):
    async def test_queued_event_from_other_account_cannot_replace_watch_chats(self):
        app = SimpleNamespace(active_account='b', chats=[{'id': 2}], screen='chats', show_chats=Mock())
        TgAsciiWatch.on_event(app, {'type': 'chats', 'account': 'a', 'data': [{'id': 1}]})
        self.assertEqual(app.chats, [{'id': 2}])
        app.show_chats.assert_not_called()

    async def test_pending_watch_action_does_not_update_new_account_ui(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def call(*args, **kwargs):
            started.set()
            await release.wait()
            return [{'id': 1}]
        tasks = []
        def create(work):
            task = asyncio.create_task(work)
            tasks.append(task)
            return task
        done = Mock()
        app = SimpleNamespace(active_account='a', call=call, loop=SimpleNamespace(create_task=create), toast=Mock())
        TgAsciiWatch.run(app, 'chats', done=done)
        await started.wait()
        app.active_account = 'b'
        release.set()
        await asyncio.gather(*tasks)
        done.assert_not_called()

    async def test_stale_watch_state_cannot_undo_new_navigation(self):
        async def call(*args):
            app.navigation += 1
            app.active_account = 'b'
            return {'stage': 'ready', 'account': 'a'}
        app = SimpleNamespace(navigation=0, active_account='a', call=call, route=Mock())
        await TgAsciiWatch.refresh(app)
        self.assertEqual(app.active_account, 'b')
        app.route.assert_not_called()


class WatchEventBufferTests(IsolatedAsyncioTestCase):
    async def test_lock_purges_backlog_and_reaches_ui_without_subscriber_error(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from tg_ascii_mobile.core import Core
        from tg_ascii_watch.app import Events
        with TemporaryDirectory() as directory:
            core = Core(Path(directory), 'Wear OS')
            self.addCleanup(core.loop.close)
            callbacks = []
            app = SimpleNamespace(core=core, on_event=Mock(), loop=SimpleNamespace(
                call_soon_threadsafe=lambda callback, *args: callbacks.append((callback, args)),
                call_soon=lambda callback, *args: callbacks.append((callback, args))))
            events = Events(app)
            core.subscribers.add(events)
            core.emit('message', {'text': 'private'})
            core.locked = True
            core.emit('lock', True)
            while callbacks:
                callback, args = callbacks.pop(0)
                callback(*args)
            self.assertEqual(app.on_event.call_count, 1)
            self.assertEqual(app.on_event.call_args.args[0]['type'], 'lock')
            self.assertEqual(events.qsize(), 0)

    async def test_many_pending_events_schedule_only_one_ui_wakeup(self):
        import json
        from tg_ascii_watch.app import Events
        loop = SimpleNamespace(call_soon_threadsafe=Mock())
        events = Events(SimpleNamespace(loop=loop, on_event=Mock()))
        for index in range(100):
            events.put_nowait(json.dumps({'type': 'chat', 'data': index}))
        self.assertEqual(loop.call_soon_threadsafe.call_count, 1)
        self.assertEqual(events.qsize(), 100)
        self.assertTrue(events.would_overflow('x' * (4 * 1024 * 1024)))

    async def test_watch_retains_only_the_twenty_displayable_messages(self):
        app = SimpleNamespace(active_account='a', screen='chat', open_peer=1, topic=None,
                              messages=[], show_chat=Mock())
        for index in range(500):
            TgAsciiWatch.on_event(app, {'type': 'message', 'account': 'a',
                                       'data': {'peer': 1, 'message': {'id': index}}})
        self.assertEqual([m['id'] for m in app.messages], list(range(480, 500)))

    async def test_lock_event_hides_existing_private_view(self):
        app = SimpleNamespace(active_account='a', show_locked=Mock())
        TgAsciiWatch.on_event(app, {'type': 'lock', 'data': True})
        app.show_locked.assert_called_once_with()

    async def test_overflow_has_one_resync_marker_and_rejoins_core(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from tg_ascii_mobile.core import Core
        from tg_ascii_watch.app import Events
        with TemporaryDirectory() as directory:
            core = Core(Path(directory), 'Wear OS')
            self.addCleanup(core.loop.close)
            callbacks = []
            app = SimpleNamespace(core=core, on_event=Mock(), resync_events=Mock(), loop=SimpleNamespace(
                call_soon_threadsafe=lambda callback, *args: callbacks.append((callback, args)),
                call_soon=lambda callback, *args: callbacks.append((callback, args))))
            events = Events(app)
            core.subscribers.add(events)
            for index in range(501):
                core.emit('message', {'id': index})
            self.assertNotIn(events, core.subscribers)
            self.assertEqual(events.qsize(), 1)
            self.assertEqual(events.pending_bytes, 0)
            while callbacks:
                callback, args = callbacks.pop(0)
                callback(*args)
            await asyncio.to_thread(core.loop.run_until_complete, asyncio.sleep(0))
            self.assertIn(events, core.subscribers)
            app.on_event.assert_not_called()
            app.resync_events.assert_called_once_with()
            self.assertEqual(events.pending_bytes, 0)
