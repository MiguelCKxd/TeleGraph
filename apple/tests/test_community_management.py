from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from tg_ascii_mobile.core import Core


class CommunityManagementTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.core = Core(Path(directory.name), 'test')
        self.addCleanup(self.core.loop.close)
        self.backend = SimpleNamespace(
            profile_change=AsyncMock(),
            community_add=AsyncMock(),
            set_discussion_group=AsyncMock(),
        )
        self.core.accounts = SimpleNamespace(current='qa', services={'qa': SimpleNamespace(backend=self.backend)})

    async def test_stale_forward_and_share_requests_do_not_send(self):
        for operation in (self.core.api_forward(10, 5, 20, account='other'),
                          self.core.api_forward_many(10, [5], 20, account='other'),
                          self.core.api_share_contacts(20, [10], account='other')):
            with self.assertRaisesRegex(ValueError, 'account changed'):
                await operation

        other = SimpleNamespace(send_contact_card=AsyncMock())
        self.core.accounts.services['other'] = SimpleNamespace(backend=other)

        async def switch_while_loading_contact(ident):
            self.core.accounts.current = 'other'
            return SimpleNamespace(id=ident, phone='123', first_name='Example', last_name='')

        self.backend.client = SimpleNamespace(get_entity=switch_while_loading_contact)
        self.backend.send_contact_card = AsyncMock()
        with self.assertRaisesRegex(ValueError, 'no longer active'):
            await self.core.api_share_contacts(20, [10], account='qa')
        self.backend.send_contact_card.assert_not_awaited()
        other.send_contact_card.assert_not_awaited()

    async def test_photo_remains_staged_when_change_fails(self):
        file = self.core.staging_path('photo.png')
        file.write_bytes(b'fixture')
        self.core.forget_avatar = Mock()
        self.backend.profile_change.side_effect = OSError('offline')
        with self.assertRaises(OSError):
            await self.core.api_group_change(-123, 'photo', key=file.name, account='qa')
        self.assertTrue(file.is_file())
        self.core.forget_avatar.assert_not_called()
        self.backend.profile_change.side_effect = None
        await self.core.api_group_change(-123, 'photo', key=file.name, account='qa')
        self.assertFalse(file.exists())
        self.core.forget_avatar.assert_called_once_with(-123)

    async def test_invitation_reports_partial_telegram_result(self):
        self.backend.community_add.return_value = SimpleNamespace(missing_invitees=[object()])
        result = await self.core.api_members_add(-123, [100, 101], account='qa')
        self.assertEqual(result, {'missing': 1})
        self.backend.community_add.assert_awaited_once_with(-123, [100, 101])

    async def test_discussion_carries_expected_link_and_exposure(self):
        await self.core.api_set_discussion(-1000000000001, -1000000000002, expected=3, expose=True, account='qa')
        self.backend.set_discussion_group.assert_awaited_once_with(
            -1000000000001, -1000000000002, expected_link=3, expose_history=True, migrate=False,
        )

    async def test_mutations_do_not_cross_account_switch(self):
        with self.assertRaises(ValueError):
            await self.core.api_group_change(-123, 'title', 'Local', account='other')
        with self.assertRaises(ValueError):
            await self.core.api_members_add(-123, [100], account='other')
        with self.assertRaises(ValueError):
            await self.core.api_set_discussion(-123, account='other')
        self.backend.profile_change.assert_not_awaited()
        self.backend.community_add.assert_not_awaited()
        self.backend.set_discussion_group.assert_not_awaited()
