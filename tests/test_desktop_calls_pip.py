import sys
import unittest
from importlib.util import find_spec
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tg_ascii.desktop_calls import CallWindow


class CallWindowPictureInPictureTests(unittest.TestCase):
    def setUp(self):
        self.call = CallWindow.__new__(CallWindow)
        self.call.owner = SimpleNamespace(_app_locked=False, status=Mock())
        self.call.snapshot = {'state': 'active', 'token': 'active', 'video': False}
        self.call.manager = Mock()
        self.call.manager.take_frame.return_value = None
        self.call.manager.take_local_frame.return_value = None
        self.call.window = Mock()
        self.call.pip = Mock()
        self.call._pip_last_remote = self.call._pip_last_shown = 0

    def test_closing_active_call_window_minimizes_and_preserves_the_call(self):
        self.call.dismiss()
        self.call.window.iconify.assert_called_once()
        self.call.owner.status.set.assert_called_once()
        self.call.manager.hangup.assert_not_called()
        self.call.snapshot['state'] = 'ended'
        self.call.dismiss()
        self.call.window.destroy.assert_called_once()

    def test_lock_closes_native_video_before_consuming_frames(self):
        native = self.call.pip
        self.call.owner._app_locked = True
        self.assertFalse(self.call.poll_call_pip())
        native.close.assert_called_once()

        self.call.manager.take_frame.assert_not_called()

    def test_closed_presenter_returns_video_to_inline_consumer(self):
        native = self.call.pip
        native.displaying.return_value = False
        self.assertFalse(self.call.poll_call_pip())
        self.assertIsNone(self.call.pip)
        native.close.assert_called_once()

    def test_video_from_a_previous_call_is_never_displayed(self):
        self.call.manager.take_frame.return_value = {'token': 'previous'}
        self.assertTrue(self.call.poll_call_pip())
        self.call.pip.show.assert_not_called()

    def test_unavailable_system_presenter_falls_back_to_compact_window(self):
        native = self.call.pip
        native.displaying.return_value = False
        native.failed_to_open = True
        with patch('tg_ascii.desktop_call_pip.CompactCallWindow') as compact:
            self.assertTrue(self.call.poll_call_pip())
            compact.assert_called_once_with(self.call)
            self.assertIs(self.call.pip, compact.return_value)
        native.close.assert_called_once()


@unittest.skipUnless(sys.platform == 'darwin' and find_spec('AVKit'), 'requires macOS AVKit')
class MacSystemPipTests(unittest.TestCase):
    def test_drawable_selects_the_call_window_when_another_window_has_focus(self):
        import tkinter as tk
        from tg_ascii.mac_call_pip import native_call_window
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.title('PiP test root')
        call = tk.Toplevel(root)
        call.title('PiP test call')
        root.update()
        root.lift()
        root.focus_force()
        root.update()
        self.assertEqual(native_call_window(call).title(), call.title())
        self.assertEqual(native_call_window(root).title(), root.title())

    def test_missing_native_window_selects_compact_presenter(self):
        from tg_ascii.desktop_call_pip import open_call_pip
        call = SimpleNamespace(window=Mock())
        with patch('tg_ascii.mac_call_pip.MacCallPiP.supported', return_value=True), \
                patch('tg_ascii.mac_call_pip.native_call_window', return_value=None), \
                patch('tg_ascii.desktop_call_pip.CompactCallWindow') as compact:
            self.assertIs(open_call_pip(call), compact.return_value)

    def test_late_restore_callback_finishes_after_a_call_is_released(self):
        from tg_ascii.mac_call_pip import TGMacCallPipDelegate
        delegate = TGMacCallPipDelegate.new()
        delegate.call = None
        restored = []
        delegate.pictureInPictureController_restoreUserInterfaceForPictureInPictureStopWithCompletionHandler_(
            None, restored.append)
        self.assertEqual(restored, [False])
