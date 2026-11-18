"""Exercise call menus and captured actions without accounts or Tk windows."""
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

from tg_ascii.desktop_calls import CallWindow, select_call_devices
from tg_ascii.i18n import set_language


class MemberControlsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        set_language('en')
        self.page = dict(items=[], next=None)
        self.jobs, self.menus = [], []
        self.manager = NS(can_manage=False, participants=AsyncMock(return_value=self.page))
        self.owner = NS(_app_locked=False,
            service=NS(services={'alt': NS(backend=NS(names={8: 'Synthetic member'}))}),
            worker=NS(submit=lambda *args: self.jobs.append(args)))
        self.view = CallWindow.__new__(CallWindow)
        self.view.owner, self.view.manager, self.view.account = self.owner, self.manager, 'alt'
        self.view.snapshot = dict(token='current', state='active')
        self.view.pending = False
        self.view.window, self.view.buttons = object(), {'members': object()}
        self.view.alive = lambda: True
        self.view.update, self.view.perform = Mock(), Mock()
        self.view.status = Mock()
        self.menu_patch = patch('tg_ascii.app_dialogs.popup_menu', side_effect=lambda window, items, **kwargs: self.menus.append(items))
        self.menu_patch.start()

    async def asyncTearDown(self):
        self.menu_patch.stop()
        for coroutine, _, _ in self.jobs:
            coroutine.close()

    def row(self, **values):
        return dict(id=8, name='Synthetic member', muted=False, video=False, screen=False, **values)

    async def load(self, row):
        self.page['items'] = [row]
        self.view.members()
        coroutine, loaded, _ = self.jobs[-1]
        loaded(await coroutine)
        self.menus[-1][0][1]()
        return dict(self.menus[-1]) if len(self.menus) > 1 else {}

    async def test_non_admin_only_receives_supported_remote_actions(self):
        actions = await self.load(self.row(is_self=False, volume=125, can_set_volume=True))
        self.assertEqual(set(actions), {'Volume (%)'})
        self.assertNotIn('Mute microphone', actions)

    async def test_own_hand_is_hidden_for_conferences_and_forced_mute_has_no_unmute(self):
        actions = await self.load(self.row(is_self=True, can_raise_hand=False, muted_by_admin=True))
        self.assertFalse(actions)

    async def test_admin_can_allow_speaking_and_lower_another_raised_hand(self):
        self.manager.can_manage = True
        actions = await self.load(self.row(is_self=False, can_raise_hand=True, raised_hand=True, muted_by_admin=True, can_set_volume=True))
        self.assertIn('Volume (%)', actions)
        actions['Allow to speak']()
        self.view.perform.assert_called_with('participant_action', 8, muted=False)
        actions['Lower hand']()
        self.view.perform.assert_called_with('participant_action', 8, raise_hand=False)

    async def test_volume_dialog_converts_percent_and_does_not_send_cancelled_or_stale_actions(self):
        row = self.row(volume=125)
        with patch('tg_ascii.app_dialogs.simpledialog.askinteger', return_value=150) as ask:
            self.view.participant_volume(row)
        self.assertEqual(ask.call_args.kwargs['minvalue'], 0)
        self.view.perform.assert_called_once_with('local_participant_volume', 8, volume=15000)
        self.view.perform.reset_mock()
        with patch('tg_ascii.app_dialogs.simpledialog.askinteger', return_value=None):
            self.view.participant_volume(row)
        def changed(*args, **kwargs):
            self.view.snapshot['token'] = 'different-call'
            return 150
        with patch('tg_ascii.app_dialogs.simpledialog.askinteger', side_effect=changed):
            self.view.participant_volume(row)
        self.view.perform.assert_not_called()

    async def test_group_settings_only_shows_server_supported_actions(self):
        self.view.buttons['group_settings'] = object()
        self.manager.control_info = AsyncMock(return_value=dict(active=True, can_edit_title=False, can_record=False))
        self.view.group_settings()
        coroutine, loaded, _ = self.jobs[-1]
        loaded(await coroutine)
        self.assertFalse(self.menus)
        self.assertFalse(self.view.pending)
        self.manager.control_info.return_value = dict(active=True, can_edit_title=True, can_change_join_muted=True, join_muted=True, can_record=True, recording=True)
        self.view.group_settings()
        coroutine, loaded, _ = self.jobs[-1]
        loaded(await coroutine)
        actions = dict(self.menus[-1])
        self.assertIn('Title', actions)
        actions['Stop recording']()
        self.view.perform.assert_called_with('set_recording', False)
        actions['Unmute new participants']()
        self.view.perform.assert_called_with('set_join_muted', False)
        self.view.perform.reset_mock()
        self.view.snapshot['token'] = 'next-call'
        actions['Stop recording']()
        self.view.perform.assert_not_called()

    async def test_loading_is_coalesced_and_lock_prevents_menu_without_leaving_pending(self):
        self.view.members()
        self.view.members()
        self.assertEqual(len(self.jobs), 1)
        self.owner._app_locked = True
        coroutine, loaded, _ = self.jobs[-1]
        loaded(await coroutine)
        self.assertFalse(self.view.pending)
        self.assertFalse(self.menus)

    async def test_volume_is_hidden_when_the_native_engine_cannot_apply_gain(self):
        actions = await self.load(self.row(is_self=False, can_set_volume=False))
        self.assertNotIn('Volume (%)', actions)

    async def test_device_choices_reach_both_managers_with_their_own_call_tokens(self):
        standard = NS(_closed=False, snapshot={'token': None}, select_devices=AsyncMock())
        group = NS(_closed=False, snapshot={'token': 'group-call'}, select_devices=AsyncMock())
        backend = NS(call_manager=standard, group_call_manager=group)
        choices = dict(microphone='mic', speaker='speaker', camera='camera')
        await select_call_devices(backend, choices)
        standard.select_devices.assert_awaited_once_with(**choices, token=None)
        group.select_devices.assert_awaited_once_with(**choices, token='group-call')
        group._closed = True
        group.select_devices.reset_mock()
        await select_call_devices(backend, choices)
        group.select_devices.assert_not_awaited()

    async def test_call_window_settings_stay_bound_to_the_original_account(self):
        self.owner.call_settings = Mock()
        self.owner.ui_account = 'another-account'
        self.view.device_settings()
        self.owner.call_settings.assert_called_once_with(account='alt')
        self.owner._app_locked = True
        self.view.device_settings()
        self.owner.call_settings.assert_called_once()
