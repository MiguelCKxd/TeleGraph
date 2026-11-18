from datetime import UTC, datetime
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock
from telethon import types as t
from tg_ascii.capability_cache import remember, consume_update
from tg_ascii.chat_capabilities import chat_capabilities
from tg_ascii.backend import Chat


class CapabilityUpdates(unittest.TestCase):
    def group(self):
        return t.Chat(1,'Synthetic',t.ChatPhotoEmpty(),2,datetime.now(UTC),1)

    def test_same_rights_do_not_emit_redundant_ui_events(self):
        backend=NS(on_change=Mock())
        remember(backend,self.group())
        remember(backend,self.group())
        self.assertEqual(backend.on_change.call_count,1)

    def test_delta_changes_cached_rights_without_rpc_and_keeps_original(self):
        entity=self.group();backend=NS(on_change=Mock())
        remember(backend,entity,notify=False)
        app=NS(active=-1,chats=[Chat(-1,'Synthetic',kind='group',entity=entity)],service=NS(backend=backend))
        self.assertTrue(chat_capabilities(app).can_poll)
        consume_update(backend,t.UpdateChatDefaultBannedRights(t.PeerChat(1),t.ChatBannedRights(None,send_polls=True),1))
        self.assertFalse(chat_capabilities(app).can_poll)
        self.assertIsNone(entity.default_banned_rights)
        backend.on_change.assert_called_once_with('capabilities',-1)

    def test_minimal_update_does_not_erase_known_channel_admin_rights(self):
        backend=NS(on_change=Mock())
        entity=t.Channel(1,'Synthetic',t.ChatPhotoEmpty(),datetime.now(UTC),broadcast=True,admin_rights=t.ChatAdminRights(post_messages=True))
        remember(backend,entity)
        minimal=t.Channel(1,'Synthetic',t.ChatPhotoEmpty(),datetime.now(UTC),broadcast=True,min=True)
        remember(backend,minimal)
        self.assertIs(backend._capability_entities[-1000000000001],entity)
        self.assertEqual(backend.on_change.call_count,1)

    def test_cache_bounded_and_separate_for_each_account(self):
        first,second=NS(on_change=Mock()),NS(on_change=Mock())
        for ident in range(2100):remember(first,t.User(ident),notify=False)
        remember(second,t.User(1,premium=True))
        self.assertEqual(len(first._capability_entities),2048)
        self.assertEqual(len(second._capability_entities),1)
        self.assertNotIn(1,first._capability_entities)

    def test_block_update_applies_before_full_profile_was_loaded(self):
        backend=NS(on_change=Mock());remember(backend,t.User(5),notify=False)
        app=NS(active=5,service=NS(backend=backend))
        self.assertTrue(chat_capabilities(app).can_send)
        consume_update(backend,t.UpdatePeerBlocked(t.PeerUser(5),blocked=True))
        self.assertFalse(chat_capabilities(app).can_send)
        consume_update(backend,t.UpdatePeerBlocked(t.PeerUser(5),blocked=False))
        self.assertTrue(chat_capabilities(app).can_send)
