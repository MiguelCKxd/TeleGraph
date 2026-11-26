import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

from PIL import Image
from telethon import types as t

from tg_ascii import account_photos as photos


class AccountPhotoTests(unittest.IsolatedAsyncioTestCase):
    async def test_photo_is_saved_and_removed_when_the_account_has_none(self):
        with tempfile.TemporaryDirectory() as root:
            async def download(user, file, download_big):
                Image.new('RGB', (8, 8), 'red').save(file, 'JPEG'); return file
            client = NS(download_profile_photo=mock.AsyncMock(side_effect=download))
            me = NS(photo=t.UserProfilePhoto(photo_id=1, dc_id=2))
            self.assertTrue(await photos.remember(root, 'abc', client, me))
            self.assertTrue(photos.photo_path(root, 'abc').is_file())
            self.assertFalse(await photos.remember(root, 'abc', client, NS(photo=t.UserProfilePhotoEmpty())))
            self.assertFalse(photos.photo_path(root, 'abc').exists())

    async def test_failures_never_raise(self):
        with tempfile.TemporaryDirectory() as root:
            client = NS(download_profile_photo=mock.AsyncMock(side_effect=ConnectionError))
            self.assertFalse(await photos.remember(root, 'abc', client, NS(photo=t.UserProfilePhoto(photo_id=1, dc_id=2))))
            self.assertEqual(list((Path(root) / photos.FOLDER).iterdir()), [])

    async def test_cancelled_download_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as root:
            started = asyncio.Event()
            async def download(user, file, download_big):
                Path(file).write_bytes(b'partial')
                started.set()
                await asyncio.Event().wait()
            task = asyncio.create_task(photos.remember(root, 'abc', NS(download_profile_photo=download),
                                       NS(photo=t.UserProfilePhoto(photo_id=1, dc_id=2))))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(list((Path(root) / photos.FOLDER).iterdir()), [])

    async def test_repeated_registration_coalesces_photo_and_close_cancels_it(self):
        from tg_ascii.accounts import Accounts, AccountsView
        with tempfile.TemporaryDirectory() as root:
            accounts = Accounts(root=root)
            view = AccountsView(accounts)
            started, finish = asyncio.Event(), asyncio.Event()
            async def download(user, file, download_big):
                started.set()
                await finish.wait()
                Path(file).write_bytes(b'photo')
                return file
            client = NS(download_profile_photo=mock.AsyncMock(side_effect=download))
            me = NS(id=7, photo=t.UserProfilePhoto(photo_id=1, dc_id=2))
            accounts._remember_photo('account', client, me)
            await started.wait()
            view._remember_photo('account', client, me)
            self.assertEqual(client.download_profile_photo.await_count, 1)
            finish.set()
            await asyncio.gather(*(value[1] for value in accounts._photo_tasks.values()))
            await asyncio.sleep(0)
            view._remember_photo('account', client, me)
            self.assertEqual(client.download_profile_photo.await_count, 1)
            finish.clear(); started.clear()
            me.photo = t.UserProfilePhoto(photo_id=2, dc_id=2)
            view._remember_photo('account', client, me)
            await started.wait()
            await accounts.close()
            self.assertFalse(accounts._photo_tasks)
            self.assertEqual([path.name for path in (Path(root) / photos.FOLDER).iterdir()], ['account.jpg'])

    def test_chooser_uses_placeholder_without_own_photo(self):
        with tempfile.TemporaryDirectory() as root:
            shown = photos.display_path(root, 'abc', 'Ana López', 7, Path(root) / 'cache')
            self.assertIn('default-avatar-', shown)
            image = photos.round_image(shown, 40)
            self.assertEqual(image.size, (40, 40))
            self.assertEqual(image.getpixel((0, 0))[3], 0)


if __name__ == '__main__':
    unittest.main()
