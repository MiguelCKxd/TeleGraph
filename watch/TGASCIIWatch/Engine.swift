import Foundation
import SwiftUI

/// Texts in Spanish or English (the watch follows the device language).
func L(_ es: String, _ en: String) -> String {
    (Locale.current.language.languageCode?.identifier == "es") ? es : en
}

/// The watch's own Telegram connection: Python + Telethon inside the watch app
/// (PythonBridge.c, tgwatch). Works with the iPhone off.
final class Local: @unchecked Sendable {
    static let shared = Local()
    /// The Python sources are only embedded in some builds (WATCH_PYTHON=1).
    static var available: Bool {
        FileManager.default.fileExists(atPath: (Bundle.main.resourcePath ?? "") + "/app/tgwatch")
    }
    private let queue = DispatchQueue(label: "tgwatch", qos: .userInitiated)
    private var started = false  // Accessed only on queue.

    private func start() -> Bool {
        if started { return true }
        setenv("TGW_TRANSPORT", "http", 1)  // HTTPS: watchOS allows WebSockets only while streaming audio
        let folder = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("tgwatch").path
        try? FileManager.default.createDirectory(atPath: folder, withIntermediateDirectories: true)
        started = tgw_start(Bundle.main.resourcePath ?? "", folder) == 1
        return started
    }

    func request<T: Decodable>(_ body: [String: Any], as type: T.Type) async throws -> T {
        let payload = String(data: try JSONSerialization.data(withJSONObject: body), encoding: .utf8) ?? "{}"
        let text: String = try await withCheckedThrowingContinuation { continuation in
            queue.async {
                guard self.start() else {
                    continuation.resume(throwing: PhoneError.failed("Python"))
                    return
                }
                guard let answer = tgw_request(payload) else {
                    continuation.resume(throwing: PhoneError.failed("Python"))
                    return
                }
                let text = String(cString: answer)
                tgw_free(answer)
                continuation.resume(returning: text)
            }
        }
        let data = Data(text.utf8)
        if let failure = try? JSONDecoder().decode([String: String].self, from: data), let message = failure["error"] {
            throw PhoneError.failed(message)
        }
        return try JSONDecoder().decode(T.self, from: data)
    }
}

struct LocalStatus: Decodable { let authorized: Bool; let name: String }
struct LoginStart: Decodable { let url: String; let authorized: Bool?; let matrix: [[Bool]]? }
struct LoginState: Decodable { let state: String }
struct WatchConfig: Decodable { let own: Bool }

/// Where chats come from: the iPhone app (linked, default) or the watch's own
/// connection (complex feature, chosen on the iPhone or here).
@MainActor
final class Engine: ObservableObject {
    static let shared = Engine()
    @Published private(set) var own = UserDefaults.standard.bool(forKey: "ownConnection") {
        didSet { UserDefaults.standard.set(own, forKey: "ownConnection") }
    }
    @Published var linked = false        // own connection signed in
    @Published var account = ""

    func request<T: Decodable>(_ body: [String: Any], as type: T.Type) async throws -> T {
        let local = own
        let result: T
        if local {
            guard linked && Local.available else {
                throw PhoneError.failed(L("Vincula la cuenta del reloj en Ajustes.", "Link the watch account in Settings."))
            }
            result = try await Local.shared.request(body, as: type)
        } else {
            result = try await Phone.shared.request(body, as: type)
        }
        guard own == local else {
            throw PhoneError.failed(L("La conexión ha cambiado.", "The connection changed."))
        }
        return result
    }

    func setOwnConnection(_ enabled: Bool) {
        UserDefaults.standard.set(true, forKey: "ownConnectionSetOnWatch")
        own = enabled
        if !enabled {
            linked = false
            account = ""
        }
        Task { await refreshLocal() }
    }

    /// An explicit selection on the watch takes precedence over the phone's setting.
    func refresh() async {
        if !UserDefaults.standard.bool(forKey: "ownConnectionSetOnWatch"),
           let config = try? await Phone.shared.request(["op": "config"], as: WatchConfig.self),
           !UserDefaults.standard.bool(forKey: "ownConnectionSetOnWatch") {
            own = config.own
        }
        await refreshLocal()
    }

    private func refreshLocal() async {
        guard own, Local.available else { linked = false; account = ""; return }
        if let status = try? await Local.shared.request(["op": "status"], as: LocalStatus.self), own {
            linked = status.authorized
            account = status.name
        }
    }

    /// Sign the watch in using a scan or approval from the linked iPhone.
    private var linking = false

    func link(showCode: (([[Bool]]) -> Void)? = nil) async throws -> String {
        // One link at a time (a second tap must not start another login).
        if linking { return "busy" }
        linking = true
        defer { linking = false }
        let start = try await Local.shared.request(["op": "login_start", "matrix": showCode != nil], as: LoginStart.self)
        if start.authorized == true { await refreshLocal(); return "ready" }
        if let showCode {
            guard let matrix = start.matrix, !matrix.isEmpty else { throw PhoneError.failed("QR") }
            showCode(matrix)
        } else {
            _ = try await Phone.shared.request(["op": "approve_login", "url": start.url], as: [String: AnyDecodable].self)
        }
        let state = try await Local.shared.request(["op": "login_wait", "timeout": showCode == nil ? 70 : 45], as: LoginState.self)
        if state.state == "ready" { await refreshLocal() }
        return state.state
    }

    func password(_ value: String) async throws {
        _ = try await Local.shared.request(["op": "password", "password": value], as: LoginState.self)
        await refreshLocal()
    }

    func unlink() async throws {
        let result = try await Local.shared.request(["op": "logout"], as: [String: Bool].self)
        guard result["ok"] == true else {
            throw PhoneError.failed(L("No se pudo cerrar la sesión.", "Could not sign out."))
        }
        linked = false
        account = ""
    }
}

/// Decodes any JSON value (answers whose content is not needed).
struct AnyDecodable: Decodable {
    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { return }
        if (try? container.decode(Bool.self)) != nil { return }
        if (try? container.decode(Double.self)) != nil { return }
        if (try? container.decode(String.self)) != nil { return }
        if (try? container.decode([String: AnyDecodable].self)) != nil { return }
        _ = try container.decode([AnyDecodable].self)
    }
}
