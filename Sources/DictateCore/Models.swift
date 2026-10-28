import Foundation
public struct ModelFile: Codable, Sendable {
    public let path: String
    public let size: Int64
    public let sha256: String?
    public let sourceRepository: String?
    public let sourceRevision: String?
    public let sourcePath: String?
    public init(path: String, size: Int64, sha256: String?, sourceRepository: String? = nil, sourceRevision: String? = nil, sourcePath: String? = nil) {
        self.path=path; self.size=size; self.sha256=sha256
        self.sourceRepository=sourceRepository; self.sourceRevision=sourceRevision; self.sourcePath=sourcePath
    }
}
public struct BarkModel: Codable, Identifiable, Sendable, Equatable {
    public let id: String
    public let name: String
    public let repository: String
    public let revision: String
    public let prefix: String
    public let precision: String
    public let files: [ModelFile]
    public var isWhisper: Bool { id.hasPrefix("whisper-") }
    public var isImported: Bool { id.hasPrefix("whisper-import-") }
    public init(id: String, name: String, repository: String, revision: String, prefix: String, precision: String, files: [ModelFile]) {
        self.id=id; self.name=name; self.repository=repository; self.revision=revision
        self.prefix=prefix; self.precision=precision; self.files=files
    }
    public var bytes: Int64 { files.reduce(0) { $0 + $1.size } }
    public static func == (a: Self, b: Self) -> Bool { a.id == b.id }
}
public enum ModelCatalog {
    public static func load() throws -> [BarkModel] {
        let packaged = Bundle.main.resourceURL.flatMap { Bundle(url: $0.appendingPathComponent("DictateUnlimited_DictateCore.bundle")) }
        let resources = packaged ?? Bundle.module
        guard let url = resources.url(forResource: "models", withExtension: "json") else { throw CatalogError.missing }
        var models = try JSONDecoder().decode([BarkModel].self, from: Data(contentsOf: url))
        guard let whisperURL = resources.url(forResource: "whisper-models", withExtension: "json") else { throw CatalogError.missing }
        models += try JSONDecoder().decode([BarkModel].self, from: Data(contentsOf: whisperURL))
        return models
    }
    public static func safeRelativePath(_ path: String) -> Bool {
        !path.isEmpty && !path.hasPrefix("/") && !path.contains("\\") && !path.split(separator: "/", omittingEmptySubsequences: false).contains(where: { $0 == ".." || $0 == "." || $0.isEmpty })
    }
    enum CatalogError: Error { case missing }
}
public enum AudioLimits {
    public static let sampleRate = 16000
    public static let maximumSeconds = 300
    public static func valid(_ samples: [Float]) -> Bool { !samples.isEmpty && samples.count <= sampleRate * maximumSeconds && samples.allSatisfy(\.isFinite) }
}
