"""Single-use Android MediaProjection consent for a live call."""
import asyncio
import json

# The Android AAR parses the input as device metadata before passing the id
# to WebRTC's ScreenCapturerAndroid.
SCREEN_DEVICE = {'id': json.dumps({'id': 'screen'}), 'name': 'Screen'}
_request_projection = None
_end_projection = None


def screen_devices():
    return [dict(SCREEN_DEVICE)] if _request_projection else []


class ScreenShare:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._projection_lock = asyncio.Lock()
        self._projection_token = None
        self._projection_lease = None

    async def share_screen(self, enabled, *, token):
        from tg_ascii.i18n import tr

        async with self._projection_lock:
            call = self._check(token=token)
            if call.state != 'active' or getattr(self, 'view_only', False) or _request_projection is None:
                raise ValueError(tr('Selected device is unavailable'))
            if call.screen == enabled:
                return
            if not enabled:
                try:
                    await self.set_screen('', token=token)
                finally:
                    self._release_projection(token)
                return
            self._projection_token = token
            lease = self._projection_lease = object()
            try:
                approved = await _request_projection(
                    lambda: self._projection_lease is lease,
                    lambda: self._schedule(self._projection_stopped(token, lease)),
                )
                if not approved:
                    return
                if self._projection_token != token:
                    return
                await self.set_screen(SCREEN_DEVICE['id'], token=token)
            finally:
                if self._call is not call or not call.screen:
                    self._release_projection(token)

    async def _projection_stopped(self, token, lease):
        async with self._projection_lock:
            if self._projection_lease is not lease:
                return
            try:
                await self.set_screen('', token=token)
            finally:
                self._release_projection(token)

    def _release_projection(self, token):
        if token != self._projection_token:
            return
        self._projection_token = self._projection_lease = None
        _end_projection()

    async def _finish(self, call, error='', *, discard=False):
        try:
            await super()._finish(call, error, discard=discard)
        finally:
            self._release_projection(call.token)


def install(app, activity):
    from java import dynamic_proxy, jclass
    from tg_ascii.i18n import tr

    service = jclass('org.tgas.calls.ScreenShareService')
    projection = jclass('android.media.projection.MediaProjectionManager')
    manager = activity.getSystemService(projection)
    context = activity.getApplicationContext()

    async def request(still_current, on_stopped):
        loop = asyncio.get_running_loop()
        answer = loop.create_future()

        def deliver(value=None, error=None):
            if answer.done():
                return
            if error is None:
                answer.set_result(value)
            else:
                answer.set_exception(error)

        class OnStopped(dynamic_proxy(jclass('java.lang.Runnable'))):
            def run(self):
                loop.call_soon_threadsafe(on_stopped)

        def complete(code, data):
            future = None
            if code == -1 and data is not None and not answer.done() and still_current() and not app.core.locked:
                try:
                    future = service.begin(context, data, tr('Share screen'), OnStopped())
                except Exception as error:
                    loop.call_soon_threadsafe(deliver, None, error)
                    return
            loop.call_soon_threadsafe(deliver, future)

        def launch():
            try:
                app._impl.start_activity(manager.createScreenCaptureIntent(), on_complete=complete)
            except Exception as error:
                loop.call_soon_threadsafe(deliver, None, error)

        prior = app.core.external_until
        app.core.expect_external(95)
        deadline = app.core.external_until
        app.loop.call_soon_threadsafe(launch)
        try:
            future = await asyncio.wait_for(answer, 90)
        finally:
            if app.core.external_until == deadline:
                app.core.external_until = prior
        if future is None:
            return False
        unit = jclass('java.util.concurrent.TimeUnit')
        return bool(await asyncio.to_thread(future.get, 6, unit.SECONDS)) and not app.core.locked

    global _request_projection, _end_projection
    _request_projection = request
    _end_projection = lambda: service.end(context)
