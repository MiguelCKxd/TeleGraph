"""iOS WebViews that can play Telegram videos inside the gallery."""
import toga
from rubicon.objc import CGRect, ObjCClass
from toga_iOS.widgets.webview import TogaWebView, WebView as IOSWebView


def inline_configuration():
    config = ObjCClass('WKWebViewConfiguration').alloc().init()
    # WebKit copies this setting at construction. The HTML video also needs
    # playsinline to keep the gallery, filmstrip and native export controls visible.
    config.allowsInlineMediaPlayback = True
    return config


class InlineWebViewImpl(IOSWebView):
    def create(self):
        self.native = TogaWebView.alloc().initWithFrame_configuration_(CGRect((0, 0), (0, 0)), inline_configuration())
        # The Toga 0.5 WebView backend creates its native view with init()
        # and has no configuration hook. Keep its delegates and setup intact.
        self.native.interface = self.interface
        self.native.impl = self
        self.native.inspectable = True
        self.native.navigationDelegate = self.native
        self.native.UIDelegate = self.native
        self.loaded_future = None
        self._allowed_url = None
        self.add_constraints()


class InlineWebView(toga.WebView):
    def _create(self):
        return InlineWebViewImpl(interface=self)
