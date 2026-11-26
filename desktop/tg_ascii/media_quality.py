"""Telegram photo qualities, prepared off the UI/network loop without source edits."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import tempfile

PHOTO_QUALITIES = ('sd', 'hd', 'original')
PHOTO_LIMITS = {'sd': 1280, 'hd': 2560}
PHOTO_SUFFIXES = frozenset(('.jpg','.jpeg','.png','.webp'))
VIDEO_SUFFIXES = frozenset(('.mp4','.m4v','.mov','.webm','.mkv','.avi'))

def is_photo_path(path):return Path(path).suffix.lower() in PHOTO_SUFFIXES

def is_video_path(path):return Path(path).suffix.lower() in VIDEO_SUFFIXES

def is_media_path(path):return is_photo_path(path) or is_video_path(path)


def validate_photo_quality(value):
    if value is not None and value not in PHOTO_QUALITIES:
        raise ValueError('Unknown photo quality')
    return value


def _prepare_photo(source, target, quality):
    from PIL import Image, ImageOps
    with Image.open(source) as image:
        # JPEG's decoder can reduce large photographs before allocating RGB.
        limit = PHOTO_LIMITS[quality]
        image.draft('RGB', (limit, limit))
        image = ImageOps.exif_transpose(image)
        try:
            image.thumbnail((limit, limit), Image.Resampling.LANCZOS)
            rgba = image.convert('RGBA')
            rgb = Image.new('RGB', image.size, 'white')
            mask = rgba.getchannel('A')
            try:
                rgb.paste(rgba, mask=mask)
                options = {'icc_profile': image.info['icc_profile']} if image.info.get('icc_profile') else {}
                rgb.save(target, 'JPEG', quality=87, progressive=True, **options)
            finally:
                mask.close(); rgba.close(); rgb.close()
        finally:
            image.close()


@asynccontextmanager
async def photo_paths(paths, quality=None, *, photos=True):
    """Yield private resized copies for SD/HD; original/None never change bytes.

    A cancelled preparation is allowed to finish before removing its directory,
    preventing the worker from recreating a temporary file after cleanup.
    """
    quality = validate_photo_quality(quality)
    paths = list(paths)
    if not photos or quality not in PHOTO_LIMITS:
        yield paths
        return
    with tempfile.TemporaryDirectory(prefix='tg-photo-upload-') as directory:
        result = []
        for index, path in enumerate(paths):
            if not is_photo_path(path):
                result.append(path);continue
            target = Path(directory) / f'{index}.jpg'
            task = asyncio.create_task(asyncio.to_thread(_prepare_photo, path, target, quality))
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                while not task.done():
                    try:await asyncio.shield(task)
                    except asyncio.CancelledError:pass
                # Observe a worker failure, but preserve the caller's cancellation.
                if not task.cancelled():task.exception()
                raise
            result.append(target)
        yield result


def photo_variant(media, minimum=1280):
    """Choose existing server bytes for display; never recompress downloaded art."""
    from telethon import types
    source = getattr(media, 'media', None) or media
    photo = getattr(source, 'photo', None) or source
    if not isinstance(photo, types.Photo):
        return None
    candidates = [size for size in photo.sizes if isinstance(size,
        (types.PhotoSize, types.PhotoCachedSize, types.PhotoSizeProgressive))]
    sufficient = [size for size in candidates if max(size.w, size.h) >= minimum]
    selected = min(sufficient, key=lambda size: size.w * size.h) if sufficient else max(
        candidates, key=lambda size: size.w * size.h, default=None)
    return selected.type if selected else None
