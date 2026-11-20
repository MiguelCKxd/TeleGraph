"""Premium is a session fact, not a per-feature network request."""
import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

from telethon import functions as f, types as t

from tg_ascii.accounts import Accounts
from tg_ascii.backend import TelegramBackend
from tg_ascii.desktop_service import DesktopService
from tg_ascii.preferences import write_json
from tg_ascii.recovery import Recovery


def backend_for(premium=True, identity=10):
    client = AsyncMock()
    client.add_event_handler = Mock()
    client.get_me.return_value = t.User(identity, first_name='Test', premium=premium)
    client.get_input_entity.return_value = t.InputPeerUser(42, 123)
    return TelegramBackend(client), client


class AccountProfileTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_result_seeds_premium_without_network_checks(self):
        backend, client = backend_for()
        backend.account_profile.remember(t.User(10, premium=True))
        for _ in range(20):
            self.assertTrue(await backend.premium_enabled())
        client.get_me.assert_not_awaited()

    async def test_concurrent_checks_share_one_request_and_cache_false_too(self):
        backend, client = backend_for(False)
        results = await asyncio.gather(*(backend.premium_enabled() for _ in range(30)))
        self.assertEqual(results, [False] * 30)
        self.assertFalse(await backend.premium_enabled())
        client.get_me.assert_awaited_once()

    async def test_accounts_are_isolated_and_manual_refresh_observes_expiry(self):
        one, first = backend_for(True, 10)
        two, second = backend_for(False, 20)
        self.assertTrue(await one.premium_enabled())
        self.assertFalse(await two.premium_enabled())
        first.get_me.return_value = t.User(10, premium=False)
        snapshot = await one.refresh_account()
        self.assertFalse(snapshot['premium'])
        self.assertTrue(snapshot['verified'])
        self.assertFalse(await two.premium_enabled())
        second.get_me.assert_awaited_once()

    async def test_partial_foreign_or_missing_users_cannot_overwrite_self(self):
        backend, client = backend_for()
        await backend.premium_enabled()
        for user in (t.User(10, min=True), t.User(20, premium=False), t.UserEmpty(10), None):
            self.assertFalse(backend.account_profile.remember(user))
        self.assertTrue(await backend.premium_enabled())
        client.get_me.return_value = t.User(20)
        with self.assertRaises(ValueError):
            await backend.refresh_account()
        self.assertEqual(backend.account_profile.user_id, 10)

    async def test_failed_or_cancelled_first_check_never_marks_account_verified(self):
        backend, client = backend_for()
        async def stalled():
            await asyncio.Event().wait()
        client.get_me.side_effect = stalled
        with patch('tg_ascii.account_profile.PROFILE_TIMEOUT', .01):
            with self.assertRaises(TimeoutError):
                await backend.premium_enabled()
        self.assertFalse(backend.account_profile.snapshot()['verified'])
        client.get_me.side_effect = None
        self.assertTrue(await backend.premium_enabled())

    async def test_newer_push_wins_over_profile_request_in_flight(self):
        backend, client = backend_for()
        backend.account_profile.remember(t.User(10, premium=False))
        started, finish = asyncio.Event(), asyncio.Event()
        async def request():
            started.set()
            await finish.wait()
            return t.User(10, premium=False)
        client.get_me.side_effect = request
        task = asyncio.create_task(backend.refresh_account())
        await started.wait()
        backend.account_profile.remember(t.User(10, premium=True))
        finish.set()
        self.assertTrue((await task)['premium'])

    async def test_self_push_updates_premium_without_rpc(self):
        backend, client = backend_for()
        backend.account_profile.remember(t.User(10, premium=True))
        backend.on_change = Mock()
        update = t.UpdateUser(10)
        update._entities = {10: t.User(10, premium=False), 20: t.User(20, premium=True)}
        await backend.account_event(update)
        self.assertFalse(await backend.premium_enabled())
        client.get_me.assert_not_awaited()
        self.assertEqual([call.args for call in backend.on_change.call_args_list if call.args[0]=='premium'], [('premium',False)])
        self.assertIn(20,backend._capability_entities)

    async def test_self_invalidation_without_entity_refreshes_once(self):
        backend, client = backend_for(True)
        backend.account_profile.remember(t.User(10, premium=False))
        await backend.account_event(t.UpdateUser(20))
        client.get_me.assert_not_awaited()
        await backend.account_event(t.UpdateUser(10))
        self.assertTrue(await backend.premium_enabled())
        client.get_me.assert_awaited_once()

    async def test_login_code_and_password_reuse_authorization_user(self):
        for method, value in [('verify_code', '12345'), ('verify_password', 'password')]:
            with self.subTest(method=method), tempfile.TemporaryDirectory() as folder:
                service = DesktopService(root=folder)
                _, client = backend_for(True)
                client.sign_in.return_value = t.User(10, premium=True)
                service.client = client
                with patch('tg_ascii.recovery.Recovery.start'):
                    self.assertEqual(await getattr(service, method)(value), 'ready')
                self.assertTrue(await service.backend.premium_enabled())
                client.get_me.assert_not_awaited()
                await service.close()

    async def test_persisted_badge_is_revalidated_once_and_account_switch_is_local(self):
        with tempfile.TemporaryDirectory() as folder:
            write_json(Path(folder) / 'accounts.json', {
                'active': 'account', 'accounts': {'account': {'premium': True, 'user_id': 10}}})
            manager = Accounts(root=folder)
            backend, client = backend_for(False)
            manager.services['account'] = NS(backend=backend, client=client, recovery=None)
            await manager.register('account')
            self.assertFalse(manager.entries['account']['premium'])
            await manager.select('account')
            client.get_me.assert_awaited_once()
            manager.changed('account', 'premium', True)
            self.assertTrue(Accounts(root=folder).entries['account']['premium'])

    async def test_reconnect_refreshes_profile_but_healthy_probe_does_not(self):
        with tempfile.TemporaryDirectory() as folder:
            client = AsyncMock()
            client._updates_error = None
            client.is_connected = Mock(return_value=False)
            client.connect.side_effect = lambda: client.is_connected.configure_mock(return_value=True)
            service = NS(client=client, root=Path(folder), on_change=None, refresh_profile=AsyncMock())
            recovery = Recovery(service)
            await recovery.ensure()
            await recovery.ensure()
            service.refresh_profile.assert_awaited_once()
            await recovery.stop()

    async def test_profile_timeout_does_not_break_reconnected_transport(self):
        with tempfile.TemporaryDirectory() as folder:
            client = AsyncMock()
            client._updates_error = None
            client.is_connected = Mock(return_value=False)
            service = NS(client=client, root=Path(folder), on_change=None,
                         refresh_profile=AsyncMock(side_effect=TimeoutError))
            recovery = Recovery(service)
            await recovery.ensure()
            self.assertEqual(recovery.state, 'online')
            await recovery.stop()

    async def test_explicit_reconnect_resets_healthy_socket_and_refreshes_premium(self):
        with tempfile.TemporaryDirectory() as folder:
            backend, client = backend_for(True)
            backend.account_profile.remember(t.User(10, premium=False))
            client.is_connected = Mock(return_value=True)
            client._updates_error = None
            service = DesktopService(root=folder)
            service.client, service.backend = client, backend
            service.recovery = Recovery(service)
            service.recovery.last_check = asyncio.get_running_loop().time()
            await service.reconnect()
            client.disconnect.assert_awaited_once()
            client.connect.assert_awaited_once()
            client.catch_up.assert_awaited_once()
            client.get_me.assert_awaited_once()
            self.assertIs(service.backend, backend)
            self.assertTrue(await backend.premium_enabled())
            client.send_message.assert_not_awaited()
            client.log_out.assert_not_awaited()
            await service.recovery.stop()

    async def test_explicit_reconnect_is_isolated_to_selected_account_and_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = Accounts(root=folder)
            one, other = NS(reconnect=AsyncMock()), NS(reconnect=AsyncMock())
            manager.entries['b' * 32] = {}
            manager.services = {'account': one, 'b' * 32: other}
            await manager.reconnect()
            one.reconnect.assert_awaited_once()
            other.reconnect.assert_not_awaited()
            service = DesktopService(root=folder)
            async def stalled(**kwargs):
                await asyncio.Event().wait()
            service.backend = object()
            service.recovery = NS(ensure=stalled)
            with patch('tg_ascii.desktop_service.RECONNECT_TIMEOUT', .01):
                with self.assertRaises(TimeoutError):
                    await service.reconnect()


class ReactionCatalogueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.backend, self.client = backend_for(True)
        self.backend.account_profile.remember(t.User(10, premium=True))
        self.requests = []
        async def rpc(request):
            self.requests.append(request)
            if isinstance(request, f.help.GetAppConfigRequest):
                return NS(config=t.JsonObject([t.JsonObjectValue('reactions_user_max_premium', t.JsonNumber(4))]))
            if isinstance(request, f.messages.GetAvailableReactionsRequest):
                return NS(reactions=[NS(reaction='👍', inactive=False)])
            if isinstance(request, f.messages.GetRecentReactionsRequest):
                return NS(reactions=[t.ReactionCustomEmoji(99)])
            if isinstance(request, f.channels.GetFullChannelRequest):
                return NS(full_chat=NS(available_reactions=t.ChatReactionsNone()))
            raise AssertionError(type(request).__name__)
        self.client.side_effect = rpc

    async def test_repeated_and_concurrent_pickers_share_catalogues(self):
        results = await asyncio.gather(*(self.backend.reaction_choices(42, None) for _ in range(10)))
        self.assertEqual(len(self.requests), 3)
        self.assertTrue(all(result[0]['maximum'] == 4 for result in results))
        self.assertEqual(results[0][1:], (['👍'], [99]))
        self.client.get_me.assert_not_awaited()

    async def test_update_config_refreshes_metadata_and_recent_update_only_recent(self):
        await self.backend.reaction_choices(42, None)
        await self.backend.account_event(t.UpdateRecentReactions())
        await self.backend.reaction_choices(42, None)
        self.assertEqual(len(self.requests), 4)
        self.assertIsInstance(self.requests[-1], f.messages.GetRecentReactionsRequest)
        await self.backend.account_event(t.UpdateConfig())
        await self.backend.reaction_choices(42, None)
        self.assertEqual(len(self.requests), 7)

    async def test_chat_permissions_are_refetched_even_with_cached_account_and_config(self):
        self.client.get_input_entity.return_value = t.InputPeerChannel(55, 123)
        for _ in range(2):
            policy = await self.backend.reaction_policy(-1000000000055)
            self.assertEqual(policy['allowed'], set())
        self.assertEqual(sum(isinstance(r, f.help.GetAppConfigRequest) for r in self.requests), 1)
        self.assertEqual(sum(isinstance(r, f.channels.GetFullChannelRequest) for r in self.requests), 2)
