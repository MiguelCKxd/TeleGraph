import asyncio
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import tkinter as tk
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

from telethon.errors import FileReferenceExpiredError
from tg_ascii.desktop_media_lifetime import ViewerMedia, private_preview, revoke, mark_contents, export_blocked, source_message
from tg_ascii.media_gallery import GalleryItem, MediaGallery, open_chat_gallery
from tg_ascii.desktop_modern import DesktopModern


class MediaLifetimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = tk.Tk(); self.root.withdraw()
        self.backend = NS()
        async def download(media, target, **kwargs):
            target = Path(target).with_suffix('.jpg')
            target.write_bytes(b'fresh original')
            return target
        self.backend.download_media = AsyncMock(side_effect=download)
        self.app = NS(ui_account='a', service=NS(backend=self.backend), preview_dir=Path(self.folder.name),
                      root=self.root, closed=False, closing=False, chats=[], show_error=Mock())
        self.expired = Mock()
        self.leases = []

    def tearDown(self):
        for lease in self.leases:lease.close()
        self.root.destroy()
        self.folder.cleanup()

    def lease(self, message=None, *, peer=42, ident=7, app=None):
        window = tk.Toplevel(self.root)
        lease = ViewerMedia(app or self.app, window, 'a', self.backend, peer, ident,
                            message or NS(protected=True), self.expired)
        self.leases.append(lease)
        return lease

    async def test_protected_uses_private_file_purges_only_matching_old_copies_and_deletes_on_close(self):
        old = self.app.preview_dir / 'a-42-7-gallery-original.media'; old.write_bytes(b'old')
        neighbor = self.app.preview_dir / 'a-42-70-thumb.jpg'; neighbor.write_bytes(b'keep')
        lease = self.lease()
        path = await lease.download('source')
        self.assertNotEqual(path, old)
        self.assertEqual(path.read_bytes(), b'fresh original')
        self.assertFalse(old.exists()); self.assertTrue(neighbor.exists())
        self.assertEqual(self.backend.download_media.call_args.args[1].suffix, '')
        lease.window.destroy()
        self.assertFalse(path.exists())
        self.assertNotIn(lease, self.app._private_media_leases)

    async def test_expired_message_level_ttl_never_downloads(self):
        lease = self.lease(NS(ttl_period=5, date=datetime(2000,1,1,tzinfo=timezone.utc)))
        with self.assertRaises(PermissionError):await lease.download('source')
        self.backend.download_media.assert_not_called()

    async def test_read_ttl_clears_file_and_notifies_viewer(self):
        lease = self.lease(NS(media=NS(ttl_seconds=2)))
        path = await lease.download('source')
        with patch('tg_ascii.desktop_media_lifetime.time.time',return_value=100):lease.viewed()
        lease.window.after_cancel(lease.timer)
        with patch('tg_ascii.desktop_media_lifetime.time.time',return_value=103):lease.tick()
        self.assertFalse(path.exists());self.expired.assert_called_once()

    async def test_account_change_clears_file_and_timers(self):
        lease = self.lease();path = await lease.download('source')
        timer = lease.timer
        lease.window.after_cancel(timer)
        self.app.ui_account = 'b';lease.tick()
        self.assertFalse(path.exists());self.assertTrue(lease.closed)
        self.assertNotIn(timer,self.root.tk.call('after','info'))

    async def test_cancelled_download_cannot_recreate_file_after_close(self):
        entered = asyncio.Event()
        async def late(media,target,**kwargs):
            entered.set()
            try:await asyncio.Event().wait()
            except asyncio.CancelledError:
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(b'late')
                return target
        self.backend.download_media.side_effect = late
        lease = self.lease()
        task = asyncio.create_task(lease.download('source'))
        await entered.wait();directory=lease.directory;lease.close()
        with self.assertRaises(PermissionError):await task
        self.assertFalse(directory.exists())

    async def test_file_reference_renewal_that_becomes_protected_changes_destination(self):
        lease = self.lease(NS(media='old'))
        download = self.backend.download_media.side_effect
        calls = 0
        async def renewing(media,target,**kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:raise FileReferenceExpiredError(None)
            return await download(media,target,**kwargs)
        self.backend.download_media.side_effect = renewing
        self.backend.media_message = AsyncMock(return_value=NS(media='new',noforwards=True))
        gallery = NS(app=self.app,backend=self.backend,account='a',peer=42,lease=lease)
        path = await MediaGallery.download(gallery,GalleryItem(7,'old'),'original')
        self.assertTrue(lease.restricted)
        self.assertEqual(path.parent,lease.directory)
        self.assertFalse((self.app.preview_dir/'a-42-7-gallery-original.media').exists())

    async def test_ordinary_gallery_original_still_reuses_known_cache(self):
        lease = self.lease(NS(media='ordinary'))
        old = self.app.preview_dir/'a-42-7-gallery-original.media';old.write_bytes(b'exact')
        gallery = NS(app=self.app,backend=self.backend,account='a',peer=42,lease=lease)
        self.assertEqual(await MediaGallery.download(gallery,GalleryItem(7,'ordinary'),'display'),old)
        self.backend.download_media.assert_not_called()
        lease.close();self.assertTrue(old.exists())

    async def test_delete_event_scopes_account_peer_and_channel_ids(self):
        first=self.lease();channel=self.lease(peer=-1000000000042)
        second=self.lease(ident=8)
        revoke(self.app,'b',42,{7});self.assertFalse(first.closed)
        revoke(self.app,'a',None,{7})
        self.assertTrue(first.closed);self.assertFalse(channel.closed);self.assertFalse(second.closed)

    async def test_linked_window_keeps_pinned_account_and_lock_owner(self):
        linked=NS(app=self.app,ui_account='a',service=NS(backend=self.backend),preview_dir=self.app.preview_dir)
        lease=self.lease(app=linked);path=await lease.download('source')
        self.app.ui_account='b';self.assertTrue(lease.active())
        self.app._app_locked=True;revoke(self.app)
        self.assertFalse(path.exists());self.assertTrue(lease.closed)

    async def test_rebinding_to_player_does_not_keep_loading_window_timer(self):
        lease=self.lease();old=lease.window;timer=lease.timer
        new=tk.Toplevel(self.root);lease.attach(new);old.destroy()
        self.assertFalse(lease.closed)
        self.assertNotIn(timer,self.root.tk.call('after','info'))
        new.destroy();self.assertTrue(lease.closed)

    async def test_reopening_or_refreshing_does_not_restart_viewing_deadline(self):
        first=self.lease(NS(media=NS(ttl_seconds=2)))
        with patch('tg_ascii.desktop_media_lifetime.time.time',return_value=100):first.viewed()
        first.close()
        second=self.lease(NS(media=NS(ttl_seconds=2)))
        self.assertEqual(second.deadline,102)
        with patch('tg_ascii.desktop_media_lifetime.time.time',return_value=103):
            with self.assertRaises(PermissionError):await second.download('source')

    async def test_contents_acknowledgement_is_scoped_and_sent_once_after_view(self):
        queued=[]
        self.app.worker=NS(submit=lambda operation,*_:queued.append(operation))
        self.backend.client=AsyncMock()
        first=self.lease(NS(media=NS(ttl_seconds=10)))
        self.assertEqual(queued,[])
        first.viewed();first.viewed()
        second=self.lease(NS(media=NS(ttl_seconds=10)));second.viewed()
        self.assertEqual(len(queued),1)
        await queued.pop()
        request=self.backend.client.call_args.args[0]
        self.assertEqual(request.id,[7])
        self.assertEqual(type(request).__module__,'telethon.tl.functions.messages')
        self.backend.client.get_input_entity=AsyncMock(return_value='channel')
        await mark_contents(self.backend,-1000000000042,9)
        request=self.backend.client.call_args.args[0]
        self.assertEqual(request.id,[9]);self.assertEqual(request.channel,'channel')

    async def test_view_once_cannot_be_reopened_after_closing(self):
        first=self.lease(NS(media=NS(ttl_seconds=2147483647)))
        first.viewed();first.close()
        second=self.lease(NS(media=NS(ttl_seconds=2147483647)))
        with self.assertRaises(PermissionError):await second.download('source')

    async def test_secret_plaintext_is_temporary_but_nonexpiring_exports_stay_allowed(self):
        from tg_ascii.secret_chats import secret_peer_id
        peer=secret_peer_id(12)
        row={'id':7,'ttl':0,'expires_at':None}
        manager=NS(session_for_peer=lambda _:NS(messages=[row]),_prune_expired_sync=Mock(),
                   _record_to_message=lambda *_:NS(id=7,media='secret bytes',protected=True))
        self.backend.secret_chats=manager
        message=NS(id=7,protected=True)
        self.assertFalse(export_blocked(message,self.app,peer))
        self.assertFalse(private_preview(self.app,message,peer))
        lease=self.lease(message,peer=peer)
        self.assertTrue(lease.restricted);self.assertFalse(lease.export_blocked)
        path=await lease.download('secret bytes')
        lease.close();self.assertFalse(path.exists())
        row['ttl']=20
        self.assertTrue(export_blocked(message,self.app,peer))

    async def test_secret_media_refresh_uses_local_record_without_cloud_rpc(self):
        from tg_ascii.secret_chats import secret_peer_id
        peer=secret_peer_id(12)
        row={'id':7,'ttl':20,'expires_at':123}
        self.backend.media_message=AsyncMock()
        self.backend.secret_chats=NS(session_for_peer=lambda _:NS(messages=[row]),_prune_expired_sync=Mock(),
            _record_to_message=lambda *_:NS(id=7,media='decrypted descriptor'))
        message=await source_message(self.backend,peer,7)
        self.assertEqual(message.expires_at,123)
        self.backend.media_message.assert_not_called()

    async def test_audio_player_destroys_private_file_and_playback_timer(self):
        from tg_ascii.desktop_tools import DesktopTools
        from tg_ascii.i18n import tr
        def dialog(*_):
            window=tk.Toplevel(self.root);frame=tk.Frame(window);frame.pack()
            return window,frame
        self.app.dialog=dialog;self.app.audio_jobs=[];self.app.active=42
        lease=self.lease();path=await lease.download('audio')
        job=NS(done=NS(is_set=lambda:False),seconds=0,error=None,stop=Mock())
        with patch('tg_ascii.desktop_tools.AudioJob',return_value=NS(play=lambda _:job)):
            window=DesktopTools.audio_dialog(self.app,path,sending=False,media_lease=lease)
            frame=window.winfo_children()[0]
            play=next(widget for widget in frame.winfo_children()
                      if widget.winfo_class()=='TButton' and widget.cget('text')==tr('Play'))
            play.invoke()
            timers=set(self.root.tk.call('after','info'))
            window.destroy()
        job.stop.assert_called_once()
        self.assertFalse(path.exists())
        self.assertFalse(timers.intersection(self.root.tk.call('after','info')))

    async def test_native_copy_keeps_source_until_done_even_if_viewer_closes(self):
        lease=self.lease(NS(id=7))
        path=await lease.download('ordinary')
        lease.retain_copy();lease.window.destroy()
        self.assertTrue(path.exists())
        lease.release_copy()
        self.assertFalse(path.exists())

    async def test_native_copy_completion_can_retire_loading_view_without_deleting_external_copy(self):
        lease=self.lease(NS(id=7));path=await lease.download('ordinary')
        external=self.app.preview_dir/'external.jpg';external.write_bytes(path.read_bytes())
        lease.retain_copy();lease.release_copy(close=True)
        self.assertTrue(lease.closed);self.assertFalse(path.exists())
        self.assertEqual(external.read_bytes(),b'fresh original')


class MediaExportTests(unittest.TestCase):
    def test_download_delivered_after_deadline_never_repaints_image(self):
        item=GalleryItem(7,'media')
        gallery=NS(item=item,valid=lambda:True,lease=NS(active=lambda:False,expire=Mock()),window=Mock())
        MediaGallery.loaded(gallery,'private.jpg',item)
        gallery.window._set_media.assert_not_called()
        gallery.lease.expire.assert_called_once()

    def test_protected_gallery_cannot_export_or_launch_external_viewer(self):
        gallery=NS(valid=lambda:True,path=Path('/private'),stream=None,
                   lease=NS(closed=False,restricted=True,export_blocked=True),status=Mock())
        gallery.exportable=lambda:MediaGallery.exportable(gallery)
        with patch('tg_ascii.media_gallery.filedialog.asksaveasfilename') as save,patch('tg_ascii.native_open.open_with_system') as launch:
            MediaGallery.save(gallery);MediaGallery.open_native(gallery)
            save.assert_not_called();launch.assert_not_called()

    def test_direct_native_open_rejects_message_level_ttl(self):
        app=NS(demo=False,ui_account='a',active=42,service=NS(backend=Mock()),show_error=Mock())
        DesktopModern.open_message_natively(app,NS(ttl_period=10))
        self.assertIsInstance(app.show_error.call_args.args[0],PermissionError)

    def test_gallery_keeps_full_message_metadata(self):
        message=NS(id=7,media='photo',text='',filename='',ttl_period=60)
        with patch('tg_ascii.media_gallery.MediaGallery') as gallery:
            open_chat_gallery(NS(active=42),message)
        self.assertIs(gallery.call_args.args[2].message,message)

    def test_private_preview_never_uses_cached_file_and_purge_is_deduplicated(self):
        worker=Mock();worker.submit.side_effect=lambda operation,*_:operation.close()
        app=NS(ui_account='a',service=NS(backend=Mock()),worker=worker,
               preview_cache={('a',42,7):Path('/old')})
        message=NS(id=7,protected=True)
        self.assertTrue(private_preview(app,message,42));self.assertTrue(private_preview(app,message,42))
        self.assertEqual(app.preview_cache,{})
        worker.submit.assert_called_once()


if __name__=='__main__':unittest.main()
