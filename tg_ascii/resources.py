"""System resource profiles (1.5, Settings › Customization › Resources).

Each resource is ``limited``, ``normal`` (exactly the pre-1.5 values) or
``unlimited``. What each one really changes:

CPU      process priority (Windows: below normal / normal / above normal;
         macOS: "limited" lowers the nice value — raising it back needs a
         restart, the OS does not allow a process to raise its own priority)
         and the size of the worker thread pool used for image/animation
         decoding (applied at start).
Memory   in-memory caches: previews and avatars, decoded animation frames,
         the per-chat message cache and the on-disk media cache budget.
Graphics animated emoji/stickers playing at once, their frame budget and
         frame rate (limited plays at 15 fps). Tk draws with the OS 2-D
         compositor: there is no direct GPU switch, so this setting controls
         the graphics *workload* the app gives the GPU/compositor.
Network  parallel downloads, avatar and emoji fetches.

Values are plain module globals so the asyncio worker can read them without
touching Tk. ``configure`` is called at start and after every settings save.
"""
import os
import sys

LEVELS = ('limited', 'normal', 'unlimited')
_profile = {'cpu': 'normal', 'ram': 'normal', 'gpu': 'normal', 'network': 'normal'}
_applied_priority = None


def level(kind):
    return _profile.get(kind, 'normal')


def configure(values):
    """Read the four choices from preferences and apply what is immediate."""
    global _frame_limit
    limit = str((values or {}).get('frame_limit', 'auto'))
    _frame_limit = limit if limit in FRAME_LIMITS else 'auto'
    for kind in _profile:
        value = (values or {}).get(f'resource_{kind}', 'normal')
        _profile[kind] = value if value in LEVELS else 'normal'
    apply_priority()
    return dict(_profile)


def scaled(kind, normal, limited, unlimited):
    return {'limited': limited, 'unlimited': unlimited}.get(level(kind), normal)


# -- network ------------------------------------------------------------------
def network_slots(normal):
    return scaled('network', normal, max(1, normal // 2), normal * 2)


# -- memory -------------------------------------------------------------------
def cache_entries(normal):
    return scaled('ram', normal, max(64, normal // 2), normal * 4)


def cache_bytes(normal):
    return scaled('ram', normal, max(4 * 1024 * 1024, normal // 2), normal * 4)


def history_chats(normal=40):
    return scaled('ram', normal, max(8, normal // 4), normal * 5)


def disk_cache(max_bytes, target_bytes):
    factor = scaled('ram', 1.0, 0.5, 3.0)
    return int(max_bytes * factor), int(target_bytes * factor)


# -- graphics -----------------------------------------------------------------
def animated_entries(normal=32):
    return scaled('gpu', normal, max(4, normal // 4), normal * 3)


def animation_budget(normal):
    return scaled('gpu', normal, max(4 * 1024 * 1024, normal // 4), normal * 3)


# 1.5.0.1: Settings › Customization › Frame rate limit ('auto' = as before).
FRAME_LIMITS = ('auto', '15', '24', '30', '60', '120', 'unlimited')
_frame_limit = 'auto'


def frame_limit():
    """None (automatic), 0 (unlimited) or frames per second."""
    if _frame_limit == 'auto':
        return None
    if _frame_limit == 'unlimited':
        return 0
    return int(_frame_limit)


def decode_fps():
    """Frames per second animations are prepared at (30 by default)."""
    limit = frame_limit()
    if limit is None:
        return 15 if level('gpu') == 'limited' else 30
    return 120 if limit == 0 else limit


def min_frame_ms():
    return max(1, round(1000 / decode_fps()))


def max_frames(normal):
    """More frames for smoother rates, so long animations are not cut short."""
    return normal * 2 if decode_fps() > 30 else normal


def frame_interval(normal_ms=33):
    """Minimum time between animation frames (33 ms ≈ 30 fps)."""
    limit = frame_limit()
    if limit is None:
        return scaled('gpu', normal_ms, max(normal_ms, 66), normal_ms)
    return 4 if limit == 0 else max(4, round(1000 / limit))


def frame_tag():
    """Suffix for rendered animation files; '' keeps pre-1.5.0.1 cache names."""
    fps = decode_fps()
    return '' if fps == 30 else f'-{fps}fps'


# -- CPU ----------------------------------------------------------------------
def worker_threads():
    """Default executor size for the asyncio worker, or None for Python's default."""
    cores = os.cpu_count() or 4
    return scaled('cpu', None, 2, min(48, cores * 2 + 4))


def apply_priority():
    """Process priority for the CPU level (best effort, never raises)."""
    global _applied_priority
    wanted = level('cpu')
    if wanted == _applied_priority:
        return
    try:
        if sys.platform == 'win32':
            import ctypes
            classes = {'limited': 0x00004000, 'normal': 0x00000020, 'unlimited': 0x00008000}
            kernel = ctypes.WinDLL('kernel32.dll', winmode=0x800)
            kernel.GetCurrentProcess.restype = ctypes.c_void_p
            kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            if _applied_priority is None and wanted == 'normal':
                _applied_priority = wanted
                return  # Leave the inherited class untouched by default.
            kernel.SetPriorityClass(kernel.GetCurrentProcess(), classes[wanted])
        elif hasattr(os, 'setpriority'):
            if wanted == 'limited':
                current = os.getpriority(os.PRIO_PROCESS, 0)
                if current < 10:
                    os.setpriority(os.PRIO_PROCESS, 0, 10)
            # Normal/unlimited cannot raise priority without privileges.
        _applied_priority = wanted
    except Exception:
        _applied_priority = wanted


def summary():
    return dict(_profile)
