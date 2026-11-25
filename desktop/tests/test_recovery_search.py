import asyncio
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase,TestCase
from unittest.mock import AsyncMock,Mock,patch
import tempfile
from telethon import errors
from tg_ascii.recovery import Recovery
from tg_ascii.desktop import Desktop
from tg_ascii.shared_media import SharedMediaBrowser


class RecoveryTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.client=AsyncMock();self.client.is_connected=Mock(return_value=False);self.client._updates_error=None
        self.service=NS(client=self.client,root=Path(self.folder.name),on_change=Mock(),backend=object())
        self.recovery=Recovery(self.service)
    async def asyncTearDown(self):
        await self.recovery.stop();self.folder.cleanup()
    async def test_disconnected_session_recovers_same_client_and_backend_without_sending(self):
        original=self.service.backend
        await self.recovery.ensure()
        self.client.disconnect.assert_awaited_once();self.client.connect.assert_awaited_once();self.client.catch_up.assert_awaited_once()
        self.assertIs(self.service.backend,original);self.client.send_message.assert_not_called();self.client.log_out.assert_not_called()
        self.assertEqual([call.args for call in self.service.on_change.call_args_list],[('connection','reconnecting'),('connection','online')])
    async def test_healthy_refresh_only_probes_and_concurrent_recovery_is_serialized(self):
        self.client.connect.side_effect=lambda:self.client.is_connected.configure_mock(return_value=True)
        await asyncio.gather(self.recovery.ensure(),self.recovery.ensure())
        self.client.connect.assert_awaited_once();self.client.disconnect.assert_awaited_once()
    async def test_live_socket_with_stuck_requests_is_reconnected(self):
        self.client.is_connected.return_value=True
        self.client.side_effect=[TimeoutError(),NS()]
        await self.recovery.ensure();self.client.connect.assert_awaited_once()
        self.assertEqual(self.recovery.state,'online')
    async def test_revoked_authorization_stops_retries_without_deleting_session(self):
        self.client.is_connected.return_value=True;self.client.side_effect=errors.SessionRevokedError(None)
        with self.assertRaises(errors.SessionRevokedError):await self.recovery.ensure()
        with self.assertRaises(errors.AuthKeyUnregisteredError):await self.recovery.ensure()
        self.assertTrue(self.recovery.auth_required);self.assertEqual(self.recovery.state,'auth')
        self.client.assert_awaited_once();self.client.connect.assert_not_called();self.client.log_out.assert_not_called()
    async def test_offline_failure_is_bounded_and_other_account_keeps_working(self):
        self.client.connect.side_effect=OSError('private details')
        with self.assertRaises(OSError):await self.recovery.ensure()
        self.assertEqual(self.recovery.state,'offline');self.assertEqual(self.recovery.failures,1)
        other=Recovery(NS(client=AsyncMock(),root=Path(self.folder.name),on_change=Mock()))
        other.service.client.is_connected=Mock(return_value=True)
        await other.ensure();self.assertEqual(other.state,'online');await other.stop()
        log=(Path(self.folder.name)/'diagnostics.log').read_text(encoding='utf-8');self.assertIn('OSError',log);self.assertNotIn('private details',log)
    async def test_rate_limit_is_respected_by_manual_refresh_too(self):
        self.client.is_connected.return_value=True;self.client.side_effect=errors.FloodWaitError(None,capture=30)
        with self.assertRaises(errors.FloodWaitError):await self.recovery.ensure()
        with self.assertRaises(errors.FloodWaitError):await self.recovery.ensure()
        self.client.assert_awaited_once();self.client.disconnect.assert_not_called()

    async def test_monitor_detects_loss_and_stops_when_app_closes(self):
        self.client.connect.side_effect=lambda:self.client.is_connected.configure_mock(return_value=True)
        with patch('tg_ascii.recovery.POLL_INTERVAL',.001):
            self.recovery.start()
            for _ in range(100):
                if self.client.catch_up.await_count:break
                await asyncio.sleep(.001)
            self.client.connect.assert_awaited_once()
            await self.recovery.stop();self.assertIsNone(self.recovery.task)

    async def test_close_cancels_manual_recovery_and_cannot_resurrect_connection(self):
        started=asyncio.Event()
        async def hanging():started.set();await asyncio.Event().wait()
        self.client.disconnect.side_effect=hanging
        task=asyncio.create_task(self.recovery.ensure());await started.wait();await self.recovery.stop()
        with self.assertRaises(asyncio.CancelledError):await task
        self.client.connect.assert_not_called()
        with self.assertRaises(ConnectionError):await self.recovery.ensure()
    async def test_foreground_timeout_unlocks_controls_and_never_retries_operation(self):
        app=NS(busy=False,status=Mock(),update_controls=Mock(),show_error=Mock(),worker=Mock())
        pending=[];app.worker.submit.side_effect=lambda coro,done,failed:pending.append((coro,done,failed))
        count=[]
        async def hanging():count.append(1);await asyncio.Event().wait()
        Desktop.call(app,hanging(),Mock(),'loading',timeout=.01)
        self.assertTrue(app.busy)
        try:await pending[0][0]
        except TimeoutError as exc:pending[0][2](exc)
        self.assertFalse(app.busy);self.assertEqual(count,[1]);app.show_error.assert_called_once()
    async def test_refresh_remains_available_during_foreground_work_and_is_account_scoped(self):
        backend=NS(chats=AsyncMock(return_value=[1]),folders=AsyncMock(return_value=[2]))
        app=NS(ui_account='a',busy=True,demo=False,closed=False,closing=False,service=NS(backend=backend,recover=AsyncMock()),
               worker=Mock(),status=Mock(),update_folder_picker=Mock(),render_chats=Mock(),show_error=Mock())
        Desktop.refresh(app);coro,done,failed=app.worker.submit.call_args.args
        Desktop.refresh(app);app.worker.submit.assert_called_once()
        result=await coro;app.service.recover.assert_awaited_once_with('a')
        app.ui_account='b';done(result);app.render_chats.assert_not_called();self.assertFalse(app._refresh_pending)


class SearchWidgetTests(TestCase):
    def test_native_emoji_targets_search_and_defers_palette(self):
        from tg_ascii.native_emoji import open_for
        entry=Mock();entry.winfo_exists.return_value=True;failed=Mock()
        with patch('tg_ascii.native_emoji.open_palette') as palette:
            open_for(entry,failed);entry.focus_set.assert_called_once();palette.assert_not_called()
            entry.after_idle.call_args.args[0]();palette.assert_called_once()
        entry.winfo_exists.return_value=False
        with patch('tg_ascii.native_emoji.open_palette') as palette:
            entry.after_idle.call_args.args[0]();palette.assert_not_called()
    def test_shared_browser_binds_real_entry_without_opening_native_menu(self):
        query=NS(get=lambda:'',entry=Mock())  # StringVar deliberately has no bind method.
        app=NS(ui_account='a',service=NS(backend=Mock()),dialog=Mock(return_value=(Mock(),Mock())),field=Mock(return_value=query),show_error=Mock())
        with patch('tg_ascii.shared_media.tk.StringVar'),patch('tg_ascii.shared_media.ttk'),patch('tg_ascii.shared_media.tk.Listbox'),patch('tg_ascii.shared_media.Choice'),patch('tg_ascii.shared_media.FlowFrame'),patch('tg_ascii.shared_media.SharedPhotoGrid'),patch('tg_ascii.recent_search_ui.RecentStrip') as recent,patch('tkinter.Menu') as native:
            browser=SharedMediaBrowser(app,True,42)
        self.assertEqual(recent.call_args.args[3], 'messages:42')
        query.entry.bind.assert_called_once();self.assertEqual(query.entry.bind.call_args.args[0],'<Return>')
        app.field.assert_called_once_with(app.dialog.return_value[1],'Search in chat',emoji=True)
        native.assert_not_called();self.assertEqual(browser.peer,42)
