"""Picker actions derive from cached account/chat facts, never Premium RPCs."""
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from unittest.mock import Mock

from telethon import types as t

from tg_ascii.sticker_picker import (
    document_send_allowed,
    insert_selected_emoji,
    send_selected_sticker,
)


def emoji(free=False, pack=123):
    return NS(id=10, attributes=[t.DocumentAttributeCustomEmoji('😀', t.InputStickerSetID(pack, 456), free=free)])


class PickerCapabilities(unittest.TestCase):
    def setUp(self):
        self.backend = NS(account_profile=NS(user_id=1, premium=False), client=Mock(), send_sticker=Mock())
        self.app = NS(service=NS(backend=self.backend), ui_account='A', active=42,
                      chats=[NS(id=42, kind='user')], busy=False, editor=Mock(), call=Mock())
        self.window = Mock(); self.window.winfo_exists.return_value = True
        self.app.editor.tag_ranges.return_value = ()

    def test_free_emoji_allowed_without_premium_and_paid_one_hidden(self):
        self.assertTrue(document_send_allowed(self.app, 42, emoji(True), True))
        self.assertFalse(document_send_allowed(self.app, 42, emoji(), True))
        self.backend.client.assert_not_called()

    def test_premium_is_cached_and_revocation_takes_effect_immediately(self):
        self.backend.account_profile.premium = True
        self.assertTrue(document_send_allowed(self.app, 42, emoji(), True))
        self.backend.account_profile.premium = False
        self.assertFalse(document_send_allowed(self.app, 42, emoji(), True))
        self.backend.client.assert_not_called()

    def test_saved_messages_allows_paid_emoji_without_premium(self):
        self.app.active = 1; self.app.chats = [NS(id=1, kind='self')]
        self.assertTrue(document_send_allowed(self.app, 1, emoji(), True))

    def test_group_assigned_emoji_pack_exception_is_exact(self):
        channel = t.Channel(5, 'Synthetic', t.ChatPhotoEmpty(), datetime.now(UTC), megagroup=True)
        self.app.chats = [NS(id=-1000000000005, kind='group', entity=channel, member=True)]
        self.app.active = -1000000000005
        self.backend._capability_full = {self.app.active: NS(emojiset=NS(id=123))}
        self.assertTrue(document_send_allowed(self.app, self.app.active, emoji(pack=123), True))
        self.assertFalse(document_send_allowed(self.app, self.app.active, emoji(pack=124), True))

    def test_text_and_sticker_permissions_are_separate(self):
        channel = t.Channel(5, 'Synthetic', t.ChatPhotoEmpty(), datetime.now(UTC), megagroup=True,
                            default_banned_rights=t.ChatBannedRights(None, send_stickers=True))
        self.app.chats = [NS(id=-1000000000005, kind='group', entity=channel, member=True)]
        self.app.active = -1000000000005
        self.assertFalse(document_send_allowed(self.app, self.app.active, object()))
        self.assertTrue(document_send_allowed(self.app, self.app.active, emoji(True), True))
        channel.default_banned_rights = t.ChatBannedRights(None, send_plain=True)
        self.assertTrue(document_send_allowed(self.app, self.app.active, object()))
        self.assertFalse(document_send_allowed(self.app, self.app.active, emoji(True), True))

    def test_unavailable_channel_cannot_insert_or_send(self):
        self.app.chats = [NS(id=42, kind='channel', member=False)]
        insert_selected_emoji(self.app, self.window, 'A', 42, emoji(True))
        send_selected_sticker(self.app, self.window, self.backend, 'A', 42, object())
        self.app.editor.insert_custom.assert_not_called()
        self.backend.send_sticker.assert_not_called()
        self.app.call.assert_not_called()

    def test_paid_emoji_rejected_before_modifying_composer(self):
        self.app.editor.tag_ranges.return_value = ('1.0', '1.2')
        insert_selected_emoji(self.app, self.window, 'A', 42, emoji())
        self.app.editor.delete.assert_not_called()
        self.app.editor.insert_custom.assert_not_called()
        self.window.destroy.assert_not_called()

    def test_reconnected_backend_invalidates_old_picker(self):
        old = self.backend; self.app.service.backend = NS()
        send_selected_sticker(self.app, self.window, old, 'A', 42, object())
        insert_selected_emoji(self.app, self.window, 'A', 42, emoji(True), backend=old)
        old.send_sticker.assert_not_called(); self.app.editor.insert_custom.assert_not_called()


if __name__ == '__main__': unittest.main()
