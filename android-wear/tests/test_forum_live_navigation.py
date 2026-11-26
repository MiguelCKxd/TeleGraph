import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from telethon import types
from tg_ascii.backend import Chat, Message
from tg_ascii.forum_topics import ForumTopicUnavailable
from tg_ascii_mobile.core import Core


class LiveForumTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.core = Core(Path(folder.name), 'iOS')
        self.core.loop.close()
        self.core.loop = asyncio.get_running_loop()
        self.backend = SimpleNamespace()
        self.core.accounts = SimpleNamespace(current='one', entries=[], services={'one': SimpleNamespace(backend=self.backend)})
        self.peer = -1000000000041
        self.chat = Chat(self.peer, 'Valle', kind='group', forum=True)
        self.core.chats = [self.chat]

    async def test_failed_list_retains_topic_and_loaded_messages_in_both_windows(self):
        self.backend.forum_topics = AsyncMock(side_effect=ConnectionError('offline'))
        self.core.open_discussion = ('one', self.peer, 7)
        self.core.discussion_messages[10] = Message(10, 'Ana', '', '')
        self.core.window_peers.add(self.peer)
        self.core.window_discussions[self.peer] = (('one', self.peer, 1), {14: Message(14, 'Alba', '', '')})
        for window, topic, message in [(None, 7, 10), (self.peer, 1, 14)]:
            with self.assertRaises(ConnectionError):
                await self.core.api_forum_topics(self.peer, account='one', open_view=True, window_peer=window)
            context, cached = self.core.discussion_view(window)
            self.assertEqual(context, ('one', self.peer, topic))
            self.assertIn(message, cached)

    async def test_delayed_list_cannot_clear_later_navigation(self):
        started, resume = asyncio.Event(), asyncio.Event()
        async def query(*args, **kwargs):
            started.set()
            await resume.wait()
            return {'topics': [], 'next_cursor': None}
        self.backend.forum_topics = query
        self.core.open_discussion = ('one', self.peer, 7)
        request = asyncio.create_task(self.core.api_forum_topics(self.peer, account='one', open_view=True))
        await started.wait()
        self.core.open_revision += 1
        self.core.open_discussion = ('one', self.peer, 9)
        self.core.discussion_messages = {30: Message(30, 'Alba', '', '')}
        resume.set()
        with self.assertRaisesRegex(ValueError, 'conversation'):
            await request
        self.assertEqual(set(self.core.discussion_messages), {30})
        self.assertEqual(self.core.open_discussion, ('one', self.peer, 9))

    async def test_native_forum_window_notifies_and_counts_only_unseen_topics(self):
        self.core.schedule_save = self.core.emit = Mock()
        self.core.prefs = SimpleNamespace(values={'notifications': True, 'notify_preview': False})
        self.core.native_notify = Mock(return_value=True)
        self.core._read_comments = AsyncMock()
        self.core.window_peers.add(self.peer)
        self.core.window_discussions[self.peer] = (('one', self.peer, 7), {})
        self.backend.notification_policy = AsyncMock(return_value={'enabled': True, 'preview': False, 'sound': False})
        for ident, topic in [(21, 7), (22, 1), (23, 9)]:
            await self.core.on_message('one', self.peer, Message(ident, 'Ana', 'Mensaje', '12:00', topic_id=topic))
        self.assertEqual(self.chat.unread, 2)
        self.assertEqual(self.core.native_notify.call_count, 2)
        self.assertEqual(list(self.core.window_discussions[self.peer][1]), [21])
        self.core._read_comments.assert_awaited_once()
        self.core.window_discussions[self.peer] = (None, {})
        await self.core.on_message('one', self.peer, Message(24, 'Ana', 'General', '12:01', topic_id=1))
        self.assertEqual(self.chat.unread, 3)
        self.assertEqual(self.core.native_notify.call_count, 3)
        # An independent main window can read General at the same time.
        self.core.open_discussion = ('one', self.peer, 1)
        await self.core.on_message('one', self.peer, Message(25, 'Ana', 'General', '12:02', topic_id=1))
        self.assertEqual(self.chat.unread, 3)
        self.assertEqual(self.core.native_notify.call_count, 3)

    async def test_metadata_distinguishes_deleted_topic_from_transport_error(self):
        self.backend.forum_topic = AsyncMock(side_effect=ForumTopicUnavailable('deleted'))
        self.assertIsNone(await self.core.api_forum_topic_info(self.peer, 7, 'one'))
        self.backend.forum_topic.side_effect = ConnectionError('offline')
        with self.assertRaises(ConnectionError):
            await self.core.api_forum_topic_info(self.peer, 7, 'one')

    def remote_group(self, forum):
        return types.Channel(41, 'Valle', types.ChatPhotoEmpty(), None, megagroup=True, forum=forum)

    async def test_restoring_a_forum_never_fetches_or_reads_mixed_history(self):
        self.core.histories[self.peer] = [Message(20, 'Alba', 'Otro tema', '')]
        self.core.reload_and_read = self.core.refresh_history = AsyncMock()
        self.core.floating_peers.add(self.peer)
        for read in (False, True):
            result = await self.core.api_window_open(self.peer, 'one', read=read)
            self.assertTrue(result['forum'])
            self.assertEqual(result['chat']['id'], self.peer)
            self.assertNotIn('messages', result)
            self.assertNotIn(self.peer, self.core.floating_peers)
        await asyncio.sleep(0)
        self.core.reload_and_read.assert_not_awaited()

    async def test_old_group_metadata_and_unknown_restored_peer_resolve_on_telegram(self):
        self.chat.forum = False
        self.backend.client = SimpleNamespace(get_entity=AsyncMock(return_value=self.remote_group(True)))
        self.core.reload_and_read = AsyncMock()
        for cached in ([self.chat], []):
            self.core.chats = cached
            self.core.forum_peers = {}
            result = await self.core.api_window_open(self.peer, 'one')
            self.assertEqual(result['chat']['name'], 'Valle')
            self.assertTrue(result['forum'])
            self.assertNotIn(self.peer, self.core.floating_peers)
        self.assertEqual(self.backend.client.get_entity.await_count, 2)
        await asyncio.sleep(0)
        self.core.reload_and_read.assert_not_awaited()

    async def test_window_rechecks_before_queueing_text_or_files_and_keeps_the_draft(self):
        self.chat.forum = False
        self.backend.client = SimpleNamespace(get_entity=AsyncMock(return_value=self.remote_group(False)))
        self.core.api_send = AsyncMock(return_value={'key': 'plain'})
        self.core.api_send_files = AsyncMock(return_value={'key': 'file'})
        self.core.refresh_history = AsyncMock()
        await self.core.api_window_open(self.peer, 'one', read=False)
        self.assertEqual(await self.core.api_window_send(self.peer, 'one', text='Grupo'), {'key': 'plain'})
        self.assertEqual(await self.core.api_window_send(self.peer, 'one', text='Grupo', keys=['key']), {'key': 'file'})
        self.backend.client.get_entity.return_value = self.remote_group(True)
        self.core.draft_store.put('one', self.peer, {'text': 'Borrador pendiente'})
        for files in ([], ['key']):
            response = await self.core.api_window_send(self.peer, 'one', text='Borrador pendiente', keys=files)
            self.assertTrue(response['chat']['forum'])
        self.assertEqual(self.core.draft_record(self.peer)['text'], 'Borrador pendiente')
        self.core.api_send.assert_awaited_once()
        self.core.api_send_files.assert_awaited_once()
        self.assertNotIn(self.peer, self.core.floating_peers)

    async def test_failed_verification_or_changed_account_never_queues_a_window_send(self):
        self.chat.forum = False
        self.core.api_send = AsyncMock()
        self.backend.client = SimpleNamespace(get_entity=AsyncMock(side_effect=ConnectionError('offline')))
        with self.assertRaises(ConnectionError):
            await self.core.api_window_send(self.peer, 'one', text='Todavía en borradores')
        async def switched(peer):
            self.core.accounts.current = 'two'
            return self.remote_group(True)
        self.backend.client.get_entity.side_effect = switched
        with self.assertRaisesRegex(ValueError, 'account changed'):
            await self.core.api_window_send(self.peer, 'one', text='Cuenta anterior')
        self.core.api_send.assert_not_awaited()
        self.assertFalse(self.chat.forum)

    async def test_promoted_group_is_not_marked_read_by_an_older_window_request(self):
        self.chat.forum = False
        async def promote(peer):
            self.chat.forum = True
            self.core.histories[peer] = [Message(20, 'Alba', 'Otro tema', '')]
        self.core.refresh_history = promote
        self.backend.mark_read = AsyncMock()
        await self.core.reload_and_read(self.peer)
        self.backend.mark_read.assert_not_awaited()
