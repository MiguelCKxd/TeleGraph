"""Regenerate the bundled desktop TeleGraph wordmarks."""
from io import BytesIO
from pathlib import Path
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tg_ascii.logos import CLASSIC_MARK, LEGACY_VARIANTS, LOGO_PALETTES, asset_path, png_bytes


def classic_mark(theme, tint='default', size=512, width=None):
    mark = Image.open(BytesIO(png_bytes(CLASSIC_MARK, theme, size, color=tint, full_bleed=True)))
    image = Image.new('RGB', (width or size, size), LOGO_PALETTES[tint][theme][0])
    image.paste(mark, ((image.width - size) // 2, 0), mark)
    return image


def main():
    folder = ROOT / 'tg_ascii' / 'assets'
    for theme in ('dark', 'light'):
        for variant in LEGACY_VARIANTS:
            asset_path(variant, theme).write_bytes(png_bytes(variant, theme))
        classic_mark(theme, size=1024, width=1536).save(folder / f'tg-as-{theme}.png')
    with Image.open(BytesIO(png_bytes(size=256))) as icon:
        icon.save(ROOT / 'tools' / 'installer' / 'app.ico',
                  sizes=[(size, size) for size in (16, 32, 48, 64, 128, 256)])
    for tint in LOGO_PALETTES:
        classic_mark('light' if tint == 'light' else 'dark', tint).save(folder / f'mobile-{tint}.png')


if __name__ == '__main__':
    main()
