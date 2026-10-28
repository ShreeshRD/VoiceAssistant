import Foundation
import DictateCore
struct AppError: LocalizedError { let text:String;init(_ text:String){self.text=text};var errorDescription:String?{text} }
@main struct CorrectionStoreChecks {
    @MainActor static func main() throws {
        let root=FileManager.default.temporaryDirectory.appendingPathComponent("corrections-"+UUID().uuidString)
        defer { try? FileManager.default.removeItem(at:root) }
        let file=root.appendingPathComponent("dictionary.json");let store=CorrectionStore(file:file)
        precondition(store.save(id:nil,heard:"doo made",replacement:"DOO MADE"))
        precondition(!store.save(id:nil,heard:"DOO MADE",replacement:"duplicate"))
        let id=store.entries[0].id
        precondition(store.save(id:id,heard:"doo made",replacement:"Doo Made"))
        let loaded=CorrectionStore(file:file);precondition(loaded.entries[0].replacement=="Doo Made")
        store.remove(id);precondition(store.entries.isEmpty);store.undo();precondition(store.entries.count==1)
        precondition(store.apply("doo made and doodle")=="Doo Made and doodle")
        try Data("not json".utf8).write(to:file)
        let broken=CorrectionStore(file:file);precondition(!broken.writable)
        precondition(!broken.save(id:nil,heard:"new",replacement:"NEW"))
        let preserved=try String(contentsOf:file,encoding:.utf8);precondition(preserved=="not json")
        print("PASS local correction persistence, duplicate validation, editing, removal/undo and corrupt-file preservation")
    }
}
