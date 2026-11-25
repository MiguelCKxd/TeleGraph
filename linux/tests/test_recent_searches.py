from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from tg_ascii.recent_searches import RecentSearches


class RecentSearchesTests(TestCase):
    def test_newest_twenty_survive_restart_separately_for_each_account_and_scope(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            history = RecentSearches(root)
            history.remember('one', 'contacts', 'Persona')
            history.remember('two', 'chats', 'Otro')
            for number in range(25):
                history.remember('one', 'chats', f'Equipo {number}')
            history.remember('one', 'chats', ' Equipo   8 ')
            history.remember('one', 'chats', 'EQUIPO 8')
            reopened = RecentSearches(root)
            queries = reopened.list('one', 'chats')
            self.assertEqual(len(queries), 20)
            self.assertEqual(queries[:2], ['EQUIPO 8', 'Equipo 24'])
            self.assertNotIn('Equipo 4', queries)
            self.assertEqual(reopened.clear('one', 'chats'), [])
            self.assertEqual(reopened.list('one', 'contacts'), ['Persona'])
            reopened.forget_account('one')
            self.assertEqual(reopened.list('one', 'contacts'), [])
            self.assertEqual(reopened.list('two', 'chats'), ['Otro'])
