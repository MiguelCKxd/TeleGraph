"""Per-account, bounded and coalesced custom emoji metadata requests."""
import asyncio
from collections import OrderedDict
import time
import sys

from telethon import functions

MAX_DOCUMENT_CACHE_BYTES = 2 * 1024 * 1024


def metadata_bytes(document):
    """Count retained Python metadata, including embedded cached thumbnails."""
    pending=[document];seen=set();total=0
    while pending:
        item=pending.pop();identity=id(item)
        if identity in seen:continue
        seen.add(identity);total+=sys.getsizeof(item)
        if total>MAX_DOCUMENT_CACHE_BYTES:return total
        if isinstance(item,dict):pending.extend(item.keys());pending.extend(item.values())
        elif isinstance(item,(list,tuple,set,frozenset)):pending.extend(item)
        elif hasattr(item,'__dict__'):pending.append(vars(item))
    return total


class EmojiDocuments:
    def __init__(self, backend):
        self.backend = backend
        self.cache = OrderedDict()
        self.pending = {}
        self.task = None
        self.cache_bytes=0
        self._costs={}

    def _remember(self,ident,document,now):
        cost=metadata_bytes(document)
        self.cache.pop(ident,None);self.cache_bytes-=self._costs.pop(ident,0)
        if cost>MAX_DOCUMENT_CACHE_BYTES:return
        self.cache[ident]=(now,document);self._costs[ident]=cost;self.cache_bytes+=cost
        while len(self.cache)>512 or self.cache_bytes>MAX_DOCUMENT_CACHE_BYTES:
            old,_=self.cache.popitem(last=False)
            self.cache_bytes-=self._costs.pop(old,0)

    def remember(self, documents):
        now = time.monotonic()
        for document in documents:
            if getattr(document, 'attributes', None) is not None:
                self._remember(document.id,document,now)

    def invalidate(self,identifiers):
        for ident in identifiers:
            self.cache.pop(ident,None);self.cache_bytes-=self._costs.pop(ident,0)

    async def get(self, identifiers):
        identifiers = list(dict.fromkeys(int(value) for value in identifiers))
        resolved, waiting = {}, {}
        now = time.monotonic()
        for ident in identifiers:
            entry = self.cache.get(ident)
            if entry and now - entry[0] < (3600 if entry[1] is not None else 60):
                self.cache.move_to_end(ident)
                resolved[ident] = entry[1]
                continue
            if ident not in self.pending:
                future = self.pending[ident] = asyncio.get_running_loop().create_future()
                # A closed view can abandon its wait while another view still
                # needs the batch. Consume errors even if every view has closed.
                future.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
            waiting[ident] = self.pending[ident]
        if waiting:
            if self.task is None:
                self.task = asyncio.create_task(self.fetch())
            values = await asyncio.gather(*(asyncio.shield(value) for value in waiting.values()))
            resolved.update(zip(waiting, values))
        return [resolved[ident] for ident in identifiers if resolved.get(ident) is not None]

    async def fetch(self):
        try:
            # Calls created together by a message redraw share a single RPC.
            await asyncio.sleep(0)
            while self.pending:
                batch = dict(list(self.pending.items())[:100])
                try:
                    # Metadata reads are idempotent: wait out a short FLOOD_WAIT
                    # instead of failing every emoji of every open view at once.
                    from .flood_control import read_with_flood_wait
                    documents = await read_with_flood_wait(self.backend, 'emoji_documents', lambda: asyncio.wait_for(
                        self.backend.client(functions.messages.GetCustomEmojiDocumentsRequest(list(batch))), 15))
                    self.remember(documents)
                    found = {document.id: document for document in documents
                             if getattr(document, 'attributes', None) is not None}
                    for ident, future in batch.items():
                        document = found.get(ident)
                        if document is None:
                            self._remember(ident,None,time.monotonic())
                        if not future.done():
                            future.set_result(document)
                except asyncio.CancelledError:
                    for future in batch.values():
                        if not future.done():
                            future.cancel()
                    raise
                except Exception as exc:
                    for future in batch.values():
                        if not future.done():
                            future.set_exception(exc)
                finally:
                    for ident, future in batch.items():
                        if self.pending.get(ident) is future:
                            self.pending.pop(ident, None)
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.cancel()
            self.pending.clear()
            self.task = None

    async def cancel(self):
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.cache.clear();self._costs.clear();self.cache_bytes=0


def catalogue(backend):
    value = getattr(backend, '_emoji_documents', None)
    if value is None:
        value = backend._emoji_documents = EmojiDocuments(backend)
    return value


async def documents(backend, identifiers):
    return await catalogue(backend).get(identifiers)


async def refresh_document(backend,document):
    """An expired reference is an explicit rejected read, safe to refresh once."""
    from telethon import types
    attribute=next((item for item in getattr(document,'attributes',()) if isinstance(item,
        (types.DocumentAttributeCustomEmoji,types.DocumentAttributeSticker))),None)
    if isinstance(attribute,types.DocumentAttributeCustomEmoji):
        catalogue(backend).invalidate([document.id])
        found=await documents(backend,[document.id])
    elif attribute is not None and not isinstance(attribute.stickerset,types.InputStickerSetEmpty):
        result=await backend.client(functions.messages.GetStickerSetRequest(attribute.stickerset,hash=0))
        found=result.documents;catalogue(backend).remember(found)
    else:return None
    return next((item for item in found if item.id==document.id),None)
