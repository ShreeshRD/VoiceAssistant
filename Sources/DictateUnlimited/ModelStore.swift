import Foundation
import CryptoKit
import DictateCore

@MainActor final class ModelStore: ObservableObject {
    @Published var models: [BarkModel] = []
    @Published var installed: Set<String> = []
    @Published var downloading: String?
    @Published var progress: Double = 0
    @Published var message = "Models download only when you choose Download. Audio stays on this Mac."
    private var task: Task<Void, Never>?
    let root: URL
    private let sessionConfiguration: URLSessionConfiguration
    init(root: URL? = nil, models: [BarkModel]? = nil, sessionConfiguration: URLSessionConfiguration = .ephemeral) {
        self.sessionConfiguration = sessionConfiguration
        self.root = root ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("DOO MADE/Dictate Unlimited/Models", isDirectory: true)
        do { self.models = try models ?? ModelCatalog.load(); try FileManager.default.createDirectory(at: self.root, withIntermediateDirectories: true); refresh() }
        catch { message = error.localizedDescription }
    }
    func directory(_ m: BarkModel) -> URL { root.appendingPathComponent(m.id + "-" + m.revision) }
    func refresh() {
        models.removeAll { $0.isImported }
        if let entries = try? FileManager.default.contentsOfDirectory(at:root,includingPropertiesForKeys:[.isSymbolicLinkKey]) {
            for folder in entries where folder.lastPathComponent.hasPrefix("whisper-import-") {
                do {
                    guard try folder.resourceValues(forKeys:[.isSymbolicLinkKey]).isSymbolicLink != true else { continue }
                    let manifest=folder.appendingPathComponent(".import.json")
                    try LocalModelImport.checkPath(manifest,inside:folder)
                    guard (try manifest.resourceValues(forKeys:[.fileSizeKey]).fileSize ?? Int.max) < 1_000_000 else { continue }
                    let model=try JSONDecoder().decode(BarkModel.self,from:Data(contentsOf:manifest))
                    guard LocalModelImport.validDescriptor(model),directory(model).standardizedFileURL.path == folder.standardizedFileURL.path else { continue }
                    models.append(model)
                } catch { message="An imported model could not be read. Its files were preserved; import the original folder again." }
            }
        }
        installed = Set(models.filter { FileManager.default.fileExists(atPath: directory($0).appendingPathComponent(".complete").path) }.map(\.id))
    }
    func importLocal(_ source:URL) {
        guard task == nil else { return }
        let id="whisper-import-"+UUID().uuidString.lowercased()
        downloading=id;progress=0;message="Checking and copying local Whisper model…"
        task=Task {
            let staging=root.appendingPathComponent(".partial-"+UUID().uuidString)
            let access=source.startAccessingSecurityScopedResource()
            defer { if access { source.stopAccessingSecurityScopedResource() };try? FileManager.default.removeItem(at:staging);downloading=nil;task=nil;refresh() }
            do {
                try FileManager.default.createDirectory(at:staging,withIntermediateDirectories:true)
                let worker=Task.detached { try LocalModelImport.copy(from:source,to:staging) }
                let files=try await withTaskCancellationHandler(operation:{ try await worker.value },onCancel:{ worker.cancel() })
                try Task.checkCancellation()
                // Load the copied files with the offline runtime before installing the import.
                let name="Imported: "+String(source.lastPathComponent.prefix(90))
                let model=BarkModel(id:id,name:name,repository:"local",revision:"local1",prefix:"",precision:"Imported WhisperKit Core ML",files:files)
                message="Preparing imported model locally. First preparation may take several minutes…"
                let probe=Recognition()
                try await probe.prepare(model,root:staging)
                await probe.unload()
                try Task.checkCancellation()
                try JSONEncoder().encode(model).write(to:staging.appendingPathComponent(".import.json"),options:.atomic)
                try Data(model.revision.utf8).write(to:staging.appendingPathComponent(".complete"))
                try FileManager.default.moveItem(at:staging,to:directory(model))
                message="Local model imported and validated. Choose Load to use it."
            } catch is CancellationError { message="Import cancelled. No model was installed." }
            catch { message="Import failed: \(error.localizedDescription)" }
        }
    }
    func cancel() { task?.cancel() }
    func download(_ m: BarkModel, repair: Bool = false) {
        guard !m.isImported, task == nil, (!installed.contains(m.id) || repair) else { return }
        downloading = m.id; progress = 0
        task = Task {
            let staging = root.appendingPathComponent(".partial-" + UUID().uuidString)
            defer { try? FileManager.default.removeItem(at: staging); downloading = nil; task = nil; refresh() }
            do {
                try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: true)
                let session = URLSession(configuration: sessionConfiguration)
                defer { session.invalidateAndCancel() }
                var total: Int64 = 0
                for file in m.files {
                    try Task.checkCancellation()
                    guard ModelCatalog.safeRelativePath(file.path) else { throw AppError("Invalid model manifest path.") }
                    message = "Downloading \(m.name): \(file.path)"
                    let repository=file.sourceRepository ?? m.repository
                    let revision=file.sourceRevision ?? m.revision
                    let remotePath=file.sourcePath ?? (m.prefix+file.path)
                    guard ModelCatalog.safeRelativePath(repository),ModelCatalog.safeRelativePath(revision),ModelCatalog.safeRelativePath(remotePath),
                          let url=URL(string:"https://huggingface.co/\(repository)/resolve/\(revision)/\(remotePath)") else { throw AppError("Invalid model source.") }
                    let (temporary, response) = try await session.download(from: url)
                    guard let http = response as? HTTPURLResponse, http.statusCode == 200 else { throw AppError("Model download failed. Check your connection and retry.") }
                    try await Task.detached { try Self.verify(temporary, file) }.value
                    try Task.checkCancellation()
                    let target = staging.appendingPathComponent(file.path)
                    try FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
                    try FileManager.default.moveItem(at: temporary, to: target)
                    total += file.size; progress = Double(total) / Double(m.bytes)
                }
                try Data(m.revision.utf8).write(to: staging.appendingPathComponent(".complete"))
                let destination = directory(m)
                let previous = root.appendingPathComponent(".previous-" + UUID().uuidString)
                let replacing = FileManager.default.fileExists(atPath: destination.path)
                if replacing { try FileManager.default.moveItem(at: destination, to: previous) }
                do { try FileManager.default.moveItem(at: staging, to: destination) }
                catch { if replacing { try? FileManager.default.moveItem(at: previous, to: destination) }; throw error }
                if replacing { try? FileManager.default.removeItem(at: previous) }
                message = "\(m.name) is ready to load."
            } catch is CancellationError { message = "Download cancelled. No partial model was installed." }
            catch {
                if Task.isCancelled || (error as? URLError)?.code == .cancelled {
                    message = "Download cancelled. No partial model was installed."
                } else { message = error.localizedDescription }
            }
        }
    }
    nonisolated static func verify(_ url: URL, _ file: ModelFile) throws {
        let attrs = try FileManager.default.attributesOfItem(atPath: url.path)
        guard (attrs[.size] as? NSNumber)?.int64Value == file.size else { throw AppError("Wrong size for \(file.path). Download was not installed.") }
        if let expected = file.sha256 {
            let h = try FileHandle(forReadingFrom: url); defer { try? h.close() }
            var digest = SHA256()
            while let chunk = try h.read(upToCount: 1024 * 1024), !chunk.isEmpty { digest.update(data: chunk) }
            let actual = digest.finalize().map { String(format: "%02x", $0) }.joined()
            guard actual == expected else { throw AppError("Integrity check failed for \(file.path).") }
        }
    }
    func validate(_ m: BarkModel) async throws {
        let dir = directory(m)
        try await Task.detached { for file in m.files { try Task.checkCancellation(); guard ModelCatalog.safeRelativePath(file.path) else { throw AppError("Invalid model file path.") }
            let url=dir.appendingPathComponent(file.path)
            try LocalModelImport.checkPath(url,inside:dir)
            try Self.verify(url,file) } }.value
    }
}
struct AppError: LocalizedError { let text: String; init(_ text: String) { self.text = text }; var errorDescription: String? { text } }
