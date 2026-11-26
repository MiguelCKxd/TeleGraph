// Append to Television.swift in a disposable simulator harness (without TVApp).
// Same-file extension exercises the actual controller's private lifecycle code.
extension Television {
    @MainActor static func verifySessionLifecycle() throws {
        let controller = Television(style: .plain)
        controller.loadViewIfNeeded()
        controller.look.logo = UIGraphicsImageRenderer(size: CGSize(width: 2, height: 2)).pngData { ctx in
            UIColor.blue.setFill()
            ctx.fill(CGRect(x: 0, y: 0, width: 2, height: 2))
        }
        controller.applyAppearance()
        precondition(controller.navigationItem.leftBarButtonItem != nil, "Logo should exist")
        controller.look.logo = nil
        controller.applyAppearance()
        precondition(controller.navigationItem.leftBarButtonItem == nil, "Reset must remove old logo")

        for id in 0..<40 {
            if id == 1 { controller.selected = "0/" }
            controller.receiveSharedChat(SharedChat(id: Int64(id), topic_id: nil,
                                                    title: "QA", messages: ["Synthetic"], appearance: nil))
        }
        precondition(controller.chats.count == 24, "Chat count must stay bounded")
        precondition(controller.chat?.id == 0, "Eviction must preserve selected chat")
        controller.receiveSharedChat(SharedChat(id: 39, topic_id: nil,
                                                title: "Updated", messages: [], appearance: nil))
        precondition(controller.chats.count == 24 && controller.chats.last?.title == "Updated",
                     "Same chat must update in place")
        controller.receiveSharedChat(SharedChat(id: 39, topic_id: 10,
                                                title: "Topic", messages: [], appearance: nil))
        precondition(controller.chats.contains { $0.key == "39/10" }, "Topics retain distinct keys")
        let generation = controller.selectionGeneration
        let pending = Task<Void, Never> { }
        controller.pickerTask = pending
        controller.clearSession()
        precondition(pending.isCancelled && controller.pickerTask == nil, "Clear cancels pending picker")
        precondition(controller.selectionGeneration != generation, "Old endpoint must be invalidated")
        precondition(controller.chats.isEmpty && controller.selected == nil, "Clear releases shared messages")
        precondition(controller.connection == nil, "Clear disconnects")
        let result = ["passed": 10, "platform": "tvOS Simulator", "real_device_pairing": false] as [String: Any]
        let file = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("tv-session-result.json")
        try JSONSerialization.data(withJSONObject: result, options: .prettyPrinted).write(to: file)
        print("TeleGraph TV lifecycle: 10 checks passed")
    }
}

final class TVSessionQAScene: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?
    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options: UIScene.ConnectionOptions) {
        guard let scene = scene as? UIWindowScene else { return }
        window = UIWindow(windowScene: scene)
        window?.rootViewController = UIViewController()
        window?.makeKeyAndVisible()
        do { try Television.verifySessionLifecycle() } catch { fatalError("TV lifecycle: \(error)") }
    }
}

@main final class TVSessionQA: UIResponder, UIApplicationDelegate {}
