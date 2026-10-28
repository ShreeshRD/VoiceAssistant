import AppKit
import Carbon
import DictateCore

@MainActor final class ShortcutController: ObservableObject {
    enum Action: UInt32 { case dictate=1, recover=2 }
    struct Configuration: Codable {
        var dictate = ShortcutBinding.dictation
        var recover = ShortcutBinding.recovery
        var hold = false
        var valid: Bool { dictate.valid && recover.valid && !dictate.conflicts(with:recover) }
    }
    @Published private(set) var configuration: Configuration
    @Published private(set) var recording: Action?
    @Published private(set) var message = ""
    var onDown: ((Action, Bool) -> Void)?
    var onUp: ((Action, Bool) -> Void)?
    private var keys: [EventHotKeyRef] = []
    private var handler: EventHandlerRef?
    private var local: Any?
    private var global: Any?
    private var resign: NSObjectProtocol?
    private var edges = ShortcutEdges()
    private var heldMode = false
    init() {
        if let data=UserDefaults.standard.data(forKey:"shortcutConfiguration"),let saved=try? JSONDecoder().decode(Configuration.self,from:data),saved.valid { configuration=saved }
        else { configuration=Configuration() }
    }
    func start() {
        var events=[EventTypeSpec(eventClass:OSType(kEventClassKeyboard),eventKind:UInt32(kEventHotKeyPressed)),EventTypeSpec(eventClass:OSType(kEventClassKeyboard),eventKind:UInt32(kEventHotKeyReleased))]
        let status=InstallEventHandler(GetApplicationEventTarget(), { _,event,context in
            guard let event,let context else { return OSStatus(eventNotHandledErr) }
            var id=EventHotKeyID();let status=GetEventParameter(event,EventParamName(kEventParamDirectObject),EventParamType(typeEventHotKeyID),nil,MemoryLayout<EventHotKeyID>.size,nil,&id)
            guard status==noErr, id.signature==0x44554E4C else { return OSStatus(eventNotHandledErr) }
            let number=id.id;let down=GetEventKind(event)==UInt32(kEventHotKeyPressed)
            let owner=Unmanaged<ShortcutController>.fromOpaque(context).takeUnretainedValue()
            Task { @MainActor in owner.edge(number,down:down) };return noErr
        },2,&events,Unmanaged.passUnretained(self).toOpaque(),&handler)
        guard status==noErr else { message="Shortcut handler unavailable (\(status)). Use the menu bar.";return }
        local=NSEvent.addLocalMonitorForEvents(matching:[.keyDown,.keyUp]) { [weak self] event in
            guard let self else { return event }
            return self.handle(event) ? nil : event
        }
        global=NSEvent.addGlobalMonitorForEvents(matching:[.keyDown,.keyUp]) { [weak self] event in
            Task { @MainActor in _ = self?.handle(event) }
        }
        resign=NotificationCenter.default.addObserver(forName:NSApplication.didResignActiveNotification,object:nil,queue:.main) { [weak self] _ in
            Task { @MainActor in if self?.recording != nil { self?.cancelRecording() } }
        }
        register(configuration)
    }
    private func unregister() { for key in keys { UnregisterEventHotKey(key) };keys=[];edges.reset() }
    @discardableResult private func register(_ config: Configuration) -> Bool {
        unregister()
        for (id,key) in [(UInt32(1),config.dictate),(UInt32(2),config.recover)] {
            var ref:EventHotKeyRef?
            let status=RegisterEventHotKey(key.keyCode,key.modifiers,EventHotKeyID(signature:0x44554E4C,id:id),GetApplicationEventTarget(),0,&ref)
            guard status==noErr,let ref else { unregister();message="Shortcut unavailable (\(status)). Choose another combination; the menu still works.";return false }
            keys.append(ref)
        }
        message="Shortcuts ready.";return true
    }
    func setHold(_ hold: Bool) { guard recording==nil else { return };configuration.hold=hold;persist() }
    func record(_ action: Action) { guard recording==nil else { return };unregister();recording=action;message="Press Control or Option plus a key. Escape cancels." }
    func cancelRecording() { recording=nil;register(configuration) }
    func resetDefaults() {
        let previous=configuration;let next=Configuration()
        if register(next) { configuration=next;persist() }
        else { let failure=message;register(previous);message=failure }
    }
    func resetHeldKeys() { edges.reset() }
    func stop() {
        unregister();if let handler { RemoveEventHandler(handler) };handler=nil
        if let local { NSEvent.removeMonitor(local) };if let global { NSEvent.removeMonitor(global) }
        if let resign { NotificationCenter.default.removeObserver(resign) }
    }
    private func persist() { if let data=try? JSONEncoder().encode(configuration) { UserDefaults.standard.set(data,forKey:"shortcutConfiguration") } }
    private static func modifiers(_ flags: NSEvent.ModifierFlags) -> UInt32 {
        var value:UInt32=0
        if flags.contains(.control) { value |= UInt32(controlKey) }
        if flags.contains(.option) { value |= UInt32(optionKey) }
        if flags.contains(.command) { value |= UInt32(cmdKey) }
        if flags.contains(.shift) { value |= UInt32(shiftKey) }
        return value
    }
    private func handle(_ event: NSEvent) -> Bool {
        if let recording {
            guard event.type == .keyDown else { return true }
            if event.keyCode==53 { cancelRecording();return true }
            guard !event.isARepeat else { return true }
            let names:[UInt16:String]=[49:"Space",36:"Return",48:"Tab",51:"Delete",123:"Left",124:"Right",125:"Down",126:"Up"]
            let label=names[event.keyCode] ?? event.charactersIgnoringModifiers?.uppercased() ?? "Key \(event.keyCode)"
            let binding=ShortcutBinding(keyCode:UInt32(event.keyCode),modifiers:Self.modifiers(event.modifierFlags),keyLabel:label)
            var next=configuration
            if recording == .dictate { next.dictate=binding } else { next.recover=binding }
            self.recording=nil
            guard next.valid else { register(configuration);message="Use Control or Option with a key, and different shortcuts for dictation and recovery.";return true }
            let previous=configuration
            if register(next) { configuration=next;persist() }
            else { let failure=message;register(previous);message=failure }
            return true
        }
        guard keys.count==2 else { return false }
        for (id,key) in [(UInt32(1),configuration.dictate),(UInt32(2),configuration.recover)] where key.keyCode == UInt32(event.keyCode) {
            if event.type == .keyUp && edges.isDown(id) { edge(id,down:false);return true }
            if event.type == .keyDown && !event.isARepeat && key.modifiers==Self.modifiers(event.modifierFlags) { edge(id,down:true);return true }
        }
        return false
    }
    private func edge(_ id: UInt32, down: Bool) {
        guard recording==nil,keys.count==2,let action=Action(rawValue:id) else { return }
        if down {
            guard edges.down(id) else { return }
            if action == .dictate { heldMode=configuration.hold }
            onDown?(action,action == .dictate && heldMode)
        } else if edges.up(id) { onUp?(action,action == .dictate && heldMode) }
    }
}
