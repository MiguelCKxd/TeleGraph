import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from tg_ascii.backend import Chat, Message
from tg_ascii.peer_tools import HistoryPage
from tg_ascii_mobile.core import Core


class ForumNavigationTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.core = Core(Path(folder.name), 'Android')
        self.core.loop.close()
        self.core.loop = asyncio.get_running_loop()
        self.backend = SimpleNamespace()
        self.core.accounts = SimpleNamespace(current='one', services={
            'one': SimpleNamespace(backend=self.backend),
            'two': SimpleNamespace(backend=SimpleNamespace())})
        self.peer = -100111
        self.core.chats = [Chat(self.peer, 'Forum', kind='group', entity=SimpleNamespace(forum=True))]
        self.backend.forum_topic = AsyncMock(return_value={'id': 7, 'title': 'Music', 'can_send': True})
        self.backend.forum_history = AsyncMock(return_value=HistoryPage([Message(21, 'Ana', 'music', '12:00')], next_offset=21, more=False))
        self.backend.forum_mark_read = AsyncMock()
        self.backend.read_discussion = AsyncMock()

    async def test_forum_list_does_not_read_other_topics(self):
        self.backend.forum_topics = AsyncMock(return_value={'topics': [], 'next_cursor': None})
        self.core.open_peer = self.peer
        self.core.open_discussion = ('one', self.peer, 7)
        await self.core.api_forum_topics(self.peer, open_view=True, account='one')
        self.assertIsNone(self.core.open_peer)
        self.assertIsNone(self.core.open_discussion)
        self.backend.forum_mark_read.assert_not_awaited()
        self.backend.read_discussion.assert_not_awaited()

    async def test_open_and_read_only_requested_topic(self):
        result = await self.core.api_forum_open(self.peer, 7, account='one')
        await asyncio.sleep(0)
        self.assertEqual(result['topic']['title'], 'Music')
        self.assertEqual(self.core.open_discussion, ('one', self.peer, 7))
        self.assertEqual(set(self.core.discussion_messages), {21})
        await self.core._read_comments(self.backend, self.peer, 7, [Message(21, 'Ana', '', '')])
        self.backend.forum_mark_read.assert_awaited_with(self.peer, 7, 21)
        self.backend.read_discussion.assert_not_awaited()

    async def test_topic_from_old_account_cannot_open_on_new_account(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def delayed(*args, **kwargs):
            started.set()
            await release.wait()
            return {'id': 7}
        self.backend.forum_topic = delayed
        task = asyncio.create_task(self.core.api_forum_open(self.peer, 7, account='one'))
        await started.wait()
        self.core.accounts.current = 'two'
        release.set()
        with self.assertRaisesRegex(ValueError, 'account'):
            await task
        self.assertIsNone(self.core.open_discussion)
        self.backend.forum_history.assert_not_awaited()

    async def test_older_topic_open_cannot_replace_new_navigation(self):
        started, release = asyncio.Event(), asyncio.Event()
        page = HistoryPage([Message(21, 'Ana', '', '')], next_offset=21, more=False)
        async def delayed(*args, **kwargs):
            started.set()
            await release.wait()
            return page
        self.backend.forum_history = delayed
        task = asyncio.create_task(self.core.api_forum_open(self.peer, 7, account='one'))
        await started.wait()
        self.core.open_revision += 1
        release.set()
        with self.assertRaisesRegex(ValueError, 'conversation'):
            await task
        self.assertIsNone(self.core.open_discussion)
