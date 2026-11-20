from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from telethon import functions, types
from tg_ascii_mobile.core import Core


class MobileStoryTests(IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.core = Core(self.root, 'iOS')
        self.core.loop.close()
        self.backend = SimpleNamespace(client=AsyncMock(), stories=AsyncMock(), publish_story=AsyncMock(),
                                       download_media=AsyncMock(), view_story=AsyncMock())
        self.core.accounts = SimpleNamespace(current='qa', services={'qa': SimpleNamespace(backend=self.backend)})
        self.core.feature = Mock(return_value=True)
        self.core.text = str

    async def test_feed_media_and_read_are_separate(self):
        photo = types.MessageMediaPhoto()
        self.backend.stories.return_value = [SimpleNamespace(peer=types.PeerUser(14), id=2, name='A',
                                                              caption='Caption', media=photo)]
        rows = await self.core.call('stories', {'account': 'qa'})
        self.assertEqual(rows, [dict(peer=14, id=2, name='A', caption='Caption', video=False)])
        self.backend.client.get_peer_id.return_value = 99
        await self.core.call('story_read', {'account': 'qa', 'peer': 99, 'id': 2})
        self.backend.view_story.assert_not_called()
        await self.core.call('story_read', {'account': 'qa', 'peer': 14, 'id': 2})
        self.backend.view_story.assert_awaited_once_with(SimpleNamespace(peer=14, id=2))
        self.backend.client.return_value = SimpleNamespace(stories=[types.StoryItemDeleted(2)])
        self.assertIsNone(await self.core.story_file('qa', 14, 2, self.root))
        self.backend.download_media.assert_not_called()

    async def test_selected_audience_is_forwarded_and_success_removes_staged_file(self):
        path = self.core.staging_path('sample.jpg')
        path.write_bytes(b'fixture')
        params = dict(account='qa', key=path.name, caption='hello', audience='close')
        self.assertTrue(await self.core.call('publish_story', params))
        self.assertIsInstance(self.backend.client.await_args.args[0], functions.stories.CanSendStoryRequest)
        self.backend.publish_story.assert_awaited_once_with(path.resolve(), 'hello', 'close')
        self.assertFalse(path.exists())

    async def test_privacy_or_permissions_failure_never_uploads(self):
        path = self.core.staging_path('photo.jpg')
        path.write_bytes(b'fixture')
        params = dict(account='qa', key=path.name)
        with self.assertRaises(ValueError):
            await self.core.call('publish_story', dict(params, audience='typo'))
        with self.assertRaises(PermissionError):
            await self.core.call('publish_story', dict(params, account='other'))
        self.backend.client.side_effect = RuntimeError('posting limit')
        with self.assertRaisesRegex(RuntimeError, 'posting limit'):
            await self.core.call('publish_story', params)
        self.assertTrue(path.exists())
        self.backend.publish_story.assert_not_called()
