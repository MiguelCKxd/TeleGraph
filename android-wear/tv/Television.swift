import UIKit
import Network
import DeviceDiscoveryUI

private struct SharedChat: Decodable {
    let id: Int64
    let topic_id: Int64?
    var key: String { "\(id)/\(topic_id.map(String.init) ?? "")" }
    let title: String
    let messages: [String]
    let appearance: TelevisionLook?
}

private struct TelevisionLook: Codable {
    var name = "TeleGraph", bg = "#08100c", text = "#8cf5a6", strong = "#bdffcd"
    var font = "", scale = 1.0
    var logo: Data?

    /// 3.2: the phone's typeface with Apple's system designs (SF Pro, SF Pro
    /// Rounded, SF Mono, New York), sized from the text style and scale.
    func uiFont(_ style: UIFont.TextStyle, bold: Bool = false) -> UIFont {
        let base = UIFont.preferredFont(forTextStyle: style)
        let size = base.pointSize * CGFloat(min(1.6, max(0.8, scale)))
        if font == "sf_compact" {
            for family in ["SF Compact", "SF Compact Text"] {
                let names = UIFont.fontNames(forFamilyName: family)
                let name = names.first { $0.localizedCaseInsensitiveContains(bold ? "bold" : "regular") } ?? names.first
                if let name, let installed = UIFont(name: name, size: size) { return installed }
            }
        }
        var weight: UIFont.Weight = bold ? .bold : .regular
        var design: UIFontDescriptor.SystemDesign = .default
        var traits: UIFontDescriptor.SymbolicTraits = []
        switch font {
        case "courier", "mono", "sf_mono", "typewriter": design = .monospaced
        case "rounded", "sf_rounded", "casual": design = .rounded
        case "serif", "classic", "book", "new_york", "noto_serif": design = .serif
        case "handwriting": design = .serif; traits.insert(.traitItalic)
        case "light": weight = bold ? .semibold : .light
        case "medium": weight = bold ? .heavy : .medium
        case "condensed": traits.insert(.traitCondensed)
        default: break  // "", sans, system, sf, sf_compact, humanist, smallcaps: SF Pro.
        }
        var descriptor = UIFont.systemFont(ofSize: size, weight: weight).fontDescriptor
        descriptor = descriptor.withDesign(design) ?? descriptor
        if !traits.isEmpty { descriptor = descriptor.withSymbolicTraits(descriptor.symbolicTraits.union(traits)) ?? descriptor }
        return UIFont(descriptor: descriptor, size: size)
    }

    static func color(_ hex: String) -> UIColor {
        guard hex.count == 7, hex.first == "#", let rgb = UInt32(hex.dropFirst(), radix: 16) else { return .label }
        return UIColor(red: CGFloat(rgb >> 16) / 255, green: CGFloat((rgb >> 8) & 255) / 255,
                       blue: CGFloat(rgb & 255) / 255, alpha: 1)
    }
}

final class Television: UITableViewController {
    private var look = UserDefaults.standard.data(forKey: "tvLook").flatMap {
        try? JSONDecoder().decode(TelevisionLook.self, from: $0)
    } ?? TelevisionLook()
    private var connection: NWConnection?
    private var pickerTask: Task<Void, Never>?
    private var selectionGeneration = UUID()
    private var chats: [SharedChat] = []
    private var selected: String?
    private var chat: SharedChat? { chats.first { $0.key == selected } }
    private var status = "Conectar con el iPhone"

    override func viewDidLoad() {
        super.viewDidLoad()
        applyAppearance()
        tableView.register(UITableViewCell.self, forCellReuseIdentifier: "row")
        NotificationCenter.default.addObserver(self, selector: #selector(clearSession),
                                               name: UIApplication.willResignActiveNotification, object: nil)
    }

    private func applyAppearance() {
        title = chat?.title ?? look.name
        tableView.backgroundColor = TelevisionLook.color(look.bg)
        navigationController?.view.tintColor = TelevisionLook.color(look.strong)
        let bar = UINavigationBarAppearance()
        bar.configureWithOpaqueBackground()
        bar.backgroundColor = TelevisionLook.color(look.bg)
        bar.titleTextAttributes = [.foregroundColor: TelevisionLook.color(look.strong), .font: look.uiFont(.headline, bold: true)]
        bar.largeTitleTextAttributes = [.foregroundColor: TelevisionLook.color(look.strong), .font: look.uiFont(.title1, bold: true)]
        navigationItem.standardAppearance = bar
        navigationItem.scrollEdgeAppearance = bar
        if let data = look.logo, data.count <= 32768, let logo = UIImage(data: data) {
            let image = UIImageView(image: logo)
            image.contentMode = .scaleAspectFit
            image.translatesAutoresizingMaskIntoConstraints = false
            NSLayoutConstraint.activate([image.widthAnchor.constraint(equalToConstant: 64),
                                         image.heightAnchor.constraint(equalToConstant: 64)])
            navigationItem.leftBarButtonItem = UIBarButtonItem(customView: image)
        } else {
            navigationItem.leftBarButtonItem = nil
        }
    }

    @objc private func clearSession() {
        close("Conectar con el iPhone")
    }

    private func close(_ label: String) {
        selectionGeneration = UUID()
        pickerTask?.cancel()
        pickerTask = nil
        let previous = connection
        connection = nil
        previous?.cancel()
        if presentedViewController is UIAlertController || presentedViewController is DDDevicePickerViewController {
            dismiss(animated: false)
        }
        chats.removeAll()
        selected = nil
        applyAppearance()
        status = label
        tableView.reloadData()
    }

    override func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int {
        1 + (chat?.messages.count ?? chats.count)
    }

    override func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let cell = tableView.dequeueReusableCell(withIdentifier: "row", for: indexPath)
        var text = cell.defaultContentConfiguration()
        if let chat {
            text.text = indexPath.row == 0 ? "Volver a los chats" : chat.messages[indexPath.row - 1]
        } else {
            text.text = indexPath.row == 0 ? status : chats[indexPath.row - 1].title
        }
        text.textProperties.numberOfLines = 3
        text.textProperties.color = TelevisionLook.color(look.text)
        text.textProperties.font = look.uiFont(.body, bold: chat == nil && indexPath.row > 0)
        cell.contentConfiguration = text
        return cell
    }

    override func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        if indexPath.row > 0, let chat {
            let reader = UIAlertController(title: chat.title, message: chat.messages[indexPath.row - 1], preferredStyle: .alert)
            reader.addAction(UIAlertAction(title: "Volver", style: .default))
            present(reader, animated: true)
            return
        }
        if chat != nil {
            selected = nil
            applyAppearance()
            tableView.reloadData()
            return
        }
        if indexPath.row > 0 {
            let choice = chats[indexPath.row - 1]
            selected = choice.key
            title = choice.title
            tableView.reloadData()
            return
        }
        if connection != nil { clearSession(); return }
        choosePhone()
    }

    private func choosePhone() {
        guard pickerTask == nil, UIApplication.shared.applicationState == .active else { return }
        let descriptor = NWBrowser.Descriptor.applicationService(name: "telegraph-companion")
        let parameters = NWParameters.applicationService
        guard DDDevicePickerViewController.isSupported(descriptor, using: parameters),
              let picker = DDDevicePickerViewController(browseDescriptor: descriptor, parameters: parameters) else {
            close("Selector de dispositivos no disponible. Volver a intentar")
            return
        }
        let generation = selectionGeneration
        present(picker, animated: true)
        pickerTask = Task { @MainActor [weak self] in
            do {
                let endpoint = try await picker.endpoint
                guard let self, !Task.isCancelled, self.selectionGeneration == generation,
                      UIApplication.shared.applicationState == .active else { return }
                self.pickerTask = nil
                picker.dismiss(animated: true)
                let link = NWConnection(to: endpoint, using: parameters)
                self.connection = link
                self.status = "Esperando al iPhone · Desconectar"
                self.tableView.reloadData()
                self.observe(link)
                link.start(queue: .main)
            } catch {
                guard let self, !Task.isCancelled, self.selectionGeneration == generation else { return }
                picker.dismiss(animated: true)
                self.clearSession()
            }
        }
    }

    private func observe(_ link: NWConnection) {
        link.stateUpdateHandler = { [weak self, weak link] state in
            // The connection delivers its state callbacks on the main queue.
            MainActor.assumeIsolated {
                guard let self, let link, self.connection === link else { return }
                switch state {
                case .ready:
                    self.status = "iPhone conectado · Comparte un chat desde el teléfono · Desconectar"
                    self.tableView.reloadData()
                    self.readHeader(link)
                case .waiting:
                    self.status = "Abre \(self.look.name) en el iPhone desbloqueado · Cancelar"
                    self.tableView.reloadData()
                case .failed, .cancelled:
                    self.clearSession()
                default: break
                }
            }
        }
    }

    private func receiveSharedChat(_ chat: SharedChat) {
        if let index = chats.firstIndex(where: { $0.key == chat.key }) {
            chats[index] = chat
        } else {
            // Each packet is already limited to 256 KiB. Keep at most
            // 24 conversations in memory, preserving the open one.
            if chats.count >= 24,
               let oldest = chats.firstIndex(where: { $0.key != selected }) {
                chats.remove(at: oldest)
            }
            chats.append(chat)
        }
        if let appearance = chat.appearance, appearance.name.count <= 60,
           appearance.logo.map({ $0.count <= 32768 }) ?? true {
            look = appearance
            if let data = try? JSONEncoder().encode(appearance) {
                UserDefaults.standard.set(data, forKey: "tvLook")
            }
            applyAppearance()
        }
        status = "Desconectar el iPhone"
        tableView.reloadData()
    }

    private func readHeader(_ link: NWConnection) {
        link.receive(minimumIncompleteLength: 4, maximumLength: 4) { [weak self] data, _, _, _ in
            guard let self, self.connection === link else { return }
            guard let data, data.count == 4 else { self.clearSession(); return }
            let bytes = data.reduce(0) { ($0 << 8) | Int($1) }
            guard (1...262144).contains(bytes) else { self.clearSession(); return }
            link.receive(minimumIncompleteLength: bytes, maximumLength: bytes) { [weak self] body, _, ended, error in
                guard let self, self.connection === link else { return }
                guard error == nil, !ended, let body, body.count == bytes,
                      let chat = try? JSONDecoder().decode(SharedChat.self, from: body),
                      chat.messages.count <= 50 else { self.clearSession(); return }
                self.receiveSharedChat(chat)
                self.readHeader(link)
            }
        }
    }
}

final class TVScene: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?
    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options: UIScene.ConnectionOptions) {
        guard let windowScene = scene as? UIWindowScene else { return }
        window = UIWindow(windowScene: windowScene)
        window?.rootViewController = UINavigationController(rootViewController: Television(style: .plain))
        window?.makeKeyAndVisible()
    }
}

@main final class TVApp: UIResponder, UIApplicationDelegate {}
