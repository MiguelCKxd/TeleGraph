import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from telethon import functions as f, types as t, utils
from tg_ascii.peer_tools import PeerTools


class DiscussionTests(unittest.IsolatedAsyncioTestCase):
    def backend(self):
        backend = PeerTools(); backend.client = AsyncMock()
        backend.cache_name = lambda *_: None
        backend.resolve_missing_senders = AsyncMock()
        backend.message = lambda value: NS(id=value.id)
        backend.client.get_input_entity.return_value = t.InputPeerChannel(5, 10)
        return backend

    async def test_discussion_resolves_group_root_not_original_channel_post(self):
        backend = self.backend()
        backend.client.return_value = NS(messages=[NS(id=8, peer_id=t.PeerChannel(5)),
            NS(id=99, peer_id=t.PeerChannel(7))], users=[], chats=[], unread_count=2)
        result = await backend.discussion_message(-1000000000005, 8)
        request = backend.client.call_args.args[0]
        self.assertIsInstance(request, f.messages.GetDiscussionMessageRequest)
        self.assertEqual(request.msg_id, 8)
        self.assertEqual(result['root_id'], 99)
        self.assertEqual(result['peer'], utils.get_peer_id(t.PeerChannel(7)))
        self.assertEqual(result['unread_count'], 2)
        self.assertEqual(backend.client.await_count, 1)  # No JoinChannel or read receipt.
        bytes(request)

    async def test_missing_discussion_does_not_select_original_post(self):
        backend = self.backend()
        backend.client.return_value = NS(messages=[NS(id=8, peer_id=t.PeerChannel(5))], users=[], chats=[])
        with self.assertRaises(ValueError): await backend.discussion_message(5, 8)

    async def test_thread_history_uses_reply_filter_and_keeps_pagination_cursor(self):
        backend = self.backend()
        backend.client.return_value = NS(messages=[NS(id=200-i) for i in range(80)], users=[], chats=[])
        page = await backend.discussion_history(7, 99, 201)
        request = backend.client.call_args.args[0]
        self.assertIsInstance(request, f.messages.GetRepliesRequest)
        self.assertEqual((request.msg_id, request.offset_id), (99, 201))
        self.assertEqual(page.next_offset, 121)
        self.assertTrue(page.more)
        self.assertEqual([page[0].id, page[-1].id], [121, 200])
        bytes(request)

    async def test_invalid_thread_arguments_never_reach_server(self):
        backend = self.backend()
        for invalid in (True, 0, -1, None, '99'):
            with self.assertRaises(ValueError): await backend.discussion_history(7, invalid)
        backend.client.assert_not_awaited()

    async def test_read_discussion_never_marks_whole_group_read(self):
        backend = self.backend()
        await backend.read_discussion(7, 99, 130)
        request = backend.client.call_args.args[0]
        self.assertIsInstance(request, f.messages.ReadDiscussionRequest)
        self.assertEqual((request.msg_id, request.read_max_id), (99, 130))
        bytes(request)


class DiscussionWindowTests(unittest.TestCase):
    def test_live_events_are_scoped_to_the_account_group_and_thread(self):
        from test_interface_windows import window_model
        from tg_ascii.backend import Message
        window = window_model()
        window.thread_id = 99
        window.receive('a', 41, Message(110, 'Other', 'unrelated', ''))
        window.receive('b', 41, Message(111, 'Wrong account', '', '', thread_id=99))
        window.receive('a', 42, Message(112, 'Wrong group', '', '', thread_id=99))
        comment = Message(113, 'Commenter', '', '', thread_id=99)
        window.receive('a', 41, comment)
        direct = Message(114, 'Direct', '', '', reply_to_id=99)
        window.receive('a', 41, direct)
        self.assertEqual(window.messages, [comment, direct])
        window.change('a', 'edit', (41, Message(110, 'Other', 'changed', '')))
        self.assertEqual(window.messages, [comment, direct])

    def test_group_drafts_never_replace_thread_composer(self):
        from test_interface_windows import window_model
        from unittest.mock import Mock
        window = window_model()
        window.thread_id = 99
        window.remote_draft = Mock()
        window.change('a', 'draft', (41, {'text': 'group draft'}))
        window.remote_draft.assert_not_called()
        window.app.demo = False
        window.valid = Mock(return_value=True)
        window.composer_focused = Mock(return_value=True)
        window._draft_edited = True
        window.call = Mock()
        window.sync_draft({'text': 'thread draft'})
        window.call.assert_not_called()

if __name__ == '__main__': unittest.main()
