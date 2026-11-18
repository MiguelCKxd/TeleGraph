"""Preview capability is based on Telegram attributes, not only the filename."""
from pathlib import PurePosixPath
from telethon import types,utils

IMAGE_SUFFIXES=frozenset(('.jpg','.jpeg','.jfif','.png','.gif','.webp','.avif','.heic','.heif','.bmp','.tif','.tiff','.ico'))
RASTER_MIMES=frozenset(('image/jpeg','image/png','image/gif','image/webp','image/avif','image/heic','image/heif',
                        'image/bmp','image/tiff','image/x-icon','image/vnd.microsoft.icon'))


def is_animation(media):
    document=getattr(media,'document',None) or media
    return getattr(document,'mime_type','')=='image/gif' or any(
        isinstance(value,types.DocumentAttributeAnimated) for value in getattr(document,'attributes',()) or ())


def preview_available(media,kind,filename=''):
    return kind in ('image','sticker','video') or PurePosixPath(filename.replace('\\','/')).suffix.lower() in IMAGE_SUFFIXES or is_animation(media)


def original_thumbnail_supported(document):
    return getattr(document,'mime_type','') in RASTER_MIMES or is_animation(document)


def thumbnail_preview(media,kind):
    if is_animation(media):return False
    document=getattr(media,'document',None)
    return kind=='video' or getattr(document,'mime_type','') in ('application/x-tgsticker','video/webm')


def download_name(media,filename=''):
    name=PurePosixPath(filename.replace('\\','/')).name
    if name and name not in ('.','..'):return name
    extension=utils.get_extension(media) or '.bin'
    return ('photo' if isinstance(media,(types.Photo,types.MessageMediaPhoto)) else 'attachment')+extension
