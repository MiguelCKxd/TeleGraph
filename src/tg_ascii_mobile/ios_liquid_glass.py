"""Install optional SwiftUI navigation controls without replacing the WebView."""


def attach(web):
    from rubicon.objc import ObjCClass
    try:
        # The factory returns nil before iOS 26. Source builds without the
        # native target keep the normal, fully functional web controls.
        return ObjCClass('TGNativeGlass').attachToWebView_(web)
    except Exception as exc:
        print("native glass:", type(exc).__name__)
        return None


def install(app):
    app._native_glass = attach(app.webview._impl.native)
