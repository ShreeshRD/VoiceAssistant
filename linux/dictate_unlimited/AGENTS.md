# Python runtime

## Purpose

The `dictate_unlimited` package implements the Linux daemon, CLI, CPU-only ASR, Wayland insertion, configuration and secrets, model management, and the optional voice assistant (LLM streaming, TTS providers, playback, notifications).

## Ownership

Owns every module in this folder. Tests live in the sibling `../tests/` and are covered by that child doc.

## Local Contracts

- Runtime imports are Python standard library only. Do not add third-party runtime dependencies.
- `daemon.Engine` is the single dictation state machine. IPC commands are `status`, `ping`, `start`, `stop`, `toggle`, `cancel`, `paste-last`, `reload`, `quit`, and the `assistant-*` variants; unknown commands return an error response instead of raising.
- `assistant.Assistant` states are `idle`, `starting`, `listening`, `transcribing`, `thinking`, and `speaking`. `toggle` means start from idle, finish from listening, and interrupt/cancel from any busy state.
- `config.Config` is a JSON-backed dataclass. New fields need a default, validation in `Config.validate()`, typed handling in `dictate config set`, documentation in both READMEs, and tests.
- API keys never enter `config.Config`. `secrets.resolve()` checks the configured environment variable first, then `$XDG_CONFIG_HOME/dictate-unlimited/secrets.json` (mode `0600`). Key values are never printed or logged.
- `asr.py` invokes whisper.cpp `parakeet-cli` with `-ng` and no GPU environment. Keep it CPU-only and preserve transcript cleanup and error reporting.
- `insertion.py` prefers `wtype`, may fall back to the clipboard, never sends Enter, and never retries a write that may already have been delivered.
- `assistant.SpeechPipeline` consumes the LLM token stream, splits complete sentences, synthesizes with bounded parallelism and prefetch, and plays in order. Preserve ordered playback and backpressure.
- `tts.TTSClient` isolates two request shapes: `openai` (`POST /v1/audio/speech`) and `mimo` (`POST /v1/chat/completions` with Base64 audio at `choices[0].message.audio.data`). Provider differences stay in `tts.py`.
- `llm.LLMClient` targets OpenAI-compatible `POST /v1/chat/completions` with SSE streaming, filters think tags, supports cancellation, and can start a configured local server.
- `models.py` and `../models.json` pin revisions, sizes, and hashes. Do not widen verification or silently accept a different model.
- Status payloads are consumed by the CLI and `../waybar/dictate-assistant-waybar`. Keep key names and semantics stable unless both consumers are updated.

## Work Guidance

- Keep slow work (capture teardown, ASR, network calls, playback) outside the main state lock so status and cancel stay responsive.
- Use explicit timeouts for subprocesses and network requests; surface failures as user-readable states or notifications, not daemon crashes.
- Treat cancellation as cooperative: check the relevant cancel event between expensive steps and clean up temporary WAV files.
- Do not log transcripts, replies, API keys, or full HTTP bodies at normal log levels.
- Add or update tests in `../tests/` for every behavior change; inject clocks, capture, transcriber, and notifier rather than using real hardware or network in tests.
- Update `../README.md` when a command, config field, provider, or state changes.

## Verification

```sh
python3 -m py_compile linux/dictate_unlimited/*.py
PYTHONPATH=linux python3 -m unittest discover -s linux/tests
./linux/dictate doctor
./linux/dictate assistant doctor   # assistant/LLM/TTS paths
```

## Child DOX Index

None.
