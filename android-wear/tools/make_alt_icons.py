"""Render the existing native icon identifiers with the TeleGraph glyphs."""
from PIL import Image

from make_icons import HERE, circular, source_image

from tg_ascii_mobile.native_logos import LEGACY

DENSITIES = {'mdpi': 48, 'hdpi': 72, 'xhdpi': 96, 'xxhdpi': 144, 'xxxhdpi': 192}

alt = HERE / 'icons' / 'alt'
web = HERE / 'src' / 'tg_ascii_mobile' / 'web' / 'icons'
alt.mkdir(parents=True, exist_ok=True)
web.mkdir(parents=True, exist_ok=True)
for name, arguments in LEGACY.items():
    image = source_image(*arguments)
    image.resize((1024, 1024), Image.Resampling.LANCZOS).save(alt / f'{name}-1024.png')
    image.resize((128, 128), Image.Resampling.LANCZOS).save(web / f'{name}.png', optimize=True)
    round_image = circular(image)
    for density, size in DENSITIES.items():
        folder = alt / 'android' / f'mipmap-{density}'
        folder.mkdir(parents=True, exist_ok=True)
        image.resize((size, size), Image.Resampling.LANCZOS).save(folder / f'ic_launcher_{name}.png')
        round_image.resize((size, size), Image.Resampling.LANCZOS).save(folder / f'ic_launcher_{name}_round.png')
