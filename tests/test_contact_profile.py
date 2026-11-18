import asyncio
from concurrent.futures import Future
from contextlib import ExitStack
from datetime import datetime,timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock,Mock,patch
from PIL import Image
from telethon import types as t
from tg_ascii.backend import TelegramBackend
from tg_ascii.contact_profile import ContactProfile,ProfileRequests,normalized_profile,prepare_avatar,profile_subtitle


class ProfileReadTests(unittest.TestCase):
    def fixture(self):
        app=NS(ui_account='one',service=NS(backend=object()),worker=Mock(),busy=False)
        futures=[];operations=[]
        def submit(operation,*callbacks):
            future=Future();futures.append(future);operations.append(operation);return future
        app.worker.submit.side_effect=submit
        requests=ProfileRequests(app,NS(winfo_exists=lambda:True),'one',app.service.backend)
        self.addCleanup(lambda:[operation.close() for operation in operations])
        self.addCleanup(lambda:[future.cancel() for future in futures])
        self.addCleanup(requests.close)
        return app,requests,futures

    def test_loading_does_not_lock_app_and_close_cancels_owned_read(self):
        app,requests,futures=self.fixture();operation=AsyncMock();done=Mock()
        requests.submit('profile',operation(),done)
        self.assertFalse(app.busy);self.assertFalse(futures[0].cancelled())
        requests.close();self.assertTrue(futures[0].cancelled())
        app.worker.submit.call_args.args[1]({'name':'old'});done.assert_not_called()

    def test_refresh_and_account_switch_discard_old_results_and_release_images(self):
        app,requests,_=self.fixture();operation=AsyncMock();done=Mock()
        requests.submit('profile',operation(),done);old=app.worker.submit.call_args.args[1]
        requests.reset();requests.submit('profile',operation(),done)
        image=Image.new('RGB',(8,8));old((Path('/unused'),image))
        with self.assertRaises(ValueError):image.getpixel((0,0))
        app.ui_account='two';app.worker.submit.call_args.args[1]({'name':'other'});done.assert_not_called()

    def test_replaced_request_same_generation_cannot_complete_new_one(self):
        app,requests,_=self.fixture();operation=AsyncMock();done=Mock()
        requests.submit('media:photos',operation(),done);old=app.worker.submit.call_args.args[1]
        requests.submit('media:photos',operation(),done)
        old(['old']);done.assert_not_called();self.assertIn('media:photos',requests.jobs)
        app.worker.submit.call_args.args[1](['new']);done.assert_called_once_with(['new'])

    def test_media_waits_until_tab_selected_and_does_not_refetch_same_page(self):
        view=NS(app=NS(preferences=NS(values={})),valid=lambda:True,selected=lambda:'info',selector=Mock(),order=['info','photos'],
                media=NS(rows={'photos':[]},queries={},pending={}),widgets={},fetch_media=Mock())
        view.build_media=lambda kind:view.widgets.__setitem__(kind,Mock())
        ContactProfile.changed(view);view.fetch_media.assert_not_called()
        view.selected=lambda:'photos';ContactProfile.changed(view);view.fetch_media.assert_called_once_with('photos')
        view.media.queries['photos']='';ContactProfile.changed(view);view.fetch_media.assert_called_once()

    def test_entry_opens_card_immediately_even_during_other_background_work(self):
        from tg_ascii.desktop_actions import DesktopActions
        app=NS(active=42,busy=True)
        with patch('tg_ascii.contact_profile.ContactProfile') as card:
            self.assertIs(DesktopActions.show_contact_profile(app),card.return_value)
        card.assert_called_once_with(app,42)

    def test_actions_using_global_busy_wait_but_local_refresh_remains_available(self):
        view=NS(valid=lambda:True,app=NS(busy=True));callback=Mock()
        ContactProfile.action(view,callback,True);callback.assert_not_called()
        ContactProfile.action(view,callback);callback.assert_called_once()
        view.app.busy=False;ContactProfile.action(view,callback,True);self.assertEqual(callback.call_count,2)

    def test_photo_activation_obeys_busy_and_account_guards(self):
        app=NS(busy=True,open_image_message=Mock())
        view=NS(app=app,account='one',backend=object(),peer=7,pages={'photos':Mock()},
                widgets={},media_status={},media_more={},valid=Mock(return_value=True),fetch_media=Mock())
        with patch('tg_ascii.contact_profile.FlowFrame'),patch('tg_ascii.contact_profile.ttk.Label'),\
             patch('tg_ascii.contact_profile.ttk.Button'),patch('tg_ascii.contact_profile.SharedPhotoGrid') as grid:
            ContactProfile.build_media(view,'photos')
        activate=grid.call_args.args[-1];message=NS(id=1)
        activate(message);app.open_image_message.assert_not_called()
        app.busy=False;activate(message);app.open_image_message.assert_called_once_with(message,7)
        view.valid.return_value=False;activate(message);app.open_image_message.assert_called_once()

    def test_hiding_every_demo_tab_keeps_change_handler_safe(self):
        view=NS(valid=lambda:True,order=[],selected=Mock())
        ContactProfile.changed(view);view.selected.assert_not_called()


class ProfileModelTests(unittest.TestCase):
    def test_demo_and_group_subtitle_are_clear_without_invented_online_state(self):
        profile=normalized_profile({'id':3,'name':'Synthetic','username':'synthetic'})
        self.assertEqual(profile['usernames'],['synthetic']);self.assertEqual(profile_subtitle(profile),'')
        group=normalized_profile({'kind':'group','is_user':False,'members_count':1200,'online_count':2})
        self.assertIn('1,200',profile_subtitle(group));self.assertIn('2',profile_subtitle(group))

    def test_avatar_crop_is_small_round_and_never_changes_original(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'photo.png';Image.new('RGB',(900,600),'red').save(path);before=path.read_bytes()
            result=prepare_avatar(path,96,True)
            self.assertEqual(result.size,(96,96));self.assertEqual(result.getpixel((0,0))[3],0)
            self.assertEqual(result.getpixel((48,48))[3],255);self.assertEqual(path.read_bytes(),before);result.close()


class ProfileConfirmationTests(unittest.TestCase):
    def confirm(self,operation,change):
        from tg_ascii.desktop_profile import DesktopProfile
        backend=NS(profile_block=Mock(return_value=object()),profile_change=Mock(return_value=object()))
        window=Mock();window.winfo_exists.return_value=True
        app=NS(demo=False,ui_account='one',service=NS(backend=backend),busy=False,call=Mock(),
               dialog=Mock(return_value=(window,Mock())))
        profile=dict(id=7,kind='user',is_user=True,is_self=False,usernames=[],name='Synthetic',
                     blocked=False,contact=False,can_invite=True)
        buttons={};variables=[]
        def button(parent,**kwargs):
            buttons[kwargs['text']]=kwargs['command'];return Mock()
        def variable(**kwargs):
            value=Mock();value.get.return_value=kwargs['value'];variables.append(value);return value
        def answer(*args,**kwargs):
            if change=='account':app.ui_account='two'
            elif change=='backend':app.service.backend=object()
            elif change=='window':window.winfo_exists.return_value=False
            elif change=='busy':app.busy=True
            return True
        with ExitStack() as patches:
            for name in ('ttk.Frame','ttk.Checkbutton','scrollable'):
                patches.enter_context(patch('tg_ascii.desktop_profile.'+name))
            patches.enter_context(patch('tg_ascii.contact_profile.copyable_field'))
            patches.enter_context(patch('tg_ascii.desktop_profile.ttk.Button',side_effect=button))
            patches.enter_context(patch('tg_ascii.desktop_profile.tk.BooleanVar',side_effect=variable))
            patches.enter_context(patch('tg_ascii.desktop_profile.tr',side_effect=lambda value:value))
            patches.enter_context(patch('tg_ascii.desktop_profile.messagebox.askyesno',side_effect=answer))
            if operation=='permissions':
                DesktopProfile.profile_permissions(app,profile,backend,'one')
                variables[0].get.return_value=False
                buttons['Save']()
            else:
                DesktopProfile.extend_profile(app,window,Mock(),Mock(),profile,backend,'one',summary=False)
                buttons['Block' if operation=='block' else 'Create link']()
        expected=0 if change else 1
        self.assertEqual(app.call.call_count,expected)
        self.assertEqual(backend.profile_block.call_count,expected if operation=='block' else 0)
        self.assertEqual(backend.profile_change.call_count,expected if operation!='block' else 0)

    def test_block_revalidates_context_after_confirmation(self):
        for change in ('account','backend','window','busy',None):
            with self.subTest(change=change):self.confirm('block',change)

    def test_invite_revalidates_context_after_confirmation(self):
        for change in ('account','backend','window','busy',None):
            with self.subTest(change=change):self.confirm('invite',change)

    def test_permissions_revalidate_context_after_confirmation(self):
        for change in ('account','backend','window','busy',None):
            with self.subTest(change=change):self.confirm('permissions',change)


class AvatarDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name);self.tasks=[]
        self.backend=NS(download_media=AsyncMock())
        async def download(photo,path,thumbnail=False):
            Image.new('RGB',(320,240) if thumbnail else (900,600),'red').save(path);return path
        self.backend.download_media.side_effect=download
        self.app=NS(demo=False,ui_account='one',service=NS(backend=self.backend),preview_dir=self.root,
                    full_profile_photo=Mock(),show_error=Mock())
        def submit(operation,done,failed):
            task=asyncio.create_task(operation);self.tasks.append(task)
            def completed(future):
                if future.cancelled():return
                error=future.exception()
                if error:failed(error)
                else:done(future.result())
            task.add_done_callback(completed);return task
        self.app.worker=NS(submit=submit)
        self.view=ContactProfile.__new__(ContactProfile)
        self.view.app=self.app;self.view.backend=self.backend;self.view.account='one';self.view.peer=7
        self.view.window=Mock();self.view.window.winfo_exists.return_value=True
        self.view.requests=ProfileRequests(self.app,self.view.window,'one',self.backend)
        self.view.profile=dict(name='Synthetic',full_photo_known=True,display_photo=object(),photo_id=19)
        self.view.art_cache={};self.view.images=[];self.view.avatar_size=96;self.view.style={}
        self.view.repaint=Mock();self.view.banner=Mock();self.view.avatar_bounds=(0,0,96,96)
        self.view.widgets={};self.view.media_status={};self.view.media_more={}
        async def cleanup():
            self.view.requests.close()
            await asyncio.gather(*self.tasks,return_exceptions=True)
        self.addAsyncCleanup(cleanup)

    async def load(self,local=None):
        with patch('tg_ascii.profile_customization.local_photo',return_value=local),patch('PIL.ImageTk.PhotoImage'):
            self.view.load_art();await self.tasks[-1];await asyncio.sleep(0)

    async def test_initial_avatar_only_fetches_thumbnail_and_click_opens_gallery(self):
        await self.load()
        self.backend.download_media.assert_awaited_once()
        initial=self.backend.download_media.call_args
        self.assertTrue(initial.kwargs['thumbnail']);self.assertTrue(initial.args[1].name.endswith('-thumb.jpg'))
        self.app.full_profile_photo.assert_not_called()
        with patch('tg_ascii.media_gallery.open_profile_gallery') as gallery:
            self.view.avatar_click(NS(x=40,y=40))
            gallery.assert_called_once_with(self.app,7,self.view.profile,path=self.view.avatar_path)
        # Original downloads belong to the independently closable gallery. The
        # contact card continues to perform only its small avatar thumbnail read.
        self.backend.download_media.assert_awaited_once()

    async def test_avatar_gallery_never_opens_for_stale_account_or_outside_avatar(self):
        await self.load()
        with patch('tg_ascii.media_gallery.open_profile_gallery') as gallery:
            self.view.avatar_click(NS(x=140,y=140));gallery.assert_not_called()
            self.app.ui_account='two'
            self.view.avatar_click(NS(x=40,y=40));gallery.assert_not_called()
        self.view.closed(NS(widget=self.view.window))
        self.assertFalse(self.view.requests.jobs)

    async def test_local_photo_opens_its_original_without_server_request(self):
        path=self.root/'local.png';Image.new('RGB',(900,600),'blue').save(path)
        await self.load(path);self.view.avatar_click(NS(x=40,y=40))
        self.backend.download_media.assert_not_awaited();self.app.full_profile_photo.assert_called_once_with(path,'Synthetic')


class FullPhotoTests(unittest.IsolatedAsyncioTestCase):
    def photo(self,ident):return t.Photo(ident,1,b'',datetime.now(timezone.utc),[],2)
    async def test_fresh_full_user_replaces_cached_identity_and_removed_fields(self):
        client=AsyncMock();client.add_event_handler=Mock()
        client.get_entity.return_value=t.User(7,first_name='Old',username='old_name',premium=True,profile_color=t.PeerColor(color=2),emoji_status=t.EmojiStatus(8))
        fresh=t.User(7,first_name='New')
        client.return_value=NS(full_user=NS(about='Fresh'),users=[t.User(99,first_name='Unrelated'),fresh])
        result=await TelegramBackend(client).profile(7)
        self.assertEqual(result['name'],'New');self.assertEqual(result['username'],'')
        self.assertFalse(result['premium']);self.assertIsNone(result['profile_color']);self.assertIsNone(result['emoji_status'])
    async def test_personal_photo_precedes_public_then_fallback_and_removal_is_authoritative(self):
        client=AsyncMock();client.add_event_handler=Mock();client.get_entity.return_value=t.User(7,first_name='Synthetic')
        backend=TelegramBackend(client)
        personal,public,fallback=self.photo(1),self.photo(2),self.photo(3)
        full=NS(about='',personal_photo=personal,profile_photo=public,fallback_photo=fallback)
        client.return_value=NS(full_user=full)
        for expected in (personal,public,fallback,None):
            result=await backend.profile(7)
            self.assertIs(result['display_photo'],expected);self.assertTrue(result['full_photo_known'])
            self.assertEqual(result['photo_id'],getattr(expected,'id',None))
            if expected is personal:full.personal_photo=None
            elif expected is public:full.profile_photo=None
            elif expected is fallback:full.fallback_photo=None
        self.assertEqual(client.call_count,4)  # Each refresh is authoritative; no stale full-profile cache.


if __name__=='__main__':unittest.main()
