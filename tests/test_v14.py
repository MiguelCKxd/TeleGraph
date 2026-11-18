"""Regression tests for TG-ASCII 1.4 features (no network, no Tk windows)."""
import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from telethon import types


class DaySeparatorTests(unittest.TestCase):
    def test_headers_only_when_the_day_changes_and_labels_are_localised(self):
        from tg_ascii.day_separators import day_headers, day_label
        from tg_ascii.i18n import set_language
        today = datetime.now().astimezone().date()
        at = lambda day, hour: NS(date=datetime(day.year, day.month, day.day, hour, tzinfo=datetime.now().astimezone().tzinfo))
        old = today - timedelta(days=40)
        messages = [at(old, 9), at(old, 10), at(today - timedelta(days=1), 8), at(today, 7), NS(date=None), at(today, 9)]
        set_language('es')
        try:
            headers = day_headers(messages, today)
            self.assertEqual(headers[1], '')
            self.assertEqual(headers[2], 'Ayer')
            self.assertEqual(headers[3], 'Hoy')
            self.assertEqual(headers[4:], ['', ''])
            self.assertIn('de', headers[0])
            self.assertEqual(day_label(date(2020, 3, 5), today, 'en'), 'March 5, 2020')
            self.assertEqual(day_label(date(2020, 3, 5), today, 'xx'), '2020-03-05')
        finally:
            set_language('en')


class GiftPreviewTests(unittest.TestCase):
    def test_official_link_prefers_collectible_then_auction_then_catalogue(self):
        from tg_ascii.gift_preview import official_gift_url, FRAGMENT_GIFTS
        self.assertEqual(official_gift_url(NS(slug='PlushPepe-1')), 'https://t.me/nft/PlushPepe-1')
        self.assertEqual(official_gift_url(NS(slug=None, auction_slug='spring')), 'https://t.me/auction/spring')
        self.assertEqual(official_gift_url(NS()), FRAGMENT_GIFTS)


class ChatActivityTests(unittest.TestCase):
    def app(self, enabled=True):
        future = datetime.now(timezone.utc) + timedelta(minutes=5)
        backend = NS(_presence={1: types.UserStatusOnline(expires=future), 2: types.UserStatusOffline(was_online=future)})
        return NS(preferences=NS(values={'advanced_features': {'chat_list_activity': enabled}}),
                  service=NS(backend=backend), ui_account='a')

    def test_online_and_typing_marks_and_off_by_default(self):
        from tg_ascii.chat_activity import mark, remember_typing, ONLINE_MARK, TYPING_MARK
        from tg_ascii.backend import Chat
        app = self.app()
        self.assertEqual(mark(app, Chat(1, 'Ana')), ONLINE_MARK)
        self.assertEqual(mark(app, Chat(2, 'Bo')), '')
        remember_typing(app, 2, 'Typing…')
        self.assertEqual(mark(app, Chat(2, 'Bo')), TYPING_MARK)
        self.assertEqual(mark(self.app(False), Chat(1, 'Ana')), '')
        from tg_ascii.preferences import DEFAULTS
        self.assertFalse(DEFAULTS['advanced_features']['chat_list_activity'])
        self.assertFalse(DEFAULTS['advanced_features']['contact_list_details'])
        from tg_ascii.advanced_features import DEFAULT_ON
        self.assertEqual(DEFAULTS['advanced_features']['group_video_grid'], 'group_video_grid' in DEFAULT_ON)


class ContactSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_changed_entries_are_uploaded_in_batches(self):
        from tg_ascii.contact_sync import import_contacts
        from tg_ascii.device_contacts import DeviceContact
        contacts = [DeviceContact('Ana', '', ['+34600000001']), DeviceContact('Bo', 'X', ['+34600000002'])]
        client = AsyncMock(return_value=NS(users=[object()], retry_contacts=[]))
        backend = NS(client=client)
        state = {'imported': {}, 'last': {}}
        with patch('tg_ascii.contact_sync.asyncio.sleep', new=AsyncMock()):
            summary = await import_contacts(backend, contacts, state)
            self.assertEqual(summary['sent'], 2)
            again = await import_contacts(backend, contacts, state)
        self.assertEqual(again['sent'], 0)
        self.assertEqual(client.await_count, 1)

    def test_vcard_and_phone_normalisation(self):
        from tg_ascii.device_contacts import read_vcard, normalize_phone, vcard_text, DeviceContact
        self.assertEqual(normalize_phone('0034 600-000-001'), '+34600000001')
        self.assertEqual(normalize_phone('12'), '')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'c.vcf'
            path.write_text(vcard_text(DeviceContact('Ana', 'Ruiz', ['+34600000001'])) +
                            'BEGIN:VCARD\r\nFN:No phone\r\nEND:VCARD\r\n', encoding='utf-8')
            contacts = read_vcard(path)
        self.assertEqual([(c.first, c.last, c.phones) for c in contacts], [('Ana', 'Ruiz', ['+34600000001'])])


class LifecycleTests(unittest.TestCase):
    def test_relaunch_commands(self):
        from tg_ascii.app_lifecycle import relaunch_command
        self.assertEqual(relaunch_command([], '/py', frozen=False), ['/py', '-m', 'tg_ascii'])
        with patch('tg_ascii.app_lifecycle.sys.platform', 'darwin'):
            command = relaunch_command([], '/A/TG-ASCII.app/Contents/MacOS/TG-ASCII', frozen=True)
        self.assertEqual(command, ['/usr/bin/open', '-n', str(Path('/A/TG-ASCII.app'))])
        with patch('tg_ascii.app_lifecycle.sys.platform', 'win32'):
            self.assertEqual(relaunch_command(['--x'], 'C:/TG/TG-ASCII.exe', frozen=True), [str(Path('C:/TG/TG-ASCII.exe')), '--x'])


class AvatarTests(unittest.IsolatedAsyncioTestCase):
    async def test_photo_less_entity_needs_no_request_and_entity_is_reused(self):
        from tg_ascii.backend import TelegramBackend
        client = AsyncMock()
        client.add_event_handler = Mock()
        backend = TelegramBackend(client)
        empty = types.User(id=5, photo=types.UserProfilePhotoEmpty())
        self.assertIsNone(await backend.avatar(5, Path('/unused/a.jpg'), entity=empty))
        client.download_profile_photo.assert_not_awaited()
        photo = types.User(id=6, photo=types.UserProfilePhoto(photo_id=77, dc_id=2))
        client.download_profile_photo.return_value = '/tmp/x.jpg'
        await backend.avatar(6, Path('/unused/b.jpg'), entity=photo)
        self.assertIs(client.download_profile_photo.await_args.args[0], photo)


class GroupVideoTests(unittest.TestCase):
    def test_grid_layout_and_worker_budget(self):
        from tg_ascii.desktop_calls import CallWindow
        from tg_ascii.calls_group_worker import slot_budget
        self.assertEqual(CallWindow.tile_layout(1), [(0, 0, 1, 1)])
        self.assertEqual(len(CallWindow.tile_layout(30)), 30)
        self.assertEqual(slot_budget(1), (.1, None))  # Default: unchanged.
        self.assertEqual(slot_budget(20)[1], (256, 144))

    def test_direct_scaling_keeps_aspect_and_rotation(self):
        from tg_ascii.calls_native import frame_image
        frame = dict(width=64, height=32, rotation=90, data=b'\x80' * (64 * 32 + 2 * 32 * 16))
        image = frame_image(frame, (40, 40))
        self.assertEqual(image.size, (20, 40))  # 64x32 rotated → portrait, fitted into 40x40.


class CarouselTests(unittest.TestCase):
    def test_slides_follow_blocks_and_missing_photos(self):
        from tg_ascii.article_carousel import slide_items
        photo = types.Photo(id=1, access_hash=1, file_reference=b'', date=None, sizes=[], dc_id=2)
        caption = types.PageCaption(types.TextPlain('one'), types.TextEmpty())
        block = types.PageBlockSlideshow([types.PageBlockPhoto(1, caption), types.PageBlockPhoto(9, caption)], caption)
        items = slide_items(block, {1: photo})
        self.assertEqual([(item[0] is photo, item[1], item[2]) for item in items], [(True, 'one', 'photo'), (False, 'one', 'photo')])


class AttachmentRoutingTests(unittest.TestCase):
    def test_files_attach_at_once_and_system_preview_is_opt_in(self):
        from tg_ascii.attachment_preview import route_attachment
        accepted = Mock()
        # 1.5.1: the old switch is now Settings › Menus › File preview.
        from tg_ascii import menu_style
        app = NS(preferences=NS(values={}), show_error=Mock())
        try:
            with patch('tg_ascii.native_open.quick_look') as look:
                menu_style.configure({})
                route_attachment(app, Path('/tmp/report.pdf'), accepted)
                look.assert_not_called()
                menu_style.configure({'advanced_features': {'custom_menus': True}, 'menu_style': 'custom', 'menu_custom': {'file_preview': 'system'}})
                route_attachment(app, Path('/tmp/report.pdf'), accepted)
                look.assert_called_once()
        finally:
            menu_style.configure({})
        self.assertEqual(accepted.call_count, 2)


class ContactSearchTests(unittest.TestCase):
    def test_name_username_phone_and_accents(self):
        from tg_ascii.contact_search import contact_matches
        person = types.User(id=1, first_name='José', last_name='Núñez', username='pepe_n', phone='34600123456')
        for query in ('', 'jose', 'NUÑEZ', 'jose nun', '@pepe', '600123', 'pepe_n'):
            self.assertTrue(contact_matches(person, query), query)
        for query in ('maria', '99', '@other'):
            self.assertFalse(contact_matches(person, query), query)

    def test_four_part_versions_order_correctly(self):
        from tg_ascii.updater import version_tuple
        self.assertGreater(version_tuple('1.4.0.1'), version_tuple('1.4.0'))
        self.assertEqual(version_tuple('1.4.0'), version_tuple('1.4.0.0'))
        self.assertGreater(version_tuple('1.5.0'), version_tuple('1.4.0.1'))
        with self.assertRaises(ValueError):
            version_tuple('1.4')


if __name__ == '__main__':
    unittest.main()
