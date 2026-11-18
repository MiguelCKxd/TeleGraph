import Foundation
import WatchConnectivity

struct ChatItem: Identifiable, Decodable, Hashable {
    let id: Int64
    let name: String
    let unread: Int
    let preview: String
    let kind: String?
}

struct SecretInfoItem: Decodable {
    let layer: Int?
    let ttl: Int?
    let fingerprint_hex: String?
    let fingerprint_emojis: [String]?
}

struct MessageItem: Identifiable, Decodable, Hashable {
    let id: Int64
    let sender: String
    let text: String
    let time: String
    let out: Bool
    let translatable: Bool?
}

enum PhoneError: LocalizedError {
    case unreachable, failed(String)
    var errorDescription: String? {
        switch self {
        case .unreachable: return L("Abre TeleGraph en el iPhone.", "Open TeleGraph on your iPhone.")
        case .failed(let text): return text
        }
    }
}

/// Requests to the iPhone app: {"json": "<request>"} -> {"json": "<answer>"}.
final class Phone: NSObject, ObservableObject, WCSessionDelegate {
    static let shared = Phone()
    @Published var reachable = false

    override init() {
        super.init()
        if WCSession.isSupported() {
            WCSession.default.delegate = self
            WCSession.default.activate()
        }
    }

    func request<T: Decodable>(_ body: [String: Any], as type: T.Type) async throws -> T {
        let session = WCSession.default
        guard session.activationState == .activated, session.isReachable else { throw PhoneError.unreachable }
        let payload = String(data: try JSONSerialization.data(withJSONObject: body), encoding: .utf8) ?? "{}"
        let reply: [String: Any] = try await withCheckedThrowingContinuation { continuation in
            session.sendMessage(["json": payload], replyHandler: { continuation.resume(returning: $0) },
                                errorHandler: { continuation.resume(throwing: $0) })
        }
        guard let text = reply["json"] as? String, let data = text.data(using: .utf8) else { throw PhoneError.failed("?") }
        if let failure = try? JSONDecoder().decode([String: String].self, from: data), let message = failure["error"] {
            throw PhoneError.failed(message)
        }
        return try JSONDecoder().decode(T.self, from: data)
    }

    func session(_ session: WCSession, activationDidCompleteWith state: WCSessionActivationState, error: Error?) {
        DispatchQueue.main.async { self.reachable = session.isReachable }
    }

    func sessionReachabilityDidChange(_ session: WCSession) {
        DispatchQueue.main.async { self.reachable = session.isReachable }
    }
}
