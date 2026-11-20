"""Lightweight boundaries for emoji sequences and combining text in Tk layouts.

Keep joined emoji, skin tones, flags, keycaps and combining marks together when
wrapping or shortening a label. No network lookup or optional font package is
needed for this purely textual operation.
"""
import unicodedata


def cluster_ends(text):
    """Return character offsets after each display cluster used by our layouts."""
    return list(iter_cluster_ends(text))


def iter_cluster_ends(text):
    """Yield boundaries lazily so short previews never scan an entire message."""
    regional = 0
    for index, char in enumerate(text):
        code = ord(char)
        previous = text[index - 1] if index else ''
        flag = 0x1F1E6 <= code <= 0x1F1FF
        extension = (unicodedata.category(char) in ('Mn', 'Mc', 'Me')
                     or 0x1F3FB <= code <= 0x1F3FF
                     or 0xE0020 <= code <= 0xE007F)
        joined = (index and (extension or char == '\u200d' or previous == '\u200d'
                             or flag and regional % 2 == 1
                             or previous == '\r' and char == '\n'))
        if index and not joined:
            yield index
        regional = regional + 1 if flag else 0
    if text:yield len(text)
