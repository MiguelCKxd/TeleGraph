"""Native QR reading for Settings › Accounts › Scan QR code.

Android: Google's code scanner (Play services shows its own camera screen; the
app needs no camera permission) and ML Kit for a picture from the gallery.
iOS / Mac: an AVFoundation camera screen, and Core Image for a picture.
Both give the core the text of the code, or None.
"""
import threading

# Returned instead of a code while Google's scanner module is still being installed.
PREPARING = '\x00preparing'


def install_android(app, activity):
    from java import dynamic_proxy, jclass

    OnSuccess = jclass('com.google.android.gms.tasks.OnSuccessListener')
    OnFailure = jclass('com.google.android.gms.tasks.OnFailureListener')
    OnCanceled = jclass('com.google.android.gms.tasks.OnCanceledListener')
    keep = set()

    def install_module():
        """Google's scanner screen is a Play services module downloaded on demand."""
        try:
            scanner = jclass('com.google.mlkit.vision.codescanner.GmsBarcodeScanning').getClient(activity)
            request = jclass('com.google.android.gms.common.moduleinstall.ModuleInstallRequest').newBuilder().addApi(scanner).build()
            jclass('com.google.android.gms.common.moduleinstall.ModuleInstall').getClient(activity).installModules(request)
        except Exception as exc:
            print('scan module:', exc)

    def scan(done):
        state = {'done': False}

        def finish(text):
            if not state['done']:
                state['done'] = True
                keep.clear()
                done(text)

        class Success(dynamic_proxy(OnSuccess)):
            def onSuccess(self, barcode):
                finish(str(barcode.getRawValue() or '') if barcode is not None else None)

        class Failure(dynamic_proxy(OnFailure)):
            def onFailure(self, error):
                print('scan:', error)
                if 'download' in str(error).lower():
                    install_module()
                    finish(PREPARING)
                else:
                    finish(None)

        class Canceled(dynamic_proxy(OnCanceled)):
            def onCanceled(self):
                finish(None)

        def start():
            try:
                Barcode = jclass('com.google.mlkit.vision.barcode.common.Barcode')
                Builder = jclass('com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions$Builder')
                options = Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build()
                scanner = jclass('com.google.mlkit.vision.codescanner.GmsBarcodeScanning').getClient(activity, options)
                listeners = (Success(), Failure(), Canceled())
                keep.update(listeners)
                scanner.startScan().addOnSuccessListener(listeners[0]).addOnFailureListener(listeners[1]).addOnCanceledListener(listeners[2])
            except Exception as exc:
                print('scan:', exc)
                finish(None)
        app.loop.call_soon_threadsafe(start)

    def read_image(path):
        """Blocking (the core calls it in a worker thread)."""
        from android.net import Uri
        from java.io import File
        image = jclass('com.google.mlkit.vision.common.InputImage').fromFilePath(activity, Uri.fromFile(File(path)))
        client = jclass('com.google.mlkit.vision.barcode.BarcodeScanning').getClient()
        try:
            codes = jclass('com.google.android.gms.tasks.Tasks').await_(client.process(image))
            for index in range(codes.size()):
                value = codes.get(index).getRawValue()
                if value:
                    return str(value)
        finally:
            client.close()
        return None

    app.core.native_scan = scan
    app.core.native_qr_image = read_image


def install_ios(app):
    import ctypes
    from rubicon.objc import NSObject, ObjCClass, ObjCInstance, objc_method
    from rubicon.objc.runtime import load_library

    load_library('AVFoundation')
    load_library('CoreImage')
    dispatch = load_library('System')
    main_queue = ObjCInstance(ctypes.cast(ctypes.addressof(ctypes.c_char.in_dll(dispatch, '_dispatch_main_q')), ctypes.c_void_p))
    current = {}

    class Scanner(NSObject):
        @objc_method
        def captureOutput_didOutputMetadataObjects_fromConnection_(self, output, objects, connection) -> None:
            for index in range(objects.count):
                item = objects.objectAtIndex(index)
                text = getattr(item, 'stringValue', None)
                if text is not None:
                    close(str(text))
                    return

        @objc_method
        def cancel_(self, sender) -> None:
            close(None)

    def close(text):
        state = current.pop('state', None)
        if state is None:
            return
        try:
            state['session'].stopRunning()
            state['controller'].dismissViewControllerAnimated_completion_(True, None)
        except Exception as exc:
            print('scan:', exc)
        threading.Thread(target=state['done'], args=(text,), daemon=True).start()

    def scan(done):
        def run():
            try:
                device = ObjCClass('AVCaptureDevice').defaultDeviceWithMediaType_('vide')
                if device is None:
                    done(None)
                    return
                session = ObjCClass('AVCaptureSession').alloc().init()
                camera = ObjCClass('AVCaptureDeviceInput').deviceInputWithDevice_error_(device, None)
                if camera is None or not session.canAddInput_(camera):
                    done(None)
                    return
                session.addInput_(camera)
                output = ObjCClass('AVCaptureMetadataOutput').alloc().init()
                session.addOutput_(output)
                delegate = Scanner.alloc().init()
                output.setMetadataObjectsDelegate_queue_(delegate, main_queue)
                output.metadataObjectTypes = ['org.iso.QRCode']
                controller = ObjCClass('UIViewController').alloc().init()
                view = controller.view
                view.backgroundColor = ObjCClass('UIColor').blackColor
                preview = ObjCClass('AVCaptureVideoPreviewLayer').layerWithSession_(session)
                preview.videoGravity = 'AVLayerVideoGravityResizeAspectFill'
                preview.frame = view.bounds
                view.layer.addSublayer_(preview)
                cancel = ObjCClass('UIButton').buttonWithType_(1)  # UIButtonTypeSystem
                from tg_ascii.i18n import tr
                cancel.setTitle_forState_(tr('Cancel'), 0)
                cancel.setTitleColor_forState_(ObjCClass('UIColor').whiteColor, 0)
                cancel.addTarget_action_forControlEvents_(delegate, 'cancel:', 1 << 6)  # TouchUpInside
                cancel.translatesAutoresizingMaskIntoConstraints = False
                view.addSubview_(cancel)
                cancel.centerXAnchor.constraintEqualToAnchor_(view.centerXAnchor).active = True
                cancel.bottomAnchor.constraintEqualToAnchor_constant_(view.safeAreaLayoutGuide.bottomAnchor, -24).active = True
                controller.modalPresentationStyle = 0  # full screen
                current['state'] = {'session': session, 'controller': controller, 'delegate': delegate,
                                    'preview': preview, 'done': done}
                root = app.main_window._impl.native.rootViewController
                root.presentViewController_animated_completion_(controller, True, None)
                preview.frame = view.bounds
                # startRunning blocks while the camera starts: not on the main thread.
                threading.Thread(target=session.startRunning, daemon=True).start()
            except Exception as exc:
                print('scan:', exc)
                current.pop('state', None)
                done(None)
        app.on_main_thread(run)

    def read_image(path):
        NSURL = ObjCClass('NSURL')
        image = ObjCClass('CIImage').imageWithContentsOfURL_(NSURL.fileURLWithPath_(path))
        if image is None:
            return None
        detector = ObjCClass('CIDetector').detectorOfType_context_options_(
            'CIDetectorTypeQRCode', None, {'CIDetectorAccuracy': 'CIDetectorAccuracyHigh'})
        features = detector.featuresInImage_(image)
        for index in range(features.count):
            text = features.objectAtIndex(index).messageString
            if text is not None:
                return str(text)
        return None

    app.core.native_scan = scan
    app.core.native_qr_image = read_image
