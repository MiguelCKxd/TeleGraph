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

    def test_chooser_uses_placeholder_without_own_photo(self):
        with tempfile.TemporaryDirectory() as root:
            shown = photos.display_path(root, 'abc', 'Ana López', 7, Path(root) / 'cache')
            self.assertIn('default-avatar-', shown)
            image = photos.round_image(shown, 40)
            self.assertEqual(image.size, (40, 40))
            self.assertEqual(image.getpixel((0, 0))[3], 0)


if __name__ == '__main__':
    unittest.main()
