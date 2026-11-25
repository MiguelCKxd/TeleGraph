"""Deliver a live call to the platform PiP controller without a foreground WebView."""
import asyncio
from time import monotonic


class CallPictureInPicture:
    def __init__(self, core, ui, window_factory):
        self.core = core
        self.ui = ui
        self.window_factory = window_factory
        self.token = None
        self.task = self.ready = None
        self.closing = False

    async def on_ui(self, work):
        loop = asyncio.get_running_loop()
        result = loop.create_future()

        def finish(value, error):
            if not result.done():
                if error is None:
                    result.set_result(value)
                else:
                    result.set_exception(error)

        def run():
            try:
                value = work()
            except Exception as exc:
                loop.call_soon_threadsafe(finish, None, exc)
            else:
                loop.call_soon_threadsafe(finish, value, None)

        self.ui(run)
        return await result

    def matches(self, token):
        return bool(token and self.token == token and not self.closing)

    def close(self):
        self.closing = True

    async def open(self, token, group=False):
        manager = self.core.group_call_manager if group else self.core.call_manager
        if self.core.locked or not token or not manager:
            return False
        snapshot = manager.snapshot
        if snapshot.get('token') != token or snapshot.get('state') != 'active':
            return False
        if self.task:
            return self.matches(token) and await asyncio.shield(self.ready)
        self.closing = False
        self.ready = asyncio.get_running_loop().create_future()
        self.token = token
        self.task = asyncio.create_task(self._show(manager, token, group, self.ready))
        return await asyncio.shield(self.ready)

    async def _show(self, manager, token, group, ready):
        from .android_calls import frame_jpeg_bytes
        account = self.core.account
        window = None
        def current():
            active = self.core.group_call_manager if group else self.core.call_manager
            return (not self.closing and not self.core.locked and self.core.account == account and active is manager
                    and manager.snapshot.get('token') == token and manager.snapshot.get('state') == 'active')
        try:
            window = self.window_factory(token)
            if not await self.on_ui(lambda: current() and window.open()):
                return
            deadline = monotonic() + 5
            seen_remote = 0
            shown = 0
            while current():
                state = await self.on_ui(window.status)
                if state == 0 or (state != 2 and monotonic() > deadline):
                    break
                if state == 2 and not ready.done():
                    ready.set_result(True)
                # In grid view the shared manager also keeps the latest remote
                # camera. Let the native window own the frame consumer until it closes.
                frame = manager.take_frame()
                local = manager.take_local_frame()
                now = monotonic()
                if frame:
                    seen_remote = now
                elif now - seen_remote > 1.2 and manager.snapshot.get('video'):
                    frame = local
                if frame and frame.get('token') == token:
                    jpeg = await asyncio.to_thread(frame_jpeg_bytes, frame)
                    await self.on_ui(lambda: current() and window.frame(jpeg))
                    shown = now
                elif shown and now - shown > 2:
                    await self.on_ui(window.clear)
                    shown = 0
                await asyncio.sleep(.12)
        except Exception:
            import logging
            logging.getLogger(__name__).warning('System call picture in picture stopped', exc_info=True)
        finally:
            try:
                if window is not None:
                    await self.on_ui(window.close)
            except Exception:
                pass
            finally:
                if not ready.done():
                    ready.set_result(False)
                self.token = self.task = self.ready = None


def install_android(app, activity):
    from java import jclass
    try:
        bridge = jclass('org.tgas.calls.CallPipActivity')
        supported = bridge.supported(activity)
    except Exception:
        # A development shell can contain the voice engine without the PiP activity.
        return
    if not supported:
        return

    class Window:
        def __init__(self, token):
            self.token = token

        def open(self):
            return bridge.open(activity, self.token)

        def status(self):
            return bridge.status(self.token)

        def frame(self, jpeg):
            bridge.frame(self.token, jpeg)

        def clear(self):
            bridge.frame(self.token, None)

        def close(self):
            bridge.close(self.token)

    app.core.call_pip = CallPictureInPicture(app.core, app.loop.call_soon_threadsafe, Window)


def install_ios(app):
    import ctypes
    from rubicon.objc import ObjCClass
    try:
        controller = ObjCClass('TGCallPiP')
    except NameError:
        return
    if not controller.supported():
        return

    class Window:
        def __init__(self, token):
            self.controller = None

        def open(self):
            self.controller = controller.alloc().init()
            return self.controller.openFrom_(app.main_window._impl.native.rootViewController.view)

        def status(self):
            return int(self.controller.state)

        def frame(self, jpeg):
            data = ctypes.c_char_p(jpeg)
            self.controller.showBytes_length_(ctypes.cast(data, ctypes.c_void_p).value, len(jpeg))

        def clear(self):
            self.controller.clear()

        def close(self):
            if self.controller is not None:
                self.controller.close()

    app.core.call_pip = CallPictureInPicture(app.core, app.on_main_thread, Window)
