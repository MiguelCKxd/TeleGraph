"""Resolve the actual author using peer IDs and the message's access-hash context."""
import asyncio
from collections import OrderedDict
import time
from telethon import types,utils,errors

NEGATIVE_CACHE_TTL=30
NEGATIVE_CACHE_LIMIT=1024
SENDER_BATCH_SIZE=100


def peer_id(value):
    if value is None:return None
    try:return utils.get_peer_id(value)
    except (TypeError,ValueError):return None


def author_id(message):
    # from_id is authoritative: an unrelated attached entity must never supply the label.
    ident=peer_id(getattr(message,'from_id',None))
    if ident is None:ident=getattr(message,'sender_id',None)
    if ident is None:ident=peer_id(getattr(message,'sender',None))
    if ident is None:
        peer=getattr(message,'peer_id',None)
        if getattr(message,'post',False) or not getattr(message,'out',False) and isinstance(peer,types.PeerUser):ident=peer_id(peer)
    return ident


def own_message(message, ident):
    return bool(getattr(message,'out',False)) and not (ident is not None and ident<0) and not getattr(message,'post',False)


def label(entity):
    if entity is None:return ''
    return ' '.join((utils.get_display_name(entity) or getattr(entity,'username','') or '').split())


def display_label(message, ident):
    """A missing entity is an unresolved identity, never somebody else's name."""
    from .i18n import tr
    if ident is None:
        return tr('Mensaje de servicio') if getattr(message, 'action', None) else tr('Autor no disponible')
    bare, kind = utils.resolve_id(ident)
    category = tr('Usuario') if kind is types.PeerUser else tr('Canal') if kind is types.PeerChannel else tr('Grupo')
    return f'{category} #{bare}'


def attached_author(message, ident):
    attached = [getattr(message, 'sender', None), getattr(message, 'chat', None)]
    # Telethon may retain entities in an update/history map before the sender
    # property has been hydrated. Marked IDs are checked before trusting a name.
    entities = getattr(message, '_entities', None)
    if isinstance(entities, dict):
        attached.append(entities.get(ident))
        if ident is not None:
            bare, _ = utils.resolve_id(ident)
            attached.append(entities.get(bare))
    for entity in attached:
        if peer_id(entity)==ident and label(entity):return entity
    return None


async def resolve(backend, messages):
    messages=[m for m in messages if m is not None]
    missing={}
    for message in messages:
        ident=author_id(message)
        entity=attached_author(message,ident)
        if entity is not None:backend.cache_name(ident,label(entity))
        if ident is not None and not own_message(message,ident):missing.setdefault(ident,message)
    negative=getattr(backend,'_sender_failures',None)
    if negative is None:negative=backend._sender_failures=OrderedDict()
    now=time.monotonic()
    if now<getattr(backend,'_sender_retry_at',0):return
    missing={ident:message for ident,message in missing.items() if ident not in backend.names
             and now-negative.get(ident,float('-inf'))>=NEGATIVE_CACHE_TTL}
    if not missing:return
    jobs=getattr(backend,'_sender_jobs',None)
    if jobs is None:jobs=backend._sender_jobs={}
    owned={ident:message for ident,message in missing.items() if ident not in jobs}
    if owned:
        record=getattr(backend,'_sender_collecting',None)
        if record is not None and not record[0].done() and len(record[2])+len(owned)<=SENDER_BATCH_SIZE:
            record[2].update(owned)
        else:
            # Requests already queued in this loop turn can share one entity
            # batch. No timer or extra network latency is introduced.
            record=[None,0,dict(owned)]
            async def fetch(record=record):
                if getattr(backend,'_sender_collecting',None) is record:
                    backend._sender_collecting=None
                await _resolve_missing(backend,record[2])
                for ident in record[2]:
                    if ident not in backend.names:
                        negative[ident]=time.monotonic();negative.move_to_end(ident)
                while len(negative)>NEGATIVE_CACHE_LIMIT:negative.popitem(last=False)
            record[0]=asyncio.create_task(fetch())
            backend._sender_collecting=record
        for ident in owned:jobs[ident]=record
    records={id(jobs[ident]):jobs[ident] for ident in missing}.values()
    records=list(records)
    for record in records:record[1]+=1
    try:
        await asyncio.gather(*(asyncio.shield(record[0]) for record in records))
    finally:
        finished=[]
        for record in records:
            record[1]-=1
            if not record[1]:
                if getattr(backend,'_sender_collecting',None) is record:
                    backend._sender_collecting=None
                for ident in record[2]:
                    if jobs.get(ident) is record:jobs.pop(ident)
                if not record[0].done():record[0].cancel()
                finished.append(record[0])
        await asyncio.gather(*finished,return_exceptions=True)


async def cancel_pending(backend):
    backend._sender_collecting=None
    tasks={record[0] for record in getattr(backend,'_sender_jobs',{}).values()}
    for task in tasks:task.cancel()
    await asyncio.gather(*tasks,return_exceptions=True)


async def _resolve_missing(backend,missing):
    recoverable=(ValueError,TypeError,errors.RPCError,OSError,TimeoutError)
    slots=getattr(backend,'_sender_slots',None)
    if slots is None:slots=backend._sender_slots=asyncio.Semaphore(4)
    def waiting():return time.monotonic()<getattr(backend,'_sender_retry_at',0)
    def rate_limit(exc):
        backend._sender_retry_at=max(getattr(backend,'_sender_retry_at',0),time.monotonic()+max(1,exc.seconds))
    try:
        async with asyncio.timeout(8):
            async with slots:
                if waiting():return
                entities=await backend.client.get_entity(list(missing))
        for entity in entities:
            ident=peer_id(entity)
            if ident in missing:backend.cache_name(ident,label(entity))
    except errors.FloodWaitError as exc:rate_limit(exc);return
    except recoverable:pass
    # One unresolvable ID must not discard the rest of a batch.
    async def one(ident,message):
        async with slots:
            if ident in backend.names or waiting():return
            getter=getattr(message,'get_sender',None)
            if getter:
                try:
                    entity=await asyncio.wait_for(getter(),timeout=3)
                    if peer_id(entity)==ident and label(entity):backend.cache_name(ident,label(entity));return
                except errors.FloodWaitError as exc:rate_limit(exc);return
                except recoverable:pass
            # An incoming channel/private post may omit from_id; use its chat context.
            if peer_id(getattr(message,'peer_id',None))==ident:
                getter=getattr(message,'get_chat',None)
                if getter:
                    try:
                        entity=await asyncio.wait_for(getter(),timeout=3)
                        if peer_id(entity)==ident and label(entity):backend.cache_name(ident,label(entity));return
                    except errors.FloodWaitError as exc:rate_limit(exc);return
                    except recoverable:pass
            if waiting():return
            try:
                entity=await asyncio.wait_for(backend.client.get_entity(ident),timeout=3)
                if peer_id(entity)==ident:backend.cache_name(ident,label(entity))
            except errors.FloodWaitError as exc:rate_limit(exc);return
            except recoverable:pass
    pending=iter((ident,message) for ident,message in missing.items() if ident not in backend.names)
    async def worker():
        for ident,message in pending:
            await one(ident,message)
    try:await asyncio.wait_for(asyncio.gather(*(worker() for _ in range(min(4,len(missing))))),timeout=8)
    except TimeoutError:pass  # Successful names stay cached; inaccessible identities do not block the chat.
