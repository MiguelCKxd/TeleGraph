from collections import OrderedDict
from queue import SimpleQueue
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
import threading
import unittest
from tg_ascii.notifications import WindowsCenter,MacCenter,InlineNotice
from tg_ascii.desktop_plus import DesktopPlus


class NotificationOpenTests(unittest.TestCase):
    def test_windows_body_activation_opens_without_replying(self):
        document,toast=Mock(),Mock();reply,opened=Mock(),Mock()
        native=WindowsCenter.__new__(WindowsCenter);native.notifier=Mock();native.notifier.setting=1;native.retained=OrderedDict()
        args=NS(arguments='open',user_input={});event=Mock();event.as_.return_value=args
        modules={'winrt.windows.data.xml.dom':NS(XmlDocument=Mock(return_value=document)),
                 'winrt.windows.ui.notifications':NS(ToastNotification=Mock(return_value=toast),ToastActivatedEventArgs=object,NotificationSetting=NS(ENABLED=1)),
                 'winrt.system':NS(unbox_string=lambda value:value)}
        with patch.dict('sys.modules',modules):
            native.show('Tg-As','hello','key',Mock(),reply,opened)
            activate=toast.add_activated.call_args.args[0]
            activate(None,event)
            opened.assert_called_once();reply.assert_not_called()
            args.arguments='reply';args.user_input={'reply':'answer'};activate(None,event)
            reply.assert_called_once_with('answer');opened.assert_called_once()

    def test_mac_body_action_uses_token_without_reply_text(self):
        native=MacCenter.__new__(MacCenter);native.api=Mock();native.api.UNAuthorizationOptionAlert=4
        native.center=Mock();native.lock=threading.Lock();native.pending=OrderedDict();native.actions=OrderedDict();native.requesting=False
        opened=Mock()
        native.show('Tg-As','text','chat',Mock(),activate=opened)
        token=native.pending['chat'][3]
        native.handle_open(token);native.handle_open(token)
        opened.assert_called_once()

    def test_os_activation_queues_original_account_chat_message_once(self):
        app=NS(worker=NS(events=SimpleQueue()),open_from_notification=Mock())
        backend=object()
        activate=DesktopPlus.notification_open_callback(app,'first',42,77,backend)
        activate();activate()
        handler,context=app.worker.events.get_nowait()
        self.assertIs(handler,app.open_from_notification)
        self.assertEqual(context,('first',42,77,backend))
        self.assertTrue(app.worker.events.empty());app.open_from_notification.assert_not_called()

    def app(self):
        class App(DesktopPlus):pass
        app=App();backend=object();pending=[]
        app.closed=app.closing=app.demo=app.busy=False;app.stage='ready';app.ui_account='one'
        app.service=NS(entries={'one':{}},services={'one':NS(backend=backend)})
        app.root=NS(after=lambda ms,fn:pending.append(fn),after_idle=lambda fn:pending.append(fn))
        app.notebook=Mock();app.chat_page=object();app.status=Mock()
        app.reopen_window=Mock();app.jump_message=Mock();app.clear_selection=Mock();app.adapt_chat_layout=Mock();app.switch_account=Mock()
        return app,backend,pending

    def test_click_restores_window_selects_chats_and_jumps_to_exact_message(self):
        app,backend,pending=self.app()
        app._preview_only=True
        app.open_from_notification(('one',42,77,backend))
        app.reopen_window.assert_called_once();app.notebook.select.assert_called_once_with(app.chat_page)
        app.jump_message.assert_called_once_with(77,42)
        self.assertFalse(app._preview_only);self.assertTrue(app.compact_conversation)
        app.clear_selection.assert_called_once()

    def test_waits_for_busy_operation_then_switches_account_before_jump(self):
        app,backend,pending=self.app();app.ui_account='other';app.busy=True
        context=('one',42,77,backend)
        app.open_from_notification(context)
        app.switch_account.assert_not_called();app.jump_message.assert_not_called()
        app.busy=False;pending.pop(0)()
        app.switch_account.assert_called_once_with('one');app.jump_message.assert_not_called()
        app.ui_account='one';pending.pop(0)()
        app.jump_message.assert_called_once_with(77,42)

    def test_failed_account_switch_does_not_loop_or_open_another_account(self):
        app,backend,pending=self.app();app.ui_account='other'
        app.open_from_notification(('one',42,77,backend));pending.pop(0)()
        app.switch_account.assert_called_once();app.jump_message.assert_not_called()
        self.assertIsNone(app._notification_target);self.assertFalse(pending)

    def test_logged_out_notification_and_replaced_pending_click_cannot_navigate(self):
        app,backend,pending=self.app();app.service.entries.clear()
        app.open_from_notification(('one',42,77,backend));app.jump_message.assert_not_called()
        app.service.entries['one']={};app.busy=True
        app.open_from_notification(('one',42,77,backend))
        app.open_from_notification(('one',43,88,backend))
        app.busy=False
        while pending:pending.pop(0)()
        app.jump_message.assert_called_once_with(88,43)

    def test_inline_body_click_closes_notice_and_queues_navigation_once(self):
        pending=[];root=NS(after=Mock(),after_cancel=Mock(),after_idle=lambda fn:pending.append(fn),winfo_width=lambda:600)
        frame,heading,title,body=Mock(),Mock(),Mock(),Mock();activate=Mock()
        notice=InlineNotice(root)
        with patch('tkinter.Frame',side_effect=[frame,heading]),patch('tkinter.Label',side_effect=[title,body]),patch('tkinter.ttk.Button'),patch.object(notice,'monitor'):
            notice.show('Ada','message',activate)
            click=body.bind.call_args.args[1];click();click()
        frame.destroy.assert_called_once();activate.assert_not_called()
        pending.pop(0)();activate.assert_called_once();self.assertFalse(pending)

    def test_inline_reply_stops_timeout_and_sends_exact_text_once(self):
        root=NS(after=Mock(return_value='timer'),after_cancel=Mock(),after_idle=Mock(),winfo_width=lambda:600)
        frame,heading,title,body,row,entry=Mock(),Mock(),Mock(),Mock(),Mock(),Mock()
        reply=Mock();buttons=[]
        def button(parent,**options):buttons.append(options);return Mock()
        notice=InlineNotice(root)
        with patch('tkinter.Frame',side_effect=[frame,heading]),patch('tkinter.Label',side_effect=[title,body]),patch('tkinter.ttk.Frame',return_value=row),patch('tkinter.ttk.Entry',return_value=entry),patch('tkinter.ttk.Button',side_effect=button),patch.object(notice,'monitor'):
            notice.show('Ada','Message',reply=reply)
            buttons[2]['command']() # Reply, after close and send buttons.
            self.assertTrue(notice.replying);root.after_cancel.assert_called_once_with('timer')
            entry.focus_set.assert_called_once()
            entry.get.side_effect=['  Hello 🙂  ',RuntimeError('Entry already destroyed')]
            buttons[1]['command']();buttons[1]['command']()
        reply.assert_called_once_with('  Hello 🙂  ');frame.destroy.assert_called_once()

    def test_new_notice_does_not_destroy_active_reply(self):
        root=Mock();notice=InlineNotice(root);notice.frame=Mock();notice.replying=True
        old_frame=notice.frame;opened,reply=Mock(),Mock()
        notice.show('Another','Message',opened,reply)
        old_frame.destroy.assert_not_called()
        self.assertEqual(notice.pending,('Another','Message',opened,reply))
        notice.finish()
        old_frame.destroy.assert_called_once();root.after_idle.assert_called_once()


if __name__=='__main__':unittest.main()
