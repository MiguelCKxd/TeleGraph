"""Companion requests keep the account that supplied their ChatItem."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from tg_ascii_mobile.core import Core


class WatchRequestContextTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.core = Core(Path(folder.name), 'iOS')
        self.addCleanup(self.core.loop.close)
        self.core.accounts = NS(current='b', services={'b': NS(backend=NS()), 'c': NS(backend=NS())})
        self.core.stage = 'ready'

    async def test_all_stale_chat_helpers_refuse_before_access_or_mutation(self):
        names = ('avatar_file', 'api_message_read_details', 'api_move_pin', 'api_translate',
                 'api_secret_info', 'api_secret_ttl', 'api_secret_start')
        for name in names:
            setattr(self.core, name, AsyncMock(return_value={}))
        for op in ('avatar', 'message_dates', 'move_pin', 'translate', 'secret_info', 'secret_ttl', 'secret_start'):
            with self.subTest(op=op), self.assertRaisesRegex(ValueError, 'account changed'):
                await self.core.watch_request(dict(op=op, account='a', peer=42, id=7,
                                                   ids=[7], direction=1, seconds=30))
        for name in names:
            getattr(self.core, name).assert_not_awaited()

    async def test_matching_account_keeps_helper_operational(self):
        self.core.api_move_pin = AsyncMock(return_value=True)
        self.assertEqual(await self.core.watch_request(dict(op='move_pin', account='b', peer=42, direction=1)),
                         {'ok': True})
        self.core.api_move_pin.assert_awaited_once_with(42, 1, 'b')

    async def test_pending_translation_never_returns_old_account_text(self):
        async def changed(*args, **kwargs):
            self.core.accounts.current = 'c'
            return {'7': {'text': 'private B'}}
        self.core.api_translate = AsyncMock(side_effect=changed)
        with self.assertRaisesRegex(ValueError, 'account changed'):
            await self.core.watch_request(dict(op='translate', account='b', peer=42, ids=[7], language='es'))

    async def test_secret_ttl_never_queries_replacement_backend(self):
        replacement = NS(secret_chat_info=AsyncMock())
        async def changed(*args):
            self.core.accounts.current = 'c'
            self.core.accounts.services[self.core.account].backend = replacement
        original = NS(set_secret_ttl=AsyncMock(side_effect=changed), secret_chat_info=AsyncMock())
        self.core.accounts.services['b'].backend = original
        with self.assertRaisesRegex(ValueError, 'account changed'):
            await self.core.api_secret_ttl(42, 30)
        original.secret_chat_info.assert_not_awaited()
        replacement.secret_chat_info.assert_not_awaited()

    async def test_secret_start_never_refreshes_replacement_account(self):
        async def changed(*args):
            self.core.accounts.current = 'c'
            return object()
        self.core.accounts.services['b'].backend = NS(start_secret_chat=AsyncMock(side_effect=changed))
        self.core.refresh_chats = AsyncMock()
        self.core.chat_json = Mock()
        with self.assertRaisesRegex(ValueError, 'account changed'):
            await self.core.api_secret_start(42)
        self.core.refresh_chats.assert_not_awaited()
        self.core.chat_json.assert_not_called()

    async def test_secret_rekey_never_queries_replacement_backend(self):
        replacement = NS(secret_chat_info=AsyncMock())
        async def changed(*args):
            self.core.accounts.services[self.core.account].backend = replacement
        self.core.accounts.services['b'].backend = NS(rekey_secret_chat=AsyncMock(side_effect=changed))
        with self.assertRaisesRegex(ValueError, 'account changed'):
            await self.core.api_secret_rekey(42)
        replacement.secret_chat_info.assert_not_awaited()
