import SwiftUI
import AppKit
import DictateCore

enum Design {
    static let background = Color(red: 30/255, green: 30/255, blue: 30/255)
    static let sidebar = Color(red: 60/255, green: 60/255, blue: 60/255)
    // Approximation approved 2026-10-21. Runtime did not expose these values.
    static let radius: CGFloat = 14
    static let motion = Animation.easeInOut(duration: 0.18)
}
struct SettingsView: View {
    @ObservedObject var session: DictationSession
    @ObservedObject var store: ModelStore
    @ObservedObject var microphones: MicrophoneController
    @ObservedObject var dictionary: CorrectionStore
    @ObservedObject var shortcuts: ShortcutController
    @State private var page = "Dictation"
    private let pages = [("Dictation","mic"),("Models","cpu"),("Dictionary","text.book.closed"),("Appearance","sparkles"),("About","info.circle")]
    var body: some View {
        HStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 10) {
                Text("Dictate Unlimited").font(.system(size: 18, weight: .semibold)).padding(.bottom, 4)
                Text("DOO MADE").font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary).padding(.bottom, 30)
                ForEach(pages, id: \.0) { name, icon in
                    Button { page = name } label: { Label(name, systemImage: icon).font(.system(size: 14, weight: .semibold)).frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 14).padding(.vertical, 10).background(page == name ? Design.background : .clear, in: Capsule()) }
                        .buttonStyle(.plain)
                }
                Spacer()
                Label("On-device dictation", systemImage: "lock.shield").font(.system(size: 11)).foregroundStyle(.secondary)
                Text("No account. No subscription.").font(.system(size: 11)).foregroundStyle(.secondary)
            }.padding(20).frame(width: 228).frame(maxHeight: .infinity).background(Design.sidebar)
            ScrollView {
                VStack(alignment: .leading, spacing: 28) {
                    Text(page).font(.system(size: 22, weight: .semibold)).padding(.bottom, 20)
                    if page == "Dictation" { dictation }
                    else if page == "Models" { models }
                    else if page == "Dictionary" { DictionarySettingsView(dictionary:dictionary,busy:session.busy) }
                    else if page == "Appearance" { appearance }
                    else { about }
                }.frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 56).padding(.top, 62).padding(.bottom, 36)
            }
        }.background(Design.background).foregroundStyle(.primary).preferredColorScheme(.dark)
    }
    private func card<Content: View>(@ViewBuilder _ content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 0, content: content).frame(maxWidth: .infinity, alignment: .leading).background(Design.background).clipShape(RoundedRectangle(cornerRadius: Design.radius)).overlay(RoundedRectangle(cornerRadius: Design.radius).stroke(.white.opacity(0.10)))
    }
    private func row(_ title: String, detail: String? = nil) -> some View {
        VStack(alignment: .leading, spacing: 4) { Text(title).font(.system(size: 14)); if let detail { Text(detail).font(.system(size: 12)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true) } }.padding(16)
    }
    private var dictation: some View {
        Group {
            Text("Record").font(.system(size: 15, weight: .semibold))
            card {
                HStack {
                    row(session.phase.rawValue, detail: session.loadedID.flatMap { id in store.models.first { $0.id == id }?.name } ?? "No model loaded")
                    Spacer()
                    if session.busy { Button("Cancel") { session.cancel() }.disabled(session.phase == .delivering).padding(.trailing, 8) }
                    Button(session.phase == .recording ? "Finish" : "Start dictation") { session.toggle() }.buttonStyle(.borderedProminent).disabled(shortcuts.recording != nil || session.loadedID == nil || (session.busy && session.phase != .recording)).padding(.trailing, 16)
                }
                Divider()
                row(shortcuts.configuration.dictate.display, detail: shortcuts.configuration.hold ? "Hold to speak, release to finish. Maximum recording: 5 minutes." : "Tap to start, tap to finish from your writing app. Maximum recording: 5 minutes.")
                if session.phase == .recording || session.phase == .testingMicrophone { ProgressView(value: session.meter).padding(16); Text(String(format: "%.1f seconds", session.seconds)).font(.caption.monospacedDigit()).padding([.horizontal,.bottom],16) }
            }
            Text(session.message).font(.system(size: 12)).foregroundStyle(.secondary).textSelection(.enabled)
            card {
                HStack {
                    row("Language", detail: session.supportsLanguageSelection ? "Transcribes speech in its original language. Auto-detect chooses the language; mixed-language results vary." : "Bark models transcribe English. Load a Whisper model for other languages.")
                    Spacer()
                    Picker("Transcription language", selection: $session.language) {
                        ForEach(TranscriptionLanguage.options,id: \.code) { option in Text(option.name).tag(option.code) }
                    }.labelsHidden().frame(width:190).padding(16).disabled(!session.supportsLanguageSelection || session.busy)
                }
            }
            MicrophoneSettingsView(session:session,microphones:microphones).disabled(shortcuts.recording != nil)
            ShortcutSettingsView(shortcuts:shortcuts,busy:session.busy)
            HStack {
                Text(session.lastDictation.isEmpty ? "No completed dictation to recover." : "Last completed dictation is available in memory.").font(.system(size:12)).foregroundStyle(.secondary)
                Spacer()
                Button("Clear last dictation") { session.clearTranscript() }.disabled(!session.canRecover)
            }
            Text("Text delivery").font(.system(size: 15, weight: .semibold))
            card {
                HStack { row("Accessibility", detail: "Enable access for verified insertion into the field where you started. If insertion cannot be verified, your text stays here."); Spacer(); Button("Enable…") { TextInsertion.requestPermission() }.padding(16) }
            }
            Text("Dictation uses clipboard paste automatically. Verified paste restores your clipboard if unchanged. Unverified paste leaves the dictated text on it; check the target before retrying. Clipboard managers may retain it.").font(.system(size: 11)).foregroundStyle(.secondary)
            if !session.transcript.isEmpty {
                card { Text(session.transcript).font(.system(size: 15)).textSelection(.enabled).padding(20); Divider(); HStack { Text("This session only").font(.caption).foregroundStyle(.secondary); Spacer(); Button("Copy text") { session.copy() }; Button("Clear") { session.clearTranscript() }.disabled(session.busy) }.padding(16) }
            }
        }
    }
    private var models: some View {
        Group {
            Text("Choose your dictation model").font(.system(size: 15, weight: .semibold))
            Text("Bark for English; Whisper for multilingual dictation. Download explicitly or import a compatible local model. Recognition stays on this Mac.").font(.system(size: 12)).foregroundStyle(.secondary)
            card {
                ForEach(store.models) { model in
                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            VStack(alignment: .leading, spacing: 5) {
                                Text(model.name).font(.system(size: 14, weight: .medium))
                                Text("\(ByteCountFormatter.string(fromByteCount: model.bytes, countStyle: .file)) \(model.isImported ? "local files" : "download") · \(model.precision)").font(.system(size: 12)).foregroundStyle(.secondary)
                            }
                            Spacer()
                            if session.loadedID == model.id { Label("Active", systemImage: "checkmark.circle.fill").foregroundStyle(.green).font(.system(size: 12)) }
                            else if store.installed.contains(model.id) { Button("Load") { session.load(model, store: store) }.disabled(session.busy) }
                            else { Button("Download") { store.download(model) }.disabled(store.downloading != nil || session.busy) }
                        }
                        if !model.isImported && store.installed.contains(model.id) && session.loadedID != model.id {
                            Button("Repair download") { store.download(model, repair: true) }.font(.system(size: 11)).disabled(store.downloading != nil || session.busy)
                        }
                        if store.downloading == model.id { HStack { ProgressView(value: store.progress); Button("Cancel") { store.cancel() } } }
                    }.padding(16)
                    if model.id != store.models.last?.id { Divider() }
                }
            }
            if session.busy {
                HStack { ProgressView().controlSize(.small); Text(session.message).font(.system(size: 12)); Spacer(); Button("Cancel") { session.cancel() }.disabled(session.phase == .cancelling || session.phase == .delivering) }
            } else { Text(session.message).font(.system(size: 12)).foregroundStyle(.secondary) }
            HStack {
                Button("Import local Whisper model…") { chooseLocalModel() }.disabled(store.downloading != nil || session.busy)
                if store.downloading?.hasPrefix("whisper-import-") == true { ProgressView().controlSize(.small);Button("Cancel import") { store.cancel() } }
            }
            Text("Import a complete WhisperKit multilingual small or large-v3/Turbo Core ML export, including its tokenizer. Files are copied into app storage and checked before installation. Raw PyTorch/MLX weights and executable plugins are not supported.").font(.system(size:11)).foregroundStyle(.secondary)
            Text(store.message).font(.system(size: 12)).foregroundStyle(.secondary).textSelection(.enabled)
            Text("Bark models are CC BY 4.0; Whisper is MIT. Imported models keep their own licences. Core ML export sizes differ from original weights. Initial preparation can take several minutes. The first longer recording may need one additional local compilation.").font(.system(size: 11)).foregroundStyle(.secondary)
        }
    }
    private func chooseLocalModel() {
        let panel=NSOpenPanel();panel.canChooseDirectories=true;panel.canChooseFiles=false;panel.allowsMultipleSelection=false
        panel.prompt="Import model";panel.message="Choose a complete WhisperKit Core ML model folder with local tokenizer files."
        if panel.runModal() == .OK,let url=panel.url { store.importLocal(url) }
    }
    private var appearance: some View {
        Group {
            Text("Recording feedback").font(.system(size: 15, weight: .semibold))
            card {
                HStack { row("Position"); Spacer(); Picker("Position", selection: $session.overlayStyle) { Text("Notch").tag("notch"); Text("Floating panel").tag("floating") }.labelsHidden().frame(width: 180).padding(16) }
                Divider()
                HStack { row("Active view", detail: "Minimal uses one row. Expanded gives the microphone feedback more room."); Spacer(); Picker("Active view", selection: $session.expanded) { Text("Minimal").tag(false); Text("Expanded").tag(true) }.labelsHidden().frame(width: 160).padding(16) }
            }.disabled(session.busy)
            Text("Choose where feedback appears while you dictate. Follows macOS Reduce Motion.").font(.system(size: 12)).foregroundStyle(.secondary)
        }
    }
    private var about: some View {
        card {
            row("Dictate Unlimited", detail: "Free, open-source macOS dictation by DOO MADE. Original application code: MIT. Bark models and adapted runtime algorithms retain their separate attribution licenses.")
            Divider()
            row("Local by design", detail: "No accounts, analytics, cloud inference, meetings, memos or agent integrations. Network requests are made only when you choose a model download. No recording or transcript history is written by the app. Only your explicit dictionary corrections and settings are saved locally.")
            Divider()
            row("Model attribution", detail: "Bark: Conway Research / Underdog, based on NVIDIA Parakeet and Moondream. Whisper: OpenAI; Core ML exports and WhisperKit: Argmax. See THIRD_PARTY_NOTICES.md in the source distribution.")
        }
    }
}
struct FeedbackView: View {
    @ObservedObject var session: DictationSession
    @Environment(\.accessibilityReduceMotion) var reduceMotion
    var body: some View {
        VStack(spacing: session.expanded ? 18 : 0) {
            HStack(spacing: 14) {
                Circle().fill(LinearGradient(colors: [.cyan,.indigo,.purple], startPoint: .topLeading, endPoint: .bottomTrailing)).frame(width: 28,height: 28).scaleEffect(reduceMotion ? 1 : 1 + CGFloat(min(session.level * 2,0.2))).animation(reduceMotion ? nil : Design.motion, value: session.level)
                Text(session.phase.rawValue).font(.system(size: 15, weight: .semibold))
                Spacer()
                if session.phase == .recording { Text(String(format: "%.0fs",session.seconds)).font(.system(size: 11)).monospacedDigit().foregroundStyle(.white.opacity(0.38)) }
                Button { session.cancel() } label: { Image(systemName: "xmark.circle.fill") }.buttonStyle(.plain).disabled(session.phase == .delivering).accessibilityLabel("Cancel dictation")
            }
            if session.expanded {
                HStack(alignment: .center, spacing: 5) { ForEach(0..<30, id: \.self) { i in Capsule().fill(.white.opacity(0.75)).frame(width: 4, height: reduceMotion ? 8 : max(4, CGFloat(session.level) * CGFloat(50 + (i % 7) * 20))) } }.frame(height: 60)
                Text(session.phase == .recording ? "Listening on this Mac" : "Audio stays on this Mac").font(.system(size: 11)).foregroundStyle(.white.opacity(0.38))
            }
        }.padding(20).frame(maxWidth: .infinity,maxHeight: .infinity).background(.black).foregroundStyle(.white).clipShape(RoundedRectangle(cornerRadius: 18)).overlay(RoundedRectangle(cornerRadius: 18).stroke(.white.opacity(0.12)))
    }
}
