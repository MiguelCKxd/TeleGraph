"""3.0: service message texts and link previews that are not attachments."""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from telethon.tl import types as t

from tg_ascii import i18n
from tg_ascii.backend import TelegramBackend
from tg_ascii.service_messages import service_text, duration_text


class WordmarkTests(unittest.TestCase):
    def test_every_letter_uses_one_scale_and_baseline_within_each_name(self):
        from tg_ascii.logos import MOBILE_RECTS, VARIANTS, mobile_wordmark

        for variant, text in VARIANTS.items():
            with self.subTest(variant=variant):
                glyphs = [MOBILE_RECTS[letter] for letter in text]
                ink = mobile_wordmark(variant)
                original_top = min(y for glyph in glyphs for _, y, _, _ in glyph)
                original_bottom = max(b for glyph in glyphs for _, _, _, b in glyph)
                top = min(y for _, y, _, _ in ink)
                bottom = max(b for _, _, _, b in ink)
                scale = (bottom - top) / (original_bottom - original_top)
                self.assertEqual(len(ink), sum(map(len, glyphs)))
                self.assertAlmostEqual(top + bottom, 1024, delta=1)
                self.assertAlmostEqual(min(x for x, _, _, _ in ink) +
                                       max(r for _, _, r, _ in ink), 1024, delta=1)
                offset = 0
                for glyph in glyphs:
                    drawn = ink[offset:offset + len(glyph)]
                    offset += len(glyph)
                    left = min(rect[0] for rect in drawn)
                    for original, rendered in zip(glyph, drawn):
                        x, y, right, base = original
                        expected = (left + x * scale, top + (y - original_top) * scale,
                                    left + right * scale, top + (base - original_top) * scale)
                        for actual, ideal in zip(rendered, expected):
                            # Both the measured bounds and the rendered edges round to pixels.
                            self.assertAlmostEqual(actual, ideal, delta=2)


class ServiceMessageTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(i18n.set_language, i18n.get_language())
        i18n.set_language('en')

    def test_members_calls_and_voice_chats_are_described(self):
        bob = t.User(2, first_name='Bob')
        self.assertEqual(service_text(t.MessageActionChatAddUser([2]), 'Ana', [bob]), 'Ana added Bob')
        self.assertEqual(service_text(t.MessageActionChatAddUser([1]), 'Ana', [t.User(1, first_name='Ana')]), 'Ana joined')
        self.assertEqual(service_text(t.MessageActionChatDeleteUser(1), 'Ana'), 'Ana left')
        missed = t.MessageActionPhoneCall(call_id=1, reason=t.PhoneCallDiscardReasonMissed())
        self.assertEqual(service_text(missed, 'Ana'), '📞 Missed call')
        done = t.MessageActionPhoneCall(call_id=1, reason=t.PhoneCallDiscardReasonHangup(), duration=75, video=True)
        self.assertEqual(service_text(done, 'Ana', outgoing=True), '📹 Outgoing call · 1:15')
        self.assertEqual(service_text(t.MessageActionGroupCall(call=t.InputGroupCall(1, 2), duration=3725), 'Ana'),
                         '🎙 Voice chat ended · 1:02:05')
        self.assertEqual(duration_text(59), '0:59')

    def test_unknown_actions_fall_back_to_nothing(self):
        self.assertEqual(service_text(object(), 'Ana'), '')

    def test_every_language_keeps_the_placeholders(self):
        from tg_ascii.translations_v30 import KEYS, ROWS
        for code, row in ROWS.items():
            for key, value in zip(KEYS, row):
                for field in ('{name}', '{users}', '{title}', '{duration}'):
                    self.assertEqual(field in key, field in value, (code, key))


class LinkPreviewTests(unittest.TestCase):
    def test_link_preview_is_text_with_its_page_not_a_file(self):
        backend = TelegramBackend(Mock())
        page = t.WebPage(1, 'https://telegram.org', 'https://telegram.org', 0, site_name='Telegram', title='Telegram')
        source = SimpleNamespace(id=1, out=False, sender_id=42, sender=t.User(id=42, first_name='Alex'),
                                 raw_text='Mira https://telegram.org', date=datetime.now(timezone.utc),
                                 media=t.MessageMediaWebPage(page), file=SimpleNamespace(name=None, size=8045, mime_type='image/jpeg'))
        message = backend.message(source)
        self.assertEqual(message.text, 'Mira https://telegram.org')
        self.assertEqual(message.media_kind, '')
        self.assertIs(message.webpage, page)

    def test_service_message_gets_a_readable_text(self):
        backend = TelegramBackend(Mock())
        source = SimpleNamespace(id=2, out=False, sender_id=42, sender=t.User(id=42, first_name='Alex'), raw_text='',
                                 date=datetime.now(timezone.utc), action=t.MessageActionPinMessage(), action_entities=[])
        i18n.set_language('en')
        self.assertEqual(backend.message(source).text, 'Alex pinned a message')


class BrandTests(unittest.TestCase):
    def test_public_name_is_telegraph_but_paths_keep_their_folder(self):
        self.assertEqual(i18n.brand('TG-ASCII is ready.'), 'TeleGraph is ready.')
        self.assertEqual(i18n.brand('Open Tg-As'), 'Open Tg-Gr')
        self.assertEqual(i18n.brand('Saved to Downloads/TG-ASCII.'), 'Saved to Downloads/TG-ASCII.')
        self.assertEqual(i18n.brand('Tg-ASCII'), 'Tg-ASCII')
