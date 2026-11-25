"""Telegram's placeholder picture for peers without a profile photo.

The placeholder is presentation only: callers keep treating the peer as
photo-less (``TelegramBackend.avatar`` still returns ``None``), so features
such as suggesting a profile photo keep working.
"""
from functools import lru_cache
import hashlib
from pathlib import Path

# Telegram's seven peer colours (red, orange, violet, green, cyan, blue, pink)
# as top/bottom gradient stops of the official Android app (ThemeColors).
GRADIENTS = (
    ('#FF845E', '#D45246'),
    ('#FEBB5B', '#F68136'),
    ('#B694F9', '#6C61DF'),
    ('#9AD164', '#46BA43'),
    ('#5BCBE3', '#359AD4'),
    ('#5CAFFA', '#408ACF'),
    ('#FF8AAC', '#D95574'),
)


def bare_id(peer_id):
    """Telegram colours by the bare id, not by the marked peer id."""
    try:
        value = int(peer_id)
    except (TypeError, ValueError):
        return 0
    if value <= -1000000000000:
        return -value - 1000000000000
    return abs(value)


def color_index(peer_id, color=None):
    """The server-chosen colour wins; otherwise the official id % 7 rule."""
    if isinstance(color, int) and 0 <= color < len(GRADIENTS):
        return color
    return bare_id(peer_id) % len(GRADIENTS)


def initials(name):
    """First letter of the first word plus first letter of the last word."""
    words = [word for word in (name or '').split() if word[:1].isalnum() or not word[:1].isascii()]
    if not words:
        return '?'
    first = words[0][0]
    letters = first + (words[-1][0] if len(words) > 1 else '')
    return letters.upper()


@lru_cache(maxsize=64)
def _font(size):
    from PIL import ImageFont
    candidates = ('/System/Library/Fonts/SFNS.ttf', '/System/Library/Fonts/SFNSRounded.ttf',
                  '/System/Library/Fonts/Helvetica.ttc', 'C:/Windows/Fonts/segoeuib.ttf',
                  '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def render(peer_id, name, size, color=None, rounded=True):
    """A Pillow RGBA image of the placeholder."""
    from PIL import Image, ImageDraw
    scale = 3
    full = max(8, int(size)) * scale
    top, bottom = GRADIENTS[color_index(peer_id, color)]
    start = tuple(int(top[i:i + 2], 16) for i in (1, 3, 5))
    end = tuple(int(bottom[i:i + 2], 16) for i in (1, 3, 5))
    gradient = Image.new('RGBA', (1, full))
    for y in range(full):
        t = y / max(1, full - 1)
        gradient.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(start, end)) + (255,))
    image = gradient.resize((full, full))
    if rounded:
        mask = Image.new('L', (full, full), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, full - 1, full - 1), fill=255)
        image.putalpha(mask)
    text = initials(name)
    draw = ImageDraw.Draw(image)
    face = _font(int(full * (.42 if len(text) < 2 else .38)))
    draw.text((full / 2, full / 2), text, fill='white', font=face, anchor='mm')
    return image.resize((int(size), int(size)), Image.LANCZOS)


def path(folder, peer_id, name, size, color=None, rounded=True):
    """Cache the placeholder as a PNG and return its path (worker threads)."""
    key = hashlib.sha1(f'{bare_id(peer_id)}|{name}|{size}|{color_index(peer_id, color)}|{rounded}'.encode()).hexdigest()[:16]
    target = Path(folder) / f'default-avatar-{key}.png'
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.tmp')
        render(peer_id, name, size, color, rounded).save(temporary, 'PNG')
        temporary.replace(target)
    return str(target)
