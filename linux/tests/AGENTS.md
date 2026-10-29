# Unit tests

## Purpose

Standard-library `unittest` coverage for the Linux port: ASR parsing, audio helpers, config, corrections, the daemon state machine, Hyprland block generation, insertion, IPC, models, and the assistant/LLM/TTS pipeline.

## Ownership

Owns every `test_*.py` file in this folder. Production code lives in `../ASR/`.

## Local Contracts

- The suite runs with `unittest` only; do not add pytest, mocks libraries, or other test dependencies.
- Run from the repository root with `PYTHONPATH=linux python3 -m unittest discover -s linux/tests`.
- Tests must not require a microphone, PipeWire, a GPU, a real LLM, a real TTS endpoint, a Waybar session, or network access. Use fakes and the local threaded HTTP servers already present in `test_assistant.py`.
- Use `tempfile` and patched XDG environment variables for config, secrets, and state paths; do not touch the user's real `~/.config` or `~/.local/state`.
- Inject clocks, capture factories, transcribers, notifiers, and HTTP endpoints instead of sleeping on real work. Keep time-based tests bounded.
- Keep the suite passing on Python 3.11 and newer; the project targets 3.11+.
- Production behavior changes require a matching test; bug fixes should include a regression test.

## Work Guidance

- Prefer small, focused tests over end-to-end tests that depend on the host.
- When adding a config field, cover its default and validation in `test_config.py`.
- When changing the assistant state machine or speech pipeline, cover the transition and cancellation path in `test_assistant.py`.
- When changing generated Hyprland config, update `test_hyprland.py` expectations.
- Do not weaken assertions just to make a flaky test pass; remove the timing or environment dependency instead.

## Verification

```sh
PYTHONPATH=linux python3 -m unittest discover -s linux/tests
```

Current baseline: 102 tests, all passing on Python 3.14 (and intended to remain compatible with 3.11+).

## Child DOX Index

None.
