"""No OS notifications, real sessions or Telegram messages are emitted by these tests."""
import asyncio
from collections import OrderedDict
from queue import SimpleQueue
from types import SimpleNamespace as NS
import threading
import unittest
from unittest.mock import Mock, AsyncMock, patch
import xml.etree.ElementTree as ET
from tg_ascii.notifications import NotificationCenter, WindowsCenter, MacCenter, notification_xml, notification_key, app_foreground
from tg_ascii.desktop_plus import DesktopPlus
from tg_ascii.i18n import tr


class NotificationTests(unittest.TestCase):
    def test_xml_is_escaped_silent_and_has_native_reply_input(self):
        xml = ET.fromstring(notification_xml('Ada & <Bob>', 'a < b\x00\n🙂', True))
        self.assertEqual(xml.find('.//text').text, 'Ada & <Bob>')
        self.assertEqual(xml.find('audio').get('silent'), 'true')
        self.assertEqual(xml.find('.//input').get('id'), 'reply')
        self.assertEqual(xml.find('.//action').get('hint-inputId'), 'reply')
        self.assertIsNone(ET.fromstring(notification_xml('x','y')).find('actions'))

    def test_key_is_account_scoped_and_foreground_excludes_hidden_window(self):
        self.assertNotEqual(notification_key('one', 42), notification_key('two', 42))
        self.assertEqual(len(notification_key('one',42)), 16)
        root=NS(state=lambda:'withdrawn', focus_displayof=lambda:object())
        self.assertFalse(app_foreground(root))
        root.state=lambda:'normal'
        self.assertTrue(app_foreground(root))

    def test_mac_unbundled_guard_precedes_framework_initialization(self):
        foundation=NS(NSBundle=NS(mainBundle=lambda:NS(bundleIdentifier=lambda:'org.python.python')))
        with patch.dict('sys.modules',{'Foundation':foundation}):
            with self.assertRaisesRegex(RuntimeError,'compiled'):MacCenter()

    def test_native_failure_reported_once_without_floating_fallback(self):
        report=Mock(); center=NotificationCenter(report)
        with patch('tg_ascii.notifications.sys.platform','win32'), patch('tg_ascii.notifications.WindowsCenter',side_effect=OSError('blocked')) as native:
            center.show('x','y','key');center.show('x','y','key')
        native.assert_called_once();report.assert_called_once_with('blocked')

    def test_windows_allows_system_banner_and_decodes_reply(self):
        document,toast=Mock(),Mock();reply=Mock()
        native=WindowsCenter.__new__(WindowsCenter);native.notifier=Mock();native.notifier.setting=1;native.retained=OrderedDict()
        args=NS(arguments='reply',user_input={'reply':' Hello 🙂 '})
        event=Mock();event.as_.return_value=args
        modules={'winrt.windows.data.xml.dom':NS(XmlDocument=Mock(return_value=document)),
                 'winrt.windows.ui.notifications':NS(ToastNotification=Mock(return_value=toast),ToastActivatedEventArgs=object,NotificationSetting=NS(ENABLED=1)),
                 'winrt.system':NS(unbox_string=lambda value:value)}
        with patch.dict('sys.modules',modules):
            native.show('Tg-As','hello','key',Mock(),reply)
            self.assertFalse(toast.suppress_popup)
            toast.add_activated.call_args.args[0](None,event)
        reply.assert_called_once_with(' Hello 🙂 ')
        native.notifier.show.assert_called_once_with(toast)

    def test_windows_first_toast_does_not_require_existing_settings_record(self):
        error = OSError('No settings record for this new AUMID')
        error.winerror = -2147023728  # HRESULT_FROM_WIN32(ERROR_NOT_FOUND)
        class FirstNotifier:
            show = Mock()
            @property
            def setting(self):
                raise error
        native = WindowsCenter.__new__(WindowsCenter)
        native.notifier = FirstNotifier(); native.retained = OrderedDict()
        toast, report = Mock(), Mock()
        modules = {'winrt.windows.data.xml.dom': NS(XmlDocument=Mock()),
                   'winrt.windows.ui.notifications': NS(ToastNotification=Mock(return_value=toast),
                                                        NotificationSetting=NS(ENABLED=1))}
        with patch.dict('sys.modules', modules):
            native.show('Synthetic', 'Synthetic', 'first', report)
        native.notifier.show.assert_called_once_with(toast)
        report.assert_not_called()

    def test_windows_explicitly_disabled_permission_never_delivers(self):
        native = WindowsCenter.__new__(WindowsCenter)
        native.notifier = Mock(setting=2); native.retained = OrderedDict()
        report = Mock()
        modules = {'winrt.windows.data.xml.dom': NS(XmlDocument=Mock()),
                   'winrt.windows.ui.notifications': NS(ToastNotification=Mock(),
                                                        NotificationSetting=NS(ENABLED=1))}
        with patch.dict('sys.modules', modules):
            native.show('Synthetic', 'Synthetic', 'disabled', report)
        native.notifier.show.assert_not_called()
        report.assert_called_once()

    def mac(self):
        native=MacCenter.__new__(MacCenter)
        native.api=Mock();native.api.UNAuthorizationOptionAlert=4;native.api.UNNotificationActionOptionAuthenticationRequired=1
        native.api.UNNotificationCategory.categoryWithIdentifier_actions_intentIdentifiers_options_.return_value='category'
        native.center=Mock();native.lock=threading.Lock();native.pending=OrderedDict();native.actions=OrderedDict();native.requesting=False
        return native

    def test_mac_permission_denied_never_delivers_and_keeps_app_usable(self):
        native=self.mac();report=Mock()
        native.show('Tg-As','private','key',report)
        native.center.requestAuthorizationWithOptions_completionHandler_.call_args.args[1](False,None)
        native.center.addNotificationRequest_withCompletionHandler_.assert_not_called()
        report.assert_called_once()

    def test_mac_permission_coalesces_and_reply_token_is_consumed_once(self):
        native=self.mac();reply=Mock()
        native.show('old','old','chat',Mock(),Mock())
        native.show('latest','text','chat',Mock(),reply)
        self.assertEqual(len(native.pending),1)
        token=native.pending['chat'][3]
        native.center.requestAuthorizationWithOptions_completionHandler_.assert_called_once()
        native.center.requestAuthorizationWithOptions_completionHandler_.call_args.args[1](True,None)
        native.center.addNotificationRequest_withCompletionHandler_.assert_called_once()
        native.handle_reply(token,'answer');native.handle_reply(token,'duplicate')
        reply.assert_called_once_with('answer')

    def test_os_callback_queues_once_without_accessing_tk(self):
        app=NS(worker=NS(events=SimpleQueue()),reply_from_notification=Mock())
        backend=object()
        callback=DesktopPlus.notification_reply_callback(app,'one',42,7,backend)
        callback('   ');callback(' hello ');callback('duplicate')
        handler, context=app.worker.events.get_nowait()
        self.assertIs(handler,app.reply_from_notification)
        self.assertEqual(context,('one',42,7,backend,' hello '))
        self.assertTrue(app.worker.events.empty())
        app.reply_from_notification.assert_not_called()

    def test_reply_uses_captured_account_peer_and_reply_id_after_switch(self):
        backend=NS(send_formatted=AsyncMock(return_value=NS(id=99)))
        other=NS(send_formatted=AsyncMock())
        tasks=[]
        app=NS(closed=False,closing=False,demo=False,ui_account='two',active=999,
               service=NS(entries={'one':{},'two':{}},services={'one':NS(backend=backend),'two':NS(backend=other)}),
               worker=NS(submit=lambda coroutine,success,failure:tasks.append((coroutine,success))),
               status=Mock(),account_event=Mock())
        DesktopPlus.reply_from_notification(app,('one',42,7,backend,'hi'))
        coroutine,success=tasks[0];result=asyncio.run(coroutine);success(result)
        backend.send_formatted.assert_awaited_once_with(42,'hi',[],reply_to=7)
        other.send_formatted.assert_not_awaited()
        app.account_event.assert_called_once_with(('one',42,result))
        self.assertEqual((app.ui_account,app.active),('two',999))

    def test_logout_before_worker_runs_prevents_reply(self):
        backend=NS(send_formatted=AsyncMock());tasks=[]
        app=NS(closed=False,closing=False,demo=False,
               service=NS(entries={'one':{}},services={'one':NS(backend=backend)}),
               worker=NS(submit=lambda coroutine,*callbacks:tasks.append(coroutine)))
        DesktopPlus.reply_from_notification(app,('one',42,7,backend,'hi'))
        app.service.entries.clear()
        with self.assertRaises(ValueError):asyncio.run(tasks[0])
        backend.send_formatted.assert_not_awaited()

    def test_routing_rechecks_visibility_and_respects_preview_and_mute(self):
        backend=NS(notification_policy=AsyncMock());requests=[]
        values=dict(notifications=True,notify_preview=False,notify_sound=True,notify_active=False)
        root=NS(state=lambda:'normal',focus_displayof=lambda:object(),bell=Mock())
        app=NS(demo=False,preferences=NS(values=values),notify_seen=set(),ui_account='one',active=5,
               root=root,chat_visible=lambda:True,service=NS(entries={'one':{}},labels={'one':'Account'},service=lambda _:NS(backend=backend)),
               worker=NS(submit=lambda coro,loaded,fail:requests.append((coro,loaded))),
               inline_notice=Mock(),notification_center=Mock(),notification_reply_callback=Mock(return_value='callback'),
               notification_open_callback=Mock(return_value='open_callback'))
        message=NS(outgoing=False,id=1,text='private',sender='Ada')
        DesktopPlus.notify_message(app,'one',42,message)
        coro,loaded=requests.pop();coro.close();loaded(dict(enabled=True,preview=True,sound=True))
        app.inline_notice.show.assert_called_once_with('Account · Ada',tr('New message'),'open_callback','callback')
        app.notification_center.show.assert_not_called()
        root.state=lambda:'withdrawn'
        message.id=2;DesktopPlus.notify_message(app,'one',42,message)
        coro,loaded=requests.pop();coro.close();loaded(dict(enabled=True,preview=True,sound=True))
        self.assertEqual(app.notification_center.show.call_args.args[3],'callback')
        root.bell.assert_called_once()
        message.id=3;DesktopPlus.notify_message(app,'one',42,message)
        coro,loaded=requests.pop();coro.close();loaded(dict(enabled=False,preview=True,sound=True))
        app.notification_center.show.assert_called_once()

    def test_notify_message_suppressed_for_closed_thread(self):
        values = dict(notifications=True, notify_preview=False, notify_sound=True, notify_active=False)
        app = NS(preferences=NS(values=values),
                 notify_seen=set(), _suppressed_thread_peers={999}, demo=False,
                 notification_history=None)
        message = NS(outgoing=False, id=1, text='thread comment', sender='Bob')
        DesktopPlus.notify_message(app, 'one', 999, message)
        self.assertNotIn(( 'one', 999, 1), app.notify_seen)

    def test_journal_respects_lock_preview_and_temporary_content(self):
        cases = [(False, True, True, False, 0, True),
                 (True, True, True, False, 0, False),
                 (False, False, True, False, 0, False),
                 (False, True, False, False, 0, False),
                 (False, True, True, True, 0, False),
                 (False, True, True, False, 60, False)]
        for locked, local_preview, remote_preview, protected, ttl, retained in cases:
            with self.subTest(locked=locked, local=local_preview, remote=remote_preview, protected=protected, ttl=ttl):
                requests = []
                backend = NS(notification_policy=AsyncMock())
                values = dict(notifications=True, notify_preview=local_preview, notify_sound=False, notify_active=False)
                app = NS(demo=False, preferences=NS(values=values), notify_seen=set(), ui_account='one', active=5,
                         root=NS(state=lambda:'withdrawn', focus_displayof=lambda:None),
                         service=NS(entries={'one':{}}, labels={'one':'Account'}, service=lambda _:NS(backend=backend)),
                         worker=NS(submit=lambda coro, loaded, fail:requests.append((coro, loaded))),
                         inline_notice=Mock(), notification_center=Mock(), notification_reply_callback=Mock(),
                         notification_open_callback=Mock())
                message = NS(outgoing=False, id=1, text='private fixture body', sender='Sender',
                             protected=protected, ttl_period=ttl)
                with patch('tg_ascii.desktop_plus.record_notice') as record, patch('tg_ascii.app_lock.is_locked', return_value=locked):
                    DesktopPlus.notify_message(app, 'one', 42, message)
                    self.assertTrue(all(not call.kwargs.get('content') for call in record.call_args_list))
                    coro, loaded = requests.pop()
                    coro.close()
                    loaded(dict(enabled=True, preview=remote_preview, sound=False))
                payloads = [call.kwargs.get('content', '') for call in record.call_args_list]
                self.assertEqual(any('private fixture body' in content for content in payloads), retained)

    def test_reading_chat_suppresses_notification_when_linked_chat_window_open(self):
        values = dict(notifications=True, notify_preview=False, notify_sound=True, notify_active=False)
        root = NS(state=lambda: 'normal', focus_displayof=lambda: None)
        win = NS(account='one', peer=777, valid=lambda: True, chat_visible=lambda: True)
        service = Mock()
        app = NS(preferences=NS(values=values),
                 notify_seen=set(), _suppressed_thread_peers=set(), demo=False,
                 ui_account='one', active=10, _chat_windows=[win], root=root,
                 notification_history=None, service=service)
        message = NS(outgoing=False, id=1, text='chat message', sender='Alice')
        DesktopPlus.notify_message(app, 'one', 777, message)
        service.service.assert_not_called()


if __name__=='__main__':unittest.main()
