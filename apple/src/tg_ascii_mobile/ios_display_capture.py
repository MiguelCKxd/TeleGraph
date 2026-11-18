"""Full-display capture through the iOS 27 system picker."""
import ctypes as C
from dataclasses import dataclass


@dataclass
class Selection:
    observer: object
    sample: object
    completed: object
    stream: object = None
    ready: bool = False


def install(app):
    from rubicon.objc import Block, ObjCClass, ObjCProtocol, objc_id, objc_method
    from rubicon.objc.runtime import load_library

    load_library('ScreenCaptureKit')
    picker = ObjCClass('SCContentSharingPicker').sharedPicker
    if not picker.isAvailable():
        return None
    Stream = ObjCClass('SCStream')
    Configuration = ObjCClass('SCStreamConfiguration')
    PickerConfiguration = ObjCClass('SCContentSharingPickerConfiguration')
    NSObject = ObjCClass('NSObject')

    class DisplayCapture:
        def __init__(self):
            self.current = None
            self.blocks = set()

        def complete_with(self, method, callback):
            def finished(error):
                failed = bool(error)

                def deliver():
                    self.blocks.discard(block)
                    callback(failed)
                app.on_main_thread(deliver)

            block = Block(finished, None, objc_id)
            self.blocks.add(block)
            try:
                method(block)
            except Exception:
                self.blocks.discard(block)
                callback(True)

        def start(self, sample, completed):
            selection = Selection(Observer.alloc().init(), sample, completed)
            self.current = selection
            try:
                config = PickerConfiguration.alloc().init()
                config.showsMicrophoneControl = False
                config.showsCameraControl = False
                picker.setDefaultConfiguration_(config)
                picker.addObserver_(selection.observer)
                picker.setActive_(True)
                picker.present()
            except Exception:
                self.stop(lambda *_: None)

        def selected(self, observer, content_filter):
            selection = self.current
            if selection is None or observer != selection.observer or selection.stream is not None:
                return
            try:
                config = Configuration.alloc().init()
                config.setCapturesAudio_(False)
                stream = Stream.alloc().initWithFilter_configuration_delegate_(content_filter, config, observer)
                if not stream.addStreamOutput_type_sampleHandlerQueue_error_(observer, 0, None, None):
                    self.stop(lambda *_: None)
                    return
                selection.stream = stream
            except Exception:
                self.stop(lambda *_: None)
                return

            def started(failed):
                if self.current is not selection:
                    if not failed:
                        self.complete_with(stream.stopCaptureWithCompletionHandler_, lambda *_: None)
                    return
                if failed:
                    self.stop(lambda *_: None)
                else:
                    selection.ready = True
                    selection.completed(False)

            self.complete_with(stream.startCaptureWithCompletionHandler_, started)

        def stop(self, completed):
            selection, self.current = self.current, None
            if selection is None:
                completed(False)
                return
            picker.removeObserver_(selection.observer)
            picker.setActive_(False)
            if selection.ready:
                self.complete_with(selection.stream.stopCaptureWithCompletionHandler_, completed)
            else:
                selection.completed(True)
                completed(False)

        def ended(self, observer, stream):
            selection = self.current
            if selection is None or observer != selection.observer:
                return
            if stream is not None and stream != selection.stream:
                return
            if selection.ready:
                selection.sample(None, 1, True)
            else:
                self.stop(lambda *_: None)

    class Observer(NSObject, protocols=(ObjCProtocol('SCContentSharingPickerObserver'),
                                       ObjCProtocol('SCStreamOutput'), ObjCProtocol('SCStreamDelegate'))):
        @objc_method
        def contentSharingPicker_didUpdateWithFilter_forStream_(self, picker, content_filter, stream) -> None:
            app.on_main_thread(lambda: backend.selected(self, content_filter))

        @objc_method
        def contentSharingPicker_didCancelForStream_(self, picker, stream) -> None:
            app.on_main_thread(lambda: backend.ended(self, stream))

        @objc_method
        def contentSharingPickerStartDidFailWithError_(self, error) -> None:
            app.on_main_thread(lambda: backend.ended(self, None))

        @objc_method
        def stream_didStopWithError_(self, stream, error) -> None:
            app.on_main_thread(lambda: backend.ended(self, stream))

        @objc_method
        def stream_didOutputSampleBuffer_ofType_(self, stream, sample: C.c_void_p, kind: C.c_long) -> None:
            selection = backend.current
            if selection is not None and self == selection.observer and kind == 0:
                selection.sample(sample, 1, None)

    backend = DisplayCapture()
    return backend
