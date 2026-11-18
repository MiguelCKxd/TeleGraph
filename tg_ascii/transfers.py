"""Transfer deadlines measure inactivity, not the total size of an upload."""
import asyncio
from asyncio import current_task
from contextlib import asynccontextmanager
from functools import wraps
import inspect

UPLOAD_IDLE_TIMEOUT=120


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
