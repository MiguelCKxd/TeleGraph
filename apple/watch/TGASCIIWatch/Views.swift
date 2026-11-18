import SwiftUI

struct ChatListView: View {
    @EnvironmentObject var phone: Phone
    @EnvironmentObject var engine: Engine
    @State private var chats: [ChatItem] = []
    @State private var problem: String?
    @State private var loading = true

    var body: some View {
        List {
            WatchLogo()
                .listRowBackground(Color.clear)
            if let problem {
                Text(problem).font(Theme.mono(13)).foregroundStyle(Theme.muted)
                Button("↻") { Task { await load() } }.font(Theme.mono(15))
            } else if loading && chats.isEmpty {
                ProgressView()
            }
            ForEach(chats) { chat in
                NavigationLink(value: chat) {
                    VStack(alignment: .leading, spacing: 2) {
                        HStack {
                            Text(chat.name).font(Theme.mono(14, bold: true)).foregroundStyle(Theme.strong).lineLimit(1)
                            if chat.unread > 0 {
                                Spacer(minLength: 2)
                                Text("\(chat.unread)").font(Theme.mono(11, bold: true))
                                    .foregroundStyle(Theme.background).padding(.horizontal, 4).background(Theme.text)
                            }
                        }
                        if !chat.preview.isEmpty {
                            Text(chat.preview).font(Theme.mono(11)).foregroundStyle(Theme.muted).lineLimit(2)
                        }
                    }
                }
                .listRowBackground(Theme.panel)
            }
        }
        .navigationTitle("TeleGraph")
        .navigationDestination(for: ChatItem.self) { ChatView(chat: $0) }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                NavigationLink { SettingsView() } label: { Image(systemName: "gearshape") }
            }
        }
        .task { await engine.refresh(); await load() }
        .refreshable { await load() }
        .onChange(of: phone.reachable) { _, reachable in if reachable && !engine.own { Task { await load() } } }
        .onChange(of: engine.own) { _, _ in
            chats = []
            problem = nil
            Task { await load() }
        }
        .onChange(of: engine.linked) { _, _ in
            guard engine.own else { return }
            chats = []
            problem = nil
            Task { await load() }
        }
    }

    func load() async {
        loading = true
        defer { loading = false }
        do {
            chats = try await engine.request(["op": "chats"], as: [ChatItem].self)
            problem = nil
            await Appearance.shared.refresh()
        } catch {
            problem = error.localizedDescription
        }
    }
}

struct ChatView: View {
    @Environment(\.locale) private var locale
    @EnvironmentObject var phone: Phone
    @EnvironmentObject var engine: Engine
    let chat: ChatItem
    @State private var messages: [MessageItem] = []
    @State private var draft = ""
    @State private var problem: String?
    @State private var translations: [String: String] = [:]
    @State private var translating = false
    @State private var secretInfo: SecretInfoItem?
    @State private var showingSecret = false
    private let quick = ["👍", "❤️", "😂", "OK", "¿?"]
    private var isSecret: Bool { chat.kind == "secret" || chat.id < -2_000_000_000_000 }

    var body: some View {
        ScrollViewReader { proxy in
            List {
                if isSecret {
                    Button("🔒 " + L("Clave y autodestrucción", "Encryption key & TTL")) {
                        Task { await loadSecretInfo() }
                    }
                    .font(Theme.mono(11, bold: true))
                } else if chat.kind == "user" {
                    Button("🔒 " + L("Iniciar chat secreto", "Start secret chat")) {
                        Task { await startSecret() }
                    }
                    .font(Theme.mono(11))
                }
                if showingSecret, let info = secretInfo {
                    VStack(alignment: .center, spacing: 3) {
                        Text((info.fingerprint_emojis ?? ["🔒"]).joined(separator: "  "))
                            .font(.system(size: 16))
                        if let hex = info.fingerprint_hex, !hex.isEmpty {
                            Text(hex).font(Theme.mono(9)).foregroundStyle(Theme.muted)
                        }
                        Text("Layer \(info.layer ?? 144) · TTL \(info.ttl ?? 0)s")
                            .font(Theme.mono(10)).foregroundStyle(Theme.muted)
                        HStack {
                            ForEach([0, 30, 60, 3600], id: \.self) { sec in
                                Button(sec == 0 ? "Off" : (sec < 60 ? "\(sec)s" : (sec < 3600 ? "1m" : "1h"))) {
                                    Task { await setSecretTTL(sec) }
                                }.font(Theme.mono(10))
                            }
                        }
                    }
                    .listRowBackground(Theme.panel)
                }
                ForEach(messages) { message in
                    VStack(alignment: .leading, spacing: 1) {
                        Text("\(message.sender) · \(message.time)").font(Theme.mono(10)).foregroundStyle(Theme.muted)
                        Text(translations[String(message.id)] ?? message.text)
                            .font(Theme.mono(13)).foregroundStyle(message.out ? Theme.strong : Theme.text)
                        if !isSecret {
                            if translations[String(message.id)] != nil {
                                Button(L("Mostrar original", "Show original")) {
                                    translations.removeValue(forKey: String(message.id))
                                }
                                .font(Theme.mono(10)).buttonStyle(.plain)
                            } else if message.translatable ?? !message.text.isEmpty {
                                Button(L("Traducir", "Translate")) { Task { await translate([message.id]) } }
                                    .font(Theme.mono(10)).buttonStyle(.plain).disabled(translating)
                            }
                        }
                    }
                    .listRowBackground(Color.clear)
                    .id(message.id)
                }
                if let problem {
                    Text(problem).font(Theme.mono(11)).foregroundStyle(Theme.muted)
                }
                if !messages.isEmpty && !isSecret {
                    Button(L("Traducir mensajes", "Translate messages")) {
                        Task { await translate(messages.filter { $0.translatable ?? !$0.text.isEmpty }.map(\.id), chatMode: true) }
                    }.font(Theme.mono(11)).disabled(translating)
                    if !translations.isEmpty {
                        Button(L("Mostrar originales", "Show originals")) { translations.removeAll() }
                            .font(Theme.mono(11))
                    }
                }
                LazyVGrid(columns: [GridItem(), GridItem(), GridItem()]) {
                    ForEach(quick, id: \.self) { item in
                        Button(item) { send(item) }.font(Theme.mono(14))
                    }
                }
                .listRowBackground(Color.clear)
                TextField(L("Mensaje", "Message"), text: $draft)
                    .font(Theme.mono(13))
                    .onSubmit { send(draft) }
                    .id("composer")
            }
            .navigationTitle(chat.name)
            .task {
                await load()
                // After the list has laid out the messages: open at the latest one.
                try? await Task.sleep(nanoseconds: 200_000_000)
                withAnimation(nil) { proxy.scrollTo("composer", anchor: .bottom) }
            }
        }
    }

    func load() async {
        do {
            messages = try await engine.request(["op": "messages", "peer": chat.id], as: [MessageItem].self)
            problem = nil
        } catch {
            problem = error.localizedDescription
        }
    }

    func translate(_ ids: [Int64], chatMode: Bool = false) async {
        guard !translating, !ids.isEmpty else { return }
        translating = true
        defer { translating = false }
        do {
            let language = locale.identifier
            let result = try await engine.request([
                "op": "translate", "peer": chat.id, "ids": ids,
                "language": language, "chat": chatMode
            ], as: [String: String].self)
            translations.merge(result) { _, new in new }
            problem = result.isEmpty ? L("No hay traducción disponible.", "No translation available.") : nil
        } catch {
            problem = error.localizedDescription
        }
    }

    func loadSecretInfo() async {
        do {
            secretInfo = try await engine.request(["op": "secret_info", "peer": chat.id], as: SecretInfoItem.self)
            showingSecret.toggle()
        } catch {
            problem = error.localizedDescription
        }
    }

    func setSecretTTL(_ seconds: Int) async {
        do {
            secretInfo = try await engine.request(["op": "secret_ttl", "peer": chat.id, "seconds": seconds], as: SecretInfoItem.self)
            await load()
        } catch {
            problem = error.localizedDescription
        }
    }

    func startSecret() async {
        do {
            _ = try await engine.request(["op": "secret_start", "peer": chat.id], as: ChatItem.self)
            problem = L("Chat secreto iniciado. Vuelve a la lista.", "Secret chat started. Go back to the list.")
        } catch {
            problem = error.localizedDescription
        }
    }

    func send(_ text: String) {
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        draft = ""
        Task {
            do {
                _ = try await engine.request(["op": "send", "peer": chat.id, "text": text], as: [String: Bool].self)
                try? await Task.sleep(nanoseconds: 700_000_000)
                await load()
            } catch {
                problem = error.localizedDescription
            }
        }
    }
}
