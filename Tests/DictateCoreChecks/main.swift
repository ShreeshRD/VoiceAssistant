import Foundation
import DictateCore
let models = try ModelCatalog.load()
precondition(Set(models.map(\.id)) == ["bark", "bark-plus", "bark-pro", "whisper-small", "whisper-turbo"])
for m in models {
    precondition(!m.revision.isEmpty && m.revision != "main")
    precondition(m.bytes > 100_000_000)
    precondition(m.files.allSatisfy { ModelCatalog.safeRelativePath($0.path) })
    precondition(m.files.filter { $0.size > 1_000_000 }.allSatisfy { $0.sha256?.count == 64 })
}
print("PASS fixed model catalog, pinned artifacts and weight hash coverage")
for path in ["../secret", "/etc/passwd", "a/../b", "a//b", "a\\b"] { precondition(!ModelCatalog.safeRelativePath(path)) }
precondition(ModelCatalog.safeRelativePath("Encoder.mlpackage/Data/model.mlmodel"))
precondition(!AudioLimits.valid([]) && !AudioLimits.valid([.nan]) && AudioLimits.valid([0,0.5]))
print("PASS traversal and audio input boundaries")

let adjacent = InsertionPlan(text: "world", original: "hello", range: NSRange(location:5,length:0))!
precondition(adjacent.insertedText == " world" && adjacent.expectedText == "hello world")
let middle = InsertionPlan(text: "brave", original: "helloworld", range: NSRange(location:5,length:0))!
precondition(middle.expectedText == "hello brave world")
let selected = InsertionPlan(text:"B",original:"aXa",range:NSRange(location:1,length:1))!
precondition(selected.expectedText == "aBa")
precondition(InsertionPlan(text:",",original:"hello",range:NSRange(location:5,length:0))!.expectedText == "hello,")
precondition(InsertionPlan(text:"world",original:"hello ",range:NSRange(location:6,length:0))!.expectedText == "hello world")
precondition(InsertionPlan(text:"x",original:"🙂",range:NSRange(location:1,length:0)) == nil)
precondition(InsertionPlan(text:"x",original:"a",range:NSRange(location:2,length:0)) == nil)
print("PASS insertion boundaries, literal replacements, whitespace and Unicode safety")

var watchdog = CaptureWatchdog(now: 100)
precondition(!watchdog.stalled(sampleCount: 0, now: 102.9))
precondition(watchdog.stalled(sampleCount: 0, now: 103))
precondition(!watchdog.stalled(sampleCount: 16000, now: 104))
precondition(!watchdog.stalled(sampleCount: 32000, now: 106.9))
precondition(watchdog.stalled(sampleCount: 32000, now: 110))
print("PASS microphone startup grace, stalled input, and resumed sample progress")

runCorrectionChecks()
precondition(ShortcutBinding.dictation.valid && ShortcutBinding.recovery.valid)
precondition(!ShortcutBinding.dictation.conflicts(with: .recovery))
precondition(!ShortcutBinding(keyCode:9,modifiers:256,keyLabel:"V").valid)
precondition(!ShortcutBinding(keyCode:53,modifiers:4096,keyLabel:"Escape").valid)
var keys = ShortcutEdges()
precondition(keys.down(1) && !keys.down(1) && !keys.down(1,repeatEvent:true))
precondition(keys.up(1) && !keys.up(1))
precondition(keys.down(2));keys.reset();precondition(!keys.isDown(2))
print("PASS shortcut validation, duplicate-source suppression, release and wake reset")
