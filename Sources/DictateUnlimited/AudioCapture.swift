import AVFoundation
import Foundation
import CoreAudio
import AudioToolbox
import DictateCore

final class AudioCapture: @unchecked Sendable {
    private let engineQueue = DispatchQueue(label: "com.doomade.dictate.capture", qos: .userInitiated)
    // Native AVAudioEngine calls are serialized here, never on the main actor.
    private var engine: AVAudioEngine?
    private var engineGeneration: UInt64?
    private var tappedInput: AVAudioInputNode?
    private let startupTimeout: TimeInterval
    private let prepareDevice: @Sendable () -> Void
    init(startupTimeout:TimeInterval = 10, prepareDevice:@escaping @Sendable () -> Void = {}) {
        self.startupTimeout=startupTimeout;self.prepareDevice=prepareDevice
    }
    private let lock = NSLock()
    private var samples: [Float] = []
    private var level: Float = 0
    private var count = 0
    private var generation: UInt64 = 0
    private var accepting = false
    private var conversionError: String?
    private var running = false
    private var starting = false
    private var startGate: AudioStartGate?
    @MainActor var onInterruption: (() -> Void)?
    private var configurationObserver: NSObjectProtocol?
    deinit { if let configurationObserver { NotificationCenter.default.removeObserver(configurationObserver) } }
    func start(deviceID: UInt32? = nil, monitoring: Bool = false) async throws {
        let gate=AudioStartGate()
        let token: UInt64 = try reserveStart(gate)
        try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { continuation in
                gate.install(continuation)
                engineQueue.async { [self] in
                    defer { lock.lock();starting=false;lock.unlock() }
                    do {
                        try checkGeneration(token)
                        try startEngine(deviceID:deviceID,monitoring:monitoring,token:token)
                        try checkGeneration(token)
                        if !gate.finish(.success(())) { stopEngine(token:token) }
                    } catch {
                        // Resolve the caller before teardown, which can itself block in Core Audio.
                        invalidate(token)
                        _ = gate.finish(.failure(error))
                        stopEngine()
                    }
                }
                DispatchQueue.global(qos:.utility).asyncAfter(deadline:.now()+startupTimeout) { [self] in
                    if gate.finish(.failure(AppError("Microphone setup stalled. Restart Dictate Unlimited and check your input device before trying again."))) {
                        invalidate(token)
                        engineQueue.async { [self] in stopEngine(token:token) }
                    }
                }
            }
        }, onCancel: { [self] in
            invalidate(token)
            _ = gate.finish(.failure(CancellationError()))
            engineQueue.async { [self] in stopEngine(token:token) }
        })
    }
    private func reserveStart(_ gate: AudioStartGate) throws -> UInt64 {
        lock.lock();defer { lock.unlock() }
        guard !starting,!accepting else { throw AppError("Microphone setup is still finishing. Restart the app if the device remains unresponsive.") }
        starting=true;generation &+= 1;startGate=gate
        samples=[];count=0;level=0;conversionError=nil
        return generation
    }
    private func checkGeneration(_ token:UInt64) throws {
        lock.lock();defer { lock.unlock() }
        if generation != token { throw CancellationError() }
    }
    private func invalidate(_ token:UInt64) {
        lock.lock();defer { lock.unlock() }
        if generation == token { generation &+= 1;accepting=false;samples=[];count=0;level=0 }
    }
    private func startEngine(deviceID:UInt32?,monitoring:Bool,token:UInt64) throws {
        stopEngine()
        prepareDevice()
        try checkGeneration(token)
        let engine = AVAudioEngine()
        self.engine = engine;engineGeneration=token
        let input = engine.inputNode
        if var deviceID {
            guard let unit=input.audioUnit else { throw AppError("Microphone input unit is unavailable.") }
            var current:UInt32=0;var size=UInt32(MemoryLayout<UInt32>.size)
            let read=AudioUnitGetProperty(unit,kAudioOutputUnitProperty_CurrentDevice,kAudioUnitScope_Global,0,&current,&size)
            if read != noErr || current != deviceID {
                let status=AudioUnitSetProperty(unit,kAudioOutputUnitProperty_CurrentDevice,kAudioUnitScope_Global,0,&deviceID,UInt32(MemoryLayout<UInt32>.size))
                guard status==noErr else { throw AppError("Cannot use the selected microphone (\(status)). Refresh inputs and try again.") }
            }
        }
        try checkGeneration(token)
        let source = input.outputFormat(forBus: 0)
        guard source.sampleRate > 0, source.channelCount > 0,
              let target = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16000, channels: 1, interleaved: false),
              let converter = AVAudioConverter(from: source, to: target) else { throw AppError("No usable microphone input. Check System Settings → Sound.") }
        try checkGeneration(token)
        let activeGeneration=token
        input.installTap(onBus: 0, bufferSize: 4096, format: source) { [weak self] buffer, _ in
            guard let self else { return }
            let capacity = AVAudioFrameCount(ceil(Double(buffer.frameLength) * 16000 / source.sampleRate) + 64)
            guard let output = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: capacity) else { return }
            var supplied = false; var error: NSError?
            converter.convert(to: output, error: &error) { _, status in
                if supplied { status.pointee = .noDataNow; return nil }
                supplied = true; status.pointee = .haveData; return buffer
            }
            self.lock.lock(); defer { self.lock.unlock() }
            guard self.accepting, self.generation == activeGeneration else { return }
            if let error { self.conversionError = error.localizedDescription; return }
            if let ptr = output.floatChannelData?[0] {
                let n = Int(output.frameLength)
                let remaining = AudioLimits.sampleRate * (monitoring ? 5 : AudioLimits.maximumSeconds) - self.count
                let values = Array(UnsafeBufferPointer(start: ptr, count: min(n, max(remaining, 0))))
                if !monitoring { self.samples.append(contentsOf: values) }
                self.count += values.count
                self.level = values.isEmpty ? 0 : sqrt(values.reduce(0) { $0 + $1 * $1 } / Float(values.count))
            }
        }
        tappedInput=input
        do {
            try checkGeneration(token)
            lock.lock();accepting = generation == token;lock.unlock()
            try engine.start(); running = true
            try checkGeneration(token)
            configurationObserver = NotificationCenter.default.addObserver(forName:.AVAudioEngineConfigurationChange,object:engine,queue:nil) { [weak self] _ in
                guard let self else { return }
                self.engineQueue.async { [weak self] in
                    guard let self, self.engineGeneration == activeGeneration,
                          let engine=self.engine, !engine.isRunning else { return }
                    Task { @MainActor [weak self] in
                        guard let self, self.isAccepting(activeGeneration) else { return }
                        self.onInterruption?()
                    }
                }
            }
        }
    }
    func snapshot() -> (count: Int, level: Float) { lock.lock(); defer { lock.unlock() }; return (count, level) }
    private func isAccepting(_ token:UInt64) -> Bool {
        lock.lock();defer { lock.unlock() };return accepting && generation == token
    }
    private func stopEngine(token:UInt64? = nil) {
        if let token,engineGeneration != token { return }
        if let observer=configurationObserver { NotificationCenter.default.removeObserver(observer);configurationObserver=nil }
        let wasRunning=running;running=false
        if wasRunning { engine?.stop() }
        tappedInput?.removeTap(onBus:0);tappedInput=nil
        engine=nil;engineGeneration=nil
    }
    func stop() throws -> [Float] {
        lock.lock()
        let token=generation
        accepting=false;generation &+= 1
        let result=samples;let error=conversionError;let gate=startGate;startGate=nil
        samples=[];count=0;level=0
        lock.unlock()
        _ = gate?.finish(.failure(CancellationError()))
        engineQueue.async { [self] in stopEngine(token:token) }
        if let error { throw AppError(error) }
        return result
    }
    func cancel() { _ = try? stop() }
}

/// Exactly-once completion even if native startup outlives cancellation/timeout.
final class AudioStartGate: @unchecked Sendable {
    private let lock=NSLock()
    private var continuation: CheckedContinuation<Void,Error>?
    private var result: Result<Void,Error>?
    func install(_ continuation:CheckedContinuation<Void,Error>) {
        lock.lock()
        if let result { lock.unlock();continuation.resume(with:result) }
        else { self.continuation=continuation;lock.unlock() }
    }
    @discardableResult func finish(_ result:Result<Void,Error>) -> Bool {
        lock.lock()
        guard self.result == nil else { lock.unlock();return false }
        self.result=result;let continuation=self.continuation;self.continuation=nil
        lock.unlock();continuation?.resume(with:result);return true
    }
}
