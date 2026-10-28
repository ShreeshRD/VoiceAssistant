import AppKit
import ApplicationServices
import DictateCore

@MainActor enum TextInsertion {
    struct Target { let pid: pid_t; let field: AXUIElement; let original: String; let range: CFRange }
    static var trusted: Bool { AXIsProcessTrusted() }
    static func requestPermission() { AXIsProcessTrustedWithOptions([kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary) }
    private static func focus(_ pid: pid_t) -> AXUIElement? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(AXUIElementCreateApplication(pid), kAXFocusedUIElementAttribute as CFString, &value) == .success,
              let value, CFGetTypeID(value) == AXUIElementGetTypeID() else { return nil }
        return unsafeBitCast(value, to: AXUIElement.self)
    }
    private static func contents(_ field: AXUIElement) -> (String, CFRange)? {
        var role: CFTypeRef?; AXUIElementCopyAttributeValue(field, kAXSubroleAttribute as CFString, &role)
        guard (role as? String) != "AXSecureTextField" else { return nil }
        var value: CFTypeRef?; var selection: CFTypeRef?
        guard AXUIElementCopyAttributeValue(field, kAXValueAttribute as CFString, &value) == .success,
              let text = value as? String, (text as NSString).length <= 1_000_000,
              AXUIElementCopyAttributeValue(field, kAXSelectedTextRangeAttribute as CFString, &selection) == .success,
              let selection, CFGetTypeID(selection) == AXValueGetTypeID() else { return nil }
        var range = CFRange()
        guard AXValueGetValue(unsafeBitCast(selection, to: AXValue.self), .cfRange, &range), range.location >= 0, range.length >= 0,
              range.location <= (text as NSString).length, range.length <= (text as NSString).length - range.location else { return nil }
        return (text, range)
    }
    static func capture() -> Target? {
        guard trusted, let pid = NSWorkspace.shared.frontmostApplication?.processIdentifier,
              pid != ProcessInfo.processInfo.processIdentifier, let field = focus(pid), let (text,range) = contents(field) else { return nil }
        return Target(pid:pid,field:field,original:text,range:range)
    }
    private static func unchanged(_ target: Target) -> Bool {
        guard NSWorkspace.shared.frontmostApplication?.processIdentifier == target.pid,
              let field = focus(target.pid), CFEqual(field, target.field),
              let (text, range) = contents(field) else { return false }
        return text == target.original && range.location == target.range.location && range.length == target.range.length
    }
    static func insert(_ text: String, into target: Target?) async -> String {
        guard trusted else { return "Text is ready. Enable Accessibility or use Copy." }
        guard let target else { return "No verifiable target was captured. Use Copy." }
        guard !Task.isCancelled, unchanged(target) else {
            return "The target field or selection changed. Nothing was inserted. Use Copy."
        }
        guard let plan = InsertionPlan(text: text, original: target.original, range: NSRange(location: target.range.location, length: target.range.length)) else { return "Invalid insertion range. Nothing was inserted. Use Copy." }
        guard let source = CGEventSource(stateID: .privateState),
              let down = CGEvent(keyboardEventSource: source, virtualKey: 9, keyDown: true),
              let up = CGEvent(keyboardEventSource: source, virtualKey: 9, keyDown: false) else { return "Cannot prepare paste. Use Copy." }
        guard let lease = ClipboardLease(text: plan.insertedText) else { return "Could not preserve your clipboard. Nothing was pasted. Use Copy." }
        guard !Task.isCancelled, unchanged(target) else {
            lease.restoreIfOwned()
            return "The target field or selection changed. Nothing was pasted. Use Copy."
        }
        down.flags = .maskCommand; up.flags = .maskCommand
        down.postToPid(target.pid); up.postToPid(target.pid)
        // Some editors update their accessibility value asynchronously. Never send a second write.
        for _ in 0..<20 {
            var after: CFTypeRef?
            AXUIElementCopyAttributeValue(target.field, kAXValueAttribute as CFString, &after)
            if (after as? String) == plan.expectedText {
                lease.restoreIfOwned()
                return "Pasted and verified."
            }
            try? await Task.sleep(nanoseconds: 50_000_000)
        }
        // A delayed target may still consume the paste. Never restore unrelated clipboard
        // data that the pending event could insert, and never dispatch a second write.
        return "Paste sent but not verified. Check your app before retrying. Dictated text remains on the clipboard unless you changed it."
    }
}
