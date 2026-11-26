import tempfile,unittest
from datetime import datetime,timezone
from types import SimpleNamespace as NS
from tg_ascii.preferences import Preferences
from tg_ascii.timestamps import date_text,message_time

class TimestampTests(unittest.TestCase):
    def test_seconds_are_disabled_by_default_and_persist_only_when_enabled(self):
        with tempfile.TemporaryDirectory() as root:
            p=Preferences(root=root);self.assertFalse(p.values['show_seconds'])
            p.save({'show_seconds':True});self.assertTrue(Preferences(root=root).values['show_seconds'])
    def test_missing_timestamp_is_not_fabricated(self):
        self.assertEqual(date_text(None,{'show_seconds':True}),'')
        self.assertEqual(message_time(NS(date=None,time='12:34'),{'show_seconds':True}),'12:34')
    def test_exact_date_gains_seconds_without_changing_date(self):
        value=datetime(2026,10,30,11,22,37,tzinfo=timezone.utc)
        self.assertTrue(date_text(value,{'show_seconds':True}).endswith(':37'))
        self.assertTrue(date_text(value,{'show_seconds':False},seconds=True).endswith(':37'))
        self.assertEqual(date_text(value,{'show_seconds':True})[:-3],date_text(value))
        self.assertTrue(message_time(NS(date=value),{'show_seconds':True}).endswith(':37'))

    def test_message_signature_invalidates_cache_on_show_seconds_toggle(self):
        from tg_ascii.bubbles import message_signature
        value = datetime(2026, 10, 30, 11, 22, 37, tzinfo=timezone.utc)
        msg = NS(
            id=1, sender='User', text='Hello', raw_text='Hello', time='11:22',
            date=value, outgoing=True, media_kind=None, filename=None, size=0,
            media=None, custom_emojis=(), entities=(), reply_to_id=None, read=True,
            reactions=(), sender_id=123, sender_color=0, reply_icon_id=None,
            reply_markup=None, keyboard_applicable=False, comments_count=None
        )
        app1 = NS(preferences=NS(values={'show_seconds': False}))
        app2 = NS(preferences=NS(values={'show_seconds': True}))
        sig1 = message_signature(msg, app1)
        sig2 = message_signature(msg, app2)
        self.assertNotEqual(sig1, sig2)
        self.assertTrue(sig2[4].endswith(':37'))
        self.assertFalse(sig1[4].endswith(':37'))


    def test_edit_timestamp_invalidates_bubble_even_when_text_is_identical(self):
        from dataclasses import replace
        from tg_ascii.backend import Message
        from tg_ascii.bubbles import message_signature, time_and_status
        original = Message(1, 'Ana', 'Revisión', '12:30')
        changed = replace(original, edited_at=datetime(2026, 11, 26, 12, 31, tzinfo=timezone.utc))
        self.assertNotEqual(time_and_status('12:30', original), time_and_status('12:30', changed))
        self.assertNotEqual(message_signature(original), message_signature(changed))
