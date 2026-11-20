"""Deterministic ASCII wordmarks used by the UI and native icon packager.

Solid wordmarks share the outlines of the original mobile lettering.
The character grid is used only for ASCII art and the legacy dotted style.
"""
from pathlib import Path
from tempfile import NamedTemporaryFile
import struct
import zlib

CLASSIC_MARK = 'tg-as'

LEGACY_VARIANTS = ('title-short', 'lower-short', 'title-long', 'lower-long')
VARIANTS = {
    'title-short': 'Tg-Gr', 'lower-short': 'tg-gr', 'title-long': 'Tg-Graph', 'lower-long': 'tg-graph',
    'telegraph-title': 'TeleGraph', 'tg-graph-upper': 'TG-GRAPH', 'tg-graph-mixed': 'Tg-GRAPH',
    'telegraph-lower': 'telegraph', 'telegraph-upper-suffix': 'teleGRAPH', 'telegraph-upper-prefix': 'TELEgraph',
    'tg-gr-upper': 'TG-GR', 'tele-graph-title': 'Tele-Graph', 'tele-graph-upper': 'TELE-GRAPH',
    'tele-graph-lower': 'tele-graph', 't-graph-lower-suffix': 'T-graph', 't-graph-title': 'T-Graph',
    'tgraph-title': 'TGraph', 'tgraph-lower': 't-graph', 'tgraph-joined-lower': 'tgraph',
    'telegraph-upper': 'TELEGRAPH', 'telegraph-capitalized': 'Telegraph',
    CLASSIC_MARK: 'Tg-As',
}

# RGB pairs are background and ink. The dark palettes retain the mobile hues.
LOGO_PALETTES = {
    'default': {'dark': ((8, 16, 12), (154, 243, 171)), 'light': ((244, 248, 243), (20, 83, 45))},
    'light': {'dark': ((15, 30, 22), (198, 240, 209)), 'light': ((255, 255, 255), (20, 83, 45))},
    'orange': {'dark': ((18, 11, 4), (255, 179, 71)), 'light': ((255, 245, 228), (125, 56, 0))},
    'blue': {'dark': ((6, 12, 24), (124, 196, 255)), 'light': ((236, 247, 255), (16, 71, 120))},
    'red': {'dark': ((22, 6, 6), (255, 122, 122)), 'light': ((255, 239, 239), (135, 25, 32))},
    'monochrome': {'dark': ((0, 0, 0), (255, 255, 255)), 'light': ((255, 255, 255), (0, 0, 0))},
    'pink': {'dark': ((22, 8, 16), (255, 154, 213)), 'light': ((255, 239, 248), (111, 22, 76))},
}
GLYPHS = {
    'T': ['#####','  #  ','  #  ','  #  ','  #  ','  #  ','  #  ','     ','     '],
    't': ['     ',' #   ','###  ',' #   ',' #   ',' #   ','  ## ','     ','     '],
    'g': ['     ','     ',' ### ','#   #','#   #',' ####','    #','    #',' ### '],
    '-': ['     ','     ','     ','     ',' ### ','     ','     ','     ','     '],
    'A': [' ### ','#   #','#   #','#####','#   #','#   #','#   #','     ','     '],
    'a': ['     ','     ',' ### ','    #',' ####','#   #',' ####','     ','     '],
    's': ['     ','     ',' ####','#    ',' ### ','    #','#### ','     ','     '],
    'S': [' ####','#    ','#    ',' ### ','    #','    #','#### ','     ','     '],
    'C': [' ### ','#   #','#    ','#    ','#    ','#   #',' ### ','     ','     '],
    'c': ['     ','     ',' ### ','#   #','#    ','#   #',' ### ','     ','     '],
    'I': ['#####','  #  ','  #  ','  #  ','  #  ','  #  ','#####','     ','     '],
    'i': ['  #  ','     ',' ##  ','  #  ','  #  ','  #  ',' ### ','     ','     '],
    'G': [' ### ','#   #','#    ','# ###','#   #','#   #',' ### ','     ','     '],
    'R': ['#### ','#   #','#   #','#### ','# #  ','#  # ','#   #','     ','     '],
    'P': ['#### ','#   #','#   #','#### ','#    ','#    ','#    ','     ','     '],
    'H': ['#   #','#   #','#   #','#####','#   #','#   #','#   #','     ','     '],
    'E': ['#####','#    ','#    ','#### ','#    ','#    ','#####','     ','     '],
    'L': ['#    ','#    ','#    ','#    ','#    ','#    ','#####','     ','     '],
    'r': ['     ','     ','# ## ','##  #','#    ','#    ','#    ','     ','     '],
    'p': ['     ','     ','#### ','#   #','#   #','#### ','#    ','#    ','#    '],
    'h': ['#    ','#    ','#### ','#   #','#   #','#   #','#   #','     ','     '],
    'e': ['     ','     ',' ### ','#   #','#####','#    ',' ####','     ','     '],
    'l': [' ##  ','  #  ','  #  ','  #  ','  #  ','  #  ',' ### ','     ','     '],
}


def ascii_art(variant='title-short'):
    label = VARIANTS.get(variant, VARIANTS['title-short'])
    return '\n'.join(' '.join(GLYPHS[c][row] for c in label).rstrip() for row in range(9))


# 2.1: the mobile app's colour icons, also selectable on the desktop.
MOBILE_ICONS = {'default': 'Tg-As', 'light': 'Tg-As · Light', 'orange': 'Tg-As · Orange', 'blue': 'Tg-As · Blue',
                'red': 'Tg-As · Red', 'pink': 'Tg-As · Pink'}


def custom_icon_path(value):
    """The custom_icon preference: a file path, or 'mobile:<name>' for a bundled mobile icon."""
    if isinstance(value, str) and value.startswith('mobile:') and value[7:] in MOBILE_ICONS:
        return Path(__file__).parent / 'assets' / f'mobile-{value[7:]}.png'
    path = Path(value) if value else None
    return path if path is not None and path.is_file() else None


def filename(variant, theme):
    variant = variant if variant in VARIANTS else 'title-short'
    theme = theme if theme in ('dark', 'light') else 'dark'
    return f'logo-{variant}-{theme}.png'


def asset_path(variant, theme):
    return Path(__file__).parent / 'assets' / filename(variant, theme)


def brand_asset_path(root, variant, theme, color='default', size=512):
    """Render only the branded PNGs the app uses, in its writable cache."""
    variant = variant if variant in VARIANTS else 'title-short'
    theme = theme if theme in ('dark', 'light') else 'dark'
    color = color if color in LOGO_PALETTES else 'default'
    folder = Path(root) / 'logo-cache'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / f'telegraph-mobile-face-v3-{variant}-{color}-{theme}-{size}.png'
    if path.is_file():
        return path
    temporary = None
    try:
        with NamedTemporaryFile(dir=folder, delete=False) as output:
            temporary = Path(output.name)
            output.write(png_bytes(variant, theme, size, color=color))
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def wordmark_layout(rows):
    """Return the cell size relative to the badge and the optical center in cells."""
    width = max(map(len, rows))
    # Share one cell scale for the five-character marks; longer names
    # scale to fit the same horizontal margins.
    cell = .93 / max(29, width)
    ink = [(x, y) for y, row in enumerate(rows) for x, char in enumerate(row) if char == '#']
    center_x = (min(x for x, _ in ink) + max(x for x, _ in ink) + 1) / 2
    center_y = (min(y for _, y in ink) + max(y for _, y in ink) + 1) / 2
    # Balance the ink without sacrificing visibly even margins. Descenders
    # and asymmetric glyphs carry less visual weight than the main letters.
    mass_x = sum(x + .5 for x, _ in ink) / len(ink)
    mass_y = sum(y + .5 for _, y in ink) / len(ink)
    center_x += max(-.25, min(.25, (mass_x - center_x) * .35))
    center_y += max(-.25, min(.25, (mass_y - center_y) * .35))
    return cell, center_x, center_y


# Ink boundaries in the 1024 px primary icon shipped on mobile before 3.0.
# Coordinates are relative to each letter and to the top of the capital T.
MOBILE_RECTS = {
    'T': [(0,0,159,36), (57,36,97,204)],
    'g': [(28,49,122,82), (0,73,40,161), (104,73,144,223),
          (20,150,144,186), (20,214,118,250)],
    '-': [(0,102,78,138)],
    'A': [(26,0,124,36), (0,30,40,204), (112,30,151,204), (0,102,151,138)],
    's': [(23,49,118,82), (0,73,41,121), (21,105,118,140),
          (102,129,146,179), (3,168,118,204)],
    # Extensions use the same cap line (0), x-height (49), baseline (204)
    # and descender (250). Stems are 40 units, bars 33–36 units.
    'G': [(26,0,129,36), (110,26,151,61), (0,29,40,176), (24,168,130,204),
          (111,101,151,175), (74,101,151,137)],
    'R': [(0,0,40,204), (36,0,126,36), (111,28,151,99),
          (35,93,130,129), (70,123,110,151), (90,147,130,178), (111,173,151,204)],
    'P': [(0,0,40,204), (36,0,126,36), (111,28,151,99), (35,93,130,129)],
    'H': [(0,0,40,204), (111,0,151,204), (38,86,113,122)],
    'E': [(0,0,40,204), (38,0,145,36), (38,85,124,121), (38,168,145,204)],
    'L': [(0,0,40,204), (38,168,139,204)],
    'r': [(0,49,40,204), (37,66,68,97), (61,49,123,82), (104,73,144,101)],
    'a': [(21,49,117,82), (103,73,143,204), (23,111,105,143),
          (0,133,40,182), (22,171,106,204)],
    'p': [(0,49,40,250), (36,49,119,82), (104,73,144,180), (36,171,119,204)],
    'h': [(0,0,40,204), (36,49,120,82), (104,73,144,204)],
    'e': [(23,49,119,82), (0,73,40,180), (104,73,144,131),
          (38,107,106,138), (22,171,134,204)],
    'l': [(0,0,40,183), (19,171,69,204)],
    't': [(29,9,69,179), (0,49,106,82), (49,171,111,204)],
}


def mobile_wordmark(variant):
    """Ink rectangles on a 1024-square canvas shared with the native renderers."""
    label = VARIANTS.get(variant, VARIANTS['title-short'])
    ink = []
    cursor = 0
    for index, letter in enumerate(label):
        glyph = MOBILE_RECTS[letter]
        if index:
            # A lowercase bowl fits under the arm of T, as in the original Tg-As.
            cursor += 1 if label[index - 1] == 'T' and letter in 'ge' else 30
        ink.extend((cursor+x, y, cursor+r, b) for x,y,r,b in glyph)
        cursor += max(r for _,_,r,_ in glyph)
    scale = min(1.0, 770 / cursor)
    left = (1024 - cursor * scale) / 2
    top = 512 - (min(y for _,y,_,_ in ink) + max(b for _,_,_,b in ink)) * scale / 2
    return [(round(left+x*scale), round(top+y*scale), round(left+r*scale), round(top+b*scale))
            for x,y,r,b in ink]


def png_bytes(variant='title-short', theme='dark', size=512, solid=True, *, color='default', full_bleed=False):
    """Render the application's ASCII text into a portable, rounded RGBA icon."""
    # Legacy macOS .icns uses an inset 824-point silhouette in a 1024 canvas.
    inset = 0 if full_bleed else round(size * 100 / 1024)
    extent = size - 2 * inset
    bg_rgb, fg_rgb = LOGO_PALETTES[color][theme]
    fg, bg = (*fg_rgb, 255), (*bg_rgb, 255)
    # Small literal # character, on a five by five monospaced cell.
    hash_rows = (' # # ', '#####', ' # # ', '#####', ' # # ')
    half = extent / 2
    center = (size - 1) / 2
    raw = bytearray()
    if solid:
        # Compose whole scanlines, including the transparent desktop-icon margins.
        rows_rgba = []
        for y in range(size):
            distance = abs((y-center)/half)
            radius = half * max(0.0, 1-distance**4)**0.25
            edge = max(0, min(size//2, round(size/2-radius)))
            rows_rgba.append(bytearray(bytes(4*edge) + bytes(bg)*(size-2*edge) + bytes(4*edge)))
        for x, y, r, b in mobile_wordmark(variant):
            x, y, r, b = (inset + round(n * extent / 1024) for n in (x,y,r,b))
            stripe = bytes(fg) * (r-x)
            for line in rows_rgba[y:b]:
                line[4*x:4*r] = stripe
        raw = b''.join(b'\x00'+line for line in rows_rgba)
    else:
        rows = ascii_art(variant).splitlines()
        cell_fraction, center_x, center_y = wordmark_layout(rows)
        cell = extent * cell_fraction
        left, top = size / 2 - center_x * cell, size / 2 - center_y * cell
        for y in range(size):
            raw.append(0)
            for x in range(size):
                # Continuous superellipse corners, with no added shadow or gradient.
                inside = (abs(x-center)/half)**4 + (abs(y-center)/half)**4 <= 1
                color = bg if inside else (0,0,0,0)
                col, row = int((x-left)//cell), int((y-top)//cell)
                if 0 <= row < len(rows) and 0 <= col < len(rows[row]) and rows[row][col] == '#':
                    hx, hy = int(((x-left)%cell)*5//cell), int(((y-top)%cell)*5//cell)
                    if hash_rows[hy][hx] == '#': color = fg
                raw.extend(color)
    def chunk(kind, data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',size,size,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(raw,9))+chunk(b'IEND',b'')
