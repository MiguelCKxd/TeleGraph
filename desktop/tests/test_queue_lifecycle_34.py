"""Delayed queue outcomes must not corrupt a replacement or hide disk errors."""
import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

from tg_ascii.drafts import DraftManager
from tg_ascii.outbox import Outbox, Pending
from tg_ascii.pending_actions import PendingActions


class QueueLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def test_offline_replacement_is_not_accepted_when_disk_write_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            queue = PendingActions(NS(root=folder), 'a')
            previous = queue.add('react', [1, 7, 'old'], {})
            with patch.object(queue, 'save', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    queue.add('react', [1, 7, 'new'], {})
            self.assertEqual(queue.records, [previous])
            restored = PendingActions(NS(root=folder), 'a')
            self.assertEqual(restored.records[0].args, [1, 7, 'old'])

    async def test_rejected_replaced_action_does_not_remove_its_successor(self):
        started, finish = asyncio.Event(), asyncio.Event()
        class Backend:
            async def react(self, *args):
                started.set()
                await finish.wait()
                service.recovery.state = 'offline'
                raise ValueError('reaction refused')
        with tempfile.TemporaryDirectory() as folder:
            service = NS(root=folder, backend=Backend(), client=NS(is_connected=lambda: True),
                         recovery=NS(state='online'))
            queue = PendingActions(service, 'a')
            first = queue.add('react', [1, 7, 'old'], {})
            answered = Mock()
            first.callbacks.append(answered)
            flushing = asyncio.create_task(queue.flush())
            await started.wait()
            replacement = queue.add('react', [1, 7, 'new'], {})
            finish.set()
            await flushing
            self.assertNotIn(first, queue.records)
            self.assertEqual(queue.records, [replacement])
            restored = PendingActions(service, 'a')
            self.assertEqual(restored.records[0].args, [1, 7, 'new'])
            answered.assert_not_called()
            self.assertEqual(replacement.callbacks, [answered])

    async def test_success_after_cancellation_does_not_run_cancelled_callback(self):
        started, finish = asyncio.Event(), asyncio.Event()
        class Backend:
            async def react(self, *args):
                started.set()
                await finish.wait()
                return 'old result'
        with tempfile.TemporaryDirectory() as folder:
            service = NS(root=folder, backend=Backend(), client=NS(is_connected=lambda: True),
                         recovery=NS(state='online'))
            queue = PendingActions(service, 'a')
            record = queue.add('react', [1, 7, 'old'], {})
            answered = Mock()
            record.callbacks.append(answered)
            flushing = asyncio.create_task(queue.flush())
            await started.wait()
            queue.cancel(record.key)
            finish.set()
            await flushing
            answered.assert_not_called()
            self.assertEqual(queue.records, [])

    async def test_cancelling_unstarted_send_does_not_create_backend_coroutine(self):
        app = NS(service=NS(root=Path('.')), demo=True, root=Mock(), worker=Mock())
        box = Outbox(app)
        item = Pending('a', 1, text='queued')
        item.reserve_ids()
        with patch('tg_ascii.outbox.build_operation') as build:
            box.start(item, object())
            wrapper = app.worker.submit.call_args.args[0]
            wrapper.close()
        build.assert_not_called()

    async def test_failed_disk_write_is_not_reported_as_saved_offline(self):
        app = NS(closed=False, closing=False, worker=Mock(), status=Mock())
        manager = DraftManager(app, store=NS(flush=Mock(side_effect=OSError('disk full'))))
        manager.snapshot = Mock()
        manager.sync_pending = AsyncMock()
        manager.persist_async()
        operation, _, failed = app.worker.submit.call_args.args
        with self.assertRaises(OSError) as caught:
            await operation
        with patch('tg_ascii.interface_layout.caption', side_effect=lambda english, spanish: english):
            failed(caught.exception)
        self.assertEqual(app.status.set.call_args.args[0], 'Draft could not be saved: disk full')
        manager.sync_pending.assert_not_awaited()
        self.assertFalse(manager._persist_running)
