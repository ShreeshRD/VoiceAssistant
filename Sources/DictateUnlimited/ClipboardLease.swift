import AppKit

/// Restore only after verified delivery and only while this app still owns the clipboard.
@MainActor final class ClipboardLease {
    private let board: NSPasteboard
    private let saved: [NSPasteboardItem]
    private let ownedChange: Int
    init?(text: String, board: NSPasteboard = .general) {
        var saved: [NSPasteboardItem] = []
        var bytes = 0
        let before = board.changeCount
        for item in board.pasteboardItems ?? [] {
            let copy = NSPasteboardItem()
            for type in item.types {
                guard let data = item.data(forType: type) else { return nil }
                bytes += data.count
                guard bytes <= 32 * 1024 * 1024, copy.setData(data, forType: type) else { return nil }
            }
            saved.append(copy)
        }
        guard board.changeCount == before else { return nil }
        self.board = board; self.saved = saved
        board.clearContents()
        guard board.setString(text, forType: .string) else {
            board.clearContents(); if !saved.isEmpty { board.writeObjects(saved) }
            return nil
        }
        ownedChange = board.changeCount
    }
    func restoreIfOwned() {
        guard board.changeCount == ownedChange else { return }
        board.clearContents()
        if !saved.isEmpty { board.writeObjects(saved) }
    }
}
