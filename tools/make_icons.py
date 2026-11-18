"""Generate native launcher resources from the common TeleGraph glyphs."""
from io import BytesIO
from pathlib import Path
import sys

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'src'))
from tg_ascii.logos import LOGO_PALETTES, png_bytes


def source_image(variant='title-short', theme='dark', color='default'):
    image = Image.open(BytesIO(png_bytes(variant, theme, 512, color=color, full_bleed=True))).convert('RGBA')
    background = Image.new('RGB', image.size, LOGO_PALETTES[color][theme][0])
    background.paste(image, mask=image.getchannel('A'))
    return background


def circular(image):
    mask = Image.new('L', image.size)
    ImageDraw.Draw(mask).ellipse((0, 0, image.width - 1, image.height - 1), fill=255)
    result = image.convert('RGBA')
    result.putalpha(mask)
    return result


def main():
    square = source_image()
    rounded = circular(square)
    out = HERE / 'icons'
    out.mkdir(exist_ok=True)

    def save(image, name, size):
        image.resize((size, size), Image.Resampling.LANCZOS).save(out / f'{name}.png')

    for size in (20, 29, 40, 58, 60, 76, 80, 87, 120, 152, 167, 180, 640, 1024, 1280, 1920):
        save(square, f'tg-ascii-{size}', size)
    for size in (48, 72, 96, 144, 192, 320, 480, 640, 960, 1280):
        save(square, f'tg-ascii-square-{size}', size)
        save(rounded, f'tg-ascii-round-{size}', size)
    canvas = Image.new('RGB', (768, 768), LOGO_PALETTES['default']['dark'][0])
    canvas.paste(square, (128, 128))
    for size in (108, 162, 216, 324, 432):
        save(canvas, f'tg-ascii-adaptive-{size}', size)
    watch = HERE / 'watch/TGASCIIWatch/Assets.xcassets/AppIcon.appiconset/icon-1024.png'
    square.resize((1024, 1024), Image.Resampling.LANCZOS).save(watch)


if __name__ == '__main__':
    main()
