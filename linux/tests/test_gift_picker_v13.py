"""Catalogue identity and eligibility checks; no purchases or network."""
from types import SimpleNamespace as NS
import unittest

from tg_ascii.gift_picker import GiftGrid, filter_gifts, gift_price, gift_status


def gift(ident, **values):
    return NS(id=ident, title=f'Gift {ident}', **values)


class GiftCatalogueTests(unittest.TestCase):
    def test_available_excludes_auction_sold_out_and_personal_limit(self):
        items = [gift(1, stars=50), gift(2, sold_out=True),
                 gift(3, availability_remains=0), gift(4, auction=True),
                 gift(5, auction_slug='sale'), gift(6, per_user_remains=0)]
        self.assertEqual([g.id for g in filter_gifts(items, mode='available')], [1])
        self.assertEqual([g.id for g in filter_gifts(items, mode='auction')], [4, 5])
        self.assertEqual([g.id for g in filter_gifts(items, mode='sold_out')], [2, 3])

    def test_missing_or_invalid_price_never_claims_free(self):
        for price in (None, -1, True, '100'):
            self.assertNotIn('0 ★', gift_price(gift(1, stars=price)))
        self.assertEqual(gift_price(gift(1, stars=0)), '0 ★')
        self.assertEqual(gift_price(gift(1, stars=125)), '125 ★')

    def test_search_matches_title_id_and_price(self):
        items = [NS(id=42, title='ÁRBOL', stars=125), gift(2, stars=80)]
        for query in (' árbol ', '42', '125'):
            self.assertEqual(filter_gifts(items, query), items[:1])

    def test_hidden_selection_is_not_actionable(self):
        grid = object.__new__(GiftGrid)
        first, second = gift(1), gift(2)
        grid.selected_id, grid.filtered = 1, [second]
        self.assertIsNone(grid.selection())
        grid.filtered = [second, first]
        self.assertIs(grid.selection(), first)

    def test_reordered_catalogue_selects_identity_not_row(self):
        grid = object.__new__(GiftGrid)
        grid.selected_id = 7
        replacement = gift(7, stars=300)
        grid.filtered = [gift(8), replacement]
        self.assertIs(grid.selection(), replacement)

    def test_selection_only_notifies_does_not_activate(self):
        from unittest.mock import Mock
        grid = object.__new__(GiftGrid)
        selected = gift(7)
        grid.filtered, grid.repaint, grid.changed, grid.activate = [selected], Mock(), Mock(), Mock()
        grid.select_index(0)
        grid.changed.assert_called_once_with(selected)
        grid.activate.assert_not_called()
        grid.select_index(5)
        self.assertEqual(grid.selected_id, 7)


if __name__ == '__main__':
    unittest.main()
