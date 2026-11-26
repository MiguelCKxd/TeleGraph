import asyncio
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from telethon import types, utils
from tg_ascii.backend import Message
from tg_ascii.forum_topics import message_topic
from tg_ascii.peer_tools import HistoryPage
from tg_ascii_mobile.core import Core


def photo(ident, video=False):
    return types.Photo(ident, 7, b'ref', datetime.now(timezone.utc), [], 4,
                       video_sizes=[types.VideoSize('v', 640, 480, 15)] if video else [])


class GalleryTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.core = Core(Path(directory.name), 'iOS')
        self.core.loop.close()
        self.core.loop = asyncio.get_running_loop()
        self.backend = SimpleNamespace(client=SimpleNamespace())
        self.core.accounts = SimpleNamespace(current='first', services={
            'first': SimpleNamespace(backend=self.backend), 'second': SimpleNamespace(backend=SimpleNamespace())})

    async def test_shared_comment_route_requires_the_exact_channel_discussion(self):
        group, channel = types.PeerChannel(45), types.PeerChannel(80)
        peer, source = utils.get_peer_id(group), utils.get_peer_id(channel)
        comment = SimpleNamespace(peer_id=group, reply_to=SimpleNamespace(reply_to_top_id=25), fwd_from=None)
        forwarded = SimpleNamespace(peer_id=group, reply_to=None,
                                    fwd_from=SimpleNamespace(from_id=channel, channel_post=90))
        self.backend.forum_message_topic = message_topic
        self.backend.checked_message = AsyncMock(side_effect=lambda peer, id: comment if id == 32 else forwarded)
        self.backend.names = {source: 'Canal'}
        self.backend.discussion_message = AsyncMock(return_value={'peer': peer, 'root_id': 25})
        self.assertEqual(await self.core.api_gallery_origin(peer, 32, 'first'), {
            'account': 'first', 'peer': peer, 'id': 32, 'source': source, 'post': 90, 'root': 25, 'source_name': 'Canal'})
        # A regular forwarded copy and a reply to it stay in the receiving chat.
        self.backend.discussion_message.return_value = {'peer': peer, 'root_id': 19}
        for ident in (25, 32):
            self.assertEqual(await self.core.api_gallery_origin(peer, ident, 'first'),
                             {'account': 'first', 'peer': peer, 'id': ident})

    async def test_shared_topic_and_account_change_during_lookup(self):
        group = types.PeerChannel(45)
        peer = utils.get_peer_id(group)
        raw = SimpleNamespace(peer_id=group, reply_to=SimpleNamespace(forum_topic=True, reply_to_top_id=76))
        self.backend.forum_message_topic = message_topic
        self.backend.checked_message = AsyncMock(return_value=raw)
        self.assertEqual((await self.core.api_gallery_origin(peer, 90, 'first'))['topic'], 76)
        async def switching(*args):
            self.core.accounts.current = 'second'
            return raw
        self.backend.checked_message = switching
        with self.assertRaises(PermissionError):
            await self.core.api_gallery_origin(peer, 90, 'first')

    async def test_context_preserves_scope_cursor_and_independent_window(self):
        group = -1000000000045
        page = HistoryPage([Message(32, 'Alba', 'foto', '12:00')], next_offset=29, more=True)
        self.backend.forum_history = AsyncMock(return_value=page)
        self.backend.discussion_around = AsyncMock(return_value=page)
        self.core.window_discussions[80] = (('first', group, 25), {})
        self.core.open_discussion = ('first', group, 1)
        topic = await self.core.api_context(group, 32, account='first', topic_id=1)
        comment = await self.core.api_context(group, 32, account='first', thread_root=25, window_peer=80)
        self.assertEqual(topic['messages'][0]['id'], comment['messages'][0]['id'])
        self.assertEqual((comment['next'], comment['more']), (29, True))
        self.assertEqual(set(self.core.discussion_messages), {32})
        self.assertEqual(set(self.core.window_discussions[80][1]), {32})
        self.assertNotIn(group, self.core.histories)
        self.backend.forum_history.assert_awaited_once_with(group, 1, around=32)
        self.backend.discussion_around.assert_awaited_once_with(group, 25, 32)
        with self.assertRaisesRegex(ValueError, 'conversation'):
            await self.core.api_context(group, 32, thread_root=25)

    async def test_context_discarded_if_same_topic_reopened_during_read(self):
        self.core.open_discussion = ('first', -45, 7)
        async def reopened(*args, **kwargs):
            self.core.discussion_messages = {}
            return HistoryPage([Message(32, 'Alba', 'foto', '12:00')])
        self.backend.forum_history = reopened
        with self.assertRaisesRegex(ValueError, 'conversation'):
            await self.core.api_context(-45, 32, account='first', topic_id=7)
        self.assertFalse(self.core.discussion_messages)

    async def test_profile_history_pages_keep_int64_and_video_type(self):
        large_id = (1 << 60) + 61
        history = AsyncMock(side_effect=[
            ([photo(large_id - n, n == 0) for n in range(20)], 21),
            ([photo(large_id - 20)], 21)])
        with patch('tg_ascii_mobile.gallery.profile_history', history):
            first = await self.core.api_profile_photos(44, 'first')
            last = await self.core.api_profile_photos(44, 'first', first['next'])
        self.assertEqual(first['items'][0], {'id': str(large_id), 'kind': 'video', 'offset': 0})
        self.assertEqual(last, {'items': [{'id': str(large_id - 20), 'kind': 'image', 'offset': 20}], 'next': None})
        self.assertIn(('first', 44, large_id), self.core.gallery_photos)

    async def test_switch_rejects_pending_history_and_foreign_file(self):
        started, resume = asyncio.Event(), asyncio.Event()

        async def history(*args):
            started.set()
            await resume.wait()
            return [photo(81)], 1

        with patch('tg_ascii_mobile.gallery.profile_history', history):
            loading = asyncio.create_task(self.core.api_profile_photos(10, 'first'))
            await started.wait()
            self.core.accounts.current = 'second'
            resume.set()
            with self.assertRaises(PermissionError):
                await loading
        self.assertFalse(getattr(self.core, 'gallery_photos', None))
        with self.assertRaises(PermissionError):
            await self.core.profile_gallery_file(10, 81, 'first', 0)

    async def test_evicted_id_revalidates_page_and_lock_blocks_export(self):
        with patch('tg_ascii_mobile.gallery.profile_history', AsyncMock(return_value=([photo(701)], 21))) as history:
            path = await self.core.profile_gallery_file(44, 700, 'first', 20)
            history.assert_awaited_once_with(self.backend, 44, 20, 20)
            self.assertIsNone(path)
        self.core.locked = True
        with self.assertRaises(PermissionError):
            await self.core.api_open_profile_photo(44, 'first', 'share', 701, 20)

    async def test_export_rechecks_policy_before_downloading(self):
        self.backend.selected_message_policy = AsyncMock(return_value={'copy': False})
        self.core.media_file = AsyncMock()
        with self.assertRaises(PermissionError):
            await self.core.api_open_file(44, 82, 'save', account='first')
        self.core.media_file.assert_not_awaited()

    async def test_switch_during_native_download_blocks_share(self):
        self.backend.selected_message_policy = AsyncMock(return_value={'copy': True})
        self.core.open_file_with_system = AsyncMock()
        async def download(*args):
            self.core.accounts.current = 'second'
            return self.core.root / 'fixture.jpg'
        self.core.media_file = download
        with self.assertRaises(PermissionError):
            await self.core.api_open_file(44, 82, 'share', account='first')
        self.core.open_file_with_system.assert_not_awaited()

    async def test_two_named_ios_exports_release_only_their_own_files(self):
        original = self.core.root / 'media.png'
        original.write_bytes(b'fixture')
        self.core.media_file = AsyncMock(return_value=original)
        self.core.histories[44] = [Message(i, 'First', '', '12:00', filename='image.png') for i in (30, 31)]
        self.backend.selected_message_policy = AsyncMock(return_value={'copy': True})
        presented = []

        def native(action, name, done, *, release):
            presented.append((Path(name), release))
            done(True)

        self.core.native_open = native
        await asyncio.gather(self.core.api_open_file(44, 30, 'share'), self.core.api_open_file(44, 31, 'save'))
        self.assertEqual([p.read_bytes() for p, _ in presented], [b'fixture', b'fixture'])
        self.assertNotEqual(presented[0][0], presented[1][0])
        presented[0][1]()
        await asyncio.sleep(0)
        self.assertFalse(presented[0][0].exists())
        self.assertTrue(presented[1][0].exists())
        presented[1][1]()
        await asyncio.sleep(0)
        self.assertFalse(presented[1][0].exists())

    async def test_shared_filters_are_server_queries_and_keep_cursor(self):
        self.backend.search_messages = AsyncMock(return_value=[])
        for exposed, expected in [('photos', 'media'), ('photos_only', 'photos'), ('videos', 'videos')]:
            await self.core.api_shared_media(44, exposed, 88, 'first')
            self.backend.search_messages.assert_awaited_with(44, '', expected, 88)
        with self.assertRaises(ValueError):
            await self.core.api_shared_media(44, 'not-a-filter', 0, 'first')

    async def test_account_switch_during_media_index_cannot_use_new_backend_for_old_folder(self):
        self.core._fetch_message = AsyncMock(return_value=SimpleNamespace(media='fixture'))
        async def switching(folder):
            self.core.accounts.current = 'second'
            return {}
        self.core._media_index = switching
        self.backend.download_media = AsyncMock()
        with self.assertRaises(PermissionError):
            await self.core.media_file(44, 82)
        self.backend.download_media.assert_not_awaited()
        self.assertFalse(self.core.__dict__.get('media_jobs'))

    async def test_display_and_original_use_separate_cache_and_previews_remain_small(self):
        self.core._fetch_message = AsyncMock(return_value=SimpleNamespace(media='fixture'))
        qualities = []
        async def download(media, path, *, thumbnail, quality):
            qualities.append((thumbnail, quality))
            path = path.with_suffix('.jpg')
            path.write_bytes(b'thumbnail' if thumbnail else quality.encode())
            return path
        self.backend.download_media = download
        display = await self.core.media_file(44, 82, False, quality='display')
        original = await self.core.media_file(44, 82, False)
        preview = await self.core.media_file(44, 82, True)
        self.assertEqual(display.read_bytes(), b'display')
        self.assertEqual(original.read_bytes(), b'original')
        self.assertEqual(preview.read_bytes(), b'thumbnail')
        self.assertEqual(qualities, [(False, 'display'), (False, 'original'), (True, 'original')])
        self.assertEqual(await self.core.media_file(44, 82, False), original)
        self.assertEqual(len(qualities), 3)
