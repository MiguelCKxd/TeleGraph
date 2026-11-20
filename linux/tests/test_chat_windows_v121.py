"""Chat-only child boundaries, without Tk roots, accounts or network calls."""
from concurrent.futures import Future
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from tg_ascii.backend import Chat
from tg_ascii.contact_appearance import ACTIONS, ordered_actions, validated_contact
from tg_ascii.desktop import Desktop
from tg_ascii.interface_layout import LayoutRuntime
from tg_ascii.interface_store import default_layout
from tg_ascii.interface_windows import WindowWorker, cancel_view_timers
from tg_ascii.i18n import tr


def context_model(child=False):
    chat = Chat(41, 'Synthetic conversation')
    callbacks = ('contact_info search_chat shared_media pinned_dialog toggle_pin scheduled_messages '
                 'choose_wallpaper commands_menu open_bot_app toggle_local_pin close open_chat_in_new_window '
                 'toggle_chat_selection mute_menu chat_history_action membership_action preview_chat')
    values = {name: Mock(name=name) for name in callbacks.split()}
    return NS(**values, _chat_only=child, _pinned_account='a' if child else None,
              _pinned_peer=41 if child else None, _linked_owner=NS() if child else None,
              closed=False, closing=False, busy=False, demo=False, active=41, ui_account='a',
              chats=[chat], preferences=NS(values={'local_pins': False}), root=object(),
              pinned_button=object(), bot_buttons={name: NS(flow_hidden=True) for name in ('Bot commands', 'Open Mini App')},
              service=NS(backend=object()), selected_folder=lambda: None)


def captured_menu(operation):
    caps = NS(kind='user',allows=lambda feature: False, can_join=False, can_leave=False)
    with patch('tg_ascii.app_dialogs.popup_menu') as popup, \
            patch('tg_ascii.chat_capabilities.chat_capabilities', return_value=caps):
        operation()
    return popup.call_args.args[1] if popup.called else []


class ChatToolsTests(unittest.TestCase):
    def test_main_header_opens_duplicate_children_without_changing_selection(self):
        app = context_model()
        entries = captured_menu(lambda: Desktop.chat_tools_menu(app))
        choices = [entry[1] for entry in entries if entry and entry[0] == tr('Open chat in new window')]
        self.assertEqual(len(choices), 1)
        choices[0](); choices[0]()
        self.assertEqual(app.open_chat_in_new_window.call_count, 2)
        self.assertEqual((app.ui_account, app.active), ('a', 41))
        app.close.assert_not_called()

    def test_child_header_replaces_open_with_close_and_retains_chat_tools(self):
        app = context_model(child=True)
        entries = captured_menu(lambda: Desktop.chat_tools_menu(app))
        labels = [entry[0] for entry in entries if entry]
        self.assertNotIn(tr('Open chat in new window'), labels)
        self.assertIn(tr('Search in chat'), labels)
        self.assertIn(tr('Shared media'), labels)
        choices = [entry[1] for entry in entries if entry and entry[0] == tr('Close')]
        self.assertEqual(len(choices), 1)
        choices[0]()
        app.close.assert_called_once()
        app.open_chat_in_new_window.assert_not_called()

    def test_main_list_action_opens_selected_peer_without_selecting_it(self):
        app = context_model()
        app.active = 99
        entries = captured_menu(lambda: Desktop.chat_actions(app, 41))
        choices = [entry[1] for entry in entries if entry and entry[0] == tr('Open chat in new window')]
        self.assertEqual(len(choices), 1)
        choices[0](); choices[0]()
        self.assertEqual(app.active, 99)
        self.assertEqual(app.open_chat_in_new_window.call_count, 2)
        self.assertEqual(app.open_chat_in_new_window.call_args.args, (41, app.chats[0], 'a'))


class UnifiedMenuTests(unittest.TestCase):
    def test_both_menus_share_tools_and_keep_their_exclusive_entries(self):
        app = context_model()
        app.mute_menu = Mock(); app.membership_action = Mock(); app.chat_history_action = Mock()
        inside = [entry[0] for entry in captured_menu(lambda: Desktop.chat_tools_menu(app)) if entry]
        listing = [entry[0] for entry in captured_menu(lambda: Desktop.chat_actions(app, 41)) if entry]
        for shared in ('Search in chat', 'Shared media', 'Mute', 'Archive', 'Add to folder', 'Delete chat'):
            self.assertIn(tr(shared), inside); self.assertIn(tr(shared), listing)
        for exclusive in ('Select', 'Preview chat — unread', 'Mark as read'):
            self.assertIn(tr(exclusive), listing); self.assertNotIn(tr(exclusive), inside)
        self.assertIn(tr('Select messages'), inside); self.assertNotIn(tr('Select messages'), listing)
        # 1.5.2: "Close chat" only in the in-chat menu.
        self.assertIn(tr('Close chat'), inside); self.assertNotIn(tr('Close chat'), listing)


class OpenWindowGuardsTests(unittest.TestCase):
    def model(self, child=False):
        app = context_model(child)
        del app.open_chat_in_new_window
        app.show_error = Mock()
        return app

    def test_duplicate_explicit_open_is_not_deduplicated(self):
        app = self.model()
        first, second = object(), object()
        with patch('tg_ascii.app_lock.show_locked', return_value=False), \
                patch('tg_ascii.interface_windows.open_linked_app_window', side_effect=[first, second]) as opened:
            self.assertIs(Desktop.open_chat_in_new_window(app), first)
            self.assertIs(Desktop.open_chat_in_new_window(app), second)
        self.assertEqual(opened.call_count, 2)
        self.assertEqual((app.ui_account, app.active), ('a', 41))

    def test_child_cannot_recursively_spawn_another_window(self):
        app = self.model(child=True)
        with patch('tg_ascii.app_lock.show_locked', return_value=False), \
                patch('tg_ascii.interface_windows.open_linked_app_window') as opened:
            Desktop.open_chat_in_new_window(app)
        opened.assert_not_called()

    def test_locked_closed_or_foreign_account_never_opens_window(self):
        for mode in ('locked', 'closed', 'closing', 'foreign'):
            with self.subTest(mode=mode):
                app = self.model()
                app.closed = mode == 'closed'; app.closing = mode == 'closing'
                with patch('tg_ascii.app_lock.show_locked', return_value=mode == 'locked'), \
                        patch('tg_ascii.interface_windows.open_linked_app_window') as opened:
                    Desktop.open_chat_in_new_window(app, account='other' if mode == 'foreign' else 'a')
                opened.assert_not_called()

    def test_late_resolve_after_account_switch_does_not_create_window(self):
        app = self.model()
        pending = []
        async def resolve(peer):
            return Chat(peer, 'Synthetic resolved chat')
        app.service.backend = NS(resolve_chat=resolve)
        def call(operation, done, text):
            operation.close()
            pending.append(done)
        app.call = call
        with patch('tg_ascii.app_lock.show_locked', return_value=False), \
                patch('tg_ascii.interface_windows.open_linked_app_window') as opened:
            Desktop.open_chat_in_new_window(app, peer=777)
            self.assertEqual(len(pending), 1)
            app.ui_account = 'b'
            pending[0](Chat(777, 'Synthetic resolved chat'))
        opened.assert_not_called()

    def test_late_resolve_after_lock_does_not_create_window(self):
        app = self.model()
        pending = []
        async def resolve(peer):
            return Chat(peer, 'Synthetic resolved chat')
        app.service.backend = NS(resolve_chat=resolve)
        def call(operation, done, text):
            operation.close(); pending.append(done)
        app.call = call
        with patch('tg_ascii.app_lock.show_locked', side_effect=[False, True]), \
                patch('tg_ascii.interface_windows.open_linked_app_window') as opened:
            Desktop.open_chat_in_new_window(app, peer=777)
            pending[0](Chat(777, 'Synthetic resolved chat'))
        opened.assert_not_called()


class RemovedEntryPointsTests(unittest.TestCase):
    def test_legacy_contact_preferences_cannot_restore_new_window_action(self):
        self.assertNotIn('new_window', ACTIONS)
        values = validated_contact({'contact_action_order': ['new_window', 'message'],
                                    'contact_hidden_actions': ['new_window']})
        self.assertNotIn('new_window', values['contact_action_order'])
        self.assertNotIn('new_window', values['contact_hidden_actions'])
        self.assertNotIn('new_window', ordered_actions(values, ['message', 'new_window']))

    def test_custom_layout_does_not_offer_or_execute_legacy_new_window_command(self):
        app = NS(closed=False, closing=False, _chat_only=False)
        for name in ('open_fixed_settings', 'open_customization', 'refresh', 'saved_messages',
                     'open_contacts', 'folder_dialog', 'telegram_picker', 'pick_attachment',
                     'send', 'open_chat_window', 'open_linked_app_window', 'open_independent_window'):
            setattr(app, name, Mock(name=name))
        layout = LayoutRuntime(app, NS(document=default_layout()))
        self.assertNotIn('new-window', layout.actions())
        layout.invoke('new-window')
        app.open_chat_window.assert_not_called()
        app.open_linked_app_window.assert_not_called()
        app.open_independent_window.assert_not_called()

    def test_legacy_menu_filter_preserves_other_actions_and_source_data(self):
        entries = [{'text': 'Old shortcut', 'action': 'new-window'},
                   {'text': 'Refresh', 'action': 'refresh'}, 'invalid',
                   {'text': 'Send', 'action': 'send'}]
        original = list(entries)
        self.assertEqual(LayoutRuntime.available_entries(entries), [entries[1], entries[3]])
        self.assertEqual(entries, original)

    def test_custom_widget_alias_cannot_resurrect_legacy_new_window_action(self):
        app = NS(closed=False, closing=False, _chat_only=False)
        for name in ('open_fixed_settings', 'open_customization', 'refresh', 'saved_messages',
                     'open_contacts', 'folder_dialog', 'telegram_picker', 'pick_attachment',
                     'send', 'open_chat_window', 'open_linked_app_window', 'open_independent_window'):
            setattr(app, name, Mock(name=name))
        document = default_layout()
        document['items'] = [{'id': 'legacy', 'kind': 'button', 'action': 'new-window'}]
        layout = LayoutRuntime(app, NS(document=document))
        layout.invoke('widget:custom/legacy')
        app.open_chat_window.assert_not_called()


class ChatVisibilityTests(unittest.TestCase):
    def test_child_visibility_uses_its_own_window_without_notebook(self):
        root = NS(winfo_viewable=lambda: True, state=lambda: 'normal')
        root.focus_displayof = lambda: NS(winfo_toplevel=lambda: root)
        child = NS(root=root, _chat_only=True, closed=False, closing=False)
        self.assertTrue(Desktop.chat_visible(child))

    def test_child_does_not_acknowledge_when_focus_belongs_to_other_window(self):
        other_root = object()
        root = NS(winfo_viewable=lambda: True, state=lambda: 'normal',
                  focus_displayof=lambda: NS(winfo_toplevel=lambda: other_root))
        child = NS(root=root, _chat_only=True, closed=False, closing=False)
        self.assertFalse(Desktop.chat_visible(child))

    def test_principal_does_not_acknowledge_when_chat_child_has_focus(self):
        child_root = object()
        root = NS(winfo_viewable=lambda: True, state=lambda: 'normal',
                  focus_displayof=lambda: NS(winfo_toplevel=lambda: child_root))
        app = NS(root=root, _chat_only=False, closed=False, closing=False, chat_page='chat-page',
                 notebook=NS(winfo_exists=lambda: True, select=lambda: 'chat-page'))
        self.assertFalse(Desktop.chat_visible(app))

    def test_hidden_child_is_not_visible_even_if_old_focus_is_retained(self):
        root = NS(winfo_viewable=lambda: False, state=lambda: 'withdrawn')
        root.focus_displayof = lambda: NS(winfo_toplevel=lambda: root)
        child = NS(root=root, _chat_only=True, closed=False, closing=False)
        self.assertFalse(Desktop.chat_visible(child))


class TimerOwnershipTests(unittest.TestCase):
    def test_cancel_descendant_timer_through_its_registered_widget(self):
        def tcl_call(*args):
            if args == ('after', 'info'):
                return ('child-timer', 'unrelated-timer')
            if args == ('after', 'info', 'child-timer'):
                return ('child_command', 'timer')
            if args == ('after', 'info', 'unrelated-timer'):
                return ('unrelated_command', 'timer')
            raise AssertionError(args)
        interpreter = NS(call=tcl_call, splitlist=lambda value: value if isinstance(value, tuple) else tuple(value.split()))
        child = NS(_tclCommands=['child_command'], winfo_children=lambda: [], after_cancel=Mock(), tk=interpreter)
        root = NS(_tclCommands=['root_command'], winfo_children=lambda: [child], after_cancel=Mock(), tk=interpreter)
        cancel_view_timers(root)
        child.after_cancel.assert_called_once_with('child-timer')
        root.after_cancel.assert_not_called()


class ChildWorkerTests(unittest.TestCase):
    def test_closing_child_suppresses_late_failure_and_keeps_shared_worker(self):
        app = NS(closed=False, _view_generation=0)
        callbacks = []
        future = Future()
        def submit(coroutine, done, failed):
            coroutine.close(); callbacks.append((done, failed)); return future
        owner = NS(loop=object(), events=object(), submit=submit, stop=Mock())
        child = WindowWorker(app, owner)
        async def operation(): return None
        failure = Mock()
        child.submit(operation(), Mock(), failure)
        child.stop()
        app.closed = True
        callbacks[0][1](RuntimeError('Synthetic late completion'))
        failure.assert_not_called()
        owner.stop.assert_not_called()
        self.assertTrue(future.cancelled())
        self.assertFalse(child.pending)


if __name__ == '__main__':
    unittest.main()
