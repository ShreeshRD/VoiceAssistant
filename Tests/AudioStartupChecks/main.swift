import Foundation
import DictateCore
struct AppError: LocalizedError { let text:String;init(_ text:String) { self.text=text };var errorDescription:String? { text } }
@main struct AudioStartupChecks {
    static func main() async throws {
        let gate=AudioStartGate()
        precondition(gate.finish(.failure(CancellationError())))
        do { try await withCheckedThrowingContinuation { gate.install($0) };preconditionFailure("Cancelled gate succeeded") } catch is CancellationError {}
        precondition(!gate.finish(.success(())))
        // Simulates a native setup call that outlives timeout. It must not block the caller,
        // allow overlapping startup, or start a microphone after eventually returning.
        let capture=AudioCapture(startupTimeout:0.04,prepareDevice:{Thread.sleep(forTimeInterval:0.3)})
        let start=Date()
        do { try await capture.start();preconditionFailure("Slow startup succeeded") }
        catch { precondition(error.localizedDescription.contains("stalled")) }
        precondition(Date().timeIntervalSince(start)<0.2)
        do { try await capture.start();preconditionFailure("Overlapping native startup accepted") }
        catch { precondition(error.localizedDescription.contains("still finishing")) }
        try await Task.sleep(nanoseconds:400_000_000)
        precondition(capture.snapshot().count==0)
        let cancelled=AudioCapture(startupTimeout:2,prepareDevice:{Thread.sleep(forTimeInterval:0.3)})
        let work=Task { try await cancelled.start() }
        try await Task.sleep(nanoseconds:20_000_000);let cancellation=Date();work.cancel()
        do { try await work.value;preconditionFailure("Cancelled startup succeeded") } catch is CancellationError {}
        precondition(Date().timeIntervalSince(cancellation)<0.2)
        try await Task.sleep(nanoseconds:400_000_000)
        precondition(cancelled.snapshot().count==0)
        print("PASS bounded native startup, overlap rejection, early cancellation and no late capture")
    }
}
