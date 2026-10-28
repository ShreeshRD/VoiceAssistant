import AppKit
@main struct ClipboardChecks {
    @MainActor static func main() {
        let board = NSPasteboard.withUniqueName()
        defer { board.releaseGlobally() }
        let a = NSPasteboardItem(); a.setString("original",forType:.string); a.setData(Data([1,2,3]),forType:NSPasteboard.PasteboardType("org.test.binary"))
        board.writeObjects([a])
        let lease = ClipboardLease(text:"dictation",board:board)!
        precondition(board.string(forType:.string)=="dictation")
        lease.restoreIfOwned()
        precondition(board.string(forType:.string)=="original")
        precondition(board.data(forType:NSPasteboard.PasteboardType("org.test.binary"))==Data([1,2,3]))
        let changed = ClipboardLease(text:"second",board:board)!
        board.clearContents();board.setString("new user copy",forType:.string)
        changed.restoreIfOwned()
        precondition(board.string(forType:.string)=="new user copy")
        board.clearContents();let empty = ClipboardLease(text:"temporary",board:board)!
        empty.restoreIfOwned();precondition((board.pasteboardItems ?? []).isEmpty)
        board.setData(Data(repeating:0,count:32*1024*1024+1),forType:.string)
        let before=board.changeCount
        precondition(ClipboardLease(text:"refused",board:board)==nil && board.changeCount==before)
        print("PASS private clipboard restoration, binary types, newer-copy protection, empty clipboard and size limit")
    }
}
