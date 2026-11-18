import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
from tg_ascii.desktop_actions import DesktopActions
from tg_ascii.interactions import ContextGesture, DesktopInteractions, is_reply_swipe
from tg_ascii.bubbles import BubbleView
from test_v010 import GestureWidget


class SenderProfileTests(unittest.TestCase):
    def app(self):
        app=DesktopActions.__new__(DesktopActions)
        app.ui_account='a';app.active=-100123;app.busy=False;app.selection_kind=None
        app.messages=[NS(id=7,sender_id=123)]
        app.show_contact_profile=Mock()
        return app

    def test_sender_opens_user_not_current_group_and_accepts_channel_senders(self):
        app=self.app()
        for sender in (123,-100789):
            app.messages[0].sender_id=sender
            app.open_sender_profile(app.messages[0],('a',-100123))
            app.show_contact_profile.assert_called_with(sender)
        self.assertEqual(app.show_contact_profile.call_count,2)

    def test_stale_missing_or_selected_sender_never_opens_other_profile(self):
        app=self.app();message=app.messages[0]
        app.open_sender_profile(message,('b',app.active))
        app.open_sender_profile(message,('a',999))
        app.open_sender_profile(NS(id=7,sender_id=999),('a',app.active))
        app.open_sender_profile(NS(id=7,sender_id=None),('a',app.active))
        app.selection_kind='messages';app.open_sender_profile(message,('a',app.active))
        app.show_contact_profile.assert_not_called()

    def test_profile_uses_owned_nonblocking_card_for_explicit_peer(self):
        app=self.app();app.call=Mock()
        with patch('tg_ascii.contact_profile.ContactProfile') as card:
            DesktopActions.show_contact_profile(app,123)
            card.assert_called_once_with(app,123)
        app.call.assert_not_called()

    def test_only_name_hit_is_clickable_in_both_views_and_selection_wins(self):
        app=self.app();message=app.messages[0];app.open_sender_profile=Mock()
        app.history=NS(tag_names=lambda index:('sender', 'sender_profile_7'))
        app.message_at=lambda event:message
        event=NS(x=10,y=20)
        DesktopInteractions.classic_profile_click(app,event)()
        app.open_sender_profile.assert_called_once_with(message,('a',-100123))
        bubble=NS(app=app,target=lambda event:message,gettags=lambda item:('message:7','sender_profile'))
        BubbleView.profile_click(bubble,event)()
        self.assertEqual(app.open_sender_profile.call_count,2)
        app.history.tag_names=lambda index:('msg_7',)
        self.assertIsNone(DesktopInteractions.classic_profile_click(app,event))
        app.selection_kind='messages'
        self.assertIsNone(BubbleView.profile_click(bubble,event))


class ReplyAndNameGestureTests(unittest.TestCase):
    def make(self):
        widget=GestureWidget();profile=Mock();reply=Mock();reaction=Mock();menu=Mock()
        scope=['a']
        gesture=ContextGesture(widget,lambda event:7,menu,reply=reply,double=reaction,
            click=lambda event:profile,scope=lambda:scope[0])
        return widget,gesture,profile,reply,reaction,menu,scope

    def flush(self,widget):
        pending=list(widget.timers.values());widget.timers.clear()
        for callback in pending:callback()

    def test_single_name_click_opens_once_but_double_click_only_reacts(self):
        w,g,profile,reply,reaction,menu,scope=self.make();event=NS(x=100,y=20)
        g.press(event);g.release(event);self.flush(w);profile.assert_called_once()
        profile.reset_mock()
        g.press(event);g.release(event);g.double(event);g.release(event);self.flush(w)
        profile.assert_not_called();reaction.assert_called_once_with(7)

    def test_left_swipe_replies_right_swipe_does_not_and_neither_opens_profile(self):
        for dx,expected in [(-80,1),(80,0),(-64,0)]:
            w,g,profile,reply,reaction,menu,scope=self.make()
            g.press(NS(x=100,y=20));g.motion(NS(x=100+dx,y=25));g.release(NS(x=100+dx,y=25));self.flush(w)
            self.assertEqual(reply.call_count,expected);profile.assert_not_called()
        self.assertFalse(is_reply_swipe(-80,60))

    def test_hold_and_delayed_click_after_switch_do_not_open_profile(self):
        w,g,profile,reply,reaction,menu,scope=self.make();event=NS(x=100,y=20)
        g.press(event);self.flush(w);g.release(event);self.flush(w)
        menu.assert_called_once_with(7);profile.assert_not_called()
        g.press(event);g.release(event);scope[0]='b';self.flush(w);profile.assert_not_called()
