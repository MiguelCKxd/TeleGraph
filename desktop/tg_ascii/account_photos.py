"""Small own-profile pictures for the account chooser shown before connecting.

Each saved account keeps a thumbnail of its own photo next to its data, so
the chooser can show it while no Telegram connection is open. Accounts
without a photo get Telegram's placeholder (default_avatar) but are still
recorded as photo-less.
"""
import asyncio
import os
from pathlib import Path
import tempfile

FOLDER = 'account-photos'
DOWNLOAD_TIMEOUT = 15


def photo_path(root, key):
    return Path(root) / FOLDER / f'{key}.jpg'


def has_photo(user):
    photo = getattr(user, 'photo', None)
    return photo is not None and type(photo).__name__ != 'UserProfilePhotoEmpty'


async def remember(root, key, client, me):
    """Refresh the thumbnail after the account connected (best effort)."""
    target = photo_path(root, key)
    temporary = None
    try:
        if not has_photo(me):
            target.unlink(missing_ok=True)
            return False
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, name = tempfile.mkstemp(prefix=f'.{key}-', suffix='.jpg', dir=target.parent)
        os.close(descriptor)
        temporary = Path(name)
        result = await asyncio.wait_for(client.download_profile_photo(me, file=str(temporary), download_big=False),
                                        DOWNLOAD_TIMEOUT)
        if not result:
            return False
        Path(result).replace(target)
        return True
    except (OSError, ValueError, TypeError, asyncio.TimeoutError, ConnectionError):
        return False
    except Exception:
        # Telegram errors must never block opening an account.
        return False
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def display_path(root, key, label, user_id, folder):
    """The account's own thumbnail, or Telegram's placeholder for it."""
    own = photo_path(root, key)
    if own.is_file():
        return str(own)
    from . import default_avatar
    return default_avatar.path(folder, user_id or 0, label or '?', 64)


def round_image(path, size):
    """A round Pillow image of ``size`` pixels for Tk lists."""
    from PIL import Image, ImageDraw, ImageOps
    with Image.open(path) as source:
        image = ImageOps.fit(source.convert('RGBA'), (size * 3, size * 3), Image.LANCZOS)
    mask = Image.new('L', image.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, image.size[0] - 1, image.size[1] - 1), fill=255)
    image.putalpha(mask)
    return image.resize((size, size), Image.LANCZOS)
