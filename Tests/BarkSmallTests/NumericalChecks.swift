#if DEBUG
import Foundation
@testable import BarkSmall

struct BarkSmallNumericalChecks {
    private func npy(_ descr: String, shape: String, body: [UInt8], order: String = "False") -> Data {
        var header = "{'descr': '\(descr)', 'fortran_order': \(order), 'shape': \(shape), }"
        while (10 + header.utf8.count + 1) % 16 != 0 { header += " " }
        header += "\n"
        let length = header.utf8.count
        return Data([0x93,0x4e,0x55,0x4d,0x50,0x59,1,0,UInt8(length&255),UInt8(length>>8)] + Array(header.utf8) + body)
    }
    func testNumericNPYAndRejectUnsafeInputs() throws {
        let half = try ArrayArchive.npy(npy("<f2", shape: "(2,)", body: [0,0x3c,0,0xc0]))
        try checkEqual(half.shape,[2]); try checkEqual(half.values,[1,-2])
        let quantized = try ArrayArchive.npy(npy("|i1", shape: "(2,)", body: [255,127]))
        try checkEqual(quantized.values,[-1,127])
        try checkThrows(try ArrayArchive.npy(npy("|O8", shape: "(1,)", body: Array(repeating:0,count:8))))
        try checkThrows(try ArrayArchive.npy(npy("<f4", shape: "(2,)", body: [0,0,0,0])))
        try checkThrows(try ArrayArchive.npy(npy("<f4", shape: "(1,)", body: [0,0,0,0],order:"True")))
        try checkThrows(try ArrayArchive.npy(npy("<f4", shape: "(99999999999999,)", body: [])))
        try checkThrows(try ArrayArchive.npy(npy("<f4", shape: "(1,)", body: [0,0,0x80,0x7f])))
    }
    func testRowwiseDequantization() throws {
        let archive = ArrayArchive(arrays: ["w.q":Tensor(shape:[2,2],values:[-2,3,4,-5]),"w.s":Tensor(shape:[2],values:[0.5,2])])
        try checkEqual(try archive.weight("w").values,[-1,1.5,8,-10])
        try checkThrows(try archive.tensor("missing"))
    }
    func testSegmentationIsContiguousBoundedAndFindsSilence() throws {
        var samples = [Float](repeating:0.5,count:500_000)
        for i in 160_000..<176_000 { samples[i] = 0 }
        let ranges = barkSegments(samples)
        try checkEqual(ranges.first?.lowerBound,0)
        try checkEqual(ranges.last?.upperBound,samples.count)
        try checkTrue(ranges.allSatisfy { $0.count > 0 && $0.count <= 236_000 })
        try checkTrue((160_000..<176_000).contains(ranges[0].upperBound))
        for (a,b) in zip(ranges,ranges.dropFirst()) { try checkEqual(a.upperBound,b.lowerBound) }
        try checkEqual(barkSegments([Float](repeating:0,count:236_000)),[0..<236_000])
    }
    func testFrontendAgainstIndependentSlowDFT() throws {
        // Sparse synthetic mel filters make the expected projection unambiguous.
        // Slow scalar DFT provides an independent numerical oracle for Accelerate's FFT.
        var filters = [Float](repeating:0,count:128*257)
        for band in 0..<128 { filters[band*257+band+1] = 1 }
        let frontend = try BarkFrontend(mel: Tensor(shape:[128,257],values:filters))
        let signal = (0..<1600).map { Float(0.4*sin(Double($0)*0.071) + 0.2*cos(Double($0)*0.033)) }
        let actual = try frontend(signal)
        try checkEqual(actual.frames,11); try checkEqual(actual.valid,10)
        var reference = [Float](repeating:0,count:11*128)
        for frame in 0..<11 {
            for band in 0..<128 {
                let bin = band+1
                var re=0.0, im=0.0
                for k in 56..<456 {
                    let sampleIndex = frame*160-256+k
                    if sampleIndex < 0 || sampleIndex >= signal.count { continue }
                    let emphasized: Float = sampleIndex == 0 ? signal[0] : signal[sampleIndex] - 0.97*signal[sampleIndex-1]
                    let window = Float(0.5-0.5*cos(2*Double.pi*Double(k-56)/399))
                    let sample = Double(emphasized*window)
                    let phase = 2*Double.pi*Double(bin*k)/512
                    re += sample*cos(phase); im -= sample*sin(phase)
                }
                reference[frame*128+band] = logf(Float(re*re+im*im)+Float(pow(2.0,-24)))
            }
        }
        for band in 0..<128 {
            let observations = (0..<10).map { reference[$0*128+band] }
            let mean = observations.reduce(Float(0),+)/10
            let variance = observations.reduce(Float(0)) { $0+($1-mean)*($1-mean) }/9
            for frame in 0..<10 {
                let expected = (reference[frame*128+band]-mean)/(sqrtf(variance)+1e-5)
                try checkEqual(actual.features[frame*128+band],expected,accuracy:0.0003)
            }
            try checkEqual(actual.features[10*128+band],0)
        }
    }
    func testSilenceFeaturesRemainFinite() throws {
        let frontend = try BarkFrontend(mel:Tensor(shape:[128,257],values:Array(repeating:1,count:128*257)))
        let result = try frontend(Array(repeating:0,count:4001))
        try checkTrue(result.features.allSatisfy(\.isFinite))
        // Float32 mean accumulation may leave a small constant residual, as in NumPy.
        for frame in 1..<result.valid {
            for band in 0..<128 { try checkEqual(result.features[frame*128+band],result.features[band]) }
        }
        try checkThrows(try frontend([]))
        try checkThrows(try frontend([.nan]))
    }
    private func decoder(tokenBias: [Float], durationBias: [Float]) throws -> BarkDecoder {
        let vocab = BarkVocabulary(vocabSize:3,blankID:2,durations:[0,2],maxSymbolsPerStep:2,pieces:["▁a","b"],specialIDs:[2])
        var arrays:[String:Tensor] = [
            "decoder.embedding.weight":Tensor(shape:[3,1],values:[0,0,0]),
            "decoder.decoder_projector.weight":Tensor(shape:[1,1],values:[0]),
            "decoder.decoder_projector.bias":Tensor(shape:[1],values:[0]),
            "joint.head.weight":Tensor(shape:[5,1],values:Array(repeating:0,count:5)),
            "joint.head.bias":Tensor(shape:[5],values:tokenBias+durationBias)
        ]
        for i in 0..<2 {
            for name in ["weight_ih", "weight_hh"] { arrays["decoder.lstm.\(name)_l\(i)"] = Tensor(shape:[4,1],values:Array(repeating:0,count:4)) }
            for name in ["bias_ih", "bias_hh"] { arrays["decoder.lstm.\(name)_l\(i)"] = Tensor(shape:[4],values:Array(repeating:0,count:4)) }
        }
        return try BarkDecoder(archive:ArrayArchive(arrays:arrays),vocabulary:vocab)
    }
    func testTDTZeroDurationIsBoundedAndBlankAdvances() throws {
        let repeated = try decoder(tokenBias:[1,0,-1],durationBias:[1,0])
        try checkEqual(try repeated.decode([0,0,0],frames:3),[0,0,0,0,0,0])
        let blank = try decoder(tokenBias:[0,0,1],durationBias:[1,0])
        try checkEqual(try blank.decode([0,0,0],frames:3),[])
        let skip = try decoder(tokenBias:[0,1,-1],durationBias:[0,1])
        try checkEqual(try skip.decode([0,0,0],frames:3),[1,1])
        try checkEqual(repeated.text([0,1,2]),"ab")
        try checkThrows(try repeated.decode([.infinity],frames:1))
    }
}

private struct CheckFailure: Error, CustomStringConvertible { let description: String }
private func checkTrue(_ value: @autoclosure () -> Bool, file: StaticString = #fileID, line: UInt = #line) throws {
    guard value() else { throw CheckFailure(description: "Condition failed at \(file):\(line)") }
}
private func checkEqual<T: Equatable>(_ a: T, _ b: T, file: StaticString = #fileID, line: UInt = #line) throws {
    guard a == b else { throw CheckFailure(description: "Equality failed: \(a) != \(b) at \(file):\(line)") }
}
private func checkEqual<T: BinaryFloatingPoint>(_ a: T, _ b: T, accuracy: T, file: StaticString = #fileID, line: UInt = #line) throws {
    guard abs(a-b) <= accuracy else { throw CheckFailure(description: "Tolerance failed: \(a) != \(b) at \(file):\(line)") }
}
private func checkThrows<T>(_ expression: @autoclosure () throws -> T, file: StaticString = #fileID, line: UInt = #line) throws {
    do { _ = try expression() } catch { return }
    throw CheckFailure(description: "Expected error at \(file):\(line)")
}

#endif
