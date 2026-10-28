import Foundation

public struct ShortcutBinding: Codable, Equatable, Sendable {
    public var keyCode: UInt32
    public var modifiers: UInt32
    public var keyLabel: String
    public init(keyCode: UInt32, modifiers: UInt32, keyLabel: String) {
        self.keyCode = keyCode; self.modifiers = modifiers; self.keyLabel = keyLabel
    }
    public static let dictation = Self(keyCode:49, modifiers:6144, keyLabel:"Space")
    public static let recovery = Self(keyCode:9, modifiers:4352, keyLabel:"V")
    public var display: String {
        ((modifiers & 4096 != 0) ? "⌃" : "") + ((modifiers & 2048 != 0) ? "⌥" : "") +
        ((modifiers & 512 != 0) ? "⇧" : "") + ((modifiers & 256 != 0) ? "⌘" : "") + keyLabel
    }
    public var valid: Bool {
        keyCode <= 126 && !(53...63).contains(keyCode) && !keyLabel.isEmpty && keyLabel.count <= 20 &&
        modifiers & ~UInt32(4096|2048|512|256) == 0 && modifiers & UInt32(4096|2048) != 0
    }
    public func conflicts(with other: Self) -> Bool { keyCode == other.keyCode && modifiers == other.modifiers }
}
public struct ShortcutEdges {
    private var pressed: Set<UInt32> = []
    public init() {}
    public mutating func down(_ id: UInt32, repeatEvent: Bool = false) -> Bool {
        guard !repeatEvent else { return false }; return pressed.insert(id).inserted
    }
    public mutating func up(_ id: UInt32) -> Bool { pressed.remove(id) != nil }
    public mutating func reset() { pressed.removeAll() }
    public func isDown(_ id: UInt32) -> Bool { pressed.contains(id) }
}
