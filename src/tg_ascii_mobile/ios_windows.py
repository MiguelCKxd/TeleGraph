"""iPadOS (and the iOS app on a Mac): a chat in its own system window.

Toga drives the main window through one scene. Chat windows are extra scenes
(UIApplication.requestSceneSessionActivation, like WhatsApp for iPad), each
with a WKWebView showing the local page in its window mode. Toga's app
delegate always answers with its own scene delegate, so its scene
configuration method is replaced by one that sends chat scenes (and any extra
app window the user opens from the system) here. iOS restores these windows
on the next launch through each scene's state restoration activity.
"""
from urllib.parse import quote

ACTIVITY = 'org.tgas.chat'
_windows = {}      # scene pointer -> (window, web view, peer, activity)
_installed = False


def install(app):
    global _installed
    if _installed:
        return
    from rubicon.objc import Block, ObjCClass, objc_id, objc_method, objc_property, SEL
    from rubicon.objc.runtime import libobjc
    from tg_ascii.preferences import read_json, write_json

    UIApplication = ObjCClass('UIApplication')
    application = UIApplication.sharedApplication
    if not application.supportsMultipleScenes:
        return  # iPhone: the page keeps its in-app window
    UIResponder = ObjCClass('UIResponder')
    UISceneConfiguration = ObjCClass('UISceneConfiguration')
    UIWindow = ObjCClass('UIWindow')
    UIViewController = ObjCClass('UIViewController')
    WKWebView = ObjCClass('WKWebView')
    WKWebViewConfiguration = ObjCClass('WKWebViewConfiguration')
    NSURL = ObjCClass('NSURL')
    NSURLRequest = ObjCClass('NSURLRequest')
    UIColor = ObjCClass('UIColor')
    NSUserActivity = ObjCClass('NSUserActivity')
    core = app.core
    pending = {}
    session_file = core.root / 'mobile' / 'ios-chat-scenes.json'
    saved_sessions = read_json(session_file, {})

    def save_sessions():
        try:
            write_json(session_file, saved_sessions)
        except OSError as exc:
            print('chat scene state:', exc)

    def activated(activity):
        peer = peer_of(activity)
        for callback in pending.pop((account_of(activity), peer), []):
            callback(True)

    def page_url(peer, account):
        base = f'http://127.0.0.1:{core.port}/?t={core.token}&platform=iOS&top=0&bottom=0'
        return base + (f'&chat={int(peer)}&window=1&account={quote(account, safe="")}' if peer is not None else '')

    def load_page(web, peer, activity):
        url = NSURL.URLWithString(page_url(peer, account_of(activity)))
        web.loadRequest_(NSURLRequest.requestWithURL_(url))

    def reload_pages():
        for _, web, peer, activity in _windows.values():
            load_page(web, peer, activity)

    def chat_activity(session=None, options=None):
        candidates = []
        if options is not None:
            activities = options.userActivities
            if activities is not None and activities.count:
                candidates.append(activities.anyObject())
        if session is not None:
            candidates.append(session.stateRestorationActivity)
        for activity in candidates:
            if activity is not None and str(activity.activityType) == ACTIVITY:
                return activity
        # UIKit can reconnect a saved session before its restoration activity
        # becomes available. Its persisted userInfo identifies the same chat.
        info = session.userInfo if session is not None else None
        if info is not None and info.objectForKey_('peer') is not None and info.objectForKey_('account') is not None:
            activity = NSUserActivity.alloc().initWithActivityType_(ACTIVITY)
            activity.userInfo = info
            activity.title = str(info.objectForKey_('name') or '')
            return activity
        # If the process was killed before backgrounding, UIKit may have
        # saved only its session identifier, without the restoration payload.
        saved = saved_sessions.get(str(session.persistentIdentifier)) if session is not None else None
        if isinstance(saved, dict) and isinstance(saved.get('peer'), int) and isinstance(saved.get('account'), str):
            activity = NSUserActivity.alloc().initWithActivityType_(ACTIVITY)
            activity.userInfo = {'peer': str(saved['peer']), 'account': saved['account']}
            return activity
        return None

    def peer_of(activity):
        try:
            return int(str(activity.userInfo.objectForKey_('peer')))
        except Exception:
            return None

    def account_of(activity):
        info = activity.userInfo if activity is not None else None
        value = info.objectForKey_('account') if info is not None else None
        return str(value) if value is not None else ''

    def scanner_window(peer, account):
        for window, _, other_peer, activity in _windows.values():
            if (peer == other_peer and account_of(activity) == account and window.windowScene
                    and window.windowScene.activationState == 0):
                return window
        return None
    app.qr_chat_window = scanner_window

    from rubicon.objc import ObjCProtocol

    class TGChatSceneDelegate(UIResponder, protocols=(ObjCProtocol('UIWindowSceneDelegate'),)):
        window = objc_property()

        @objc_method
        def scene_willConnectToSession_options_(self, scene, session, options) -> None:
            activity = chat_activity(session, options)
            peer = peer_of(activity) if activity is not None else None
            window = UIWindow.alloc().initWithWindowScene_(scene)
            controller = UIViewController.alloc().init()
            web = WKWebView.alloc().initWithFrame_configuration_(window.bounds, WKWebViewConfiguration.alloc().init())
            color = UIColor.colorWithRed_green_blue_alpha_(8 / 255, 16 / 255, 12 / 255, 1.0)
            web.setOpaque_(False)
            web.backgroundColor = color
            web.scrollView.bounces = False
            pinch = web.scrollView.pinchGestureRecognizer
            if pinch is not None:
                pinch.enabled = False
            controller.view = web
            window.rootViewController = controller
            self.window = window
            window.makeKeyAndVisible()
            if activity is not None:
                scene.title = str(activity.title or '')
                session.userInfo = activity.userInfo
                session.stateRestorationActivity = activity
                key = str(session.persistentIdentifier)
                saved = {'peer': peer, 'account': account_of(activity)}
                if peer is not None and saved_sessions.get(key) != saved:
                    saved_sessions[key] = saved
                    save_sessions()
            load_page(web, peer, activity)
            _windows[scene.ptr.value] = (window, web, peer, activity)
            if activity is not None:
                activated(activity)

        @objc_method
        def sceneDidBecomeActive_(self, scene) -> None:
            entry = _windows.get(scene.ptr.value)
            if entry and entry[3] is not None:
                activated(entry[3])

        @objc_method
        def stateRestorationActivityForScene_(self, scene):
            entry = _windows.get(scene.ptr.value)
            return entry[3] if entry else None

        @objc_method
        def sceneDidDisconnect_(self, scene) -> None:
            entry = _windows.pop(scene.ptr.value, None)
            if entry and entry[2] is not None and account_of(entry[3]) == core.account:
                import asyncio
                asyncio.run_coroutine_threadsafe(core.api_close(entry[2], window=True), core.loop)

    class TGSceneRouter(ObjCClass('NSObject')):
        @objc_method
        def application_configurationForConnectingSceneSession_options_(self, application, session, options):
            main_window = app.main_window._impl.native
            activity = chat_activity(session, options)
            extra = activity is not None or main_window.windowScene is not None
            name = 'Chat window' if extra else 'Default Configuration'
            configuration = UISceneConfiguration.alloc().initWithName_sessionRole_(name, session.role)
            configuration.delegateClass = TGChatSceneDelegate if extra else ObjCClass('PythonSceneDelegate')
            return configuration

        @objc_method
        def application_didDiscardSceneSessions_(self, application, sessions) -> None:
            count = len(saved_sessions)
            for session in sessions.allObjects():
                saved_sessions.pop(str(session.persistentIdentifier), None)
            if len(saved_sessions) != count:
                save_sessions()

    for name in ('application:configurationForConnectingSceneSession:options:', 'application:didDiscardSceneSessions:'):
        selector = SEL(name)
        method = libobjc.class_getInstanceMethod(TGSceneRouter, selector)
        libobjc.class_replaceMethod(ObjCClass('PythonAppDelegate'), selector,
                                    libobjc.method_getImplementation(method), libobjc.method_getTypeEncoding(method))

    def open_window(peer, name, account, done):
        def run():
            key = (account, int(peer))
            if key in pending:
                pending[key].append(done)
                return
            callbacks = pending[key] = [done]

            def failed():
                if pending.get(key) is callbacks:
                    del pending[key]
                    for callback in callbacks:
                        callback(False)

            try:
                # openSessions also includes windows which UIKit disconnected.
                session = activity = None
                for existing in application.openSessions.allObjects():
                    saved = chat_activity(existing)
                    if saved is not None and (account_of(saved), peer_of(saved)) == key:
                        session, activity = existing, saved
                        break
                if activity is None:
                    activity = NSUserActivity.alloc().initWithActivityType_(ACTIVITY)
                    activity.title = str(name)
                    activity.userInfo = {'peer': str(int(peer)), 'name': str(name), 'account': account}
                error_handler = Block(lambda error: app.on_ui_thread(failed), None, objc_id)
                application.requestSceneSessionActivation_userActivity_options_errorHandler_(session, activity, None, error_handler)
                if session is not None and session.scene is not None and session.scene.activationState in (0, 1):
                    # A visible scene may be foreground-inactive in tiled mode.
                    activated(activity)
                else:
                    # The system may defer a request without connecting a scene.
                    core.loop.call_soon_threadsafe(core.loop.call_later, 8, app.on_ui_thread, failed)
            except Exception as exc:
                print('window:', type(exc).__name__, exc)
                failed()
        app.on_ui_thread(run)
    core.native_window = open_window
    app.reload_ios_chat_windows = reload_pages
    _installed = True
