"""Bounded animation decoding and a single Tk playback clock."""
import asyncio
from collections import OrderedDict
import gzip
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
import weakref
from telethon.errors import RPCError,FileReferenceExpiredError,FileReferenceInvalidError,FileReferenceEmptyError
from .preferences import animated_emoji_enabled

REFERENCE_ERRORS=(FileReferenceExpiredError,FileReferenceInvalidError,FileReferenceEmptyError)

MAX_FILE = 4 * 1024 * 1024
MAX_FRAMES = 90
MAX_DECODE_PIXELS = 64_000_000
MAX_CACHE_BYTES = 24 * 1024 * 1024


def frame_duration(value):
    """Malformed image metadata must not break playback or create a busy timer."""
    try:
        from .resources import decode_fps, min_frame_ms
        return max(min_frame_ms() if decode_fps() > 30 else 33, min(1000, int(value)))
    except (TypeError, ValueError, OverflowError):
        return 100


def renderer_available(mime):
    import importlib.util
    module = 'rlottie_python' if mime == 'application/x-tgsticker' else 'av' if mime == 'video/webm' else None
    return module is None or importlib.util.find_spec(module) is not None


def render_animation(path, destination, mime, animated=True, side=128):
    """Decode off the Tk thread, producing a small transparent animated WebP."""
    frames=[]
    try:return _render_animation(path,destination,mime,animated,side,frames)
    finally:
        for frame in frames:frame.close()


def _render_animation(path,destination,mime,animated,side,frames):
    from PIL import Image
    path, destination = Path(path), Path(destination)
    if path.stat().st_size > MAX_FILE: raise ValueError('Animation is too large')
    side=max(16,min(536,int(side)))
    from .resources import max_frames, decode_fps, min_frame_ms
    limit=max_frames(MAX_FRAMES) if animated else 1
    target_fps, shortest=decode_fps(), min_frame_ms()
    durations=[]
    if mime == 'application/x-tgsticker':
        from rlottie_python import LottieAnimation
        with gzip.open(path, 'rb') as source: data = source.read(MAX_FILE + 1)
        if len(data) > MAX_FILE: raise ValueError('Animation is too large')
        meta = json.loads(data)
        if not isinstance(meta,dict) or not isinstance(meta.get('assets',[]),list):
            raise ValueError('Invalid animation metadata')
        if any(not isinstance(asset,dict) or 'p' in asset or 'u' in asset for asset in meta.get('assets', [])):
            raise ValueError('External animation assets are not supported')
        try:
            rate = float(meta.get('fr', 0)); count = float(meta.get('op', 0)) - float(meta.get('ip', 0))
        except (TypeError,ValueError,OverflowError) as exc:raise ValueError('Invalid animation timing') from exc
        if not math.isfinite(rate) or not math.isfinite(count) or not 0 < rate <= 120 or not 0 < count <= 720:
            raise ValueError('Invalid animation timing')
        with LottieAnimation.from_data(data.decode('utf-8')) as animation:
            total = animation.lottie_animation_get_totalframe()
            fps = animation.lottie_animation_get_framerate()
            if not 0 < total <= 720 or not math.isfinite(fps) or not 0 < fps <= 120:
                raise ValueError('Invalid animation timing')
            step = max(1, math.ceil(fps / target_fps), math.ceil(total / limit))
            for index in list(range(0, total, step))[:limit]:
                rendered=animation.render_pillow_frame(frame_num=index,width=side,height=side)
                try:frames.append(rendered.convert('RGBA'))
                finally:rendered.close()
                durations.append(max(shortest, round(min(step, total-index) * 1000 / fps)))
    elif mime == 'video/webm':
        import av
        with av.open(str(path)) as container:
            stream = container.streams.video[0]
            if stream.width * stream.height > 512 * 512: raise ValueError('Animation is too large')
            # libvpx preserves VP9 alpha, unlike FFmpeg's native VP9 decoder.
            decoder=stream.codec_context
            if decoder.name=='vp9':
                try:
                    decoder=av.CodecContext.create('libvpx-vp9','r')
                    decoder.extradata=stream.codec_context.extradata
                except (ValueError,RuntimeError):decoder=stream.codec_context
            last = -1.0; decoded=0; finished=False; rate=float(stream.average_rate or 30)
            for packet in container.demux(stream):
                for frame in decoder.decode(packet):
                    at = float(frame.time) if frame.time is not None else decoded/max(1,rate)
                    decoded+=1
                    if at > 3.1 or len(frames) >= limit or decoded>720:
                        finished=True;break
                    if last >= 0 and at - last < 1 / target_fps - .002: continue
                    if frames: durations[-1] = max(shortest, min(200, round((at-last)*1000)))
                    rgba = frame.reformat(format='rgba')
                    plane = rgba.planes[0]
                    image = Image.frombytes('RGBA', (rgba.width, rgba.height), bytes(plane), 'raw', 'RGBA', plane.line_size)
                    image.thumbnail((side,side))
                    frames.append(image); durations.append(33); last=at
                if finished or len(frames) >= limit: break
    else:
        with Image.open(path) as image:
            if image.width * image.height > 512 * 512: raise ValueError('Animation is too large')
            for index in range(min(limit, getattr(image, 'n_frames', 1))):
                image.seek(index); frame=image.convert('RGBA'); frame.thumbnail((side,side))
                frames.append(frame); durations.append(frame_duration(image.info.get('duration',100)))
    if not frames: raise ValueError('No animation frames')
    descriptor,temporary=tempfile.mkstemp(prefix='emoji-render-',suffix='.webp',dir=destination.parent)
    os.close(descriptor)
    try:
        # The default high-effort lossless encoder adds considerable latency to
        # every previously unseen emoji. Method 0 preserves all pixels/frames.
        frames[0].save(temporary,format='WEBP',save_all=True,append_images=frames[1:],duration=durations,loop=0,lossless=True,method=0)
        os.replace(temporary,destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return destination


async def emoji_file(app, document, account, backend, side=128):
    """Path to a renderable file for a sticker/custom emoji document.

    TGS (Lottie) and WebM stickers are downloaded as the original Telegram
    document and rendered natively (rlottie / PyAV) at ``side`` pixels: 128 for
    inline emoji, larger for message stickers and gift previews.
    """
    side=max(64,min(512,int(side)))
    if document is None or not isinstance(getattr(document,'id',None),int):
        # A sticker/emoji whose document Telegram no longer supplies
        # (DocumentEmpty, expired media): nothing to draw, not an error.
        return None
    cache=getattr(app,'_emoji_files',None)
    if cache is None:cache=app._emoji_files=OrderedDict()
    from .resources import decode_fps
    key=(account,document.id,animated_emoji_enabled(app.preferences.values),side,decode_fps())
    path=cache.get(key)
    if path and Path(path).is_file():cache.move_to_end(key);return path
    jobs=getattr(app,'_emoji_jobs',None)
    if jobs is None:jobs=app._emoji_jobs={}
    if key not in jobs:
        task=jobs[key]=asyncio.create_task(asyncio.wait_for(_emoji_with_refresh(app,document,account,backend,side),60))
        def completed(task):
            if jobs.get(key) is task:jobs.pop(key,None)
            if task.cancelled():return
            try:path=task.result()
            except Exception:return
            if path:cache[key]=path;cache.move_to_end(key)
            while len(cache)>256:cache.popitem(last=False)
        task.add_done_callback(completed)
    return await asyncio.shield(jobs[key])


async def _emoji_with_refresh(app,document,account,backend,side=128):
    try:return await _emoji_file(app,document,account,backend,side)
    except REFERENCE_ERRORS:
        from .emoji_documents import refresh_document
        fresh=await refresh_document(backend,document)
        if fresh is None:raise
        return await _emoji_file(app,fresh,account,backend,side)


async def _emoji_file(app, document, account, backend, side=128):
    """Keep the chosen emoji visible even when Telegram supplies no raster thumbnail."""
    mime = getattr(document, 'mime_type', '')
    # Emoji/sticker documents are immutable: keep their downloads and (CPU
    # heavy) renders across launches in the account's persistent cache.
    from .media_cache import emoji_base, touch
    base = emoji_base(backend, document.id) or app.preview_dir / f'{account}-emoji-{document.id}'
    animated=animated_emoji_enabled(app.preferences.values)
    if not animated:
        try:
            return await backend.download_media(document,base.with_suffix('.jpg'),thumbnail=True)
        except REFERENCE_ERRORS:raise
        except (OSError,ValueError,RPCError):
            # Many TGS documents contain only an outline. Turning animation off
            # must show their first frame, rather than permanently hiding them.
            pass
    if renderer_available(mime) and getattr(document, 'size', MAX_FILE+1) <= MAX_FILE:
        try:
            # 128 px keeps the pre-1.4 file name, so existing caches stay valid.
            from .resources import frame_tag
            size_tag=('' if side==128 else f'-{side}')+frame_tag()
            rendered=base.with_suffix(f'.animated{size_tag}.webp' if animated else f'.still{size_tag}.webp')
            if rendered.is_file() and rendered.stat().st_size:
                touch(rendered)
                return rendered
            source=base.with_suffix('.source')
            path=source if source.is_file() and source.stat().st_size==getattr(document,'size',0) else await backend.download_media(document,source,thumbnail=False)
            if not path:raise ValueError('Animation download is empty')
            from .decode_pool import run as decode_run
            return await decode_run(render_animation, str(path), str(rendered), mime, animated, side)  # process_decoding: another core
        except REFERENCE_ERRORS:raise
        except (ImportError, OSError, ValueError, RuntimeError, KeyError, IndexError, RPCError):
            pass
    return await backend.download_media(document, base.with_suffix('.jpg'), thumbnail=True)


def decode_frames(path, size, animated=True):
    from PIL import Image,UnidentifiedImageError
    frames, durations = [], []
    size=tuple(max(1,int(value)) for value in size)
    try:source=Image.open(path)
    except UnidentifiedImageError:return decode_video_frames(path,size,animated)
    try:
        with source:
            if source.width * source.height > 30_000_000: raise ValueError('Image is too large')
            # Bound work at the decoder's original resolution, not only the tiny
            # output bitmaps: an animated 30 MP image otherwise decodes 2.7 Gpixels.
            count=min(MAX_FRAMES,getattr(source,'n_frames',1),max(1,MAX_DECODE_PIXELS//(source.width*source.height))) if animated else 1
            if count>1:size=(min(128,size[0]),min(128,size[1]))
            else:source.draft('RGB',size)
            for index in range(count):
                source.seek(index); frame=source.convert('RGBA');frames.append(frame)
                frame.thumbnail(size);durations.append(frame_duration(source.info.get('duration',100)))
        return frames,durations
    except Exception:
        for frame in frames:frame.close()
        raise


def decode_video_frames(path,size,animated=True):
    """Small GIF documents can contain MP4; keep the same decode budget as Pillow."""
    from PIL import ImageOps
    from .media_viewer import ImageFrames
    source=ImageFrames(path);frames=[];durations=[]
    try:
        first=source.get(0)
        count=min(MAX_FRAMES,source.count,max(1,MAX_DECODE_PIXELS//(first.width*first.height))) if animated else 1
        if count>1:size=(min(128,size[0]),min(128,size[1]))
        for index in range(count):
            frame=source.get(index)
            if index>=source.count:break  # Streaming decoders learn count at EOF.
            frames.append(ImageOps.contain(frame,size));durations.append(frame_duration(source.image.info.get('duration',100)))
        return frames,durations
    except Exception:
        for frame in frames:frame.close()
        raise
    finally:source.close()


class AnimationPlayer:
    def __init__(self, root):
        self.root=root; self.entries=[]; self.cache=OrderedDict(); self.photos=weakref.WeakValueDictionary(); self.job=None; self.stopped=False
        self.cache_bytes=0
        self._cache_lock=threading.RLock()
        self._owners=weakref.WeakKeyDictionary()

    def has(self, path, size, enabled=True, tint=None):
        try:
            key=(str(path),Path(path).stat().st_mtime_ns,tuple(size),bool(enabled),tint)
        except OSError:
            return False
        with self._cache_lock:
            return key in self.cache

    def prepare(self, path, size, enabled=True, tint=None, prepared=None):
        """Decode/tint without Tk; safe to call in a worker before photo()."""
        key=(str(path),Path(path).stat().st_mtime_ns,tuple(size),bool(enabled),tint)
        with self._cache_lock:
            cached=self.cache.get(key)
            if cached is not None:
                self.cache.move_to_end(key)
                return cached
            if prepared is None and not enabled:
                prepared=self.cache.get((*key[:3],True,tint))
            if prepared is None and tint:
                prepared=self.cache.get((*key[:3],bool(enabled),None))
        # Keep slow decoding outside the cache lock: a visible cache hit must
        # never wait for an unrelated worker decoding a large image.
        frames,durations=prepared if prepared is not None else decode_frames(path,size,animated=enabled)
        if not enabled:frames,durations=frames[:1],durations[:1]
        if tint:
            from PIL import Image
            colored=[]
            for frame in frames:
                colored_frame=Image.new('RGBA',frame.size,tint)
                colored_frame.putalpha(frame.getchannel('A') if frame.mode=='RGBA' else frame.convert('RGBA').getchannel('A'))
                colored.append(colored_frame)
            frames=colored
        if not frames or len(frames)!=len(durations):raise ValueError('Invalid animation frames')
        cost=sum(frame.width*frame.height*4 for frame in frames)
        with self._cache_lock:
            if key in self.cache:
                return self.cache[key]  # Another caller prepared the same art.
            from .resources import cache_bytes
            budget=cache_bytes(MAX_CACHE_BYTES)
            if not self.stopped and cost<=budget:
                while self.cache and self.cache_bytes+cost>budget:
                    _,(old,_) = self.cache.popitem(last=False)
                    self.cache_bytes-=sum(frame.width*frame.height*4 for frame in old)
                self.cache[key]=(frames,durations);self.cache_bytes+=cost
        return frames,durations

    def photo(self, path, size, enabled=True, prepared=None, tint=None, owner=None):
        from PIL import ImageTk
        key=(str(path),Path(path).stat().st_mtime_ns,tuple(size),bool(enabled),tint)
        photo_key=(key,bool(enabled))
        existing=self.photos.get(photo_key)
        if existing is not None:
            self._track_owner(existing,owner)
            return existing
        frames,durations=self.prepare(path,size,enabled,tint,prepared)
        photo=ImageTk.PhotoImage(frames[0],master=self.root);self.photos[photo_key]=photo
        self._track_owner(photo,owner)
        self.entries=[entry for entry in self.entries if entry[0]() is not None]
        # A strict upper bound prevents a large emoji history from consuming unlimited CPU/RAM.
        cost=lambda sequence:sum(frame.width*frame.height*4 for frame in sequence)
        from .resources import animated_entries, animation_budget
        if not self.stopped and enabled and len(frames)>1 and len(self.entries)<animated_entries(32) and sum(cost(entry[1]) for entry in self.entries)+cost(frames)<=animation_budget(32*1024*1024):
            self.entries.append([weakref.ref(photo),frames,durations,0,time.monotonic()+durations[0]/1000])
            if self.job is None:self.job=self.root.after(33,self.tick)
        return photo

    def _track_owner(self,photo,owner):
        if owner is None:
            self._owners[photo]=None  # Compatibility for callers without a widget.
        elif photo not in self._owners:
            self._owners[photo]=weakref.WeakSet((owner,))
        elif self._owners[photo] is not None:
            self._owners[photo].add(owner)

    def _visible(self,photo):
        owners=self._owners.get(photo)
        if owners is None:return bool(self.root.winfo_viewable())
        for owner in tuple(owners):
            try:
                if owner.winfo_viewable():return True
            except tk.TclError:continue
        return False

    def tick(self):
        self.job=None
        if self.stopped:return
        self.entries=[entry for entry in self.entries if entry[0]() is not None]
        now=time.monotonic()
        visible=False;next_due=None
        try:
            for entry in list(self.entries):
                photo,frames,durations,index,due=entry
                target=photo()
                if target is None or not self._visible(target):continue
                visible=True
                if now>=due:
                    index=(index+1)%len(frames)
                    try:target.paste(frames[index])
                    except tk.TclError:self.entries.remove(entry);continue
                    entry[3:]=[index,now+durations[index]/1000]
                next_due=min(next_due,entry[4]) if next_due is not None else entry[4]
        except tk.TclError:self.stop();return
        if self.entries:
            from .resources import frame_interval, frame_limit
            floor=frame_interval() if frame_limit() is not None else (16 if frame_interval()<=33 else frame_interval())
            delay=max(floor,min(250,math.ceil((next_due-now)*1000))) if visible else 250
            self.job=self.root.after(delay,self.tick)

    def stop(self):
        self.stopped=True
        if self.job is not None:
            try:self.root.after_cancel(self.job)
            except tk.TclError:pass
        self.job=None;self.entries.clear();self.photos.clear();self._owners.clear()
        with self._cache_lock:self.cache.clear();self.cache_bytes=0
