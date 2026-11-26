import UIKit
import WebKit

// System dialogs keep native keyboard, accessibility and iPad presentation.
// UIKit adopts the system's material and Reduce Transparency automatically.
@objc(TGNativeDialogs) public final class TGNativeDialogs: NSObject {
    @MainActor @objc(presentFromWebView:request:completion:)
    public static func present(from webView: WKWebView, request: NSDictionary,
                               completion: @escaping (NSDictionary) -> Void) -> NSObject? {
        var responder: UIResponder? = webView
        while responder != nil && !(responder is UIViewController) { responder = responder?.next }
        guard let controller = responder as? UIViewController, let window = webView.window,
              window.windowScene?.activationState == .foregroundActive,
              controller.presentedViewController == nil, !controller.isBeingDismissed else { return nil }
        let session = NativeDialogSession(webView: webView, request: request, completion: completion)
        guard session.present(from: controller) else { return nil }
        return session
    }
}

@MainActor private final class NativeDialogSession: NSObject, UITextFieldDelegate {
    private weak var webView: WKWebView?
    private let request: NSDictionary
    private var completion: ((NSDictionary) -> Void)?
    private var alert: UIAlertController?
    private var observer: NSObjectProtocol?
    private var maximum = 4096
    private var animated: Bool { !UIAccessibility.isReduceMotionEnabled && !(request["reduce_motion"] as? Bool ?? false) }

    init(webView: WKWebView, request: NSDictionary, completion: @escaping (NSDictionary) -> Void) {
        self.webView = webView; self.request = request; self.completion = completion
        super.init()
    }

    func present(from controller: UIViewController) -> Bool {
        guard let kind = request["kind"] as? String, ["confirm", "menu", "prompt"].contains(kind),
              let title = request["title"] as? String, title.count <= 4096,
              let actions = request["actions"] as? [[String: Any]], !actions.isEmpty, actions.count <= 32,
              let cancel = request["cancel"] as? String else { return false }
        let alert = UIAlertController(title: title, message: request["message"] as? String,
                                      preferredStyle: kind == "menu" ? .actionSheet : .alert)
        self.alert = alert
        if kind == "prompt" {
            maximum = min(4096, max(1, request["maxlength"] as? Int ?? 4096))
            alert.addTextField { [weak self] field in
                guard let self else { return }
                field.delegate = self
                field.text = self.request["value"] as? String ?? ""
                field.placeholder = self.request["placeholder"] as? String
                field.isSecureTextEntry = self.request["input_type"] as? String == "password"
                switch self.request["input_type"] as? String {
                case "email": field.keyboardType = .emailAddress; field.autocapitalizationType = .none
                case "url": field.keyboardType = .URL; field.autocapitalizationType = .none
                case "tel": field.keyboardType = .phonePad
                default: break
                }
            }
        }
        for (index, action) in actions.enumerated() {
            guard let label = action["label"] as? String else { return false }
            alert.addAction(UIAlertAction(title: label, style: action["destructive"] as? Bool == true ? .destructive : .default) { [weak self] _ in
                guard let self else { return }
                var result: [String: Any] = ["handled": true, "cancelled": false, "index": index]
                if kind == "prompt" { result["text"] = self.alert?.textFields?.first?.text ?? "" }
                self.finish(result)
            })
        }
        alert.addAction(UIAlertAction(title: cancel, style: .cancel) { [weak self] _ in self?.finish(["handled": true, "cancelled": true]) })
        if let popover = alert.popoverPresentationController, let webView {
            popover.sourceView = webView
            popover.sourceRect = CGRect(x: webView.bounds.midX, y: webView.bounds.midY, width: 1, height: 1)
            popover.permittedArrowDirections = []
        }
        // UIAlertController owns its presentation delegate. Replacing it is
        // rejected by UIKit for alert-style dialogs (including text prompts).
        // The native cancel action also handles an action sheet's outside tap.
        observer = NotificationCenter.default.addObserver(forName: UIScene.willDeactivateNotification, object: webView?.window?.windowScene, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.cancel() }
        }
        controller.present(alert, animated: animated)
        return true
    }

    private func finish(_ result: [String: Any]) {
        guard let callback = completion else { return }
        completion = nil
        if let observer { NotificationCenter.default.removeObserver(observer) }
        observer = nil
        // Chain a following dialog after this presentation has disappeared.
        if let alert, alert.presentingViewController != nil {
            alert.dismiss(animated: animated) { callback(result as NSDictionary) }
        } else { callback(result as NSDictionary) }
        alert = nil
    }

    @objc func cancel() { finish(["handled": true, "cancelled": true]) }
    func textField(_ textField: UITextField, shouldChangeCharactersIn range: NSRange, replacementString string: String) -> Bool {
        guard let text = textField.text, let swiftRange = Range(range, in: text) else { return false }
        return text.replacingCharacters(in: swiftRange, with: string).utf16.count <= maximum
    }
    deinit { if let observer { NotificationCenter.default.removeObserver(observer) } }
}
