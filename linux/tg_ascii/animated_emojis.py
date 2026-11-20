"""Telegram's standard animated-emoji pack, resolved without changing source text."""
from dataclasses import replace
import unicodedata
from .preferences import animated_emoji_enabled


def candidate(message):
    if message.media:return ''
    text=(message.raw_text if message.raw_text is not None else message.text).strip()
    if not text or len(text)>12:return ''
    if any(type(entity).__name__=='MessageEntityCustomEmoji' for entity in message.entities):return ''
    if not any(unicodedata.category(char) in ('So','Sk') or char=='\u20e3' for char in text):return ''
    if any(unicodedata.category(char) not in ('So','Sk','Mn','Me','Cf') and char not in '0123456789#*' for char in text):return ''
    return text.replace('\ufe0f','')


def animated_content(app,message):
    if not animated_emoji_enabled(app.preferences.values):return message
    key=candidate(message)
    document=getattr(app,'_standard_emoji_packs',{}).get(app.ui_account,{}).get(key)
    if document is None:return message
    from telethon import types
    text=message.raw_text if message.raw_text is not None else message.text
    # This entity exists only in the local view; forwarding/editing uses the original.
    stripped = text.strip()
    start = len(text) - len(text.lstrip())
    entity = types.MessageEntityCustomEmoji(len(text[:start].encode('utf-16-le'))//2,
                                          len(stripped.encode('utf-16-le'))//2,document.id)
    return replace(message,raw_text=text,entities=(*message.entities,entity))


def ensure_pack(app):
    if app.demo or app.active is None or not animated_emoji_enabled(app.preferences.values):return
    if not any(candidate(message) for message in app.messages):return
    from .animation import renderer_available
    if not renderer_available('application/x-tgsticker'):return
    account,backend=app.ui_account,app.service.backend
    if not hasattr(app,'_standard_emoji_packs'):app._standard_emoji_packs={};app._standard_emoji_pending=set();app._standard_emoji_documents={}
    if account in app._standard_emoji_packs or account in app._standard_emoji_pending:return
    import time
    if time.monotonic() < getattr(app,'_standard_emoji_retry',{}).get(account,0):return
    app._standard_emoji_pending.add(account)
    async def fetch():
        from telethon import functions,types
        return await backend.client(functions.messages.GetStickerSetRequest(types.InputStickerSetAnimatedEmoji(),hash=0))
    def loaded(result):
        app._standard_emoji_pending.discard(account)
        if account not in app.service.entries:return
        docs={doc.id:doc for doc in result.documents}
        app._standard_emoji_packs[account]={pack.emoticon.replace('\ufe0f',''):docs[pack.documents[0]] for pack in result.packs if pack.documents and pack.documents[0] in docs}
        app._standard_emoji_documents.update({(account,key):value for key,value in docs.items()})
        if account==app.ui_account and backend is app.service.backend:app.render_messages(False)
    def failed(_):
        app._standard_emoji_pending.discard(account)
        if not hasattr(app,'_standard_emoji_retry'):app._standard_emoji_retry={}
        app._standard_emoji_retry[account]=time.monotonic()+30
    app.worker.submit(fetch(),loaded,failed)
