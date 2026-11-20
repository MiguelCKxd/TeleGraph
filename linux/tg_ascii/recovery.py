"""Bounded per-session recovery. Never replay a user operation or revoke a session."""
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from contextlib import closing
from pathlib import Path
import threading
import time
import traceback
from telethon import functions,errors

PROBE_TIMEOUT=12
CONNECT_TIMEOUT=30
POLL_INTERVAL=5
HEARTBEAT_INTERVAL=30
RECENT_PROBE_INTERVAL=5
AUTH_ERRORS=(errors.AuthKeyUnregisteredError,errors.AuthKeyDuplicatedError,errors.SessionRevokedError,errors.SessionExpiredError,errors.UserDeactivatedError,errors.UserDeactivatedBanError)
_diagnostics_lock = threading.Lock()


# Identical failures arriving in a burst (e.g. 957 FLOOD_WAITs in one second in
# a real 1.3.1 log) were each written with open/write/close/chmod on the asyncio
# thread. Keep the first few of each burst and summarise the rest.
BURST_LIMIT=5
BURST_WINDOW=10.0
_bursts={}


def _burst_admit(key,now):
    """Return (write, suppressed_before). Called with _diagnostics_lock held."""
    state=_bursts.get(key)
    if state is None or now-state[0]>=BURST_WINDOW:
        suppressed=state[2] if state is not None else 0
        _bursts.pop(key,None);_bursts[key]=[now,1,0]
        while len(_bursts)>256:_bursts.pop(next(iter(_bursts)))
        return True,suppressed
    state[1]+=1
    if state[1]<=BURST_LIMIT:return True,0
    state[2]+=1
    return False,0


def record_failure(root,component,error):
    """Record types and code locations, never exception text, request bodies or account identifiers."""
    try:
        path=Path(root)/'diagnostics.log'
        locations=' > '.join(f'{Path(frame.filename).name}:{frame.lineno}:{frame.name}' for frame in traceback.extract_tb(error.__traceback__)[-8:])
        # Windows cannot remove a log while a FileHandler keeps it open.
        # Use a short-lived handler, with one process-wide lock to serialize
        # writes/rotation from Tk and the worker. Do not retain per-folder loggers.
        with _diagnostics_lock:
            write,suppressed=_burst_admit((str(root),component,type(error).__name__,locations),time.monotonic())
            if not write:return
            if suppressed:
                record=logging.LogRecord('tg_ascii.diagnostics',logging.WARNING,__file__,0,
                                         '%s %s %s (+%d repeated)',(component,type(error).__name__,locations,suppressed),None)
            else:
                record=logging.LogRecord('tg_ascii.diagnostics',logging.WARNING,__file__,0,
                                         '%s %s %s',(component,type(error).__name__,locations),None)
            path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            with closing(RotatingFileHandler(path,maxBytes=256*1024,backupCount=1,
                                            encoding='utf-8',delay=True)) as handler:
                handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
                handler.handle(record)
            try:path.chmod(0o600)
            except OSError:pass
    except (OSError,ValueError):pass


class Recovery:
    def __init__(self,service):
        self.service=service;self.lock=asyncio.Lock();self.task=None;self.closed=False;self.auth_required=False
        self.state='online';self.last_check=0;self.failures=0;self.operations=set();self.retry_at=0;self.wait_error=None;self.last_reconnect=0;self.restart_streak=0
        self.attempt_generation=0;self.last_attempt_error=None;self.last_attempt_reset=False
    def emit(self,state):
        if self.state==state:return
        self.state=state
        if self.service.on_change:self.service.on_change('connection',state)
        pending=getattr(self.service,'pending',None)
        if state=='online' and pending is not None and pending.records:
            # 1.5.3: actions made offline go out as soon as Telegram answers.
            try:
                task=asyncio.get_running_loop().create_task(pending.flush())
                self.operations.add(task);task.add_done_callback(self.operations.discard)
            except RuntimeError:pass
    def start(self):
        if self.task is None:self.task=asyncio.create_task(self.watch())
    async def stop(self):
        self.closed=True
        tasks=self.operations | ({self.task} if self.task is not None else set())
        tasks.discard(asyncio.current_task())
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True);self.task=None
    async def probe(self):
        await asyncio.wait_for(self.service.client(functions.updates.GetStateRequest()),PROBE_TIMEOUT)
        self.last_check=asyncio.get_running_loop().time()
    async def ensure(self,force=False):
        task=asyncio.current_task();self.operations.add(task)
        generation=self.attempt_generation
        try:return await self._ensure(force,generation)
        finally:self.operations.discard(task)
    async def _ensure(self,force=False,generation=None):
        if generation is None:generation=self.attempt_generation
        async with self.lock:
            if self.closed:raise ConnectionError('Service closed')
            if self.auth_required:raise errors.AuthKeyUnregisteredError(None)
            if asyncio.get_running_loop().time()<self.retry_at:raise self.wait_error
            # Callers already waiting behind this attempt share its outcome,
            # including failure. A concurrent forced reset must not disconnect
            # the freshly recovered transport again for every queued caller.
            if generation!=self.attempt_generation and (not force or self.last_attempt_reset):
                if self.last_attempt_error is not None:raise self.last_attempt_error
                return
            client=self.service.client
            completed=False
            self.last_attempt_error=None;self.last_attempt_reset=False
            try:
                if client.is_connected() and not force:
                    # Several refreshes/account switches may queue behind one probe.
                    # Reuse that successful check instead of adding a round trip each.
                    if self.state=='online' and self.last_check and asyncio.get_running_loop().time()-self.last_check<RECENT_PROBE_INTERVAL:
                        return
                    try:
                        await self.probe();self.failures=0
                        if self.last_check-self.last_reconnect>=30:self.restart_streak=0
                        self.emit('online');completed=True;return
                    except (ConnectionError,OSError,asyncio.TimeoutError):pass
                now=asyncio.get_running_loop().time()
                self.restart_streak=self.restart_streak+1 if now-self.last_reconnect<30 else 1
                self.last_reconnect=now
                self.emit('reconnecting')
                self.last_attempt_reset=True
                previous=getattr(client,'_updates_error',None)
                if isinstance(previous,AUTH_ERRORS):raise previous
                if isinstance(previous,BaseException):record_failure(self.service.root,'updates',previous)
                # Await full teardown before reconnecting the same client. This keeps
                # exactly one set of event handlers and the existing backend/caches.
                await asyncio.wait_for(client.disconnect(),10)
                await asyncio.wait_for(client.connect(),CONNECT_TIMEOUT)
                await self.probe()
                await asyncio.wait_for(client.catch_up(),10)
                refresh_profile = getattr(self.service, 'refresh_profile', None)
                if refresh_profile is not None:
                    try:
                        await refresh_profile()
                    except (OSError, TimeoutError) as exc:
                        # An optional profile refresh must not label a working
                        # transport as offline; its cache remains invalidated.
                        record_failure(self.service.root, 'account_profile', exc)
                self.failures=0;self.emit('online');completed=True
            except errors.FloodWaitError as exc:
                self.last_attempt_error=exc;completed=True
                self.wait_error=exc;self.retry_at=asyncio.get_running_loop().time()+max(1,exc.seconds)
                self.emit('offline');record_failure(self.service.root,'rate_limit',exc);raise
            except AUTH_ERRORS as exc:
                self.last_attempt_error=exc;completed=True
                self.auth_required=True;self.emit('auth');record_failure(self.service.root,'authorization',exc);raise
            except Exception as exc:
                self.last_attempt_error=exc;completed=True
                self.failures+=1;self.emit('offline');record_failure(self.service.root,'connection',exc);raise
            finally:
                if completed:self.attempt_generation+=1
    async def watch(self):
        while not self.closed and not self.auth_required:
            attempts=max(self.failures,self.restart_streak)
            await asyncio.sleep(max(POLL_INTERVAL,min(60,2**min(attempts,6))) if attempts else POLL_INTERVAL)
            if self.closed:return
            client=self.service.client
            if client is None:return
            if client.is_connected() and asyncio.get_running_loop().time()-self.last_check<HEARTBEAT_INTERVAL:continue
            try:await self.ensure()
            except asyncio.CancelledError:raise
            except errors.FloodWaitError as exc:
                await asyncio.sleep(max(1,exc.seconds))
            except Exception:pass  # State/diagnostics already recorded; retry with backoff.
