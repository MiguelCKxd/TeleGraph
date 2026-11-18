"""Telegram profile-photo markup, history and atomic rendered previews."""
import asyncio
import os
from pathlib import Path
import tempfile
from copy import copy

from telethon import functions,types


def photo_markup(photo):
    return next((value for value in getattr(photo,'video_sizes',()) or ()
                 if isinstance(value,(types.VideoSizeEmojiMarkup,types.VideoSizeStickerMarkup))),None)


def compose_profile(symbol,destination,colors,side=512):
    """Telegram's centred 67% sticker over its 1–4 supplied background colours."""
    from PIL import Image,ImageOps
    colors=[int(value)&0xffffff for value in list(colors)[:4]] or [0x222f3d]
    rgb=[tuple((color>>shift)&255 for shift in (16,8,0)) for color in colors]
    size=64
    gradient=Image.new('RGB',(size,size))
    def blend(first,last,ratio):return tuple(round(a+(b-a)*ratio) for a,b in zip(first,last))
    pixels=[]
    for y in range(size):
        for x in range(size):
            if len(rgb)==1:color=rgb[0]
            elif len(rgb)==2:color=blend(rgb[0],rgb[1],y/(size-1))
            else:
                # Four corner interpolation, with the third colour repeated for
                # Telegram's three-colour freeform background.
                color=blend(blend(rgb[0],rgb[1],x/(size-1)),
                            blend(rgb[-1],rgb[2],x/(size-1)),y/(size-1))
            pixels.append(color)
    gradient.putdata(pixels)
    background=gradient.resize((side,side),Image.Resampling.BILINEAR).convert('RGBA');gradient.close()
    try:
        with Image.open(symbol) as source:
            original=source.convert('RGBA')
            try:icon=ImageOps.contain(original,(round(side*.67),round(side*.67)),Image.Resampling.LANCZOS)
            finally:original.close()
        try:background.alpha_composite(icon,((side-icon.width)//2,(side-icon.height)//2))
        finally:icon.close()
        destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd,temporary=tempfile.mkstemp(prefix='.profile-',suffix='.png',dir=destination.parent);os.close(fd)
        try:background.save(temporary,format='PNG');os.replace(temporary,destination)
        finally:Path(temporary).unlink(missing_ok=True)
    finally:background.close()
    return destination


async def prepare_profile_photo(app,backend,account,peer,photo,thumbnail=False):
    """Download real photos; synthesize markup-only avatars without a fake JPEG request."""
    markup=photo_markup(photo)
    revision=getattr(photo,'id','current')
    suffix='-thumb' if thumbnail else ''
    animated=not thumbnail and not markup and any(isinstance(value,types.VideoSize) for value in getattr(photo,'video_sizes',()) or ())
    target=app.preview_dir/f'{account}-profile-{peer}-{revision}{suffix}{".png" if markup else ".mp4" if animated else ".jpg"}'
    if target.is_file() and target.stat().st_size:return target
    if markup is None:return await backend.download_media(photo,target,thumbnail=thumbnail)
    # Prefer Telegram's server-generated static preview when present. It exactly
    # preserves the native freeform gradient and any future avatar composition.
    downloadable=any(isinstance(value,(types.PhotoSize,types.PhotoCachedSize,types.PhotoSizeProgressive))
                     for value in getattr(photo,'sizes',()) or ())
    if downloadable:
        raster=target.with_suffix('.jpg')
        if raster.is_file() and raster.stat().st_size:return raster
        # Telethon otherwise includes VideoSize markup when selecting a full
        # image. Markup is not a file location and has neither size nor type.
        static=copy(photo);static.video_sizes=[]
        try:return await backend.download_media(static,raster,thumbnail=thumbnail)
        except (ValueError,OSError):pass
    if isinstance(markup,types.VideoSizeEmojiMarkup):
        documents=await backend.custom_emoji_documents([markup.emoji_id]);ident=markup.emoji_id
    else:
        result=await backend.client(functions.messages.GetStickerSetRequest(markup.stickerset,hash=0))
        documents=result.documents;ident=markup.sticker_id
    document=next((item for item in documents if item.id==ident),None)
    if document is None:raise ValueError('Profile picture sticker is unavailable')
    from .animation import render_animation,renderer_available,MAX_FILE
    side=160 if thumbnail else 800
    symbol=app.preview_dir/f'{account}-profile-symbol-{ident}-{side}.webp'
    if not symbol.is_file():
        if getattr(document,'size',MAX_FILE+1)>MAX_FILE:raise ValueError('Profile picture sticker is too large')
        mime=getattr(document,'mime_type','')
        if not renderer_available(mime):raise ValueError('Install animation support to render this profile picture')
        source=app.preview_dir/f'{account}-emoji-{ident}.source'
        if not source.is_file() or source.stat().st_size!=document.size:
            source=await backend.download_media(document,source)
        await asyncio.to_thread(render_animation,source,symbol,mime,False,round(side*.67))
    return await asyncio.to_thread(compose_profile,symbol,target,markup.background_colors,side)


async def profile_history(backend,peer,offset=0,limit=20):
    """The client handles users and chat/channel photo service messages correctly."""
    photos=await backend.client.get_profile_photos(peer,offset=max(0,int(offset)),limit=max(1,min(40,int(limit))))
    return [photo for photo in photos if isinstance(photo,types.Photo)],getattr(photos,'total',None)
