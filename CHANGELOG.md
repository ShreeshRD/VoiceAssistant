# Changelog

## 1.1.0-linux.1 · Linux CPU-only port

- New additive Linux port under `linux/`; the macOS Swift app is unchanged.
- PipeWire capture through `pw-cat`, CPU-only recognition of the English-only
  Bark 3.0 model through whisper.cpp's `parakeet-cli`, and Wayland delivery
  through `wtype`/`wl-clipboard`.
- Bark 3.0 is downloaded as five pinned source files and converted locally to
  GGML f16; the converter checks the decoded-state digest and tensor-name set.
- Long-running Unix-socket daemon with tap, hold, cancel, paste-last, and status
  commands; hotkeys auto-start it when needed.
- Hyprland tap/hold keybind generation with backup and marked config block.
- Pinned-size and SHA-256 verification for every download, source re-verification,
  and `doctor` diagnostics.
- Ported explicit correction dictionary (no automatic learning).
- CPU-only enforcement: all GPU backends disabled at build time, `-ng` required
  before every run, empty CUDA/HIP/ROCR device variables, and no linked GPU
  libraries.
- Headless `insertion = "none"` mode and offline `transcribe` command.
- 63 unit tests plus a PipeWire null-sink end-to-end run; physical microphone
  and physical hold-mode testing remain unverified.

## 0.2.0-preview.1 · V1.1

- Whisper small and compressed large-v3-turbo with fully local tokenizers.
- Automatic or explicit transcription language, including English and Korean.
- Validated, copied local WhisperKit model imports with persistence.
- Existing Bark models and local-only inference retained.
- Microphone startup moved off the UI thread with bounded timeout and cancellation.
- Fixed false input-change interruptions; nine repeated capture cycles tested.
- Source-only preview. No signed/notarized app binary is distributed.

## 0.1.0-preview.1

Initial source-only preview from DOO MADE.

- English on-device dictation with Bark 3.0, Plus and Pro.
- Explicit verified model download/repair and selected-model restoration.
- Microphone readiness, per-app input selection and five-second signal test.
- Configurable tap/hold dictation and paste-last recovery shortcuts.
- Local word/phrase dictionary with edit, remove and undo.
- Guarded clipboard delivery, cancellation, interruption handling and five-minute limit.
- Notch/floating feedback and Settings reopening for the menu-bar app.

Build from source. No notarized binary, hosted CI, or broad device compatibility
claim is included. See docs/TESTING.md and docs/LICENSING.md.
