// SPDX-License-Identifier: CC-BY-4.0
// Adapted from Conway Research Bark; see ATTRIBUTION.md for source and changes.
// Adapted algorithm: Conway Research Bark 3.0 coreml/ane/bark_coreml.py, CC-BY-4.0.
// See ATTRIBUTION.md in this directory. This Swift port has not inherited any Resonant code.
import Foundation
import Accelerate

final class BarkFrontend {
    private let mel: [Float]
    private let window: [Float]
    private let fft: vDSP_DFT_SetupD
    init(mel: Tensor) throws {
        guard mel.shape == [128, 257] else { throw SmallBarkError.invalid("Expected mel_filters [128,257]") }
        self.mel = mel.values
        var window = [Float](repeating: 0, count: 512)
        for n in 0..<400 { window[n + 56] = Float(0.5 - 0.5 * cos(2 * Double.pi * Double(n) / 399)) }
        self.window = window
        guard let fft = vDSP_DFT_zop_CreateSetupD(nil, 512, .FORWARD) else { throw SmallBarkError.invalid("Cannot create audio FFT") }
        self.fft = fft
    }
    deinit { vDSP_DFT_DestroySetupD(fft) }

    func callAsFunction(_ samples: [Float]) throws -> (features: [Float], frames: Int, valid: Int) {
        guard !samples.isEmpty, samples.allSatisfy(\.isFinite) else { throw SmallBarkError.invalid("Audio must be nonempty and finite") }
        let length = samples.count
        let frames = 1 + length / 160
        let valid = length / 160
        guard valid > 0 else { throw SmallBarkError.invalid("Insufficient audio frames") }
        var emphasized = samples
        for i in 1..<length { emphasized[i] = samples[i] - 0.97 * samples[i-1] }
        var features = [Float](repeating: 0, count: frames * 128)
        var real = [Double](repeating: 0, count: 512)
        let imaginary = [Double](repeating: 0, count: 512)
        var spectrumReal = real, spectrumImaginary = real
        var power = [Float](repeating: 0, count: 257)
        var filtered = [Float](repeating: 0, count: 128)
        for frame in 0..<frames {
            if frame % 32 == 0 { try Task.checkCancellation() }
            let start = frame * 160 - 256
            for i in 0..<512 {
                let j = start + i
                real[i] = (j >= 0 && j < length) ? Double(emphasized[j] * window[i]) : 0
            }
            vDSP_DFT_ExecuteD(fft, real, imaginary, &spectrumReal, &spectrumImaginary)
            for i in 0..<257 { power[i] = Float(spectrumReal[i] * spectrumReal[i] + spectrumImaginary[i] * spectrumImaginary[i]) }
            vDSP_mmul(mel, 1, power, 1, &filtered, 1, 128, 1, 257)
            for band in 0..<128 { features[frame*128 + band] = logf(filtered[band] + Float(pow(2.0, -24.0))) }
        }
        for band in 0..<128 {
            var mean: Float = 0
            for frame in 0..<valid { mean += features[frame*128 + band] }
            mean /= Float(valid)
            var variance: Float = 0
            for frame in 0..<valid { let delta = features[frame*128 + band] - mean; variance += delta * delta }
            let denominator = sqrtf(variance / Float(max(1, valid-1))) + 1e-5
            for frame in 0..<valid { features[frame*128 + band] = (features[frame*128 + band] - mean) / denominator }
            for frame in valid..<frames { features[frame*128 + band] = 0 }
        }
        guard features.allSatisfy(\.isFinite) else { throw SmallBarkError.invalid("Non-finite audio features") }
        return (features, frames, valid)
    }
}

/// Source reference cuts within [5s,14.75s] at the quietest smoothed 200ms energy span.
func barkSegments(_ wave: [Float], maximumSamples: Int = 236_000) -> [Range<Int>] {
    if wave.count <= maximumSamples { return [0..<wave.count] }
    let energyFrames = wave.count / 160
    var raw = [Float](repeating: 0, count: energyFrames)
    for frame in 0..<energyFrames {
        var sum: Float = 0
        for i in 0..<160 { let v = wave[frame*160+i]; sum += v*v }
        raw[frame] = sum / 160
    }
    // NumPy convolve(mode="same") with an even, length-20 kernel centers at i-10...i+9.
    var energy = [Double](repeating: 0, count: energyFrames)
    for i in 0..<energyFrames {
        var sum = 0.0
        for j in max(0,i-10)..<min(energyFrames,i+10) { sum += Double(raw[j]) }
        energy[i] = sum / 20
    }
    var result: [Range<Int>] = [], start = 0
    while wave.count - start > maximumSamples {
        let lo = (start + 80_000) / 160
        let hi = (start + maximumSamples) / 160
        var quietest = lo
        for i in (lo+1)..<hi { if energy[i] < energy[quietest] { quietest = i } }
        let cut = quietest * 160 + 80
        result.append(start..<cut); start = cut
    }
    result.append(start..<wave.count)
    return result
}
