import AppKit
import AVFoundation
import DictateCore

@MainActor final class DictationSession: ObservableObject {
    enum Phase: String { case idle = "Ready", loading = "Loading model", requestingMicrophone = "Preparing microphone", testingMicrophone = "Testing microphone", recording = "Listening", transcribing = "Transcribing", delivering = "Delivering text", cancelling = "Cancelling" }
    @Published var phase: Phase = .idle
    @Published var message = "Download and load a model to begin."
    @Published var transcript = ""
    @Published var level: Float = 0
    @Published var seconds: Double = 0
    @Published var loadedID: String?
    @Published var language = UserDefaults.standard.string(forKey:"transcriptionLanguage") ?? "auto" {
        didSet { UserDefaults.standard.set(language,forKey:"transcriptionLanguage") }
    }
    var supportsLanguageSelection: Bool { loadedID?.hasPrefix("whisper-") == true }
    var recognitionLanguage: String? { supportsLanguageSelection ? (language == "auto" ? nil : language) : "en" }
    @Published private(set) var lastDictation = ""
    var canRecover: Bool { !lastDictation.isEmpty && !busy }
    var meter: Double { min(1,max(0,(20 * log10(max(Double(level),0.000001)) + 60) / 60)) }
    private var holdActive = false
    private var testing = false
    private var peakLevel: Float = 0
    private let resolveInput: () throws -> UInt32?
    private let correct: (String) -> String
    private let microphoneAccess: () async -> Bool
    @Published var overlayStyle = UserDefaults.standard.string(forKey: "overlay") ?? "notch" { didSet { UserDefaults.standard.set(overlayStyle, forKey: "overlay") } }
    @Published var expanded = UserDefaults.standard.bool(forKey: "expanded") { didSet { UserDefaults.standard.set(expanded, forKey: "expanded") } }
    private let capture = AudioCapture()
    let recognition = Recognition()
    private var timer: Timer?
    private var work: Task<Void, Never>?
    private var target: TextInsertion.Target?
    private var watchdog: CaptureWatchdog?
    var stateChanged: (() -> Void)?
    var busy: Bool { phase != .idle }
    init(resolveInput: @escaping () throws -> UInt32? = { nil }, correct: @escaping (String) -> String = { $0 }, microphoneAccess: @escaping () async -> Bool = { await AVCaptureDevice.requestAccess(for:.audio) }) {
        self.resolveInput=resolveInput;self.correct=correct;self.microphoneAccess=microphoneAccess
        if !TranscriptionLanguage.valid(language) { language="auto" }
        capture.onInterruption = { [weak self] in
            guard let self, self.phase == .recording || self.phase == .testingMicrophone else { return }
            self.interrupt("Microphone input changed. Recording discarded; start again when your input is ready.")
        }
    }
    func restoreSelection(store: ModelStore) {
        guard let id = UserDefaults.standard.string(forKey: "selectedModel") else { return }
        guard let model = store.models.first(where: { $0.id == id }), store.installed.contains(id) else {
            message = "Your selected model is not installed. Choose a model in Models."
            return
        }
        load(model, store: store)
    }
    func interrupt(_ reason: String) {
        guard busy, phase != .delivering else { return }
        cancel()
        message = reason
    }
    func load(_ model: BarkModel, store: ModelStore) {
        guard !busy, store.installed.contains(model.id) else { return }
        phase = .loading; loadedID = nil; message = "Checking and compiling \(model.name). First load may take a few minutes."; stateChanged?()
        work = Task {
            do {
                try await store.validate(model)
                try Task.checkCancellation()
                try await recognition.prepare(model, root: store.directory(model))
                try Task.checkCancellation()
                loadedID = model.id; UserDefaults.standard.set(model.id, forKey: "selectedModel")
                message = "\(model.name) is ready."
            } catch is CancellationError { message = "Loading cancelled." }
            catch { message = error.localizedDescription }
            phase = .idle; work = nil; stateChanged?()
        }
    }
    func beginHold() {
        guard phase == .idle, loadedID != nil else { return }
        holdActive=true;startCapture(test:false)
    }
    func endHold() {
        guard holdActive else { return }
        holdActive=false
        if phase == .recording { finish() } else if phase == .requestingMicrophone { cancel() }
    }
    func toggle() {
        if phase == .recording { finish(); return }
        guard phase == .idle, loadedID != nil else { if !busy { message="Load a downloaded model first." };return }
        startCapture(test:false)
    }
    func testMicrophone() {
        guard !busy else { return }
        startCapture(test:true)
    }
    private func startCapture(test: Bool) {
        testing=test;peakLevel=0
        target=test ? nil : TextInsertion.capture()
        phase = .requestingMicrophone; message = "Preparing microphone access…"; stateChanged?()
        work = Task {
            let allowed = await microphoneAccess()
            if Task.isCancelled { target=nil;holdActive=false;phase = .idle;work=nil;stateChanged?();return }
            guard allowed else { target=nil;holdActive=false;phase = .idle;message="Microphone access is required. Enable Dictate Unlimited in System Settings → Privacy & Security → Microphone.";work=nil;stateChanged?();return }
            do {
                try await capture.start(deviceID:try resolveInput(), monitoring:test)
                try Task.checkCancellation()
                watchdog=CaptureWatchdog(now:ProcessInfo.processInfo.systemUptime)
                if !test { transcript="" }
                seconds=0;phase=test ? .testingMicrophone : .recording
                message=test ? "Speak to test your microphone. Stops after five seconds; nothing is transcribed or saved." : "Listening locally. Use your shortcut to finish, or Cancel."
                timer=Timer(timeInterval:0.05,repeats:true) { [weak self] _ in
                    Task { @MainActor in
                        guard let self,self.phase == .recording || self.phase == .testingMicrophone else { return }
                        let snapshot=self.capture.snapshot();self.level=snapshot.level;self.peakLevel=max(self.peakLevel,snapshot.level);self.seconds=Double(snapshot.count)/16000
                        if self.watchdog?.stalled(sampleCount:snapshot.count,now:ProcessInfo.processInfo.systemUptime)==true { self.interrupt("Microphone input stopped. Recording discarded; check your input and start again.");return }
                        if self.testing && self.seconds >= 5 { self.finishMicrophoneTest() }
                        else if !self.testing && self.seconds >= Double(AudioLimits.maximumSeconds) { self.finish() }
                    }
                }
                if let timer { RunLoop.main.add(timer,forMode:.common) }
                stateChanged?()
            } catch { capture.cancel();target=nil;holdActive=false;phase = .idle;message=error is CancellationError ? "Microphone preparation cancelled." : error.localizedDescription;stateChanged?() }
            work=nil
        }
    }
    private func finishMicrophoneTest() {
        timer?.invalidate();timer=nil;watchdog=nil;capture.cancel();level=0;phase = .idle;testing=false
        message=peakLevel >= 0.001 ? "Microphone test complete: audio signal detected. Ready for dictation." : "Microphone test complete: no clear input signal. Check the selected input, mute and volume."
        stateChanged?()
    }
    func clearTranscript() { guard !busy else { return };transcript="";lastDictation="" }
    func pasteLast() {
        guard canRecover else { return }
        let destination=TextInsertion.capture();let text=lastDictation
        transcript=text;phase = .delivering;message="Pasting last completed dictation…";stateChanged?()
        work=Task {
            message=await TextInsertion.insert(text,into:destination)
            phase = .idle;work=nil;stateChanged?()
        }
    }
    func finish() {
        guard phase == .recording else { return }
        holdActive=false
        timer?.invalidate(); timer = nil; watchdog = nil
        do {
            let audio = try capture.stop(); level = 0; phase = .transcribing; message = "Transcribing on this Mac…"; stateChanged?()
            work = Task {
                defer { target = nil }
                do {
                    let result = try await recognition.transcribe(audio, language: recognitionLanguage)
                    try Task.checkCancellation()
                    transcript = correct(result.trimmingCharacters(in: .whitespacesAndNewlines))
                    if transcript.isEmpty { message = "No speech detected. Try again." }
                    else {
                        lastDictation=transcript
                        phase = .delivering; message = "Delivering text…"; stateChanged?()
                        message = await TextInsertion.insert(transcript, into: target)
                    }
                } catch is CancellationError { message = "Cancelled. Nothing was inserted." }
                catch { message = error.localizedDescription }
                phase = .idle; work = nil; stateChanged?()
            }
        } catch { target = nil; phase = .idle; message = error.localizedDescription; stateChanged?() }
    }
    func cancel() {
        guard phase != .delivering else { return }
        timer?.invalidate(); timer = nil; watchdog = nil
        holdActive=false
        if phase == .testingMicrophone { capture.cancel();target=nil;phase = .idle;level=0;testing=false;message="Microphone test stopped. Nothing was saved." }
        else if phase == .recording { capture.cancel(); target = nil; phase = .idle; level = 0; transcript = ""; message = "Recording discarded." }
        else if work != nil { target = nil; work?.cancel(); phase = .cancelling; message = "Cancelling after the current local operation finishes…" }
        stateChanged?()
    }
    func copy() { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(transcript, forType: .string); message = "Copied. Clipboard contents were replaced at your request." }
}
