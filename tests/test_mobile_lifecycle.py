"""Account and task races exercised with real Core entry points."""
import asyncio
import json
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from tg_ascii_mobile.core import Core


class LifecycleTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.core = Core(Path(directory.name), 'iOS')
        self.core.loop.close()
        self.core.loop = asyncio.get_running_loop()
        self.first, self.second = SimpleNamespace(), SimpleNamespace()
        self.core.accounts = SimpleNamespace(current='a', services={
            'a': SimpleNamespace(backend=self.first), 'b': SimpleNamespace(backend=self.second)})

    async def test_account_refresh_does_not_wait_for_the_previous_account(self):
        entered, release = asyncio.Event(), asyncio.Event()
        seen = []
        async def refresh(backend=None):
            backend = backend or self.core.backend
            seen.append(backend)
            if backend is self.first:
                entered.set()
                await release.wait()
        self.core._refresh_chats = refresh
        first = asyncio.create_task(self.core.refresh_chats())
        await entered.wait()
        self.core.accounts.current = 'b'
        second = asyncio.create_task(self.core.refresh_chats())
        try:
            await asyncio.sleep(.01)
            self.assertTrue(any(item is self.second for item in seen))
            self.assertTrue(second.done())
        finally:
            release.set()
            await asyncio.gather(first, second)

    async def test_cancelled_waiter_does_not_cancel_shared_refresh(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def refresh(backend=None):
            entered.set()
            await release.wait()
        self.core._refresh_chats = AsyncMock(side_effect=refresh)
        first = asyncio.create_task(self.core.refresh_chats())
        await entered.wait()
        second = asyncio.create_task(self.core.refresh_chats())
        await asyncio.sleep(0)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        release.set()
        await second
        self.core._refresh_chats.assert_awaited_once()

    async def test_old_reconnect_cannot_overwrite_the_new_connection(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def ensure(**kwargs):
            entered.set()
            await release.wait()
        self.core.stage = 'ready'
        self.core.accounts.services['a'].recovery = SimpleNamespace(ensure=ensure, state='offline')
        self.core.emit = Mock()
        self.core.schedule_draft_sync = Mock()
        task = asyncio.create_task(self.core.api_reconnect())
        await entered.wait()
        self.core.accounts.current = 'b'
        self.core.connection = 'online'
        release.set()
        await task
        self.assertEqual(self.core.connection, 'online')
        self.core.emit.assert_called_once_with('connection', 'reconnecting')

    async def test_switch_clears_previous_reading_chat(self):
        self.core.open_peer, self.core.preview = 42, True
        self.core.load_snapshot = Mock()
        self.core.visible_chats = Mock(return_value=[])
        self.core.emit, self.core.after_login = Mock(), Mock()
        await self.core.switch_finished('ready')
        self.assertIsNone(self.core.open_peer)
        self.assertFalse(self.core.preview)

    async def test_snapshots_cannot_overwrite_a_newer_preview_when_threads_overlap(self):
        entered, release = threading.Event(), threading.Event()
        second_entered = threading.Event()
        calls = 0
        def write(*args):
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                release.wait(2)
            else:
                second_entered.set()
        self.core.previews = {42: {'text': 'old'}}
        with patch('tg_ascii.offline_store.write', write):
            first = asyncio.create_task(self.core.save_snapshot())
            await asyncio.to_thread(entered.wait, 2)
            self.core.previews = {42: {'text': 'new'}}
            second = asyncio.create_task(self.core.save_snapshot())
            try:
                # On the broken implementation the second writer completes before
                # the delayed first one, which then overwrites the newer preview.
                await asyncio.to_thread(second_entered.wait, .05)
            finally:
                release.set()
                await asyncio.gather(first, second)
        saved = json.loads(self.core.previews_path().read_text())
        self.assertEqual(saved['42']['text'], 'new')

    async def test_watch_does_not_return_another_accounts_messages_after_reload(self):
        self.core.stage = 'ready'
        self.core.watch_forum = AsyncMock(return_value=False)
        async def changed(peer):
            self.core.accounts.current = 'b'
        self.core.reload_and_read = changed
        with self.assertRaises((ValueError, PermissionError)):
            await self.core.watch_request({'op': 'messages', 'peer': 42, 'account': 'a'})

    async def test_outbox_burst_schedules_only_one_staging_scan(self):
        self.core.prune_staging = Mock()
        for _ in range(1000):
            self.core.schedule_prune_sent('a', 42)
        handle = self.core._prune_handle
        handles = [item for item in self.core.loop._scheduled if not item.cancelled()]
        self.assertEqual(handles, [handle])
        handle.cancel()
        self.core._prune_sent()
        self.core.prune_staging.assert_called_once_with(age=3600)
        self.assertIsNone(self.core._prune_handle)

    async def test_explicit_save_cancels_pending_delayed_save(self):
        self.core.prefs = SimpleNamespace(values={'offline_copy': True})
        self.core.schedule_save()
        handle = self.core._save_handle
        await self.core.save_snapshot()
        self.assertTrue(handle.cancelled())
        self.assertIsNone(self.core._save_handle)

    async def test_watch_lock_during_reload_hides_cached_history(self):
        self.core.stage = 'ready'
        self.core.watch_forum = AsyncMock(return_value=False)
        async def changed(peer):
            self.core.locked = True
        self.core.reload_and_read = changed
        with self.assertRaises(PermissionError):
            await self.core.watch_request({'op': 'messages', 'peer': 42, 'account': 'a'})

    async def test_reopening_same_chat_shares_one_history_request(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def history(peer):
            started.set()
            await release.wait()
            return []
        self.first.history = AsyncMock(side_effect=history)
        self.core.translation_state = Mock(return_value={})
        self.core.schedule_save = Mock()
        self.core.emit = Mock()
        first = asyncio.create_task(self.core.reload_history(42))
        await started.wait()
        others = [asyncio.create_task(self.core.reload_history(42)) for _ in range(99)]
        await asyncio.sleep(.01)
        try:
            self.assertEqual(self.first.history.await_count, 1)
        finally:
            release.set()
            await asyncio.gather(first, *others)

    async def test_reconnect_burst_shares_one_draft_pull(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def sync(*args, **kwargs):
            started.set()
            await release.wait()
        self.core.sync_drafts = AsyncMock(side_effect=sync)
        for _ in range(100):
            self.core.schedule_draft_sync(pull=True)
        await started.wait()
        self.assertEqual(self.core.sync_drafts.await_count, 1)
        tasks = list(self.core.draft_pull_jobs.values())
        release.set()
        await asyncio.gather(*tasks)
        await asyncio.sleep(0)
        self.assertFalse(self.core.draft_pull_jobs)

    async def test_snapshot_retains_recent_and_active_histories_within_budget(self):
        self.core.histories = {peer: list(range(600)) for peer in range(10)}
        self.core.open_peer = 0
        self.core.floating_peers.add(1)
        self.core.history_requests['pending'] = ('a', 2, [])
        with patch('tg_ascii.offline_store.chat_limit', return_value=5):
            self.core.trim_histories(4)
        self.assertEqual(set(self.core.histories), {0, 1, 2, 4, 9})
        self.assertEqual(len(self.core.histories[0]), 600)
        self.assertEqual(len(self.core.histories[9]), 400)
        self.assertEqual(self.core.histories[9][-1], 599)

    async def test_shutdown_cancels_draft_pulls_delayed_writes_and_qr(self):
        tasks = [asyncio.create_task(asyncio.sleep(60)) for _ in range(3)]
        self.core.draft_jobs['a'] = tasks[0]
        self.core.draft_pull_jobs[('a', id(self.first))] = tasks[1]
        self.core.qr_task = tasks[2]
        self.core.siri_vocabulary.sync = Mock()
        self.core.close_media_requests = AsyncMock()
        self.core.cancel_current_voice = AsyncMock()
        self.core.save_snapshot = AsyncMock()
        self.core.close_call_manager = AsyncMock()
        self.core.accounts.close = AsyncMock()
        await self.core.shutdown()
        self.assertTrue(all(task.cancelled() for task in tasks))
        self.assertFalse(self.core.draft_jobs)
        self.assertFalse(self.core.draft_pull_jobs)
        self.assertIsNone(self.core.qr_task)
