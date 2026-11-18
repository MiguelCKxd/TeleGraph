"""Lossless article editing and bounded text fallback for Telegram rich messages."""
from copy import deepcopy

from telethon import types as t
from telethon import utils

from .i18n import tr


def article_input(source, *, format='markdown', rtl=False, noautolink=False):
    if not isinstance(source, str) or not source.strip() or len(source) > 32768:
        raise ValueError(tr('An article must contain between 1 and 32768 characters.'))
    cls = {'markdown': t.InputRichMessageMarkdown, 'html': t.InputRichMessageHTML}.get(format)
    if cls is None: raise ValueError(tr('Choose Markdown or HTML.'))
    return cls(source, rtl=bool(rtl), noautolink=bool(noautolink))


def rich_text(value, depth=0):
    if depth > 16 or value is None: return ''
    if isinstance(value, str): return value
    if isinstance(value, t.TextConcat):
        return ''.join(rich_text(item, depth + 1) for item in value.texts[:500])
    text = rich_text(getattr(value, 'text', None), depth + 1)
    if hasattr(value, 'url') and value.url:
        text += ' (' + value.url + ')' if value.url != text else ''
    if not text:
        text = str(getattr(value, 'alt', '') or getattr(value, 'name', '') or getattr(value, 'formula', '') or '')
    return text


def block_text(block, depth=0):
    if depth > 16: return ''
    pieces = []
    for name in ('title', 'text', 'author', 'language'):
        value = getattr(block, name, None)
        if value is not None:
            text = rich_text(value, depth + 1)
            if text: pieces.append(text)
    if isinstance(block, t.PageBlockDivider): pieces.append('────────')
    caption = getattr(block, 'caption', None)
    if caption is not None:
        pieces.append(rich_text(getattr(caption, 'text', caption), depth + 1))
        if getattr(caption, 'credit', None): pieces.append(rich_text(caption.credit, depth + 1))
    for name in ('blocks', 'items'):
        for item in (getattr(block, name, None) or ())[:500]:
            pieces.append(block_text(item, depth + 1))
    for row in (getattr(block, 'rows', None) or ())[:500]:
        pieces.append(' | '.join(rich_text(getattr(cell, 'text', None), depth + 1) for cell in row.cells[:20]))
    if getattr(block, 'photo_id', None): pieces.append(tr('[Photo]'))
    if getattr(block, 'video_id', None): pieces.append(tr('[Video]'))
    if getattr(block, 'audio_id', None): pieces.append(tr('[Audio]'))
    if getattr(block, 'document_id', None): pieces.append(tr('[Document]'))
    if getattr(block, 'geo', None):
        geo = block.geo
        if isinstance(geo, t.GeoPoint): pieces.append(f'{geo.lat:.6f}, {geo.long:.6f}')
    return '\n'.join(piece for piece in pieces if piece)


def rich_article_text(rich, maximum=32768):
    if rich is None: return ''
    text = '\n\n'.join(block_text(block) for block in (getattr(rich, 'blocks', None) or ())[:500])
    return text[:maximum] or tr('[Article]')


def editable_article(rich):
    """Keep every block and media reference rather than flattening on save."""
    if not isinstance(rich, t.RichMessage) or rich.part:
        raise ValueError(tr('Load the complete article before editing it.'))
    return t.InputRichMessage(deepcopy(rich.blocks), rtl=rich.rtl,
                              photos=[utils.get_input_photo(photo) for photo in rich.photos or ()],
                              documents=[utils.get_input_document(document) for document in rich.documents or ()])


def article_fields(value, prefix=(), depth=0):
    """Return editable leaf fields; unknown formatting and media stay untouched."""
    if depth > 16: return []
    result = []
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value[:500]):
            result.extend(article_fields(item, prefix + (index,), depth + 1))
    elif hasattr(value, 'to_dict'):
        for name, item in vars(value).items():
            if name.startswith('_'): continue
            if isinstance(item, str) and name in ('text', 'url', 'language', 'name', 'alt', 'formula', 'email', 'phone'):
                result.append((prefix + (name,), type(value).__name__ + ' · ' + name, item))
            elif isinstance(item, (list, tuple)) or hasattr(item, 'to_dict'):
                result.extend(article_fields(item, prefix + (name,), depth + 1))
    return result


def replace_article_field(article, path, value):
    """Only an advertised text leaf can be modified; arbitrary attributes cannot."""
    if path not in {entry[0] for entry in article_fields(article.blocks)}:
        raise ValueError(tr('This article field is no longer available.'))
    if not isinstance(value, str) or len(value) > 32768:
        raise ValueError(tr('This article field is too long.'))
    target = article.blocks
    for part in path[:-1]: target = target[part] if isinstance(part, int) else getattr(target, part)
    setattr(target, path[-1], value)


def article_media(rich):
    """Deduplicated Telegram objects available for explicit open/download."""
    result = []
    for item in getattr(rich, 'photos', None) or ():
        result.append((tr('Photo') + f' · {len(result) + 1}', t.MessageMediaPhoto(item)))
    for item in getattr(rich, 'documents', None) or ():
        filename = next((entry.file_name for entry in item.attributes if isinstance(entry, t.DocumentAttributeFilename)), None)
        result.append((filename or tr('Document') + f' · {len(result) + 1}', t.MessageMediaDocument(item)))
    return result
