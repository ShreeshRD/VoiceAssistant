# Changelog

## 1.2.0-linux.1 · Voice assistant

- Optional voice assistant inside the existing daemon: tap to listen, tap again
  to transcribe and answer, tap while thinking or speaking to interrupt.
  Dictation keeps its own state machine and behaves as before.
- Reuses PipeWire capture and the CPU-only Bark runtime for assistant input;
  audio never goes to the LLM.
- Streaming OpenAI-compatible chat client with conversation history held in
  memory, sentence splitting, bounded parallel synthesis, ordered playback, and
  prefetch of upcoming sentences.
- TTS client with two request shapes: OpenAI `/v1/audio/speech` and the
  MiMo-V2.5-TTS chat-completions API with Base64 audio, behind a provider
  abstraction so a local model can replace either by configuration.
- API keys stored outside `config.json`: environment first, then a mode-0600
  `secrets.json`; `dictate secrets set` reads from stdin and never argv.
- Optional local LLM autostart with log capture and readiness timeout.
- Waybar module (`dictate-assistant-waybar`) plus short replaced notifications
  for the transcript and reply.
- `dictate assistant` commands (`toggle`, `start`, `stop`, `cancel`, `reset`,
  `status`, `warmup`, `doctor`) and `dictate setup --hyprland --assistant` binds
  `SUPER + A` to toggle/finish/interrupt; dictation binds unchanged. The toggle
  interrupts an in-flight reply, so no separate cancel shortcut is needed.
- Assistant configuration validation plus `doctor` checks for the LLM endpoint,
  TTS key source, player, notifications, and Waybar helper.
- 88 unit tests covering the splitter, think-tag filtering, clients, secrets,
  pipeline, and a full simulated turn.

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
claim is included.
