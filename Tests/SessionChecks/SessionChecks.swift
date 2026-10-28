// Compiles the production Session.swift with deterministic boundary doubles.
// These checks do not claim physical microphone, sleep or Accessibility coverage.
import AppKit
import DictateCore

struct AppError: LocalizedError { let text: String; init(_ text: String) { self.text = text }; var errorDescription: String? { text } }
@MainActor final class ModelStore {
    var models = try! ModelCatalog.load()
    var installed: Set<String> = ["bark", "bark-plus", "bark-pro"]
    var validationFails = false
    func directory(_ model: BarkModel) -> URL { URL(fileURLWithPath: "/unused-test-model") }
    func validate(_ model: BarkModel) async throws { if validationFails { throw AppError("Integrity check failed") } }
}
@MainActor final class AudioCapture {
    static var starts = 0
    var onInterruption: (() -> Void)?
    func start(deviceID: UInt32? = nil, monitoring: Bool = false) async throws { Self.starts += 1 }
    func snapshot() -> (count: Int, level: Float) { (16000, 0) }
    func stop() throws -> [Float] { [0, 0] }
    func cancel() {}
}
actor Recognition {
    func prepare(_ model: BarkModel, root: URL) async throws { try? await Task.sleep(nanoseconds: 40_000_000) }
    func transcribe(_ samples: [Float], language: String? = nil) async throws -> String {
        // Deliberately ignores cancellation to simulate a noninterruptible native call.
        try? await Task.sleep(nanoseconds: 100_000_000)
        return "late result"
    }
}
@MainActor enum TextInsertion {
    struct Target {}
    static var writes = 0
    static var captures = 0
    static var lastText = ""
    static var deliveryDelay: UInt64 = 0
    static func capture() -> Target? { captures += 1; return Target() }
    static func insert(_ text: String, into target: Target?) async -> String { writes += 1; lastText=text; try? await Task.sleep(nanoseconds: deliveryDelay); return "Inserted" }
}
@main struct SessionChecks {
    @MainActor static func settle(_ s: DictationSession) async {
        for _ in 0..<100 { if !s.busy { return }; try? await Task.sleep(nanoseconds: 10_000_000) }
        preconditionFailure("Session failed to settle")
    }
    @MainActor static func main() async {
        let defaults = UserDefaults.standard
        let savedLanguage=defaults.object(forKey:"transcriptionLanguage")
        defer { if let savedLanguage { defaults.set(savedLanguage,forKey:"transcriptionLanguage") } else { defaults.removeObject(forKey:"transcriptionLanguage") } }
        let languageSession=DictationSession()
        languageSession.loadedID="whisper-small";languageSession.language="ko"
        precondition(languageSession.supportsLanguageSelection && languageSession.recognitionLanguage == "ko")
        languageSession.language="auto";precondition(languageSession.recognitionLanguage == nil)
        languageSession.loadedID="bark";languageSession.language="ko"
        precondition(!languageSession.supportsLanguageSelection && languageSession.recognitionLanguage == "en")
        defaults.set("invalid",forKey:"transcriptionLanguage")
        precondition(DictationSession().language == "auto")
        print("PASS language selection, automatic detection, Bark English boundary and invalid preference recovery")
        let saved = defaults.object(forKey: "selectedModel")
        defer { if let saved { defaults.set(saved, forKey: "selectedModel") } else { defaults.removeObject(forKey: "selectedModel") } }
        for id in ["bark", "bark-plus", "bark-pro"] {
            defaults.set(id, forKey: "selectedModel")
            let s = DictationSession(); s.restoreSelection(store: ModelStore()); await settle(s)
            precondition(s.loadedID == id)
        }
        defaults.set("removed-model", forKey: "selectedModel")
        let missing = DictationSession(); missing.restoreSelection(store: ModelStore())
        precondition(!missing.busy && missing.loadedID == nil && missing.message.contains("not installed"))
        defaults.set("bark", forKey: "selectedModel")
        let invalid = DictationSession(); let badStore = ModelStore(); badStore.validationFails = true
        invalid.restoreSelection(store: badStore); await settle(invalid)
        precondition(invalid.loadedID == nil && invalid.message.contains("Integrity"))
        let loading = DictationSession(); loading.restoreSelection(store: ModelStore()); loading.interrupt("Sleep")
        await settle(loading); precondition(loading.loadedID == nil)
        for _ in 0..<3 {
            let recording = DictationSession(); recording.phase = .recording; recording.transcript = "previous"
            recording.interrupt("Input changed")
            precondition(recording.phase == .idle && recording.transcript.isEmpty)
            let processing = DictationSession(); processing.phase = .recording; processing.finish()
            precondition(processing.phase == .transcribing)
            processing.interrupt("Sleep"); await settle(processing)
            precondition(processing.transcript.isEmpty && TextInsertion.writes == 0)
        }
        TextInsertion.deliveryDelay = 100_000_000
        let delivering = DictationSession(); delivering.phase = .recording; delivering.finish()
        for _ in 0..<100 {
            if delivering.phase == .delivering { break }
            try? await Task.sleep(nanoseconds: 5_000_000)
        }
        precondition(delivering.phase == .delivering)
        delivering.cancel()
        precondition(delivering.phase == .delivering)
        await settle(delivering)
        precondition(delivering.message == "Inserted" && TextInsertion.writes == 1)
        let beforeStarts=AudioCapture.starts
        let earlyRelease=DictationSession(microphoneAccess:{ try? await Task.sleep(nanoseconds:50_000_000);return true })
        earlyRelease.loadedID="bark";earlyRelease.beginHold();earlyRelease.endHold();await settle(earlyRelease)
        precondition(AudioCapture.starts==beforeStarts && earlyRelease.phase == .idle)
        let denied=DictationSession(microphoneAccess:{false});denied.loadedID="bark";denied.toggle();await settle(denied)
        precondition(denied.message.contains("Microphone access is required") && AudioCapture.starts==beforeStarts)
        let missingInput=DictationSession(resolveInput:{throw AppError("Selected input unavailable")},microphoneAccess:{true})
        missingInput.loadedID="bark";missingInput.toggle();await settle(missingInput)
        precondition(missingInput.message.contains("Selected input unavailable") && AudioCapture.starts==beforeStarts)
        TextInsertion.deliveryDelay=0
        let recovered=DictationSession(correct:{_ in "Corrected phrase"});let beforeWrites=TextInsertion.writes
        recovered.pasteLast();precondition(TextInsertion.writes==beforeWrites)
        recovered.phase = .recording;recovered.finish();await settle(recovered)
        precondition(recovered.lastDictation=="Corrected phrase" && recovered.canRecover)
        recovered.phase = .recording;recovered.transcript="cancelled material";recovered.cancel()
        let beforeCapture=TextInsertion.captures
        recovered.pasteLast();await settle(recovered)
        precondition(TextInsertion.captures==beforeCapture+1 && TextInsertion.lastText=="Corrected phrase")
        recovered.clearTranscript();precondition(!recovered.canRecover && recovered.transcript.isEmpty)
        let beforeEmpty=TextInsertion.writes;recovered.pasteLast();precondition(TextInsertion.writes==beforeEmpty)
        print("PASS early hold release, permission denial, missing input, explicit fresh-target recovery, dictionary integration and Clear")
        print("PASS dispatched delivery cannot be misreported as cancelled or written twice")
        print("PASS installed selection restoration for all models; missing and corrupt models fail closed")
        print("PASS interruption during loading and recording; three late native results suppressed after cancellation")
    }
}
