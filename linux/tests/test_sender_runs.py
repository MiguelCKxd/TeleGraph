import unittest
from datetime import datetime, timedelta, timezone

from tg_ascii.backend import Message
from tg_ascii.sender_runs import positions, shows_authors

T0 = datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc)


def m(ident, sender, minutes=0, out=False, service=False):
    return Message(ident, f'User {sender}', 'x', '10:00', out, sender_id=sender,
                   date=T0 + timedelta(minutes=minutes), service=service)


class SenderRunTests(unittest.TestCase):
    def test_name_first_and_picture_last(self):
        runs = positions([m(1, 7), m(2, 7, 1), m(3, 7, 2), m(4, 8, 3), m(5, 7, 4)])
        self.assertEqual(runs, [(True, False), (False, False), (False, True), (True, True), (True, True)])

    def test_day_separator_time_gap_and_service_break_runs(self):
        messages = [m(1, 7), m(2, 7, 1), m(3, 7, 10), m(4, 7, 11, service=True), m(5, 7, 12), m(6, 7, 40)]
        runs = positions(messages, [None, 'Hoy', None, None, None, None])
        self.assertEqual(runs, [(True, True), (True, False), (False, True), (True, True), (True, True), (True, True)])

    def test_own_and_unknown_authors_never_join(self):
        runs = positions([m(1, 7, out=True), m(2, 7, out=False), m(3, None), m(4, None)])
        self.assertEqual(runs, [(True, True), (True, True), (True, True), (True, True)])

    def test_only_groups_show_author_pictures(self):
        self.assertTrue(shows_authors('group'))
        self.assertFalse(shows_authors('channel'))
        self.assertFalse(shows_authors('user'))


if __name__ == '__main__':
    unittest.main()
