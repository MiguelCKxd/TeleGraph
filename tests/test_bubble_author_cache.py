"""Visiting many group authors must not grow the canvas path cache forever."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from tg_ascii.bubbles import AUTHOR_PATH_LIMIT, BubbleView


class AuthorCacheTests(IsolatedAsyncioTestCase):
    async def test_many_authors_are_bounded_and_recently_used_path_survives(self):
        with TemporaryDirectory() as folder:
            requests = []
            backend = SimpleNamespace(avatar=AsyncMock(return_value='fixture.jpg'))
            app = SimpleNamespace(ui_account='a', preview_dir=Path(folder), request_photo=Mock(),
                                  service=SimpleNamespace(backend=backend),
                                  worker=SimpleNamespace(submit=lambda *args: requests.append(args)))
            canvas = SimpleNamespace(app=app, generation=1)
            for sender in range(512):
                BubbleView.sender_avatar(canvas, sender, SimpleNamespace(sender_id=sender, sender='User', sender_color=None), 1)
                work, done, failed = requests.pop()
                done(await work)
            self.assertEqual(len(canvas._author_paths), AUTHOR_PATH_LIMIT)
            self.assertFalse(canvas._author_waiting)
            recent = 256
            BubbleView.sender_avatar(canvas, recent, SimpleNamespace(sender_id=recent), 1)
            self.assertFalse(requests)  # Hit remains a path lookup; no duplicate RPC.
            BubbleView.sender_avatar(canvas, 512, SimpleNamespace(sender_id=512, sender='User', sender_color=None), 1)
            work, done, failed = requests.pop()
            done(await work)
            self.assertIn(('a', recent), canvas._author_paths)
            self.assertNotIn(('a', recent+1), canvas._author_paths)
