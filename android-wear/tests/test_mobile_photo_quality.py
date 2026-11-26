import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from tg_ascii.drafts import DraftStore
from tg_ascii.outbox import Outbox, build_operation
from tg_ascii_mobile.core import Core


class MobilePhotoQualityTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.core = Core(self.root, 'iOS')
        self.core.loop.close()
        self.core.loop = asyncio.get_running_loop()
        self.backend = SimpleNamespace(save_draft=AsyncMock(), fetch_drafts=AsyncMock(return_value={}),
                                       _protected_drafts=set())
        self.core.accounts = SimpleNamespace(current='first', services={
            'first': SimpleNamespace(backend=self.backend)})
        self.core.stage = 'ready'
        self.host = SimpleNamespace(demo=False, closed=True, service=SimpleNamespace(root=self.root))
        self.core.outbox = Outbox(self.host)
        self.photo = self.core.staging_path('photo.png')
        self.photo.write_bytes(b'original photo fixture')
        self.video = self.core.staging_path('video.mp4')
        self.video.write_bytes(b'original video fixture')

    async def asyncTearDown(self):
        for task in list(self.core.draft_jobs.values()):
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_quality_survives_draft_restart_and_cloud_update_without_entering_cloud_rpc(self):
        await self.core.api_draft(10, 'first', 'Caption', files=[self.photo.name], photo_quality='hd')
        await self.core.sync_drafts('first', self.backend)
        self.backend.save_draft.assert_awaited_once_with(10, 'Caption', [], [], None)
        self.core.draft_store = DraftStore(self.root / 'mobile')
        self.assertEqual(self.core.draft_record(10)['photo_quality'], 'hd')
        self.core.receive_draft(10, {'text': 'Updated elsewhere'})
        restored = self.core.draft_record(10)
        self.assertEqual(restored['photo_quality'], 'hd')
        self.assertEqual(restored['files'][0]['key'], self.photo.name)
        self.assertEqual(restored['text'], 'Updated elsewhere')
        self.assertNotIn('photo_quality', self.core.draft_record(11))
        self.core.accounts.current = 'other'
        self.assertNotIn('photo_quality', self.core.draft_record(10))

    async def test_selected_quality_is_persisted_in_outbox_for_single_album_and_forum(self):
        for index, quality in enumerate(('sd', 'hd', 'original')):
            peer = 10 + index
            params = {'thread_root': 7, 'topic_id': 7} if quality == 'original' else {}
            paths = [self.photo.name, self.video.name] if quality == 'hd' else [self.photo.name]
            await self.core.api_send_files(peer, paths, caption='Caption', account='first',
                                           photo_quality=quality, **params)
        restored = Outbox(self.host)
        self.assertEqual([item.photo_quality for item in restored.items], ['sd', 'hd', 'original'])
        self.assertEqual(self.photo.read_bytes(), b'original photo fixture')
        self.assertEqual(self.video.read_bytes(), b'original video fixture')
        sender = SimpleNamespace(send_formatted=AsyncMock(), send_batch=AsyncMock(), forum_send=AsyncMock())
        for item, method in zip(restored.items, ('send_formatted', 'send_batch', 'forum_send')):
            await build_operation(sender, item)
            self.assertEqual(getattr(sender, method).await_args.kwargs['photo_quality'], item.photo_quality)
        restored.items[1].state = 'failed'
        restored.retry(restored.items[1])
        self.assertEqual(Outbox(self.host).items[1].photo_quality, 'hd')
        self.assertEqual(restored.items[2].topic_id, 7)

    async def test_floating_window_preserves_quality_and_rejects_other_account(self):
        await self.core.api_window_send(10, 'first', keys=[self.photo.name], photo_quality='original')
        self.assertEqual(self.core.outbox.items[0].photo_quality, 'original')
        with self.assertRaisesRegex(ValueError, 'account'):
            await self.core.api_window_send(10, 'other', keys=[self.photo.name], photo_quality='hd')
        self.assertEqual(len(self.core.outbox.items), 1)

    async def test_invalid_quality_is_rejected_before_queue_or_draft_changes(self):
        for quality in ('hdr', '', 10, {}):
            with self.subTest(quality=quality):
                with self.assertRaises((ValueError, TypeError)):
                    await self.core.api_send_files(10, [self.photo.name], account='first', photo_quality=quality)
                with self.assertRaises((ValueError, TypeError)):
                    await self.core.api_draft(10, 'first', 'Caption', files=[self.photo.name], photo_quality=quality)
        self.assertFalse(self.core.outbox.items)
        self.assertFalse(self.core.draft_store.records)
