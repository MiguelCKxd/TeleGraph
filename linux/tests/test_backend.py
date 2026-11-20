import unittest
from tg_ascii.backend import DemoBackend, display

class BackendTests(unittest.IsolatedAsyncioTestCase):
    def test_display(self):
        self.assertEqual(display('café'), 'cafe')
        self.assertNotIn('\x1b', display('\x1b[31mHola'))
        self.assertTrue(display('👋').isascii())

    async def test_send_preserves_original_and_chat(self):
        backend = DemoBackend()
        other_chat = await backend.history(2)
        original = 'Qué tal 👋'
        sent = await backend.send(1, original)
        self.assertEqual(sent.text, original)
        self.assertEqual((await backend.history(1))[-1], sent)
        self.assertEqual(await backend.history(2), other_chat)


class NameTests(unittest.TestCase):
    def test_names_use_attached_sender_then_cache_without_extra_requests(self):
        from datetime import datetime, timezone
        from types import SimpleNamespace
        from unittest.mock import Mock
        from telethon.tl.types import User
        from tg_ascii.backend import TelegramBackend
        backend = TelegramBackend(Mock())
        source = SimpleNamespace(id=1, out=False, sender_id=42, sender=User(id=42, first_name='Alex', last_name='Prueba'), raw_text='Hola', date=datetime.now(timezone.utc))
        self.assertEqual(backend.message(source).sender, 'Alex Prueba')
        source.sender = None
        self.assertEqual(backend.message(source).sender, 'Alex Prueba')
        source.out = True
        from tg_ascii.i18n import tr
        self.assertEqual(backend.message(source).sender, tr('Tu'))
        self.assertTrue(backend.message(source).outgoing)
        backend.client.get_entity.assert_not_called()
