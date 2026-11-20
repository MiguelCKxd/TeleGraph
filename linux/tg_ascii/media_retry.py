"""Bounded negative preview cache; transient network failures are never permanent."""
from collections import OrderedDict
import time

RETRY_DELAYS=(15_100,30_000,60_000,120_000)


def failed_recently(app,key,delay=15):
    failed=getattr(app,'preview_failed',set())
    if key not in failed:return False
    failures=getattr(app,'_preview_failure_times',None)
    when=failures.get(key) if failures is not None else None
    if when is None or time.monotonic()-when>=delay:
        failed.discard(key)
        if failures is not None:failures.pop(key,None)
        return False
    return True


def remember_failure(app,key):
    failures=getattr(app,'_preview_failure_times',None)
    if failures is None:failures=app._preview_failure_times=OrderedDict()
    failures[key]=time.monotonic();failures.move_to_end(key)
    app.preview_failed.add(key)
    while len(failures)>1024:
        old,_=failures.popitem(last=False);app.preview_failed.discard(old)


def clear_failure(app,key):
    app.preview_failed.discard(key)
    getattr(app,'_preview_failure_times',{}).pop(key,None)


def retry_visible_art(app,key,operation,listeners):
    """One recovery attempt for still-current views, with no persistent polling."""
    import tkinter as tk
    if getattr(app,'closing',False) or getattr(app,'closed',False):return
    def live(listener):
        try:return bool(getattr(listener,'media_valid',lambda:False)())
        except tk.TclError:return False
    listeners=[listener for listener in listeners if live(listener)]
    if not listeners:return
    retries=getattr(app,'_art_retries',None)
    if retries is None:retries=app._art_retries=OrderedDict()
    if key in retries:
        state=retries[key]
        state['listeners']=[listener for listener in state['listeners'] if live(listener)]+listeners
        state['listeners']=state['listeners'][-512:]
        return
    used=getattr(app,'_art_retry_used',None)
    if used is None:used=app._art_retry_used=OrderedDict()
    # 1.4.1: a few spaced retries (15 s, 30 s, 60 s, 120 s) instead of one.
    # A single failed retry used to leave an emoji/sticker blank for good.
    attempt=used.get(key) or 0
    if attempt>=len(RETRY_DELAYS):return
    used[key]=attempt+1;used.move_to_end(key)
    while len(used)>1024:used.popitem(last=False)
    state={'listeners':listeners[-512:],'operation':operation}
    def retry():
        retries.pop(key,None)
        if getattr(app,'closing',False) or getattr(app,'closed',False):return
        current=[listener for listener in state['listeners'] if live(listener)]
        if not current:return
        clear_failure(app,key)
        for listener in current:app.fetch_art(key,operation,listener,valid=listener.media_valid)
    state['retry']=retry
    state['timer']=app.root.after(RETRY_DELAYS[attempt],retry)
    retries[key]=state
    while len(retries)>128:
        _,old=retries.popitem(last=False)
        try:app.root.after_cancel(old['timer'])
        except tk.TclError:pass


def retry_now(app):
    """Connection is back: retry every still-visible blank emoji/sticker now."""
    import tkinter as tk
    for index,(key,state) in enumerate(list(getattr(app,'_art_retries',{}).items())):
        try:app.root.after_cancel(state['timer'])
        except (tk.TclError,KeyError):pass
        try:state['timer']=app.root.after(200+min(index,40)*50,state['retry'])
        except (tk.TclError,KeyError):pass
    # Keys whose retries were used up get a fresh budget after a reconnect.
    used=getattr(app,'_art_retry_used',None)
    if used:used.clear()


def clear_art_retry(app,key):
    """A successful explicit load supersedes pending automatic recovery."""
    import tkinter as tk
    getattr(app,'_art_retry_used',{}).pop(key,None)
    state=getattr(app,'_art_retries',{}).pop(key,None)
    if state:
        try:app.root.after_cancel(state['timer'])
        except tk.TclError:pass


def grid_failed_recently(grid,ident):
    if ident not in grid.failed:return False
    when,count=getattr(grid,'_failed_times',{}).get(ident,(0,0))
    if time.monotonic()-when<15:return True
    grid.failed.discard(ident)
    return False


def remember_grid_failure(grid,ident):
    failures=getattr(grid,'_failed_times',None)
    if failures is None:failures=grid._failed_times=OrderedDict()
    count=failures.get(ident,(0,0))[1]+1
    failures[ident]=(time.monotonic(),count);failures.move_to_end(ident)
    grid.failed.add(ident)
    while len(failures)>512:
        old,_=failures.popitem(last=False);grid.failed.discard(old)
    # One delayed retry while the pack is visible. Persistent failures never
    # create an endless background timer; returning to a tile can retry later.
    if count==1 and getattr(grid,'_retry_job',None) is None and hasattr(grid,'after'):
        def retry():
            grid._retry_job=None
            if grid.winfo_exists() and grid.winfo_viewable():grid.repaint.request()
        grid._retry_job=grid.after(15_100,retry)
