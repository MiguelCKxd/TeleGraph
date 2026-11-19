"""Heavy image work in separate processes, one per spare core (1.5.5).

Converting stickers and custom emoji (TGS/WebM → animated WebP) and
unpacking animation frames run in a ``spawn`` process pool, so they use
other cores and never share the interface process's Python lock. If the pool
cannot start or breaks, everything falls back to the threads used before.

Complex feature › "Decode in separate processes", off by default (the Beta
line turns it on). The pool starts on first use and its processes end with the app.
"""
import asyncio
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
import multiprocessing
import os
import pickle
import sys
import threading

FEATURE = 'process_decoding'
_enabled = False
_pool = None
_broken = False
_stopping = False
_lock = threading.Lock()


def configure(values):
    global _enabled, _stopping
    _stopping = False
    features = (values or {}).get('advanced_features') or {}
    _enabled = isinstance(features, dict) and features.get(FEATURE, False) is True


def workers():
    return max(1, min(6, (os.cpu_count() or 2) - 1))


def active():
    return _enabled and not _broken


def parallelism(default=2):
    """How many images the interface may prepare at once."""
    return workers() if active() else default


def _watch_mac_parent():
    # Cocoa can terminate the GUI outside Tk's shutdown path. A frozen worker
    # then keeps its own Dock presence until it exits, even while idle.
    parent = multiprocessing.parent_process()

    def wait_for_parent():
        while os.getppid() == parent.pid:
            parent.join(timeout=2)
            if not parent.is_alive():
                break
        os._exit(0)  # Only this disposable decoder process.

    threading.Thread(target=wait_for_parent, name='decoder-parent', daemon=True).start()


def _get_pool():
    global _pool
    with _lock:
        if _stopping:
            raise asyncio.CancelledError
        if _pool is None:
            _pool = ProcessPoolExecutor(
                max_workers=workers(), mp_context=multiprocessing.get_context('spawn'),
                initializer=_watch_mac_parent if sys.platform == 'darwin' else None,
            )
        return _pool


async def run(function, *args):
    """``function(*args)`` in a process (or a thread when unavailable)."""
    global _broken
    if not active():
        return await asyncio.to_thread(function, *args)
    try:
        return await asyncio.get_running_loop().run_in_executor(_get_pool(), function, *args)
    except (pickle.PicklingError, TypeError, AttributeError):
        # Something that cannot cross to another process: do this one in a thread.
        return await asyncio.to_thread(function, *args)
    except (BrokenProcessPool, OSError, RuntimeError) as error:
        if _stopping:
            raise asyncio.CancelledError from error
        _broken = True
        try:
            from .preferences import data_root
            from .recovery import record_failure
            record_failure(data_root(), 'decode_pool', error)
        except Exception:
            pass
        return await asyncio.to_thread(function, *args)


def _decode(path, size, animated):
    """Runs in the child: frames as raw RGBA bytes (no PIL objects cross)."""
    from .animation import decode_frames
    frames, durations = decode_frames(path, size, animated=animated)
    try:
        return [(frame.mode, frame.size, frame.tobytes()) for frame in frames], durations
    finally:
        for frame in frames:
            frame.close()


async def decode_frames(path, size, animated=True):
    from PIL import Image
    raw, durations = await run(_decode, str(path), tuple(size), bool(animated))
    return [Image.frombytes(mode, frame_size, data) for mode, frame_size, data in raw], durations


def shutdown():
    global _pool, _stopping
    with _lock:
        _stopping = True
        pool, _pool = _pool, None
    if pool is None:
        return
    if hasattr(pool, 'kill_workers'):  # Python 3.14+
        pool.kill_workers()
        return
    # Python 3.11–3.13 have no public API to interrupt a running decoder.
    # Take just this executor's workers while submissions are excluded.
    with pool._shutdown_lock:
        for process in (pool._processes or {}).copy().values():
            try:
                process.kill()
            except (ProcessLookupError, ValueError):
                pass  # Already exited or reaped by the executor.
    pool.shutdown(wait=True, cancel_futures=True)
