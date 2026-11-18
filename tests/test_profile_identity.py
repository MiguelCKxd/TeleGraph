"""Local profile edits never leak to Telegram or another account's dialog."""
import asyncio
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image
from telethon import types as t

from tg_ascii.backend import TelegramBackend
from tg_ascii.desktop_features import DesktopFeatures
from tg_ascii.profile_customization import (
    apply_profile_identity, apply_profile_photo, clear_design, configure_design,
    load_design, local_photo, overlay_profile, validate,
)


class LocalIdentityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.client = AsyncMock()
        self.client.add_event_handler = Mock()
        self.client.return_value = True
        self.backend = TelegramBackend(self.client)
        self.backend.account_profile.remember(t.User(10, first_name='Server', premium=True))
        configure_design(self.backend, self.root, 'account')

    def image(self, name='input.png', color='red'):
        path = self.root / name
        Image.new('RGB', (12, 12), color).save(path)
        return path

    async def test_local_identity_is_durable_and_does_not_change_public_identifiers(self):
        await apply_profile_identity(self.backend, ' Local 👍 ', ' Persona ', 'My\nbiography', False)
        self.client.assert_not_awaited()
        saved = load_design(self.backend.profile_design_path, 'account')
        self.assertEqual(saved['identity']['first_name'], 'Local 👍')
        profile = {'id': 10, 'name': 'Server', 'username': 'public_user', 'phone': '123', 'premium': True}
        displayed = overlay_profile(self.backend, profile)
        self.assertEqual(displayed['name'], 'Local 👍 Persona')
        self.assertEqual(displayed['about'], 'My\nbiography')
        for field in ('username', 'phone', 'premium'):
            self.assertEqual(displayed[field], profile[field])
        self.assertEqual(self.backend.account_profile.user.first_name, 'Server')
        self.assertEqual(overlay_profile(self.backend, {'id': 20}), {'id': 20})
        self.assertEqual(load_design(self.backend.profile_design_path, 'other'), {})

    async def test_failed_native_identity_keeps_override_then_success_removes_only_identity(self):
        await apply_profile_identity(self.backend, 'Local', '', '', False)
        await apply_profile_photo(self.backend, self.image(), False)
        photo = local_photo(self.backend, 10)
        self.client.side_effect = ConnectionError('offline')
        with self.assertRaises(ConnectionError):
            await apply_profile_identity(self.backend, 'Public', 'New', 'Biography')
        self.assertIn('identity', self.backend.local_profile_design)
        self.client.side_effect = None
        self.client.return_value = t.User(10, first_name='Public', last_name='New', premium=True)
        await apply_profile_identity(self.backend, ' Public ', ' New ', 'Biography')
        request = self.client.call_args.args[0]
        self.assertEqual(request.first_name, 'Public')
        self.assertEqual(request.last_name, 'New')
        self.assertNotIn('identity', self.backend.local_profile_design)
        self.assertEqual(local_photo(self.backend, 10), photo)
        self.assertEqual(self.backend.account_profile.user.first_name, 'Public')
        self.assertTrue(self.backend.account_profile.premium)

    async def test_local_photo_owns_a_verified_copy_and_both_avatar_views_use_it(self):
        original = self.image()
        await apply_profile_photo(self.backend, original, False)
        photo = local_photo(self.backend, 10)
        self.assertTrue(Path(photo).is_file())
        self.assertNotEqual(Path(photo), original)
        original.unlink()
        for peer in ('me', 'self', 10, t.InputPeerSelf(), t.PeerUser(10)):
            self.assertEqual(await self.backend.avatar(peer, self.root / 'thumb.jpg'), photo)
            self.assertEqual(await self.backend.profile_photo(peer, self.root / 'full.jpg'), photo)
        self.client.download_profile_photo.assert_not_awaited()
        self.client.assert_not_awaited()
        configure_design(self.backend, self.root, 'account')
        self.assertEqual(local_photo(self.backend, 10), photo)
        with Image.open(photo) as result:
            self.assertEqual(result.getpixel((0, 0)), (255, 0, 0))

    async def test_local_photo_is_account_scoped_and_other_peers_keep_real_photo(self):
        await apply_profile_photo(self.backend, self.image(), False)
        for peer in (20, t.PeerChannel(10), 'another_username', None):
            self.assertIsNone(local_photo(self.backend, peer))
        self.client.download_profile_photo.return_value = 'server-photo'
        self.assertEqual(await self.backend.avatar(20, self.root / 'other.jpg'), 'server-photo')
        configure_design(self.backend, self.root, 'another-account')
        self.assertIsNone(local_photo(self.backend, 'me'))

    async def test_replacing_photo_and_restoring_profile_reclaim_only_owned_images(self):
        original = self.image()
        await apply_profile_photo(self.backend, original, False)
        old = Path(local_photo(self.backend, 10))
        await apply_profile_photo(self.backend, self.image('second.png', 'blue'), False)
        latest = Path(local_photo(self.backend, 10))
        self.assertFalse(old.exists())
        self.assertTrue(latest.exists())
        await apply_profile_identity(self.backend, 'Local', '', '', False)
        clear_design(self.backend)
        self.assertFalse(latest.exists())
        self.assertTrue(original.is_file())
        self.assertEqual(load_design(self.backend.profile_design_path, 'account'), {})
        self.client.assert_not_awaited()

    async def test_native_photo_failure_preserves_local_copy_and_success_removes_it(self):
        original = self.image()
        await apply_profile_photo(self.backend, original, False)
        local = Path(local_photo(self.backend, 10))
        self.backend.update_photo = AsyncMock(side_effect=ConnectionError)
        with self.assertRaises(ConnectionError):
            await apply_profile_photo(self.backend, original, True)
        self.assertTrue(local.exists())
        self.assertEqual(local_photo(self.backend, 10), str(local))
        self.backend.update_photo = AsyncMock(return_value=True)
        await apply_profile_photo(self.backend, original, True)
        self.backend.update_photo.assert_awaited_once_with(original)
        self.assertFalse(local.exists())
        self.assertIsNone(local_photo(self.backend, 10))

    async def test_copy_is_off_event_loop_and_corrupt_image_preserves_prior_photo(self):
        original = self.image()
        from tg_ascii.profile_customization import _copy_photo
        worker_threads = []
        def copy(*args):
            worker_threads.append(threading.get_ident())
            return _copy_photo(*args)
        with patch('tg_ascii.profile_customization._copy_photo', side_effect=copy):
            await apply_profile_photo(self.backend, original, False)
        self.assertNotEqual(worker_threads, [threading.get_ident()])
        old = local_photo(self.backend, 10)
        broken = self.root / 'broken.png'
        broken.write_bytes(b'not an image')
        with self.assertRaises(OSError):
            await apply_profile_photo(self.backend, broken, False)
        self.assertEqual(local_photo(self.backend, 10), old)
        self.assertEqual([p.name for p in Path(old).parent.iterdir()], [Path(old).name])

    async def test_cancelled_copy_reclaims_late_result_without_publishing_it(self):
        ready, release = threading.Event(), threading.Event()
        copied = self.root / 'unpublished.image'
        create_task, workers = asyncio.create_task, []
        def remember_worker(coroutine):
            task = create_task(coroutine)
            workers.append(task)
            return task
        def copy(*_):
            ready.set()
            release.wait(3)
            copied.write_bytes(b'copy')
            return copied
        with patch('tg_ascii.profile_customization._copy_photo', side_effect=copy), \
             patch('tg_ascii.profile_customization.asyncio.create_task', side_effect=remember_worker):
            task = create_task(apply_profile_photo(self.backend, 'source', False))
            await asyncio.to_thread(ready.wait, 3)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            release.set()
            await asyncio.gather(*workers)
        self.assertEqual(self.backend.local_profile_design, {})
        self.assertFalse(copied.exists())

    async def test_imported_paths_and_invalid_text_never_reach_server_or_external_files(self):
        for field, value in [('photo', '/tmp/arbitrary.png'), ('photo', '../arbitrary.image'),
                             ('identity', {'first_name': '', 'last_name': '', 'about': ''}),
                             ('identity', {'first_name': 'Name', 'last_name': '', 'about': '\x00'}),
                             ('identity', {'first_name': 'Name', 'last_name': '', 'about': '', 'username': 'spoof'})]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate(field, value)
        self.backend.local_profile_design = {'photo': '../arbitrary.image'}
        self.assertIsNone(local_photo(self.backend, 10))
        self.client.assert_not_awaited()

class ProfileDialogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.backend = NS(profile=AsyncMock(return_value={
            'id': 10, 'first_name': 'Name', 'last_name': '', 'about': '', 'username': 'public'}),
            update_username=AsyncMock(), update_profile=AsyncMock(), update_photo=AsyncMock())
        self.pending, self.buttons = [], {}
        self.window = Mock()
        self.window.winfo_exists.return_value = True
        self.app = NS(busy=False, demo=False, ui_account='a', service=NS(backend=self.backend),
            preferences={'sync_customizations': False}, status=Mock(), dialog=Mock(return_value=(self.window, Mock())),
            field=lambda parent, label, value: NS(get=lambda:value), load_avatars=Mock(), refresh_header=Mock())
        self.app.call = lambda operation, done, status: self.pending.append((operation, done))
        def button(parent, text, command, **kwargs):
            self.buttons[text] = command
            return Mock()
        for name, replacement in [('ttk.Button', button), ('ttk.Label', Mock()), ('ttk.Separator', Mock()),
                                  ('tk.StringVar', Mock()), ('scrollable', lambda parent:parent), ('tr', lambda text:text)]:
            self.enterContext(patch('tg_ascii.desktop_features.' + name, replacement))
        self.addCleanup(self.close_pending)

    def close_pending(self):
        for operation, _ in self.pending:
            operation.close()

    async def load(self):
        DesktopFeatures.edit_profile(self.app)
        operation, done = self.pending.pop(0)
        done(await operation)

    async def test_profile_load_after_account_switch_never_opens_stale_dialog(self):
        DesktopFeatures.edit_profile(self.app)
        self.app.ui_account = 'b'
        operation, done = self.pending.pop(0)
        done(await operation)
        self.app.dialog.assert_not_called()

    async def test_actions_after_account_switch_or_dialog_close_are_ignored(self):
        await self.load()
        self.app.ui_account = 'b'
        for button in self.buttons.values():
            button()
        self.assertEqual(self.pending, [])
        self.app.ui_account = 'a'
        self.window.winfo_exists.return_value = False
        for button in self.buttons.values():
            button()
        self.assertEqual(self.pending, [])

    async def test_file_picker_rechecks_account_before_saving(self):
        await self.load()
        def select(**kwargs):
            self.app.ui_account = 'b'
            return '/tmp/image.png'
        with patch('tg_ascii.desktop_features.filedialog.askopenfilename', side_effect=select):
            self.buttons['Cambiar foto']()
        self.assertEqual(self.pending, [])

    async def test_save_uses_current_sync_setting_and_captured_backend(self):
        await self.load()
        self.backend.local_profile_design = {}
        self.buttons['Guardar nombre y biografia']()
        operation, done = self.pending.pop(0)
        done(await operation)
        self.backend.update_profile.assert_not_awaited()
        self.assertEqual(self.backend.local_profile_design['identity']['first_name'], 'Name')
        self.app.preferences['sync_customizations'] = True
        self.buttons['Guardar nombre y biografia']()
        operation, done = self.pending.pop(0)
        done(await operation)
        self.backend.update_profile.assert_awaited_once_with('Name', '', '')
        self.assertNotIn('identity', self.backend.local_profile_design)

    async def test_username_remains_explicit_server_action_in_local_mode(self):
        await self.load()
        self.buttons['Cambiar nombre de usuario']()
        operation, done = self.pending.pop(0)
        self.app.ui_account = 'b'
        done(await operation)
        self.backend.update_username.assert_awaited_once_with('public')
        self.app.status.set.assert_not_called()


if __name__ == '__main__':
    unittest.main()
