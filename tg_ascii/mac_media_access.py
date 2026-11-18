"""Request macOS media access before dialing or opening native capture devices."""
import asyncio
import sys


async def ensure_media_access(video=False):
    if sys.platform != 'darwin':
        return
    import AVFoundation as av
    loop = asyncio.get_running_loop()
    requested = [(av.AVMediaTypeAudio, 'Microphone')]
    if video:
        requested.append((av.AVMediaTypeVideo, 'Camera'))
    for media, label in requested:
        status = av.AVCaptureDevice.authorizationStatusForMediaType_(media)
        if status == av.AVAuthorizationStatusAuthorized:
            continue
        if status != av.AVAuthorizationStatusNotDetermined:
            raise PermissionError(label + ' access is disabled in macOS Privacy & Security.')
        future = loop.create_future()
        def complete(allowed, future=future):
            def deliver():
                if not future.done():
                    future.set_result(bool(allowed))
            try:
                loop.call_soon_threadsafe(deliver)
            except RuntimeError:
                pass
        av.AVCaptureDevice.requestAccessForMediaType_completionHandler_(media, complete)
        if not await asyncio.wait_for(future, 45):
            raise PermissionError(label + ' access was not granted.')
