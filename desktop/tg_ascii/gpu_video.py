"""GPU video in group calls (1.5.5 complex feature, off by default; on in version B).

Group call cameras drawn by the GPU in their own window.

Each camera arrives as an I420 frame. Here it is uploaded as-is to a GPU
texture (SDL2 ``IYUV``); the GPU converts the colours, scales every tile to
the window (any size, also full screen) and composes the grid. Measured on
the user's Mac with 30 cameras: ~43 % less processor per frame than the Tk
path, and the window can be enlarged without extra cost.

- Renderer: Metal on macOS, Direct3D 11 on Windows (an accelerated one or
  nothing). If SDL2 or the GPU is unavailable, :meth:`GpuVideoWindow.open`
  returns None and the call keeps the normal grid inside the call window.
- Closing this window returns the cameras to the call window. Double-click or
  F toggles full screen. Controls (mute, camera, hang up) stay in the call
  window.
- Uses the main (Tk) thread, pumped from the call window's timer: no extra
  threads, nothing runs while there is no group video call.
"""
from . import APP_NAME
import ctypes
import math
import os
import sys

FEATURE = 'gpu_video'
ENVIRONMENT = 'TG_ASCII_GPU_VIDEO'   # read by the call helper (calls_group_worker)
_initialized = False


def configure(values):
    """Tell call helpers started from now on whether the GPU draws the grid."""
    features = (values or {}).get('advanced_features') or {}
    on = isinstance(features, dict) and features.get(FEATURE, False) is True and features.get('group_video_grid', False) is True
    if on:
        os.environ[ENVIRONMENT] = '1'
    else:
        os.environ.pop(ENVIRONMENT, None)
    return on


def gpu_budget(active):
    """(seconds between frames, max size) per camera when the GPU draws."""
    if active <= 1:
        return .05, None
    if active <= 4:
        return .05, (1280, 720)
    if active <= 9:
        return .066, (640, 360)
    if active <= 16:
        return .066, (480, 270)
    return .1, (320, 180)


def fit(frame_size, cell, rotation=0):
    """Destination (x, y, w, h) keeping the aspect ratio, centred in ``cell``."""
    width, height = frame_size
    if rotation in (90, 270):
        width, height = height, width
    cx, cy, cw, ch = cell
    if width <= 0 or height <= 0 or cw <= 0 or ch <= 0:
        return cx, cy, 0, 0
    scale = min(cw / width, ch / height)
    w, h = int(width * scale), int(height * scale)
    return cx + (cw - w) // 2, cy + (ch - h) // 2, w, h


def cells(count, width, height, gap=2):
    if count <= 0:
        return []
    columns = math.ceil(math.sqrt(count))
    rows = math.ceil(count / columns)
    cw, ch = width / columns, height / rows
    return [(int((i % columns) * cw) + gap, int((i // columns) * ch) + gap,
             max(0, int(cw) - 2 * gap), max(0, int(ch) - 2 * gap)) for i in range(count)]


class GpuVideoWindow:
    def __init__(self, sdl2, window, renderer, renderer_name):
        self.sdl2 = sdl2
        self.window = window
        self.renderer = renderer
        self.renderer_name = renderer_name
        self.textures = {}   # ssrc -> (texture, width, height)
        self.frames = {}     # ssrc -> last frame shown
        self.order = []
        self.closed = False
        self.fullscreen = False
        self.dirty = True

    @classmethod
    def open(cls, title=f'{APP_NAME} · Video'):
        global _initialized
        try:
            import sdl2
        except Exception:
            return None
        try:
            hint = b'metal' if sys.platform == 'darwin' else b'direct3d11' if sys.platform == 'win32' else b'opengl'
            sdl2.SDL_SetHint(sdl2.SDL_HINT_RENDER_DRIVER, hint)
            sdl2.SDL_SetHint(sdl2.SDL_HINT_RENDER_SCALE_QUALITY, b'linear')
            if not _initialized:
                if sdl2.SDL_InitSubSystem(sdl2.SDL_INIT_VIDEO) != 0:
                    return None
                _initialized = True
            window = sdl2.SDL_CreateWindow(title.encode('utf-8'), sdl2.SDL_WINDOWPOS_CENTERED, sdl2.SDL_WINDOWPOS_CENTERED,
                                           960, 540, sdl2.SDL_WINDOW_RESIZABLE | sdl2.SDL_WINDOW_ALLOW_HIGHDPI)
            if not window:
                return None
            renderer = sdl2.SDL_CreateRenderer(window, -1, sdl2.SDL_RENDERER_ACCELERATED | sdl2.SDL_RENDERER_PRESENTVSYNC)
            info = sdl2.SDL_RendererInfo()
            if not renderer or sdl2.SDL_GetRendererInfo(renderer, ctypes.byref(info)) != 0 \
                    or not info.flags & sdl2.SDL_RENDERER_ACCELERATED:
                if renderer:
                    sdl2.SDL_DestroyRenderer(renderer)
                sdl2.SDL_DestroyWindow(window)
                return None  # No GPU: the normal grid is lighter than software SDL.
            return cls(sdl2, window, renderer, info.name.decode('ascii', 'replace'))
        except Exception:
            return None

    def alive(self):
        return not self.closed

    def pump(self):
        """Window events: close, resize, full screen."""
        if self.closed:
            return False
        sdl2 = self.sdl2
        event = sdl2.SDL_Event()
        window_id = sdl2.SDL_GetWindowID(self.window)
        while sdl2.SDL_PollEvent(ctypes.byref(event)):
            kind = event.type
            if kind == sdl2.SDL_WINDOWEVENT and event.window.windowID == window_id:
                if event.window.event == sdl2.SDL_WINDOWEVENT_CLOSE:
                    self.close()
                    return False
                self.dirty = True
            elif kind == sdl2.SDL_MOUSEBUTTONDOWN and event.button.clicks == 2 and event.button.windowID == window_id:
                self.toggle_fullscreen()
            elif kind == sdl2.SDL_KEYDOWN and event.key.windowID == window_id and event.key.keysym.sym in (sdl2.SDLK_f, sdl2.SDLK_ESCAPE):
                if event.key.keysym.sym == sdl2.SDLK_f or self.fullscreen:
                    self.toggle_fullscreen()
        return True

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        self.sdl2.SDL_SetWindowFullscreen(self.window, self.sdl2.SDL_WINDOW_FULLSCREEN_DESKTOP if self.fullscreen else 0)
        self.dirty = True

    def _texture(self, ssrc, width, height):
        sdl2 = self.sdl2
        current = self.textures.get(ssrc)
        if current is not None and current[1:] == (width, height):
            return current[0]
        if current is not None:
            sdl2.SDL_DestroyTexture(current[0])
        texture = sdl2.SDL_CreateTexture(self.renderer, sdl2.SDL_PIXELFORMAT_IYUV, sdl2.SDL_TEXTUREACCESS_STREAMING, width, height)
        if not texture:
            raise RuntimeError('SDL texture failed')
        self.textures[ssrc] = (texture, width, height)
        return texture

    def upload(self, ssrc, frame):
        """I420 bytes straight into the texture (no copy, no conversion)."""
        width, height, data = int(frame['width']), int(frame['height']), frame['data']
        chroma_width, chroma_height = (width + 1) // 2, (height + 1) // 2
        if not (0 < width <= 4096 and 0 < height <= 4096) or len(data) != width * height + 2 * chroma_width * chroma_height:
            return False
        texture = self._texture(ssrc, width, height)
        pointer = ctypes.POINTER(ctypes.c_ubyte)
        holder = ctypes.c_char_p(bytes(data))
        base = ctypes.cast(holder, ctypes.c_void_p).value
        y = ctypes.cast(base, pointer)
        u = ctypes.cast(base + width * height, pointer)
        v = ctypes.cast(base + width * height + chroma_width * chroma_height, pointer)
        self.sdl2.SDL_UpdateYUVTexture(texture, None, y, width, u, chroma_width, v, chroma_width)
        return True

    def show(self, active, frames):
        """Draw the grid: ``active`` = ordered camera ids, ``frames`` = new frames."""
        if not self.pump():
            return False
        sdl2 = self.sdl2
        for ssrc in [ssrc for ssrc in self.textures if ssrc not in active]:
            sdl2.SDL_DestroyTexture(self.textures.pop(ssrc)[0])
            self.frames.pop(ssrc, None)
        changed = self.dirty or list(active) != self.order
        for ssrc, frame in (frames or {}).items():
            if ssrc in active and self.upload(ssrc, frame):
                self.frames[ssrc] = frame
                changed = True
        self.order = list(active)
        if not changed:
            return True
        self.dirty = False
        width, height = ctypes.c_int(), ctypes.c_int()
        sdl2.SDL_GetRendererOutputSize(self.renderer, ctypes.byref(width), ctypes.byref(height))
        sdl2.SDL_SetRenderDrawColor(self.renderer, 0, 0, 0, 255)
        sdl2.SDL_RenderClear(self.renderer)
        for ssrc, cell in zip(self.order, cells(len(self.order), width.value, height.value)):
            frame = self.frames.get(ssrc)
            entry = self.textures.get(ssrc)
            if frame is None or entry is None:
                continue
            rotation = int(frame.get('rotation', 0) or 0) % 360
            x, y, w, h = fit((entry[1], entry[2]), cell, rotation)
            if rotation in (90, 270):
                # RenderCopyEx rotates around the centre of the unrotated rect.
                rect = sdl2.SDL_Rect(x + (w - h) // 2, y + (h - w) // 2, h, w)
            else:
                rect = sdl2.SDL_Rect(x, y, w, h)
            sdl2.SDL_RenderCopyEx(self.renderer, entry[0], None, rect, float(rotation), None, sdl2.SDL_FLIP_NONE)
        sdl2.SDL_RenderPresent(self.renderer)
        return True

    def close(self):
        if self.closed:
            return
        self.closed = True
        sdl2 = self.sdl2
        for texture, _, _ in self.textures.values():
            sdl2.SDL_DestroyTexture(texture)
        self.textures.clear()
        self.frames.clear()
        if self.renderer:
            sdl2.SDL_DestroyRenderer(self.renderer)
        if self.window:
            sdl2.SDL_DestroyWindow(self.window)
        self.renderer = self.window = None
