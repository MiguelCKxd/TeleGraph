"""3.0.0.2: Complex features › Keep more loaded / Prepare content at startup."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from tg_ascii_mobile.core import Core, mobile_features
from tg_ascii_mobile.server import Server


def message(ident, outgoing=False):
    from tg_ascii.backend import Message
    return Message(ident, 'Ana', f'text {ident}', '12:00', outgoing)


class KeepLoadedTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.core = Core(Path(folder.name), 'Android')
        self.core.loop.close()
        self.core.loop = asyncio.get_running_loop()
        self.values = {}
        self.core.prefs = SimpleNamespace(values=self.values)
        self.events = []
        self.core.emit = lambda kind, payload=None: self.events.append((kind, payload))
        self.core.schedule_save = lambda: None
        self.core.connection = 'online'

    def enable(self, *keys):
        self.values['mobile_features'] = {key: True for key in keys}

    def test_both_off_by_default_others_still_on(self):
        features = mobile_features({})
        self.assertFalse(features['keep_loaded'])
        self.assertFalse(features['preload_startup'])
        self.assertTrue(features['polls'])
        self.assertTrue(mobile_features({'mobile_features': {'keep_loaded': True}})['keep_loaded'])

    def test_media_and_native_glass_require_explicit_opt_in(self):
        for key in ('media_originals', 'native_liquid_glass'):
            self.assertFalse(mobile_features({})[key])
            self.assertFalse(mobile_features({'mobile_features': {key: 'true'}})[key])
            self.assertTrue(mobile_features({'mobile_features': {key: True}})[key])
            self.assertFalse(mobile_features({'mobile_features': {key: False}})[key])

    def test_opt_in_survives_shared_preferences_reload(self):
        from tg_ascii.preferences import Preferences
        prefs = Preferences(self.core.root)
        prefs.save({'mobile_features': {'media_originals': True, 'native_liquid_glass': True}})
        restored = mobile_features(Preferences(self.core.root).values)
        self.assertTrue(restored['media_originals'])
        self.assertTrue(restored['native_liquid_glass'])

    async def test_recent_chat_only_asks_for_newer_messages(self):
        backend = SimpleNamespace(client=SimpleNamespace(get_messages=AsyncMock(return_value=[])),
                                  resolve_missing_senders=AsyncMock(), message=lambda raw: raw, read_max={},
                                  history=AsyncMock(return_value=[message(1), message(2)]))
        self.core.accounts = SimpleNamespace(current='account', services={'account': SimpleNamespace(backend=backend)})
        self.core.histories[7] = [message(1)]
        await self.core.refresh_history(7)  # off: the latest page is read
        backend.history.assert_awaited_once()
        self.enable('keep_loaded')
        self.events.clear()
        await self.core.refresh_history(7)  # on and recent: only what is newer than 2
        backend.client.get_messages.assert_awaited_once_with(7, min_id=2, limit=100)
        self.assertEqual(backend.history.await_count, 1)
        self.assertEqual(self.events, [])  # nothing new: no redraw
        backend.client.get_messages.return_value = [message(3)]
        await self.core.refresh_history(7)
        self.assertEqual([m.id for m in self.core.histories[7]], [1, 2, 3])
        self.assertEqual(self.events[-1][0], 'history')
        # A connection gap: the next opening reads the latest page again.
        self.core.on_change('account', 'connection', 'reconnecting')
        await self.core.refresh_history(7)
        self.assertEqual(backend.history.await_count, 2)

    async def test_profile_kept_and_dropped_after_a_change(self):
        self.enable('keep_loaded')
        self.core._profile = AsyncMock(return_value={'id': 5})
        self.core.accounts = SimpleNamespace(current='account', services={})
        self.assertEqual(await self.core.api_profile(5), {'id': 5})
        await self.core.api_profile(5)
        self.assertEqual(self.core._profile.await_count, 1)
        self.core.api_contact_edit = AsyncMock(return_value=True)
        await self.core.call('contact_edit', {})
        await self.core.api_profile(5)
        self.assertEqual(self.core._profile.await_count, 2)

    async def test_avatar_reused_while_the_photo_id_is_the_same(self):
        self.enable('keep_loaded')
        photo = SimpleNamespace(photo_id=99)
        self.core.chats = [SimpleNamespace(id=5, entity=SimpleNamespace(photo=photo), archived=False)]
        self.core.accounts = SimpleNamespace(current='account', services={})
        folder = self.core.root / 'mobile-avatars' / 'account'
        folder.mkdir(parents=True)
        (folder / '5.jpg').write_bytes(b'jpg')
        (folder / '5.id').write_text('99')
        import os
        os.utime(folder / '5.jpg', (0, 0))  # far older than the usual three days
        self.assertEqual(await self.core.avatar_file(5), folder / '5.jpg')
        self.assertEqual(self.core.photo_id(5), 99)
        photo.photo_id = 100  # a new profile photo: the copy is no longer trusted
        self.assertEqual(self.core.photo_id(5), 100)
        self.assertNotEqual((folder / '5.id').read_text(), '100')

    def test_server_lets_the_web_view_keep_unchangeable_pictures(self):
        server = Server(SimpleNamespace(keep_loaded=lambda: False))
        self.assertEqual(server.keep_headers({'p': '1'}, 'p'), ())
        server.core.keep_loaded = lambda: True
        self.assertEqual(server.keep_headers({}, 'p'), ())
        self.assertIn('immutable', server.keep_headers({'p': '1'}, 'p')[0])
