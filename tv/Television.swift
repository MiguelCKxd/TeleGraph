import UIKit
import Network
import DeviceDiscoveryUI

private struct SharedChat: Decodable {
    let id: Int64
    let title: String
    let messages: [String]
}

final class Television: UITableViewController {
    private var connection: NWConnection?
    private var chats: [SharedChat] = []
    private var selected: Int64?
    private var chat: SharedChat? { chats.first { $0.id == selected } }
    private var status = "Conectar con el iPhone"

    override func viewDidLoad() {
        super.viewDidLoad()
        title = "TeleGraph"
        tableView.register(UITableViewCell.self, forCellReuseIdentifier: "row")
        NotificationCenter.default.addObserver(self, selector: #selector(clearSession),
                                               name: UIApplication.willResignActiveNotification, object: nil)
    }

    @objc private func clearSession() {
        close("Conectar con el iPhone")
    }

    private func close(_ label: String) {
        let previous = connection
        connection = nil
        previous?.cancel()
        if presentedViewController is UIAlertController { dismiss(animated: false) }
        chats.removeAll()
        selected = nil
        title = "TeleGraph"
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
            title = "TeleGraph"
            tableView.reloadData()
            return
        }
        if indexPath.row > 0 {
            let choice = chats[indexPath.row - 1]
            selected = choice.id
            title = choice.title
            tableView.reloadData()
            return
        }
        if connection != nil { clearSession(); return }
        choosePhone()
    }

    private func choosePhone() {
        let descriptor = NWBrowser.Descriptor.applicationService(name: "telegraph-companion")
        let parameters = NWParameters.applicationService
        guard DDDevicePickerViewController.isSupported(descriptor, using: parameters),
              let picker = DDDevicePickerViewController(browseDescriptor: descriptor, parameters: parameters) else {
            close("Selector de dispositivos no disponible. Volver a intentar")
            return
        }
        Task { @MainActor in
            present(picker, animated: true)
            do {
                let endpoint = try await picker.endpoint
                picker.dismiss(animated: true)
                let link = NWConnection(to: endpoint, using: parameters)
                connection = link
                status = "Esperando al iPhone · Desconectar"
                tableView.reloadData()
                observe(link)
                link.start(queue: .main)
            } catch {
                picker.dismiss(animated: true)
                clearSession()
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
                    self.status = "Abre TeleGraph en el iPhone desbloqueado · Cancelar"
                    self.tableView.reloadData()
                case .failed, .cancelled:
                    self.clearSession()
                default: break
                }
            }
        }
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
                if let index = self.chats.firstIndex(where: { $0.id == chat.id }) {
                    self.chats[index] = chat
                } else {
                    self.chats.append(chat)
                }
                self.status = "Desconectar el iPhone"
                self.tableView.reloadData()
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
