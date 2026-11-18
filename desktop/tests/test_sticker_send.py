import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

from telethon import errors, functions, types

from tg_ascii.backend import TelegramBackend
from tg_ascii.sticker_picker import send_selected_sticker


class StickerPickerTests(unittest.TestCase):
    def setUp(self):
        self.backend=NS(send_sticker=Mock(return_value='operation'))
        self.app=NS(busy=False,ui_account='A',active=42,call=Mock(),clear_sent_reply=Mock(),incoming=Mock(),
                    service=NS(backend=self.backend),chats=[NS(id=42,kind='user')])
        self.window=NS(winfo_exists=lambda:True,destroy=Mock())

    def test_first_sticker_sends_without_ever_using_reply(self):
        document=object()
        send_selected_sticker(self.app,self.window,self.backend,'A',42,document)
        self.backend.send_sticker.assert_called_once_with(42,document,reply_to=None)
        self.window.destroy.assert_not_called()
        self.app.call.call_args.args[1]('sent')
        self.app.incoming.assert_called_once_with((42,'sent'))
        self.window.destroy.assert_called_once()

    def test_failed_send_keeps_picker_and_reply_until_success(self):
        self.app.reply_drafts={('A',42):7}
        document=object()
        send_selected_sticker(self.app,self.window,self.backend,'A',42,document)
        self.backend.send_sticker.assert_called_once_with(42,document,reply_to=7)
        self.app.clear_sent_reply.assert_not_called();self.window.destroy.assert_not_called()
        self.assertEqual(self.app.reply_drafts[('A',42)],7)

    def test_stale_picker_cannot_send_to_another_chat_or_account(self):
        send_selected_sticker(self.app,self.window,self.backend,'B',42,object())
        send_selected_sticker(self.app,self.window,self.backend,'A',43,object())
        self.app.busy=True
        send_selected_sticker(self.app,self.window,self.backend,'A',42,object())
        self.backend.send_sticker.assert_not_called()


class StickerReferenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client=AsyncMock();self.client.add_event_handler=Mock()
        self.backend=TelegramBackend(self.client);self.backend.message=lambda value:value
        attr=types.DocumentAttributeSticker('alt',types.InputStickerSetID(20,30))
        self.document=NS(id=10,attributes=[attr],file_reference=b'old')
        self.fresh=NS(id=10,attributes=[attr],file_reference=b'new')
        self.client.return_value=NS(documents=[NS(id=11),self.fresh])

    async def test_expired_reference_refreshes_exact_sticker_once_and_preserves_reply(self):
        self.client.send_file.side_effect=[errors.FileReferenceExpiredError(None),'sent']
        result=await self.backend.send_sticker(42,self.document,reply_to=7)
        self.assertEqual(result,'sent')
        self.assertIsInstance(self.client.call_args.args[0],functions.messages.GetStickerSetRequest)
        self.assertEqual(self.client.send_file.await_count,2)
        self.client.send_file.assert_awaited_with(42,self.fresh,force_document=False,reply_to=7)

    async def test_missing_sticker_or_second_reference_failure_does_not_loop(self):
        self.client.send_file.side_effect=errors.FileReferenceExpiredError(None)
        with self.assertRaises(errors.FileReferenceExpiredError):await self.backend.send_sticker(42,self.document)
        self.assertEqual(self.client.send_file.await_count,2)
        self.client.send_file.reset_mock();self.client.return_value=NS(documents=[NS(id=99)])
        with self.assertRaises(errors.FileReferenceExpiredError):await self.backend.send_sticker(42,self.document)
        self.assertEqual(self.client.send_file.await_count,1)

    async def test_timeout_not_retried_to_avoid_duplicate_stickers(self):
        self.client.send_file.side_effect=TimeoutError()
        with self.assertRaises(TimeoutError):await self.backend.send_sticker(42,self.document)
        self.client.send_file.assert_awaited_once();self.client.assert_not_awaited()


if __name__=='__main__':unittest.main()
