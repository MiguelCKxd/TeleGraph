"""Prepare optional poll files without sending a message or decoding video frames."""
import asyncio
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from telethon import functions as f
from telethon import types as t
from telethon import utils

from .i18n import tr
from .transfers import tracked_transfer, transfer_timeout


@dataclass(frozen=True)
class PollFile:
    path: Path
    identity: tuple
    video: tuple | None = None


def identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def inspect_poll_file(value):
    """Bounded metadata inspection, run outside the UI/network event loop."""
    path = Path(value).expanduser()
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(tr('Elige un archivo normal, no una carpeta.'))
    if info.st_size <= 0:
        raise ValueError(tr('Choose a JPEG, PNG or MP4 file.'))
    extension = path.suffix.lower()
    video = None
    if extension == '.mp4':
        from .video_metadata import mp4_metadata
        try:
            video = mp4_metadata(path, max_duration=None)
        except (OSError, ValueError) as error:
            raise ValueError(tr('Choose a JPEG, PNG or MP4 file.')) from error
    elif extension in ('.jpg', '.jpeg', '.png'):
        from PIL import Image
        try:
            with Image.open(path) as image:
                expected = 'PNG' if extension == '.png' else 'JPEG'
                if image.format != expected or image.width <= 0 or image.height <= 0:
                    raise ValueError
                # Header parsing does not allocate the original pixel buffer.
                # Telegram validates the uploaded photo before we publish it.
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            raise ValueError(tr('Choose a JPEG, PNG or MP4 file.')) from error
    else:
        raise ValueError(tr('Choose a JPEG, PNG or MP4 file.'))
    if identity(path.stat()) != identity(info):
        raise ValueError(tr('Choose file'))
    return PollFile(path, identity(info), video)


@tracked_transfer
async def upload_poll_files(owner, peer, files, progress=None):
    """Register files with Telegram; cancellation never sends a chat message.

    InputMediaPoll accepts InputMedia. UploadMedia turns each local upload into
    a reusable InputMediaPhoto/Document for the nested fields. Sequential work
    avoids occupying multiple upload lanes for this small, on-demand feature.
    """
    prepared, reused = {}, {}
    for key, item in files.items():
        cache_key = (str(item.path.resolve()), item.identity)
        if cache_key in reused:
            prepared[key] = reused[cache_key]
            continue
        with item.path.open('rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode) or identity(os.fstat(stream.fileno())) != item.identity:
                raise ValueError(tr('Choose file'))
            def notify(current, total, name=item.path.name):
                if progress: return progress(name, current, total)
            async with transfer_timeout(notify) as report:
                uploaded = await owner.client.upload_file(stream, progress_callback=report)
                if identity(os.fstat(stream.fileno())) != item.identity:
                    raise ValueError(tr('Choose file'))
                if item.video:
                    duration, width, height = item.video
                    media = t.InputMediaUploadedDocument(uploaded, 'video/mp4', [
                        t.DocumentAttributeVideo(duration, width, height),
                        t.DocumentAttributeFilename(item.path.name)])
                else:
                    media = t.InputMediaUploadedPhoto(uploaded)
                result = await owner.client(f.messages.UploadMediaRequest(peer, media))
        if not isinstance(result, (t.MessageMediaPhoto, t.MessageMediaDocument)):
            raise TypeError(tr('This message is no longer available in this form.'))
        value = utils.get_input_media(result)
        if not isinstance(value, (t.InputMediaPhoto, t.InputMediaDocument)):
            raise TypeError(tr('This message is no longer available in this form.'))
        prepared[key] = reused[cache_key] = value
    return prepared


async def inspect_poll_files(files):
    if set(files) - {'attached_media', 'solution_media'}:
        raise ValueError('Unknown poll attachment')
    # At most two bounded metadata reads, with no thumbnail/animation decoding.
    return {key: await asyncio.to_thread(inspect_poll_file, value) for key, value in files.items()}
