import SwiftUI

/// Watch settings: own connection (complex feature) and linking it to the
/// iPhone app's account.
struct SettingsView: View {
    @EnvironmentObject var engine: Engine
    @AppStorage("watchAccent") private var accent = ""
    @State private var busy = false
    @State private var problem: String?
    @State private var needsPassword = false
    @State private var password = ""
    @State private var matrix: [[Bool]]?
    @State private var apiID = ""
    @State private var apiHash = ""
    @State private var editingCredentials = false

    var body: some View {
        ScrollViewReader { reader in
            settings.onChange(of: matrix != nil) { _, showing in
                if showing { reader.scrollTo("login-qr", anchor: .center) }
            }
        }
    }

    private var settings: some View {
        List {
            NavigationLink(L("Logos de la app", "App logos")) { LogoSettings() }
            Picker(L("Color de realce", "Accent color"), selection: $accent) {
                Text(L("Del iPhone", "From iPhone")).tag("")
                Text(L("Azul", "Blue")).tag("#58aaff")
                Text(L("Verde", "Green")).tag("#8cf5a6")
                Text(L("Naranja", "Orange")).tag("#ffb347")
                Text(L("Rosa", "Pink")).tag("#ff9ad5")
            }
            if !Local.available {
                Text(L("La conexión propia del reloj llegará en una próxima versión. Ahora el reloj usa la sesión del iPhone.",
                       "The watch's own connection comes in a later version. For now the watch uses the iPhone's session."))
                    .font(Theme.mono(11)).foregroundStyle(Theme.muted)
            } else {
            Toggle(L("Conexión propia", "Own connection"), isOn: Binding(get: { engine.own }, set: engine.setOwnConnection))
                .disabled(busy)
                .font(Theme.mono(13))
            Text(L("El reloj se conecta a Telegram por su cuenta y funciona con el iPhone apagado.",
                   "The watch connects to Telegram by itself and works with the iPhone off."))
                .font(Theme.mono(10)).foregroundStyle(Theme.muted)
            if engine.own {
                if engine.linked {
                    Text(engine.account).font(Theme.mono(13, bold: true)).foregroundStyle(Theme.strong)
                    Button(L("Desvincular", "Unlink"), role: .destructive) {
                        busy = true
                        problem = nil
                        Task {
                            defer { busy = false }
                            do { try await engine.unlink() } catch { problem = error.localizedDescription }
                        }
                    }
                    .disabled(busy)
                } else if engine.needsCredentials || editingCredentials {
                    Text(L("Credenciales de Telegram", "Telegram API credentials")).font(Theme.mono(13, bold: true))
                    Text(L("Obtén el API ID y el API hash de tu aplicación en my.telegram.org.",
                           "Get your application’s API ID and API hash from my.telegram.org.")).font(Theme.mono(10))
                    TextField("API ID", text: $apiID)
                    SecureField("API hash", text: $apiHash)
                    Button(L("Guardar en este dispositivo", "Save on this device")) {
                        busy = true
                        problem = nil
                        Task {
                            defer { busy = false }
                            do {
                                try await engine.saveCredentials(id: apiID, hash: apiHash)
                                apiHash = ""
                                apiID = ""
                                editingCredentials = false
                            } catch { problem = error.localizedDescription }
                        }
                    }
                    .disabled(busy || apiID.isEmpty || apiHash.isEmpty)
                } else if needsPassword {
                    SecureField(L("Contraseña", "Password"), text: $password).font(Theme.mono(13))
                    Button(L("Continuar", "Continue")) {
                        busy = true
                        problem = nil
                        Task {
                            defer { busy = false; password = "" }
                            do { try await engine.password(password); needsPassword = false } catch { problem = error.localizedDescription }
                        }
                    }
                    .disabled(busy || password.isEmpty)
                } else {
                    if let matrix {
                        Canvas { context, size in
                            let count = matrix.count
                            let cell = floor(min(size.width, size.height) / CGFloat(count))
                            let offset = CGPoint(x: (size.width - cell * CGFloat(count)) / 2,
                                                 y: (size.height - cell * CGFloat(count)) / 2)
                            var dark = Path()
                            for (y, row) in matrix.enumerated() {
                                for (x, marked) in row.enumerated() where marked {
                                    dark.addRect(CGRect(x: offset.x + CGFloat(x) * cell,
                                                        y: offset.y + CGFloat(y) * cell,
                                                        width: cell, height: cell))
                                }
                            }
                            context.fill(dark, with: .color(.black))
                        }
                        .aspectRatio(1, contentMode: .fit)
                        .background(.white)
                        .accessibilityLabel(L("Código QR de inicio de sesión", "Sign-in QR code"))
                        .id("login-qr")
                        Text(L("En Telegram, abre Ajustes, Dispositivos y Vincular dispositivo para escanear el código.",
                               "In Telegram, open Settings, Devices, and Link Desktop Device to scan the code."))
                            .font(Theme.mono(10))
                    }
                    if engine.personalAPI == true {
                        Button(L("Editar credenciales", "Edit credentials")) {
                            editingCredentials = true
                            problem = nil
                        }
                        .disabled(busy)
                    }
                    Button(L("Mostrar código QR", "Show QR code")) { beginLink(scannable: true) }
                        .disabled(busy)
                    Button(L("Vincular con el iPhone", "Link with the iPhone")) { beginLink(scannable: false) }
                        .disabled(busy)
                }
            }
            }
            if let problem {
                Text(problem).font(Theme.mono(10)).foregroundStyle(Theme.muted)
            }
        }
        .onDisappear { apiHash = ""; apiID = "" }
        .navigationTitle(L("Ajustes", "Settings"))
        .task { await engine.refresh() }
    }

    private func beginLink(scannable: Bool) {
        busy = true
        problem = nil
        Task {
            defer { busy = false; matrix = nil }
            do {
                let display: (([[Bool]]) -> Void)? = scannable ? { matrix = $0 } : nil
                let state = try await engine.link(showCode: display)
                needsPassword = state == "password"
                if state == "expired" {
                    problem = L("El código ha caducado. Genera otro.", "The code expired. Generate another one.")
                }
            } catch {
                problem = error.localizedDescription
            }
        }
    }
}
