"""1.5.2: customizable menus switch, Close chat, dragged-away chat list."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from tg_ascii import custom_menus, menu_style, pane_memory


class CustomMenusOffTests(unittest.TestCase):
    def tearDown(self):
        menu_style.configure({})

    def test_turning_the_feature_off_goes_back_to_the_lightest_menus(self):
        with tempfile.TemporaryDirectory() as folder:
            values = {'advanced_features': {'custom_menus': True}, 'menu_style': 'custom',
                      'menu_custom': {kind: 'app' for kind, _ in menu_style.KINDS}}
            menu_style.configure(values, folder)
            for kind, _ in menu_style.KINDS:
                path = custom_menus.ensure(kind)
                (path / 'style.json').write_text('{"title": "mine"}', encoding='utf-8')
                (path / 'menu.py').write_text('def show(*args):\n    return True\n', encoding='utf-8')
                self.assertTrue(custom_menus.active(kind))
                self.assertEqual(menu_style.choice(kind), 'app')
            # Same saved choices and files, feature switched off.
            menu_style.configure({**values, 'advanced_features': {'custom_menus': False}}, folder)
            for kind, _ in menu_style.KINDS:
                self.assertEqual(menu_style.choice(kind), menu_style.LIGHTEST[kind], kind)
                self.assertFalse(custom_menus.active(kind))
                self.assertIsNone(custom_menus.replacement(kind))
                self.assertEqual(custom_menus.style(kind), {})
                self.assertFalse(custom_menus.handled(kind, None, None, None))
                self.assertEqual(custom_menus.run(kind, lambda: 'builtin'), 'builtin')
            # The user's files are kept for when it is switched on again.
            self.assertTrue((custom_menus.folder('message_box') / 'menu.py').is_file())


def panes_model(width, sash, sidebar_first=True):
    sidebar, conversation = 'sidebar', 'conversation'
    panes = Mock()
    panes.panes.return_value = [sidebar, conversation] if sidebar_first else [conversation, sidebar]
    panes.winfo_width.return_value = width
    panes.sashpos.return_value = sash
    panes.winfo_exists.return_value = True
    app = SimpleNamespace(demo=True, chat_sidebar=sidebar, chat_panes=panes, adapt_chat_layout=Mock(),
                          compact_conversation=False)
    return app, panes


class HiddenChatListTests(unittest.TestCase):
    def test_dragging_the_list_away_switches_to_one_pane_with_the_button(self):
        app, panes = panes_model(1000, 10)
        pane_memory.remember(app, panes)
        self.assertEqual(pane_memory.hidden_pane(app), 'list')
        self.assertTrue(app.compact_conversation)
        app.adapt_chat_layout.assert_called_once()

    def test_right_to_left_and_conversation_dragged_away(self):
        app, panes = panes_model(1000, 990, sidebar_first=False)
        pane_memory.remember(app, panes)
        self.assertEqual(pane_memory.hidden_pane(app), 'list')
        app, panes = panes_model(1000, 990)
        pane_memory.remember(app, panes)
        self.assertEqual(pane_memory.hidden_pane(app), 'conversation')
        self.assertFalse(app.compact_conversation)

    def test_normal_drag_only_stores_the_share(self):
        app, panes = panes_model(1000, 300)
        pane_memory.remember(app, panes)
        self.assertIsNone(pane_memory.hidden_pane(app))
        self.assertEqual(pane_memory.stored(app), 0.3)
        app.adapt_chat_layout.assert_not_called()

    def test_reset_forgets_everything_and_relays_out(self):
        with tempfile.TemporaryDirectory() as folder:
            app, panes = panes_model(1000, 5)
            app.demo = False
            app.service = SimpleNamespace(root=Path(folder))
            pane_memory.remember(app, panes)
            self.assertTrue((Path(folder) / 'chat-layout.json').is_file())
            app.adapt_chat_layout.reset_mock()
            pane_memory.reset(app)
            self.assertFalse((Path(folder) / 'chat-layout.json').exists())
            self.assertEqual((pane_memory.stored(app), pane_memory.hidden_pane(app)), (0.0, None))
            self.assertEqual(panes.forget.call_count, 2)
            app.adapt_chat_layout.assert_called_once()
            # A fresh start reads nothing back.
            app._chat_list_share = None
            self.assertEqual((pane_memory.stored(app), pane_memory.hidden_pane(app)), (0.0, None))


class CloseChatTests(unittest.TestCase):
    def test_close_chat_keeps_the_draft_and_shows_choose_a_chat(self):
        from tg_ascii.desktop import Desktop
        editor = Mock(); editor.get.return_value = 'half written'
        chat_list = Mock(); chat_list.exists.return_value = True
        app = SimpleNamespace(active=41, busy=False, messages=[1, 2], drafts={}, attachment=None,
                              editor=editor, chat_list=chat_list, ui_account='a', title=Mock(),
                              save_custom_draft=Mock(), update_attachment=Mock(), cancel_reply=Mock(),
                              render_messages=Mock(), adapt_chat_layout=Mock(), compact_conversation=True)
        Desktop.close_active_chat(app)
        self.assertIsNone(app.active)
        self.assertEqual(app.messages, [])
        self.assertEqual(app.drafts[41], ('half written', None))
        self.assertEqual(app._history_cache[('a', 41)], [1, 2])
        chat_list.selection_remove.assert_called_once_with('41')
        self.assertFalse(app.compact_conversation)
        app.render_messages.assert_called_once_with(False)

    def test_in_a_chat_window_it_closes_the_window(self):
        from tg_ascii.desktop import Desktop
        app = SimpleNamespace(_chat_only=True, close=Mock())
        Desktop.close_active_chat(app)
        app.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
