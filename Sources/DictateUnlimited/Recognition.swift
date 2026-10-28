import Foundation
import CoreML
import FluidAudio
import BarkSmall
import DictateCore

actor Recognition {
    private var small: SmallBarkRecognizer?
    private var whisper: WhisperRecognition?
    private var pro: [String: AsrManager] = [:]
    private var selectedID: String?
    func unload() { small = nil; whisper = nil; pro = [:]; selectedID = nil }
    func prepare(_ model: BarkModel, root: URL) async throws {
        if selectedID == model.id { return }
        unload()
        if model.id.hasPrefix("whisper-") {
            whisper = try await WhisperRecognition(root: root)
        } else if model.id == "bark-pro" {
            let cache = root.appendingPathComponent("Compiled", isDirectory: true)
            try FileManager.default.createDirectory(at: cache, withIntermediateDirectories: true)
            var compiled: [String: URL] = [:]
            for name in ["Encoder", "Preprocessor", "Decoder", "JointDecisionv3"] {
                let dest = cache.appendingPathComponent(name + ".mlmodelc")
                if !FileManager.default.fileExists(atPath: dest.path) {
                    let temporary = try await MLModel.compileModel(at: root.appendingPathComponent(name + ".mlpackage"))
                    try FileManager.default.moveItem(at: temporary, to: dest)
                }
                compiled[name] = dest
            }
            func load(_ name: String, function: String? = nil) throws -> MLModel {
                let c = MLModelConfiguration(); c.computeUnits = name == "Encoder" ? .cpuAndNeuralEngine : .cpuOnly; c.functionName = function
                return try MLModel(contentsOf: compiled[name]!, configuration: c)
            }
            let raw = try JSONDecoder().decode([String:String].self, from: Data(contentsOf: root.appendingPathComponent("parakeet_v3_vocab.json")))
            let vocabulary = Dictionary(uniqueKeysWithValues: raw.compactMap { k,v in Int(k).map { ($0,v) } })
            let config = MLModelConfiguration(); config.computeUnits = .cpuOnly
            // Load one encoder path on demand; avoid holding two copies of the model.
            let models = try AsrModels(encoder: load("Encoder", function: "full15"), preprocessor: load("Preprocessor"), decoder: load("Decoder"), joint: load("JointDecisionv3"), configuration: config, vocabulary: vocabulary, version: .ultra)
            pro["full15"] = AsrManager(models: models)
        } else { small = try SmallBarkRecognizer(root: root) }
        selectedID = model.id
    }
    func transcribe(_ samples: [Float], language: String? = nil) async throws -> String {
        guard AudioLimits.valid(samples) else { throw AppError("Recording is empty, invalid or longer than five minutes.") }
        if let whisper { return try await whisper.transcribe(samples, language: language) }
        if let small { return try await small.transcribe(samples) }
        if let manager = pro["full15"] {
            var state = try TdtDecoderState()
            let result = try await manager.transcribe(Array(repeating: Float(0), count: 4000) + samples, decoderState: &state)
            return result.text
        }
        throw AppError("Select and load a downloaded model first.")
    }
}
