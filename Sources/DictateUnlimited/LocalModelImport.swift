import Foundation
import CryptoKit
import DictateCore

/// Imported models are data-only WhisperKit exports, copied into owned storage.
enum LocalModelImport {
    static let maximumBytes: Int64 = 4_000_000_000
    static let maximumFiles = 2048
    static let components = ["MelSpectrogram.mlmodelc", "AudioEncoder.mlmodelc", "TextDecoder.mlmodelc"]
    static let rootFiles: Set<String> = ["tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "config.json", "generation_config.json", "LICENSE", "NOTICE", "README.md"]

    static func allowed(_ path: String) -> Bool {
        guard ModelCatalog.safeRelativePath(path) else { return false }
        let parts = path.split(separator: "/")
        if parts.count == 1 { return rootFiles.contains(path) }
        guard components.contains(String(parts[0])) else { return false }
        return ["bin", "mil", "json", "mlmodel"].contains(URL(fileURLWithPath:path).pathExtension)
    }
    static func checkPath(_ url: URL, inside root: URL) throws {
        let base = root.standardizedFileURL.path + "/"
        guard url.standardizedFileURL.path.hasPrefix(base) else { throw AppError("Model file escapes its folder.") }
        var current = url
        while current.standardizedFileURL.path != root.standardizedFileURL.path {
            try Task.checkCancellation()
            let values = try current.resourceValues(forKeys:[.isSymbolicLinkKey])
            guard values.isSymbolicLink != true else { throw AppError("Model folders cannot contain symbolic links.") }
            let parent=current.deletingLastPathComponent()
            guard parent.standardizedFileURL.path != current.standardizedFileURL.path else { throw AppError("Model folder boundary could not be resolved.") }
            current=parent
        }
        guard try root.resourceValues(forKeys:[.isSymbolicLinkKey]).isSymbolicLink != true else { throw AppError("Choose a model folder, not a symbolic link.") }
    }
    static func hash(_ url: URL) throws -> String {
        let handle=try FileHandle(forReadingFrom:url);defer { try? handle.close() }
        var hash=SHA256()
        while let data=try handle.read(upToCount:1024*1024),!data.isEmpty { try Task.checkCancellation();hash.update(data:data) }
        return hash.finalize().map { String(format:"%02x",$0) }.joined()
    }
    static func inspect(_ input: URL) throws -> [ModelFile] {
        let keys:Set<URLResourceKey>=[.isSymbolicLinkKey,.isRegularFileKey,.isDirectoryKey,.fileSizeKey]
        let rootValues=try input.resourceValues(forKeys:keys)
        guard rootValues.isDirectory == true,rootValues.isSymbolicLink != true else { throw AppError("Choose the complete WhisperKit model folder.") }
        let root=input.resolvingSymlinksInPath().standardizedFileURL
        // Do not skip hidden entries: they must not conceal links or executable content.
        guard let enumerator=FileManager.default.enumerator(at:root,includingPropertiesForKeys:Array(keys)) else { throw AppError("Cannot read this model folder.") }
        var files:[ModelFile]=[];var total:Int64=0;var entries=0
        for case let url as URL in enumerator {
            try Task.checkCancellation(); entries += 1
            guard entries <= maximumFiles * 2 else { throw AppError("Model folder contains too many entries.") }
            let values=try url.resourceValues(forKeys:keys)
            try checkPath(url,inside:root)
            let relative=String(url.standardizedFileURL.path.dropFirst(root.path.count+1))
            if values.isDirectory == true {
                guard components.contains(relative.split(separator:"/").first.map(String.init) ?? "") else { throw AppError("Unexpected folder in model: \(relative)") }
                continue
            }
            // Finder metadata is ignored, never copied.
            if [".DS_Store", ".complete", ".import.json"].contains(url.lastPathComponent) && url.deletingLastPathComponent().standardizedFileURL.path == root.standardizedFileURL.path { continue }
            guard values.isRegularFile == true,allowed(relative) else { throw AppError("Unsupported model file: \(relative). Import a WhisperKit Core ML export, not scripts or raw weights.") }
            let size=Int64(values.fileSize ?? 0);total += size
            guard size > 0,total <= maximumBytes,files.count < maximumFiles else { throw AppError("Model folder is empty, too large, or contains too many files.") }
            files.append(ModelFile(path:relative,size:size,sha256:try hash(url)))
        }
        let paths=Set(files.map(\.path))
        guard paths.contains("tokenizer.json"),paths.contains("tokenizer_config.json"),components.allSatisfy({ paths.contains($0+"/coremldata.bin") && paths.contains($0+"/model.mil") }) else {
            throw AppError("Missing model components. Include AudioEncoder, MelSpectrogram and TextDecoder .mlmodelc folders, tokenizer.json and tokenizer_config.json.")
        }
        return files.sorted { $0.path < $1.path }
    }
    static func validDescriptor(_ model:BarkModel) -> Bool {
        guard model.isImported,UUID(uuidString:String(model.id.dropFirst("whisper-import-".count))) != nil,model.revision == "local1",!model.name.isEmpty,model.name.count <= 120,
              model.files.count <= maximumFiles,!model.files.isEmpty,Set(model.files.map(\.path)).count == model.files.count else { return false }
        var total:Int64=0
        for f in model.files {
            guard allowed(f.path),f.size > 0,f.size <= maximumBytes,let hash=f.sha256,hash.count == 64,hash.allSatisfy({ $0.isHexDigit }),f.sourceRepository == nil,f.sourceRevision == nil,f.sourcePath == nil else { return false }
            total += f.size;guard total <= maximumBytes else { return false }
        }
        return true
    }
    static func copy(from source:URL,to staging:URL) throws -> [ModelFile] {
        let files=try inspect(source)
        for file in files {
            try Task.checkCancellation()
            let original=source.appendingPathComponent(file.path)
            try checkPath(original,inside:source)
            let dest=staging.appendingPathComponent(file.path)
            try FileManager.default.createDirectory(at:dest.deletingLastPathComponent(),withIntermediateDirectories:true)
            try FileManager.default.copyItem(at:original,to:dest)
            try checkPath(dest,inside:staging)
            try ModelStore.verify(dest,file)
        }
        return files
    }
}
