"""Telegram request/ownership contracts; no account, payment or external IO."""
import unittest
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from telethon import functions as f
from telethon import types as t
from telethon.extensions.binaryreader import BinaryReader

from tg_ascii.advanced_messaging import (
    AdvancedMessagingMixin,
    advanced_media_summary,
    config_values,
    coordinates,
    poll_media,
    todo_fingerprint,
    todo_media,
)
from tg_ascii.rich_articles import (
    article_fields,
    article_input,
    article_media,
    editable_article,
    replace_article_field,
    rich_article_text,
)


def roundtrip(value):
    with BinaryReader(bytes(value)) as reader:
        return reader.tgread_object()


def message(media=None, *, outgoing=True, rich=None):
    return t.Message(12, t.PeerUser(77), date=datetime.now(UTC), out=outgoing,
                     message='', media=media, rich_message=rich)


def poll(**options):
    media = poll_media('Question 😀', ['First', 'Second'], **options)
    media.poll.id = 999
    media.poll.answers = [t.PollAnswer(answer.text, bytes([index])) for index, answer in enumerate(media.poll.answers)]
    return t.MessageMediaPoll(media.poll, t.PollResults(results=[], total_voters=0))


def checklist(**options):
    return t.MessageMediaToDo(todo_media('Tasks', [(1, 'First'), (2, 'Second')], **options).todo, completions=[])


class Backend(AdvancedMessagingMixin):
    def __init__(self, current=None):
        self.current = current
        self.client = AsyncMock(return_value=t.Updates([], [], [], datetime.now(UTC), 1))
        self.client.get_input_entity = AsyncMock(return_value=t.InputPeerUser(77, 123))
        self.client.get_entity = AsyncMock(return_value=t.User(77, first_name='Synthetic recipient', access_hash=123))
        self.checked_message = AsyncMock(side_effect=lambda peer, ident: self.current)
        self.resolve_missing_senders = AsyncMock()
        self.message = lambda value: value
        self.premium_enabled = AsyncMock(return_value=True)
        self.account_profile = NS(user_id=77)
        self.app_config = AsyncMock(return_value=t.help.AppConfig(0, t.JsonObject([])))


class Builders(unittest.TestCase):
    def test_poll_current_layer_serializes_correct_indices_and_entities(self):
        text = t.TextWithEntities('😀 vote', [t.MessageEntityBold(0, 2)])
        value = roundtrip(poll_media(text, [text, 'No'], quiz=True, correct=[0], solution='Explain',
                                    anonymous=False, multiple=True, shuffle=True, revoting=False,
                                    hidden_results=True, subscribers_only=True, countries=['es', 'ES']))
        self.assertEqual(value.correct_answers, [0])
        self.assertEqual(value.poll.answers[0].text.entities[0].length, 2)
        self.assertEqual(value.poll.countries_iso2, ['ES'])
        self.assertTrue(value.poll.public_voters)
        self.assertTrue(value.poll.revoting_disabled)
        self.assertTrue(value.poll.shuffle_answers)
        self.assertTrue(value.poll.hide_results_until_close)
        self.assertTrue(value.poll.subscribers_only)
        self.assertTrue(all(isinstance(answer, t.InputPollAnswer) for answer in value.poll.answers))

    def test_poll_invalid_settings_never_build_a_request(self):
        for options in ({'quiz': True}, {'correct': [0]}, {'quiz': True, 'correct': [8]},
                        {'quiz': True, 'correct': [0], 'open_answers': True}, {'close_period': 0},
                        {'countries': ['Spain']}, {'solution': 'Non quiz'},
                        {'close_period': 10, 'close_date': datetime.now(UTC)}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                poll_media('Q', ['A', 'B'], **options)
        with self.assertRaises(ValueError): poll_media('Q', ['A'])
        with self.assertRaises(ValueError): poll_media('Q', ['A'] * 13)
        with self.assertRaises(ValueError): poll_media('Q', ['A', 'B'], quiz=True, correct=[0], solution='A\nB\nC\nD')

    def test_config_limits_are_obeyed_without_hardcoded_twelve_cap(self):
        self.assertEqual(len(poll_media('Q', ['A'] * 15, config={'poll_answers_max': 15}).poll.answers), 15)
        with self.assertRaises(ValueError): todo_media('List', [(1, 'A'), (2, 'B')], config={'todo_items_max': 1})
        self.assertEqual(config_values(t.help.AppConfig(0, t.JsonObject([t.JsonObjectValue('x', t.JsonNumber(12))]))), {'x': 12})

    def test_todo_ids_and_entities_are_preserved(self):
        text = t.TextWithEntities('One', [t.MessageEntityBold(0, 3)])
        value = roundtrip(todo_media('List', [(32, text), (88, 'Two')], others_can_append=True))
        self.assertEqual([task.id for task in value.todo.list], [32, 88])
        self.assertEqual(value.todo.list[0].title.entities[0].length, 3)
        for items in ([], [(0, 'A')], [(1, 'A'), (1, 'B')], [(True, 'A')]):
            with self.subTest(items=items), self.assertRaises(ValueError): todo_media('List', items)

    def test_coordinates_finite_bounds_and_no_permission_side_effects(self):
        value = roundtrip(coordinates('-90', 180, 10))
        self.assertEqual((value.lat, value.long, value.accuracy_radius), (-90, 180, 10))
        for lat, lon in [('nan', 1), (1, float('inf')), (91, 1), (1, -181), ('abc', 1)]:
            with self.assertRaises(ValueError): coordinates(lat, lon)

    def test_received_structured_media_always_has_readable_fallback(self):
        media = poll()
        media.results = t.PollResults(results=[t.PollAnswerVoters(media.poll.answers[0].option, chosen=True, voters=3)], total_voters=3)
        kind, text = advanced_media_summary(media)
        self.assertEqual(kind, 'poll'); self.assertIn('First', text); self.assertIn('3', text)
        kind, text = advanced_media_summary(checklist())
        self.assertEqual(kind, 'checklist'); self.assertIn('☐ First', text)
        kind, text = advanced_media_summary(t.MessageMediaContact('12345', 'First', 'Last', '', 77))
        self.assertEqual(kind, 'contact'); self.assertIn('First Last', text)
        kind, text = advanced_media_summary(t.MessageMediaGeo(t.GeoPoint(1, 2, 0)))
        self.assertEqual(kind, 'location'); self.assertIn('2.000000', text)
        self.assertEqual(advanced_media_summary(None), ('', ''))


class MessageOperations(unittest.IsolatedAsyncioTestCase):
    async def test_send_preserves_peer_reply_and_unique_request_id(self):
        backend = Backend()
        backend.client.get_input_entity.return_value = t.InputPeerChat(77)
        def response(request):
            sent = message(poll())
            sent.peer_id = t.PeerChat(77)
            return t.Updates([t.UpdateMessageID(sent.id, request.random_id), t.UpdateNewMessage(sent, 1, 1)], [], [], datetime.now(UTC), 1)
        backend.client.side_effect = response
        sent = await backend.send_poll(77, 'Q', ['A', 'B'], reply_to=22)
        request = backend.client.call_args.args[0]
        self.assertIsInstance(request, f.messages.SendMediaRequest)
        self.assertEqual(request.reply_to.reply_to_msg_id, 22)
        self.assertIsInstance(request.random_id, int)
        self.assertEqual(sent.id, 12)
        self.assertIsNone(request.allow_paid_stars)

    async def test_ack_without_message_does_not_retry(self):
        backend = Backend()
        backend.client.get_input_entity.return_value = t.InputPeerChat(77)
        self.assertIsNone(await backend.send_poll(77, 'Q', ['A', 'B']))
        self.assertEqual(backend.client.await_count, 1)

    async def test_human_private_chat_rejects_poll_before_send_or_config(self):
        backend = Backend()
        with self.assertRaisesRegex(ValueError, 'Choose a group or channel'):
            await backend.send_poll(77, 'Q', ['A', 'B'])
        backend.client.assert_not_awaited()
        backend.app_config.assert_not_awaited()

    async def test_bot_private_chat_preserves_request_poll_reply(self):
        backend = Backend()
        backend.client.get_entity.return_value = t.User(77, bot=True)
        await backend.send_poll(77, 'Q', ['A', 'B'], reply_to=22)
        request = backend.client.call_args.args[0]
        self.assertIsInstance(request, f.messages.SendMediaRequest)
        self.assertEqual(request.reply_to.reply_to_msg_id, 22)

    async def test_saved_messages_inputpeer_self_does_not_throw_after_sending(self):
        backend = Backend()
        backend.client.get_input_entity.return_value = t.InputPeerSelf()
        backend.client.side_effect = lambda request: t.Updates([t.UpdateNewMessage(message(poll()), 1, 1)], [], [], datetime.now(UTC), 1)
        self.assertEqual((await backend.send_poll('me', 'Q', ['A', 'B'])).id, 12)

    async def test_vote_and_retract_use_original_option_bytes(self):
        backend = Backend(message(poll()))
        selected = backend.current.media.poll.answers[1].option
        await backend.vote_poll(77, 12, [selected, selected])
        self.assertEqual(backend.client.call_args.args[0].options, [selected])
        await backend.vote_poll(77, 12, [])
        self.assertEqual(backend.client.call_args.args[0].options, [])

    async def test_quiz_revoting_and_closed_poll_reject_before_rpc(self):
        for mode in ('quiz', 'closed', 'revoting'):
            media = poll(quiz=mode == 'quiz', correct=[0] if mode == 'quiz' else [])
            media.poll.closed = mode == 'closed'
            media.poll.revoting_disabled = mode == 'revoting'
            media.results.results = [t.PollAnswerVoters(media.poll.answers[0].option, chosen=True)]
            backend = Backend(message(media))
            with self.subTest(mode=mode), self.assertRaises(ValueError): await backend.vote_poll(77, 12, [])
            backend.client.assert_not_awaited()

    async def test_country_restriction_is_checked_before_vote(self):
        backend = Backend(message(poll(countries=['ES'])))
        with self.assertRaises(ValueError): await backend.vote_poll(77, 12, [backend.current.media.poll.answers[0].option])
        backend.client.assert_not_awaited()

    async def test_close_preserves_poll_and_does_not_modify_snapshot(self):
        backend = Backend(message(poll(anonymous=False, shuffle=True)))
        old = bytes(backend.current.media.poll)
        await backend.close_poll(77, 12)
        sent = backend.client.call_args.args[0].media.poll
        self.assertTrue(sent.closed)
        self.assertTrue(sent.public_voters)
        self.assertTrue(sent.shuffle_answers)
        self.assertEqual(sent.id, 999)
        self.assertEqual(bytes(backend.current.media.poll), old)

    async def test_anonymous_poll_does_not_fetch_voter_identities(self):
        backend = Backend(message(poll()))
        with self.assertRaises(ValueError): await backend.poll_voters(77, 12)
        backend.client.assert_not_awaited()

    async def test_open_answer_has_current_api_constructor(self):
        backend = Backend(message(poll(open_answers=True)))
        await backend.append_poll_answer(77, 12, 'Third')
        request = roundtrip(backend.client.call_args.args[0])
        self.assertIsInstance(request.answer, t.InputPollAnswer)
        self.assertEqual(request.answer.text.text, 'Third')

    async def test_checklist_create_requires_premium_once_and_preserves_permissions(self):
        backend = Backend()
        backend.premium_enabled.return_value = False
        with self.assertRaises(ValueError): await backend.send_checklist(77, 'A', [(1, 'B')])
        backend.client.assert_not_awaited()
        backend.premium_enabled.return_value = True
        await backend.send_checklist(77, 'A', [(1, 'B')], others_can_complete=True)
        self.assertTrue(backend.client.call_args.args[0].media.todo.others_can_complete)

    async def test_completion_uses_ids_and_checks_permissions(self):
        backend = Backend(message(checklist(), outgoing=False))
        with self.assertRaises(ValueError): await backend.toggle_checklist(77, 12, 1, True)
        backend.current.media.todo.others_can_complete = True
        await backend.toggle_checklist(77, 12, 2, True)
        request = backend.client.call_args.args[0]
        self.assertEqual((request.completed, request.incompleted), ([2], []))

    async def test_checklist_conflict_and_completions_are_independent(self):
        backend = Backend(message(checklist()))
        snapshot = todo_fingerprint(backend.current.media.todo)
        backend.current.media.completions = [t.TodoCompletion(1, t.PeerUser(77), 1)]
        await backend.edit_checklist(77, 12, 'New', [(1, 'First')], snapshot)
        self.assertEqual(backend.client.call_args.args[0].media.todo.list[0].id, 1)
        backend.current.media.todo.title.text = 'Changed elsewhere'
        backend.client.reset_mock()
        with self.assertRaises(ValueError): await backend.edit_checklist(77, 12, 'New', [(1, 'First')], snapshot)
        backend.client.assert_not_awaited()

    async def test_append_tasks_keeps_existing_ids_and_uses_new_ids(self):
        backend = Backend(message(checklist(others_can_append=True), outgoing=False))
        await backend.append_checklist(77, 12, ['Third', 'Fourth'])
        request = backend.client.call_args.args[0]
        ids = {item.id for item in request.list}
        self.assertEqual(len(ids), 2)
        self.assertFalse(ids & {1, 2})
        self.assertEqual([item.id for item in backend.current.media.todo.list], [1, 2])

    async def test_locations_stop_without_hiding_original_coordinates_in_new_message(self):
        backend = Backend(message(t.MessageMediaGeoLive(t.GeoPoint(2, 1, 0), 900)))
        await backend.edit_location(77, 12, stop=True)
        request = backend.client.call_args.args[0]
        self.assertIsInstance(request, f.messages.EditMessageRequest)
        self.assertTrue(request.media.stopped)
        self.assertIsInstance(request.media.geo_point, t.InputGeoPointEmpty)

    async def test_live_location_owned_guard_and_finite_validation(self):
        backend = Backend(message(t.MessageMediaGeoLive(t.GeoPoint(2, 1, 0), 900), outgoing=False))
        with self.assertRaises(ValueError): await backend.edit_location(77, 12, 1, 2)
        with self.assertRaises(ValueError): await backend.send_location(77, 1, 2, period=-1)
        backend.client.assert_not_awaited()

    async def test_contact_card_keeps_vcard_and_explicit_number(self):
        backend = Backend()
        await backend.send_contact_card(77, 'Example', 'Contact', '+34123456789', vcard='BEGIN:VCARD\nEND:VCARD')
        request = roundtrip(backend.client.call_args.args[0])
        self.assertEqual(request.media.phone_number, '+34123456789')
        self.assertIn('BEGIN:VCARD', request.media.vcard)


class PaymentContracts(unittest.IsolatedAsyncioTestCase):
    async def test_prepare_invoice_reads_price_and_cannot_charge(self):
        backend = Backend()
        bill = t.Invoice('XTR', [t.LabeledPrice('Gift', 75)], test=False)
        backend.client.return_value = t.payments.PaymentFormStarGift(123, bill)
        quote = await backend._prepare_stars_invoice(t.InputInvoiceStarGift(t.InputPeerSelf(), 7), 'Gift', 'Example')
        self.assertEqual((quote.amount, quote.recipient), (75, 'Example'))
        self.assertIsInstance(backend.client.call_args.args[0], f.payments.GetPaymentFormRequest)
        self.assertEqual(backend.client.await_count, 1)

    async def test_commit_requires_exact_price_and_consumes_token_once(self):
        backend = Backend()
        quote = backend._remember_payment('Gift', 75, 'Example', ('invoice', 123, t.InputInvoiceStarGift(t.InputPeerSelf(), 7)))
        with self.assertRaises(ValueError): await backend.commit_stars_payment(quote.token, confirmed_amount=74)
        backend.client.assert_not_awaited()
        await backend.commit_stars_payment(quote.token, confirmed_amount=75)
        self.assertIsInstance(backend.client.call_args.args[0], f.payments.SendStarsFormRequest)
        with self.assertRaises(ValueError): await backend.commit_stars_payment(quote.token, confirmed_amount=75)
        self.assertEqual(backend.client.await_count, 1)

    async def test_uncertain_charge_is_never_retried(self):
        backend = Backend()
        backend.client.side_effect = TimeoutError('lost reply')
        quote = backend._remember_payment('Gift', 75, 'Example', ('invoice', 123, t.InputInvoiceStarGift(t.InputPeerSelf(), 7)))
        with self.assertRaises(TimeoutError): await backend.commit_stars_payment(quote.token, confirmed_amount=75)
        with self.assertRaises(ValueError): await backend.commit_stars_payment(quote.token, confirmed_amount=75)
        self.assertEqual(backend.client.await_count, 1)

    async def test_expiry_and_account_scoped_quotes(self):
        backend, other = Backend(), Backend()
        with patch('tg_ascii.advanced_messaging.time.monotonic', return_value=0):
            quote = backend._remember_payment('Gift', 1, 'Example', ('invoice', 1, object()))
        with self.assertRaises(ValueError): await other.commit_stars_payment(quote.token, confirmed_amount=1)
        with patch('tg_ascii.advanced_messaging.time.monotonic', return_value=121), self.assertRaises(ValueError):
            await backend.commit_stars_payment(quote.token, confirmed_amount=1)
        backend.client.assert_not_awaited(); other.client.assert_not_awaited()

    async def test_paid_reaction_timestamp_and_privacy(self):
        backend = Backend()
        quote = backend._remember_payment('Reaction', 2, 'Example',
            ('reaction', t.InputPeerChannel(77, 123), 12, 2, t.PaidReactionPrivacyAnonymous()))
        with patch('tg_ascii.advanced_messaging.time.time', return_value=1_700_000_000):
            await backend.commit_stars_payment(quote.token, confirmed_amount=2)
        request = roundtrip(backend.client.call_args.args[0])
        self.assertEqual(request.random_id >> 32, 1_700_000_000)
        self.assertEqual(request.count, 2)
        self.assertIsInstance(request.private, t.PaidReactionPrivacyAnonymous)

    async def test_quotes_are_bounded_and_cancel_discards(self):
        backend = Backend()
        quotes = [backend._remember_payment('X', 1, 'A', ('invoice', 1, object())) for _ in range(20)]
        self.assertEqual(len(backend._advanced_payment_quotes), 8)
        backend.discard_stars_quote(quotes[-1].token)
        self.assertEqual(len(backend._advanced_payment_quotes), 7)

    async def test_nonstars_and_recurring_forms_cannot_be_charged(self):
        backend = Backend()
        for currency, recurring in [('USD', False), ('XTR', True)]:
            bill = t.Invoice(currency, [t.LabeledPrice('Gift', 75)], recurring=recurring)
            backend.client.return_value = t.payments.PaymentFormStarGift(123, bill)
            with self.assertRaises(ValueError): await backend._prepare_stars_invoice(t.InputInvoiceStarGift(t.InputPeerSelf(), 7), 'Gift', 'User')
        self.assertFalse(getattr(backend, '_advanced_payment_quotes', None))

    async def test_saved_gift_reference_distinguishes_channel_and_user(self):
        backend = Backend()
        record = NS(msg_id=41, saved_id=82)
        self.assertEqual((await backend.saved_gift_reference(record)).msg_id, 41)
        backend.client.get_input_entity.return_value = t.InputPeerChannel(9, 1)
        self.assertEqual((await backend.saved_gift_reference(record, -1000000000009)).saved_id, 82)

    async def test_profile_gifts_are_public_by_default_and_paginated(self):
        backend = Backend()
        await backend.profile_gifts(77, 'next')
        request = backend.client.call_args.args[0]
        self.assertTrue(request.exclude_unsaved)
        self.assertEqual((request.offset, request.limit), ('next', 30))

    async def test_free_transfer_and_prepaid_upgrade_never_create_payment_forms(self):
        backend = Backend()
        record = NS(msg_id=41, saved_id=None, transfer_stars=None, upgrade_stars=None, can_upgrade=True)
        await backend.transfer_free_gift(record, 88)
        self.assertIsInstance(backend.client.call_args.args[0], f.payments.TransferStarGiftRequest)
        await backend.upgrade_prepaid_gift(record, keep_original=False)
        self.assertIsInstance(backend.client.call_args.args[0], f.payments.UpgradeStarGiftRequest)
        self.assertFalse(backend.client.call_args.args[0].keep_original_details)
        backend.client.reset_mock(); record.transfer_stars = 25; record.upgrade_stars = 50
        with self.assertRaises(ValueError): await backend.transfer_free_gift(record, 88)
        with self.assertRaises(ValueError): await backend.upgrade_prepaid_gift(record)
        backend.client.assert_not_awaited()

    async def test_resale_uses_paginated_stars_only_catalogue_and_confirmable_invoice(self):
        backend = Backend()
        await backend.resale_gifts(7, 'page')
        request = roundtrip(backend.client.call_args.args[0])
        self.assertEqual((request.gift_id, request.offset, request.limit), (7, 'page', 30))
        self.assertTrue(request.stars_only)
        backend.client.return_value = t.payments.PaymentFormStarGift(123, t.Invoice('XTR', [t.LabeledPrice('Gift', 75)]))
        quote = await backend.prepare_resale_gift('Gift-12', 77)
        self.assertEqual(quote.amount, 75)
        request = backend.client.call_args.args[0]
        self.assertIsInstance(request, f.payments.GetPaymentFormRequest)
        self.assertIsInstance(request.invoice, t.InputInvoiceStarGiftResale)
        self.assertEqual(request.invoice.slug, 'Gift-12')


class ArticleTests(unittest.IsolatedAsyncioTestCase):
    def rich(self):
        return t.RichMessage([t.PageBlockTitle(t.TextPlain('Title')),
            t.PageBlockParagraph(t.TextBold(t.TextPlain('Important'))),
            t.PageBlockDetails([t.PageBlockParagraph(t.TextPlain('Hidden detail'))], t.TextPlain('Expand'))], [], [])

    async def test_markdown_html_use_native_rich_requests(self):
        backend = Backend()
        await backend.send_article(77, '# Hello', reply_to=13)
        request = roundtrip(backend.client.call_args.args[0])
        self.assertIsInstance(request.rich_message, t.InputRichMessageMarkdown)
        self.assertEqual(request.reply_to.reply_to_msg_id, 13)
        self.assertEqual(request.message, '')
        self.assertIsInstance(roundtrip(article_input('<h1>Hi</h1>', format='html')), t.InputRichMessageHTML)

    def test_field_edit_keeps_unknown_blocks_and_nested_formatting(self):
        rich = self.rich()
        before = bytes(rich.blocks[2])
        fields = article_fields(rich.blocks)
        path = next(path for path, _, text in fields if text == 'Important')
        replace_article_field(rich, path, 'Changed')
        self.assertIsInstance(rich.blocks[1].text, t.TextBold)
        self.assertEqual(rich.blocks[1].text.text.text, 'Changed')
        self.assertEqual(bytes(rich.blocks[2]), before)
        with self.assertRaises(ValueError): replace_article_field(rich, ('__dict__',), '')

    def test_editable_article_does_not_alias_original(self):
        original = self.rich()
        editable = editable_article(original)
        editable.blocks[0].text.text = 'Different'
        self.assertEqual(original.blocks[0].text.text, 'Title')
        self.assertIsInstance(roundtrip(editable), t.InputRichMessage)

    def test_readable_fallback_includes_collapsed_details_and_is_bounded(self):
        rich = self.rich()
        self.assertIn('Hidden detail', rich_article_text(rich))
        self.assertEqual(len(rich_article_text(rich, maximum=10)), 10)
        self.assertEqual(article_media(rich), [])

    async def test_partial_article_uses_messages_wrapper_response(self):
        full = self.rich()
        partial = deepcopy(full); partial.part = True
        backend = Backend(message(rich=partial))
        backend.client.return_value = t.messages.Messages([message(rich=full)], [], [], 0)
        actual, own = await backend.article_state(77, 12)
        self.assertEqual(bytes(actual), bytes(full)); self.assertTrue(own)
        self.assertIsInstance(backend.client.call_args.args[0], f.messages.GetRichMessageRequest)

    async def test_article_conflict_prevents_overwriting_another_device(self):
        original = self.rich()
        backend = Backend(message(rich=original))
        snapshot = bytes(original)
        edited = deepcopy(original)
        edited.blocks[0].text.text = 'New title'
        backend.current.rich_message.blocks[0].text.text = 'Changed remotely'
        with self.assertRaises(ValueError): await backend.edit_article(77, 12, edited, snapshot)
        backend.client.assert_not_awaited()

    async def test_article_edit_retains_structure(self):
        original = self.rich()
        backend = Backend(message(rich=original))
        edited = deepcopy(original); edited.blocks[0].text.text = 'New title'
        await backend.edit_article(77, 12, edited, bytes(original))
        request = roundtrip(backend.client.call_args.args[0])
        self.assertEqual(request.rich_message.blocks[0].text.text, 'New title')
        self.assertIsInstance(request.rich_message.blocks[2], t.PageBlockDetails)


if __name__ == '__main__': unittest.main()
