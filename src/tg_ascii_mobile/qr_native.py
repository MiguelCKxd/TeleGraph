"""Native QR reading for Settings › Accounts › Scan QR code.

Android: the packaged ZXing decoder reads from a native camera screen or a photo.
iOS / Mac: an AVFoundation camera screen, and Core Image for a picture.
Both give the core the text of the code, or None.
"""

CAMERA_DENIED = '\x00camera-denied'


def install_android(app, activity):
    from android.content import Intent
    from java import jclass

    reader = jclass('org.tgas.qr.QrCaptureActivity')
    busy = False

    def scan(done):
        def start():
            nonlocal busy
            if busy:
                done(None)
                return
            busy = True

            def completed(code, data):
                nonlocal busy
                busy = False
                if code == -1 and data is not None:
                    done(str(data.getStringExtra('SCAN_RESULT') or ''))
                elif data is not None and data.getBooleanExtra('MISSING_CAMERA_PERMISSION', False):
                    done(CAMERA_DENIED)
                else:
                    done(None)

            try:
                intent = Intent('com.google.zxing.client.android.SCAN')
                intent.setClassName(activity, 'org.tgas.qr.QrCaptureActivity')
                intent.putExtra('SCAN_FORMATS', 'QR_CODE')
                intent.putExtra('BEEP_ENABLED', False)
                intent.putExtra('SCAN_ORIENTATION_LOCKED', False)
                app._impl.start_activity(intent, on_complete=completed)
            except Exception:
                busy = False
                done(None)

        app.loop.call_soon_threadsafe(start)

    def read_image(path):
        value = reader.readImage(str(path))
        return str(value) if value is not None else None

    app.core.native_scan = scan
    app.core.native_qr_image = read_image


def install_ios(app):
    import ctypes
    from threading import Timer
    from concurrent.futures import ThreadPoolExecutor
    from rubicon.objc import Block, NSObject, ObjCClass, ObjCInstance, ObjCProtocol, objc_method
    from rubicon.objc.runtime import SEL, load_library

    load_library('AVFoundation')
    load_library('CoreImage')
    dispatch = load_library('System')
    main_queue = ObjCInstance(ctypes.cast(ctypes.addressof(ctypes.c_char.in_dll(dispatch, '_dispatch_main_q')), ctypes.c_void_p))
    current = {}
    camera_queue = ThreadPoolExecutor(max_workers=1, thread_name_prefix='qr-camera')

    class Scanner(NSObject, protocols=(ObjCProtocol('AVCaptureMetadataOutputObjectsDelegate'),)):
        @objc_method
        def captureOutput_didOutputMetadataObjects_fromConnection_(self, output, objects, connection) -> None:
            for item in objects:
                text = getattr(item, 'stringValue', None)
                if text is not None:
                    close(self, str(text))
                    return

        @objc_method
        def cancel_(self, sender) -> None:
            close(self, None)

    def finish(state):
        if current.get('state') is state:
            current.pop('state')
            if timer := state.pop('watchdog', None):
                timer.cancel()
            state.pop('present_completion', None)
            state.pop('dismiss_completion', None)
            state['done'](state.get('text'))

    def dismiss_if_ready(state):
        if not state.get('presented') or not state.get('stopped') or state.get('dismissing'):
            return
        state['dismissing'] = True
        controller = state['controller']
        if controller.presentingViewController is None:
            finish(state)
            return
        try:
            completion = Block(lambda: finish(state), None)
            state['dismiss_completion'] = completion
            controller.dismissViewControllerAnimated_completion_(True, completion)
        except Exception:
            finish(state)

    def close(delegate, text):
        state = current.get('state')
        if state is None or state.get('closing') or state['delegate'] is not delegate:
            return
        state.update(closing=True, text=text)
        try:
            state['output'].setMetadataObjectsDelegate_queue_(None, None)
        except Exception as exc:
            print('scan delegate:', type(exc).__name__)

        def stopped():
            state['stopped'] = True
            dismiss_if_ready(state)

        def stop():
            try:
                state['session'].stopRunning()
            finally:
                app.on_main_thread(stopped)
        camera_queue.submit(stop)

    def scan(done, window_peer=None, window_account=None):
        cancelled = False
        def cancel():
            nonlocal cancelled
            cancelled = True
            def stop_current():
                state = current.get('state')
                if state and state['done'] is done:
                    close(state['delegate'], None)
            app.on_main_thread(stop_current)

        def run():
            try:
                if cancelled or 'state' in current:
                    done(None)
                    return
                capture = ObjCClass('AVCaptureDevice')
                status = capture.authorizationStatusForMediaType_('vide')
                if status == 0:
                    if 'permission' in current:
                        done(None)
                        return
                    def answered(allowed):
                        def proceed():
                            current.pop('permission', None)
                            if allowed:
                                run()
                            else:
                                done(CAMERA_DENIED)
                        app.on_main_thread(proceed)
                    reply = Block(answered, None, ctypes.c_bool)
                    current['permission'] = reply
                    capture.requestAccessForMediaType_completionHandler_('vide', reply)
                    return
                if status != 3:
                    done(CAMERA_DENIED)
                    return
                device = capture.defaultDeviceWithMediaType_('vide')
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
                if not session.canAddOutput_(output):
                    done(None)
                    return
                session.addOutput_(output)
                delegate = Scanner.alloc().init()
                output.setMetadataObjectsDelegate_queue_(delegate, main_queue)
                qr_type = 'org.iso.QRCode'
                if not any(str(kind) == qr_type for kind in output.availableMetadataObjectTypes):
                    done(None)
                    return
                output.setMetadataObjectTypes_([qr_type])
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
                cancel.addTarget_action_forControlEvents_(delegate, SEL('cancel:'), 1 << 6)  # TouchUpInside
                cancel.translatesAutoresizingMaskIntoConstraints = False
                view.addSubview_(cancel)
                cancel.centerXAnchor.constraintEqualToAnchor_(view.centerXAnchor).active = True
                cancel.bottomAnchor.constraintEqualToAnchor_constant_(view.safeAreaLayoutGuide.bottomAnchor, -24).active = True
                controller.modalPresentationStyle = 0  # full screen
                state = {'session': session, 'controller': controller, 'delegate': delegate,
                                    'output': output, 'preview': preview, 'done': done}
                window = (app.qr_chat_window(window_peer, window_account) if window_peer is not None
                          else app.main_window._impl.native)
                if window is None or window.windowScene is None or window.windowScene.activationState != 0:
                    done(None)
                    return
                root = window.rootViewController
                while root.presentedViewController is not None:
                    root = root.presentedViewController
                if root.view.window is None or root.isBeingDismissed() or root.isBeingPresented():
                    done(None)
                    return
                current['state'] = state
                def presented():
                    state.pop('present_completion', None)
                    state['presented'] = True
                    dismiss_if_ready(state)
                def check_presentation():
                    if current.get('state') is not state or state.get('presented'):
                        return
                    if controller.presentingViewController is not None:
                        presented()
                    else:
                        state['presented'] = True
                        close(delegate, None)
                        dismiss_if_ready(state)
                completion = Block(presented, None)
                state['present_completion'] = completion
                root.presentViewController_animated_completion_(controller, True, completion)
                preview.frame = view.bounds
                # startRunning blocks while the camera starts: not on the main thread.
                camera_queue.submit(session.startRunning)
                timer = Timer(2, lambda: app.on_main_thread(check_presentation))
                timer.daemon = True
                state['watchdog'] = timer
                timer.start()
            except Exception as exc:
                print('scan:', exc)
                current.pop('state', None)
                current.pop('permission', None)
                done(None)
        app.on_main_thread(run)
        return cancel

    def read_image(path):
        NSURL = ObjCClass('NSURL')
        image = ObjCClass('CIImage').imageWithContentsOfURL_(NSURL.fileURLWithPath_(path))
        if image is None:
            return None
        detector = ObjCClass('CIDetector').detectorOfType_context_options_(
            'CIDetectorTypeQRCode', None, {'CIDetectorAccuracy': 'CIDetectorAccuracyHigh'})
        features = detector.featuresInImage_(image)
        for feature in features:
            text = feature.messageString
            if text is not None:
                return str(text)
        return None

    app.core.native_scan = scan
    app.core.native_qr_image = read_image
