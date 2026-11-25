"""AVKit Picture in Picture for a live Telegram video call on macOS 12+."""
from time import monotonic
import ctypes
import _tkinter

import AppKit
import AVFoundation
import AVKit
import CoreMedia
import Quartz
import objc


# AVKit encodes CMTime/CMVideoDimensions as anonymous C structs in its runtime
# protocol. Use the installed SDK's encodings so PyObjC accepts both forms.
_playback = objc.protocolNamed('AVPictureInPictureSampleBufferPlaybackDelegate')
_signatures = {entry['selector']: entry['typestr'] for entry in _playback.instanceMethods()}


def native_call_window(widget):
    # Tk's window ID on Aqua is its Drawable, not the NSWindow number.
    # Resolve it in the copy of Tk linked into this particular interpreter.
    library = ctypes.CDLL(_tkinter.__file__)
    lookup = getattr(library, 'Tk_MacOSXGetNSWindowForDrawable', None) or getattr(library, 'TkMacOSXDrawable', None)
    if lookup is None:
        return None
    lookup.argtypes = (ctypes.c_void_p,)
    lookup.restype = ctypes.c_void_p
    address = lookup(widget.winfo_id())
    return next((window for window in AppKit.NSApplication.sharedApplication().windows()
                 if objc.pyobjc_id(window) == address), None)


class TGMacCallPipDelegate(AppKit.NSObject, protocols=[
        _playback,
        objc.protocolNamed('AVPictureInPictureControllerDelegate')]):
    @objc.typedSelector(_signatures[b'pictureInPictureControllerTimeRangeForPlayback:'])
    def pictureInPictureControllerTimeRangeForPlayback_(self, controller):
        return CoreMedia.CMTimeRangeMake(CoreMedia.kCMTimeZero, CoreMedia.kCMTimePositiveInfinity)

    @objc.typedSelector(_signatures[b'pictureInPictureControllerIsPlaybackPaused:'])
    def pictureInPictureControllerIsPlaybackPaused_(self, controller):
        return False

    @objc.typedSelector(_signatures[b'pictureInPictureController:setPlaying:'])
    def pictureInPictureController_setPlaying_(self, controller, playing):
        pass

    @objc.typedSelector(_signatures[b'pictureInPictureController:didTransitionToRenderSize:'])
    def pictureInPictureController_didTransitionToRenderSize_(self, controller, size):
        pass

    @objc.typedSelector(_signatures[b'pictureInPictureController:skipByInterval:completionHandler:'])
    def pictureInPictureController_skipByInterval_completionHandler_(self, controller, interval, completion):
        completion()

    def pictureInPictureControllerDidStartPictureInPicture_(self, controller):
        self.started = True

    def pictureInPictureController_failedToStartPictureInPictureWithError_(self, controller, error):
        self.finished = True

    def pictureInPictureControllerDidStopPictureInPicture_(self, controller):
        self.finished = True

    def pictureInPictureController_restoreUserInterfaceForPictureInPictureStopWithCompletionHandler_(
            self, controller, completion):
        call = getattr(self, 'call', None)
        restore = bool(call and call.alive())
        if restore:
            call.window.deiconify()
            call.window.lift()
        completion(restore)


class MacCallPiP:
    @staticmethod
    def supported():
        return (hasattr(AVKit, 'AVPictureInPictureControllerContentSource')
                and AVKit.AVPictureInPictureController.isPictureInPictureSupported())

    def __init__(self, call):
        window = native_call_window(call.window)
        if window is None or window.contentView() is None:
            raise RuntimeError('Call window is unavailable for system picture in picture')
        self.call = call
        self.delegate = TGMacCallPipDelegate.new()
        self.delegate.call = call
        self.delegate.started = self.delegate.finished = False
        # Translate this call's inline video rectangle from Tk to AppKit.
        self.layer = AVFoundation.AVSampleBufferDisplayLayer.layer()
        self.layer.setVideoGravity_(AVFoundation.AVLayerVideoGravityResizeAspect)
        content = window.contentView()
        x = call.viewport.winfo_rootx() - call.window.winfo_rootx()
        y = call.viewport.winfo_rooty() - call.window.winfo_rooty()
        width, height = call.viewport.winfo_width(), call.viewport.winfo_height()
        rect = AppKit.NSMakeRect(x, content.bounds().size.height - y - height, width, height)
        self.host = AppKit.NSView.alloc().initWithFrame_(rect)
        self.host.setWantsLayer_(True)
        self.host.setLayer_(self.layer)
        source = AVKit.AVPictureInPictureControllerContentSource.alloc().initWithSampleBufferDisplayLayer_playbackDelegate_(
            self.layer, self.delegate)
        self.controller = AVKit.AVPictureInPictureController.alloc().initWithContentSource_(source)
        if self.controller is None:
            raise RuntimeError('The system picture-in-picture controller is unavailable')
        self.controller.setDelegate_(self.delegate)
        self.controller.setRequiresLinearPlayback_(True)
        content.addSubview_(self.host)
        self.deadline = monotonic() + 5
        self.requested = False

    @property
    def failed_to_open(self):
        return not self.delegate.started

    def displaying(self):
        if self.delegate.finished:
            return False
        if not self.requested and self.controller.isPictureInPicturePossible():
            self.requested = True
            self.controller.startPictureInPicture()
        return self.delegate.started or monotonic() < self.deadline

    def show(self, image):
        width, height = image.size
        err, buf = Quartz.CVPixelBufferCreate(None, width, height, Quartz.kCVPixelFormatType_32BGRA,
                                             {Quartz.kCVPixelBufferIOSurfacePropertiesKey: {}}, None)
        if err or Quartz.CVPixelBufferLockBaseAddress(buf, 0):
            return
        try:
            stride = Quartz.CVPixelBufferGetBytesPerRow(buf)
            view = Quartz.CVPixelBufferGetBaseAddress(buf).as_buffer(stride * height)
            raw = image.convert('RGBA').tobytes('raw', 'BGRA', stride)
            view[:] = raw
        finally:
            Quartz.CVPixelBufferUnlockBaseAddress(buf, 0)
        err, desc = CoreMedia.CMVideoFormatDescriptionCreateForImageBuffer(None, buf, None)
        if err:
            return
        now = CoreMedia.CMClockGetTime(CoreMedia.CMClockGetHostTimeClock())
        timing = CoreMedia.CMSampleTimingInfo(CoreMedia.kCMTimeInvalid, now, CoreMedia.kCMTimeInvalid)
        err, sample = CoreMedia.CMSampleBufferCreateReadyWithImageBuffer(None, buf, desc, timing, None)
        if err:
            return
        attachments = CoreMedia.CMSampleBufferGetSampleAttachmentsArray(sample, True)
        attachments[0][CoreMedia.kCMSampleAttachmentKey_DisplayImmediately] = True
        if self.layer.status() == AVFoundation.AVQueuedSampleBufferRenderingStatusFailed:
            self.layer.flush()
        if self.layer.isReadyForMoreMediaData():
            self.layer.enqueueSampleBuffer_(sample)

    def clear(self):
        self.layer.flushAndRemoveImage()

    def close(self):
        self.clear()
        self.controller.setDelegate_(None)
        self.controller.stopPictureInPicture()
        self.controller.setContentSource_(None)
        self.host.removeFromSuperview()
        self.delegate.call = None
