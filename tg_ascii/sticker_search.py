"""Per-account bounded catalogue cache and Telegram sticker/emoji search."""
import asyncio
from collections import OrderedDict
import time
import unicodedata
from telethon import functions


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',value.casefold()) if not unicodedata.combining(c) and c not in '\ufe0e\ufe0f').strip()


def emoji_query(value):
    return bool(value.strip()) and any(ord(c)>=0x1f000 or 0x2600<=ord(c)<=0x27ff or c in '\u20e3\u00a9\u00ae\u3030\u303d\u3297\u3299' for c in value) and not any(c.isalpha() for c in value)


def matching_packs(packs,query):
    words=normalized(query).split()
    if not words:return list(packs)
    result=[]
    for pack in packs:
        title=normalized(getattr(pack,'title','')+' '+getattr(pack,'short_name',''))
        if all(word in title for word in words):result.append(pack)
    return result


def matching_documents(documents,query):
    from .telegram_extras import sticker_alt
    needle=normalized(query)
    return [d for d in documents if needle and needle in normalized(sticker_alt(d))]


def unique(items):
    return list({item.id:item for item in items}.values())


async def cached(backend,key,loader,ttl=60):
    cache=getattr(backend,'_sticker_catalogue',None)
    if cache is None:cache=backend._sticker_catalogue=OrderedDict()
    entry=cache.get(key)
    if entry and time.monotonic()-entry[0]<ttl:cache.move_to_end(key);return entry[1]
    jobs=getattr(backend,'_sticker_jobs',None)
    if jobs is None:jobs=backend._sticker_jobs={}
    generation=getattr(backend,'_sticker_generation',0)
    job_key=(generation,key)
    job=jobs.get(job_key)
    if job is None:
        async def fetch():
            result=await asyncio.wait_for(loader(),timeout=15)
            # An install/settings change may invalidate the cache during the RPC.
            if generation==getattr(backend,'_sticker_generation',0):
                cache[key]=(time.monotonic(),result);cache.move_to_end(key)
                while len(cache)>64:cache.popitem(last=False)
            return result
        job=jobs[job_key]=[asyncio.create_task(fetch()),0]
    job[1]+=1
    try:
        # Closing one view must not cancel an RPC still used by another view.
        return await asyncio.shield(job[0])
    finally:
        job[1]-=1
        if not job[1]:
            jobs.pop(job_key,None)
            if not job[0].done():job[0].cancel()
            await asyncio.gather(job[0],return_exceptions=True)


def invalidate(backend):
    backend._sticker_generation=getattr(backend,'_sticker_generation',0)+1
    getattr(backend,'_sticker_catalogue',{}).clear()


async def cancel_pending(backend):
    jobs=list(getattr(backend,'_sticker_jobs',{}).values())
    for task,_ in jobs:task.cancel()
    await asyncio.gather(*(task for task,_ in jobs),return_exceptions=True)


async def search(backend,query,custom=False,language='en',offset=0):
    query=query.strip()[:100]
    if not query:return {'documents':[],'packs':[],'next':None}
    language=language.split('-')[0]
    async def fetch():
        is_emoji=emoji_query(query)
        request=functions.messages.SearchStickersRequest(q='' if is_emoji else query,emoticon=query if is_emoji else '',
                    lang_code=[language],offset=offset,limit=60,hash=0,emojis=True if custom else None)
        operations=[backend.client(request)]
        if not is_emoji and not offset:
            method=functions.messages.SearchEmojiStickerSetsRequest if custom else functions.messages.SearchStickerSetsRequest
            operations.append(backend.client(method(q=query,hash=0)))
        results=await asyncio.gather(*operations,return_exceptions=True)
        if all(isinstance(r,Exception) for r in results):raise results[0]
        first=results[0];docs=list(getattr(first,'stickers',[]) or [])
        packs=[covered.set for covered in getattr(results[-1],'sets',[]) or []] if len(results)>1 else []
        next_offset=getattr(first,'next_offset',None)
        return {'documents':unique(docs),'packs':unique(packs),'next':next_offset if docs and next_offset is not None and next_offset>offset else None}
    return await cached(backend,('search',custom,query,language,offset),fetch,60)


class PickerRequests:
    """Cancel obsolete searches and prevent late results from replacing a newer view."""
    def __init__(self,app,window,current):
        self.app,self.window,self.current=app,window,current;self.version=0;self.future=None;self.timer=None
    def cancel(self):
        self.version+=1
        if self.future is not None:self.future.cancel();self.future=None
        if self.timer is not None:self.window.after_cancel(self.timer);self.timer=None
    def load(self,operation,done,failed,delay=0):
        self.cancel();version=self.version
        def valid():return version==self.version and self.window.winfo_exists() and self.current()
        def start():
            self.timer=None
            if valid():self.future=self.app.worker.submit(operation(),lambda value:done(value) if valid() else None,lambda error:failed(error) if valid() else None)
        if delay:self.timer=self.window.after(delay,start)
        else:start()
