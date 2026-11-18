import SwiftUI

struct LogoChoice: Codable, Hashable {
    var variant = "title-short"
    var color = "default"
    var theme = "dark"

    static func restore(_ data: Data) -> Self? {
        try? JSONDecoder().decode(Self.self, from: data)
    }
}

struct LogoMark: View {
    let choice: LogoChoice

    var body: some View {
        Canvas { context, size in
            let mark = LogoVariants.options.first { $0.id == choice.variant } ?? LogoVariants.options[0]
            let palette = LogoVariants.palettes["\(choice.color)-\(choice.theme)"] ?? LogoVariants.palettes["default-dark"]!
            let extent = size.width * (824.0 / 1024)
            let inset = (size.width - extent) / 2
            let badge = RoundedRectangle(cornerRadius: extent / 4, style: .continuous)
                .path(in: CGRect(x: inset, y: inset, width: extent, height: extent))
            context.fill(badge, with: .color(Color(hex: palette.background)))
            let unit = extent / 1024
            let coords = mark.ink.split(separator: " ").compactMap { Int($0) }
            var pixels = Path()
            for i in stride(from: 0, to: coords.count, by: 4) {
                pixels.addRect(CGRect(x: inset + CGFloat(coords[i]) * unit, y: inset + CGFloat(coords[i+1]) * unit,
                                      width: CGFloat(coords[i+2]-coords[i]) * unit,
                                      height: CGFloat(coords[i+3]-coords[i+1]) * unit))
            }
            context.fill(pixels, with: .color(Color(hex: palette.foreground)))
        }
    }
}

struct WatchLogo: View {
    @EnvironmentObject private var appearance: Appearance
    @AppStorage("watchLogoOverride") private var saved = Data()

    var body: some View {
        let logo = LogoChoice.restore(saved) ?? appearance.look.brand_logo ?? LogoChoice()
        LogoMark(choice: logo)
            .frame(width: 48, height: 48)
            .frame(maxWidth: .infinity).accessibilityHidden(true)
    }
}

struct LogoSettings: View {
    @EnvironmentObject private var appearance: Appearance
    @AppStorage("watchLogoOverride") private var saved = Data()
    @State private var usePhone = true
    @State private var choice = LogoChoice()
    private let colors = [
        ("default", L("Predeterminado", "Default")),
        ("light", L("Claro", "Light")),
        ("orange", L("Naranja", "Orange")),
        ("blue", L("Azul", "Blue")),
        ("red", L("Rojo", "Red")),
        ("pink", L("Rosa", "Pink")),
    ]

    var body: some View {
        List {
            let preview = usePhone ? appearance.look.brand_logo ?? LogoChoice() : choice
            LogoMark(choice: preview)
                .frame(width: 64, height: 64)
                .frame(maxWidth: .infinity).accessibilityHidden(true)
            Toggle(L("Usar logo del iPhone", "Use iPhone logo"), isOn: $usePhone)
            if !usePhone {
                Picker(L("Diseño", "Design"), selection: $choice.variant) {
                    ForEach(LogoVariants.options, id: \.id) { option in
                        Text(option.title).tag(option.id)
                    }
                }
                Picker(L("Color", "Color"), selection: $choice.color) {
                    ForEach(colors, id: \.0) { color in Text(color.1).tag(color.0) }
                }
                Picker(L("Tema", "Theme"), selection: $choice.theme) {
                    Text(L("Oscuro", "Dark")).tag("dark")
                    Text(L("Claro", "Light")).tag("light")
                }
            }
            Button(L("Aplicar", "Apply")) {
                saved = usePhone ? Data() : (try? JSONEncoder().encode(choice)) ?? Data()
            }
        }
        .navigationTitle(L("Logos", "Logos"))
        .onAppear {
            let stored = LogoChoice.restore(saved)
            usePhone = stored == nil
            choice = stored ?? appearance.look.brand_logo ?? LogoChoice()
        }
    }
}
