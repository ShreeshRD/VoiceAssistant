// Production ModelStore with synthetic HTTPS model responses. No external requests.
import Foundation
import CryptoKit
import DictateCore

final class ModelProtocol: URLProtocol {
    static var mode = "success"
    static let payload = Data("valid model fixture".utf8)
    override class func canInit(with request: URLRequest) -> Bool { request.url?.host == "huggingface.co" }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        if Self.mode == "disconnect" { client?.urlProtocol(self, didFailWithError: URLError(.networkConnectionLost)); return }
        if Self.mode == "cancel" { client?.urlProtocol(self, didFailWithError: URLError(.cancelled)); return }
        let bytes = Self.mode == "wrong-size" ? Data([1]) : Self.mode == "corrupt" ? Data(repeating: 120, count: Self.payload.count) : Self.payload
        let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: ["Content-Length":"\(bytes.count)"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: bytes)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
// Native model compatibility is separately exercised with real offline fixtures.
// This double isolates the production store's import transaction and filesystem checks.
actor Recognition {
    func prepare(_ model:BarkModel,root:URL) async throws { try Task.checkCancellation() }
    func unload() {}
}
@main struct ModelStoreChecks {
    @MainActor static func settle(_ store: ModelStore) async {
        for _ in 0..<500 { if store.downloading == nil { return }; try? await Task.sleep(nanoseconds: 10_000_000) }
        preconditionFailure("Download did not settle")
    }
    @MainActor static func main() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("model-store-checks-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let hash = SHA256.hash(data: ModelProtocol.payload).map { String(format:"%02x", $0) }.joined()
        let data = try JSONSerialization.data(withJSONObject: [["id":"fixture","name":"Fixture","repository":"test/fixture","revision":"pinned","prefix":"","precision":"test","files":[["path":"weights.bin","size":ModelProtocol.payload.count,"sha256":hash]]]])
        let model = try JSONDecoder().decode([BarkModel].self, from:data)[0]
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [ModelProtocol.self]
        let store = ModelStore(root:root, models:[model], sessionConfiguration:config)
        ModelProtocol.mode = "success"; store.download(model); await settle(store)
        print("success state:",store.message)
        precondition(store.installed.contains(model.id))
        let installed = store.directory(model).appendingPathComponent("weights.bin")
        for mode in ["disconnect","corrupt"] {
            ModelProtocol.mode = mode; store.download(model,repair:true); await settle(store)
            precondition((try? Data(contentsOf:installed)) == ModelProtocol.payload)
            precondition(store.installed.contains(model.id))
            let entries = try FileManager.default.contentsOfDirectory(atPath:root.path)
            precondition(!entries.contains { $0.hasPrefix(".partial-") })
            if mode == "corrupt" { precondition(store.message.contains("Integrity check failed")) }
            print("PASS failed repair preserved prior installation and removed staging:",mode)
        }
        for mode in ["wrong-size", "corrupt", "disconnect"] {
            let freshRoot = root.appendingPathComponent(mode)
            let fresh = ModelStore(root:freshRoot, models:[model], sessionConfiguration:config)
            ModelProtocol.mode = mode; fresh.download(model); await settle(fresh)
            precondition(fresh.installed.isEmpty)
            let entries = try FileManager.default.contentsOfDirectory(atPath:freshRoot.path)
            precondition(entries.isEmpty)
            print("PASS failed fresh download left no installation or staging:",mode)
        }
        ModelProtocol.mode = "success"; store.download(model,repair:true); await settle(store)
        precondition(store.message.contains("ready to load"))
        ModelProtocol.mode = "cancel";store.download(model,repair:true);await settle(store)
        precondition((try? Data(contentsOf:installed)) == ModelProtocol.payload)
        print("cancellation state:",store.message)
        precondition(store.message == "Download cancelled. No partial model was installed.")
        print("PASS valid download and repair, disconnect, hash failure and cancellation preservation")
        let source=root.appendingPathComponent("source-model")
        for component in LocalModelImport.components {
            let folder=source.appendingPathComponent(component)
            try FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true)
            try Data("fixture".utf8).write(to:folder.appendingPathComponent("coremldata.bin"))
            try Data("fixture".utf8).write(to:folder.appendingPathComponent("model.mil"))
        }
        for name in ["tokenizer.json","tokenizer_config.json"] { try Data("{}".utf8).write(to:source.appendingPathComponent(name)) }
        // URL equality includes directory/trailing-slash metadata; path containment must not.
        let withoutSlash=URL(fileURLWithPath:source.path,isDirectory:false)
        try LocalModelImport.checkPath(source.appendingPathComponent("tokenizer.json"),inside:withoutSlash)
        let importRoot=root.appendingPathComponent("imports")
        let imported=ModelStore(root:importRoot,models:[model],sessionConfiguration:config)
        imported.importLocal(source);await settle(imported)
        guard let local=imported.models.first(where:{ $0.isImported }) else { preconditionFailure(imported.message) }
        precondition(imported.installed.contains(local.id));try await imported.validate(local)
        let reopened=ModelStore(root:importRoot,models:[model],sessionConfiguration:config)
        precondition(reopened.installed.contains(local.id))
        try Data("bad".utf8).write(to:imported.directory(local).appendingPathComponent("tokenizer.json"))
        do { try await imported.validate(local);preconditionFailure("Corrupt import accepted") } catch {}
        // Symlinks, scripts and incomplete exports never install.
        for failure in ["script","symlink","missing"] {
            let invalid=root.appendingPathComponent("input-"+failure)
            try FileManager.default.copyItem(at:source,to:invalid)
            if failure == "script" { try Data("print('unsafe')".utf8).write(to:invalid.appendingPathComponent("loader.py")) }
            if failure == "symlink" { try FileManager.default.createSymbolicLink(at:invalid.appendingPathComponent("linked.json"),withDestinationURL:source.appendingPathComponent("tokenizer.json")) }
            if failure == "missing" { try FileManager.default.removeItem(at:invalid.appendingPathComponent("tokenizer.json")) }
            let failureStore=ModelStore(root:root.appendingPathComponent("failed-"+failure),models:[model],sessionConfiguration:config)
            failureStore.importLocal(invalid);await settle(failureStore)
            precondition(failureStore.installed.isEmpty && failureStore.message.contains("Import failed"))
            let remaining=try FileManager.default.contentsOfDirectory(atPath:failureStore.root.path);precondition(remaining.isEmpty)
        }
        let cancelled=ModelStore(root:root.appendingPathComponent("cancelled-import"),models:[model],sessionConfiguration:config)
        cancelled.importLocal(source);cancelled.cancel();await settle(cancelled)
        precondition(cancelled.installed.isEmpty)
        print("PASS import transaction, persistence, corrupt-file detection, link/script/missing-file rejection and cancellation")
    }
}
