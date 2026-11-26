from collections import OrderedDict
from io import StringIO
import threading
from unittest import TestCase
from unittest.mock import Mock, patch

from tg_ascii.notifications import LinuxCenter


class LinuxNotificationRaceTests(TestCase):
    def center(self):
        center = LinuxCenter.__new__(LinuxCenter)
        center.tool, center.icon = 'fixture-notify-send', 'fixture-icon'
        center.gdbus = None
        center.lock = threading.Lock()
        center.ids, center.waiting = OrderedDict(), OrderedDict()
        center.privacy_locked, center.privacy_generation = False, 0
        center._close = Mock()
        return center

    def test_id_delivered_after_lock_is_closed_even_if_user_unlocks_again(self):
        center = self.center()
        process = Mock(stdout=StringIO('17\ndefault\n'), stderr=StringIO(''))
        process.wait.return_value = 0
        activate = Mock()
        with patch('subprocess.Popen', return_value=process), patch('threading.Thread') as thread:
            center.show('private sender', 'private text', 'key', Mock(), activate=activate)
            watcher = thread.call_args.kwargs['target']
        center.set_locked(True)
        center.set_locked(False)
        watcher()
        center._close.assert_called_once_with('17')
        self.assertFalse(center.ids)
        activate.assert_not_called()

    def test_current_notification_keeps_click_and_locked_show_is_redacted(self):
        center = self.center()
        process = Mock(stdout=StringIO('18\ndefault\n'), stderr=StringIO(''))
        process.wait.return_value = 0
        activate = Mock()
        with patch('subprocess.Popen', return_value=process), patch('threading.Thread') as thread:
            center.show('sender', 'text', 'key', Mock(), activate=activate)
            thread.call_args.kwargs['target']()
        self.assertEqual(center.ids['key'], '18')
        activate.assert_called_once()
        center.set_locked(True)
        with patch('subprocess.Popen', return_value=process) as spawn, patch('threading.Thread'):
            center.show('private sender', 'private text', 'other', Mock())
        command = spawn.call_args.args[0]
        self.assertNotIn('private sender', command)
        self.assertNotIn('private text', command)
