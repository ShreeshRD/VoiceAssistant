// SPDX-License-Identifier: CC-BY-4.0
// Adapted from Conway Research Bark; see ATTRIBUTION.md for source and changes.
// Adapted inference pipeline: Conway Research Bark 3.0, CC-BY-4.0.
// See ATTRIBUTION.md. Local files only; this module contains no network client.
import Foundation
import CoreML

/// Native Core ML/Accelerate implementation for the Bark 3.0 and Bark 3.0 Plus ANE packages.
/// `root` contains BarkEncoder.mlpackage (or .mlmodelc), decoder.npz and vocab.json.
/// Input is mono, 16 kHz normalized Float audio. The caller owns microphone conversion and model integrity checks.
public actor SmallBarkRecognizer {
    private let decoder: BarkDecoder
    private let frontend: BarkFrontend
    private var encoders: [Int: MLModel]
    private let compiledEncoder: URL

    public init(root: URL) throws {
        guard root.isFileURL else { throw SmallBarkError.invalid("A local model directory is required") }
        let archive = try ArrayArchive(url: root.appendingPathComponent("decoder.npz"))
        let vocabularyURL = root.appendingPathComponent("vocab.json")
        let vocabularyData = try Data(contentsOf: vocabularyURL)
        guard vocabularyData.count <= 4 * 1024 * 1024 else { throw SmallBarkError.invalid("Vocabulary exceeds size budget") }
        let vocabulary = try JSONDecoder().decode(BarkVocabulary.self, from: vocabularyData)
        decoder = try BarkDecoder(archive: archive, vocabulary: vocabulary)
        guard decoder.outputWidth == 640 else { throw SmallBarkError.invalid("Bark encoder requires 640-wide joint features") }
        frontend = try BarkFrontend(mel: archive.tensor("mel_filters"))
        compiledEncoder = try Self.compiledEncoder(root: root)
        // Be ready for short dictation without specializing the unused long function.
        encoders = [8: try Self.loadEncoder(at: compiledEncoder, window: 8)]
    }

    private static func compiledEncoder(root: URL) throws -> URL {
        let fm = FileManager.default
        let cached = root.appendingPathComponent("BarkEncoder.mlmodelc")
        var isDirectory: ObjCBool = false
        if !fm.fileExists(atPath: cached.path, isDirectory: &isDirectory) {
            let package = root.appendingPathComponent("BarkEncoder.mlpackage")
            guard fm.fileExists(atPath: package.path) else {
                throw SmallBarkError.invalid("BarkEncoder.mlpackage is missing")
            }
            let temporary = try MLModel.compileModel(at: package)
            // Stage inside the identity-pinned model directory so final publication is a same-volume rename.
            let staging = root.appendingPathComponent(".BarkEncoder-\(UUID().uuidString).mlmodelc")
            defer {
                try? fm.removeItem(at: temporary)
                try? fm.removeItem(at: staging)
            }
            try fm.copyItem(at: temporary, to: staging)
            do {
                try fm.moveItem(at: staging, to: cached)
            } catch {
                // Another worker may have atomically published the same identity's cache. Never overwrite it.
                var winnerIsDirectory: ObjCBool = false
                guard fm.fileExists(atPath: cached.path, isDirectory: &winnerIsDirectory), winnerIsDirectory.boolValue else { throw error }
            }
        } else if !isDirectory.boolValue {
            throw SmallBarkError.invalid("Compiled encoder cache is not a directory")
        }
        return cached
    }

    private static func loadEncoder(at url: URL, window: Int) throws -> MLModel {
        try Task.checkCancellation()
        let trace = ProcessInfo.processInfo.environment["DU_MODEL_LOAD_TIMINGS"] == "1"
        let start = ProcessInfo.processInfo.systemUptime
        if trace { FileHandle.standardError.write(Data("[model-load] begin w\(window)\n".utf8)) }
        let configuration = MLModelConfiguration()
        configuration.computeUnits = .cpuAndNeuralEngine
        configuration.functionName = "w\(window)"
        let model = try MLModel(contentsOf: url, configuration: configuration)
        if trace { FileHandle.standardError.write(Data("[model-load] ready w\(window) seconds=\(ProcessInfo.processInfo.systemUptime - start)\n".utf8)) }
        try Task.checkCancellation()
        return model
    }

    private func encoder(for window: Int) throws -> MLModel {
        if let existing = encoders[window] { return existing }
        let model = try Self.loadEncoder(at: compiledEncoder, window: window)
        encoders[window] = model
        return model
    }

    public func transcribe(_ samples: [Float]) async throws -> String {
        try Task.checkCancellation()
        guard !samples.isEmpty, samples.allSatisfy(\.isFinite) else {
            throw SmallBarkError.invalid("Expected nonempty, finite mono 16 kHz audio")
        }
        // Bounds the pre-emphasis/FFT range and avoids overflow for accidentally unnormalized PCM.
        guard samples.allSatisfy({ abs($0) <= 16 }) else {
            throw SmallBarkError.invalid("Expected normalized floating-point audio, not integer PCM values")
        }
        var texts: [String] = []
        for range in barkSegments(samples) {
            try Task.checkCancellation()
            let padded = [Float](repeating: 0, count: 4_000) + samples[range]
            let window = padded.count <= 128_000 ? 8 : 15
            let featureCount = window * 100 + 1
            guard padded.count <= window * 16_000 else { throw SmallBarkError.invalid("Audio segment exceeds encoder window") }
            let extracted = try frontend(padded)
            guard extracted.frames <= featureCount, extracted.valid <= featureCount else {
                throw SmallBarkError.invalid("Audio features exceed encoder window")
            }
            let features = try MLMultiArray(shape: [1, NSNumber(value: featureCount), 128], dataType: .float16)
            let mask = try MLMultiArray(shape: [1, NSNumber(value: featureCount)], dataType: .int32)
            let featurePointer = features.dataPointer.bindMemory(to: Float16.self, capacity: features.count)
            let maskPointer = mask.dataPointer.bindMemory(to: Int32.self, capacity: mask.count)
            for i in 0..<features.count { featurePointer[i] = 0 }
            for i in 0..<mask.count { maskPointer[i] = i < extracted.valid ? 1 : 0 }
            for i in extracted.features.indices { featurePointer[i] = Float16(extracted.features[i]) }
            let input = try MLDictionaryFeatureProvider(dictionary: ["features": features, "mask": mask])
            let model = try encoder(for: window)
            let result = try await model.prediction(from: input)
            try Task.checkCancellation()
            guard let encoded = result.featureValue(for: "encoded")?.multiArrayValue,
                  encoded.shape.count == 3, encoded.shape[0].intValue == 1,
                  encoded.shape[2].intValue == decoder.outputWidth else {
                throw SmallBarkError.invalid("Unexpected Core ML encoder output shape")
            }
            var frames = extracted.valid
            for _ in 0..<3 { frames = (frames + 1) / 2 }
            guard encoded.shape[1].intValue >= frames else { throw SmallBarkError.invalid("Encoder output is too short") }
            var flat = [Float](repeating: 0, count: frames * decoder.outputWidth)
            let frameStride = encoded.strides[1].intValue
            let channelStride = encoded.strides[2].intValue
            for frame in 0..<frames {
                for channel in 0..<decoder.outputWidth {
                    let index = frame * frameStride + channel * channelStride
                    let number: Float
                    switch encoded.dataType {
                    case .float16: number = Float(encoded.dataPointer.assumingMemoryBound(to: Float16.self)[index])
                    case .float32: number = encoded.dataPointer.assumingMemoryBound(to: Float.self)[index]
                    case .double: number = Float(encoded.dataPointer.assumingMemoryBound(to: Double.self)[index])
                    default: throw SmallBarkError.invalid("Unexpected encoder output data type")
                    }
                    flat[frame*decoder.outputWidth + channel] = number
                }
            }
            texts.append(decoder.text(try decoder.decode(flat, frames: frames)))
        }
        try Task.checkCancellation()
        return texts.joined(separator: " ").trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
