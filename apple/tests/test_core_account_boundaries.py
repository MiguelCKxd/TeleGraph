import asyncio
import gzip
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from telethon import types
from tg_ascii_mobile.core import Core


class CoreAccountBoundaryTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.core = Core(Path(directory.name), 'Android')
        self.core.loop.close()
        self.core.loop = asyncio.get_running_loop()
        self.first, self.second = SimpleNamespace(), SimpleNamespace()
        self.core.accounts = SimpleNamespace(current='one', services={
            'one': SimpleNamespace(backend=self.first), 'two': SimpleNamespace(backend=self.second)},
            refresh_account=AsyncMock())
        self.core.prefs = SimpleNamespace(values={})
        self.core.emit = Mock()
        self.core.keep_loaded = lambda: True

    async def test_contacts_from_old_account_never_enter_current_cache(self):
        async def contacts():
            self.core.accounts.current = 'two'
            self.core.forget_details()
            return [types.User(id=7, first_name='private contact of one')]
        self.first.contacts = contacts
        with self.assertRaisesRegex(ValueError, 'account'):
            await self.core.api_contacts()
        self.assertIsNone(self.core.cached_detail('contacts'))

    async def test_profile_change_after_read_never_mutates_the_new_account(self):
        async def profile(_):
            self.core.accounts.current = 'two'
            return {'first_name': 'old', 'last_name': '', 'about': '', 'usernames': ['old']}
        self.first.profile = profile
        self.second.update_profile = AsyncMock()
        self.second.update_username = AsyncMock()
        self.second.profile = AsyncMock(return_value={})
        with self.assertRaisesRegex(ValueError, 'account'):
            await self.core.api_save_my_profile('new', '', '', 'new')
        self.second.update_profile.assert_not_called()
        self.second.update_username.assert_not_called()

    async def test_profile_change_stops_between_two_mutations(self):
        self.first.profile = AsyncMock(return_value={'first_name': 'old', 'usernames': ['old']})
        async def update(*args):
            self.core.accounts.current = 'two'
        self.first.update_profile = update
        self.first.update_username = AsyncMock()
        self.second.update_username = AsyncMock()
        self.second.profile = AsyncMock(return_value={})
        with self.assertRaisesRegex(ValueError, 'account'):
            await self.core.api_save_my_profile('new', '', '', 'new')
        self.first.update_username.assert_not_called()
        self.second.update_username.assert_not_called()

    async def test_header_rejects_previous_account_and_older_same_chat_answer(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow(peer):
            entered.set()
            await release.wait()
            return {'status': 'obsolete'}
        self.first.chat_header = slow
        pending = asyncio.create_task(self.core.refresh_header(42))
        await entered.wait()
        self.first.chat_header = AsyncMock(return_value={'status': 'fresh'})
        await self.core.refresh_header(42)
        release.set()
        await pending
        self.assertEqual(self.core.emit.call_args_list, [(('header', {'peer': 42, 'status': 'fresh'}),)])
        self.core.emit.reset_mock()
        async def changed(peer):
            self.core.accounts.current = 'two'
            return {'status': 'private one'}
        self.first.chat_header = changed
        await self.core.refresh_header(42)
        self.core.emit.assert_not_called()

    async def test_save_to_saved_never_uses_second_account_after_me_lookup(self):
        async def me():
            self.core.accounts.current = 'two'
            return SimpleNamespace(id=101)
        self.first.client = SimpleNamespace(get_me=me)
        self.second.forward_message = AsyncMock()
        with self.assertRaisesRegex(ValueError, 'account'):
            await self.core.api_save_to_saved(42, 8)
        self.second.forward_message.assert_not_called()

    async def test_mark_read_never_mutates_second_account(self):
        async def latest(*args, **kwargs):
            self.core.accounts.current = 'two'
            return [SimpleNamespace(id=31)]
        self.first.client = SimpleNamespace(get_messages=latest)
        self.second.mark_read = AsyncMock()
        self.second.set_chat_unread = AsyncMock()
        with self.assertRaisesRegex(ValueError, 'account'):
            await self.core.api_mark_read_chat(42)
        self.second.mark_read.assert_not_called()

    async def test_secret_discard_result_does_not_remove_other_accounts_chat(self):
        async def discard(*args, **kwargs):
            self.core.accounts.current = 'two'
        self.first.discard_secret_chat = discard
        self.core.refresh_chats = AsyncMock()
        marker = object()
        self.core.histories[42] = [marker]
        await self.core.api_secret_discard(42)
        self.assertEqual(self.core.histories[42], [marker])
        self.core.refresh_chats.assert_not_called()

    async def test_sticker_expansion_limit_keeps_no_partial_animation(self):
        expanded = b' ' * (4 * 1024 * 1024 + 1)
        data = gzip.compress(expanded)
        self.first.client = SimpleNamespace(download_media=AsyncMock(return_value=data))
        self.core.sticker_store = {19: SimpleNamespace(id=19, mime_type='application/x-tgsticker', size=len(data))}
        with self.assertRaisesRegex(ValueError, 'large'):
            await self.core.sticker_animation(19)
        self.assertEqual(list((self.core.root / 'mobile-stickers').iterdir()), [])

    async def test_late_bot_button_does_not_inject_old_message_into_current_account(self):
        async def activate(*args):
            self.core.accounts.current = 'two'
            return {'message': SimpleNamespace(id=21)}
        self.first.activate_bot_button = activate
        self.core.message_json = lambda message: {'id': message.id}
        self.core.on_message = Mock()
        with self.assertRaisesRegex(ValueError, 'account'):
            await self.core.api_bot_button(42, 8, 0, 0, '00')
        self.core.on_message.assert_not_called()

    async def test_resume_of_previous_account_does_not_publish_connection(self):
        self.core.stage = 'ready'
        self.core.server = SimpleNamespace(ensure=AsyncMock(return_value=4321))
        finished = asyncio.Event()
        async def recover(**kwargs):
            self.core.accounts.current = 'two'
            finished.set()
        self.core.accounts.services['one'].recovery = SimpleNamespace(ensure=recover, state='offline')
        await self.core.resume()
        await finished.wait()
        await asyncio.sleep(0)
        self.core.emit.assert_not_called()

    async def test_wallpaper_sync_cannot_apply_after_account_switch(self):
        wallpaper = SimpleNamespace(id=1, creator=True, document=object(), pattern=False)
        self.first.client = AsyncMock(return_value=SimpleNamespace(wallpapers=[wallpaper]))
        self.core.appearance = Mock(return_value={'background_sync': True, 'background': 'existing'})
        async def image(*args, **kwargs):
            self.core.accounts.current = 'two'
            return 'old-account.jpg'
        self.core.wallpaper_image = image
        self.core.save_appearance = Mock()
        with self.assertRaisesRegex(ValueError, 'account'):
            await self.core.api_sync_background()
        self.core.save_appearance.assert_not_called()

    async def test_avatar_revision_comes_from_its_owner_not_current_account(self):
        target = types.User(id=7, photo=types.UserProfilePhoto(photo_id=101, dc_id=1))
        self.core._avatar_slots = asyncio.Semaphore(4)
        self.core.photo_id = lambda peer: 201 if self.core.account == 'two' else 101
        async def download(target, file, download_big):
            Path(file).write_bytes(b'old account photo')
            self.core.accounts.current = 'two'
            return file
        self.first.client = SimpleNamespace(download_profile_photo=download)
        path = self.core.root / '7.jpg'
        await self.core._download_avatar(self.first, target, path, path.with_suffix('.none'), False)
        self.assertEqual(path.with_suffix('.id').read_text(), '101')

    async def test_logo_and_background_reject_account_change_while_preparing_image(self):
        for method in ('api_set_logo_photo', 'api_set_background'):
            with self.subTest(method=method):
                self.core.accounts.current = 'one'
                source = self.core.staging_path('picked.jpg')
                source.write_bytes(b'input')
                created = []
                def image(path, folder=None):
                    folder = folder or self.core.root / 'mobile-backgrounds'
                    folder.mkdir(exist_ok=True)
                    target = folder / 'a.jpg'
                    target.write_bytes(b'prepared')
                    created.append(target)
                    self.core.accounts.current = 'two'
                    return target.name
                self.core.background_image = image
                self.core.appearance = Mock(return_value={})
                self.core.save_appearance = Mock()
                with self.assertRaisesRegex(ValueError, 'account'):
                    await getattr(self.core, method)(source.name)
                self.assertFalse(created[0].exists())
                self.assertFalse(source.exists())
                self.core.save_appearance.assert_not_called()

    async def test_outbox_host_follows_recreated_accounts_after_restart(self):
        from tg_ascii_mobile.core import _OutboxHost
        host = _OutboxHost(self.core)
        replacement = SimpleNamespace()
        self.core.accounts = replacement
        self.assertIs(host.service, replacement)

    async def test_shutdown_stops_outbox_worker_and_resets_only_inflight_for_retry(self):
        from tg_ascii.outbox import Outbox, Pending
        from tg_ascii_mobile.core import _OutboxHost
        self.core.accounts.root = self.core.root
        self.core.outbox = Outbox(_OutboxHost(self.core))
        item = Pending('one', 42, text='pending', state='sending', random_ids=[42])
        self.core.outbox.items.append(item)
        self.core.outbox.inflight[('one', 42)] = item
        self.core.outbox.timer = self.core.loop.call_later(60, lambda: None)
        timer = self.core.outbox.timer
        task = self.core.outbox.app.worker.submit(asyncio.sleep(60), Mock(), Mock())
        self.core.siri_vocabulary.sync = Mock()
        self.core.close_media_requests = AsyncMock()
        self.core.cancel_current_voice = AsyncMock()
        self.core.save_snapshot = AsyncMock()
        self.core.close_call_manager = AsyncMock()
        self.core.accounts.close = AsyncMock()
        try:
            await self.core.shutdown()
            self.assertTrue(task.cancelled())
            self.assertTrue(timer.cancelled())
            self.assertTrue(self.core.outbox.app.closed)
            self.assertFalse(self.core.outbox.inflight)
            self.assertEqual((item.state, item.random_ids), ('waiting', [42]))
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            timer.cancel()
