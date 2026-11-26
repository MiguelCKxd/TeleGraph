"""Failed emoji tooltips must not keep closed Tk widgets alive."""
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from tg_ascii.row_emoji import RowEmoji


class RowEmojiLifetimeTests(TestCase):
    def setUp(self):
        self.app = SimpleNamespace(ui_account='a', demo=False, service=SimpleNamespace(backend=object()),
                                   emoji_art=Mock(), emoji_tint=Mock(return_value=None), request_photo=Mock())
        self.tree = SimpleNamespace(winfo_exists=lambda: True)
        self.overlay = RowEmoji(self.app, self.tree)
        self.overlay.refresh = Mock()

    def test_failed_artwork_releases_all_waiting_tooltips(self):
        for _ in range(64):
            self.overlay.load(42, 20, Mock())
            self.app.emoji_art.call_args.args[3](None)
        self.assertEqual(sum(map(len, self.overlay.waiters.values())), 0)
        self.assertFalse(self.overlay.pending)

    def test_failed_decode_releases_waiters(self):
        self.overlay.load(42, 20, Mock())
        self.app.emoji_art.call_args.args[3](Path('fixture'))
        self.app.request_photo.call_args.args[2](None)
        self.assertFalse(self.overlay.waiters)
        self.assertFalse(self.overlay.pending)

    def test_cancelled_account_cannot_discard_new_accounts_waiter(self):
        old, new = Mock(), Mock()
        self.overlay.load(42, 20, old)
        stale = self.app.emoji_art.call_args.args[3]
        self.app.ui_account = 'b'
        self.overlay.load(42, 20, new)
        stale(Path('old'))
        self.assertEqual(set(self.overlay.waiters), {('b', 42, 20)})
        old.assert_not_called()
        self.app.emoji_art.call_args.args[3](Path('new'))
        picture = object()
        self.app.request_photo.call_args.args[2](picture)
        new.assert_called_once_with(picture)
        self.assertFalse(self.overlay.waiters)

    def test_one_success_keeps_all_consumers_of_that_attempt(self):
        first, second = Mock(), Mock()
        self.overlay.load(42, 20, first)
        self.overlay.load(42, 20, second)
        self.app.emoji_art.assert_called_once()
        self.app.emoji_art.call_args.args[3](Path('new'))
        picture = object()
        self.app.request_photo.call_args.args[2](picture)
        first.assert_called_once_with(picture)
        second.assert_called_once_with(picture)
        self.assertFalse(self.overlay.waiters)

    def test_demo_does_not_register_a_callback_that_will_never_run(self):
        self.app.demo = True
        self.overlay.load(42, 20, Mock())
        self.assertFalse(getattr(self.overlay, 'waiters', {}))
        self.app.emoji_art.assert_not_called()
