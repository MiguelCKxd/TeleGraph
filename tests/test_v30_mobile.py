import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from tg_ascii_mobile.chat_translations import ChatTranslations, digest
from tg_ascii_mobile.core import Core, custom_emoji_spans, emoji_status_id


class ChatTranslationStoreTests(TestCase):
    def test_language_and_texts_persist_per_account_and_edit(self):
        with TemporaryDirectory() as folder:
            store = ChatTranslations(folder, 'a1')
            store.set_language(5, 'es')
            store.store(5, 'es', [(9, 'Hello', {'text': 'Hola', 'emojis': []})])
            again = ChatTranslations(folder, 'a1')
            self.assertEqual(again.language(5), 'es')
            self.assertEqual(again.lookup(5, 'es', [(9, 'Hello')])[9]['text'], 'Hola')
            self.assertIsNone(again.lookup(5, 'es', [(9, 'Hello (edited)')]).get(9))
            self.assertIsNone(ChatTranslations(folder, 'a2').language(5))
            self.assertEqual(os.stat(Path(folder) / 'translations-a1.sqlite3').st_mode & 0o777, 0o600)
            again.set_language(5, None)
            self.assertIsNone(again.language(5))
            again.set_language(5, 'es')
            self.assertEqual(again.lookup(5, 'es', [(9, 'Hello')])[9]['text'], 'Hola')

    def test_deletions_respect_channel_ids_and_thread_scopes(self):
        with TemporaryDirectory() as folder:
            store = ChatTranslations(folder, 'test')
            scopes = [5, -20, -1000000000011, '-1000000000011/14', -1000000000012]
            for peer in scopes:
                store.store(peer, 'es', [(7, 'hello', {'text': 'hola'})])
            store.discard(None, [7])
            store.discard(-1000000000011, [7])
            for peer in scopes[:-1]:
                self.assertFalse(store.lookup(peer, 'es', [(7, 'hello')]))
            self.assertIn(7, store.lookup(scopes[-1], 'es', [(7, 'hello')]))

    def test_migrated_history_survives_previous_count_and_byte_limits(self):
        with TemporaryDirectory() as folder:
            legacy = Path(folder) / 'translations-a1.json'
            value = {'text': 'Hola', 'emojis': []}
            legacy.write_text(json.dumps({'chats': {'5': 'es', '6/2': 'fr'}, 'texts': {
                f'5:es:0:{digest("original")}': value}}))
            store = ChatTranslations(folder, 'a1')
            self.assertFalse(legacy.exists())
            large = {'text': 'é' * 740, 'emojis': []}
            store.store(5, 'es', ((i, 'original', large) for i in range(1, 3101)))
            reopened = ChatTranslations(folder, 'a1')
            self.assertEqual(reopened.language('6/2'), 'fr')
            self.assertEqual(reopened.lookup(5, 'es', [(0, 'original'), (3100, 'original')]),
                             {0: value, 3100: large})


class HelpersTests(TestCase):
    def test_folder_title_custom_emoji_and_expired_status(self):
        entity = SimpleNamespace(document_id=77, offset=5, length=2)
        self.assertEqual(custom_emoji_spans('Work 🔥', [entity]), [['77', '🔥']])
        from datetime import datetime, timedelta, timezone
        live = SimpleNamespace(emoji_status=SimpleNamespace(document_id=5, until=datetime.now(timezone.utc) + timedelta(hours=1)))
        gone = SimpleNamespace(emoji_status=SimpleNamespace(document_id=5, until=datetime.now(timezone.utc) - timedelta(hours=1)))
        self.assertEqual(emoji_status_id(live), '5')
        self.assertIsNone(emoji_status_id(gone))
        self.assertIsNone(emoji_status_id(None))


class AutomaticTranslationTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.core = Core(Path(folder.name), 'Android')
        self.addCleanup(self.core.loop.close)

    async def test_unscoped_delete_only_removes_private_and_basic_group_messages(self):
        from tg_ascii.backend import Message
        from tg_ascii.secret_chats import secret_peer_id

        channel, secret = -1000000000042, secret_peer_id(4)
        message = Message(7, 'QA', 'text', '12:00')
        self.core.histories = {peer: [message] for peer in (5, -9, channel, secret)}
        self.core.floating_peers = {12}
        self.core.open_discussion = ('account', channel, 10)
        self.core.discussion_messages = {7: message}
        with patch.object(self.core, 'emit') as emit, patch.object(self.core, 'schedule_save'):
            self.core.on_change('account', 'delete', (None, [7]))
            affected = {event.args[1]['peer'] for event in emit.call_args_list if event.args[0] == 'delete'}
            self.assertEqual(affected, {5, -9, 12})
            self.assertEqual(self.core.histories, {5: [], -9: [], channel: [message], secret: [message]})
            self.assertIn(7, self.core.discussion_messages)
            self.core.on_change('account', 'delete', (channel, [7]))
            self.assertFalse(self.core.discussion_messages)
            self.assertFalse(self.core.histories[channel])
            self.assertEqual(self.core.histories[secret], [message])

    async def test_saved_translations_are_not_requested_again(self):
        self.core.histories[5] = [SimpleNamespace(id=9, raw_text='Hello', text='Hello')]
        backend = SimpleNamespace(premium_enabled=AsyncMock(return_value=True),
                                  translate_messages=AsyncMock(return_value={9: SimpleNamespace(text='Hola', entities=())}))
        self.core.accounts = SimpleNamespace(current='account', services={'account': SimpleNamespace(backend=backend)})
        await self.core.api_set_chat_translation(5, 'es')
        first = await self.core.api_translate(5, [9], 'es', chat=True)
        second = await self.core.api_translate(5, [9], 'es', chat=True)
        self.assertEqual(first['9']['text'], 'Hola')
        self.assertEqual(second['9']['text'], 'Hola')
        backend.translate_messages.assert_awaited_once()


    async def test_translated_named_link_survives_reopen_with_utf16_offsets(self):
        from telethon.tl import types
        from tg_ascii.backend import Message

        message = Message(9, 'QA', 'Visit the site', '12:00')
        value = types.TextWithEntities('😀 Visita el sitio', [
            types.MessageEntityTextUrl(13, 5, 'https://example.org/info'),
            types.MessageEntityBold(13, 5),
        ])
        backend = SimpleNamespace(premium_enabled=AsyncMock(return_value=True),
                                  translate_messages=AsyncMock(return_value={9: value}))
        self.core.accounts = SimpleNamespace(current='qa', services={'qa': SimpleNamespace(backend=backend)})
        self.core.histories[5] = [message]
        await self.core.api_set_chat_translation(5, 'es')
        response = await self.core.api_translate(5, [9], 'es', chat=True)
        self.assertIn([13, 18, 'link', 'https://example.org/info'], response['9']['formats'])
        self.assertIn([13, 18, 'bold', ''], response['9']['formats'])
        self.core.__dict__.pop('_translations')
        self.assertEqual(self.core.translation_state(5, [message])['translated'], response)
        backend.translate_messages.assert_awaited_once()

    async def test_translation_setting_is_broadcast_and_loaded_in_floating_window(self):
        from tg_ascii.backend import Message

        message = Message(9, 'Reader', 'Hello', '12:00')
        backend = SimpleNamespace(premium_enabled=AsyncMock(return_value=True))
        self.core.accounts = SimpleNamespace(current='account', services={'account': SimpleNamespace(backend=backend)})
        self.core.histories[5] = [message]
        self.core.emit = lambda event, data: events.append((event, data))
        events = []
        store = self.core.translations()
        store.store(5, 'es', [(9, 'Hello', {'text': 'Hola', 'emojis': []})])
        enabled = await self.core.api_set_chat_translation(5, 'es')
        self.assertEqual(events[-1], ('chat_translation', {
            'account': 'account', 'peer': 5, 'thread_root': None, **enabled,
        }))
        with patch.object(self.core.loop, 'create_task', side_effect=asyncio.create_task):
            window = await self.core.api_window_open(5, 'account', read=False)
        self.assertEqual(window['translated']['9']['text'], 'Hola')
        self.assertEqual(window['translate'], 'es')
        await self.core.api_set_chat_translation(5, None)
        self.assertIsNone(events[-1][1]['translate'])

    async def test_older_history_reuses_translations_without_an_rpc(self):
        from tg_ascii.backend import Message

        message = Message(9, 'Reader', 'Hello', '12:00')
        backend = SimpleNamespace(
            older_messages=AsyncMock(return_value=[message]),
            translate_messages=AsyncMock(),
        )
        self.core.accounts = SimpleNamespace(current='account', services={'account': SimpleNamespace(backend=backend)})
        store = self.core.translations()
        store.set_language(5, 'es')
        store.store(5, 'es', [(9, 'Hello', {'text': 'Hola', 'emojis': []})])
        self.core.__dict__.pop('_translations', None)
        page = await self.core.api_older(5, 10)
        self.assertEqual(page['translate'], 'es')
        self.assertEqual(page['translated']['9']['text'], 'Hola')
        self.assertEqual(page['messages'][0]['id'], 9)
        backend.translate_messages.assert_not_awaited()

    async def test_discussion_uses_its_own_translation_and_restores_cache_on_open(self):
        from tg_ascii.backend import Message
        from tg_ascii.peer_tools import HistoryPage

        peer, root = -200, 10
        post = Message(root, 'Channel', 'News', '12:00')
        reply = Message(21, 'Reader', 'Good morning', '12:01', thread_id=root)
        backend = SimpleNamespace(
            premium_enabled=AsyncMock(return_value=True),
            discussion_message=AsyncMock(return_value={'peer': peer, 'root_id': root, 'root': post}),
            discussion_history=AsyncMock(return_value=HistoryPage([reply])),
            read_discussion=AsyncMock(),
            translate_messages=AsyncMock(return_value={21: SimpleNamespace(text='Buenos días')}),
        )
        self.core.accounts = SimpleNamespace(current='account', services={'account': SimpleNamespace(backend=backend)})
        # Keep the background read receipt on the loop owned by this test.
        from unittest.mock import patch

        with patch.object(self.core.loop, 'create_task', side_effect=asyncio.create_task):
            await self.core.api_comments(-100, 1)
            await self.core.api_set_chat_translation(peer, 'es', thread_root=root)
            await self.core.api_translate(peer, [21], 'es', chat=True, thread_root=root)
            await self.core.api_close(peer)
            self.core.__dict__.pop('_translations', None)
            reopened = await self.core.api_comments(-100, 1)
            self.assertEqual(reopened['translate'], 'es')
            self.assertEqual(reopened['translated']['21']['text'], 'Buenos días')
            self.assertIsNone(self.core.translations().language(peer))
            backend.translate_messages.assert_awaited_once()
            edited = Message(21, 'Reader', 'Good night', '12:01', thread_id=root)
            backend.discussion_history.return_value = HistoryPage([edited])
            self.assertEqual((await self.core.api_comments(-100, 1))['translated'], {})
            await self.core.api_set_chat_translation(peer, None, thread_root=root)
            self.assertIsNone((await self.core.api_comments(-100, 1))['translate'])


class ContactProfileTests(IsolatedAsyncioTestCase):
    async def test_personal_channel_preview_is_optional_and_uses_the_exact_post(self):
        from tg_ascii.backend import Message

        with TemporaryDirectory() as folder:
            core = Core(Path(folder), 'iOS')
            self.addCleanup(core.loop.close)
            channel = -1000000000123
            raw = object()
            checked = AsyncMock(return_value=raw)
            post = Message(20, 'Channel', 'News 😀', '10:00', custom_emojis=[(918273645546372819, '😀')])
            backend = SimpleNamespace(checked_message=checked, message=lambda item: post if item is raw else None)
            core.accounts = SimpleNamespace(current='account', services={'account': SimpleNamespace(backend=backend)})
            self.assertEqual(await core.api_personal_channel_preview(channel, 20),
                             {'text': 'News 😀', 'emojis': [['918273645546372819', '😀']]})
            checked.assert_awaited_once_with(channel, 20)
            checked.side_effect = ValueError('Unavailable')
            self.assertIsNone(await core.api_personal_channel_preview(channel, 20))

    async def test_profile_serializes_server_fields_and_respects_call_privacy(self):
        from telethon.tl import types

        with TemporaryDirectory() as folder:
            core = Core(Path(folder), 'iOS')
            self.addCleanup(core.loop.close)
            backend = SimpleNamespace(profile=AsyncMock(return_value={
                'name': 'Contact', 'kind': 'user', 'premium': True,
                'location': types.BusinessLocation('Office'),
                'work_hours': types.BusinessWorkHours('Europe/Madrid', [types.BusinessWeeklyOpen(540, 1020)]),
                'personal_channel_id': 123, 'personal_channel_message': 20, 'linked_chat_id': 456,
                'business_intro': types.BusinessIntro('Welcome', 'Office hours apply'),
                'bot_verification': types.BotVerification(1, 918273645546372819, 'Verified by Test'),
                'phone_calls_private': True, 'phone_calls_available': True, 'video_calls_available': True,
            }))
            core.accounts = SimpleNamespace(current='account', services={'account': SimpleNamespace(backend=backend)})
            profile = await core.api_profile(7)
            self.assertEqual(profile['address'], 'Office')
            self.assertEqual(profile['work_hours'], {'timezone': 'Europe/Madrid', 'periods': [[540, 1020]]})
            self.assertEqual(profile['personal_channel'], -1000000000123)
            self.assertEqual(profile['personal_channel_message'], 20)
            self.assertEqual(profile['linked_peer'], -1000000000456)
            self.assertEqual(profile['business_intro']['description'], 'Office hours apply')
            self.assertEqual(profile['bot_verification']['icon'], '918273645546372819')
            self.assertFalse(profile['phone_calls_available'])
            self.assertFalse(profile['video_calls_available'])

    async def test_contact_card_editor_persists_locally_and_keeps_settings_reachable(self):
        from tg_ascii.preferences import Preferences

        with TemporaryDirectory() as folder:
            core = Core(Path(folder), 'iOS')
            self.addCleanup(core.loop.close)
            core.accounts = SimpleNamespace(current='qa')
            core.prefs = Preferences(Path(folder))
            await core.api_contact_card_appearance('qa', {'contact_avatar_size': 112, 'contact_hidden_actions': ['call']})
            core.prefs = Preferences(Path(folder))
            result = await core.api_contact_card_appearance('qa')
            self.assertEqual(result['values']['contact_avatar_size'], 112)
            self.assertEqual(result['values']['contact_hidden_actions'], ['call'])
            for account, changes in [('other', {'contact_card_width': 400}), ('qa', {'contact_hidden_actions': ['manage']}),
                                     ('qa', {'contact_hidden_sections': ['settings']}), ('qa', {'theme': 'light'})]:
                with self.subTest(account=account, changes=changes), self.assertRaises(ValueError):
                    await core.api_contact_card_appearance(account, changes)
            restored = await core.api_contact_card_appearance('qa', result['defaults'])
            self.assertEqual(restored['values'], result['defaults'])


class MobileLinksTests(TestCase):
    def test_message_links_keep_utf16_offsets_and_detect_bare_domains(self):
        from telethon.tl import types
        from tg_ascii.backend import Message
        from tg_ascii_mobile.core import formats_json

        text = '😀 open example.com'
        message = Message(7, 'Reader', text, '', raw_text=text,
                          entities=[types.MessageEntityTextUrl(3, 4, 'https://t.me/telegram'),
                                    types.MessageEntityBold(3, 4)])
        spans = formats_json(message, text, False)
        self.assertIn([3, 7, 'link', 'https://t.me/telegram'], spans)
        self.assertIn([3, 7, 'bold', ''], spans)
        self.assertIn([8, 19, 'link', 'https://example.com'], spans)
        message.entities = [types.MessageEntityTextUrl(3, 4, 'javascript:alert(1)')]
        self.assertNotIn([3, 7], [span[:2] for span in formats_json(message, text, False)])


class DefaultReactionTests(IsolatedAsyncioTestCase):
    async def test_custom_reaction_survives_reload_without_number_rounding(self):
        from tg_ascii.backend import Message
        from tg_ascii.preferences import Preferences

        with TemporaryDirectory() as folder:
            core = Core(Path(folder), 'Android')
            self.addCleanup(core.loop.close)
            core.prefs = Preferences(Path(folder))
            core.prefs.save({'quick_reaction': '👍'})
            backend = SimpleNamespace(set_default_reaction=AsyncMock(return_value=False),
                                      available_reactions=AsyncMock(return_value=['👍']))
            core.accounts = SimpleNamespace(current='account', services={'account': SimpleNamespace(backend=backend)})
            ident = 918273645546372819
            result = await core.api_set_default_reaction(str(ident), account='account')
            self.assertEqual(result, {'current': str(ident), 'synced': False})
            backend.set_default_reaction.assert_awaited_once_with(ident)
            core.prefs = Preferences(Path(folder))
            self.assertEqual(core.settings_snapshot()['quick_reaction'], str(ident))
            self.assertEqual((await core.api_default_reaction_choices())['custom'], [str(ident)])
            message = Message(7, 'Reader', 'Hello', '12:00', reactions=[(ident, 1, True)])
            self.assertEqual(core.message_json(message)['reactions'], [[str(ident), 1, True]])
            core.accounts.current = 'second'
            self.assertEqual(core.settings_snapshot()['quick_reaction'], '👍')
            with self.assertRaisesRegex(ValueError, 'account changed'):
                await core.api_set_default_reaction('👍', account='account')
            core.accounts.current = 'account'
            self.assertEqual(core.settings_snapshot()['quick_reaction'], str(ident))


class DateSearchTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.core = Core(Path(folder.name), 'Android')
        self.addCleanup(self.core.loop.close)

    def set_backend(self, backend):
        self.core.accounts = SimpleNamespace(current='account', services={'account': SimpleNamespace(backend=backend)})

    async def test_date_only_includes_local_midnight_and_finds_the_first_message(self):
        from datetime import datetime, timedelta, timezone
        from tg_ascii.backend import Message

        start = datetime(2026, 10, 24, 22, tzinfo=timezone.utc)
        end = start + timedelta(hours=25)
        first = SimpleNamespace(date=start, message='At midnight')

        async def iterate(peer, **options):
            self.assertEqual(peer, 7)
            self.assertTrue(options['reverse'])
            self.assertEqual(options['offset_date'], start - timedelta(seconds=1))
            for raw in (SimpleNamespace(date=start - timedelta(seconds=1), message='Earlier'), first,
                        SimpleNamespace(date=end - timedelta(seconds=1), message='Later')):
                yield raw

        self.set_backend(SimpleNamespace(client=SimpleNamespace(iter_messages=iterate), resolve_missing_senders=AsyncMock(),
                                         message=lambda item: Message(9, 'Reader', item.message, '00:00', date=item.date)))
        results = await self.core.api_search_messages(7, '', date='2026-10-25',
                                                      day_bounds=[int(start.timestamp()), int(end.timestamp())])
        self.assertEqual([item['text'] for item in results], ['At midnight'])

    async def test_thread_date_and_text_are_both_applied(self):
        from datetime import datetime, timedelta, timezone
        from tg_ascii.backend import Message

        start = datetime(2026, 11, 17, tzinfo=timezone.utc)
        end = start + timedelta(days=1)

        async def iterate(peer, **options):
            self.assertEqual(options, {'offset_date': end, 'reverse': False, 'reply_to': 12})
            for ident, date, text in ((1, end, 'MATCH'), (2, end - timedelta(seconds=1), 'Other'),
                                      (3, start, 'match'), (4, start - timedelta(seconds=1), 'match')):
                yield SimpleNamespace(id=ident, date=date, message=text)

        self.set_backend(SimpleNamespace(client=SimpleNamespace(iter_messages=iterate), resolve_missing_senders=AsyncMock(),
                                         message=lambda item: Message(item.id, 'Reader', item.message, '', date=item.date)))
        results = await self.core.api_search_messages(7, 'Match', thread_root=12, date='2026-11-17',
                                                      day_bounds=[int(start.timestamp()), int(end.timestamp())])
        self.assertEqual([item['id'] for item in results], [3])


class DiscussionNavigationTests(IsolatedAsyncioTestCase):
    async def test_slow_discussion_cannot_replace_a_more_recent_one(self):
        from unittest.mock import patch

        from tg_ascii.backend import Message
        from tg_ascii.peer_tools import HistoryPage

        with TemporaryDirectory() as folder:
            core = Core(Path(folder), 'Android')
            self.addCleanup(core.loop.close)
            started, release = asyncio.Event(), asyncio.Event()

            async def discussion_message(_peer, ident):
                return {'peer': -200, 'root_id': ident, 'root': Message(ident, 'Channel', 'Post', '12:00')}

            async def discussion_history(_peer, root):
                if root == 10:
                    started.set()
                    await release.wait()
                return HistoryPage([Message(root + 1, 'Reader', 'Comment', '12:01', thread_id=root)])

            backend = SimpleNamespace(discussion_message=discussion_message, discussion_history=discussion_history,
                                      read_discussion=AsyncMock())
            core.accounts = SimpleNamespace(current='account', services={'account': SimpleNamespace(backend=backend)})
            with patch.object(core.loop, 'create_task', side_effect=asyncio.create_task):
                first = asyncio.create_task(core.api_comments(-100, 10))
                await started.wait()
                self.assertEqual((await core.api_comments(-100, 20))['root_id'], 20)
                release.set()
                with self.assertRaisesRegex(ValueError, 'active conversation changed'):
                    await first
                self.assertEqual(core.open_discussion, ('account', -200, 20))
                self.assertEqual(set(core.discussion_messages), {20, 21})
                backend.read_discussion.assert_awaited_once_with(-200, 20, 21)


    async def test_system_window_keeps_its_discussion_separate_from_the_main_chat(self):
        from unittest.mock import patch

        from tg_ascii.backend import Message
        from tg_ascii.peer_tools import HistoryPage

        with TemporaryDirectory() as folder:
            core = Core(Path(folder), 'Android')
            self.addCleanup(core.loop.close)
            core.stage = 'ready'

            async def discussion_message(_peer, root):
                return {'peer': -200, 'root_id': root, 'root': Message(root, 'Channel', 'Post', '12:00')}

            backend = SimpleNamespace(discussion_message=discussion_message,
                                      discussion_history=AsyncMock(return_value=HistoryPage()),
                                      read_discussion=AsyncMock(), history=AsyncMock(return_value=[]))
            core.accounts = SimpleNamespace(current='account', services={'account': SimpleNamespace(backend=backend)})
            core.refresh_header = AsyncMock()
            with patch.object(core.loop, 'create_task', side_effect=asyncio.create_task):
                await core.api_comments(-100, 10)
                await core.api_open(-100, window=True)
                await core.api_comments(-100, 20, window_peer=-100)
                self.assertEqual(core.open_discussion, ('account', -200, 10))
                self.assertEqual(core.discussion_view(-100)[0], ('account', -200, 20))
                core.locked = True
                draft = {'account': 'account', 'peer': -200, 'thread_root': 20, 'text': 'Window draft'}
                self.assertTrue(await core.call('draft', {**draft, 'window_peer': -100}))
                with self.assertRaises(PermissionError):
                    await core.call('draft', draft)
                await core.call('close', {'peer': -100, 'window': True})
                self.assertIsNone(core.discussion_view(-100)[0])
                self.assertEqual(core.open_discussion, ('account', -200, 10))
                self.assertEqual(core.draft_record(-200, 20)['text'], 'Window draft')


class DiscussionPollTests(IsolatedAsyncioTestCase):
    async def test_quiz_keeps_selected_indices_and_discussion_reply(self):
        with TemporaryDirectory() as folder:
            core = Core(Path(folder), 'Android')
            self.addCleanup(core.loop.close)
            backend = SimpleNamespace(send_poll=AsyncMock(return_value=None))
            core.accounts = SimpleNamespace(current='account', services={'account': SimpleNamespace(backend=backend)})
            await core.api_send_poll(-200, 'Question', ['A', 'B', 'C'], quiz=True, correct=[0, 2],
                                     solution='Explanation', thread_root=10, account='account')
            backend.send_poll.assert_awaited_once_with(
                -200, 'Question', ['A', 'B', 'C'], reply_to=10, anonymous=True, multiple=True,
                quiz=True, correct=[0, 2], solution='Explanation', open_answers=False, revoting=True,
                shuffle=False, hidden_results=False, subscribers_only=False, countries=(), close_period=None)


    async def test_poll_uploads_attachments_and_keeps_files_until_send_succeeds(self):
        with TemporaryDirectory() as folder:
            core = Core(Path(folder), 'Android')
            self.addCleanup(core.loop.close)
            attachment = core.staging_path('photo.png')
            attachment.write_bytes(b'image')
            media = object()
            backend = SimpleNamespace(
                prepare_poll_attachments=AsyncMock(return_value={'attached_media': media}),
                send_poll=AsyncMock(side_effect=[RuntimeError('send failed'), None]),
            )
            core.accounts = SimpleNamespace(current='account', services={'account': SimpleNamespace(backend=backend)})
            params = dict(files={'attached_media': attachment.name}, thread_root=10, account='account')
            with self.assertRaisesRegex(RuntimeError, 'send failed'):
                await core.api_send_poll(-200, 'Question', ['A', 'B'], **params)
            self.assertTrue(attachment.exists())
            await core.api_send_poll(-200, 'Question', ['A', 'B'], **params)
            self.assertFalse(attachment.exists())
            self.assertEqual(backend.prepare_poll_attachments.await_args.args[3], {'attached_media': attachment.resolve()})
            self.assertIs(backend.send_poll.await_args.kwargs['attached_media'], media)
            self.assertEqual(backend.send_poll.await_args.kwargs['reply_to'], 10)


class SettingsParityTests(TestCase):
    def test_ringtones_round_trip_and_features_default_on(self):
        from telethon.tl import types
        from tg_ascii_mobile.notification_settings import parse_sound, sound_name
        from tg_ascii_mobile.core import mobile_features
        self.assertEqual(sound_name(types.NotificationSoundRingtone(42)), 'ringtone:42')
        self.assertEqual(parse_sound('ringtone:42').id, 42)
        with self.assertRaises(ValueError):
            parse_sound('ringtone:x')
        values = mobile_features({'mobile_features': {'calls': False, 'gpu_video': True}})
        self.assertFalse(values['calls'])
        self.assertTrue(values['polls'])
        self.assertNotIn('gpu_video', values)


class SecretChatMobileTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.core = Core(Path(self.folder.name), 'Android')
        self.addCleanup(self.core.loop.close)

    async def test_secret_drafts_and_previews_never_persist_unencrypted(self):
        from tg_ascii.backend import Chat
        from tg_ascii.secret_chats import secret_peer_id
        sec_peer = secret_peer_id(77)
        normal_peer = 100
        self.core.set_draft(sec_peer, {'text': 'Top secret draft'})
        self.core.set_draft(normal_peer, {'text': 'Normal draft'})
        self.assertEqual(self.core.draft_record(sec_peer)['text'], 'Top secret draft')
        self.assertIsNone(self.core.draft_store.get(self.core.account, sec_peer))
        self.assertEqual(self.core.draft_store.get(self.core.account, normal_peer)['text'], 'Normal draft')

        self.core.previews = {
            sec_peer: {'text': 'Encrypted message', 'out': True, 'date': 1000},
            normal_peer: {'text': 'Public message', 'out': False, 'date': 1000},
        }
        await self.core.save_snapshot()
        import json
        saved = json.loads(self.core.previews_path().read_text('utf-8'))
        self.assertNotIn(str(sec_peer), saved)
        self.assertIn(str(normal_peer), saved)

        sec_chat = Chat(id=sec_peer, name='🔒 Alice', unread=0, entity=None, kind='secret')
        self.assertEqual(self.core.chat_json(sec_chat)['draft'], 'Top secret draft')
        self.core.set_draft(sec_peer, {'text': ''})
        self.assertEqual(self.core.draft_record(sec_peer)['text'], '')

    async def test_watch_translation_accepts_locale_and_rejects_secret_messages(self):
        from unittest.mock import patch
        from tg_ascii.secret_chats import secret_peer_id

        self.core.stage = 'ready'
        translate = AsyncMock(return_value={'12': {'text': 'Hola'}})
        with patch.object(self.core, 'api_translate', translate):
            result = await self.core.watch_request(
                {'op': 'translate', 'peer': 5, 'ids': [12], 'language': 'an_ES'})
            self.assertEqual(result, {'12': 'Hola'})
            translate.assert_awaited_once_with(5, [12], 'es', chat=False)
            with self.assertRaisesRegex(ValueError, 'Secret chat'):
                await self.core.watch_request(
                    {'op': 'translate', 'peer': secret_peer_id(88), 'ids': [12], 'language': 'es'})
            self.assertEqual(translate.await_count, 1)

    async def test_secret_api_and_watch_bridge(self):
        from tg_ascii.backend import Chat
        from tg_ascii.secret_chats import secret_peer_id
        sec_peer = secret_peer_id(88)
        sec_chat = Chat(id=sec_peer, name='🔒 Bob', unread=0, entity=None, kind='secret')
        info_payload = {
            'id': 88, 'peer_id': sec_peer, 'user_id': 500, 'title': 'Bob',
            'state': 'active', 'layer': 144, 'ttl': 30,
            'hex': 'AA BB CC', 'emojis': '🔒 🔑 🛡 ✨', 'grid': ['█░'],
        }
        backend = SimpleNamespace(
            start_secret_chat=AsyncMock(return_value=sec_chat),
            secret_chat_info=AsyncMock(side_effect=lambda peer: info_payload if int(peer) == sec_peer else None),
            set_secret_ttl=AsyncMock(return_value=True),
            rekey_secret_chat=AsyncMock(return_value=True),
            notify_secret_screenshot=AsyncMock(return_value=True),
            discard_secret_chat=AsyncMock(return_value=True),
            fetch_chats=AsyncMock(return_value=[sec_chat]),
            pinned_dialogs=AsyncMock(return_value=set()),
            archived_chats=AsyncMock(return_value=[]),
            client=SimpleNamespace(_self_id=1),
        )
        self.core.accounts = SimpleNamespace(
            current='account',
            services={'account': SimpleNamespace(backend=backend, state='online', previews={}, histories={}, chats=[sec_chat])},
            active=SimpleNamespace(backend=backend, state='online', previews={}, histories={}, chats=[sec_chat]),
        )
        self.core.chats = [sec_chat]
        info = await self.core.api_secret_info(sec_peer)
        self.assertEqual(info['ttl'], 30)
        self.assertIn(10, info['ttl_choices'])
        self.assertEqual(info['hex'], 'AA BB CC')
        await self.core.api_secret_ttl(sec_peer, 60)
        backend.set_secret_ttl.assert_awaited_once_with(sec_peer, 60)
        await self.core.api_secret_rekey(sec_peer)
        backend.rekey_secret_chat.assert_awaited_once_with(sec_peer)
        await self.core.api_secret_screenshot(sec_peer)
        backend.notify_secret_screenshot.assert_awaited_once_with(sec_peer)

        media_dir = self.core.media_folder()
        media_dir.mkdir(parents=True, exist_ok=True)
        cached_file = media_dir / f'{sec_peer}-1-secret.jpg'
        cached_file.write_bytes(b'data')
        self.core.refresh_chats = AsyncMock()
        await self.core.api_secret_discard(sec_peer, delete_history=True)
        backend.discard_secret_chat.assert_awaited_once_with(sec_peer, delete_history=True)
        self.assertFalse(cached_file.exists())
        self.assertEqual(self.core.chats, [])

        self.core.stage = 'ready'
        watch_res = await self.core.watch_request({'op': 'secret_info', 'peer': sec_peer})
        self.assertEqual(watch_res['layer'], 144)


class PushRegistrationMobileTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.core = Core(Path(self.folder.name), 'iOS')
        self.addCleanup(self.core.loop.close)

    async def test_ios_requests_background_time_on_each_enabled_transition(self):
        self.core.prefs = SimpleNamespace(values={'notifications': True})
        self.core.appearance = Mock(return_value={'keep_connected': True})
        self.core.native_keep_alive = Mock()
        await self.core.api_app_hidden()
        await self.core.api_app_visible()
        await self.core.api_app_hidden()
        self.core.prefs.values['notifications'] = False
        self.core.keep_connected()
        calls = self.core.native_keep_alive.call_args_list
        self.assertEqual([call.args[0] for call in calls], [True, False, True, False])

    async def test_permission_install_before_and_after_account_is_ready(self):
        enable, disable = Mock(), Mock()
        self.core.prefs = SimpleNamespace(values={'notifications': True})
        self.core.stage = 'loading'
        self.core.install_notification_permission(enable, disable)
        enable.assert_not_called()
        self.core.stage = 'ready'
        self.core.apply_notification_permission()
        enable.assert_called_once()
        self.core.prefs.values['notifications'] = False
        self.core.install_notification_permission(enable, disable)
        disable.assert_called_once()
        enable.assert_called_once()

    async def test_socket_and_push_deliver_an_incoming_message_only_once(self):
        self.core.loop = asyncio.get_running_loop()
        self.core.accounts = SimpleNamespace(current='active')
        self.core.notify = AsyncMock()
        events = []
        self.core.emit = lambda kind, payload: events.append((kind, payload))
        message = SimpleNamespace(id=15, outgoing=False)

        self.core.on_message('other', 777000, message)
        self.core.on_message('other', 777000, message)
        self.core.on_message('another', 777000, message)
        await asyncio.sleep(0)

        self.assertEqual(self.core.notify.await_count, 2)
        self.assertEqual(events, [('other_account', {'account': 'other'}),
                                  ('other_account', {'account': 'another'})])

    async def test_wakeup_at_account_chooser_only_connects_the_addressed_saved_session(self):
        self.core.stage = 'choose_account'
        client = AsyncMock()
        backend = SimpleNamespace(client=client)
        service = SimpleNamespace(backend=None, session_path=self.core.root / 'account')
        service.session_path.with_suffix('.session').touch()

        async def connect(credentials):
            service.backend = backend
            return 'ready'

        service.connect = AsyncMock(side_effect=connect)
        accounts = SimpleNamespace(identities={'first': 10, 'second': 20}, current='first', credentials=None,
                                   services={}, register=AsyncMock())

        def lookup(key):
            self.assertEqual(key, 'second')
            accounts.services[key] = service
            return service

        accounts.service = Mock(side_effect=lookup)
        self.core.accounts = accounts
        self.assertEqual(await self.core._handle_push_payload({'user_id': 99}), 1)
        accounts.service.assert_not_called()
        results = await asyncio.gather(*(self.core._handle_push_payload({'user_id': 20}) for _ in range(2)))
        self.assertEqual(results, [1, 1])
        service.connect.assert_awaited_once()
        accounts.register.assert_awaited_once_with('second')
        self.assertEqual(client.catch_up.await_count, 2)
        self.assertEqual((accounts.current, self.core.stage), ('first', 'choose_account'))

    async def test_android_badge_finds_only_recent_unread_and_deduplicates_after_restart(self):
        from datetime import datetime, timezone
        from tg_ascii.backend import Message

        core = self.core
        core.system, core.stage, core.in_background = 'Android', 'ready', True
        core.prefs = SimpleNamespace(values={'notify_preview': False})
        core.native_notify = Mock()
        now = int(datetime.now(timezone.utc).timestamp())

        def item(peer, age=0, unread=1, out=False, pinned=False):
            raw = SimpleNamespace(id=20, date=datetime.fromtimestamp(now-age, timezone.utc), out=out)
            return SimpleNamespace(id=peer, input_entity=peer, pinned=pinned, message=raw, unread_count=unread,
                                   dialog=SimpleNamespace(read_inbox_max_id=0 if unread else 20))

        async def dialogs():
            for row in (item(1,200,pinned=True),item(2,unread=0),item(3,out=True),item(4),item(5,200)):
                yield row

        async def history(peer, **bounds):
            self.assertEqual((peer, bounds), (3, {'offset_id': 20, 'min_id': 0}))
            for message in ():
                yield message

        backend = SimpleNamespace(client=SimpleNamespace(iter_dialogs=dialogs, iter_messages=history),
                                  notification_policy=AsyncMock(return_value={'enabled':True,'preview':True,'sound':True}),
                                  message=lambda raw: Message(id=20, sender='Sender', text='Private test', date=raw.date, time='12:00'))
        core.accounts = SimpleNamespace(services={'a':SimpleNamespace(backend=backend)},current='a',entries={'a':{}})
        core.native_notify.side_effect = OSError('System delivery failed')
        with self.assertRaises(OSError):
            await core.sync_android_badge(now)
        core.native_notify.side_effect = None
        self.assertEqual(await core.sync_android_badge(now), 0)
        self.assertEqual(core.native_notify.call_args.args[:2], ('a',4))
        self.assertNotIn('Private test', core.native_notify.call_args.args)
        core.native_notify.reset_mock()
        self.assertEqual(await core.sync_android_badge(now), 1)
        core.native_notify.assert_not_called()
        fresh = Core(core.root, 'Android')
        self.addCleanup(fresh.loop.close)
        self.assertFalse(fresh.claim_android_notification(('a',4,20)))
        self.assertTrue(fresh.claim_android_notification(('b',4,20)))

    async def test_badge_reaches_second_account_when_first_account_fails(self):
        from datetime import datetime, timezone

        core = self.core
        core.stage = 'choose_account'
        core.prefs = SimpleNamespace(values={})
        now = datetime.now(timezone.utc)
        raw = SimpleNamespace(id=3, date=now, out=False)
        async def dialogs():
            yield SimpleNamespace(message=raw, id=4, unread_count=1,
                                  dialog=SimpleNamespace(read_inbox_max_id=0))
        backend = SimpleNamespace(client=SimpleNamespace(iter_dialogs=dialogs), message=lambda message: message)
        core.accounts = SimpleNamespace(services={}, identities={'offline': 1, 'ready': 2}, current='offline')
        async def connect(key):
            if key == 'offline':
                raise ConnectionError('offline')
            core.accounts.services[key] = SimpleNamespace(backend=backend)
        core.connect_saved_push_account = connect
        core.notify = AsyncMock(return_value=True)
        with self.assertRaises(ConnectionError):
            await core.sync_android_badge(int(now.timestamp()))
        core.notify.assert_awaited_once_with('ready', 4, raw)
        self.assertEqual((core.stage, core.accounts.current), ('choose_account', 'offline'))

    async def test_badge_finds_recent_unread_behind_call_but_stops_at_time_boundary(self):
        from datetime import datetime, timedelta, timezone

        core = self.core
        core.stage = 'ready'
        core.prefs = SimpleNamespace(values={})
        now = datetime.now(timezone.utc)
        def message(number, age=0, action=None):
            return SimpleNamespace(id=number, out=False, date=now-timedelta(seconds=age), action=action)
        async def dialogs():
            for peer in (4, 5):
                yield SimpleNamespace(id=peer, input_entity=peer, message=message(22, action='call'),
                                      unread_count=1, dialog=SimpleNamespace(read_inbox_max_id=18))
        async def history(peer, **bounds):
            self.assertEqual(bounds, {'offset_id': 22, 'min_id': 18})
            yield message(21, action='call')
            yield message(20, age=60 if peer == 4 else 100)
        client = SimpleNamespace(iter_dialogs=dialogs, iter_messages=history)
        backend = SimpleNamespace(client=client, message=lambda raw: raw.id)
        core.accounts = SimpleNamespace(services={'ready': SimpleNamespace(backend=backend)})
        core.notify = AsyncMock(return_value=True)
        self.assertEqual(await core.sync_android_badge(int(now.timestamp())), 0)
        core.notify.assert_awaited_once_with('ready', 4, 20)

    async def test_account_only_android_wakeup_never_scans_another_account(self):
        core = self.core
        core.stage = 'choose_account'
        core.prefs = SimpleNamespace(values={})
        core.accounts = SimpleNamespace(identities={'first': 10, 'second': 20}, current='first')
        core._sync_account_badge = AsyncMock(return_value=True)
        for unknown in (0, True, '20', 99):
            self.assertEqual(await core.sync_android_badge(200, unknown), 1)
        core._sync_account_badge.assert_not_awaited()
        self.assertEqual(await core.sync_android_badge(200, 20), 0)
        core._sync_account_badge.assert_awaited_once_with('second', 110, 20)
        self.assertEqual(core.accounts.current, 'first')

    async def test_android_token_refresh_retries_when_telegram_did_not_register(self):
        client = AsyncMock(return_value=False)
        self.core.accounts = SimpleNamespace(services={'a':SimpleNamespace(backend=SimpleNamespace(client=client))},
                                             identities={'a':10})
        self.core.stage = 'ready'
        self.assertEqual(await self.core.refresh_android_push_token('rotated'), 2)
        client.return_value = True
        self.assertEqual(await self.core.refresh_android_push_token('rotated'), 0)
        self.assertEqual(client.await_count, 2)

    async def test_token_rotation_and_account_removal_refresh_push_registration(self):
        from telethon.tl.functions.account import RegisterDeviceRequest, UnregisterDeviceRequest

        clients = {key: AsyncMock(return_value=True) for key in ('a', 'b')}
        self.core.accounts = SimpleNamespace(
            services={key: SimpleNamespace(backend=SimpleNamespace(client=client))
                      for key, client in clients.items()},
            identities={'a': 10, 'b': 20})
        self.core._push_token = (2, 'first', False)
        await self.core.sync_push_registration()
        self.core._push_token = (2, 'second', False)
        await asyncio.gather(self.core.sync_push_registration(), self.core.sync_push_registration())
        for key, other in [('a', 20), ('b', 10)]:
            requests = [call.args[0] for call in clients[key].await_args_list]
            self.assertEqual([(type(req), req.token, req.other_uids) for req in requests], [
                (RegisterDeviceRequest, 'first', [other]),
                (UnregisterDeviceRequest, 'first', []),
                (RegisterDeviceRequest, 'second', [other])])

        self.core._push_logging_out.add('b')
        await self.core.unregister_push_account('b')
        await self.core.sync_push_registration()
        self.assertEqual(clients['a'].await_args.args[0].other_uids, [])
        self.assertIsInstance(clients['b'].await_args.args[0], UnregisterDeviceRequest)
        self.assertNotIn('b', self.core._push_registered)

    async def test_apple_registration_honors_private_previews_lock_and_disabled_notifications(self):
        from telethon.tl.functions.account import RegisterDeviceRequest, UnregisterDeviceRequest, UpdateDeviceLockedRequest
        client = AsyncMock(return_value=True)
        self.core.prefs = SimpleNamespace(values={'notify_preview': False})
        self.core.accounts = SimpleNamespace(services={'a': SimpleNamespace(backend=SimpleNamespace(client=client))},
                                             identities={'a': 1})
        self.core._push_token = (1, 'qa', True)
        await self.core.sync_push_registration()
        requests = [call.args[0] for call in client.await_args_list]
        self.assertEqual([type(r) for r in requests], [UpdateDeviceLockedRequest, RegisterDeviceRequest])
        self.assertEqual(requests[0].period, 0)
        self.core.prefs.values['notify_preview'] = True
        self.core.lock_record = lambda: {'enabled': True}
        await self.core.sync_push_registration()
        self.assertEqual(client.await_count, 2)
        self.core.lock_record = lambda: None
        await self.core.sync_push_registration()
        self.assertEqual(client.await_args.args[0].period, -1)
        self.core.prefs.values['notifications'] = False
        await self.core.sync_push_registration()
        self.assertIsInstance(client.await_args.args[0], UnregisterDeviceRequest)
        self.assertNotIn('a', self.core._push_registered)
        self.core.prefs.values.update(notifications=True, notify_preview=False)
        client.return_value = False
        await self.core.sync_push_registration()
        self.assertIsInstance(client.await_args.args[0], UnregisterDeviceRequest)
        self.assertNotIn('a', self.core._push_registered)
        client.return_value = True
        await self.core.sync_push_registration()
        self.assertIsInstance(client.await_args.args[0], RegisterDeviceRequest)

    async def test_apns_registration_unregistration_and_payload_hint(self):
        from telethon.tl import functions
        from tg_ascii.backend import Message
        from datetime import datetime, timezone
        calls = []

        async def client_call(request):
            calls.append(request)
            if isinstance(request, functions.messages.GetPeerDialogsRequest):
                return SimpleNamespace(dialogs=[SimpleNamespace(read_inbox_max_id=10)])
            return True

        client = AsyncMock(side_effect=client_call)
        client._self_id = 42
        client.catch_up = AsyncMock()
        client.get_input_entity = AsyncMock(return_value='input_peer')
        raw_msg = SimpleNamespace(id=15, out=False, message='Login code')
        client.get_messages = AsyncMock(return_value=raw_msg)
        converted = Message(id=15, sender='Telegram', text='Login code', time='12:00',
                            outgoing=False, date=datetime.now(timezone.utc))
        backend = SimpleNamespace(client=client, message=lambda m: converted)
        self.core.accounts = SimpleNamespace(
            current='account',
            identities={'account': 42},
            services={'account': SimpleNamespace(backend=backend, state='online', previews={}, histories={}, chats=[])},
            active=SimpleNamespace(backend=backend, state='online', previews={}, histories={}, chats=[]),
        )
        self.core.register_push_token(1, 'deadbeef01020304')
        await self.core.sync_push_registration()
        self.assertEqual(len(calls), 1)
        self.assertIsInstance(calls[0], functions.account.RegisterDeviceRequest)
        self.assertEqual(calls[0].token_type, 1)
        self.assertEqual(calls[0].token, 'deadbeef01020304')
        self.assertEqual(calls[0].other_uids, [])

        # Calling sync_push_registration again with unchanged state does not duplicate RPC.
        await self.core.sync_push_registration()
        self.assertEqual(len(calls), 1)

        # Remote push payload with peer hint routes through authenticated state to on_message.
        hint = {'user_id': 42, 'custom': {'from_id': 777000, 'msg_id': 15}}
        started, submitted = asyncio.Event(), asyncio.Event()
        async def deliver(key, peer, msg):
            self.assertEqual((key, peer, msg.text), ('account', 777000, 'Login code'))
            started.set()
            await submitted.wait()
        self.core.on_message = deliver
        fetch = asyncio.create_task(self.core._handle_push_payload(hint))
        await asyncio.sleep(0)
        client.catch_up.assert_not_awaited()
        self.core._push_ready.set()
        await asyncio.wait_for(started.wait(), 2)
        self.assertFalse(fetch.done())
        submitted.set()
        self.assertEqual(await asyncio.wait_for(fetch, 2), 0)
        client.catch_up.assert_awaited_once()

        raw_msg.id = 16
        self.assertEqual(await self.core._handle_push_payload(hint), 1)
        client.catch_up.side_effect = OSError('offline')
        self.assertEqual(await self.core._handle_push_payload(hint), 2)
        self.assertEqual(await self.core._handle_push_payload({}), 1)

        # Unregistering on logout sends UnregisterDeviceRequest.
        await self.core.unregister_push_account('account')
        self.assertEqual(len(calls), 4)
        self.assertIsInstance(calls[-1], functions.account.UnregisterDeviceRequest)
        self.assertEqual(calls[-1].token_type, 1)
        self.assertEqual(calls[-1].token, 'deadbeef01020304')


