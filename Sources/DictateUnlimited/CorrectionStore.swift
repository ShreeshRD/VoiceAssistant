import Foundation
import DictateCore

@MainActor final class CorrectionStore: ObservableObject {
    @Published private(set) var entries: [LocalCorrection] = []
    @Published var message = "Corrections stay on this Mac. Nothing is learned automatically."
    @Published private(set) var writable = true
    @Published private(set) var canUndo = false
    private var previous: [LocalCorrection]?
    let file: URL
    init(file: URL? = nil) {
        self.file = file ?? FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0].appendingPathComponent("DOO MADE/Dictate Unlimited/Corrections.json")
        do {
            if FileManager.default.fileExists(atPath:self.file.path) {
                let data=try Data(contentsOf:self.file)
                guard data.count <= 1_000_000 else { throw AppError("Dictionary file is too large.") }
                let loaded=try JSONDecoder().decode([LocalCorrection].self,from:data)
                guard loaded.count <= 500,Set(loaded.map(\.id)).count==loaded.count else { throw AppError("Invalid dictionary entries.") }
                var checked:[LocalCorrection]=[]
                for entry in loaded {
                    if let error=LocalCorrections.validationError(heard:entry.heard,replacement:entry.replacement,existing:checked) { throw AppError(error) }
                    checked.append(entry)
                }
                entries=checked
            }
        } catch { writable=false;message="Dictionary could not be loaded. Existing file preserved. \(error.localizedDescription)" }
    }
    func save(id: UUID?, heard: String, replacement: String) -> Bool {
        guard writable else { return false }
        if let error=LocalCorrections.validationError(heard:heard,replacement:replacement,existing:entries,excludingID:id) { message=error;return false }
        var next=entries
        let entry=LocalCorrection(id:id ?? UUID(),heard:heard.trimmingCharacters(in:.whitespacesAndNewlines),replacement:replacement.trimmingCharacters(in:.whitespacesAndNewlines))
        if let id,let index=next.firstIndex(where:{$0.id==id}) { next[index]=entry }
        else { guard next.count < 500 else { message="Dictionary is limited to 500 corrections.";return false };next.append(entry) }
        return persist(next)
    }
    func remove(_ id: UUID) { _ = persist(entries.filter { $0.id != id }) }
    func undo() {
        guard let previous else { return }
        if persist(previous,remember:false) { self.previous=nil;canUndo=false;message="Dictionary change undone." }
    }
    private func persist(_ next: [LocalCorrection], remember: Bool = true) -> Bool {
        guard writable else { return false }
        do {
            try FileManager.default.createDirectory(at:file.deletingLastPathComponent(),withIntermediateDirectories:true)
            try JSONEncoder().encode(next).write(to:file,options:.atomic)
            if remember { previous=entries;canUndo=true }
            entries=next;message="Saved locally. Applies to your next completed dictation.";return true
        } catch { message="Could not save dictionary. \(error.localizedDescription)";return false }
    }
    func apply(_ text: String) -> String { LocalCorrections.apply(text,entries:entries) }
}
