import ast
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from telethon import types, functions
from telethon.crypto import AuthKey
from telethon.sessions import SQLiteSession
from tg_ascii.accounts import Accounts
from tg_ascii.backend import Chat, Message, TelegramBackend
from tg_ascii.desktop import Desktop
from tg_ascii.i18n import TRANSLATIONS, set_language, tr
from tg_ascii.preferences import Preferences, write_json
from tg_ascii.telegram_features import matches_folder


class PreferencesTests(unittest.TestCase):
    def tearDown(self):
        set_language('es')

    def test_language_and_preferences_survive_restart_without_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            preferences = Preferences(folder)
            preferences.save({'language': 'en', 'font_size': 15, 'ascii_text': False, 'password': 'must-not-save'})
            restored = Preferences(folder)
            self.assertEqual(restored.values['language'], 'en')
            self.assertEqual(restored.values['font_size'], 15)
            stored = (Path(folder) / 'preferences.json').read_text(encoding='utf-8')
            self.assertEqual(json.loads(stored)['quick_reaction'], '👍')
            self.assertNotIn('password', stored)
            if os.name == 'posix':
                self.assertEqual((Path(folder) / 'preferences.json').stat().st_mode & 0o777, 0o600)
            set_language(restored.values['language'])
            self.assertEqual(tr('Guardar ajustes'), 'Save settings')

    def test_all_literal_translation_keys_have_english(self):
        missing = set()
        for path in (Path(__file__).resolve().parents[1] / 'tg_ascii').glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'tr' and node.args:
                    from tg_ascii.translations import CATALOGUES
                    if isinstance(node.args[0], ast.Constant) and node.args[0].value not in TRANSLATIONS and node.args[0].value not in CATALOGUES['ru']:
                        missing.add(node.args[0].value)
        self.assertEqual(missing, set())

    def test_corrupt_settings_use_defaults_and_demo_writes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'preferences.json').write_text('{bad', encoding='utf-8')
            self.assertEqual(Preferences(folder).values['font_size'], 12)
            demo = Preferences(Path(folder) / 'unused', demo=True)
            demo.save({'language': 'en'})
            self.assertFalse(demo.path.exists())


class TextEncodingTests(unittest.TestCase):
    def test_text_file_io_chooses_encoding_instead_of_windows_default(self):
        # Windows Python 3.13 commonly uses cp1252. UTF-8 JSON containing
        # emoji can therefore fail even when the same test passes on macOS.
        root = Path(__file__).resolve().parents[1]
        missing = []
        for directory in ('tg_ascii', 'tests', 'tools'):
            for path in (root / directory).glob('*.py'):
                for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                        continue
                    if node.func.attr not in ('read_text', 'write_text'):
                        continue
                    position = 0 if node.func.attr == 'read_text' else 1
                    encoding = next((kw.value for kw in node.keywords if kw.arg == 'encoding'), None)
                    if encoding is None and len(node.args) > position:
                        encoding = node.args[position]
                    if encoding is None or (isinstance(encoding, ast.Constant) and encoding.value is None):
                        missing.append(f'{path.relative_to(root)}:{node.lineno}')
        self.assertEqual(missing, [], 'Text file encoding must be explicit')


class FakeService:
    """Fake network plus real SQLite session for the persistence test."""
    def __init__(self, demo=False, root=None, session_path=None):
        self.path = Path(session_path)
        self.client = SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(id=1 if self.path.parent == root else 2, first_name='Test', last_name='Account')))
        self.backend = None
        self.config_warning = False
        self.credentials = (12345, 'a' * 32)
        self.on_message = None
        self.closed = False
        self.session = None

    async def connect(self, *args, **kwargs):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.session = SQLiteSession(str(self.path))
        if self.session.auth_key is None:
            self.session.auth_key = AuthKey(bytes(range(256)))
            self.session.save()
        self.backend = SimpleNamespace(send=AsyncMock(return_value='sent'))
        return 'ready'

    async def close(self):
        self.closed = True
        if self.session: self.session.close()


class AccountTests(unittest.IsolatedAsyncioTestCase):
    async def test_sessions_persist_and_all_accounts_reconnect_separately(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manager = Accounts(root=root, factory=FakeService)
            await manager.connect()
            original = manager.services['account']
            await manager.add()
            second_id = manager.current
            second = manager.services[second_id]
            self.assertNotEqual(original.path, second.path)
            self.assertFalse(original.closed)
            await manager.select('account')
            self.assertFalse(second.closed)
            self.assertIs(manager.backend, original.backend)
            event = Mock()
            manager.on_message = event
            second.on_message(42, 'background')
            event.assert_called_once_with(second_id, 42, 'background')
            await manager.close()
            self.assertTrue(original.closed and second.closed)
            reopened = Accounts(root=root, factory=FakeService)
            await reopened.connect()
            self.assertEqual(set(reopened.services), {'account', second_id})
            self.assertEqual(reopened.services[second_id].session.auth_key.key, bytes(range(256)))
            self.assertEqual(reopened.services['account'].path, root / 'account')
            self.assertNotIn('api_hash', (root / 'accounts.json').read_text(encoding='utf-8'))
            await reopened.close()

    async def test_registry_rejects_session_path_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_json(root / 'accounts.json', {'active': '../outside', 'accounts': {'../outside': {'label': 'bad'}}})
            manager = Accounts(root=root, factory=FakeService)
            self.assertEqual(list(manager.entries), [manager.current])
            self.assertRegex(manager.current, r'^[a-f0-9]{32}$')
            self.assertTrue(manager.service(manager.current).path.is_relative_to(root))

    async def test_duplicate_account_does_not_replace_original_session(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = Accounts(root=folder, factory=FakeService)
            await manager.connect()
            first = manager.services['account']
            original_identity = manager.identities['account']
            pending = 'b' * 32
            service = manager.service(pending)
            service.client.get_me.return_value.id = original_identity
            await service.connect()
            with self.assertRaises(ValueError):
                await manager.register(pending)
            self.assertNotIn(pending, manager.entries)
            self.assertFalse(first.closed)
            self.assertTrue(service.closed)
            await manager.close()

    async def test_cancelled_add_disconnects_only_pending_account(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = Accounts(root=folder, factory=FakeService)
            await manager.connect()
            first = manager.services['account']
            manager.current = 'c' * 32
            pending = manager.service(manager.current)
            await pending.connect()
            await manager.select('account')
            self.assertTrue(pending.closed)
            self.assertFalse(first.closed)
            self.assertEqual(manager.current, 'account')
            await manager.close()

    async def test_background_events_never_appear_in_foreground_chat(self):
        ui = object.__new__(Desktop)
        ui.ui_account, ui.stage = 'one', 'ready'
        ui.service = SimpleNamespace(entries={'one': {}, 'two': {}})
        ui.account_unread = {}
        ui.account_states = {'two': {'active': 42, 'messages': []}}
        ui.incoming, ui.update_account_picker = Mock(), Mock()
        message = Message(1, 'Alex', 'private to account two', '12:00')
        ui.account_event(('two', 42, message))
        ui.incoming.assert_not_called()
        self.assertEqual(ui.account_states['two']['messages'], [message])
        self.assertEqual(ui.account_unread['two'], 1)


class FeatureRpcTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = AsyncMock()
        self.client.add_event_handler = Mock()
        self.client.get_input_entity.side_effect = lambda peer: types.InputPeerUser(peer, 123)
        self.backend = TelegramBackend(self.client)

    async def test_folder_rename_and_membership_preserve_unloaded_rules(self):
        folder = types.DialogFilter(5, types.TextWithEntities('Work', []), [types.InputPeerUser(7, 9)],
                                    [types.InputPeerUser(8, 9)], [types.InputPeerUser(9, 9)], groups=True, exclude_muted=True)
        self.client.return_value=SimpleNamespace(filters=[folder],tags_enabled=False)
        renamed = await self.backend.save_folder('Trabajo', None, folder)
        self.assertTrue(renamed.groups and renamed.exclude_muted)
        self.assertEqual(renamed.pinned_peers[0].user_id, 7)
        self.assertEqual(renamed.exclude_peers[0].user_id, 9)
        self.assertEqual(folder.title.text, 'Work')
        changed = await self.backend.folder_membership(folder, 10, True)
        self.assertEqual([p.user_id for p in changed.include_peers], [8, 10])
        self.assertEqual([p.user_id for p in folder.include_peers], [8])
        self.assertIsInstance(self.client.call_args.args[0], functions.messages.UpdateDialogFilterRequest)

    def test_folder_rules_include_exclude_and_shared_folders(self):
        folder = types.DialogFilter(5, types.TextWithEntities('Work', []), [], [types.InputPeerUser(1, 0)], [types.InputPeerUser(2, 0)], groups=True)
        self.assertTrue(matches_folder(Chat(1, 'Explicit'), folder))
        self.assertFalse(matches_folder(Chat(2, 'Excluded', kind='group'), folder))
        self.assertTrue(matches_folder(Chat(3, 'Group', kind='group'), folder))
        self.assertFalse(matches_folder(Chat(4, 'Person'), folder))
        shared = types.DialogFilterChatlist(6, types.TextWithEntities('Shared', []), [], [types.InputPeerUser(1, 0)])
        self.assertTrue(matches_folder(Chat(1, 'Shared member'), shared))

    async def test_contact_import_normalizes_phone_and_does_not_send(self):
        self.client.return_value = SimpleNamespace(retry_contacts=[], users=[types.User(5, first_name='Test')])
        await self.backend.add_contact('Test', 'Friend', '+56 9 1234 5678')
        request = self.client.call_args.args[0]
        self.assertIsInstance(request, functions.contacts.ImportContactsRequest)
        self.assertEqual(request.contacts[0].phone, '+56912345678')
        self.client.send_message.assert_not_called()

    async def test_pin_targets_explicit_peer_and_group_returns_missing_invites(self):
        await self.backend.pin(42, True)
        request = self.client.call_args.args[0]
        self.assertEqual(request.peer.peer.user_id, 42)
        self.assertTrue(request.pinned)
        self.client.return_value = SimpleNamespace(updates=SimpleNamespace(chats=[types.Chat(5, 'New', types.ChatPhotoEmpty(), 2, None, 1)]), missing_invitees=[object()])
        chat, missing = await self.backend.create_group('New', [42, 43])
        self.assertEqual(chat.id, -5)
        self.assertEqual(missing, 1)

    async def test_profile_updates_and_username_change_are_separate(self):
        await self.backend.update_profile('First', 'Last', 'Bio 👋')
        request = self.client.call_args.args[0]
        self.assertIsInstance(request, functions.account.UpdateProfileRequest)
        self.assertEqual(request.about, 'Bio 👋')
        await self.backend.update_username('@new_name')
        self.assertEqual(self.client.call_args.args[0].username, 'new_name')

    async def test_story_pages_expand_skipped_items_and_views_are_explicit(self):
        media = types.MessageMediaPhoto(photo=types.PhotoEmpty(1))
        first = types.StoryItem(1, None, None, media, caption='Hola')
        second = types.StoryItem(2, None, None, media, caption='World')
        page1 = types.stories.AllStories(2, 'next-page', [types.PeerStories(types.PeerUser(42), [types.StoryItemSkipped(1, None, None)])], [], [types.User(42, first_name='Alex')], types.StoriesStealthMode(), has_more=True)
        page2 = types.stories.AllStories(2, 'last', [types.PeerStories(types.PeerUser(42), [second])], [], [types.User(42, first_name='Alex')], types.StoriesStealthMode(), has_more=False)
        self.client.side_effect = [page1, SimpleNamespace(stories=[first]), page2]
        stories = await self.backend.stories()
        self.assertEqual([s.id for s in stories], [1, 2])
        self.assertEqual(stories[0].name, 'Alex')
        calls = [c.args[0] for c in self.client.call_args_list]
        self.assertEqual(calls[2].state, 'next-page')
        self.assertTrue(calls[2].next)
        self.assertFalse(any(isinstance(call, functions.stories.ReadStoriesRequest) for call in calls))
        self.client.side_effect = None
        await self.backend.view_story(stories[0])
        self.assertIsInstance(self.client.call_args_list[-2].args[0], functions.stories.ReadStoriesRequest)
        self.assertEqual(self.client.call_args.args[0].id, [1])

    async def test_missing_media_and_thumbnail_download(self):
        self.client.get_messages.return_value = None
        with self.assertRaises(ValueError):
            await self.backend.media_message(42, 7)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'preview.jpg'
            self.client.download_media.return_value = str(target)
            await self.backend.download_media(SimpleNamespace(thumbs=[types.PhotoSize('m',100,100,2048)]), target, thumbnail=True)
            self.assertEqual(self.client.download_media.call_args.kwargs['thumb'], 'm')
            self.client.download_media.return_value = None
            with self.assertRaises(ValueError):
                await self.backend.download_media(object(), target)


class DropTests(unittest.TestCase):
    def test_drop_stages_unicode_path_without_sending(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'archivo con espacios ñ.txt'
            path.write_text('test', encoding='utf-8')
            ui = object.__new__(Desktop)
            ui.busy, ui.active, ui.stage = False, 42, 'ready'
            from tg_ascii.backend import Chat
            ui.demo=False;ui.chats=[Chat(42,'Synthetic recipient')]
            ui.status, ui.update_attachment, ui.send = Mock(), Mock(), Mock()
            ui.ui_account = 'test-account'
            ui.attachment = None
            ui.dropped_files([str(path)])
            self.assertEqual(ui.attachment, path)
            ui.send.assert_not_called()
            ui.busy = True
            ui.dropped_files(['unavailable'])
            self.assertEqual(ui.attachment, path)

    def test_unicode_and_emoji_are_preserved_unless_ascii_is_selected(self):
        ui = object.__new__(Desktop)
        ui.preferences = SimpleNamespace(values={'ascii_text': False})
        self.assertEqual(ui.text_display('Hola 👋 café'), 'Hola 👋 café')
        ui.preferences.values['ascii_text'] = True
        self.assertTrue(ui.text_display('Hola 👋 café').isascii())
