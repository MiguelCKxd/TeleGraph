"""Capability matrices use cached TL facts only; no account or network access."""
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from telethon import types as t

from tg_ascii.backend import Chat
from tg_ascii.chat_capabilities import (
    account_premium,
    capabilities_for,
    chat_capabilities,
    gift_action_available,
)
from tg_ascii.desktop_advanced import AdvancedDialog, DesktopAdvancedMixin

NOW = datetime(2026, 10, 21, tzinfo=UTC)


def channel(**options):
    return t.Channel(4, 'Synthetic', t.ChatPhotoEmpty(), NOW, **options)


def group(**options):
    return t.Chat(4, 'Synthetic', t.ChatPhotoEmpty(), 2, NOW, 1, **options)


def full_user(**options):
    return t.UserFull(7, None, None, 0, **options)


def message(**options):
    values = {'id': 12, 'outgoing': True, 'media_kind': '', 'date': NOW, 'service': False, 'protected': False, 'read': True}
    values.update(options)
    return NS(**values)


def caps(entity, **options):
    return capabilities_for(entity=entity, now=NOW, **options)


class CapabilityMatrix(unittest.TestCase):
    def test_human_bot_self_poll_and_schedule_matrix(self):
        for entity, poll, schedule, bot in [(t.User(7), False, True, False),
                                           (t.User(7, bot=True), True, False, True),
                                           (t.User(7, is_self=True), True, True, False)]:
            with self.subTest(entity=entity):
                value = caps(entity)
                self.assertTrue(value.allows('send'))
                self.assertEqual(value.allows('poll'), poll)
                self.assertEqual(value.allows('schedule'), schedule)
                self.assertEqual(value.allows('bot_action'), bot)

    def test_premium_is_own_account_fact_not_recipient_flag(self):
        self.assertFalse(caps(t.User(7, premium=True)).allows('checklist'))
        self.assertTrue(caps(t.User(7), premium=True).allows('checklist'))
        self.assertFalse(caps(group()).allows('translate'))
        self.assertTrue(caps(group(), premium=True).allows('translate'))

    def test_readonly_channel_requires_post_rights_to_send(self):
        for rights, expected in [(None, False), (t.ChatAdminRights(edit_messages=True), False),
                                 (t.ChatAdminRights(post_messages=True), True)]:
            value = caps(channel(broadcast=True, admin_rights=rights))
            self.assertTrue(value.readable)
            self.assertEqual(value.allows('poll'), expected)
            self.assertEqual(value.allows('article'), expected)
        self.assertTrue(caps(channel(broadcast=True, creator=True)).writable)

    def test_creator_admin_and_member_default_restrictions(self):
        restrictions = t.ChatBannedRights(None, send_plain=True, send_polls=True, pin_messages=True)
        member = caps(group(default_banned_rights=restrictions))
        self.assertFalse(member.allows('send_text')); self.assertFalse(member.allows('poll'))
        self.assertFalse(member.allows('pin_message')); self.assertTrue(member.allows('send_photos'))
        for entity in (group(creator=True, default_banned_rights=restrictions),
                       group(admin_rights=t.ChatAdminRights(pin_messages=True), default_banned_rights=restrictions)):
            self.assertTrue(caps(entity).allows('poll')); self.assertTrue(caps(entity).allows('pin_message'))

    def test_granular_media_restrictions_do_not_disable_plain_messages(self):
        rights = t.ChatBannedRights(None, send_photos=True, send_gifs=True, send_voices=True)
        value = caps(channel(megagroup=True, banned_rights=rights))
        for action in ('send_photos', 'send_gifs', 'send_voices'): self.assertFalse(value.allows(action))
        for action in ('send_text', 'send_videos', 'send_docs', 'send_stickers', 'poll'): self.assertTrue(value.allows(action))
        coarse = caps(channel(megagroup=True, banned_rights=t.ChatBannedRights(None, send_media=True)))
        self.assertTrue(coarse.allows('send_text')); self.assertFalse(coarse.allows('location'))

    def test_bans_expire_but_zero_is_permanent(self):
        expired = t.ChatBannedRights(NOW - timedelta(seconds=1), send_messages=True)
        forever = t.ChatBannedRights(0, send_messages=True)
        self.assertTrue(caps(channel(megagroup=True, banned_rights=expired)).writable)
        self.assertFalse(caps(channel(megagroup=True, banned_rights=forever)).writable)

    def test_left_kicked_deleted_forbidden_and_unknown_do_not_grant_writes(self):
        for entity in (channel(megagroup=True, left=True), group(left=True), t.User(7, deleted=True),
                       channel(megagroup=True, banned_rights=t.ChatBannedRights(None, view_messages=True)),
                       t.ChatForbidden(4, 'Gone')):
            self.assertFalse(caps(entity).writable)
        self.assertFalse(capabilities_for(Chat(-4, 'Unknown', kind='group', member=True)).writable)
        self.assertTrue(caps(channel(megagroup=True, left=True)).allows('join'))
        self.assertFalse(caps(group(left=True)).allows('join'))
        self.assertTrue(caps(group()).allows('leave'))
        self.assertFalse(caps(group(creator=True)).allows('leave'))

    def test_blocked_premium_required_and_paid_message_recipients(self):
        for full in (full_user(blocked=True), full_user(send_paid_messages_stars=5)):
            value = caps(t.User(7), full=full)
            self.assertTrue(value.readable); self.assertFalse(value.writable)
        self.assertFalse(caps(t.User(7, contact_require_premium=True)).writable)
        self.assertTrue(caps(t.User(7, contact_require_premium=True), premium=True).writable)
        self.assertFalse(caps(channel(megagroup=True, send_paid_messages_stars=4)).writable)

    def test_voice_privacy_reactions_and_translation_full_flags(self):
        value = caps(t.User(7), full=full_user(voice_messages_forbidden=True, translations_disabled=True), premium=True)
        self.assertFalse(value.allows('send_voices')); self.assertFalse(value.allows('send_roundvideos'))
        self.assertTrue(value.allows('send_videos')); self.assertFalse(value.allows('translate'))
        self.assertFalse(caps(group(), full=NS(available_reactions=t.ChatReactionsNone())).allows('react'))

    def test_stars_require_confirmed_channel_support_but_not_write_rights(self):
        entity = channel(broadcast=True)
        self.assertFalse(caps(entity).allows('star_react'))
        self.assertFalse(caps(t.User(7), full=NS(paid_reactions_available=True)).allows('star_react'))
        value = caps(entity, full=NS(paid_reactions_available=True, stargifts_available=True))
        self.assertFalse(value.writable); self.assertTrue(value.allows('star_react')); self.assertTrue(value.allows('gift'))

    def test_gift_availability_uses_cached_recipient_and_catalogue_facts(self):
        value = caps(t.User(7))
        gift = t.StarGift(1, t.DocumentEmpty(1), 100, 80)
        self.assertTrue(value.allows_gift(gift))
        for flag in ('sold_out', 'auction', 'require_premium'):
            setattr(gift, flag, True); self.assertFalse(value.allows_gift(gift)); setattr(gift, flag, False)
        gift.limited_per_user = True; gift.per_user_remains = 0
        self.assertFalse(value.allows_gift(gift))
        blocked = full_user(disallowed_gifts=t.DisallowedGiftsSettings(disallow_premium_gifts=True, disallow_unlimited_stargifts=True))
        self.assertFalse(caps(t.User(7), full=blocked).allows('gift_premium'))
        self.assertFalse(caps(t.User(7), full=blocked).allows_gift(gift))

    def test_received_gift_conversion_window_and_refunds_are_respected(self):
        gift = t.StarGift(1, t.DocumentEmpty(1), 100, 80)
        record = t.SavedStarGift(NOW-timedelta(hours=1), gift, msg_id=12, convert_stars=80, can_upgrade=True)
        self.assertFalse(gift_action_available(record,'convert',now=NOW))
        self.assertTrue(gift_action_available(record,'convert',config={'stargifts_convert_period_max':7200},now=NOW))
        self.assertFalse(gift_action_available(record,'convert',config={'stargifts_convert_period_max':60},now=NOW))
        record.refunded=True
        for action in ('visibility','convert','upgrade','transfer'):
            self.assertFalse(gift_action_available(record,action,now=NOW))

    def test_edit_age_ownership_forwarded_and_service_matrix(self):
        value = caps(t.User(7))
        self.assertTrue(value.allows_message('edit', message(), now=NOW))
        for changed in ({'outgoing': False}, {'service': True}, {'via_bot_id': 2}, {'forwarded': True},
                        {'date': NOW-timedelta(days=3)}, {'date': None}, {'media_kind': 'poll'}):
            self.assertFalse(value.allows_message('edit', message(**changed), now=NOW), changed)
        self.assertTrue(caps(t.User(7, is_self=True)).allows_message('edit', message(date=NOW-timedelta(days=30)), now=NOW))
        self.assertTrue(caps(channel(broadcast=True, admin_rights=t.ChatAdminRights(edit_messages=True))).allows_message('edit', message(outgoing=False), now=NOW))

    def test_delete_pin_and_read_time_matrix(self):
        human = caps(t.User(7), full=full_user(can_pin_message=True))
        self.assertTrue(human.allows_message('delete', message(outgoing=False)))
        self.assertTrue(human.allows_message('pin', message()))
        self.assertTrue(human.allows_message('read_time', message(), now=NOW))
        for changed in ({'outgoing': False}, {'read': False}, {'date': NOW-timedelta(days=8)}):
            self.assertFalse(human.allows_message('read_time', message(**changed), now=NOW))
        self.assertFalse(caps(t.User(7), full=full_user(read_dates_private=True)).allows_message('read_time', message(), now=NOW))
        self.assertFalse(caps(channel(broadcast=True)).allows_message('delete', message()))
        self.assertTrue(caps(channel(broadcast=True, admin_rights=t.ChatAdminRights(delete_messages=True))).allows_message('delete', message(outgoing=False)))

    def test_protected_media_cannot_forward_but_can_reply(self):
        for value, item in [(caps(t.User(7)), message(protected=True)),
                            (caps(group(noforwards=True)), message())]:
            self.assertFalse(value.allows_message('forward', item))
            self.assertTrue(value.allows_message('reply', item))

    def test_poll_closed_quiz_permissions_and_country_are_local(self):
        poll = t.Poll(1, t.TextWithEntities('Q', []), [t.PollAnswer(t.TextWithEntities('A', []), b'a')], hash=0)
        media = t.MessageMediaPoll(poll, t.PollResults(results=[]))
        item = message(media=media, media_kind='poll', outgoing=False)
        value = caps(channel(broadcast=True))
        self.assertTrue(value.allows_message('vote', item))
        self.assertFalse(value.allows_message('close_poll', item))
        poll.countries_iso2 = ['ES']; self.assertFalse(value.allows_message('vote', item))
        self.assertTrue(caps(channel(broadcast=True), config={'phone_country_iso2':'ES'}).allows_message('vote', item))
        poll.countries_iso2 = None; poll.closed = True
        self.assertFalse(value.allows_message('vote', item))

    def test_checklist_creation_premium_does_not_block_allowed_completion(self):
        media = t.MessageMediaToDo(t.TodoList(t.TextWithEntities('L', []), [], others_can_complete=True))
        item = message(outgoing=False, media_kind='checklist', media=media)
        value = caps(t.User(7))
        self.assertFalse(value.allows('checklist'))
        self.assertTrue(value.allows_message('toggle_checklist', item))
        self.assertFalse(value.allows_message('append_checklist', item))


class CachedAdapter(unittest.TestCase):
    def app(self):
        backend = NS(account_profile=NS(premium=True, user_id=3), _capability_entities={7:t.User(7)}, _capability_full={})
        return NS(active=7, ui_account='first', chats=[], service=NS(backend=backend, entries={}))

    def test_cached_entity_skips_dialog_iteration_and_never_calls_client(self):
        app = self.app()
        class NeverIterate:
            def __iter__(self): raise AssertionError('Scanning dialogs in normal hot path')
        app.chats=NeverIterate(); app.service.backend.client=Mock()
        self.assertTrue(chat_capabilities(app).allows('checklist'))
        app.service.backend.client.assert_not_called()

    def test_premium_follows_selected_backend_not_other_account_entry(self):
        app = self.app(); app.service.entries={'first':{'premium':True}, 'second':{'premium':True}}
        app.service.backend.account_profile.premium=False
        self.assertFalse(account_premium(app))
        app.service.backend.account_profile=None; app.service.entries['first']['premium']=False
        self.assertFalse(account_premium(app))

    def test_known_chat_argument_avoids_foreign_account_cache(self):
        app = self.app()
        chat=Chat(-4,'Group',kind='group',entity=group())
        self.assertTrue(chat_capabilities(app,-4,chat=chat).allows('poll'))
        app.service.backend=NS(account_profile=NS(premium=False,user_id=88),_capability_entities={7:t.User(7,deleted=True)})
        self.assertFalse(chat_capabilities(app,7).readable)

    def test_confirmation_rechecks_revoked_permission_before_creating_operation(self):
        app = self.app(); app.busy=False
        dialog=object.__new__(AdvancedDialog)
        dialog.app,dialog.peer,dialog.window,dialog.valid=app,7,Mock(),lambda:True
        factory=Mock();app.call=Mock()
        def confirm(*args,**kwargs):
            app.service.backend._capability_full[7]=full_user(blocked=True)
            return True
        with patch('tg_ascii.desktop_advanced.messagebox.askyesno',side_effect=confirm):
            dialog.mutate(factory,confirm='Confirm?',capability='send_text')
        factory.assert_not_called();app.call.assert_not_called()

    def test_advanced_menu_omits_unavailable_actions(self):
        app=DesktopAdvancedMixin()
        app.active,app.demo,app.ui_account=7,False,'first'
        app.chats=[Chat(7,'Person')]
        app.service=NS(backend=NS(account_profile=NS(premium=False,user_id=3),_capability_entities={7:t.User(7)}))
        app.preferences=NS(values={'advanced_features':dict.fromkeys(('polls','checklists','locations','contacts','articles','stars_gifts'),True)})
        app.root=Mock()
        with patch('tg_ascii.desktop_advanced.popup_menu') as menu:
            app.open_advanced_menu()
        labels={entry[0] for entry in menu.call_args.args[1]}
        self.assertNotIn('Poll / quiz',labels);self.assertNotIn('Checklist',labels)
        self.assertIn('Share location',labels);self.assertIn('Article',labels)


if __name__=='__main__':unittest.main()
