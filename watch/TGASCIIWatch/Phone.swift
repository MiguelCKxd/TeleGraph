import Foundation
import WatchConnectivity

struct ChatItem: Identifiable, Decodable, Hashable {
    let id: Int64
    let name: String
    let unread: Int
    var pinned: Bool? = nil
    let preview: String
    let kind: String?
    var forum: Bool? = nil
    var has_link: Bool? = nil
    var account: String? = nil

    func request(_ operation: String, topic: WatchTopic? = nil, parameters: [String: Any] = [:]) -> [String: Any] {
        var request = parameters
        request["op"] = operation
        if request["peer"] == nil { request["peer"] = id }
        if let account { request["account"] = account }
        if let topic { request["topic_id"] = topic.id }
        return request
    }
}

struct WatchLinkedChat: Decodable { let chat: ChatItem? }

struct WatchTopic: Identifiable, Decodable {
    let id: Int64
    let title: String
    let unread_count: Int
    let closed: Bool
    let can_send: Bool
}

struct WatchTopicCursor: Decodable {
    let peer: Int64
    let query: String
    let owner: String
    let seen: Int
    let pinned: [Int64]
    let offset_date: Int
    let offset_id: Int
    let offset_topic: Int
    var request: [String: Any] {
        ["peer": peer, "query": query, "owner": owner, "seen": seen, "pinned": pinned,
         "offset_date": offset_date, "offset_id": offset_id, "offset_topic": offset_topic]
    }
}

struct WatchTopicPage: Decodable {
    let topics: [WatchTopic]
    let next_cursor: WatchTopicCursor?
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
    var sender_id: Int64?
    var date: Double?
    var edited_at: Double?
    var read: Bool?
    var color: Int?

    func joins(_ other: Self?) -> Bool {
        guard let other, let sender_id, sender_id == other.sender_id, out == other.out,
              let date, let before = other.date, abs(date - before) <= 900 else { return false }
        return Calendar.current.isDate(Date(timeIntervalSince1970: date), inSameDayAs: Date(timeIntervalSince1970: before))
    }
}

struct WatchReadDetails: Decodable {
    struct Reader: Decodable { let date: Double }
    let read: String?
    let timestamp: Double?
    let readers: [Reader]?
}

struct SenderPortrait: Decodable { let image: Data? }

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
