import UIKit
import SwiftUI
import WebKit
import Observation

// The Objective-C factory remains callable on the iOS 15 deployment target.
// Older systems keep the existing web controls; no imitation glass is drawn.
@objc(TGNativeGlass) public final class TGNativeGlass: NSObject {
    @MainActor @objc(attachToWebView:)
    public static func attach(to webView: WKWebView) -> NSObject? {
        if #available(iOS 26.0, *) { return GlassCoordinator(webView: webView) }
        return nil
    }
}

@available(iOS 26.0, *)
private struct GlassControl: Identifiable, Equatable {
    let id: Int
    let rect: CGRect
    let label: String
    let text: String
    let symbol: String
    let disabled: Bool
    let fontSize: Double
    let family: String
    let radius: Double
    let color: String
    let selected: Bool
    let showsText: Bool

    init?(_ data: [String: Any], viewport: TGNativeViewportGeometry) {
        guard let id = data["id"] as? Int, id > 0,
              let x = data["x"] as? Double, let y = data["y"] as? Double,
              let w = data["width"] as? Double, let h = data["height"] as? Double,
              [x, y, w, h].allSatisfy({ $0.isFinite }), w >= 28, h >= 28,
              let label = data["label"] as? String, !label.isEmpty, label.count <= 160 else { return nil }
        guard let rect = viewport.rect(x: x, y: y, width: w, height: h) else { return nil }
        self.id = id; self.rect = rect; self.label = label
        text = String((data["text"] as? String ?? "").prefix(40))
        symbol = String((data["symbol"] as? String ?? "").prefix(40))
        disabled = data["disabled"] as? Bool ?? false
        let font = data["font"] as? Double ?? 17
        fontSize = (font.isFinite ? min(96, max(12, font)) : 17) * viewport.scale
        family = String((data["family"] as? String ?? "").prefix(80))
        let rounding = data["radius"] as? Double ?? 0
        radius = (rounding.isFinite ? min(100, max(0, rounding)) : 0) * viewport.scale
        color = data["color"] as? String ?? ""
        selected = data["selected"] as? Bool ?? false
        showsText = data["showsText"] as? Bool ?? false
    }

    var typeface: Font {
        let name = family.lowercased()
        if name.contains("mono") { return .system(size: fontSize, design: .monospaced) }
        if name.contains("rounded") { return .system(size: fontSize, design: .rounded) }
        if name == "ui-serif" || name.contains("new york") { return .system(size: fontSize, design: .serif) }
        if let font = UIFont(name: family, size: fontSize) { return Font(font) }
        return .system(size: fontSize)
    }

    var foreground: Color {
        let values = color.replacingOccurrences(of: "rgba(", with: "").replacingOccurrences(of: "rgb(", with: "")
            .replacingOccurrences(of: ")", with: "").split(separator: ",").compactMap { Double($0.trimmingCharacters(in: .whitespaces)) }
        guard values.count >= 3, values.prefix(3).allSatisfy({ $0.isFinite }) else { return .primary }
        return Color(red: min(255, max(0, values[0])) / 255,
                     green: min(255, max(0, values[1])) / 255, blue: min(255, max(0, values[2])) / 255)
    }
}

@available(iOS 26.0, *) @Observable
private final class GlassControlsModel {
    var controls: [GlassControl] = []
    var revision = 0
    var session = ""
    var dark = false
    var reduceMotion = false
}

@available(iOS 26.0, *)
private struct GlassControlsView: View {
    let model: GlassControlsModel
    let activate: (Int, Int, String) -> Void
    @Environment(\.accessibilityReduceMotion) private var systemReduceMotion

    var body: some View {
        let revision = model.revision, session = model.session
        GlassEffectContainer(spacing: 4) {
            ZStack(alignment: .topLeading) {
                ForEach(model.controls) { control in
                    Button { activate(control.id, revision, session) } label: {
                        Group {
                            if control.symbol.isEmpty { Text(control.text.isEmpty ? control.label : control.text) }
                            else if control.showsText {
                                VStack(spacing: 3) {
                                    Image(systemName: control.symbol).accessibilityHidden(true)
                                    Text(control.text.isEmpty ? control.label : control.text).lineLimit(1)
                                }
                            } else { Image(systemName: control.symbol).accessibilityHidden(true) }
                        }
                        .font(control.typeface)
                        .foregroundStyle(control.foreground)
                        .frame(width: control.rect.width, height: control.rect.height)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .glassEffect(.regular.interactive(!systemReduceMotion && !model.reduceMotion),
                                 in: RoundedRectangle(cornerRadius: control.radius))
                    .disabled(control.disabled)
                    .accessibilityLabel(control.label)
                    .accessibilityAddTraits(control.selected ? .isSelected : [])
                    .offset(x: control.rect.minX, y: control.rect.minY)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
        .environment(\.colorScheme, model.dark ? .dark : .light)
        .transaction { if systemReduceMotion || model.reduceMotion { $0.disablesAnimations = true } }
        .ignoresSafeArea()
    }
}

@available(iOS 26.0, *)
private final class GlassPassthroughView: UIView {
    var controlRects: [CGRect] = []
    override func point(inside point: CGPoint, with event: UIEvent?) -> Bool {
        !isHidden && controlRects.contains { $0.contains(point) }
    }
}

@available(iOS 26.0, *) @MainActor
private final class GlassCoordinator: NSObject, WKScriptMessageHandler {
    private weak var webView: WKWebView?
    private let model = GlassControlsModel()
    private let overlay = GlassPassthroughView()
    private var host: UIHostingController<GlassControlsView>?
    private var observers: [NSObjectProtocol] = []
    private var enabled = false

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(self, name: "tgNativeGlass")
        for name in [UIAccessibility.reduceTransparencyStatusDidChangeNotification,
                     UIAccessibility.reduceMotionStatusDidChangeNotification,
                     UIAccessibility.voiceOverStatusDidChangeNotification,
                     UIApplication.didBecomeActiveNotification] {
            observers.append(NotificationCenter.default.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { self?.environmentChanged() }
            })
        }
        // Extra iPad/Mac windows have their own lifecycle while the app remains
        // active. Do not keep a hidden scene's hosting tree or glass renderer.
        for name in [UIScene.willDeactivateNotification, UIScene.didEnterBackgroundNotification, UIScene.didActivateNotification] {
            observers.append(NotificationCenter.default.addObserver(forName: name, object: nil, queue: .main) { [weak self] notification in
                MainActor.assumeIsolated {
                    guard let self, let scene = notification.object as? UIScene,
                          scene === self.webView?.window?.windowScene else { return }
                    if name == UIScene.didActivateNotification { self.environmentChanged() }
                    else { self.clear() }
                }
            })
        }
        observers.append(NotificationCenter.default.addObserver(forName: UIApplication.willResignActiveNotification,
            object: nil, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { self?.clear() }
            })
    }

    deinit { for token in observers { NotificationCenter.default.removeObserver(token) } }

    private func installOverlay() -> Bool {
        if host != nil { return true }
        guard let webView, let parent = webView.superview else { return false }
        var responder: UIResponder? = webView
        while responder != nil && !(responder is UIViewController) { responder = responder?.next }
        guard let controller = responder as? UIViewController else { return false }
        let host = UIHostingController(rootView: GlassControlsView(model: model) { [weak self] id, revision, session in
            self?.activate(id, revision: revision, session: session)
        })
        host.safeAreaRegions = []
        host.view.backgroundColor = .clear
        host.view.isOpaque = false
        host.view.translatesAutoresizingMaskIntoConstraints = false
        overlay.backgroundColor = .clear
        overlay.translatesAutoresizingMaskIntoConstraints = false
        controller.addChild(host)
        parent.addSubview(overlay)
        overlay.addSubview(host.view)
        NSLayoutConstraint.activate([
            overlay.leadingAnchor.constraint(equalTo: webView.leadingAnchor), overlay.trailingAnchor.constraint(equalTo: webView.trailingAnchor),
            overlay.topAnchor.constraint(equalTo: webView.topAnchor), overlay.bottomAnchor.constraint(equalTo: webView.bottomAnchor),
            host.view.leadingAnchor.constraint(equalTo: overlay.leadingAnchor), host.view.trailingAnchor.constraint(equalTo: overlay.trailingAnchor),
            host.view.topAnchor.constraint(equalTo: overlay.topAnchor), host.view.bottomAnchor.constraint(equalTo: overlay.bottomAnchor)
        ])
        host.didMove(toParent: controller)
        self.host = host
        return true
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, let webView, message.webView === webView,
              let source = message.frameInfo.request.url, source.scheme == "http", source.host == "127.0.0.1",
              source.port == webView.url?.port,
              let body = message.body as? [String: Any], let revision = body["revision"] as? Int,
              let session = body["session"] as? String, session.count == 32,
              session.allSatisfy({ $0.isHexDigit }) else { return }
        let requested = body["enabled"] as? Bool ?? false
        guard requested, !UIAccessibility.isReduceTransparencyEnabled,
              UIApplication.shared.applicationState == .active,
              webView.window?.windowScene?.activationState == .foregroundActive, installOverlay() else {
            clear(); acknowledge(revision, ids: [], session: session); return
        }
        guard let viewportData = body["viewport"] as? [String: Any],
              let viewport = TGNativeViewportGeometry(viewportData, bounds: webView.bounds) else {
            clear(); acknowledge(revision, ids: [], session: session); return
        }
        let controls = (body["controls"] as? [[String: Any]] ?? []).prefix(32).compactMap { GlassControl($0, viewport: viewport) }
        enabled = true
        model.revision = revision
        model.session = session
        model.dark = body["dark"] as? Bool ?? false
        model.reduceMotion = body["reduceMotion"] as? Bool ?? false
        if model.controls != controls { model.controls = controls }
        overlay.controlRects = controls.map(\.rect)
        overlay.isHidden = controls.isEmpty
        acknowledge(revision, ids: controls.map(\.id), session: session)
    }

    private func acknowledge(_ revision: Int, ids: [Int], session: String) {
        guard let data = try? JSONSerialization.data(withJSONObject: ids), let encoded = String(data: data, encoding: .utf8) else { return }
        let voiceOver = UIAccessibility.isVoiceOverRunning ? "true" : "false"
        webView?.evaluateJavaScript("window.tgNativeAccessibility={voiceOver:\(voiceOver)};window.tgNativeGlass?.acknowledge(\(revision),\(encoded),\"\(session)\");", completionHandler: nil)
    }

    private func activate(_ id: Int, revision: Int, session: String) {
        guard enabled, revision == model.revision, session == model.session, model.controls.contains(where: { $0.id == id && !$0.disabled }),
              UIApplication.shared.applicationState == .active,
              webView?.window?.windowScene?.activationState == .foregroundActive else { return }
        webView?.evaluateJavaScript("window.tgNativeGlass?.activate(\(id),\(revision),\"\(session)\");", completionHandler: nil)
    }

    private func clear() {
        enabled = false
        model.controls = []
        overlay.controlRects = []
        overlay.isHidden = true
        // Disabling the feature releases the hosting tree and its glass renderer.
        host?.willMove(toParent: nil)
        host?.view.removeFromSuperview()
        host?.removeFromParent()
        host = nil
        overlay.removeFromSuperview()
    }

    @objc func detach() {
        clear()
        webView?.configuration.userContentController.removeScriptMessageHandler(forName: "tgNativeGlass")
        for token in observers { NotificationCenter.default.removeObserver(token) }
        observers.removeAll()
    }

    private func environmentChanged() {
        if UIAccessibility.isReduceTransparencyEnabled { clear() }
        let voiceOver = UIAccessibility.isVoiceOverRunning ? "true" : "false"
        webView?.evaluateJavaScript("window.tgNativeGlass?.environment(\(voiceOver));", completionHandler: nil)
    }
}
