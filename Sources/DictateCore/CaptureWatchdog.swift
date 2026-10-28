import Foundation

/// Uses monotonic time and received samples, so silence does not count as a stalled input.
public struct CaptureWatchdog {
    private var lastCount = 0
    private var lastProgress: TimeInterval
    public init(now: TimeInterval) { lastProgress = now }
    public mutating func stalled(sampleCount: Int, now: TimeInterval) -> Bool {
        if sampleCount != lastCount { lastCount = sampleCount; lastProgress = now }
        return now - lastProgress >= 3
    }
}
