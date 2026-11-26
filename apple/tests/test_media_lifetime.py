import asyncio
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from tg_ascii_mobile.core import Core
from tg_ascii_mobile.media_lifetime import media_response
from tg_ascii_mobile.server import Server


class MediaLifetimeTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.core = Core(self.root, 'iOS')
        self.core.loop.close()
        self.core.loop = asyncio.get_running_loop()
        self.backend = SimpleNamespace(download_media=self.download)
        self.core.accounts = SimpleNamespace(current='first', services={
            'first': SimpleNamespace(backend=self.backend), 'second': SimpleNamespace(backend=None)})
        self.raw = SimpleNamespace(id=8, media=SimpleNamespace(ttl_seconds=10), date=datetime.now(timezone.utc))
        self.core._fetch_message = AsyncMock(side_effect=lambda *args: self.raw)
        self.paths, self.gate, self.finished = [], None, asyncio.Event()
        self.started = asyncio.Event()
        self.payload = b'\xff\xd8\xfftemporary-original'
        self.server = Server(self.core)
        self.port = await self.server.start()
        self.addAsyncCleanup(self.cleanup)

    async def cleanup(self):
        await self.core.close_media_requests()
        self.server.video_ranges.close()
        self.server.server.close()
        await self.server.server.wait_closed()

    async def download(self, media, path, *, thumbnail, quality):
        self.assertFalse(path.suffix, 'An explicit suffix could use the shared preview cache')
        self.paths.append(path)
        self.started.set()
        partial = path.with_suffix('.part')
        partial.write_bytes(b'partial')
        try:
            if self.gate is not None:
                await self.gate.wait()
            target = path.with_suffix('.ogg' if self.payload.startswith(b'OggS') else '.jpg')
            target.write_bytes(self.payload)
            return target
        finally:
            partial.unlink(missing_ok=True)
            self.finished.set()

    def files(self):
        return [path for path in self.root.rglob('*') if path.is_file()]

    async def request(self, query='thumb=0'):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.port)
        writer.write((f'GET /media?peer=42&id=8&{query} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n'
                      f'X-TG-Token: {self.core.token}\r\nConnection: close\r\n\r\n').encode())
        await writer.drain()
        try:
            response = await asyncio.wait_for(reader.read(), 5)
            head, body = response.split(b'\r\n\r\n', 1)
            return head.decode(), body
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_self_destruct_original_and_thumbnail_have_no_disk_or_http_cache(self):
        for query in ('thumb=0', 'thumb=1&v=fixture'):
            head, body = await self.request(query)
            self.assertIn('200 OK', head)
            self.assertIn('Cache-Control: no-store', head)
            self.assertEqual(body, self.payload)
            self.assertEqual(self.files(), [])
            self.assertFalse(self.core.__dict__.get('media_indexes'))

    async def test_auto_delete_and_protected_content_remain_viewable_without_retention(self):
        variants = [dict(ttl_period=60), dict(noforwards=True), dict(protected=True)]
        for policy in variants:
            self.raw = SimpleNamespace(id=8, media=SimpleNamespace(), date=datetime.now(timezone.utc), **policy)
            head, body = await self.request()
            self.assertIn('200 OK', head)
            self.assertEqual(body, self.payload)
            self.assertEqual(self.files(), [])

    async def test_chat_protection_is_respected_even_when_raw_message_has_no_flag(self):
        self.raw.media.ttl_seconds = None
        self.core.chats = [SimpleNamespace(id=42, entity=SimpleNamespace(noforwards=True))]
        _, body = await self.request()
        self.assertEqual(body, self.payload)
        self.assertEqual(self.files(), [])

    async def test_temporary_poll_attachment_and_article_photo_use_same_response_lifetime(self):
        from telethon import types
        photo = types.Photo(123, 2, b'ref', datetime.now(timezone.utc), [], 4)
        poll = types.Poll(1, types.TextWithEntities('question', []), [], 5)
        self.raw.media = types.MessageMediaPoll(poll, types.PollResults(),
                                                attached_media=types.MessageMediaPhoto(photo=photo))
        self.raw.ttl_period = 60
        head, body = await self.request('thumb=0&poll=attached')
        self.assertIn('200 OK', head)
        self.assertEqual(body, self.payload)
        self.assertEqual(self.files(), [])
        self.raw.media = None
        self.raw.rich_message = SimpleNamespace(photos=[photo], part=False)
        head, body = await self.request('thumb=0&photo=0')
        self.assertIn('200 OK', head)
        self.assertEqual(body, self.payload)
        self.assertEqual(self.files(), [])

    async def test_stream_fallback_uses_one_message_lookup_and_no_persistent_download(self):
        from telethon import types
        document = types.Document(123, 1, b'ref', datetime.now(timezone.utc), 'video/mp4', 8, 4, [])
        self.raw.media = types.MessageMediaDocument(document=document, ttl_seconds=10)
        head, body = await self.request('thumb=0&stream=fixture')
        self.assertIn('200 OK', head)
        self.assertEqual(body, self.payload)
        self.core._fetch_message.assert_awaited_once()
        self.assertEqual(self.files(), [])

    async def test_preload_and_export_cannot_persist_and_old_variants_are_purged(self):
        folder = self.core.media_folder()
        folder.mkdir(parents=True)
        for name in ('42-8.jpg', '42-8-t.jpg', '42-8-d.jpg', '42-8-play-v2.caf', '42-80.jpg'):
            (folder / name).write_bytes(b'legacy')
        with self.assertRaises(PermissionError):
            await self.core.media_file(42, 8)
        with self.assertRaises(PermissionError):
            await self.core.api_open_file(42, 8, 'file')
        self.assertEqual([p.name for p in self.files()], ['42-80.jpg'])
        self.assertEqual(self.paths, [])

    async def test_two_readers_share_download_and_last_response_releases_file(self):
        self.gate = asyncio.Event()
        release_first, release_second = asyncio.Event(), asyncio.Event()
        got_first, got_second = asyncio.Event(), asyncio.Event()
        async def reader(ready, release):
            async with media_response(self.core):
                path = await self.core.media_file(42, 8, False)
                ready.set()
                await release.wait()
                self.assertEqual(path.read_bytes(), self.payload)
        first = asyncio.create_task(reader(got_first, release_first))
        second = asyncio.create_task(reader(got_second, release_second))
        await self.started.wait()
        self.gate.set()
        await got_first.wait()
        await got_second.wait()
        self.assertEqual(len(self.paths), 1)
        release_first.set()
        await first
        self.assertEqual(len(self.files()), 1)
        release_second.set()
        await second
        self.assertEqual(self.files(), [])

    async def test_cancel_last_reader_cancels_download_and_removes_partial(self):
        self.gate = asyncio.Event()
        async def reader():
            async with media_response(self.core):
                await self.core.media_file(42, 8)
        task = asyncio.create_task(reader())
        await self.started.wait()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(self.finished.is_set())
        self.assertEqual(self.files(), [])
        self.assertFalse(self.core._transient_media.entries)

    async def test_account_change_during_download_sends_no_bytes_or_leftovers(self):
        self.gate = asyncio.Event()
        task = asyncio.create_task(self.request())
        await self.started.wait()
        self.core.accounts.current = 'second'
        self.gate.set()
        head, body = await task
        self.assertIn('403 Forbidden', head)
        self.assertNotIn(self.payload, body)
        self.assertEqual(self.files(), [])

    async def test_server_deleted_message_does_not_resurrect_legacy_cache(self):
        folder = self.core.media_folder()
        folder.mkdir(parents=True)
        (folder / '42-8.jpg').write_bytes(b'legacy')
        self.raw = SimpleNamespace(id=8, media=None)
        head, body = await self.request()
        self.assertIn('404 Not Found', head)
        self.assertNotIn(b'legacy', body)
        self.assertEqual(self.files(), [])

    async def test_expired_auto_delete_message_is_never_downloaded(self):
        self.raw.ttl_period = 1
        self.raw.date = 1
        head, _ = await self.request()
        self.assertIn('403 Forbidden', head)
        self.assertEqual(self.paths, [])

    async def test_expiry_and_explicit_close_remove_files_before_response_finishes(self):
        self.raw.ttl_period = 1
        self.raw.date = datetime.now(timezone.utc).timestamp() - .9
        async with media_response(self.core) as response:
            path = await self.core.media_file(42, 8)
            self.assertTrue(path.is_file())
            await asyncio.sleep(.15)
            with self.assertRaises(PermissionError):
                response.check()
            self.assertFalse(path.exists())
        self.raw.ttl_period = 0
        async with media_response(self.core) as response:
            path = await self.core.media_file(42, 8)
            await self.core.close_media_requests()
            self.assertFalse(path.exists())
            with self.assertRaises(PermissionError):
                response.check()

    async def test_delete_event_revokes_active_view_and_blocks_remaining_reads(self):
        async with media_response(self.core) as response:
            path = await self.core.media_file(42, 8)
            self.core._transient_media.revoke('first', 42, [8])
            self.assertFalse(path.exists())
            with self.assertRaises(PermissionError):
                response.check()

    async def test_ios_audio_remux_is_removed_together_with_source(self):
        from tg_ascii_mobile.opus_mux import write_ogg
        self.payload = write_ogg([bytes.fromhex('f8fffe')] * 30)
        head, body = await self.request('thumb=0&play=caf')
        self.assertIn('200 OK', head)
        self.assertEqual(body[:4], b'caff')
        self.assertEqual(self.files(), [])

    async def test_offline_ordinary_snapshot_keeps_cache_but_unknown_legacy_file_is_not_trusted(self):
        self.core.accounts.services['first'].backend = None
        folder = self.core.media_folder()
        folder.mkdir(parents=True)
        ordinary = folder / '42-8.jpg'
        ordinary.write_bytes(b'ordinary')
        with self.assertRaises(ConnectionError):
            await self.core.media_file(42, 8, False)
        self.core.histories[42] = [SimpleNamespace(id=8, media=None)]
        self.assertEqual(await self.core.media_file(42, 8, False), ordinary)
        self.core._fetch_message.assert_not_awaited()
