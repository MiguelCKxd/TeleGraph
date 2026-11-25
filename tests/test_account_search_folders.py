import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from telethon import types

from tg_ascii.recent_searches import RecentSearches
from tg_ascii_mobile.core import Core


class AccountStateTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.core = Core(Path(folder.name), 'Android')
        self.core.loop.close()
        self.core.loop = asyncio.get_running_loop()
        self.backend = SimpleNamespace()
        self.core.accounts = SimpleNamespace(current='one', services={
            'one': SimpleNamespace(backend=self.backend), 'two': SimpleNamespace(backend=SimpleNamespace())})

    async def test_delayed_folder_query_cannot_replace_new_account(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def folders():
            started.set()
            await release.wait()
            return ['old folder']

        self.backend.folders = folders
        pending = asyncio.create_task(self.core.api_folders(account='one'))
        await started.wait()
        self.core.accounts.current = 'two'
        self.core.folder_records = []
        release.set()
        with self.assertRaisesRegex(ValueError, 'account'):
            await pending
        self.assertEqual(self.core.folder_records, [])

    async def test_batch_stops_on_account_switch(self):
        seen = []

        async def archive(peer, value):
            seen.append(peer)
            self.core.accounts.current = 'two'

        self.core.api_archive_chat = archive
        with self.assertRaisesRegex(ValueError, 'account'):
            await self.core.api_chats_batch([1, 2], 'archive', account='one')
        self.assertEqual(seen, [1])

    async def test_recent_queries_are_scoped_and_secret_history_is_never_saved(self):
        search = self.core.api_recent_searches
        self.assertEqual(await search('one', 'messages:-2000000000004', 'personal'), [])
        for term in ('Trabajo', 'Patio', 'TRABAJO'):
            await search('one', 'chats', term)
        self.assertEqual(await search('one', 'chats'), ['TRABAJO', 'Patio'])
        self.assertEqual(await search('one', 'contacts'), [])
        self.core.accounts.current = 'two'
        self.assertEqual(await search('two', 'chats'), [])
        await search('two', 'chats', 'Otro')
        store = RecentSearches(self.core.root)
        store.forget_account('one')
        self.assertEqual(store.list('one', 'chats'), [])
        self.assertEqual(store.list('two', 'chats'), ['Otro'])
        self.assertEqual(await search('two', 'chats', clear=True), [])

    async def test_report_uses_the_server_options_and_refuses_foreign_accounts(self):
        client = AsyncMock(side_effect=[
            types.ReportResultChooseOption('Motivo', [types.MessageReportOption('Spam', b'\x00\xfe')]),
            types.ReportResultAddComment(b'comment', optional=True), types.ReportResultReported()])
        client.get_input_entity = AsyncMock(return_value=types.InputPeerSelf())
        self.backend.client = client
        report = self.core.api_report_message
        with self.assertRaises(ValueError):
            await report('two', 42, 123)
        self.assertEqual((await report('one', 42, 123))['options'], [{'text': 'Spam', 'option': '00fe'}])
        comment = await report('one', 42, 123, '00fe')
        self.assertEqual(comment, {'comment': True, 'optional': True, 'option': b'comment'.hex()})
        self.assertEqual(await report('one', 42, 123, comment['option'], 'Ejemplo'), {'reported': True})
        request = client.await_args.args[0]
        self.assertEqual((request.id, request.option, request.message), ([123], b'comment', 'Ejemplo'))
