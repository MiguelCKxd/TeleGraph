import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image
from telethon import types

from tg_ascii.animated_emojis import animated_content, ensure_pack
from tg_ascii.animation import AnimationPlayer, decode_frames
from tg_ascii.backend import Message
from tg_ascii.bubbles import layout_text_run, rich_runs
from tg_ascii.desktop_modern import DesktopModern
from tg_ascii.emoji_documents import EmojiDocuments
from tg_ascii.message_tools import display_segments, entity_spans
from tg_ascii.rich_preview import fit_text, preview_runs
from tg_ascii.sticker_picker import StickerGrid, insert_selected_emoji
from tg_ascii.sticker_search import emoji_query
from tg_ascii.text_layout import cluster_ends


class EmojiLayoutTests(unittest.TestCase):
    def test_joined_emoji_flags_skin_tones_keycaps_and_accents_are_atomic(self):
        for glyph in ('👩🏽\u200d💻', '👨\u200d👩\u200d👧\u200d👦', '🇪🇸', '1️⃣', 'e\u0301', '🏴\U000e0067\U000e0062\U000e007f'):
            with self.subTest(glyph=glyph):
                self.assertEqual(cluster_ends(glyph), [len(glyph)])
                chunks, _, _ = layout_text_run(glyph + 'x', 0, 0, 0, 1, 10, len)
                self.assertEqual([value for _, _, value in chunks], [glyph, 'x'])
                self.assertEqual(list(preview_runs(glyph + 'x', limit=1)), [(glyph + '…', None)])
                self.assertEqual(fit_text(glyph + 'xyz', 2, len), ('…', True))
        self.assertEqual(cluster_ends('🇪🇸🇺🇦'), [2, 4])

    def test_invalid_zero_length_and_mid_surrogate_entities_never_block_render(self):
        text='😀 x'
        entities=(types.MessageEntityCustomEmoji(0,0,1),types.MessageEntityCustomEmoji(1,1,2),
                  types.MessageEntityCustomEmoji(2,-1,3))
        self.assertEqual(entity_spans(text,entities),([],[]))
        message=Message(1,'Ada',text,'12:00',raw_text=text,entities=entities)
        self.assertEqual(list(rich_runs(message)),[(text,None,None)])
        self.assertEqual(list(preview_runs(text,entities)),[(text,None)])

    def test_repeated_custom_emoji_occupy_independent_slots_after_astral_text(self):
        text='🚀 😀 x 😀'
        entities=(types.MessageEntityCustomEmoji(3,2,42),types.MessageEntityCustomEmoji(8,2,42))
        message=Message(1,'Ada',text,'12:00',raw_text=text,entities=entities)
        self.assertEqual(list(display_segments(message)),['🚀 ',42,' x ',42])
        self.assertEqual(list(rich_runs(message)),[('🚀 ',None,None),('◇',None,42),(' x ',None,None),('◇',None,42)])

    def test_standard_animation_preserves_surrounding_whitespace_and_format(self):
        bold=types.MessageEntityBold(0,5)
        message=Message(1,'Ada','  ❤️\n','12:00',raw_text='  ❤️\n',entities=(bold,))
        app=NS(ui_account='a',preferences=NS(values={'animated_emoji':True}),_standard_emoji_packs={'a':{'❤':NS(id=42)}})
        local=animated_content(app,message)
        self.assertEqual(local.entities[0],bold)
        self.assertEqual((local.entities[1].offset,local.entities[1].length),(2,2))
        self.assertEqual(list(display_segments(local)),['  ',42,'\n'])
        self.assertEqual(message.entities,(bold,))

    def test_keycap_search_uses_telegram_emoticon_parameter(self):
        self.assertTrue(emoji_query('1️⃣'));self.assertTrue(emoji_query('#️⃣'))
        self.assertTrue(emoji_query('©️'));self.assertFalse(emoji_query('copyright ©'))


class EmojiDocumentsTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_views_share_batches_and_cache_per_account(self):
        async def rpc(request):return [NS(id=ident,attributes=[]) for ident in request.document_id]
        backend=NS(client=AsyncMock(side_effect=rpc));catalogue=EmojiDocuments(backend)
        values=await asyncio.gather(*(catalogue.get([ident,ident]) for ident in range(205)))
        self.assertEqual([entry[0].id for entry in values],list(range(205)))
        self.assertEqual([len(call.args[0].document_id) for call in backend.client.call_args_list],[100,100,5])
        await catalogue.get([1,2,1]);self.assertEqual(backend.client.call_count,3)
        second=EmojiDocuments(backend);await second.get([1]);self.assertEqual(backend.client.call_count,4)

    async def test_cancelled_view_does_not_cancel_shared_metadata(self):
        started=asyncio.Event();release=asyncio.Event()
        async def rpc(request):started.set();await release.wait();return [NS(id=5,attributes=[])]
        backend=NS(client=AsyncMock(side_effect=rpc));catalogue=EmojiDocuments(backend)
        first=asyncio.create_task(catalogue.get([5]));await started.wait()
        second=asyncio.create_task(catalogue.get([5]));await asyncio.sleep(0)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):await first
        release.set();self.assertEqual((await second)[0].id,5)
        backend.client.assert_awaited_once();self.assertIsNone(catalogue.task)

    async def test_shutdown_cancels_pending_waiters_without_retained_jobs(self):
        started=asyncio.Event()
        async def rpc(request):started.set();await asyncio.Event().wait()
        catalogue=EmojiDocuments(NS(client=AsyncMock(side_effect=rpc)))
        waiter=asyncio.create_task(catalogue.get([1]));await started.wait();await catalogue.cancel()
        with self.assertRaises(asyncio.CancelledError):await waiter
        self.assertFalse(catalogue.pending);self.assertIsNone(catalogue.task)

    async def test_failure_can_retry_missing_documents_back_off_and_cache_is_bounded(self):
        backend=NS(client=AsyncMock(side_effect=OSError('offline')));catalogue=EmojiDocuments(backend)
        with self.assertRaises(OSError):await catalogue.get([1])
        backend.client.side_effect=None;backend.client.return_value=[]
        self.assertEqual(await catalogue.get([1]),[])
        self.assertEqual(await catalogue.get([1]),[])
        self.assertEqual(backend.client.call_count,2)
        catalogue.remember(NS(id=ident,attributes=[]) for ident in range(600))
        self.assertEqual(len(catalogue.cache),512)

    async def test_failed_standard_pack_retries_later_without_hammering_server(self):
        app=NS(demo=False,active=42,ui_account='a',preferences=NS(values={'animated_emoji':True}),
            messages=[Message(1,'Ada','❤️','12:00')],service=NS(backend=NS(client=AsyncMock()),entries={'a':1}),worker=Mock())
        with patch('tg_ascii.animation.renderer_available',return_value=True),patch('time.monotonic',return_value=100):
            ensure_pack(app);coroutine,_,failed=app.worker.submit.call_args.args;coroutine.close();failed(OSError())
            ensure_pack(app);app.worker.submit.assert_called_once()
        with patch('tg_ascii.animation.renderer_available',return_value=True),patch('time.monotonic',return_value=131):
            ensure_pack(app)
        self.assertEqual(app.worker.submit.call_count,2);app.worker.submit.call_args.args[0].close()


class EmojiArtworkTests(unittest.TestCase):
    def test_status_composes_worker_prepared_emoji_without_opening_animation_on_tk(self):
        widget=Mock();avatar=object();emoji=object()
        app=NS(demo=False,ui_account='a',service=NS(backend=None),root=Mock(),chat_list=widget,
               avatar_images={('a',42,'avatar'):avatar},_chat_by_id={42:NS(emoji_status_id=7)},
               emoji_art=Mock(),request_photo=Mock(),show_avatar=Mock())
        app.remember_avatar=lambda key,photo:app.avatar_images.__setitem__(key,photo)
        DesktopModern.decorate_chat_status(app,42,app._chat_by_id[42]);app.emoji_art.call_args.args[-1]('emoji.webm')
        args,options=app.request_photo.call_args
        self.assertEqual(args[:2],('emoji.webm',(20,20)));self.assertFalse(options['enabled']);self.assertTrue(options['valid']())
        frames=[]
        def bitmap(photo):
            image=Image.new('RGBA',(30,30) if photo is avatar else (20,20),'red');frames.append(image);return image
        with patch('PIL.Image.open',side_effect=AssertionError('Decode on Tk')),patch('PIL.ImageTk.getimage',side_effect=bitmap),patch('PIL.ImageTk.PhotoImage',return_value='composite'):
            args[2](emoji)
        app.show_avatar.assert_called_once_with(widget,42,'composite');self.assertFalse(options['valid']())
        for image in frames:
            with self.assertRaises(ValueError):image.getpixel((0,0))
        app._chat_by_id[42].emoji_status_id=8
        DesktopModern.decorate_chat_status(app,42,app._chat_by_id[42]);app.emoji_art.call_args.args[-1]('next.webp')
        current=app.request_photo.call_args.kwargs['valid'];self.assertTrue(current())
        app._chat_by_id[42].emoji_status_id=0;self.assertFalse(current())

    def test_header_avatar_request_rejects_old_header_and_changed_account(self):
        backend=NS(chat_header=AsyncMock(),avatar=AsyncMock())
        app=NS(update_chat_capabilities=Mock(),demo=False,active=42,ui_account='a',service=NS(backend=backend),bot_row=Mock(),bot_buttons={},
               header_avatar=Mock(),header_status_emoji=Mock(),activity=Mock(),worker=Mock(),preview_dir=Path('/cache'),request_photo=Mock())
        DesktopModern.refresh_header(app)
        callback=app.worker.submit.call_args.args[1]
        for call in app.worker.submit.call_args_list:call.args[0].close()
        callback('avatar.jpg');args,options=app.request_photo.call_args;self.assertTrue(options['valid']())
        args[2]('photo');app.header_avatar.configure.assert_called_with(image='photo')
        app.worker.submit.reset_mock();DesktopModern.refresh_header(app)
        for call in app.worker.submit.call_args_list:call.args[0].close()
        self.assertFalse(options['valid']());callback('old.jpg');self.assertEqual(app.request_photo.call_count,1)
        app.worker.submit.call_args.args[1]('new.jpg');self.assertEqual(app.request_photo.call_count,2)
        app.ui_account='b';self.assertFalse(app.request_photo.call_args.kwargs['valid']())

    def test_text_color_emoji_tints_rgb_and_keeps_alpha_without_mutating_shared_frames(self):
        class Photo:
            def __init__(self,frame,**kwargs):self.frame=frame
        frame=Image.new('RGBA',(8,8),(255,0,0,72));player=AnimationPlayer(Mock())
        with patch('PIL.ImageTk.PhotoImage',Photo):
            tinted=player.photo(__file__,(8,8),prepared=([frame],[100]),tint='#123456')
            self.assertEqual(tinted.frame.getpixel((0,0)),(18,52,86,72))
            ordinary=player.photo(__file__,(8,8),prepared=([frame],[100]))
            self.assertEqual(ordinary.frame.getpixel((0,0)),(255,0,0,72))
            self.assertIs(tinted,player.photo(__file__,(8,8),tint='#123456'))
        player.stop()

    def test_disabled_animation_decodes_only_first_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'emoji.gif'
            Image.new('RGB',(8,8),'red').save(path,save_all=True,append_images=[Image.new('RGB',(8,8),'blue')],duration=100)
            frames,durations=decode_frames(path,(8,8),animated=False)
            self.assertEqual(len(frames),1);self.assertEqual(durations,[100])

    def test_old_emoji_label_result_cannot_overwrite_new_chat_status(self):
        widget=Mock();app=NS(ui_account='a',emoji_art=Mock(),emoji_tint=Mock(return_value=None),request_photo=Mock())
        DesktopModern.label_emoji(app,widget,1,'a',None);old=app.emoji_art.call_args.args[-1]
        DesktopModern.label_emoji(app,widget,2,'a',None);new=app.emoji_art.call_args.args[-1]
        old('old.webp');app.request_photo.assert_not_called()
        new('new.webp');app.request_photo.assert_called_once()
        args,options=app.request_photo.call_args
        self.assertEqual(args[:2],('new.webp',(20,20)))
        self.assertIs(options['owner'],widget);self.assertIsNone(options['tint'])
        self.assertTrue(options['valid']())
        args[2]('photo');widget.configure.assert_called_with(image='photo')
        self.assertTrue(any(call.kwargs.get('cursor')=='hand2' for call in widget.configure.call_args_list))
        widget._emoji_request=object();self.assertFalse(options['valid']())
        new('late.webp');self.assertEqual(app.request_photo.call_count,1)
        app.ui_account='b';self.assertFalse(options['valid']())

    def test_cached_art_callback_survives_cache_eviction_and_closed_view(self):
        app=NS(preview_cache={'key':'image.webp'},root=Mock())
        done=Mock();DesktopModern.fetch_art(app,'key',None,done)
        app.preview_cache.clear();app.root.after_idle.call_args.args[0]()
        done.assert_called_once_with('image.webp')

    def test_grid_empty_right_margin_does_not_select_next_row(self):
        app=NS(canvas=Mock(),cell=100,columns=3,documents=[NS(id=i) for i in range(6)],repaint=Mock(),activate=Mock())
        app.canvas.canvasy.side_effect=lambda y:y
        StickerGrid.click(app,NS(x=320,y=20));app.activate.assert_not_called()
        StickerGrid.click(app,NS(x=20,y=120));app.activate.assert_called_once_with(app.documents[3])

    def test_keyboard_moves_selection_and_scrolls_without_sending(self):
        docs=[NS(id=i) for i in range(20)]
        grid=NS(documents=docs,selected=None,columns=3,cell=64,canvas=Mock(),repaint=Mock())
        grid.canvas.canvasy.return_value=0;grid.canvas.winfo_height.return_value=128
        StickerGrid.navigate(grid,'down');self.assertIs(grid.selected,docs[0])
        StickerGrid.navigate(grid,'down');self.assertIs(grid.selected,docs[3])
        StickerGrid.navigate(grid,'end');self.assertIs(grid.selected,docs[-1])
        grid.canvas.yview_moveto.assert_called_once()

    def test_pack_insertion_preserves_document_and_refuses_stale_account_chat(self):
        app=NS(busy=False,active=42,ui_account='a',editor=Mock(),chats=[NS(id=42,kind='user')],
               service=NS(backend=NS(account_profile=NS(premium=True))));app.editor.tag_ranges.return_value=()
        window=Mock();document=NS(id=9,attributes=[types.DocumentAttributeCustomEmoji('👩🏽\u200d💻',types.InputStickerSetEmpty())])
        insert_selected_emoji(app,window,'a',43,document);app.editor.insert_custom.assert_not_called()
        insert_selected_emoji(app,window,'b',42,document);app.editor.insert_custom.assert_not_called()
        insert_selected_emoji(app,window,'a',42,document)
        app.editor.insert_custom.assert_called_once_with(9,'👩🏽\u200d💻');window.destroy.assert_called_once()
