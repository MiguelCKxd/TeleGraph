"""Only a background dialog refresh delegates transport errors to the connection indicator."""
import errno
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from tg_ascii_mobile.core import Core


class ConnectionNoticeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.core = Core.__new__(Core)
        self.client = type('Client', (), {'iter_dialogs': lambda self: ()})()
        self.backend = SimpleNamespace(client=self.client, chats=AsyncMock())
        self.core.accounts = SimpleNamespace(current='test', services={'test': SimpleNamespace(backend=self.backend)})
        self.core.emit = Mock()

    async def test_background_transport_loss_uses_connection_indicator(self):
        for error in (ConnectionError(), TimeoutError(), OSError(errno.ENETUNREACH, 'network unavailable')):
            with self.subTest(error=type(error).__name__):
                self.backend.chats.side_effect = error
                await self.core._refresh_chats()
                self.core.emit.assert_not_called()
                self.assertNotIn('iter_dialogs', vars(self.client))

    async def test_local_access_failure_still_reports_an_error(self):
        self.backend.chats.side_effect = PermissionError(errno.EACCES, 'not allowed')
        await self.core._refresh_chats()
        name, data = self.core.emit.call_args.args
        self.assertEqual(name, 'toast')
        self.assertEqual(data['kind'], 'error')
        self.assertTrue(data['text'])
