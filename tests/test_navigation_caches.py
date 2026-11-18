"""Browsing many chats must not retain unlimited reply/media metadata."""
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

from tg_ascii.backend import Message
from tg_ascii.desktop_modern import DesktopModern
from tg_ascii.desktop_plus import DesktopPlus
from tg_ascii.i18n import tr


class PreviewCacheTests(unittest.TestCase):
    def app(self):
        app=object.__new__(DesktopPlus)
        app.preferences=NS(values={'inline_media':True});app.demo=False
        app.ui_account='a';app.active=42;app.service=NS(backend=Mock())
        app.preview_cache={};app.preview_failed=set();app.preview_pending=set()
        app.preview_images={'visible':object()};app.preview_generation=3
        app.preview_dir=Path('/unused');app.insert_preview=Mock()
        app.jobs=[]
        def submit(coro,*callbacks):
            coro.close();app.jobs.append(callbacks)
        app.worker=NS(submit=submit)
        return app

    def test_browsing_thousands_of_previews_bounds_paths_without_dropping_visible_art(self):
        app=self.app();photo=app.preview_images['visible']
        for ident in range(1500):
            app.schedule_preview(NS(id=ident),f'm_{ident}',3)
            loaded,_=app.jobs.pop();loaded(Path(f'{ident}.jpg'))
        self.assertEqual(len(app.preview_cache),512)
        self.assertEqual(app.preview_cache[('a',42,1499)],Path('1499.jpg'))
        self.assertNotIn(('a',42,0),app.preview_cache)
        self.assertIs(app.preview_images['visible'],photo)
        self.assertFalse(app.preview_pending)
        self.assertEqual(app.insert_preview.call_count,1500)
        app.schedule_preview(NS(id=1499),'existing',3)
        self.assertFalse(app.jobs)
        app.insert_preview.assert_called_with((3,'existing',Path('1499.jpg')))

    def test_unavailable_previews_bound_negative_cache_and_suppress_repeated_requests(self):
        app=self.app()
        for ident in range(1500):
            app.schedule_preview(NS(id=ident),f'm_{ident}',3)
            _,failed=app.jobs.pop();failed(OSError('not available'))
        self.assertEqual(len(app.preview_failed),1024)
        self.assertFalse(app.preview_pending)
        key=next(iter(app.preview_failed))
        app.schedule_preview(NS(id=key[2]),'retry',3)
        self.assertFalse(app.jobs)
        app.insert_preview.assert_not_called()


class ReplyCacheTests(unittest.TestCase):
    def app(self):
        app=object.__new__(DesktopModern)
        app.ui_account='a';app.active=42;app.demo=app.busy=False
        app.reply_cache={};app.reply_pending=set();app.reply_drafts={}
        app.messages=[];app.update_reply=Mock();app.render_messages=Mock()
        app.editor=Mock();app.root=Mock()
        app.service=NS(backend=NS(reply_contexts=AsyncMock(),message_palettes=AsyncMock()))
        app.message_palettes={'a':{}};app.palette_pending=set()
        app.preferences=NS(values={'bubbles':False})
        app.jobs=[]
        def submit(coro,*callbacks):
            coro.close();app.jobs.append(callbacks)
        app.worker=NS(submit=submit)
        return app

    def message(self,ident,reply=None):
        return Message(ident,'Sender',f'Message {ident}','12:00',reply_to_id=reply)

    def test_missing_art_bounds_negative_cache_and_delivers_every_subscriber(self):
        app=self.app();app.preview_cache={};app.preview_failed=set();app.media_requests={}
        first,second=Mock(),Mock();operation=AsyncMock()
        for ident in range(1500):
            key=('a','emoji',ident)
            app.fetch_art(key,operation,first)
            app.fetch_art(key,operation,second)
            self.assertEqual(len(app.jobs),1)
            loaded,_=app.jobs.pop();loaded(None)
        self.assertEqual(len(app.preview_failed),1024)
        self.assertFalse(app.media_requests)
        self.assertEqual(first.call_count,1500)
        self.assertEqual(second.call_count,1500)
        first.assert_called_with(None);second.assert_called_with(None)
        operation.assert_called_with()
        self.assertEqual(operation.call_count,1500)
        app.fetch_art(next(iter(app.preview_failed)),operation,first)
        self.assertFalse(app.jobs)
        self.assertEqual(operation.call_count,1500)

    def test_old_chats_are_evicted_while_visible_missing_and_composed_contexts_survive(self):
        app=self.app();visible=self.message(1);composed=self.message(3)
        app.messages=[self.message(50,1),self.message(51,2)]
        app.reply_drafts[('a',42)]=3
        app.remember_replies({('a',42,1):visible,('a',42,2):None,('a',42,3):composed})
        stale=self.message(1)
        app.remember_replies({('other',peer,1):stale for peer in range(2000)})
        self.assertEqual(len(app.reply_cache),1024)
        self.assertIs(app.reply_cache[('a',42,1)],visible)
        self.assertIsNone(app.reply_cache[('a',42,2)])
        self.assertIs(app.reply_cache[('a',42,3)],composed)
        self.assertNotIn(('other',0,1),app.reply_cache)
        self.assertIs(app.reply_cache[('other',1999,1)],stale)
        app.ensure_message_accents()
        self.assertFalse(app.jobs)  # Missing visible context is still negatively cached.

    def test_both_reply_actions_use_bounded_storage_and_preserve_new_composer(self):
        for menu in (False,True):
            with self.subTest(menu=menu):
                app=self.app();app.reply_cache={('a',0,i):None for i in range(1024)}
                from tg_ascii.backend import Chat
                app.chats=[Chat(42,'Synthetic recipient')]
                message=self.message(7)
                if menu:
                    with patch('tg_ascii.app_dialogs.popup_menu') as popup:
                        app.message_actions(message)
                        dict(popup.call_args.args[1])[tr('Reply')]()
                else:app.reply_message(message)
                self.assertEqual(len(app.reply_cache),1024)
                self.assertEqual(app.reply_drafts[('a',42)],7)
                self.assertIs(app.reply_cache[('a',42,7)],message)
                app.update_reply.assert_called_once()
                app.editor.focus_set.assert_called_once()

    def test_fetched_reply_batch_is_bounded_and_delivery_refreshes_current_chat(self):
        app=self.app();app.reply_cache={('a',0,i):None for i in range(1024)}
        app.messages=[self.message(50,1),self.message(51,2)]
        app.ensure_message_accents()
        self.assertEqual(app.reply_pending,{('a',42,1),('a',42,2)})
        loaded,_=app.jobs.pop();reply=self.message(1);loaded({1:reply})
        self.assertEqual(len(app.reply_cache),1024)
        self.assertIs(app.reply_cache[('a',42,1)],reply)
        self.assertIsNone(app.reply_cache[('a',42,2)])
        self.assertFalse(app.reply_pending)
        app.render_messages.assert_called_once_with(False)
        app.ensure_message_accents()
        self.assertFalse(app.jobs)

    def test_palette_failure_does_not_deliver_or_clear_the_separate_reply_request(self):
        app=self.app();app.message_palettes={};app.messages=[self.message(50,1)]
        app.ensure_message_accents()
        self.assertEqual(len(app.jobs),2)
        _,palette_failed=app.jobs[0]
        palette_failed(OSError('palette unavailable'))
        self.assertFalse(app.palette_pending)
        self.assertEqual(app.message_palettes,{'a':{}})
        self.assertEqual(app.reply_pending,{('a',42,1)})
        self.assertFalse(app.reply_cache)
        reply=self.message(1);reply_loaded,_=app.jobs[1];reply_loaded({1:reply})
        self.assertIs(app.reply_cache[('a',42,1)],reply)
        self.assertFalse(app.reply_pending)
