import AppKit
import SwiftUI
import Carbon
import DictateCore
import AVFoundation

@main struct Main {
    @MainActor static func main() {
        if CommandLine.arguments.contains("--check-resources") {
            do { let models = try ModelCatalog.load(); print("Catalog: \(models.map(\.id).joined(separator: ", "))"); print("Application resources: \(Bundle.main.resourceURL?.path ?? "unavailable")"); exit(0) }
            catch { fputs("\(error.localizedDescription)\n",stderr); exit(1) }
        }
        if CommandLine.arguments.count >= 5, CommandLine.arguments[1] == "--transcribe" {
            let args = CommandLine.arguments
            Task {
                do {
                    guard let model = try ModelCatalog.load().first(where: { $0.id == args[2] }) else { throw AppError("Unknown model") }
                    let engine = Recognition()
                    try await engine.prepare(model, root: URL(fileURLWithPath: args[3]))
                    for inputPath in args.dropFirst(4) {
                        let f = try AVAudioFile(forReading: URL(fileURLWithPath: inputPath))
                        guard f.processingFormat.sampleRate == 16000, f.processingFormat.channelCount == 1, f.length > 0, f.length <= 16000 * 300,
                              let b = AVAudioPCMBuffer(pcmFormat: f.processingFormat, frameCapacity: AVAudioFrameCount(f.length)) else { throw AppError("Expected mono 16kHz audio up to five minutes") }
                        try f.read(into: b)
                        guard let p = b.floatChannelData?[0] else { throw AppError("Expected floating audio") }
                        let samples = Array(UnsafeBufferPointer(start: p, count: Int(b.frameLength)))
                        let selectedLanguage=ProcessInfo.processInfo.environment["DICTATE_TRANSCRIPTION_LANGUAGE"]
                        print(try await engine.transcribe(samples,language:selectedLanguage == "auto" ? nil : selectedLanguage))
                    }
                    exit(0)
                } catch { fputs("\(error.localizedDescription)\n",stderr); exit(1) }
            }
            dispatchMain()
        }
        let application = NSApplication.shared
        let delegate = AppDelegate()
        application.delegate = delegate
        application.setActivationPolicy(.accessory)
        withExtendedLifetime(delegate) { application.run() }
    }
}
@MainActor final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let microphones = MicrophoneController()
    let dictionary = CorrectionStore()
    let shortcuts = ShortcutController()
    lazy var session = DictationSession(resolveInput: { [unowned self] in try self.microphones.selectedDeviceID() }, correct: { [unowned self] text in self.dictionary.apply(text) })
    let store = ModelStore()
    private var window: NSWindow!
    private var feedback: NSPanel!
    private var status: NSStatusItem!
    private var interruptionObservers: [NSObjectProtocol] = []
    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu(); let appMenuItem = NSMenuItem(); menu.addItem(appMenuItem)
        let submenu = NSMenu(); submenu.addItem(withTitle: "Settings…", action: #selector(showSettings), keyEquivalent: ",").target = self
        submenu.addItem(.separator()); submenu.addItem(withTitle: "Quit Dictate Unlimited", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appMenuItem.submenu = submenu
        let editItem=NSMenuItem();let edit=NSMenu(title:"Edit")
        edit.addItem(withTitle:"Undo",action:NSSelectorFromString("undo:"),keyEquivalent:"z")
        let redo=edit.addItem(withTitle:"Redo",action:NSSelectorFromString("redo:"),keyEquivalent:"z");redo.keyEquivalentModifierMask=[.command,.shift]
        edit.addItem(.separator())
        edit.addItem(withTitle:"Cut",action:#selector(NSText.cut(_:)),keyEquivalent:"x")
        edit.addItem(withTitle:"Copy",action:#selector(NSText.copy(_:)),keyEquivalent:"c")
        edit.addItem(withTitle:"Paste",action:#selector(NSText.paste(_:)),keyEquivalent:"v")
        edit.addItem(withTitle:"Select All",action:#selector(NSText.selectAll(_:)),keyEquivalent:"a")
        editItem.submenu=edit;menu.addItem(editItem);NSApp.mainMenu=menu
        window = NSWindow(contentRect: NSRect(x:0,y:0,width:1100,height:860), styleMask:[.titled,.closable,.miniaturizable,.resizable,.fullSizeContentView], backing:.buffered,defer:false)
        window.delegate=self;window.title = "Dictate Unlimited"; window.titleVisibility = .hidden; window.titlebarAppearsTransparent = true; window.isReleasedWhenClosed = false
        window.minSize = NSSize(width:820,height:600)
        window.contentView = NSHostingView(rootView: SettingsView(session:session,store:store,microphones:microphones,dictionary:dictionary,shortcuts:shortcuts)); window.center()
        feedback = NSPanel(contentRect:.zero, styleMask:[.borderless,.nonactivatingPanel], backing:.buffered,defer:false)
        feedback.isFloatingPanel = true; feedback.level = .statusBar; feedback.backgroundColor = .clear; feedback.isOpaque = false; feedback.hasShadow = true
        feedback.collectionBehavior = [.canJoinAllSpaces,.fullScreenAuxiliary]; feedback.hidesOnDeactivate = false
        feedback.contentView = NSHostingView(rootView:FeedbackView(session:session))
        status = NSStatusBar.system.statusItem(withLength:NSStatusItem.squareLength)
        status.button?.image = NSImage(systemSymbolName:"mic",accessibilityDescription:"Dictate Unlimited")
        let tray = NSMenu()
        tray.addItem(withTitle:"Start / finish dictation",action:#selector(toggle),keyEquivalent:"").target = self
        tray.addItem(withTitle:"Cancel dictation",action:#selector(cancel),keyEquivalent:"").target = self
        tray.addItem(withTitle:"Paste last dictation",action:#selector(pasteLast),keyEquivalent:"").target = self
        tray.addItem(.separator());tray.addItem(withTitle:"Settings…",action:#selector(showSettings),keyEquivalent:"").target = self
        tray.addItem(withTitle:"Quit",action:#selector(NSApplication.terminate(_:)),keyEquivalent:"")
        status.menu = tray
        session.stateChanged = { [weak self] in self?.updateFeedback(); self?.microphones.refresh() }
        shortcuts.onDown = { [weak self] action, hold in
            guard let self else { return }
            guard action == .dictate else { return }
            if hold { self.session.beginHold() } else { self.session.toggle() }
        }
        shortcuts.onUp = { [weak self] action,hold in
            if action == .recover { self?.session.pasteLast() }
            else if hold { self?.session.endHold() }
        }
        shortcuts.start()
        interruptionObservers.append(NSWorkspace.shared.notificationCenter.addObserver(forName:NSWorkspace.didWakeNotification,object:nil,queue:.main) { [weak self] _ in
            Task { @MainActor in self?.shortcuts.resetHeldKeys();self?.microphones.refresh() }
        })
        for name in [NSWorkspace.willSleepNotification, NSWorkspace.sessionDidResignActiveNotification] {
            interruptionObservers.append(NSWorkspace.shared.notificationCenter.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                Task { @MainActor in self?.session.interrupt("Session interrupted. Nothing will be inserted; start a new dictation when you return.") }
            })
        }
        session.restoreSelection(store: store)
        showSettings()
    }
    func applicationWillTerminate(_ notification: Notification) {
        session.cancel();shortcuts.stop()
        for observer in interruptionObservers { NSWorkspace.shared.notificationCenter.removeObserver(observer) }
    }
    func windowWillClose(_ notification: Notification) { if shortcuts.recording != nil { shortcuts.cancelRecording() } }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        // Opening a running menu-bar app must bring its settings back into view.
        if window != nil { showSettings() }
        return true
    }
    @objc func toggle() { guard shortcuts.recording == nil else { return }; session.toggle() }
    @objc func pasteLast() { guard shortcuts.recording == nil else { return };session.pasteLast() }
    @objc func cancel() { session.cancel() }
    @objc func showSettings() { microphones.refresh();window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps:true) }
    func applicationDidBecomeActive(_ notification: Notification) { microphones.refresh() }
    private func updateFeedback() {
        status.button?.image = NSImage(systemSymbolName:session.phase == .recording ? "mic.fill" : "mic",accessibilityDescription:session.phase.rawValue)
        guard session.phase == .recording || session.phase == .testingMicrophone || session.phase == .transcribing || session.phase == .delivering || session.phase == .cancelling else { feedback.orderOut(nil); return }
        let screen = NSScreen.screens.first { NSMouseInRect(NSEvent.mouseLocation,$0.frame,false) } ?? NSScreen.main!
        let width:CGFloat = session.expanded ? 752 : 492, height:CGFloat = session.expanded ? 216 : 100
        let x = screen.frame.midX - width/2
        let y = session.overlayStyle == "notch" ? screen.frame.maxY - height : screen.visibleFrame.minY + 32
        feedback.setFrame(NSRect(x:x,y:y,width:width,height:height),display:true)
        feedback.orderFrontRegardless()
    }
    func applicationShouldTerminate(_ sender:NSApplication) -> NSApplication.TerminateReply { session.cancel(); store.cancel(); return .terminateNow }
}
