import UIKit
import WebKit

// Observe the window's real layout, never the global screen or the keyboard.
// The web viewport owns keyboard avoidance and receives the original insets.
@objc(TGNativeViewport) public final class TGNativeViewport: NSObject {
    @MainActor @objc(attachToWebView:)
    public static func attach(to webView: WKWebView) -> NSObject {
        ViewportCoordinator(webView: webView)
    }
}

@MainActor private final class ViewportSensor: UIView {
    var changed: (() -> Void)?
    override func layoutSubviews() { super.layoutSubviews(); changed?() }
    override func safeAreaInsetsDidChange() { super.safeAreaInsetsDidChange(); changed?() }
    override func didMoveToWindow() { super.didMoveToWindow(); changed?() }
}

@MainActor private final class ViewportCoordinator: NSObject {
    private weak var webView: WKWebView?
    private let sensor = ViewportSensor()
    private var loading: NSKeyValueObservation?
    private var pending = false
    private var force = true
    private var last: [Int] = []

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        sensor.frame = webView.bounds
        sensor.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        sensor.isUserInteractionEnabled = false
        sensor.accessibilityElementsHidden = true
        sensor.changed = { [weak self] in self?.schedule() }
        webView.insertSubview(sensor, at: 0)
        loading = webView.observe(\.isLoading, options: [.new]) { [weak self] _, change in
            if change.newValue == false {
                MainActor.assumeIsolated { self?.force = true; self?.schedule() }
            }
        }
        schedule()
    }

    private func schedule() {
        guard !pending else { return }
        pending = true
        DispatchQueue.main.async { [weak self] in self?.apply() }
    }

    private func apply() {
        pending = false
        guard let webView, let window = webView.window else { return }
        let frame = webView.convert(webView.bounds, to: window)
        let top = max(0, Int((window.safeAreaInsets.top - frame.minY).rounded()))
        let bottom = max(0, Int((frame.maxY - (window.bounds.maxY - window.safeAreaInsets.bottom)).rounded()))
        guard force || last != [top, bottom] else { return }
        force = false
        last = [top, bottom]
        // Only numbers originating in UIKit enter this script. No navigation,
        // focus, DOM rebuild or synthetic keyboard compensation is performed.
        let script = "if(document.documentElement){const s=document.documentElement.style;s.setProperty('--top','\(top)px');s.setProperty('--bottom','\(bottom)px');}"
        webView.evaluateJavaScript(script) { [weak self] _, error in
            if error != nil { self?.force = true }
        }
    }

    @objc func detach() {
        loading?.invalidate(); loading = nil
        sensor.changed = nil
        sensor.removeFromSuperview()
        webView = nil
    }
}
