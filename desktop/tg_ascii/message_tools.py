"""Telegram entities, translation and AI. No third-party AI services or auto-send."""
from urllib.parse import urlsplit
from telethon import functions, types
from .i18n import tr
from .telegram_extras import custom_entities
from .transfers import transfer_timeout, tracked_transfer

STYLES = {'bold': types.MessageEntityBold, 'italic': types.MessageEntityItalic,
          'underline': types.MessageEntityUnderline, 'strike': types.MessageEntityStrike,
          'spoiler': types.MessageEntitySpoiler, 'code': types.MessageEntityCode,
          'link': types.MessageEntityTextUrl, 'quote': types.MessageEntityBlockquote,
          'collapsed_quote': types.MessageEntityBlockquote}


def formatted_entities(text, spans=(), emojis=()):
    entities = custom_entities(text, emojis)
    ranges = []
    for start, end, style, argument in spans:
        if style not in STYLES or not 0 <= start < end <= len(text):
            raise ValueError(tr('Invalid text formatting.'))
        if style == 'link' and (urlsplit(argument).scheme not in ('http', 'https', 'tg') or any(c.isspace() for c in argument)):
            raise ValueError(tr('Use an https://, http:// or tg:// link.'))
        for a, b, previous in ranges:
            overlaps = start < b and end > a
            nested = start <= a and end >= b or a <= start and b >= end
            if overlaps and (not nested or style == 'code' or previous == 'code' or style == previous == 'link'
                             or style in ('quote','collapsed_quote') and previous in ('quote','collapsed_quote')):
                raise ValueError(tr('Remove overlapping formatting first.'))
        if style == 'code' and any(start < b and end > a for a, b, _, _ in emojis):
            raise ValueError(tr('Remove overlapping formatting first.'))
        offset = len(text[:start].encode('utf-16-le')) // 2
        length = len(text[start:end].encode('utf-16-le')) // 2
        if style in ('quote','collapsed_quote'):
            entities.append(types.MessageEntityBlockquote(offset,length,collapsed=style=='collapsed_quote'))
        else:entities.append(STYLES[style](offset, length, argument) if style == 'link' else STYLES[style](offset, length))
        ranges.append((start, end, style))
    return sorted(entities, key=lambda e: (e.offset, -e.length))


def entity_spans(text, entities):
    """Convert Telegram UTF-16 entity ranges to Python indexes for editor tags."""
    if not entities:return [],[]
    positions, offset = {0: 0}, 0
    for index, char in enumerate(text):
        offset += 2 if ord(char)>0xffff else 1
        positions[offset] = index + 1
    spans, emojis = [], []
    for entity in entities:
        start, end = positions.get(entity.offset), positions.get(entity.offset + entity.length)
        if start is None or end is None or start >= end: continue
        if isinstance(entity, types.MessageEntityCustomEmoji):
            emojis.append((start, end, entity.document_id, text[start:end]))
        if isinstance(entity,types.MessageEntityBlockquote):
            spans.append((start,end,'collapsed_quote' if entity.collapsed else 'quote',''))
            continue
        for style, cls in STYLES.items():
            if isinstance(entity, cls): spans.append((start, end, style, getattr(entity, 'url', '')))
    return spans, emojis


def display_segments(message):
    """Replace custom-emoji entity ranges, never duplicate their Unicode fallback."""
    raw = message.raw_text if message.raw_text is not None else message.text
    _, emojis = entity_spans(raw, getattr(message, 'entities', ()))
    prefix = message.text[:-len(raw)] if raw and message.text.endswith(raw) else ''
    cursor = 0
    if prefix: yield prefix
    for start, end, document_id, _ in sorted(emojis):
        if start < cursor: continue
        if start > cursor: yield raw[cursor:start]
        yield document_id
        cursor = end
    if cursor < len(raw): yield raw[cursor:]
    if not raw and not prefix: yield message.text


class MessageTools:
    @tracked_transfer
    async def send_batch(self,peer,paths,text='',spans=(),emojis=(),progress=None,reply_to=None,silent=False,schedule=None):
        from contextlib import ExitStack
        from .backend import attachment_path
        from .secret_chats import is_secret_peer
        paths=[attachment_path(path) for path in paths]
        if not 2<=len(paths)<=10:raise ValueError(tr('Choose up to 10 files for one album.'))
        if is_secret_peer(peer):
            import secrets
            gid = secrets.randbits(62) or 1
            results = []
            async with transfer_timeout(progress) as report:
                for idx, path in enumerate(paths):
                    msg = await self.secret_chats.send_file(
                        peer, path, progress=report,
                        caption=text if idx == 0 else '',
                        spans=spans if idx == 0 else (),
                        emojis=emojis if idx == 0 else (),
                        reply_to=reply_to, silent=silent, grouped_id=gid,
                    )
                    results.append(msg)
            return results
        entities=formatted_entities(text,spans,emojis)
        from .emoji_usage import note
        note(self,emojis,text)
        photos=all(path.suffix.lower() in ('.jpg','.jpeg','.png','.webp') for path in paths)
        # Open every source before the request: missing/unreadable files cannot cause a partial upload batch.
        with ExitStack() as stack:
            streams=[stack.enter_context(path.open('rb')) for path in paths]
            async with transfer_timeout(progress) as report:
                messages=await self.client.send_file(peer,streams,caption=[text]+['']*(len(paths)-1),
                    formatting_entities=[entities]+[[] for _ in paths[1:]],parse_mode=None,force_document=not photos,
                    reply_to=reply_to,silent=silent,schedule=schedule,progress_callback=report)
        return [self.message(message) for message in messages]

    @tracked_transfer
    async def send_formatted(self, peer, text, spans, emojis=(), path=None, progress=None, reply_to=None, as_photo=False, silent=False, schedule=None):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            async with transfer_timeout(progress) as report:
                return await self.secret_chats.send_formatted(
                    peer, text, spans, emojis, path=path, progress=report,
                    reply_to=reply_to, as_photo=as_photo, silent=silent, schedule=schedule
                )
        entities = formatted_entities(text, spans, emojis)
        from .emoji_usage import note
        note(self, emojis, text)
        if path:
            from .backend import attachment_path
            with attachment_path(path).open('rb') as stream:
                async with transfer_timeout(progress) as report:
                    result = await self.client.send_file(peer, stream, caption=text, formatting_entities=entities,
                                                         parse_mode=None, force_document=not as_photo, progress_callback=report, reply_to=reply_to, silent=silent, schedule=schedule)
        else:
            result = await self.client.send_message(peer, text, formatting_entities=entities, parse_mode=None, reply_to=reply_to, silent=silent, schedule=schedule)
        return self.message(result)

    @tracked_transfer
    async def send_audio(self, peer, path, voice=False, duration=0, reply_to=None):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            async with transfer_timeout() as report:
                return await self.secret_chats.send_file(
                    peer, path, progress=report, voice=voice, duration=duration, reply_to=reply_to
                )
        from .backend import attachment_path
        options = {'force_document': False, 'voice_note': voice, 'reply_to': reply_to}
        if voice:
            options.update(mime_type='audio/ogg', attributes=[types.DocumentAttributeAudio(duration=max(1, round(duration)), voice=True)])
        with attachment_path(path).open('rb') as stream:
            async with transfer_timeout() as report:
                return self.message(await self.client.send_file(peer, stream, progress_callback=report, **options))

    async def translate_messages(self, peer, ids, language, premium=False):
        if premium and not await self.premium_enabled():
            raise ValueError(tr('Automatic chat translation requires Telegram Premium.'))
        from .message_translation import translate_rows

        peer = await self.client.get_input_entity(peer)
        return await translate_rows(self.client, peer, ids, language, tr('Incomplete translation. Try again.'))

    async def compose_ai(self, text, spans=(), emojis=(), mode='proofread', language='en'):
        if mode not in ('proofread', 'emojify', 'translate'): raise ValueError('Unknown AI operation')
        result = await self.client(functions.messages.ComposeMessageWithAIRequest(
            types.TextWithEntities(text, formatted_entities(text, spans, emojis)),
            proofread=True if mode == 'proofread' else None,
            emojify=True if mode == 'emojify' else None,
            translate_to_lang=language if mode == 'translate' else None))
        return result.result_text

    async def summarize_message(self, peer, message_id, language):
        return await self.client(functions.messages.SummarizeTextRequest(
            await self.client.get_input_entity(peer), message_id, to_lang=language))

    async def transcribe_audio(self, peer, message_id):
        return await self.client(functions.messages.TranscribeAudioRequest(
            await self.client.get_input_entity(peer), message_id))
