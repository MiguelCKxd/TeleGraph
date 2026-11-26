"""Slow WebViews must reconnect before queued history exhausts memory."""
import asyncio
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock, patch

from tg_ascii_mobile.core import Core
from tg_ascii_mobile.event_queue import EventQueue, MAX_EVENT_BYTES
from tg_ascii_mobile.server import Server


class EventQueueTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.core = Core(Path(directory.name), 'iOS')
        self.core.loop.close()
        self.core.loop = asyncio.get_running_loop()
        self.core.siri_vocabulary.sync = Mock()

    async def test_undrained_histories_stay_within_budget_and_signal_resync(self):
        previous, bounded = asyncio.Queue(), EventQueue()
        self.core.subscribers.update((previous, bounded))
        peak = 0
        text = 'x' * (128 * 1024)
        for number in range(100):
            self.core.emit('history', {'peer': number, 'messages': [{'id': 1, 'text': text}]})
            peak = max(peak, bounded.pending_bytes)
        retained_before = sum(sys.getsizeof(item) for item in previous._queue)
        self.assertGreater(retained_before, 12 * 1024 * 1024)
        self.assertLessEqual(peak, MAX_EVENT_BYTES)
        self.assertNotIn(bounded, self.core.subscribers)
        self.assertEqual(bounded.pending_bytes, 0)
        self.assertIsNone(await bounded.get())
        # The reconnected page can receive the current state immediately.
        fresh = EventQueue()
        self.core.subscribers.add(fresh)
        self.core.emit('chats', [{'id': 99}])
        self.assertEqual(json.loads(await fresh.get())['data'], [{'id': 99}])
        self.assertEqual(fresh.pending_bytes, 0)

    async def test_multibyte_python_storage_is_counted_and_released_on_get(self):
        queue = EventQueue()
        text = 'a' * 1000 + '😀'
        queue.put_nowait(text)
        self.assertEqual(queue.pending_bytes, sys.getsizeof(text))
        self.assertGreater(queue.pending_bytes, len(text.encode()))
        self.assertEqual(await queue.get(), text)
        self.assertEqual(queue.pending_bytes, 0)
        queue.put_nowait(text)
        queue.clear()
        self.assertEqual(queue.pending_bytes, 0)

    async def test_single_oversize_event_and_event_count_both_reconnect(self):
        for queue, payload, repeats in ((EventQueue(byte_limit=100), 'x' * 101, 1),
                                         (EventQueue(maxsize=2), 'small', 3)):
            with self.subTest(payload=payload[:10]):
                self.core.subscribers = {queue}
                for _ in range(repeats):
                    self.core.emit('message', payload)
                self.assertIsNone(queue.get_nowait())
                self.assertEqual(queue.pending_bytes, 0)
                self.assertNotIn(queue, self.core.subscribers)

    async def test_lock_discards_sensitive_backlog_and_releases_its_bytes(self):
        queue = EventQueue()
        self.core.subscribers.add(queue)
        self.core.emit('history', {'text': 'private' * 10000})
        self.core.locked = True
        self.core.emit('lock', True)
        self.assertEqual(queue.qsize(), 1)
        packet = await queue.get()
        self.assertEqual(json.loads(packet), {'type': 'lock', 'data': True, 'account': None})
        self.assertEqual(queue.pending_bytes, 0)
        self.core.emit('history', {'text': 'never queued'})
        self.assertTrue(queue.empty())

    async def test_legacy_subscriber_keeps_existing_count_limit(self):
        queue = asyncio.Queue()
        self.core.subscribers.add(queue)
        for _ in range(501):
            self.core.emit('message', 'x')
        self.assertEqual(queue.qsize(), 1)
        self.assertIsNone(queue.get_nowait())

    async def test_no_subscribers_skips_json_but_still_updates_siri(self):
        with patch('tg_ascii_mobile.core.json.dumps') as serialize:
            self.core.emit('chats', [])
        self.core.siri_vocabulary.sync.assert_called_once_with(self.core)
        serialize.assert_not_called()

    async def test_server_disconnect_releases_queue_backlog(self):
        class Writer:
            writes = 0
            def write(self, data):
                self.writes += 1
            async def drain(self):
                if self.writes > 1:
                    raise ConnectionResetError('Suspended view disconnected')
        server, writer = Server(self.core), Writer()
        task = asyncio.create_task(server.events(writer, {'x-tg-token': self.core.token}, {}))
        await asyncio.sleep(0)
        queue = next(iter(self.core.subscribers))
        self.assertIsInstance(queue, EventQueue)
        for _ in range(10):
            self.core.emit('message', 'test' * 1000)
        await asyncio.wait_for(task, 1)
        self.assertEqual(queue.pending_bytes, 0)
        self.assertTrue(queue.empty())
        self.assertFalse(self.core.subscribers)
