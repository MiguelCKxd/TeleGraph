"""1.5.5: archived chats have their own list (More › Archived chats)."""
import unittest
from types import SimpleNamespace

from tg_ascii.telegram_features import compile_folder, in_chat_list


def chat(archived):
    return SimpleNamespace(id=1, name='x', archived=archived, contact=True, kind='user', muted=False,
                           unread=0, unread_mark=False, pinned=False, entity=None)


class ArchivedListTests(unittest.TestCase):
    def test_all_chats_leaves_archived_out_and_the_archive_shows_only_them(self):
        compiled = compile_folder(None)
        self.assertTrue(in_chat_list(chat(False), None, compiled))
        self.assertFalse(in_chat_list(chat(True), None, compiled))
        self.assertTrue(in_chat_list(chat(True), None, compiled, archive_view=True))
        self.assertFalse(in_chat_list(chat(False), None, compiled, archive_view=True))

    def test_unarchiving_moves_the_chat_back(self):
        item, compiled = chat(True), compile_folder(None)
        self.assertFalse(in_chat_list(item, None, compiled))
        item.archived = False
        self.assertTrue(in_chat_list(item, None, compiled))
        self.assertFalse(in_chat_list(item, None, compiled, archive_view=True))

    def test_label_is_translated(self):
        from tg_ascii.i18n import set_language, tr
        try:
            set_language('es')
            self.assertEqual(tr('Archived chats'), 'Chats archivados')
            set_language('fr')
            self.assertEqual(tr('Archived chats'), 'Discussions archivées')
        finally:
            set_language('en')


if __name__ == '__main__':
    unittest.main()
