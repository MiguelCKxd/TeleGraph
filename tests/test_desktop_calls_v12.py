"""Call controls must stay bound to the captured account, peer and call token."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch
from telethon import types
from tg_ascii.desktop_calls import call_allowed, DesktopCalls, CallWindow
from tg_ascii.i18n import set_language

def app_fixture():
    backend = NS(account_profile=NS(user_id=1), _capability_entities={2: types.User(2)},
                 _capability_full={}, names={2: 'Test'})
    app = NS(demo=False, preferences={'advanced_features': {'calls': True}}, active=2,
             ui_account='a', chats=[], closed=False, closing=False,
             service=NS(services={'a': NS(backend=backend)}, labels={'a': 'Test account'}))
    return app, backend

class CallPermissionsTests(unittest.TestCase):
    def setUp(self):
        self.available = patch('tg_ascii.calls.engine_available', return_value=True)
        self.available.start()
        self.addCleanup(self.available.stop)

    def test_hides_unavailable_calls_without_network_lookup(self):
        app, backend = app_fixture()
        self.assertTrue(call_allowed(app))
        for entity in (types.User(2, bot=True), types.User(2, deleted=True), types.User(2, is_self=True), types.ChatEmpty(2)):
            backend._capability_entities[2] = entity
            self.assertFalse(call_allowed(app))
        backend._capability_entities[2] = types.User(2)
        backend._capability_full[2] = NS(phone_calls_available=True, video_calls_available=False)
        self.assertTrue(call_allowed(app))
        self.assertFalse(call_allowed(app, video=True))
        backend._capability_full[2].phone_calls_private = True
        self.assertFalse(call_allowed(app))

    def test_other_account_permissions_are_not_borrowed(self):
        app, _ = app_fixture()
        self.assertFalse(call_allowed(app, account='other'))
        self.assertFalse(call_allowed(app, peer=1))
        app.preferences['advanced_features']['calls'] = False
        self.assertFalse(call_allowed(app))

    def test_late_event_cannot_replace_current_call_window(self):
        app, backend = app_fixture()
        backend.call_manager = NS(snapshot={'token': 'new'})
        app._call_windows = {'a': Mock()}
        DesktopCalls.call_event(app, 'a', {'token': 'old', 'state': 'ended'})
        app._call_windows['a'].update.assert_not_called()
        DesktopCalls.call_event(app, 'a', {'token': 'new', 'state': 'active'})
        app._call_windows['a'].update.assert_called_once()

class CallControlsTests(unittest.TestCase):
    def setUp(self):
        set_language('en')
        self.owner, _ = app_fixture()
        self.view = CallWindow.__new__(CallWindow)
        self.view.owner, self.view.account = self.owner, 'a'
        self.view.window = Mock()
        self.view.heading = Mock()
        self.view.status = Mock()
        self.view.fingerprint = Mock()
        self.view.picture = Mock()
        self.view.controls = Mock()
        self.view.buttons = {key: Mock() for key in ('accept', 'accept_video', 'mute', 'camera', 'screen', 'hangup')}
        self.view.snapshot = {}
        self.view.pending = False
        self.view.photo = None
        self.view.timer = 'timer'

    def test_camera_and_microphone_controls_wait_for_connection(self):
        self.view.update({'state': 'connecting', 'token': 'call', 'peer': 2})
        self.assertIn(unittest.mock.call(state='disabled'), self.view.buttons['camera'].configure.call_args_list)
        self.view.buttons['camera'].reset_mock()
        self.view.update({'state': 'active', 'token': 'call', 'peer': 2})
        self.assertIn(unittest.mock.call(state='normal'), self.view.buttons['camera'].configure.call_args_list)

    def test_fingerprint_preserves_emoji_sequences(self):
        sequence = '👩‍💻 🌈 ❤️ 🦊'
        self.view.update({'state': 'active', 'token': 'call', 'peer': 2, 'emojis': sequence})
        self.view.fingerprint.configure.assert_called_with(text=sequence)

    def test_wrapping_toolbar_keeps_hidden_actions_hidden(self):
        self.view.update({'state': 'incoming', 'incoming': True, 'peer': 2, 'token': 'call'})
        self.assertFalse(self.view.buttons['accept'].flow_hidden)
        self.assertTrue(self.view.buttons['camera'].flow_hidden)
        self.view.update({'state': 'ended', 'peer': 2, 'token': 'call'})
        self.assertTrue(all(button.flow_hidden for button in self.view.buttons.values()))

    def test_controls_capture_token_and_peer_before_account_switch(self):
        self.view.snapshot = {'state': 'incoming', 'token': 'call', 'peer': 2}
        self.view.manager = NS(accept=AsyncMock())
        self.view.owner.worker = Mock()
        with patch('tg_ascii.app_lock.is_locked', return_value=False):
            self.view.perform('accept', video=True)
        self.view.manager.accept.assert_called_once_with(video=True, peer=2, token='call')
        self.view.owner.worker.submit.call_args.args[0].close()

    def test_lock_prevents_call_actions(self):
        self.view.manager = Mock()
        with patch('tg_ascii.app_lock.is_locked', return_value=True):
            self.view.perform('set_camera', True)
        self.view.manager.set_camera.assert_not_called()

    def test_new_call_clears_previous_window_action_state(self):
        self.view.snapshot = {'state': 'active', 'token': 'old'}
        self.view.pending = True
        self.view._dismiss_when_ended = True
        self.view.update({'state': 'incoming', 'incoming': True, 'token': 'new', 'peer': 2})
        self.assertFalse(self.view.pending)
        self.assertFalse(self.view._dismiss_when_ended)
        self.view.update({'state': 'ended', 'token': 'new', 'peer': 2})
        self.view.window.destroy.assert_not_called()

    def test_previous_action_callback_cannot_change_new_call(self):
        self.view.snapshot = {'state': 'active', 'token': 'old', 'peer': 2}
        self.view.manager = NS(mute=AsyncMock())
        self.owner.worker = Mock()
        with patch('tg_ascii.app_lock.is_locked', return_value=False):
            self.view.perform('mute', True)
        coroutine, done, failed = self.owner.worker.submit.call_args.args
        coroutine.close()
        self.view.update({'state': 'active', 'token': 'new', 'peer': 2})
        self.view.pending = True
        self.view.status.reset_mock()
        done(None)
        failed(RuntimeError('Old call failed'))
        self.assertTrue(self.view.pending)
        self.view.status.configure.assert_not_called()

    def test_camera_off_discards_visible_frame(self):
        self.view.photo = object()
        self.view.update({'state': 'active', 'token': 'call', 'peer': 2, 'remote_video': False})
        self.view.picture.configure.assert_called_with(image='')
        self.assertIsNone(self.view.photo)
