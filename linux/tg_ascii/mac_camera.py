"""AVFoundation metadata and system effects; never creates a capture session."""
import json
import sys


def choose_format(formats, preferred=(4, 3), pixel_budget=1280 * 720):
    """Choose actual supported dimensions instead of stretching another format."""
    usable = [(w, h, fps) for w, h, fps in formats
              if 0 < w <= 4096 and 0 < h <= 4096 and w % 2 == h % 2 == 0 and 0 < fps <= 60]
    if not usable:
        return 640, 480, 24
    bounded = [item for item in usable if item[0] * item[1] <= pixel_budget]
    if not bounded:
        return min(usable, key=lambda item: item[0] * item[1])
    ratio = preferred[0] / max(1, preferred[1])
    return min(bounded, key=lambda item: (abs(item[0] / item[1] - ratio), -item[0] * item[1], abs(item[2] - 24)))


def camera_format(metadata):
    if sys.platform != 'darwin':
        return 640, 480, 24
    try:
        import AVFoundation as av
        import CoreMedia
        ident = json.loads(metadata)['id']
        kinds = [av.AVCaptureDeviceTypeBuiltInWideAngleCamera, av.AVCaptureDeviceTypeExternal]
        session = av.AVCaptureDeviceDiscoverySession.discoverySessionWithDeviceTypes_mediaType_position_(
            kinds, av.AVMediaTypeVideo, av.AVCaptureDevicePositionUnspecified)
        device = next((item for item in session.devices() if item.uniqueID() == ident), None)
        if device is None:
            return 640, 480, 24
        active = CoreMedia.CMVideoFormatDescriptionGetDimensions(device.activeFormat().formatDescription())
        formats = []
        for item in device.formats():
            dimensions = CoreMedia.CMVideoFormatDescriptionGetDimensions(item.formatDescription())
            rates = item.videoSupportedFrameRateRanges()
            fps = next((fps for fps in (24, 30, 15) if any(rate.minFrameRate() <= fps <= rate.maxFrameRate() for rate in rates)), None)
            if fps:
                formats.append((dimensions.width, dimensions.height, fps))
        return choose_format(formats, (active.width, active.height))
    except Exception:
        # Optional metadata must never prevent an otherwise supported call.
        return 640, 480, 24


def show_effects():
    if sys.platform != 'darwin':
        return False
    import AVFoundation as av
    if not hasattr(av.AVCaptureDevice, 'showSystemUserInterface_'):
        return False
    av.AVCaptureDevice.showSystemUserInterface_(av.AVCaptureSystemUserInterfaceVideoEffects)
    return True
