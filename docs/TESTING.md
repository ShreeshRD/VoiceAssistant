# Validation and known limits

The local Apple-Silicon/macOS build passed core checks, numerical checks, session
checks and packaged inference tests. Full XCTest has not run on the Command Line
Tools-only test host. Use full Xcode for `swift test`.

```sh
./scripts/check-local.sh
./scripts/check-audio-startup.sh
./scripts/check-session.sh
./scripts/check-model-store.sh
./scripts/check-correction-store.sh
./scripts/check-clipboard.sh
```

Session checks compile the production session controller against deterministic
boundary doubles. They verify restored selections, missing/corrupt model failure,
interruption and suppression of late results. They do not simulate physical hardware.

## Observed coverage

- All three Bark models downloaded through the app into isolated storage and passed
  declared size/hash checks. The clean-built app then transcribed the synthetic
  fixture from those new downloads with networking denied. Base Repair restored a
  deliberately corrupted artifact. Cancel/retry also passed in the real UI.
- All three Bark models accepted five-minute input and rejected input over the limit.
- Base and Plus exactly matched a 738-word repeated fixture. Pro inserted three
  extra words. This fixture is not a general recognition-accuracy benchmark.
- A real five-minute microphone recording stopped automatically; cancellation during
  transcription discarded the result. This live limit/cancellation check used base.
- Automatic selected-model restoration was observed with Pro. Deterministic checks
  cover all three selections, including missing/corrupt installations.
- The tester confirmed physical shortcut insertion in TextEdit, an untitled editor
  and a browser address bar, plus recovery after sleep/wake and microphone loss.
  Editor/browser identities and physical interruption timing were not recorded.

## Limits to disclose

Every-app insertion compatibility, varied
hardware/accents/noise, and a fresh second Mac are unverified. Download/Repair validation is described in PREVIEW-RELEASE.md.
ModelStore checks use synthetic HTTPS responses, including cancellation, connection
loss, bad size/hash and preservation of existing models after failed repair. First Core ML specialization can take
minutes. Native compilation/prediction cannot always stop immediately after Cancel.
Pro may print an upstream Core ML shape diagnostic before successful CLI inference.
The development app is ad-hoc signed; rebuilding can require permission refresh.

Audio and session text are not saved as history. Local test logs, screenshots and
investigation material are excluded from the source-preview export. Test results
are evidence for this bounded build, not public-release acceptance.


## Local workflow additions

New deterministic coverage includes Unicode dictionary boundaries, longest-match
and non-cascading replacement, dictionary disk persistence/undo/corrupt-file
preservation, shortcut validation and duplicate-event suppression, hold release
before permission completes, unavailable input, and fresh-target paste-last recovery.
Live UI checks cover correction editing/removal/undo, shortcut recording and duplicate
rejection, and explicit microphone selection/testing. The five-second test returned
Ready while a menu remained open, validating its common-run-loop timer. Physical hold mode, dictionary corrections and paste-last recovery were confirmed
by the tester. Text delivery was also confirmed in a chat composer. A stale
Accessibility entry after an ad-hoc rebuild was reproduced and resolved by removing
and re-adding the current app; the tester confirmed delivery afterward. Closing and
reopening Settings was tested after adding the application reopen handler. These
checks do not imply every keyboard layout, application or microphone was tested.

## V1.1 validation

Whisper small and compressed Turbo were exercised with networking denied using
installed macOS Samantha/Yuna synthetic voices, separately in English/Korean and
with auto detection. Both returned English correctly aside from punctuation.
Turbo matched the Korean fixture exactly; small misrecognized a Korean word and
spacing. In one concatenated English/Korean fixture, Turbo retained both languages
(with “Mac” in Latin letters) while small omitted the English portion. This is a
small synthetic smoke test, not a multilingual accuracy benchmark or human acceptance.
Both returned empty output for digital silence. Bark models still completed local
English inference; base heard “Mac” as “map”, and Pro emitted its known shape warning.

Import store checks cover copied-file hashes, persistence, corruption, symlinks,
unexpected executable files, missing components, cancellation and URL directory
metadata differences. Runtime checks confirm corrupt tokenizers fail locally with
no fallback. The tester confirmed Korean and Japanese dictation worked and reported completion
of the requested English/Korean/mixed-language check. After the microphone freeze
repair, the tester confirmed the app worked. These are user confirmations, separate
from the synthetic fixtures and bounded repeated-start checks below.

Microphone-startup follow-up: a user-reported freeze was sampled inside
AVAudioEngine input-device setup on the main actor, not Whisper inference. Engine
setup/teardown now run on a dedicated serial queue; a ten-second native-start timeout
returns an actionable error without waiting for the native call. Cancellation
invalidates the generation, and late completion cannot accept samples. A stalled
native call cannot be forcibly unwound; the app may still need restarting to reset
its audio worker. Shared audio services are never restarted by the app.

`./scripts/check-audio-startup.sh` injects delayed native preparation and checks
bounded completion, overlap rejection, cancellation and no late capture. These
checks do not reproduce every hardware-driver failure.

The repaired packaged app completed nine live capture cycles across Wireless
Microphone Rx and MacBook Pro Microphone: automatic microphone-test stops, an early
stop, repeated dictation cancellation, and a recording that completed transcription
with no speech detected. No UI freeze was observed in those cycles. A follow-up fix
ignores configuration notifications while the engine is still running and avoids
redundant input-device writes. This bounded check does not guarantee all audio drivers
or every future device transition.
