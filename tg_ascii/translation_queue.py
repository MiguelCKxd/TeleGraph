"""One bounded, cancellable translation job; no global UI/network lock."""
import asyncio
import time
from .i18n import LANGUAGES

REQUEST_TIMEOUT=25
BATCH_SIZE=20
FAILURE_CACHE_LIMIT=3000
SUPPORTED_LANGUAGES=frozenset(code.split('-')[0] for code in LANGUAGES)


def remember_failures(app, keys):
    app.translation_failed.update(keys)
    while len(app.translation_failed)>FAILURE_CACHE_LIMIT:
        app.translation_failed.pop()


async def request(backend,peer,ids,language):
    return await asyncio.wait_for(backend.translate_messages(peer,ids,language,premium=True),REQUEST_TIMEOUT)


def schedule(app):
    from .advanced_features import feature_enabled
    from .chat_capabilities import chat_capabilities
    allowed = feature_enabled(app, 'chat_translation') and (getattr(app, 'thread', None) is not None or chat_capabilities(app).allows('translate'))
    language=app.chat_translations.get(f'{app.ui_account}:{app.active}') if allowed else None
    scope=(app.ui_account,app.active,language)
    previous=getattr(app,'_translation_scope',None)
    if previous!=scope:
        job=getattr(app,'_translation_job',None)
        if job is not None:job.cancel()
        app._translation_job=None;app._translation_scope=scope
        app._translation_token=object();app.translation_pending.clear()
        app._translation_attempted=set();app._translation_after=0;app._translation_retry_count=0
    if app.demo or app.active is None or language not in SUPPORTED_LANGUAGES:return
    if getattr(app,'_translation_job',None) is not None:return
    if getattr(app, '_translation_retry_count', 0) > 3:return
    if time.monotonic()<getattr(app,'_translation_after',0):return
    account,peer,_=scope
    attempted=app._translation_attempted
    visible=[(account,peer,m.id,language,m.text) for m in reversed(app.messages)
             if (m.raw_text if getattr(m,'raw_text',None) is not None else m.text).strip()]
    # History is replaced as the user navigates. Do not retain entire old text
    # strings forever merely to prevent retries within the current view.
    attempted.intersection_update(visible)
    keys=[]
    for key in visible:
        if key not in app.translated and key not in app.translation_failed and key not in attempted:
            keys.append(key)
            if len(keys)==BATCH_SIZE:break
    if not keys:return
    token=app._translation_token;app.translation_pending.update(keys)
    def finish():
        if token is not app._translation_token:return False
        app._translation_job=None;app.translation_pending.difference_update(keys)
        attempted.update(keys);return True
    def done(result):
        if not finish():return
        if account not in app.service.entries:return
        for key in keys:
            if key[2] in result:app.translated[key]=result[key[2]]
            else:remember_failures(app,(key,))
        app._translation_retry_count = 0
        # Eviction never causes a render/request loop for long histories.
        while len(app.translated)>3000:app.translated.pop(next(iter(app.translated)))
        app._translation_after=time.monotonic()+.7
        if (account,peer)==(app.ui_account,app.active):
            app.render_messages(False)
            root=getattr(app,'root',None)
            if root is not None:root.after(750,lambda:app.schedule_translations() if scope==getattr(app,'_translation_scope',None) else None)
    def failed(exc):
        if not finish():return
        # A transient outage must not permanently blacklist this chat's text.
        # Retry at most three times automatically; re-entering the chat resets
        # the bounded retry budget. Telegram flood waits are always respected.
        from telethon import errors
        transient = isinstance(exc, (OSError, TimeoutError, errors.FloodWaitError, errors.ServerError)) or getattr(exc, 'message', '') in (
            'TRANSLATE_REQ_QUOTA_EXCEEDED', 'TRANSLATE_REQ_FAILED', 'TRANSLATION_TIMEOUT')
        count = getattr(app, '_translation_retry_count', 0) + 1
        app._translation_retry_count = count
        delay = max(min(300, 30 * (2 ** min(count - 1, 4))), getattr(exc, 'seconds', 0))
        app._translation_after = time.monotonic() + delay
        if transient:
            attempted.difference_update(keys)
            if count <= 3 and getattr(app, 'root', None) is not None:
                app.root.after(int(delay * 1000) + 10,
                    lambda: app.schedule_translations() if scope == getattr(app, '_translation_scope', None) and not getattr(app, 'closed', False) else None)
        else:
            remember_failures(app, keys)
        if (account,peer)==(app.ui_account,app.active):
            from .auth import error_message
            from .i18n import tr
            app.status.set(tr('Translation')+': '+error_message(exc))
    app._translation_job=app.worker.submit(request(app.service.backend,peer,[key[2] for key in keys],language),done,failed)
