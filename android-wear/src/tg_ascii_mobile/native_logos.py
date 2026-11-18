"""Stable launcher identifiers for each appearance in the shared logo catalogue."""
from tg_ascii.logos import LOGO_PALETTES, VARIANTS

LEGACY = {
    **{color: ('title-short', 'light' if color == 'light' else 'dark', color)
       for color in LOGO_PALETTES},
    **{f'{short}_{theme}': (variant, theme, 'default')
       for short, variant in (('ts', 'title-short'), ('tl', 'title-long'),
                              ('ls', 'lower-short'), ('ll', 'lower-long'))
       for theme in ('dark', 'light')},
}
NATIVE_LOGOS = dict(LEGACY)
NAMES = {choice: key for key, choice in reversed(LEGACY.items())}
for variant in VARIANTS:
    for color in LOGO_PALETTES:
        for theme in ('dark', 'light'):
            choice = (variant, theme, color)
            if choice not in NAMES:
                key = f'{variant.replace("-", "_")}_{color}_{theme}'
                NAMES[choice] = key
                NATIVE_LOGOS[key] = choice
