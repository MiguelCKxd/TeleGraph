"""Work scales with visible rows and changed content, without live accounts."""
import tkinter as tk
import unittest
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from telethon import types

from tg_ascii.backend import Chat, Message
from tg_ascii.bubbles import cached_measure, rich_runs
from tg_ascii.desktop_plus import DesktopPlus
from tg_ascii.ui_work import sync_tree_rows, visible_tree_rows


class Tree:
    def __init__(self,count=5000):
        self.rows={str(i):f'Chat {i}' for i in range(count)}
        self.reads=0;self.writes=[];self.fractions=(0, .002);self.visible=True
        self._synced_tree_order=tuple(self.rows)
    def get_children(self):return tuple(self.rows)
    def item(self,ident,option=None,**values):
        if 'text' in values:self.rows[ident]=values['text'];self.writes.append(ident)
        else:self.reads+=1
        return self.rows[ident]
    def insert(self,*args,iid,**values):self.rows[iid]=values['text']
    def set_children(self,*args):pass
    def delete(self,*ids):
        for ident in ids:self.rows.pop(ident)
    def winfo_exists(self):return True
    def winfo_viewable(self):return self.visible
    def winfo_height(self):return 400
    def yview(self):return self.fractions


class TreeWorkTests(unittest.TestCase):
    def test_spanish_index_preserves_every_legacy_label_and_catalogue_override(self):
        from tg_ascii import i18n
        from tg_ascii.translations import CATALOGUES
        previous=i18n.get_language()
        try:
            i18n.set_language('es')
            for value in set(i18n.TRANSLATIONS)|set(i18n.TRANSLATIONS.values())|set(CATALOGUES['es'])|{'Unknown fixture'}:
                english=i18n.TRANSLATIONS.get(value,value)
                fallback=next((key for key,target in i18n.TRANSLATIONS.items() if target==english),value)
                self.assertEqual(i18n.tr(value),i18n.brand(CATALOGUES['es'].get(english,fallback)))
        finally:i18n.set_language(previous)

    def test_unchanged_labels_do_not_cross_tcl_for_every_chat(self):
        tree=Tree();rows=list(tree.rows.items())
        sync_tree_rows(tree,rows);tree.reads=0
        for _ in range(10):sync_tree_rows(tree,rows)
        self.assertEqual(tree.reads,0)
        self.assertEqual(tree.writes,[])
        changed = [(ident, 'Unread' if ident == '3' else label) for ident, label in rows]
        sync_tree_rows(tree, changed)
        self.assertEqual(tree.writes, ['3'])
        self.assertEqual(tree.rows['3'], 'Unread')
        tree.writes.clear()
        sync_tree_rows(tree, changed)
        self.assertEqual(tree.writes, [])
        sync_tree_rows(tree, rows)
        self.assertEqual(tree.writes, ['3'])

    def test_viewport_is_bounded_even_before_scroll_fraction_settles(self):
        tree=Tree()
        self.assertLessEqual(len(visible_tree_rows(tree)),36)
        tree.fractions=(0,1)
        self.assertLessEqual(len(visible_tree_rows(tree)),36)
        tree.fractions=(.5,.502)
        self.assertIn('2500',visible_tree_rows(tree))
        tree.visible=False
        self.assertEqual(visible_tree_rows(tree),())

    def test_thousands_of_chats_schedule_only_two_visible_avatar_jobs(self):
        app=object.__new__(DesktopPlus)
        app.demo=app.closed=app.closing=False;app.ui_account='a'
        app.chat_list=Tree();app.chats=[Chat(i,f'Chat {i}') for i in range(5000)]
        app._chat_by_id={c.id:c for c in app.chats}
        app.service=NS(backend=Mock());app.preview_dir=Path('/unused')
        app.animation_player=Mock();app.preferences=NS(values={'animated_emoji':True})
        app.avatar_images=OrderedDict();app.preview_failed=set();app.preview_pending=set()
        app._avatar_pending=set();app._avatar_status={};app._avatar_displayed={}
        submitted=[]
        def submit(coro,*callbacks):submitted.append(coro);coro.close()
        app.worker=NS(submit=submit)
        app.load_avatars();app.load_avatars()
        from tg_ascii.desktop_plus import AVATAR_CONCURRENCY
        self.assertEqual(len(submitted),AVATAR_CONCURRENCY)
        self.assertEqual(app._avatar_pending,{('a',i,'avatar') for i in range(AVATAR_CONCURRENCY)})
        self.assertEqual(app.avatar_images,{})

    def test_avatar_native_bitmaps_have_a_bounded_cache(self):
        app=object.__new__(DesktopPlus)
        app.avatar_images=OrderedDict();app._avatar_status={}
        for i in range(1000):app.remember_avatar(('a',i,'avatar'),object())
        self.assertEqual(len(app.avatar_images),256)
        self.assertIn(('a',999,'avatar'),app.avatar_images)
        self.assertNotIn(('a',0,'avatar'),app.avatar_images)


class RichRunWorkTests(unittest.TestCase):
    def test_explicit_telegram_link_overrides_detected_url_and_preserves_custom_emoji(self):
        raw='visit example.com 😀 now'
        entities=(types.MessageEntityTextUrl(0,24,'https://different.example'),
                  types.MessageEntityCustomEmoji(18,2,42))
        value=Message(1,'Sender',raw,'12:00',raw_text=raw,entities=entities)
        self.assertEqual(list(rich_runs(value)),[
            ('visit example.com ','https://different.example',None),
            ('◇',None,42),(' now','https://different.example',None)])

    def test_plain_text_returns_one_span_and_preserves_surrogates(self):
        text='plain 😀\ntext'*1000
        value=Message(1,'Sender',text,'12:00')
        self.assertEqual(list(rich_runs(value)),[(text,None,None)])
        invalid=Message(2,'Sender','😀 x','12:00',entities=(types.MessageEntityCustomEmoji(1,1,3),))
        self.assertEqual(list(rich_runs(invalid)),[('😀 x',None,None)])

    def test_font_measure_cache_reuses_small_text_but_does_not_retain_huge_messages(self):
        face=NS(measure=Mock(side_effect=len))
        measure=cached_measure(face)
        for _ in range(30):self.assertEqual(measure('hello'),5)
        face.measure.assert_called_once_with('hello')
        for _ in range(2):measure('x'*5000)
        self.assertEqual(face.measure.call_count,3)
        for i in range(1500):measure(str(i))
        measure('hello')
        self.assertEqual(face.measure.call_count,1504)


class PhotoDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # These check the default path (threads, two at once).
        from tg_ascii import decode_pool
        decode_pool.configure({'advanced_features': {'process_decoding': False}})
        self.addCleanup(decode_pool.configure, {})

    async def test_shared_request_survives_a_destroyed_previous_owner(self):
        app=object.__new__(DesktopPlus);app.closed=app.closing=False
        app.preferences=NS(values={'animated_emoji':True});app.animation_player=Mock()
        pending=[];app.worker=NS(submit=lambda *args:pending.append(args))
        old=Mock();fresh=Mock();valid=Mock(side_effect=[True,True,tk.TclError('destroyed')])
        app.request_photo('same.png',(20,20),old,valid=valid)
        app.request_photo('same.png',(20,20),fresh)
        self.assertEqual(len(pending),1)
        coro,loaded,_=pending[0];coro.close();loaded(('frames','durations'))
        old.assert_not_called();fresh.assert_called_once()

    async def test_closed_views_are_removed_before_queued_images_are_decoded(self):
        app=object.__new__(DesktopPlus);app.closed=app.closing=False
        app.preferences=NS(values={'animated_emoji':True});app.animation_player=Mock()
        pending=[];app.worker=NS(submit=lambda *args:pending.append(args))
        current=[0];delivered=[]
        for index in range(100):
            current[0]=index
            app.request_photo(f'{index}.png',(20,20),lambda _,i=index:delivered.append(i),
                              valid=lambda i=index:current[0]==i)
        self.assertEqual(len(pending),2)
        first,loaded,_=pending.pop(0);first.close();loaded(('frames','durations'))
        self.assertEqual(len(pending),2)  # Second in-flight request and latest queued image.
        self.assertEqual(len(app._photo_requests),2)
        for coro,loaded,_ in pending:
            coro.close();loaded(('frames','durations'))
        self.assertEqual(delivered,[99])
        self.assertEqual(app._photo_requests,{})

    async def test_decode_is_off_thread_shared_and_stale_views_never_receive_art(self):
        app=object.__new__(DesktopPlus)
        app.closed=app.closing=False
        app.preferences=NS(values={'animated_emoji':True})
        app.animation_player=Mock();app.animation_player.prepare.return_value=('frames','durations')
        app.animation_player.photo.return_value='photo'
        pending=[]
        app.worker=NS(submit=lambda *args:pending.append(args))
        old=Mock();new=Mock();live=[True]
        app.request_photo('asset.png',(30,30),old,valid=lambda:live[0])
        live[0]=False
        app.request_photo('asset.png',(30,30),new)
        self.assertEqual(len(pending),1)
        coro,loaded,_=pending.pop()
        with patch('tg_ascii.desktop_plus.asyncio.to_thread',new=AsyncMock(return_value=('frames','durations'))) as thread:
            loaded(await coro)
        thread.assert_awaited_once_with(app.animation_player.prepare,'asset.png',(30,30),True,None)
        old.assert_not_called();new.assert_called_once_with('photo')
        self.assertEqual(app._photo_requests,{})

    async def test_close_drops_pending_decoded_results(self):
        app=object.__new__(DesktopPlus);app.closed=app.closing=False
        app.preferences=NS(values={'animated_emoji':True});app.animation_player=Mock()
        pending=[];app.worker=NS(submit=lambda *args:pending.append(args))
        callback=Mock();app.request_photo('asset.png',(20,20),callback)
        coro,loaded,_=pending[0];coro.close()
        app.closing=True;loaded(('frames','durations'))
        callback.assert_not_called();app.animation_player.photo.assert_not_called()
        self.assertEqual(app._photo_requests,{})
