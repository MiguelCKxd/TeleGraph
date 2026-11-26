"""A transfer may not outlive the account/unlock state which started it."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from tg_ascii_mobile.server import Server


class Writer:
    def __init__(self, mutate=lambda: None):
        self.parts, self.drains, self.mutate = [], 0, mutate
        self.tg_keep = False

    def write(self, payload):
        self.parts.append(bytes(payload))

    async def drain(self):
        self.drains += 1
        # Headers, then the first payload block: simulate the next UI action.
        if self.drains == 2:
            self.mutate()


class TransferContextTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.payload = b'x' * (3 * 65536)
        self.path = self.root / 'video.mp4'
        self.path.write_bytes(self.payload)
        self.core = NS(root=self.root, token='fixture', account='first', backend=object(), locked=False,
                       staging_path=lambda name: self.root / name)
        self.server = Server(self.core)
        self.headers = {'x-tg-token': 'fixture'}

    async def asyncTearDown(self):
        for task in self.server.story_downloads.values():
            task.expiry.cancel()
            task.cancel()
        await asyncio.gather(*self.server.story_downloads.values(), return_exceptions=True)
        for task in self.server.story_downloads.values():
            if not task.cancelled() and task.exception() is None:
                task.result()[0].cleanup()

    async def test_secret_stream_stops_on_lock_or_account_change(self):
        self.core.secret_preview_file = AsyncMock(return_value=self.path)
        for attr, value in [('locked', True), ('account', 'second'), ('backend', object())]:
            with self.subTest(change=attr):
                self.core.locked, self.core.account = False, 'first'
                writer = Writer(lambda: setattr(self.core, attr, value))
                with self.assertRaises(ConnectionError):
                    await self.server.secret_media(writer, self.headers, {}, 1, 2, False)
                self.assertEqual(b''.join(writer.parts).count(b'HTTP/1.1 '), 1)
                self.assertEqual(sum(map(len, writer.parts[1:])), 65536)

    async def test_story_stream_stops_on_lock_or_backend_change(self):
        def backend(account):
            if self.core.locked or self.core.account != account:
                raise PermissionError('context changed')
            return self.core.backend
        self.core.story_backend = backend
        self.core.story_file = AsyncMock(return_value=self.path)
        for attr, value in [('locked', True), ('backend', object())]:
            with self.subTest(change=attr):
                self.core.locked = False
                writer = Writer(lambda: setattr(self.core, attr, value))
                with self.assertRaises(ConnectionError):
                    await self.server.story(writer, self.headers, {'account': 'first', 'peer': '1', 'id': '2', 'view': attr})
                self.assertEqual(sum(map(len, writer.parts[1:])), 65536)

    async def test_staged_file_stops_on_account_change(self):
        self.core.staged = lambda key: self.path
        writer = Writer(lambda: setattr(self.core, 'account', 'second'))
        with self.assertRaises(ConnectionError):
            await self.server.staged(writer, self.headers, {})
        self.assertEqual(sum(map(len, writer.parts[1:])), 65536)

    async def test_upload_cancellation_removes_partial_file(self):
        reader = NS(read=AsyncMock(side_effect=[b'abc', asyncio.CancelledError()]))
        with self.assertRaises(asyncio.CancelledError):
            await self.server.upload(reader, Writer(), self.headers, {'name': 'pending.bin'}, 6)
        self.assertFalse((self.root / 'pending.bin').exists())

    async def test_upload_drops_last_chunk_after_lock_or_account_change(self):
        for attr, value in [('locked', True), ('account', 'second'), ('backend', object())]:
            with self.subTest(change=attr):
                self.core.locked, self.core.account = False, 'first'
                async def read(size):
                    setattr(self.core, attr, value)
                    return b'abc'
                writer = Writer()
                await self.server.upload(NS(read=read), writer, self.headers, {'name': 'pending.bin'}, 3)
                self.assertTrue(writer.parts[0].startswith(b'HTTP/1.1 403 '))
                self.assertFalse((self.root / 'pending.bin').exists())
                self.assertFalse(writer.tg_keep)

    async def test_successful_upload_preserves_bytes_and_key(self):
        writer = Writer()
        await self.server.upload(NS(read=AsyncMock(return_value=b'abc')), writer, self.headers,
                                 {'name': 'pending.bin'}, 3, True)
        self.assertEqual((self.root / 'pending.bin').read_bytes(), b'abc')
        self.assertIn(b'"key": "pending.bin"', writer.parts[1])
        self.assertTrue(writer.tg_keep)

    async def test_abandoned_story_readers_release_downloads_and_cache(self):
        active, finished = set(), set()
        self.core.story_backend = lambda account: self.core.backend
        async def download(account, peer, ident, directory):
            active.add(ident)
            try:
                await asyncio.Event().wait()
            finally:
                active.discard(ident)
                finished.add(ident)
        self.core.story_file = download
        for ident in range(10):
            request = asyncio.create_task(self.server.story(Writer(), self.headers,
                {'account': 'first', 'peer': '1', 'id': str(ident), 'view': str(ident)}))
            while ident not in active:
                await asyncio.sleep(0)
            request.cancel()
            await asyncio.gather(request, return_exceptions=True)
        self.assertEqual(active, set())
        self.assertEqual(finished, set(range(10)))
        self.assertEqual(self.server.story_downloads, {})

    async def test_shared_story_download_survives_one_cancelled_reader(self):
        started, release = asyncio.Event(), asyncio.Event()
        self.core.story_backend = lambda account: self.core.backend
        async def download(*args):
            started.set()
            await release.wait()
            return self.path
        self.core.story_file = AsyncMock(side_effect=download)
        query = {'account': 'first', 'peer': '1', 'id': '2', 'view': 'same'}
        first = asyncio.create_task(self.server.story(Writer(), self.headers, query))
        await started.wait()
        writer = Writer()
        second = asyncio.create_task(self.server.story(writer, self.headers, query))
        await asyncio.sleep(0)
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        release.set()
        await second
        self.core.story_file.assert_awaited_once()
        self.assertEqual(b''.join(writer.parts[1:]), self.payload)

    async def test_profile_and_wallpaper_streams_stop_after_lock(self):
        self.core.profile_gallery_file = AsyncMock(return_value=self.path)
        self.core.chat_wallpaper_file = lambda *args: self.path
        for path in ('/profile-photo', '/chat-wallpaper'):
            with self.subTest(path=path):
                self.core.locked = False
                writer = Writer(lambda: setattr(self.core, 'locked', True))
                with self.assertRaises(ConnectionError):
                    await self.server.route(writer, 'GET', path, self.headers,
                        {'peer': '1', 'photo': '2', 'account': 'first'}, b'')
                self.assertEqual(sum(map(len, writer.parts[1:])), 65536)

    async def test_disconnected_story_reader_cancels_pending_download(self):
        started = asyncio.Event()
        self.core.story_backend = lambda account: self.core.backend
        async def download(*args):
            started.set()
            await asyncio.Event().wait()
        self.core.story_file = download
        writer = Writer()
        writer.is_closing = lambda: started.is_set()
        with self.assertRaises(ConnectionError):
            await self.server.story(writer, self.headers,
                {'account': 'first', 'peer': '1', 'id': '2', 'view': 'closed'})
        self.assertEqual(self.server.story_downloads, {})
