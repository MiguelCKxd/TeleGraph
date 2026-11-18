"""Telegram link parsing and explicit navigation; no network or accounts."""
import asyncio
import itertools
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from telethon import types as t

from tg_ascii.link_navigation import open_target
from tg_ascii.links import browser_url, detected_links, link_target, message_links


class Links(unittest.TestCase):
    def test_peer_and_message_links(self):
        for address in ('https://t.me/example/42', 'tg://resolve?domain=example&post=42',
                        'https://example.t.me/42', 'https://t.me/example/12/42'):
            with self.subTest(address=address):
                value = link_target(address)
                self.assertEqual((value.kind, value.peer, value.message_id), ('peer', 'example', 42))
        self.assertEqual(link_target('https://t.me/c/123/22/42').peer, -1000000000123)
        self.assertEqual(link_target('tg://privatepost?channel=123&post=42').message_id, 42)
        self.assertTrue(link_target('@example').profile)
        self.assertEqual(link_target('tg://user?id=77').peer, 77)
        self.assertEqual(link_target('https://t.me/example/42?comment=59').comment_id, 59)
        self.assertEqual(link_target('tg:resolve?phone=12345678').peer, '+12345678')

    def test_invites_packs_and_folders_never_mutate_in_parser(self):
        for address in ('https://t.me/+Token_12', 'https://t.me/joinchat/Token_12', 'tg://join?invite=Token_12'):
            self.assertEqual(link_target(address).kind, 'invite')
        self.assertEqual(link_target('tg://addlist?slug=Token').kind, 'folder')
        self.assertEqual(link_target('https://t.me/addemoji/MyEmoji').value, 'MyEmoji')
        self.assertEqual(link_target('tg://addstickers?set=MyStickers').kind, 'pack')
        self.assertEqual(link_target('https://t.me/+12345678').peer, '+12345678')

    def test_browser_commands_are_not_executed(self):
        for address in ('https://t.me/example?start=payload', 'tg://resolve?domain=example&start=payload',
                        'https://t.me/nft/Gift-12', 'https://t.me/share/url?url=https%3A%2F%2Fexample.org',
                        'https://t.me/proxy?server=example.org', 'https://telegra.ph/Article'):
            self.assertEqual(link_target(address).kind, 'browser')
        for address in ('tg://proxy?server=example.org', 'tg://login?token=secret', 'javascript:alert(1)',
                        'file:///tmp/data', 'https://user:password@t.me/example',
                        'tg://user:password@resolve?domain=example#fragment',
                        'tg://resolve/extra?domain=example', 'tg://user?id=-1',
                        'tg://privatepost?channel=123&post=0', 'https://t.me/addemoji/bad%2Fvalue',
                        'https://t.me/example/42?comment=wrong', 'https://t.me/example\n/42'):
            with self.subTest(address=address), self.assertRaises(ValueError): link_target(address)

    def test_entities_use_utf16_and_hidden_target_wins(self):
        text = '😀 example.com @Alice #tema'
        entities = [t.MessageEntityTextUrl(3, 11, 'https://example.org/actual'),
                    t.MessageEntityMentionName(15, 6, 99)]
        result = message_links(text, entities)
        self.assertEqual(result, [(2, 13, 'https://example.org/actual'),
                                  (14, 20, 'tg://user?id=99'), (21, 26, '#tema')])
        self.assertEqual(message_links('😀', [t.MessageEntityTextUrl(1, 1, 'https://example.org')]), [])

    def test_nonoverlapping_entities_fallback_and_punctuation(self):
        text = '(tg://resolve?domain=example&post=42), https://example.org/#tag @someone #tema $USD'
        result = message_links(text)
        self.assertEqual(len(result), 5)
        self.assertEqual(result[0][2], 'tg://resolve?domain=example&post=42')
        self.assertEqual(result[1][2], 'https://example.org/#tag')
        self.assertEqual([item[2] for item in result[2:]], ['@someone', '#tema', '$USD'])
        self.assertTrue(all(left[1] <= right[0] for left, right in itertools.pairwise(result)))
        self.assertEqual(message_links('test@example.com'), [])

    def test_dense_entities_remain_disjoint(self):
        text = ' '.join('#tag' + str(index) for index in range(1500))
        self.assertEqual(len(message_links(text)), 1500)
        self.assertEqual(list(detected_links('example.com test@example.com')), [(0, 11, 'https://example.com')])
        self.assertEqual(browser_url('t.me/example'), 'https://t.me/example')


class Navigation(unittest.TestCase):
    def app(self, enabled=True):
        backend = NS(resolve_chat=AsyncMock(return_value=NS(id=77)))
        return NS(preferences=NS(values={'advanced_features': {'links': enabled}}), demo=False, busy=False,
                  service=NS(backend=backend), active=11, ui_account='A', open_resolved=Mock(),
                  jump_message=Mock(), show_contact_profile=Mock(), invite_dialog=Mock(),
                  join_folder_dialog=Mock(), show_document_pack=Mock())

    def test_disabled_links_do_no_work(self):
        app = self.app(False)
        self.assertFalse(open_target(app, link_target('@example')))
        app.service.backend.resolve_chat.assert_not_called()

    def test_invite_folder_and_pack_open_review_only(self):
        app = self.app()
        self.assertTrue(open_target(app, link_target('https://t.me/+Token')))
        app.invite_dialog.assert_called_once_with('Token')
        self.assertTrue(open_target(app, link_target('https://t.me/addlist/Token')))
        app.join_folder_dialog.assert_called_once_with('https://t.me/addlist/Token')
        self.assertTrue(open_target(app, link_target('https://t.me/addemoji/MyEmoji')))
        self.assertEqual(app.show_document_pack.call_args.args[0].attributes[0].stickerset.short_name, 'MyEmoji')
        app.service.backend.resolve_chat.assert_not_called()

    def test_profile_and_message_navigation_and_stale_account_guard(self):
        app = self.app()
        def execute(coroutine, callback, status): callback(asyncio.run(coroutine))
        app.call = execute
        open_target(app, link_target('@example'))
        app.show_contact_profile.assert_called_once_with(77)
        open_target(app, link_target('https://t.me/example/42'))
        app.jump_message.assert_called_once_with(42, 77)
        def switch(coroutine, callback, status):
            result = asyncio.run(coroutine)
            app.ui_account = 'B'
            callback(result)
        app.call = switch
        open_target(app, link_target('https://t.me/example/43'))
        self.assertEqual(app.jump_message.call_count, 1)

    def test_explicit_browser_only_purchase_remains_available_with_feature_off(self):
        from tg_ascii.desktop_actions import DesktopActions
        app = self.app(False)
        app.root = None; app.show_error = Mock()
        with patch('tg_ascii.app_dialogs.messagebox.askyesno', return_value=True), patch('webbrowser.open', return_value=True) as opened:
            DesktopActions.open_link(app, 'https://t.me/PremiumBot', browser_only=True)
            opened.assert_called_once_with('https://t.me/PremiumBot', new=2)
        app.show_error.assert_not_called()


if __name__ == '__main__': unittest.main()
