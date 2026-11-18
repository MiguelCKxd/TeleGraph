from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock,patch
from tg_ascii.profile_tabs import ProfileTabPane
from tg_ascii.contact_profile import ContactProfile
from tg_ascii.shared_media import SharedMediaBrowser
from tg_ascii.desktop_customization import DesktopCustomization
from tg_ascii.backend import Chat


class DisabledProfileTests(unittest.TestCase):
    def setUp(self):
        self.app=NS(demo=False,busy=False,preferences=NS(values={'advanced_features':{}}))

    def test_existing_profile_panes_do_no_work_after_feature_disabled(self):
        for kind in ('posts','gifts'):
            pane=object.__new__(ProfileTabPane)
            pane.view=NS(valid=lambda:True,requests=Mock())
            pane.app,pane.kind=self.app,kind
            pane.more=True
            pane.fetch();pane.fetch(True)
            pane.view.requests.submit.assert_not_called()

    def test_existing_poll_and_link_tabs_do_not_page_or_open(self):
        for kind in ('polls','links'):
            profile=object.__new__(ContactProfile)
            profile.app=self.app;profile.valid=lambda:True;profile.media=Mock()
            profile.fetch_media(kind);profile.open_media(kind)
            profile.media.begin.assert_not_called()
            browser=object.__new__(SharedMediaBrowser)
            browser.app=self.app;browser.valid=lambda:True;browser.kind=lambda:kind;browser.pages=Mock()
            browser.fetch();browser.open()
            browser.pages.begin.assert_not_called()

    def test_profile_selection_does_not_instantiate_a_disabled_pane(self):
        profile=object.__new__(ContactProfile)
        profile.app=self.app;profile.valid=lambda:True;profile.order=['posts'];profile.selected=lambda:'posts'
        profile.selector=Mock();profile.extra_panes={}
        with patch('tg_ascii.profile_tabs.ProfileTabPane') as pane:
            profile.changed();pane.assert_not_called()
        profile.selector.current.assert_not_called()


class OpenSelectedChatTests(unittest.TestCase):
    def app(self):
        app=NS(closed=False,closing=False,ui_account='a',active=1,chats=[Chat(1,'Main'),Chat(2,'Second')],
               service=NS(backend=object()),show_error=Mock(),call=Mock(),_app_locked=False)
        return app

    def test_selected_chat_does_not_change_main_or_reuse_old_window(self):
        app=self.app()
        with patch('tg_ascii.interface_windows.open_linked_app_window',side_effect=[object(),object()]) as opened:
            first=DesktopCustomization.open_chat_in_new_window(app,2)
            second=DesktopCustomization.open_chat_in_new_window(app,2)
            self.assertIsNot(first,second)
            self.assertEqual(opened.call_count,2)
            self.assertIs(opened.call_args.kwargs['initial_chat'],app.chats[1])
        self.assertEqual((app.ui_account,app.active),('a',1));app.call.assert_not_called()

    def test_stale_account_or_locked_app_cannot_open_a_chat(self):
        app=self.app()
        with patch('tg_ascii.interface_windows.open_linked_app_window') as opened:
            DesktopCustomization.open_chat_in_new_window(app,2,account='old')
            app._app_locked=True
            DesktopCustomization.open_chat_in_new_window(app,2)
            opened.assert_not_called()

    def test_resolved_profile_chat_ignores_a_late_account_switch(self):
        app=self.app();app.service.backend=Mock();app.service.backend.resolve_chat.return_value='operation'
        with patch('tg_ascii.interface_windows.open_linked_app_window') as opened:
            DesktopCustomization.open_chat_in_new_window(app,3)
            app.call.assert_called_once()
            callback=app.call.call_args.args[1]
            app.ui_account='b';callback(Chat(3,'Third'));opened.assert_not_called()


if __name__=='__main__':unittest.main()
