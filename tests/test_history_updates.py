import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from tg_ascii.backend import Chat, Message
from tg_ascii_mobile.core import Core


class HistoryUpdateTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.core = Core(Path(folder.name), 'Android')
        self.core.loop.close()
        self.core.loop = asyncio.get_running_loop()
        self.backend = SimpleNamespace()
        self.core.accounts = SimpleNamespace(current='qa', services={'qa': SimpleNamespace(backend=self.backend)})
        self.core.chats = [Chat(5, 'Test')]
        self.core.schedule_save = Mock()
        self.core.emit = Mock()
        self.core.notify = AsyncMock()

    async def test_events_during_first_history_and_older_page(self):
        started = asyncio.Event()
        resume = asyncio.Event()

        async def stale_history(*args):
            started.set()
            await resume.wait()
            return [Message(1, 'A', 'Old text', '12:00'), Message(2, 'B', 'Removed', '12:01'),
                    Message(3, 'Me', 'Outgoing', '12:02', outgoing=True)]

        self.backend.history = self.backend.older_messages = stale_history
        latest = asyncio.create_task(self.core.reload_history(5))
        await started.wait()
        started.clear()
        older = asyncio.create_task(self.core.api_older(5, 4))
        await started.wait()
        self.core.on_change('qa', 'delete', (None, [2]))
        self.core.on_change('qa', 'edit', (5, Message(1, 'A', 'Correction', '12:00')))
        self.core.on_message('qa', 5, Message(4, 'B', 'Arrived during load', '12:03'))
        self.core.on_change('qa', 'read', (5, 3))
        resume.set()
        await latest
        page = await older
        self.assertEqual([m.id for m in self.core.histories[5]], [1, 3, 4])
        self.assertEqual(self.core.histories[5][0].text, 'Correction')
        self.assertTrue(self.core.histories[5][1].read)
        self.assertEqual([m['id'] for m in page['messages']], [1, 3])
        self.assertEqual(page['messages'][0]['text'], 'Correction')
        self.assertFalse(self.core.history_requests)

    async def test_older_page_can_finish_before_first_history(self):
        started, resume = asyncio.Event(), asyncio.Event()

        async def latest(peer):
            started.set()
            await resume.wait()
            return [Message(3, 'A', 'Newest', '12:00')]

        self.backend.history = latest
        self.backend.older_messages = AsyncMock(return_value=[Message(1, 'A', 'Older', '10:00')])
        task = asyncio.create_task(self.core.reload_history(5))
        await started.wait()
        await self.core.api_older(5, 2)
        resume.set()
        await task
        self.assertEqual([m.id for m in self.core.histories[5]], [1, 3])

    async def test_cancelled_context_releases_pending_events(self):
        started = asyncio.Event()

        async def wait(*args):
            started.set()
            await asyncio.Future()

        self.backend.message_context = wait
        task = asyncio.create_task(self.core.api_context(5, 7))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.core.history_requests)
