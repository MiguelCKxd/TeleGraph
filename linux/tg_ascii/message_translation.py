"""Telegram message translation shared by the desktop, phone and watch."""
import re

from telethon import errors, functions


def watch_language(value):
    language = str(value).replace('_', '-').split('-', 1)[0].lower()
    if not re.fullmatch('[a-z]{2,3}', language):
        raise ValueError('Invalid translation language.')
    return {'an': 'es', 'oc': 'ca'}.get(language, language)


async def translate_rows(client, peer, ids, language, incomplete='Incomplete translation. Try again.'):
    translated = {}
    # A deleted message can invalidate its batch. Isolate invalid input while
    # allowing rate limits, connectivity failures and server errors to propagate.
    invalid = (errors.MsgIdInvalidError, errors.MessageIdInvalidError, errors.InputTextEmptyError)

    async def translate(batch):
        try:
            response = await client(functions.messages.TranslateTextRequest(to_lang=language, peer=peer, id=batch))
        except invalid:
            if len(batch) > 1:
                middle = len(batch) // 2
                await translate(batch[:middle])
                await translate(batch[middle:])
            return
        if len(response.result) != len(batch):
            raise ValueError(incomplete)
        translated.update(zip(batch, response.result))

    for start in range(0, len(ids), 20):
        await translate(ids[start:start + 20])
    return translated
