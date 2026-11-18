"""Native media navigation, GIF playback and cancellation with synthetic files only."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,Mock,patch

from PIL import Image
from telethon import types

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tg_ascii.desktop import AsyncWorker
from tg_ascii.media_gallery import open_profile_gallery,open_chat_gallery
from tg_ascii.media_viewer import show_image
from tg_ascii.backend import Message


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result={'success':False,'synthetic_only':True,'platform':sys.platform}
    started=time.monotonic();errors=[];downloads=[];history=[];threads=set()
    with tempfile.TemporaryDirectory(prefix='tg-media-native-') as temporary:
        directory=Path(temporary);root=tk.Tk();root.geometry('900x680');root.title('Synthetic media verification')
        root.report_callback_exception=lambda kind,error,trace:errors.append(str(error))
        worker=AsyncWorker();waiting,cancelled=threading.Event(),threading.Event();stall=[False]
        photos=[types.Photo(ident,0,b'',None,[],1) for ident in (30,29,28)]
        async def records(peer,offset,limit):history.append((offset,limit));return photos[offset:offset+limit]
        async def download(media,path,thumbnail=False):
            downloads.append((getattr(media,'id',None),thumbnail));threads.add(threading.get_ident())
            if stall[0]:
                waiting.set()
                try:await asyncio.Event().wait()
                except asyncio.CancelledError:cancelled.set();raise
            image=Image.new('RGB',(320,240) if thumbnail else (1200,900),'red' if getattr(media,'id',0)%2 else 'blue')
            try:image.save(path,format='JPEG')
            finally:image.close()
            return path
        backend=NS(client=NS(get_profile_photos=records,get_messages=AsyncMock(return_value=[])),
                   download_media=download,message=lambda value:value)
        app=NS(root=root,worker=worker,ui_account='synthetic',service=NS(backend=backend),preview_dir=directory,
               popups=[],busy=False,active=42,jump_message=Mock(),show_error=lambda error:errors.append(str(error)))
        def pump(condition,timeout=8):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                root.update()
                while not worker.events.empty():
                    callback,value=worker.events.get_nowait();callback(value)
                if errors:raise AssertionError(errors)
                if condition():return
                time.sleep(.005)
            raise AssertionError('Native media test timed out')
        def painted(view):return bool(getattr(view._media_canvas,'image',None))
        try:
            profile={'name':'Synthetic profile','display_photo':photos[0]}
            gallery=open_profile_gallery(app,42,profile)
            pump(lambda:gallery.path is not None and painted(gallery.window))
            original=gallery.path;digest=hashlib.sha256(original.read_bytes()).hexdigest()
            self_image=Image.open(original)
            try:assert self_image.size==(1200,900)
            finally:self_image.close()
            assert not history and not app.busy
            gallery.navigate(1);pump(lambda:gallery.index==1 and gallery.path is not None)
            assert gallery.item.ident==29 and history==[(0,20)]
            gallery.window.focus_force();root.update()
            gallery.window.event_generate('<Left>')
            pump(lambda:gallery.index==0 and gallery.path is not None)
            assert gallery.path==original and hashlib.sha256(original.read_bytes()).hexdigest()==digest
            assert len(downloads)==2
            canvas=gallery.window._media_canvas
            canvas.event_generate('<ButtonPress-1>',x=250,y=100)
            canvas.event_generate('<B1-Motion>',x=100,y=100)
            canvas.event_generate('<ButtonRelease-1>',x=100,y=100)
            pump(lambda:gallery.index==1 and gallery.path is not None)
            result.update(profile_buttons_keys_swipe=True,profile_cache_reused=True,original_preserved=True,
                          lazy_metadata_pages=len(history),download_count=len(downloads))
            destination=directory/'exported.jpg'
            with patch('tg_ascii.media_gallery.filedialog.asksaveasfilename',return_value=str(destination)):
                gallery.save()
            assert destination.read_bytes()==gallery.path.read_bytes()
            result['save_preserves_original']=True
            # The modal file chooser may pump events and switch accounts.
            untouched=directory/'must-not-save.jpg'
            def switch(**kwargs):app.ui_account='other';return str(untouched)
            with patch('tg_ascii.media_gallery.filedialog.asksaveasfilename',side_effect=switch):gallery.save()
            assert not untouched.exists();app.ui_account='synthetic'
            result['stale_account_save_rejected']=True
            stall[0]=True;gallery.navigate(1);pump(waiting.is_set)
            gallery.window.destroy();pump(cancelled.is_set)
            assert gallery.requests.closed and not gallery.requests.jobs
            result['close_cancels_pending_original']=True;stall[0]=False
            # A GIF encoded as silent MP4 must animate, despite its .media name.
            import av
            movie=directory/'telegram-gif.media'
            with av.open(str(movie),'w',format='mp4') as output:
                stream=output.add_stream('mpeg4',rate=25);stream.width=48;stream.height=32;stream.pix_fmt='yuv420p'
                for index in range(12):
                    image=Image.new('RGB',(48,32),'red' if index%2 else 'blue')
                    try:frame=av.VideoFrame.from_image(image)
                    finally:image.close()
                    for packet in stream.encode(frame):output.mux(packet)
                for packet in stream.encode():output.mux(packet)
            viewer=show_image(root,movie,'Synthetic MP4 GIF');app.popups.append(viewer)
            pump(lambda:painted(viewer));first=viewer._media_canvas.image
            pump(lambda:viewer._media_canvas.image is not first)
            viewer.withdraw();until=time.monotonic()+.2;pump(lambda:time.monotonic()>until)
            paused=viewer._media_canvas.image;until=time.monotonic()+.3;pump(lambda:time.monotonic()>until)
            assert viewer._media_canvas.image is paused
            viewer.deiconify();pump(lambda:viewer._media_canvas.image is not paused)
            viewer.destroy();result['mp4_gif_playback_hidden_pause_resume']=True
            # The ordinary chat gallery stays usable while the main UI is busy.
            message=Message(7,'Synthetic','','12:00',media=photos[2],media_kind='image')
            app.busy=True;chat=open_chat_gallery(app,message,42)
            pump(lambda:chat.path is not None and painted(chat.window))
            chat.go_to();app.jump_message.assert_called_once_with(7,42)
            chat.window.destroy();app.busy=False
            result.update(independent_chat_gallery=True,worker_downloads_off_tk=threading.get_ident() not in threads,
                          callback_errors=errors,success=True)
        except Exception as error:
            result.update(error=type(error).__name__,detail=str(error))
        finally:
            for window in app.popups:
                if window.winfo_exists():window.destroy()
            worker.stop();root.destroy();worker.thread.join(3)
            result['worker_stopped']=not worker.thread.is_alive()
            if worker.thread.is_alive():result['success']=False
            # Decoder executors release files after their current bounded frame.
            until=time.monotonic()+3
            while any(thread.name.startswith('tg-image-view') for thread in threading.enumerate()) and time.monotonic()<until:time.sleep(.01)
            result['decoder_threads_stopped']=not any(thread.name.startswith('tg-image-view') for thread in threading.enumerate())
            if not result['decoder_threads_stopped']:result['success']=False
    result['wall_seconds']=round(time.monotonic()-started,3)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2));return 0 if result['success'] else 1


if __name__=='__main__':raise SystemExit(main())
