"""Transfer deadlines measure inactivity, not the total size of an upload."""
import asyncio
from asyncio import current_task
from contextlib import asynccontextmanager
from functools import wraps
import inspect
import math

UPLOAD_IDLE_TIMEOUT=120


async def owned_thread(operation, *args, **kwargs):
    """Finish an already-running file operation before its owner removes its files.

    Cancelling to_thread alone does not stop the thread. Waiting for that one
    operation prevents a late write from recreating a cancelled temporary file.
    The caller still receives CancelledError and never publishes the result.
    """
    task = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if task.done() and not task.cancelled():
            task.exception()  # Consume a late file error without losing cancellation.
        raise


class DownloadProgress:
    """Absolute bytes for this attempt, with an explicit reset on a retry.

    The cloud downloader supplies bytes actually written, not a sum of
    Telethon callbacks. A zero total means that the total is not known.
    """
    def __init__(self, callback=None):
        self.callback = callback
        self.last = None

    async def report(self, current, total):
        current = max(0, int(current))
        valid_total = type(total) is int or type(total) is float and math.isfinite(total)
        total = int(total) if valid_total and total >= current else 0
        value = (current, total)
        if self.last == value:
            return
        self.last = value
        if self.callback:
            result = self.callback(*value)
            if inspect.isawaitable(result):
                await result

    async def restart(self):
        if self.last is not None:
            await self.report(0, self.last[1])


@asynccontextmanager
async def transfer_scope(owner):
    """Own active and queued work so closing one backend cancels only its transfers."""
    if getattr(owner,'_transfers_closed',False):
        raise ConnectionError('Transfer service closed')
    tasks=getattr(owner,'_transfer_tasks',None)
    if tasks is None:tasks=owner._transfer_tasks={}
    task=current_task()
    tasks[task]=tasks.get(task,0)+1
    try:yield
    finally:
        depth=tasks[task]-1
        if depth:tasks[task]=depth
        else:tasks.pop(task,None)


def tracked_transfer(operation):
    @wraps(operation)
    async def tracked(owner,*args,**kwargs):
        async with transfer_scope(owner):
            return await operation(owner,*args,**kwargs)
    return tracked


async def cancel_transfers(owner):
    """Finish stream/temporary cleanup before disconnecting, without starting retries."""
    owner._transfers_closed=True
    current=current_task()
    tasks=[task for task in getattr(owner,'_transfer_tasks',()) if task is not current]
    for task in tasks:task.cancel()
    if tasks:await asyncio.gather(*tasks,return_exceptions=True)


@asynccontextmanager
async def transfer_timeout(progress=None,timeout=None):
    """Keep active transfers alive and preserve sync/async progress callbacks.

    Repeated progress values do not extend the deadline. This context never
    retries an operation: a timed-out send may already have reached Telegram.
    """
    if timeout is None:timeout=UPLOAD_IDLE_TIMEOUT
    async with asyncio.timeout(timeout) as deadline:
        transferred=0
        async def report(current,total):
            nonlocal transferred
            if current>transferred:
                transferred=current
                deadline.reschedule(asyncio.get_running_loop().time()+timeout)
            if progress:
                result=progress(current,total)
                if inspect.isawaitable(result):await result
        yield report
