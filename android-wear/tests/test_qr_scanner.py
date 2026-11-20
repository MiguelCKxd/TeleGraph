"""Regression tests for a QR callback racing the iOS presentation animation."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tg_ascii_mobile import qr_native


class Proxy:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()

    @classmethod
    def alloc(cls):
        return cls()

    def init(self):
        return self


class ScannerLifecycleTests(unittest.TestCase):
    def test_cancel_or_read_while_presenting_can_reopen(self):
        ui = []
        camera = []
        delegates = []
        presentations = []
        dismissals = []
        root = MagicMock()
        root.presentedViewController = None
        root.isBeingDismissed.return_value = root.isBeingPresented.return_value = False
        root.presentViewController_animated_completion_.side_effect = lambda vc, animate, cb: presentations.append(cb)
        controller = MagicMock()
        controller.presentingViewController = root
        controller.dismissViewControllerAnimated_completion_.side_effect = lambda animate, cb: dismissals.append(cb)
        output = MagicMock()
        output.availableMetadataObjectTypes = ['org.iso.QRCode']
        output.setMetadataObjectsDelegate_queue_.side_effect = lambda delegate, queue: delegates.append(delegate)
        classes = {name: MagicMock() for name in (
            'AVCaptureDevice', 'AVCaptureSession', 'AVCaptureDeviceInput', 'AVCaptureMetadataOutput',
            'UIViewController', 'UIColor', 'AVCaptureVideoPreviewLayer', 'UIButton')}
        classes['AVCaptureDevice'].authorizationStatusForMediaType_.return_value = 3
        classes['AVCaptureMetadataOutput'].alloc().init.return_value = output
        classes['UIViewController'].alloc().init.return_value = controller
        app = SimpleNamespace(core=SimpleNamespace(), on_main_thread=ui.append,
                              main_window=SimpleNamespace(_impl=SimpleNamespace(native=SimpleNamespace(rootViewController=root, windowScene=SimpleNamespace(activationState=0)))))
        objc = SimpleNamespace(NSObject=Proxy, ObjCClass=classes.__getitem__, ObjCProtocol=lambda name: name,
                               ObjCInstance=lambda value: value, objc_method=lambda method: method,
                               Block=lambda method, *types: method)
        import ctypes
        # install_ios looks up the system main queue through ctypes.
        library = SimpleNamespace(_handle=ctypes.CDLL(None)._handle)
        cancel_selector = object()
        selector = MagicMock(return_value=cancel_selector)
        with patch.dict(sys.modules, {'rubicon.objc': objc, 'rubicon.objc.runtime': SimpleNamespace(load_library=lambda name: library, SEL=selector)}), \
             patch('ctypes.c_char', MagicMock(in_dll=lambda *args: ctypes.c_byte())), \
             patch('concurrent.futures.ThreadPoolExecutor', return_value=SimpleNamespace(submit=camera.append)):
            qr_native.install_ios(app)
            results = []
            for expected in [None, 'sample QR']:
                app.core.native_scan(results.append)
                ui.pop(0)()
                delegate = delegates[-1]
                self.assertIsNotNone(delegate)
                selector.assert_called_with('cancel:')
                classes['UIButton'].buttonWithType_.return_value.addTarget_action_forControlEvents_.assert_called_with(delegate, cancel_selector, 1 << 6)
                camera.pop(0)()
                if expected is None:
                    delegate.cancel_(None)
                else:
                    delegate.captureOutput_didOutputMetadataObjects_fromConnection_(output, [SimpleNamespace(stringValue=expected)], None)
                delegate.cancel_(None)
                camera.pop(0)()
                ui.pop(0)()
                self.assertFalse(dismissals)
                presentations.pop(0)()
                self.assertEqual(len(dismissals), 1)
                dismissals.pop(0)()
                self.assertEqual(results[-1], expected)
            self.assertEqual(results, [None, 'sample QR'])
            root.isBeingDismissed.return_value = True
            app.core.native_scan(results.append)
            ui.pop(0)()
            self.assertEqual(results, [None, 'sample QR', None])
            root.isBeingDismissed.return_value = False
            app.qr_chat_window = MagicMock(return_value=app.main_window._impl.native)
            controller.presentingViewController = None
            with patch('threading.Timer') as timer:
                # install_ios already captured the timer class; install a fresh bridge.
                qr_native.install_ios(app)
                app.core.native_scan(results.append, 81, 'qa')
                ui.pop(0)()
                app.qr_chat_window.assert_called_once_with(81, 'qa')
                timer.call_args.args[1]()
                ui.pop(0)()
                camera.pop(0)()
                camera.pop(0)()
                ui.pop(0)()
                self.assertEqual(results, [None, 'sample QR', None, None])
                app.core.native_scan(results.append)
                ui.pop(0)()
                self.assertEqual(len(camera), 1)


@unittest.skipUnless(sys.platform == 'darwin', 'Core Image requires macOS')
class QRImageTests(unittest.TestCase):
    def test_decodes_real_qr_with_core_image(self):
        try:
            import qrcode
            import rubicon.objc
        except ImportError as exc:
            self.skipTest(str(exc))
        app = SimpleNamespace(core=SimpleNamespace())
        qr_native.install_ios(app)
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'scan.png'
            qrcode.make('TeleGraph QR test').save(image)
            self.assertEqual(app.core.native_qr_image(str(image)), 'TeleGraph QR test')
