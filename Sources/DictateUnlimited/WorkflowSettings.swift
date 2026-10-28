import SwiftUI
import AppKit
import DictateCore

struct MicrophoneSettingsView: View {
    @ObservedObject var session: DictationSession
    @ObservedObject var microphones: MicrophoneController
    var body: some View {
        VStack(alignment:.leading,spacing:12) {
            Text("Microphone readiness").font(.system(size:15,weight:.semibold))
            Picker("Input device",selection:$microphones.selectedUID) {
                Text("System default").tag("")
                ForEach(microphones.devices) { device in Text(device.name).tag(device.id) }
                if !microphones.selectedUID.isEmpty && !microphones.devices.contains(where:{$0.id==microphones.selectedUID}) {
                    Text("Selected device disconnected").tag(microphones.selectedUID)
                }
            }.disabled(session.busy)
            Text("Input: \(microphones.inputName)").font(.system(size:12))
            Text("Microphone access: \(microphones.permission)").font(.system(size:12)).foregroundStyle(.secondary)
            Text(microphones.accessibilityGranted ? "Text insertion access: Ready" : "Text insertion access: Missing — use Enable below. After a development rebuild, remove and re-add this app in Accessibility.").font(.system(size:12)).foregroundStyle(.secondary)
            ProgressView(value:session.meter).accessibilityLabel("Microphone input level")
            HStack {
                Button("Refresh inputs") { microphones.refresh() }.disabled(session.busy)
                Button(session.phase == .testingMicrophone ? "Stop microphone test" : "Test microphone (5 seconds)") {
                    if session.phase == .testingMicrophone { session.cancel() } else { session.testMicrophone() }
                }.disabled(session.busy && session.phase != .testingMicrophone)
            }
            Text("Input selection applies only to this app. Testing is explicit, stops automatically, and never transcribes or saves audio.").font(.system(size:11)).foregroundStyle(.secondary)
        }.padding(16).overlay(RoundedRectangle(cornerRadius:Design.radius).stroke(.white.opacity(0.10)))
    }
}
struct ShortcutSettingsView: View {
    @ObservedObject var shortcuts: ShortcutController
    let busy: Bool
    var body: some View {
        VStack(alignment:.leading,spacing:12) {
            Text("Shortcuts").font(.system(size:15,weight:.semibold))
            HStack {
                Text("Dictation");Spacer();Text(shortcuts.configuration.dictate.display).monospaced()
                Button("Change dictation shortcut") { shortcuts.record(.dictate) }.disabled(shortcuts.recording != nil)
            }
            Picker("Recording mode",selection:Binding(get:{shortcuts.configuration.hold},set:{shortcuts.setHold($0)})) {
                Text("Tap to start / finish").tag(false)
                Text("Hold to talk").tag(true)
            }.disabled(shortcuts.recording != nil)
            HStack {
                Text("Paste last completed dictation");Spacer();Text(shortcuts.configuration.recover.display).monospaced()
                Button("Change recovery shortcut") { shortcuts.record(.recover) }.disabled(shortcuts.recording != nil)
            }
            Text(shortcuts.message).font(.system(size:12)).foregroundStyle(.secondary)
            HStack {
                if shortcuts.recording != nil { Button("Cancel shortcut capture") { shortcuts.cancelRecording() } }
                else { Button("Restore default shortcuts") { shortcuts.resetDefaults() } }
            }
            Text("Choose Control or Option plus a key. Paste-last is an explicit action in your focused field; it never presses Enter. Only the last completed result is kept in memory, until Clear or Quit.").font(.system(size:11)).foregroundStyle(.secondary)
        }.padding(16).overlay(RoundedRectangle(cornerRadius:Design.radius).stroke(.white.opacity(0.10))).disabled(busy)
        .onDisappear { if shortcuts.recording != nil { shortcuts.cancelRecording() } }
    }
}
struct DictionarySettingsView: View {
    @ObservedObject var dictionary: CorrectionStore
    let busy: Bool
    @State private var heard=""
    @State private var replacement=""
    @State private var editing: UUID?
    var body: some View {
        VStack(alignment:.leading,spacing:16) {
            Text("Local corrections").font(.system(size:15,weight:.semibold))
            Text("Replace specific misheard words or phrases after transcription. Whole-word matching is case-insensitive; your replacement keeps its spelling. No automatic learning, Contacts access, cloud sync or extra model.").font(.system(size:12)).foregroundStyle(.secondary)
            TextField("Heard (for example, do made)",text:$heard).textFieldStyle(.roundedBorder)
            TextField("Replace with (for example, DOO MADE)",text:$replacement).textFieldStyle(.roundedBorder)
            HStack {
                Button(editing == nil ? "Add correction" : "Save correction") {
                    if dictionary.save(id:editing,heard:heard,replacement:replacement) { heard="";replacement="";editing=nil }
                }.disabled(!dictionary.writable || heard.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty || replacement.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty)
                if editing != nil { Button("Cancel editing") { heard="";replacement="";editing=nil } }
                Spacer()
                Button("Undo dictionary change") { dictionary.undo();editing=nil;heard="";replacement="" }.disabled(!dictionary.canUndo)
            }
            Text(dictionary.message).font(.system(size:12)).foregroundStyle(.secondary)
            if !dictionary.writable { Button("Reveal dictionary file") { NSWorkspace.shared.activateFileViewerSelecting([dictionary.file]) } }
            if dictionary.entries.isEmpty { Text("No corrections yet.").foregroundStyle(.secondary) }
            ForEach(dictionary.entries) { entry in
                HStack {
                    VStack(alignment:.leading,spacing:4) { Text(entry.heard);Text("→ \(entry.replacement)").foregroundStyle(.secondary) }
                    Spacer()
                    Button("Edit") { editing=entry.id;heard=entry.heard;replacement=entry.replacement }.accessibilityLabel("Edit correction \(entry.heard)")
                    Button("Remove") { dictionary.remove(entry.id); if editing==entry.id { editing=nil;heard="";replacement="" } }.accessibilityLabel("Remove correction \(entry.heard)")
                }.padding(12).overlay(RoundedRectangle(cornerRadius:10).stroke(.white.opacity(0.10)))
            }
        }.disabled(busy)
    }
}
