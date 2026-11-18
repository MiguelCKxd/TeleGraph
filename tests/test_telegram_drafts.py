import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

from telethon import functions as f, types as t

from tg_ascii.backend import TelegramBackend
from tg_ascii.telegram_drafts import decode_draft


class TelegramDraftTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = AsyncMock()
        self.client.add_event_handler = Mock()
        self.client.get_input_entity.return_value = t.InputPeerUser(42, 123)
        self.client.return_value = True
        self.backend = TelegramBackend(self.client)
        self.now = datetime(2026, 10, 20, tzinfo=timezone.utc)

    async def test_native_save_preserves_text_format_emoji_and_reply_without_sending_message(self):
        await self.backend.save_draft(42, 'Hi 😀 bold', [(5, 9, 'bold', '')], [(3, 4, 99, '😀')], 7)
        request = self.client.call_args.args[0]
        self.assertIsInstance(request, f.messages.SaveDraftRequest)
        self.assertEqual(request.message, 'Hi 😀 bold')
        self.assertEqual(request.peer.user_id, 42)
        self.assertEqual(request.reply_to.reply_to_msg_id, 7)
        self.assertEqual([(e.offset, e.length) for e in request.entities], [(3, 2), (6, 4)])
        self.client.send_message.assert_not_awaited()

    async def test_decode_entities_roundtrips_python_indexes_and_timestamp(self):
        draft = t.DraftMessage('Hi 😀 bold', self.now, entities=[t.MessageEntityCustomEmoji(3, 2, 99),
            t.MessageEntityBold(6, 4)], reply_to=t.InputReplyToMessage(7))
        decoded = decode_draft(draft)
        self.assertEqual(decoded['text'], draft.message)
        self.assertEqual(decoded['formats'], [(5, 9, 'bold', '')])
        self.assertEqual(decoded['custom'], [(3, 4, 99, '😀')])
        self.assertEqual(decoded['reply'], 7)
        self.assertEqual(decoded['date'], self.now.timestamp())
        self.assertFalse(decoded['unsupported'])

    async def test_fetch_is_account_scoped_and_keeps_forum_drafts_separate(self):
        self.client.return_value = NS(updates=[
            t.UpdateDraftMessage(t.PeerUser(42), t.DraftMessage('main', self.now)),
            t.UpdateDraftMessage(t.PeerChannel(55), t.DraftMessage('channel', self.now)),
            t.UpdateDraftMessage(t.PeerUser(42), t.DraftMessage('topic', self.now), top_msg_id=7),
            t.UpdateDraftMessage(t.PeerUser(42), t.DraftMessage('saved peer', self.now), saved_peer_id=t.PeerUser(77))])
        results = await self.backend.fetch_drafts()
        self.assertIsInstance(self.client.call_args.args[0], f.messages.GetAllDraftsRequest)
        self.assertEqual(set(results), {42, -1000000000055})
        self.assertEqual(results[42]['text'], 'main')

    async def test_raw_update_notifies_exact_peer_and_clear_is_not_dropped(self):
        self.backend.on_change = Mock()
        await self.backend.account_event(t.UpdateDraftMessage(t.PeerChannel(55), t.DraftMessageEmpty(self.now)))
        kind, (peer, record) = self.backend.on_change.call_args.args
        self.assertEqual((kind, peer), ('draft', -1000000000055))
        self.assertEqual(record['text'], '')
        self.assertEqual(record['date'], self.now.timestamp())
        self.client.assert_not_awaited()

    async def test_explicit_empty_draft_removes_text_reply_and_entities(self):
        await self.backend.save_draft(42, '')
        request = self.client.call_args.args[0]
        self.assertEqual(request.message, '')
        self.assertIsNone(request.reply_to)
        self.assertEqual(request.entities, [])

    async def test_richer_remote_draft_is_protected_until_explicit_replacement(self):
        draft = t.DraftMessage('caption', self.now, media=t.InputMediaEmpty())
        self.backend.draft_event(t.UpdateDraftMessage(t.PeerUser(42), draft))
        with self.assertRaises(ValueError):
            await self.backend.save_draft(42, 'new text')
        self.client.assert_not_awaited()
        await self.backend.save_draft(42, 'new text', replace_unsupported=True)
        self.client.assert_awaited_once()

    async def test_quotes_and_story_replies_are_marked_richer(self):
        quoted = t.DraftMessage('text', self.now, reply_to=t.InputReplyToMessage(7, quote_text='quote'))
        self.assertTrue(decode_draft(quoted)['unsupported'])
        story = t.DraftMessage('text', self.now, reply_to=t.InputReplyToStory(t.InputPeerUser(42, 3), 9))
        self.assertTrue(decode_draft(story)['unsupported'])

    async def test_webpage_preview_options_survive_text_draft_edit(self):
        draft = t.DraftMessage('link', self.now, no_webpage=True, invert_media=True)
        self.backend.draft_event(t.UpdateDraftMessage(t.PeerUser(42), draft))
        await self.backend.save_draft(42, 'updated link')
        request = self.client.call_args.args[0]
        self.assertTrue(request.no_webpage)
        self.assertTrue(request.invert_media)

    async def test_concurrent_saves_for_same_peer_do_not_finish_out_of_order_and_release_lock(self):
        order = []
        async def save(request):
            order.append(('start', request.message))
            await asyncio.sleep(.002)
            order.append(('end', request.message))
            return True
        self.client.side_effect = save
        await asyncio.gather(self.backend.save_draft(42, 'first'), self.backend.save_draft(42, 'last'))
        self.assertEqual(order, [('start', 'first'), ('end', 'first'), ('start', 'last'), ('end', 'last')])
        self.assertEqual(self.backend._draft_locks, {})

    async def test_timeout_keeps_failure_visible_and_releases_per_peer_lock(self):
        async def stalled(request):
            await asyncio.Event().wait()
        self.client.side_effect = stalled
        with patch('tg_ascii.telegram_drafts.DRAFT_TIMEOUT', .01):
            with self.assertRaises(TimeoutError):
                await self.backend.save_draft(42, 'keep locally')
        self.assertEqual(self.backend._draft_locks, {})

    async def test_false_response_is_not_treated_as_success(self):
        self.client.return_value = False
        with self.assertRaises(ValueError):
            await self.backend.save_draft(42, 'keep locally')

    async def test_invalid_reply_or_formatting_never_requests_server(self):
        for reply in (True, 0, -1):
            with self.assertRaises(ValueError):
                await self.backend.save_draft(42, 'text', reply_to=reply)
        with self.assertRaises(ValueError):
            await self.backend.save_draft(42, 'x', [(0, 9, 'bold', '')])
        self.client.assert_not_awaited()

    async def test_incomplete_snapshot_is_not_mistaken_for_all_drafts_deleted(self):
        self.client.return_value = t.UpdatesTooLong()
        with self.assertRaises(ValueError):
            await self.backend.fetch_drafts()

    async def test_new_richer_push_during_snapshot_keeps_protection_and_preview_flags(self):
        async def snapshot(request):
            self.backend.draft_event(t.UpdateDraftMessage(t.PeerUser(42),
                t.DraftMessage('new rich draft', self.now, media=t.InputMediaEmpty(), no_webpage=True)))
            return NS(updates=[t.UpdateDraftMessage(t.PeerUser(42), t.DraftMessage('old text', self.now))])
        self.client.side_effect = snapshot
        await self.backend.fetch_drafts()
        self.assertIn(42, self.backend._protected_drafts)
        self.assertTrue(self.backend._draft_options[42]['no_webpage'])
        with self.assertRaises(ValueError):
            await self.backend.save_draft(42, 'must not erase rich draft')

    async def test_new_clear_push_during_snapshot_cannot_restore_old_protection_or_options(self):
        async def snapshot(request):
            self.backend.draft_event(t.UpdateDraftMessage(t.PeerUser(42), t.DraftMessageEmpty(self.now)))
            return NS(updates=[t.UpdateDraftMessage(t.PeerUser(42),
                t.DraftMessage('old rich draft', self.now, media=t.InputMediaEmpty(), no_webpage=True))])
        self.client.side_effect = snapshot
        await self.backend.fetch_drafts()
        self.assertNotIn(42, self.backend._protected_drafts)
        self.assertNotIn(42, self.backend._draft_options)

    async def test_complete_snapshot_removes_options_for_draft_deleted_while_offline(self):
        self.backend.draft_event(t.UpdateDraftMessage(t.PeerUser(42),
            t.DraftMessage('old rich draft', self.now, media=t.InputMediaEmpty(), no_webpage=True)))
        self.client.return_value = NS(updates=[])
        await self.backend.fetch_drafts()
        self.assertNotIn(42, self.backend._protected_drafts)
        self.assertNotIn(42, self.backend._draft_options)

    async def test_new_rich_draft_during_save_is_not_unprotected_by_save_completion(self):
        async def save(request):
            self.backend.draft_event(t.UpdateDraftMessage(t.PeerUser(42),
                t.DraftMessage('other client', self.now, media=t.InputMediaEmpty(), no_webpage=True)))
            return True
        self.client.side_effect = save
        await self.backend.save_draft(42, '')
        self.assertIn(42, self.backend._protected_drafts)
        self.assertTrue(self.backend._draft_options[42]['no_webpage'])

    async def test_successful_clear_while_snapshot_in_flight_prevents_old_metadata_returning(self):
        requested, complete = asyncio.Event(), asyncio.Event()
        async def request(request):
            if isinstance(request, f.messages.GetAllDraftsRequest):
                requested.set()
                await complete.wait()
                return NS(updates=[t.UpdateDraftMessage(t.PeerUser(42),
                    t.DraftMessage('old rich draft', self.now, media=t.InputMediaEmpty(), no_webpage=True))])
            return True
        self.client.side_effect = request
        snapshot = asyncio.create_task(self.backend.fetch_drafts())
        await requested.wait()
        await self.backend.save_draft(42, '')
        complete.set()
        await snapshot
        self.assertNotIn(42, self.backend._protected_drafts)
        self.assertNotIn(42, getattr(self.backend, '_draft_options', {}))

    async def test_container_updates_dispatch_draft_events(self):
        self.backend.on_change = Mock()
        draft1 = t.DraftMessage('from container updates', self.now)
        container1 = t.Updates(updates=[t.UpdateDraftMessage(t.PeerUser(42), draft1)], users=[], chats=[], date=self.now, seq=1)
        self.backend.draft_event(container1)
        kind, (peer, record) = self.backend.on_change.call_args.args
        self.assertEqual((kind, peer), ('draft', 42))
        self.assertEqual(record['text'], 'from container updates')

        draft2 = t.DraftMessage('from update short', self.now)
        container2 = t.UpdateShort(update=t.UpdateDraftMessage(t.PeerUser(43), draft2), date=self.now)
        self.backend.draft_event(container2)
        kind, (peer, record) = self.backend.on_change.call_args.args
        self.assertEqual((kind, peer), ('draft', 43))
        self.assertEqual(record['text'], 'from update short')

