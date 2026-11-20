"""Lock privacy races are tested without showing any OS notifications."""
from collections import OrderedDict
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

from tg_ascii.i18n import tr
from tg_ascii.notifications import APP_ID, MacCenter, NotificationCenter, WindowsCenter


class LockedNotificationsTests(unittest.TestCase):
    def mac(self):
        adapter = MacCenter.__new__(MacCenter)
        adapter.api = Mock()
        adapter.api.UNAuthorizationOptionAlert = 4
        adapter.api.UNNotificationActionOptionAuthenticationRequired = 1
        adapter.center = Mock()
        adapter.lock = threading.RLock()
        adapter.pending, adapter.actions = OrderedDict(), OrderedDict()
        adapter.requesting = adapter.privacy_locked = False
        adapter.privacy_generation = 0
        return adapter

    def test_lock_during_permission_prompt_redacts_pending_and_revokes_reply(self):
        adapter, reply = self.mac(), Mock()
        adapter.show('Private name', 'Private text', 'chat', Mock(), reply, Mock())
        token = adapter.pending['chat'][3]
        adapter.set_locked(True)
        self.assertEqual(adapter.pending['chat'][:2], ('TeleGraph', tr('New message')))
        adapter.center.removeAllPendingNotificationRequests.assert_called_once()
        adapter.center.removeAllDeliveredNotifications.assert_called_once()
        adapter.center.requestAuthorizationWithOptions_completionHandler_.call_args.args[1](True, None)
        content = adapter.api.UNMutableNotificationContent.alloc().init()
        content.setTitle_.assert_called_once_with('TeleGraph')
        content.setBody_.assert_called_once_with(tr('New message'))
        content.setCategoryIdentifier_.assert_not_called()
        adapter.handle_reply(token, 'must not send')
        reply.assert_not_called()

    def test_os_add_completed_after_lock_removes_that_delayed_request(self):
        adapter = self.mac()
        adapter.show('Private', 'Content', 'chat', Mock())
        adapter.center.requestAuthorizationWithOptions_completionHandler_.call_args.args[1](True, None)
        completed = adapter.center.addNotificationRequest_withCompletionHandler_.call_args.args[1]
        adapter.set_locked(True)
        completed(None)
        adapter.center.removePendingNotificationRequestsWithIdentifiers_.assert_called_once_with(['chat'])
        adapter.center.removeDeliveredNotificationsWithIdentifiers_.assert_called_once_with(['chat'])

    def test_unlock_does_not_restore_private_content_of_old_pending_message(self):
        adapter = self.mac()
        adapter.show('Private', 'Content', 'chat', Mock())
        adapter.set_locked(True)
        adapter.set_locked(False)
        adapter.center.requestAuthorizationWithOptions_completionHandler_.call_args.args[1](True, None)
        content = adapter.api.UNMutableNotificationContent.alloc().init()
        content.setBody_.assert_called_once_with(tr('New message'))

    def test_windows_clears_only_app_identity_and_locked_xml_has_no_reply(self):
        adapter = WindowsCenter.__new__(WindowsCenter)
        adapter.notifier = Mock()
        adapter.notifier.setting = 1
        old = Mock()
        adapter.retained = OrderedDict([('old', old)])
        history, document, toast = Mock(), Mock(), Mock()
        modules = {'winrt.windows.ui.notifications': NS(ToastNotificationManager=NS(history=history),
                    ToastNotification=Mock(return_value=toast), NotificationSetting=NS(ENABLED=1)),
                   'winrt.windows.data.xml.dom': NS(XmlDocument=Mock(return_value=document))}
        with patch.dict('sys.modules', modules):
            adapter.set_locked(True)
            history.clear_with_id.assert_called_once_with(APP_ID)
            adapter.notifier.hide.assert_called_once_with(old)
            self.assertFalse(adapter.retained)
            adapter.show('Private', 'Content', 'new', Mock(), Mock())
        xml = ET.fromstring(document.load_xml.call_args.args[0])
        self.assertEqual([item.text for item in xml.findall('.//text')], ['TeleGraph', tr('New message')])
        self.assertIsNone(xml.find('actions'))

    def test_startup_history_clear_never_requests_notification_permission(self):
        from tg_ascii.notifications import clear_locked_notification_history
        adapter = self.mac()
        with patch('tg_ascii.notifications.sys.platform', 'darwin'), patch('tg_ascii.notifications.MacCenter', return_value=adapter):
            center = clear_locked_notification_history()
        self.assertIs(center.adapter, adapter)
        self.assertTrue(center.locked)
        adapter.center.removeAllDeliveredNotifications.assert_called_once()
        adapter.center.requestAuthorizationWithOptions_completionHandler_.assert_not_called()
        adapter.center.addNotificationRequest_withCompletionHandler_.assert_not_called()

    def test_center_passes_lock_to_new_adapter_and_masks_inputs(self):
        center, adapter = NotificationCenter(Mock()), Mock()
        with patch('tg_ascii.notifications.sys.platform', 'win32'), patch('tg_ascii.notifications.WindowsCenter', return_value=adapter):
            center.set_locked(True)
            center.show('Private', 'Content', 'chat', Mock())
        adapter.set_locked.assert_called_once_with(True)
        self.assertEqual(adapter.show.call_args.args[:2], ('TeleGraph', tr('New message')))
        self.assertIsNone(adapter.show.call_args.args[4])
        center.set_locked(False)
        self.assertEqual(adapter.set_locked.call_args.args, (False,))
