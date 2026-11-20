"""One account worker per process, shared by the window and Android push jobs."""
from threading import Lock

_lock = Lock()
_running = None


def get_core(root, system, locale, background_notify=None):
    global _running
    if system == 'iOS':
        # macOS exposes the Apache MIME database to stat(), but the iOS
        # sandbox disallows reading it. Use Python's bundled MIME mappings.
        import mimetypes
        mimetypes.knownfiles = []
    from .core import Core
    with _lock:
        if _running is None or not _running.thread.is_alive():
            core = Core(root, system, locale)
            if background_notify is not None:
                core.in_background = True
                core.native_notify = background_notify
            core.start()
            _running = core
        return _running


def _android_root(context):
    from pathlib import Path
    return Path(str(context.getFilesDir().getAbsolutePath())) / 'data' / 'tg-ascii'


def _android_core(context, root):
    from java.util import Locale
    from .notify_native import android_message_poster

    return get_core(root, 'Android', str(Locale.getDefault().toLanguageTag()), android_message_poster(context))


def android_push(context, payload):
    """Called on a WorkManager thread. No Activity or WebView is required."""
    core = _android_core(context, _android_root(context))
    import asyncio
    import json
    hint = json.loads(str(payload))
    from tg_ascii.push_notifications import parse_hint
    # Jobs enqueued by older versions may still carry a maintenance route.
    kind = hint.get('loc_key', '')
    if not isinstance(kind, str) or kind in ('SESSION_REVOKE', 'MESSAGE_MUTED', 'DC_UPDATE') or kind.startswith(
            ('READ_', 'DELETE_', 'PHONE_CALL')):
        return 1
    route = parse_hint(str(payload))
    if route is not None and route.peer is not None and route.message_id is not None:
        return core.receive_push_payload(str(payload)).result(timeout=30)
    if 'badge_sent_at' in hint and not hint.get('loc_key'):
        account = hint.get('user_id')
        if 'user_id' in hint and (type(account) is not int or account <= 0):
            return 1
        job = asyncio.run_coroutine_threadsafe(core.sync_android_badge(hint['badge_sent_at'], user_id=account), core.loop)
        try:
            return job.result(timeout=90)
        except TimeoutError:
            job.cancel()
            return 2
    return 1


def android_refresh_token(context, token):
    import asyncio
    root = _android_root(context)
    if not (root / 'account.session').is_file() and not any(root.glob('accounts/*/account.session')):
        return 1
    core = _android_core(context, root)
    job = asyncio.run_coroutine_threadsafe(core.refresh_android_push_token(str(token)), core.loop)
    try:
        return job.result(timeout=240)
    except TimeoutError:
        job.cancel()
        return 2
