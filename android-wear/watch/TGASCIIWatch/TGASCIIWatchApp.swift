// TG-ASCII for Apple Watch: a companion of the iPhone app. Telegram runs in the
// iPhone app's Python core (watchOS does not allow the TCP connections Telegram
// needs); the watch asks it for chats and messages over WatchConnectivity.
import SwiftUI

@main
struct TGASCIIWatchApp: App {
    @AppStorage("watchAccent") private var accent = ""
    @StateObject private var phone = Phone.shared
    @StateObject private var engine = Engine.shared
    @StateObject private var appearance = Appearance.shared

    var body: some Scene {
        WindowGroup {
            NavigationStack {
                ChatListView()
            }
            .environmentObject(phone)
            .environmentObject(engine)
            .environmentObject(appearance)
            .tint(accent.isEmpty ? Theme.strong : Color(hex: accent))
            .id(appearance.style)  // redraw when the phone's theme changes
            // The phone's «Disable all animations»: screens change without motion.
            .transaction { transaction in
                if appearance.look.reduce_animations == true {
                    transaction.animation = nil
                    transaction.disablesAnimations = true
                }
            }
            .task { await appearance.refresh() }
        }
    }
}

/// The phone app's look (theme colours, text size, bold / italic, typeface),
/// asked for over WatchConnectivity and kept for when the phone is away.
struct Look: Codable, Hashable {
    var bg = "#08100c", panel = "#0e1b13", text = "#8cf5a6", muted = "#80a98c", strong = "#bdffcd"
    var brand_logo: LogoChoice?
    var name: String?
    var photo_previews: Bool?
    var scale = 1.0, bold = false, italic = false, font = "", bubbles = false
    var reduce_animations: Bool?  // absent when the phone app is older
}

@MainActor final class Appearance: ObservableObject {
    static let shared = Appearance()
    @Published var look: Look

    var style: Look {
        var style = look
        style.brand_logo = nil
        return style
    }

    private init() {
        if let data = UserDefaults.standard.data(forKey: "look"), let saved = try? JSONDecoder().decode(Look.self, from: data) {
            look = saved
        } else {
            look = Look()
        }
    }

    /// Ask the phone again (at start and when the chat list is refreshed).
    func refresh() async {
        guard let fresh = try? await Phone.shared.request(["op": "appearance"], as: Look.self), fresh != look else { return }
        look = fresh
        if let data = try? JSONEncoder().encode(fresh) { UserDefaults.standard.set(data, forKey: "look") }
    }
}

extension Color {
    init(hex: String) {
        let value = UInt64(hex.dropFirst(), radix: 16) ?? 0
        self.init(red: Double((value >> 16) & 0xFF) / 255, green: Double((value >> 8) & 0xFF) / 255, blue: Double(value & 0xFF) / 255)
    }
}

enum Theme {
    @MainActor static var look: Look { Appearance.shared.look }
    @MainActor static var background: Color { Color(hex: look.bg) }
    @MainActor static var panel: Color { Color(hex: look.panel) }
    @MainActor static var text: Color { Color(hex: look.text) }
    @MainActor static var muted: Color { Color(hex: look.muted) }
    @MainActor static var strong: Color { Color(hex: UserDefaults.standard.string(forKey: "watchAccent").flatMap { $0.isEmpty ? nil : $0 } ?? look.strong) }
    @MainActor static func mono(_ size: CGFloat, bold: Bool = false) -> Font {
        typeface(look.font, size: size * CGFloat(look.scale), bold: bold || look.bold, italic: look.italic)
    }

    /// 3.2: every phone typeface on watchOS, with Apple's own faces. The
    /// system design is SF Compact on Apple Watch; rounded, monospaced and
    /// serif are SF Compact Rounded, SF Mono and New York.
    static func typeface(_ key: String, size: CGFloat, bold: Bool, italic: Bool) -> Font {
        var weight: Font.Weight = bold ? .bold : .regular
        var design: Font.Design = .monospaced
        var condensed = false
        switch key {
        case "sans", "system", "sf", "sf_compact", "humanist", "smallcaps": design = .default
        case "rounded", "sf_rounded", "casual": design = .rounded
        case "serif", "classic", "book", "new_york", "noto_serif", "handwriting": design = .serif
        case "light": design = .default; weight = bold ? .semibold : .light
        case "medium": design = .default; weight = bold ? .heavy : .medium
        case "condensed": design = .default; condensed = true
        default: design = .monospaced  // "", courier, mono, sf_mono, typewriter: the ASCII look.
        }
        var font = Font.system(size: size, weight: weight, design: design)
        if condensed { font = font.width(.condensed) }
        if italic || key == "handwriting" { font = font.italic() }
        return font
    }
}
