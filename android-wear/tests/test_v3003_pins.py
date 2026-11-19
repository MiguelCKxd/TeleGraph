import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from tg_ascii.backend import Chat
from tg_ascii.local_state import LocalPins
from tg_ascii.preferences import Preferences
from tg_ascii_mobile.core import Core


class PinAndStartupTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.core = core = Core(self.root, 'iOS')
        core.loop.close()
        core.loop = asyncio.get_running_loop()
        core.prefs = Preferences(self.root)
        core.local_pins = LocalPins(self.root)
        self.backend = SimpleNamespace(pin=AsyncMock(), move_pinned=AsyncMock())
        core.accounts = SimpleNamespace(current='qa', services={'qa': SimpleNamespace(backend=self.backend)})
        core.chats = [Chat(i, str(i), pinned=i <= 2) for i in range(1, 12)]
        core.emit = Mock()
        core.chat_json = lambda c: {'id': c.id, 'pinned': core.is_pinned(c)}
        core.refresh_chats = AsyncMock()

    async def test_local_order_survives_new_activity_relaunch_and_mode_switch(self):
        core = self.core
        await core.api_settings({'local_pins': True})
        for peer in range(3, 12):
            await core.api_pin_chat(peer, True)
        await core.api_move_pin(1, -1, 'qa')
        expected = [11, 10, 9, 8, 7, 6, 5, 4, 1, 3, 2]
        self.assertEqual([c.id for c in core.visible_chats()], expected)
        core.chats.reverse()
        core.local_pins = LocalPins(self.root)
        self.assertEqual([c.id for c in core.visible_chats()], expected)
        self.backend.pin.assert_not_awaited()
        self.backend.move_pinned.assert_not_awaited()
        await core.api_settings({'local_pins': False})
        self.assertEqual({c.id for c in core.visible_chats() if core.is_pinned(c)}, {1, 2})
        await core.api_move_pin(1, 1, 'qa')
        self.backend.move_pinned.assert_awaited_once_with(1, 1, False)

    async def test_limit_error_preserves_unpinned_chat(self):
        self.backend.pin.side_effect = ValueError('PINNED_DIALOGS_TOO_MUCH')
        with self.assertRaisesRegex(ValueError, 'PINNED_DIALOGS_TOO_MUCH'):
            await self.core.api_pin_chat(3, True)
        self.assertFalse(self.core.is_pinned(self.core.chats[2]))

    async def test_startup_option_persists_and_retries_when_online(self):
        core = self.core
        core.prefs.save({'mobile_features': {'preload_startup': True}})
        core.prefs = Preferences(self.root)
        core._prepare_chats = AsyncMock()
        core.connection = 'offline'
        await core.preload()
        core._prepare_chats.assert_not_awaited()
        core.connection = 'online'
        await core.preload()
        await core.preload()
        core._prepare_chats.assert_awaited_once()
