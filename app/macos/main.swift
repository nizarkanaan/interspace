import AppKit
import WebKit

/// Methods the WebView may send to the backend. Everything else is refused here.
let allowedMethods: Set<String> = [
    "state", "select_task", "connection", "cancel", "sign_in", "switch_project", "update_project",
    // Agentic tasks (scheduler.md, events.md, scope.md)
    "agent_create", "agent_message", "agent_answer", "agent_cancel", "task_events", "task_blob",
    "scope_get", "scope_update", "scope_approve", "scope_default", "scheduler_settings",
    // Multi-provider extensions (docs/superpowers/specs/multi-provider): providers, teams, review and merge
    "providers_list", "provider_sign_in", "provider_status", "routing_update", "team_answer",
    "review_summary", "review_merge", "review_branches",
]

final class AppDelegate: NSObject, NSApplicationDelegate, WKScriptMessageHandler, WKNavigationDelegate, NSWindowDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var backend: Process?
    var input: FileHandle?
    var output: Pipe?
    var pending = Data()
    let readQueue = DispatchQueue(label: "interspace.backend.read")
    let writeLock = NSLock()
    var ready = false
    var queued: [[String: Any]] = []
    var resourceRoot: URL { Bundle.main.resourceURL! }
    var dataRoot: URL {
        if let index = CommandLine.arguments.firstIndex(of: "--data-root"), CommandLine.arguments.count > index + 1 {
            return URL(fileURLWithPath: CommandLine.arguments[index + 1], isDirectory: true)
        }
        return FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("Interspace", isDirectory: true)
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let configuration = WKWebViewConfiguration()
        configuration.userContentController.add(self, name: "interspace")
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        web = WKWebView(frame: .zero, configuration: configuration)
        web.navigationDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1180, height: 820), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Interspace"
        window.minSize = NSSize(width: 760, height: 580)
        window.delegate = self
        window.contentView = web
        window.center()
        let menu = NSMenu()
        let appItem = NSMenuItem()
        menu.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About Interspace", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "Quit Interspace", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        let editItem = NSMenuItem()
        menu.addItem(editItem)
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        NSApp.mainMenu = menu
        web.loadFileURL(resourceRoot.appendingPathComponent("app/ui/index.html"), allowingReadAccessTo: resourceRoot.appendingPathComponent("app/ui"))
        startBackend()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func startBackend() {
        let python = ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"].first { FileManager.default.isExecutableFile(atPath: $0) }
        guard let python else { deliver(["type": "fatal", "error": "Python 3.9 or newer is required. Install Python and reopen Interspace."]); return }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = ["-B", "-u", resourceRoot.appendingPathComponent("app/backend/service.py").path, "--data-root", dataRoot.path]
        process.currentDirectoryURL = resourceRoot
        let stdin = Pipe(), stdout = Pipe(), stderr = Pipe()
        process.standardInput = stdin; process.standardOutput = stdout; process.standardError = stderr
        input = stdin.fileHandleForWriting
        output = stdout
        stdout.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let bytes = handle.availableData
            guard !bytes.isEmpty else { return }
            self?.readQueue.async { [weak self] in self?.receive(bytes) }
        }
        // Drain diagnostics without exposing raw provider output or storing it in the chat.
        stderr.fileHandleForReading.readabilityHandler = { handle in _ = handle.availableData }
        process.terminationHandler = { [weak self] process in
            DispatchQueue.main.async {
                self?.deliver(["type": "fatal", "error": "Local backend stopped (\(process.terminationStatus)). Reopen Interspace to restore saved work."])
            }
        }
        do { try process.run(); backend = process }
        catch { deliver(["type": "fatal", "error": "Could not start the local backend. Check Python installation and reopen Interspace."]) }
    }

    func receive(_ bytes: Data) {
        pending.append(bytes)
        while let newline = pending.firstIndex(of: 10) {
            let line = pending.prefix(upTo: newline)
            pending.removeSubrange(...newline)
            if let message = try? JSONSerialization.jsonObject(with: Data(line)) as? [String: Any] {
                DispatchQueue.main.async { [weak self] in self?.deliver(message) }
            }
        }
    }

    /// Writes one JSON line to the backend. Serialised, because requests can come from different threads.
    @discardableResult
    func writeLine(_ message: [String: Any]) -> Bool {
        guard let backend, backend.isRunning, let input, var bytes = try? JSONSerialization.data(withJSONObject: message) else { return false }
        bytes.append(10)
        writeLock.lock(); defer { writeLock.unlock() }
        do { try input.write(contentsOf: bytes); return true } catch { return false }
    }

    func deliver(_ message: [String: Any]) {
        guard ready else { queued.append(message); return }
        guard let bytes = try? JSONSerialization.data(withJSONObject: message), let json = String(data: bytes, encoding: .utf8) else { return }
        web.evaluateJavaScript("window.interspaceReceive(\(json));", completionHandler: nil)
    }

    func send(_ message: [String: Any]) {
        guard let backend, backend.isRunning, input != nil else {
            deliver(["id": message["id"] ?? NSNull(), "error": "Local backend is unavailable. Reopen Interspace."]); return
        }
        if !writeLine(message) { deliver(["id": message["id"] ?? NSNull(), "error": "Connection to local backend closed."]) }
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, let url = message.frameInfo.request.url,
              url.isFileURL, url.standardizedFileURL == resourceRoot.appendingPathComponent("app/ui/index.html").standardizedFileURL,
              let request = message.body as? [String: Any], let method = request["method"] as? String else { return }
        if method == "choose_project" {
            let alert = NSAlert()
            alert.messageText = "Add a project folder"
            alert.informativeText = "Agent tasks work in their own copy of the project. Interspace never edits your checked-out files."
            let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 480, height: 26))
            field.placeholderString = "Full repository folder path"
            field.stringValue = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Documents/Projects").path
            alert.accessoryView = field
            alert.addButton(withTitle: "Use folder")
            alert.addButton(withTitle: "Browse…")
            alert.addButton(withTitle: "Cancel")
            alert.beginSheetModal(for: window) { [weak self] response in
                if response == .alertFirstButtonReturn {
                    self?.send(["id": request["id"] ?? NSNull(), "method": "add_project", "params": ["path": field.stringValue]])
                } else if response == .alertSecondButtonReturn {
                    self?.browseProject(request)
                } else { self?.deliver(["id": request["id"] ?? NSNull(), "result": ["cancelled": true]]) }
            }
            return
        }
        guard allowedMethods.contains(method) else {
            deliver(["id": request["id"] ?? NSNull(), "error": "Unsupported app action."]); return
        }
        // Forward only id, method and params, so the WebView can never add other fields to a backend line.
        send(["id": request["id"] ?? NSNull(), "method": method, "params": request["params"] ?? [String: Any]()])
    }

    func browseProject(_ request: [String: Any]) {
        let picker = NSOpenPanel()
        picker.title = "Add a Git project repository"
        picker.prompt = "Choose folder"
        picker.canChooseDirectories = true
        picker.canChooseFiles = false
        picker.allowsMultipleSelection = false
        picker.canCreateDirectories = false
        picker.beginSheetModal(for: window) { [weak self] result in
            if result == .OK, let path = picker.url?.path {
                self?.send(["id": request["id"] ?? NSNull(), "method": "add_project", "params": ["path": path]])
            } else { self?.deliver(["id": request["id"] ?? NSNull(), "result": ["cancelled": true]]) }
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        ready = true
        let messages = queued; queued.removeAll()
        for message in messages { deliver(message) }
        web.evaluateJavaScript("window.interspaceBoot();", completionHandler: nil)
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if url.isFileURL && url.standardizedFileURL == resourceRoot.appendingPathComponent("app/ui/index.html").standardizedFileURL {
            decisionHandler(.allow)
        } else {
            if navigationAction.navigationType == .linkActivated && ["https", "http"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
            decisionHandler(.cancel)
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) {
        send(["id": "quit", "method": "cancel", "params": [:]])
        try? input?.close()
        // EOF lets the backend stop its provider process group and persist interrupted state.
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.regular)
let delegate = AppDelegate()
app.delegate = delegate
app.run()
