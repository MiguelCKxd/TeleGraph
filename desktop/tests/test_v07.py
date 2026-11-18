import asyncio
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock
import struct
import tempfile
import unittest

from telethon import types, errors
from tg_ascii.accounts import Accounts
from tg_ascii.backend import Message, TelegramBackend
from tg_ascii.links import detected_links, browser_url
from tg_ascii.logos import VARIANTS, ascii_art, png_bytes
from tg_ascii.message_tools import display_segments
from tg_ascii.preferences import Preferences
from tg_ascii.scrolling import WheelRouter, wheel_units
from tg_ascii.video_metadata import mp4_metadata


class ActionTests(unittest.IsolatedAsyncioTestCase):
    def backend(self):
        client=Mock()
        client.get_messages=AsyncMock(return_value=NS(peer_id=types.PeerUser(42),raw_text='original',entities=[]))
        client.delete_messages=AsyncMock()
        client.forward_messages=AsyncMock()
        client.edit_message=AsyncMock()
        backend=TelegramBackend(client)
        backend.message=lambda value:value
        return backend,client

    async def test_delete_rejects_other_peer_without_mutation(self):
        backend,client=self.backend()
        with self.assertRaises(ValueError): await backend.delete_message(99,7,True)
        client.delete_messages.assert_not_called()
        await backend.delete_message(42,7,False)
        client.delete_messages.assert_awaited_once_with(42,[7],revoke=False)

    async def test_forward_has_explicit_source_and_destination(self):
        backend,client=self.backend()
        await backend.forward_message(42,7,99)
        client.forward_messages.assert_awaited_once_with(99,[7],from_peer=42)

    async def test_edit_preserves_entities_when_only_media_changes(self):
        backend,client=self.backend()
        entity=types.MessageEntityBold(0,8)
        client.get_messages.return_value.entities=[entity]
        await backend.edit_existing(42,7,'original','new.jpg')
        self.assertEqual(client.edit_message.call_args.kwargs['formatting_entities'],[entity])
        await backend.edit_existing(42,7,'new text')
        self.assertEqual(client.edit_message.call_args.kwargs['formatting_entities'],[])

    async def test_reply_is_part_of_original_send(self):
        backend,client=self.backend()
        client.send_message=AsyncMock(return_value='sent')
        await backend.send_formatted(42,'reply',[],reply_to=7)
        self.assertEqual(client.send_message.call_args.args,(42,'reply'))
        self.assertEqual(client.send_message.call_args.kwargs['reply_to'],7)

    async def test_search_pages_are_scoped_and_typed(self):
        backend,client=self.backend();client.get_messages.return_value=[]
        await backend.search_messages(42,'hello','photos',50)
        args=client.get_messages.call_args
        self.assertEqual(args.args,(42,))
        self.assertEqual(args.kwargs['offset_id'],50)
        self.assertIsInstance(args.kwargs['filter'],types.InputMessagesFilterPhotos)

    async def test_read_ticks_advance_only_on_outbox_event(self):
        backend,_=self.backend();backend.on_change=Mock()
        await backend.read_event(NS(outbox=True,chat_id=42,max_id=7))
        self.assertEqual(backend.read_max[42],7)
        backend.on_change.assert_called_with('read',(42,7))
        await backend.read_event(NS(outbox=False,chat_id=42,max_id=99))
        self.assertEqual(backend.read_max[42],7)

    async def test_username_contact_does_not_share_phone(self):
        client=AsyncMock();client.get_entity.return_value=types.User(42,first_name='Alex')
        backend=TelegramBackend.__new__(TelegramBackend);backend.client=client
        await backend.save_contact('@alex','Alex')
        request=client.call_args.args[0]
        self.assertEqual(request.phone,'')
        self.assertFalse(request.add_phone_privacy_exception)

    async def test_story_targets_self_and_contacts_by_default(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'photo.png';path.write_bytes(png_bytes(size=64))
            client=AsyncMock();client.upload_file.return_value=types.InputFile(1,1,'photo.png','')
            backend=TelegramBackend.__new__(TelegramBackend);backend.client=client
            await backend.publish_story(path,'caption')
            request=client.call_args.args[0]
            self.assertIsInstance(request.peer,types.InputPeerSelf)
            self.assertIsInstance(request.privacy_rules[0],types.InputPrivacyValueAllowContacts)
            self.assertEqual(request.period,86400)
            self.assertFalse(request.pinned)


class QRTests(unittest.IsolatedAsyncioTestCase):
    async def test_expiry_regenerates_and_registers_only_original_account(self):
        accounts=Accounts(demo=True)
        one=NS(url='tg://login?token=test1',wait=AsyncMock(side_effect=asyncio.TimeoutError))
        two=NS(url='tg://login?token=test2',wait=AsyncMock())
        service=NS(client=NS(qr_login=AsyncMock(side_effect=[one,two])),ready=Mock(return_value='ready'))
        accounts.service=lambda _:service
        accounts.register=AsyncMock();accounts.restore_saved=AsyncMock()
        seen=[]
        self.assertEqual(await accounts.login_qr(seen.append),'ready')
        self.assertEqual(len(seen),2)
        accounts.register.assert_awaited_once_with('account')

    async def test_qr_2fa_does_not_register_unfinished_login(self):
        accounts=Accounts(demo=True)
        qr=NS(url='tg://login?token=test',wait=AsyncMock(side_effect=errors.SessionPasswordNeededError(None)))
        service=NS(client=NS(qr_login=AsyncMock(return_value=qr)),ready=Mock())
        accounts.service=lambda _:service;accounts.register=AsyncMock()
        self.assertEqual(await accounts.login_qr(lambda _:None),'password')
        accounts.register.assert_not_called();service.ready.assert_not_called()

    async def test_cancellation_does_not_save_session_registry(self):
        accounts=Accounts(demo=True)
        waiting=asyncio.Event()
        async def wait(): waiting.set(); await asyncio.Future()
        qr=NS(url='tg://login?token=test',wait=wait)
        service=NS(client=NS(qr_login=AsyncMock(return_value=qr)),ready=Mock())
        accounts.service=lambda _:service;accounts.register=AsyncMock()
        task=asyncio.create_task(accounts.login_qr(lambda _:None))
        await waiting.wait();task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        accounts.register.assert_not_called()


class DisplayTests(unittest.TestCase):
    def test_custom_emoji_replaces_only_entity_utf16_range(self):
        message=Message(1,'A','👋 x 😀 and 😀','12:00',raw_text='👋 x 😀 and 😀',
                        entities=(types.MessageEntityCustomEmoji(5,2,123),))
        self.assertEqual(list(display_segments(message)),['👋 x ',123,' and 😀'])
        message.text='[File] photo.jpg\n'+message.raw_text
        self.assertEqual(list(display_segments(message))[0],'[File] photo.jpg\n')

    def test_only_safe_clickable_links(self):
        text='See (https://example.com/a). www.example.org and t.me/example'
        links=list(detected_links(text))
        self.assertEqual([x[2] for x in links],['https://example.com/a','https://www.example.org','https://t.me/example'])
        for value in ('javascript:alert(1)','file:///tmp/a','https://user:secret@example.com','https://example.com/\nsecret'):
            with self.assertRaises(ValueError): browser_url(value)

    def test_logo_case_and_defaults_are_distinct(self):
        self.assertEqual(len({ascii_art(v) for v in VARIANTS}),len(VARIANTS))
        self.assertTrue(all(set(ascii_art(v))<=set('# \n') for v in VARIANTS))
        values=Preferences.validated({'logo_variant':'invalid','bubbles':False})
        self.assertEqual(values['logo_variant'],'title-short');self.assertFalse(values['bubbles'])
        self.assertEqual(struct.unpack('>II',png_bytes(size=64)[16:24]),(64,64))

    def test_wheel_falls_through_inner_edge_to_global_view(self):
        outer=NS(yview=lambda:(0,.5),yview_scroll=Mock(),master=None,winfo_class=lambda:"Text")
        inner=NS(yview=lambda:(.5,1),yview_scroll=Mock(),master=outer,winfo_class=lambda:"Text")
        router=object.__new__(WheelRouter); router.remainders={}
        router.route(inner,NS(widget=inner,state=0),1)
        inner.yview_scroll.assert_not_called();outer.yview_scroll.assert_called_once_with(1,'units')
        self.assertEqual(wheel_units(-2,'darwin'),2)
        self.assertEqual(wheel_units(-120,'win32'),1)

    def test_mp4_metadata_and_limit(self):
        def box(kind,data): return struct.pack('>I4s',len(data)+8,kind)+data
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'video.mp4'
            def write(seconds):
                mvhd=b'\0'*12+struct.pack('>II',1000,seconds*1000)+b'\0'*12
                tkhd=b'\0'*76+struct.pack('>II',720<<16,1280<<16)
                path.write_bytes(box(b'moov',box(b'mvhd',mvhd)+box(b'trak',box(b'tkhd',tkhd))))
            write(30);self.assertEqual(mp4_metadata(path),(30,720,1280))
            write(61)
            with self.assertRaises(ValueError):mp4_metadata(path)

class ReplyMediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_audio_and_sticker_keep_selected_reply(self):
        backend = TelegramBackend(Mock())
        backend.client.send_file = AsyncMock(return_value='sent')
        backend.message = lambda result: result
        document = object()
        await backend.send_sticker(42, document, reply_to=7)
        self.assertEqual(backend.client.send_file.call_args.args, (42, document))
        self.assertEqual(backend.client.send_file.call_args.kwargs['reply_to'], 7)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.ogg'
            path.write_bytes(b'synthetic fixture; never played')
            await backend.send_audio(42, path, voice=True, duration=2, reply_to=8)
        self.assertEqual(backend.client.send_file.call_args.args[0], 42)
        self.assertEqual(backend.client.send_file.call_args.kwargs['reply_to'], 8)
        self.assertTrue(backend.client.send_file.call_args.kwargs['voice_note'])

    def test_completion_does_not_clear_another_reply_or_account(self):
        from tg_ascii.desktop_actions import DesktopActions
        app = NS(ui_account='one', active=42, reply_drafts={('one',42):9, ('two',42):7}, update_reply=Mock())
        DesktopActions.clear_sent_reply(app, 'one', 42, 7)
        self.assertEqual(app.reply_drafts[('one',42)],9)
        DesktopActions.clear_sent_reply(app, 'two', 42, 7)
        self.assertNotIn(('two',42),app.reply_drafts)
        app.update_reply.assert_not_called()
        DesktopActions.clear_sent_reply(app, 'one', 42, 9)
        app.update_reply.assert_called_once()
