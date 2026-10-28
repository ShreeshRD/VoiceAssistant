// SPDX-License-Identifier: CC-BY-4.0
// Adapted from Conway Research Bark; see ATTRIBUTION.md for source and changes.
// Adapted algorithm: Conway Research Bark 3.0 coreml/ane/bark_coreml.py, CC-BY-4.0.
// See ATTRIBUTION.md in this directory.
import Foundation
import Accelerate

struct BarkVocabulary: Decodable, Sendable {
    let vocabSize: Int
    let blankID: Int
    let durations: [Int]
    let maxSymbolsPerStep: Int
    let pieces: [String]
    let specialIDs: [Int]
    enum CodingKeys: String, CodingKey {
        case vocabSize = "vocab_size", blankID = "blank_id", durations
        case maxSymbolsPerStep = "max_symbols_per_step", pieces, specialIDs = "special_ids"
    }
}

struct Matrix: Sendable {
    let rows: Int, columns: Int
    let values: [Float]
    init(_ tensor: Tensor) throws {
        guard tensor.shape.count == 2, tensor.shape[0] > 0, tensor.shape[1] > 0,
              tensor.shape[0] <= Int(Int32.max), tensor.shape[1] <= Int(Int32.max),
              tensor.values.count == tensor.shape[0] * tensor.shape[1] else {
            throw SmallBarkError.invalid("Invalid decoder matrix")
        }
        rows = tensor.shape[0]; columns = tensor.shape[1]; values = tensor.values
    }
    func multiply(_ input: [Float]) -> [Float] {
        precondition(input.count == columns)
        var output = [Float](repeating: 0, count: rows)
        vDSP_mmul(values, 1, input, 1, &output, 1, vDSP_Length(rows), 1, vDSP_Length(columns))
        return output
    }
}

struct BarkDecoder: Sendable {
    struct Layer: Sendable { let input: Matrix, recurrent: Matrix, bias: [Float] }
    let vocabulary: BarkVocabulary
    private let embedding: Matrix
    private let layers: [Layer]
    private let projection: Matrix, projectionBias: [Float]
    private let head: Matrix, headBias: [Float]
    let outputWidth: Int

    init(archive: ArrayArchive, vocabulary: BarkVocabulary) throws {
        guard vocabulary.vocabSize > 0, vocabulary.vocabSize <= 100_000,
              (0..<vocabulary.vocabSize).contains(vocabulary.blankID),
              !vocabulary.durations.isEmpty, vocabulary.durations.count <= 32,
              vocabulary.durations.allSatisfy({ (0...100).contains($0) }),
              (1...1000).contains(vocabulary.maxSymbolsPerStep),
              vocabulary.pieces.count <= vocabulary.vocabSize else {
            throw SmallBarkError.invalid("Invalid vocabulary or TDT configuration")
        }
        self.vocabulary = vocabulary
        embedding = try Matrix(archive.weight("decoder.embedding.weight"))
        let hidden = embedding.columns
        guard embedding.rows == vocabulary.vocabSize else { throw SmallBarkError.invalid("Embedding and vocabulary size disagree") }
        func bias(_ name: String, count: Int) throws -> [Float] {
            let t = try archive.weight(name)
            guard t.shape == [count] else { throw SmallBarkError.invalid("Invalid bias \(name)") }
            return t.values
        }
        var layers: [Layer] = []
        for i in 0..<2 {
            let input = try Matrix(archive.weight("decoder.lstm.weight_ih_l\(i)"))
            let recurrent = try Matrix(archive.weight("decoder.lstm.weight_hh_l\(i)"))
            guard input.rows == hidden*4, input.columns == hidden,
                  recurrent.rows == hidden*4, recurrent.columns == hidden else {
                throw SmallBarkError.invalid("Invalid LSTM matrix shapes")
            }
            let a = try bias("decoder.lstm.bias_ih_l\(i)", count: hidden*4)
            let b = try bias("decoder.lstm.bias_hh_l\(i)", count: hidden*4)
            layers.append(Layer(input: input, recurrent: recurrent, bias: zip(a,b).map(+)))
        }
        self.layers = layers
        projection = try Matrix(archive.weight("decoder.decoder_projector.weight"))
        guard projection.columns == hidden else { throw SmallBarkError.invalid("Invalid decoder projection") }
        projectionBias = try bias("decoder.decoder_projector.bias", count: projection.rows)
        head = try Matrix(archive.weight("joint.head.weight"))
        guard head.columns == projection.rows, head.rows == vocabulary.vocabSize + vocabulary.durations.count else {
            throw SmallBarkError.invalid("Invalid joint-head dimensions")
        }
        headBias = try bias("joint.head.bias", count: head.rows)
        outputWidth = projection.rows
    }

    func decode(_ encoded: [Float], frames: Int) throws -> [Int] {
        guard frames >= 0, encoded.count == frames * outputWidth,
              encoded.allSatisfy(\.isFinite) else { throw SmallBarkError.invalid("Invalid encoder output") }
        let hidden = embedding.columns
        var state = Array(repeating: (h: [Float](repeating: 0, count: hidden), c: [Float](repeating: 0, count: hidden)), count: 2)
        func step(_ token: Int) throws -> [Float] {
            var x = Array(embedding.values[(token*hidden)..<((token+1)*hidden)])
            for layerIndex in 0..<2 {
                let layer = layers[layerIndex]
                let ih = layer.input.multiply(x)
                let hh = layer.recurrent.multiply(state[layerIndex].h)
                let gates = (0..<(hidden*4)).map { ih[$0] + hh[$0] + layer.bias[$0] }
                var h = [Float](repeating: 0, count: hidden), c = h
                for i in 0..<hidden {
                    let input = 1 / (1 + expf(-gates[i]))
                    let forget = 1 / (1 + expf(-gates[hidden+i]))
                    let candidate = tanhf(gates[2*hidden+i])
                    let output = 1 / (1 + expf(-gates[3*hidden+i]))
                    c[i] = forget * state[layerIndex].c[i] + input * candidate
                    h[i] = output * tanhf(c[i])
                }
                guard h.allSatisfy(\.isFinite), c.allSatisfy(\.isFinite) else { throw SmallBarkError.invalid("Non-finite decoder state") }
                state[layerIndex] = (h,c); x = h
            }
            return zip(projection.multiply(x), projectionBias).map(+)
        }
        var prediction = try step(vocabulary.blankID)
        var t = 0, output: [Int] = [], symbols = 0, iterations = 0
        while t < frames {
            if iterations % 16 == 0 { try Task.checkCancellation() }
            iterations += 1
            let joint = (0..<outputWidth).map { max(encoded[t*outputWidth+$0] + prediction[$0], 0) }
            let logits = zip(head.multiply(joint), headBias).map(+)
            guard logits.allSatisfy(\.isFinite) else { throw SmallBarkError.invalid("Non-finite joint logits") }
            // Strict > retains the first index on a tie, matching numpy.argmax.
            var token = 0, durationIndex = 0
            for i in 1..<vocabulary.vocabSize { if logits[i] > logits[token] { token = i } }
            for i in 1..<vocabulary.durations.count {
                if logits[vocabulary.vocabSize+i] > logits[vocabulary.vocabSize+durationIndex] { durationIndex = i }
            }
            var duration = vocabulary.durations[durationIndex]
            if token == vocabulary.blankID {
                t += max(duration, 1); symbols = 0
            } else {
                output.append(token); prediction = try step(token); symbols += 1
                if duration == 0 && symbols >= vocabulary.maxSymbolsPerStep { duration = 1 }
                if duration > 0 { symbols = 0 }
                t += duration
            }
        }
        return output
    }

    func text(_ tokens: [Int]) -> String {
        let special = Set(vocabulary.specialIDs)
        return tokens.filter { !special.contains($0) && $0 >= 0 && $0 < vocabulary.pieces.count }
            .map { vocabulary.pieces[$0] }.joined().replacingOccurrences(of: "▁", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
