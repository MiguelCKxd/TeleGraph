import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import zipfile
from string import Formatter

from telethon import types, functions
from tg_ascii.backend import TelegramBackend
from tg_ascii.i18n import LANGUAGES, TRANSLATIONS, set_language, tr
from tg_ascii.local_state import LocalPins
from tg_ascii.preferences import Preferences
from tg_ascii.telegram_extras import custom_entities
from tg_ascii.translations import CATALOGUES
from tg_ascii import updater
from tg_ascii.themes import resolve_theme


class SettingsTests(unittest.TestCase):
    def tearDown(self): set_language('en')

    def test_default_and_independent_theme_language_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefs = Preferences(tmp)
            self.assertEqual(prefs.values['language'], 'en')
            self.assertEqual(prefs.values['theme'], 'dark')
            self.assertEqual(prefs.values['logo_theme'], 'dark')
            self.assertFalse(prefs.values['local_pins'])
            self.assertTrue(prefs.values['inline_media'])
            for language in LANGUAGES:
                prefs.save({'language': language, 'theme': 'system', 'logo_theme': 'light'})
                saved = Preferences(tmp)
                self.assertEqual(saved.values['language'], language)
                self.assertEqual(saved.values['theme'], 'system')
                self.assertEqual(saved.values['logo_theme'], 'light')
            self.assertEqual(resolve_theme('system', 'light'), 'light')
            self.assertEqual(resolve_theme('dark', 'light'), 'dark')

    def test_local_pins_disabled_no_limit_and_account_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            pins = LocalPins(Path(tmp))
            with self.assertRaises(ValueError): pins.toggle('a', 1)
            self.assertFalse(pins.path.exists())
            # A large fixture exercises absence of any client-side cap without repeated I/O.
            pins.values['a'] = list(range(1200))
            pins.toggle('a', 5000, enabled=True)
            saved = LocalPins(Path(tmp))
            self.assertEqual(len(saved.get('a', enabled=True)), 1201)
            self.assertEqual(saved.get('a'), set())
            self.assertEqual(saved.get('b', enabled=True), set())
            saved.toggle('a', 5000, enabled=True)
            self.assertNotIn(5000, saved.get('a', True))

    def test_translation_placeholders_and_key_labels(self):
        fields = lambda value: {name for _, name, _, _ in Formatter().parse(value) if name}
        for code, catalogue in CATALOGUES.items():
            for original, translated in catalogue.items():
                self.assertEqual(fields(original), fields(translated), (code, original))
        for code in ('ru', 'pl', 'ca', 'ca-valencia', 'uk'):
            set_language(code)
            for label in ('Ajustes', 'Tu numero de telefono', 'Guardar ajustes', 'Notifications', 'Interface theme'):
                self.assertNotEqual(tr(label), TRANSLATIONS.get(label, label), (code, label))
        set_language('es')
        self.assertEqual(tr('Logo theme'), 'Tema del logo')


class ExtrasTests(unittest.IsolatedAsyncioTestCase):
    def test_custom_emoji_utf16_offsets_and_exact_fallback(self):
        text = '🙂a❤️Z'
        entity, = custom_entities(text, [(2, 4, 123, '❤️')])
        self.assertEqual((entity.offset, entity.length, entity.document_id), (3, 2, 123))
        with self.assertRaises(ValueError): custom_entities(text, [(2, 4, 123, '🔥')])
        with self.assertRaises(ValueError): custom_entities(text, [(2, 4, 123, '❤️'), (2, 4, 456, '❤️')])

    async def test_custom_send_and_native_sticker_payload(self):
        client = Mock()
        client.send_message = AsyncMock(return_value='sent')
        client.send_file = AsyncMock(return_value='sticker')
        backend = TelegramBackend(client)
        backend.message = lambda value: value
        self.assertEqual(await backend.send_custom(42, 'x🙂', [(1, 2, 999, '🙂')]), 'sent')
        args = client.send_message.call_args
        self.assertEqual(args.args, (42, 'x🙂'))
        self.assertEqual(args.kwargs['formatting_entities'][0].length, 2)
        document = Mock()
        await backend.send_sticker(42, document)
        client.send_file.assert_awaited_once_with(42, document, force_document=False, reply_to=None)

    async def test_notification_edit_does_not_overwrite_unrelated_fields(self):
        client = AsyncMock()
        client.add_event_handler = Mock()
        backend = TelegramBackend(client)
        await backend.save_notification_settings('groups', {'show_previews': False})
        request = client.call_args.args[0]
        self.assertIsInstance(request, functions.account.UpdateNotifySettingsRequest)
        self.assertIsInstance(request.peer, types.InputNotifyChats)
        self.assertFalse(request.settings.show_previews)
        self.assertIsNone(request.settings.mute_until)
        self.assertIsNone(request.settings.stories_sound)

    async def test_notification_policy_respects_specific_mute(self):
        client = AsyncMock(side_effect=[types.PeerNotifySettings(mute_until=datetime(2037, 1, 1, tzinfo=timezone.utc)), types.PeerNotifySettings(show_previews=True)])
        client.add_event_handler = Mock()
        client.get_entity.return_value = types.User(42, first_name='A')
        client.get_input_entity.return_value = types.InputPeerUser(42, 7)
        policy = await TelegramBackend(client).notification_policy(42)
        self.assertFalse(policy['enabled'])
        self.assertTrue(policy['preview'])


class UpdateTests(unittest.TestCase):
    def archive(self, folder, extra=None, target='windows-x64', version='99.0.0'):
        path = Path(folder) / 'update.zip'
        with zipfile.ZipFile(path, 'w') as bundle:
            bundle.writestr('release/release.json', json.dumps({'app': 'TG-ASCII', 'target': target, 'version': version}))
            bundle.writestr('release/TG-ASCII.exe', b'fixture, never executed')
            bundle.writestr('release/_internal/lib.dat', b'fixture')
            if extra: extra(bundle)
        return path

    def test_valid_extract_and_reject_wrong_arch_or_old_version(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(updater, 'target_id', return_value='windows-x64'):
            archive = self.archive(folder)
            target = updater.extract_archive(archive, Path(folder) / 'extracted')
            self.assertTrue((target / 'TG-ASCII.exe').is_file())
            with self.assertRaises(ValueError): updater.validate_archive(archive, 'windows-arm64')
            self.archive(folder, version='0.0.1')
            with self.assertRaises(ValueError): updater.validate_archive(archive)

    def test_linux_archive_requires_the_linux_launcher(self):
        with tempfile.TemporaryDirectory() as folder:
            target = 'linux-aarch64'
            archive = self.archive(folder, target=target)
            with self.assertRaises(ValueError):
                updater.validate_archive(archive, target)
            with zipfile.ZipFile(archive, 'a') as bundle:
                bundle.writestr('release/TG-ASCII', b'linux executable fixture')
            manifest, _, _ = updater.validate_archive(archive, target)
            self.assertEqual(manifest['target'], target)

    def test_zip_traversal_and_case_collision_rejected_before_extract(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(updater, 'target_id', return_value='windows-x64'):
            for name in ('../escape', '/absolute', 'release/../escape', 'release/C:\\escape', 'release/tg-ascii.EXE'):
                archive = self.archive(folder, lambda z: z.writestr(name, b'bad'))
                with self.assertRaises(ValueError, msg=name): updater.validate_archive(archive)
            self.assertFalse((Path(folder) / 'escape').exists())

    def test_symlink_escape_and_write_through_rejected(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(updater, 'target_id', return_value='windows-x64'):
            def add(z):
                link = zipfile.ZipInfo('release/link')
                link.external_attr = (stat.S_IFLNK | 0o777) << 16
                z.writestr(link, '../../outside')
            archive = self.archive(folder, add)
            with self.assertRaises(ValueError): updater.validate_archive(archive)
            def through(z):
                link = zipfile.ZipInfo('release/link')
                link.external_attr = (stat.S_IFLNK | 0o777) << 16
                z.writestr(link, '_internal')
                z.writestr('release/link/overwritten', b'bad')
            with self.assertRaises(ValueError): updater.validate_archive(self.archive(folder, through))

    def test_install_rolls_back_on_launch_failure_and_preserves_sessions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            current = root / 'TG-ASCII'
            current.mkdir(); (current / 'old').write_text('previous', encoding='utf-8')
            session = root / 'account.session'; session.write_bytes(b'synthetic session fixture')
            staging = root / '.tg-ascii-update-test'; staging.mkdir()
            incoming = staging / 'payload'; incoming.mkdir(); (incoming / 'new').write_text('new', encoding='utf-8')
            plan = staging / 'update-plan.json'
            plan.write_text(json.dumps({'staging': str(staging), 'current': str(current), 'incoming': str(incoming), 'backup': str(staging / 'previous'), 'pid': 12345}), encoding='utf-8')
            with patch.object(updater, 'process_alive', return_value=False), patch.object(updater.subprocess, 'Popen', side_effect=OSError('test launch failure')):
                with self.assertRaises(OSError): updater.apply_update(plan)
            self.assertEqual((current / 'old').read_text(encoding='utf-8'), 'previous')
            self.assertEqual(session.read_bytes(), b'synthetic session fixture')


if __name__ == '__main__': unittest.main()

class SynchronizationTests(unittest.TestCase):
    def test_background_edits_and_deletes_stay_in_their_account(self):
        from tg_ascii.desktop_plus import DesktopPlus
        from tg_ascii.backend import Message
        app = SimpleNamespace(ui_account='foreground', stage='ready', active=42,
                              service=SimpleNamespace(entries={'foreground': {}, 'background': {}}),
                              messages=[Message(1, 'F', 'foreground', '12:00')],
                              account_states={'background': {'active': 42, 'messages': [Message(1, 'B', 'old', '12:00')]}})
        edited = Message(1, 'B', 'edited', '12:00')
        DesktopPlus.account_change(app, ('background', 'edit', (42, edited)))
        self.assertEqual(app.account_states['background']['messages'][0].text, 'edited')
        self.assertEqual(app.messages[0].text, 'foreground')
        DesktopPlus.account_change(app, ('background', 'delete', (None, (1,))))
        self.assertEqual(app.account_states['background']['messages'], [])
        self.assertEqual(len(app.messages), 1)

    def test_unscoped_delete_does_not_delete_a_channel_message_with_same_id(self):
        from tg_ascii.desktop_plus import DesktopPlus
        from tg_ascii.backend import Message
        app = SimpleNamespace(ui_account='a', stage='ready', active=-1000000000123,
                              service=SimpleNamespace(entries={'a': {}}),
                              messages=[Message(1, 'Channel', 'keep', '12:00')], account_states={})
        DesktopPlus.account_change(app, ('a', 'delete', (None, (1,))))
        self.assertEqual(app.messages[0].text, 'keep')

    def test_gui_literal_translation_coverage_in_requested_languages(self):
        for path in (Path(__file__).resolve().parents[1] / 'tg_ascii').glob('*.py'):
            if path.name in ('ui.py', 'auth.py'): continue  # retired terminal/developer prompts
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'tr' and node.args and isinstance(node.args[0], ast.Constant)): continue
                english = TRANSLATIONS.get(node.args[0].value, node.args[0].value)
                for code in ('ru', 'pl', 'ca', 'ca-valencia', 'uk'):
                    self.assertIn(english, CATALOGUES[code], (path.name, code, english))


class HistoryRaceTests(unittest.TestCase):
    def test_delete_and_edit_are_not_overwritten_by_late_history(self):
        from tg_ascii.backend import Message
        from tg_ascii.telegram_extras import reconcile_history
        old = [Message(1, 'A', 'old', ''), Message(2, 'B', 'deleted', '')]
        edited = Message(1, 'A', 'new', '')
        events = [('edit', (42, edited)), ('delete', (None, (2,)))]
        result = reconcile_history(old, events, 42)
        self.assertEqual([(m.id, m.text) for m in result], [(1, 'new')])
        self.assertEqual(len(reconcile_history(old, [('delete', (None, (2,)))], -1000000000005)), 2)
