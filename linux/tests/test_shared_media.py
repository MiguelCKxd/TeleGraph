import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock,AsyncMock,patch
from tg_ascii.shared_media import MediaPages
from tg_ascii.desktop import Desktop


class SharedMediaTests(unittest.TestCase):
    def test_profile_peer_is_accepted_by_actual_desktop_override(self):
        ui=Desktop.__new__(Desktop);ui.active=42;ui.busy=False;ui.demo=False
        with patch('tg_ascii.shared_media.SharedMediaBrowser') as browser:
            ui.message_browser(True,-100123);browser.assert_called_once_with(ui,True,-100123)

    def test_category_switch_does_not_discard_other_pending_category(self):
        pages=MediaPages(['photos','files'])
        photo,_=pages.begin('photos','');files,_=pages.begin('files','')
        self.assertTrue(pages.finish(files,[NS(id=9)]));self.assertTrue(pages.finish(photo,[NS(id=7)]))
        self.assertEqual(pages.rows['photos'][0].id,7);self.assertEqual(pages.rows['files'][0].id,9)

    def test_stale_query_result_and_stale_failure_are_discarded(self):
        pages=MediaPages(['files']);old,_=pages.begin('files','old');new,_=pages.begin('files','new')
        self.assertFalse(pages.finish(old,[NS(id=1)]));self.assertFalse(pages.fail(old))
        self.assertTrue(pages.finish(new,[NS(id=2)]));self.assertEqual(pages.queries['files'],'new')
        self.assertEqual([m.id for m in pages.rows['files']],[2])

    def test_pagination_deduplicates_and_stops_when_exhausted(self):
        pages=MediaPages(['files']);ticket,_=pages.begin('files','')
        pages.finish(ticket,[NS(id=i) for i in range(100,50,-1)])
        ticket,offset=pages.begin('files','',True);self.assertEqual(offset,51)
        self.assertIsNone(pages.begin('files','',True))
        pages.finish(ticket,[NS(id=51),NS(id=50)])
        self.assertEqual(len(pages.rows['files']),51);self.assertIsNone(pages.begin('files','',True))


class MediaTargetTests(unittest.IsolatedAsyncioTestCase):
    async def test_attachment_uses_profile_peer_and_ignores_late_other_account(self):
        ui=Desktop.__new__(Desktop);ui.active=42;ui.ui_account='a';ui.busy=False
        backend=NS(media_message=AsyncMock(return_value='media'));ui.service=NS(backend=backend);ui.media_dialog=Mock()
        pending=[];ui.call=lambda coro,done,status:pending.append((coro,done))
        message=NS(id=8,media_kind='file',filename='file.pdf',text='',size=10)
        ui.view_message_media(message,99)
        result=await pending[0][0];backend.media_message.assert_awaited_once_with(99,8)
        ui.ui_account='b';pending[0][1](result);ui.media_dialog.assert_not_called()

    async def test_audio_and_non_image_forward_explicit_peer(self):
        ui=Desktop.__new__(Desktop);ui.busy=False;ui.active=42;ui.play_message_audio=Mock()
        ui.view_message_media(NS(media_kind='audio'),99);ui.play_message_audio.assert_called_once()
        self.assertEqual(ui.play_message_audio.call_args.args[1],99)
        ui.view_message_media=Mock();message=NS(media_kind='file')
        ui.open_image_message(message,99);ui.view_message_media.assert_called_once_with(message,99)
