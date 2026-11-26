import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from tg_ascii import outbox, pending_actions, media_cache, offline_store


class OutboxAuditTests(unittest.TestCase):
    def test_article_media_wraps_payload_in_current_telethon_fields(self):
        from tg_ascii.rich_articles import article_media
        from telethon import types
        photo = types.PhotoEmpty(123)
        document = types.Document(321, 4, b'', None, 'video/mp4', 100, 2, [])
        wrapped = article_media(NS(photos=[photo], documents=[document]))
        self.assertIs(wrapped[0][1].photo, photo)
        self.assertIs(wrapped[1][1].document, document)
        self.assertFalse(wrapped[0][1].spoiler)

    def test_explicit_video_quality_reaches_formatted_upload_path(self):
        backend = Mock()
        item = outbox.Pending('a', 1, paths=['clip.mp4'], photo_quality='original')
        outbox.build_operation(backend, item)
        backend.send_attachment.assert_not_called()
        self.assertEqual(backend.send_formatted.call_args.kwargs['photo_quality'], 'original')

    def make_box(self, root, demo=False):
        app = NS(service=NS(root=root), demo=demo, root=Mock(), closed=False, closing=False)
        return outbox.Outbox(app)

    def test_enqueue_persists_ids_before_first_network_attempt(self):
        with tempfile.TemporaryDirectory() as root:
            box = self.make_box(root)
            def kick():
                saved = json.loads(box.path.read_text(encoding='utf-8'))
                self.assertEqual(saved[0]['random_ids'], box.items[0].random_ids)
                self.assertEqual(len(saved[0]['random_ids']), 3)
            box.kick = kick
            box.add(outbox.Pending('a', 1, paths=['a.jpg', 'b.mp4', 'c.jpg']))
            restored = self.make_box(root)
            self.assertEqual(restored.items[0].random_ids, box.items[0].random_ids)

    def test_failed_persistence_does_not_accept_or_send_message(self):
        box = self.make_box('.')
        box.kick = Mock()
        with patch.object(box, 'save', side_effect=OSError('full disk')):
            with self.assertRaises(OSError):
                box.add(outbox.Pending('a', 1, 'keep draft'))
        self.assertEqual(box.items, [])
        box.kick.assert_not_called()

    def test_limits_each_account_and_preserves_heads_in_retry_or_failed(self):
        box = self.make_box('.', demo=True)
        first = outbox.Pending('a', 1, retry_at=float('inf'))
        later = outbox.Pending('a', 1)
        failed = outbox.Pending('b', 1, state='failed')
        box.items = [first, later, failed] + [outbox.Pending(a, i) for a in ('a', 'b') for i in range(1, 100)]
        box.backend_for = Mock(return_value=object())
        started = []
        def start(item, backend):
            started.append(item)
            box.inflight[(item.account, item.peer)] = item
        box.start = start
        with patch('tg_ascii.resources.network_slots', return_value=2):
            box.kick()
            self.assertEqual([(x.account, x.peer) for x in started], [('a', 2), ('a', 3), ('b', 1), ('b', 2)])
            box.kick()
        self.assertEqual(len(started), 4)
        self.assertLessEqual(box.backend_for.call_count, 2)

    def test_offline_backend_is_resolved_once_per_account(self):
        box = self.make_box('.', demo=True)
        box.items = [outbox.Pending('a', i) for i in range(5000)]
        box.backend_for = Mock(return_value=None)
        box.kick()
        box.backend_for.assert_called_once_with('a')


class PendingActionsAuditTests(unittest.TestCase):
    def test_offline_forward_ids_are_saved_before_replay(self):
        with tempfile.TemporaryDirectory() as root:
            service = NS(root=root)
            queue = pending_actions.PendingActions(service, 'a')
            item = queue.add('forward_selected_messages', [1, [10, 20, 30], 2], {})
            self.assertEqual(len(item.random_ids), 3)
            again = pending_actions.PendingActions(service, 'a')
            self.assertEqual(again.records[0].random_ids, item.random_ids)


class CacheAuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_pruning_repeats_after_growth_and_coalesces_a_burst(self):
        with tempfile.TemporaryDirectory() as root:
            backend = NS(media_cache_dir=Path(root))
            with patch('tg_ascii.media_cache.prune', return_value=0) as prune:
                await asyncio.gather(*(media_cache.prune_once(backend, 10) for _ in range(100)))
                self.assertEqual(prune.call_count, 1)
                await media_cache.prune_once(backend, media_cache.PRUNE_WRITTEN_BYTES)
                self.assertEqual(prune.call_count, 2)
                backend._media_cache_pruned_at -= media_cache.PRUNE_INTERVAL + 1
                await media_cache.prune_once(backend)
                self.assertEqual(prune.call_count, 3)

    def test_expiring_media_and_messages_never_enter_persistent_cache(self):
        from telethon import types
        from tg_ascii.backend import Chat, Message
        with tempfile.TemporaryDirectory() as root:
            media = types.MessageMediaPhoto(photo=types.PhotoEmpty(3), ttl_seconds=10)
            backend = NS(media_cache_dir=Path(root))
            self.assertTrue(media_cache.has_expiry(media))
            self.assertIsNone(media_cache.preview_entry(backend, media, 'm', '.jpg'))
            self.assertTrue(media_cache.has_expiry(NS(media=media)))
            self.assertFalse(media_cache.has_expiry(NS(ttl_seconds=0)))
            messages = [Message(1, 'A', 'plain', '10:00'), Message(2, 'A', 'photo', '10:00', media=media),
                        Message(3, 'A', 'auto delete', '10:00', ttl_period=60)]
            offline_store.write(root, 'a', [Chat(7, 'A')], [], {7: messages})
            self.assertEqual([m.id for m in offline_store.read(root, 'a')[2][7]], [1])

    def test_slow_old_snapshot_cannot_replace_newer_snapshot_or_recreate_logout_copy(self):
        from tg_ascii.backend import Chat
        for purge in (False, True):
            with self.subTest(purge=purge), tempfile.TemporaryDirectory() as root:
                entered, release = threading.Event(), threading.Event()
                original = offline_store._encode_chats
                def encode(chats):
                    if chats[0].name == 'old':
                        entered.set()
                        self.assertTrue(release.wait(2))
                    return original(chats)
                with patch.object(offline_store, '_encode_chats', side_effect=encode):
                    thread = threading.Thread(target=offline_store.write, args=(root, 'a', [Chat(1, 'old')], [], {}))
                    thread.start()
                    self.assertTrue(entered.wait(2))
                    offline_store.write(root, 'a', [Chat(1, 'new')], [], {})
                    if purge:
                        offline_store.purge(root, 'a')
                    release.set()
                    thread.join(2)
                result = offline_store.read(root, 'a')
                self.assertIsNone(result) if purge else self.assertEqual(result[0][0].name, 'new')


class LifecycleAuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_flood_gate_observes_extensions_and_total_wait_budget(self):
        from tg_ascii.flood_control import FloodGate
        from telethon.errors import FloodWaitError
        for extension, expected_waits in ((3, 2), (30, 1)):
            now, waits = [0.0], []
            gate = FloodGate()
            gate.resume_at = 1
            async def sleep(delay):
                waits.append(delay)
                now[0] += delay
                if len(waits) == 1:
                    gate.resume_at = now[0] + extension
            with patch('tg_ascii.flood_control.time.monotonic', side_effect=lambda: now[0]), \
                 patch('tg_ascii.flood_control.random.uniform', return_value=0), \
                 patch('tg_ascii.flood_control.asyncio.sleep', side_effect=sleep):
                if extension == 30:
                    with self.assertRaises(FloodWaitError):
                        await gate.passage(limit=10)
                else:
                    await gate.passage(limit=10)
            self.assertEqual(len(waits), expected_waits)

    async def test_account_switch_stops_preload_and_discards_delayed_avatar(self):
        import queue
        from tg_ascii.preload import Preloader
        with tempfile.TemporaryDirectory() as root:
            app = NS(ui_account='a', service=NS(), closed=False, closing=False,
                     preferences=NS(values={}), preview_cache={}, preview_dir=Path(root),
                     worker=NS(events=queue.SimpleQueue()), active=None)
            async def avatar(*args, **kwargs):
                app.ui_account = 'b'
                return 'stale-a.jpg'
            backend = NS(avatar=AsyncMock(side_effect=avatar), history=AsyncMock(return_value=[]))
            app.service.backend = backend
            preloader = Preloader(app)
            with patch('tg_ascii.preload.SPACING', 0):
                await preloader.run([NS(id=1, entity=None), NS(id=2, entity=None)])
            while not app.worker.events.empty():
                callback, value = app.worker.events.get()
                callback(value)
            self.assertEqual(backend.avatar.await_count, 1)
            backend.history.assert_not_awaited()
            self.assertEqual(app.preview_cache, {})

    async def test_preload_skip_cancels_current_request(self):
        from tg_ascii.preload import Preloader
        preloader = Preloader(NS(ui_account='a', service=NS(backend=object())))
        preloader.future = asyncio.create_task(asyncio.Event().wait())
        preloader.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await preloader.future
