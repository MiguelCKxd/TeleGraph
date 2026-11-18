"""System controls for incoming Telegram calls received by the live connection."""
import asyncio
from concurrent.futures import Future
from dataclasses import dataclass
import logging

log = logging.getLogger(__name__)


@dataclass
class IncomingCall:
    token: str
    uuid: object
    audio: Future
    request: Future | None = None
    video: bool = False
    ending: bool = False
    delegate_action: object = None
    delegate_task: Future | None = None


def install(app, configure_audio):
    from rubicon.objc import Block, ObjCClass, ObjCProtocol, objc_id, objc_method
    from rubicon.objc.runtime import load_library
    from tg_ascii.i18n import tr

    load_library('CallKit')
    NSObject = ObjCClass('NSObject')
    NSUUID = ObjCClass('NSUUID')
    NSDate = ObjCClass('NSDate')
    CXProvider = ObjCClass('CXProvider')
    CXProviderConfiguration = ObjCClass('CXProviderConfiguration')
    CXCallUpdate = ObjCClass('CXCallUpdate')
    CXHandle = ObjCClass('CXHandle')
    CXCallController = ObjCClass('CXCallController')
    CXTransaction = ObjCClass('CXTransaction')
    CXAnswerCallAction = ObjCClass('CXAnswerCallAction')

    core = app.core
    current = None
    last_reported = None
    blocks = set()

    def with_completion(callback, invoke):
        def completion(error):
            blocks.discard(block)
            callback(bool(error))

        block = Block(completion, None, objc_id)
        blocks.add(block)
        try:
            invoke(block)
        except Exception:
            blocks.discard(block)
            callback(True)

    def finish(reason, *, report=True):
        nonlocal current
        call, current = current, None
        if call is None:
            return
        if not call.audio.done():
            call.audio.set_result(False)
        if call.request is not None and not call.request.done():
            call.request.set_exception(RuntimeError('The call ended'))
        if report:
            provider.reportCallWithUUID_endedAtDate_reason_(call.uuid, NSDate.date, reason)

    def run(action, name):
        call = current
        if call is None or not action.callUUID.isEqual_(call.uuid):
            action.fail()
            return

        muted = bool(action.isMuted()) if name == 'mute' else False

        async def control():
            try:
                return await core._call_action(
                    name, token=call.token, video=call.video, value=muted, from_system=True)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.info('CallKit %s action failed', name)
                raise

        if name == 'end':
            call.ending = True
        if name == 'accept':
            try:
                configure_audio()
            except RuntimeError as error:
                action.fail()
                if call.request is not None and not call.request.done():
                    call.request.set_exception(error)
                return
        task = asyncio.run_coroutine_threadsafe(control(), core.loop)
        if name in ('accept', 'end'):
            call.delegate_action, call.delegate_task = action, task

        def done(result):
            def deliver():
                if call.delegate_task is task:
                    call.delegate_action = call.delegate_task = None
                error = None if not result.cancelled() else RuntimeError('The call ended')
                if error is None:
                    error = result.exception()
                if not action.isComplete():
                    if error is None:
                        action.fulfill()
                    else:
                        action.fail()
                if name == 'end' and current is call:
                    call.ending = False
                    if error is None:
                        finish(2, report=False)
                if name == 'accept' and call.request is not None and not call.request.done():
                    if error is None:
                        call.request.set_result(result.result())
                    else:
                        call.request.set_exception(error)
            app.on_main_thread(deliver)

        task.add_done_callback(done)

    class TGCallKitDelegate(NSObject, protocols=(ObjCProtocol('CXProviderDelegate'),)):
        @objc_method
        def providerDidReset_(self, provider) -> None:
            call = current
            finish(1, report=False)
            if call is not None:
                future = asyncio.run_coroutine_threadsafe(
                    core._call_action('end', token=call.token, from_system=True), core.loop)
                future.add_done_callback(
                    lambda result: result.exception() if not result.cancelled() else None)

        @objc_method
        def provider_performAnswerCallAction_(self, provider, action) -> None:
            run(action, 'accept')

        @objc_method
        def provider_performEndCallAction_(self, provider, action) -> None:
            run(action, 'end')

        @objc_method
        def provider_performSetMutedCallAction_(self, provider, action) -> None:
            run(action, 'mute')

        @objc_method
        def provider_timedOutPerformingAction_(self, provider, action) -> None:
            call = current
            if call is not None and call.delegate_action is not None:
                if action.UUID.isEqual_(call.delegate_action.UUID):
                    call.delegate_task.cancel()
                    finish(1)

        @objc_method
        def provider_didActivateAudioSession_(self, provider, session) -> None:
            call = current
            if call is not None and not call.audio.done():
                call.audio.set_result(True)

    configuration = CXProviderConfiguration.alloc().init()
    configuration.supportsVideo = True
    configuration.maximumCallGroups = 1
    configuration.maximumCallsPerCallGroup = 1
    provider = CXProvider.alloc().initWithConfiguration_(configuration)
    controller = CXCallController.alloc().init()
    delegate = TGCallKitDelegate.alloc().init()
    provider.setDelegate_queue_(delegate, None)

    def update(snapshot):
        def apply():
            nonlocal current, last_reported
            token = snapshot.get('token')
            phase = snapshot.get('state')
            if current is not None and (current.token != token or phase in ('idle', 'ended')):
                if current.ending and current.token == token:
                    return
                finish(1 if snapshot.get('error') else 2, report=not current.ending)
            if current is not None or not token or token == last_reported or phase != 'incoming':
                return
            last_reported = token
            call = current = IncomingCall(token, NSUUID.UUID, Future())
            report = CXCallUpdate.alloc().init()
            report.remoteHandle = CXHandle.alloc().initWithType_value_(1, str(snapshot['peer']))
            report.localizedCallerName = snapshot.get('name') or tr('Call')
            report.hasVideo = bool(snapshot.get('requested_video'))

            def reported(failed):
                def complete():
                    if failed and current is call:
                        finish(1, report=False)
                app.on_main_thread(complete)

            with_completion(reported, lambda block: provider.reportNewIncomingCallWithUUID_update_completion_(
                call.uuid, report, block))
        app.on_main_thread(apply)

    async def answer(token, video):
        requested = Future()

        def request():
            call = current
            if call is None or call.token != token:
                requested.set_result(None)
                return
            if call.request is not None and not call.request.done():
                requested.set_exception(RuntimeError('The call is already being answered'))
                return
            call.request, call.video = requested, video
            action = CXAnswerCallAction.alloc().initWithCallUUID_(call.uuid)
            transaction = CXTransaction.alloc().initWithAction_(action)

            def completed(failed):
                if not failed:
                    return

                def reject():
                    if not requested.done():
                        requested.set_exception(RuntimeError('CallKit could not answer the call'))

                app.on_main_thread(reject)

            with_completion(completed, lambda block: controller.requestTransaction_completion_(transaction, block))

        app.on_main_thread(request)
        return await asyncio.shield(asyncio.wrap_future(requested))

    async def wait_for_audio(token):
        call = current
        if call is None or call.token != token:
            return False
        if not await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(call.audio)), 10):
            raise RuntimeError('CallKit ended before activating audio')
        return True

    # The provider's delegate is weak. Keep it alive for the lifetime of the app.
    app._callkit_delegate = delegate
    core.native_callkit_update = update
    core.native_callkit_answer = answer
    return wait_for_audio
