# DOX framework

- DOX is a binding AGENTS.md hierarchy for this repository.
- Agents must follow DOX instructions across every edit.

## Core Contract

- AGENTS.md files are binding work contracts for their subtrees.
- Work products, source materials, instructions, records, assets, and durable docs must stay understandable from the nearest applicable AGENTS.md plus every parent AGENTS.md above it.

## Read Before Editing

1. Read the root AGENTS.md.
2. Identify every file or folder you expect to touch.
3. Walk from the repository root to each target path.
4. Read every AGENTS.md found along each route.
5. If a parent AGENTS.md lists a child AGENTS.md whose scope contains the path, read that child and continue from there.
6. Use the nearest AGENTS.md as the local contract and parent docs for repo-wide rules.
7. If docs conflict, the closer doc controls local work details, but no child doc may weaken DOX.

Do not rely on memory. Re-read the applicable DOX chain in the current session before editing.

## Update After Editing

Every meaningful change requires a DOX pass before the task is done.

Update the closest owning AGENTS.md when a change affects:

- purpose, scope, ownership, or responsibilities
- durable structure, contracts, workflows, or operating rules
- required inputs, outputs, permissions, constraints, side effects, or artifacts
- user preferences about behavior, communication, process, organization, or quality
- AGENTS.md creation, deletion, move, rename, or index contents

Update parent docs when parent-level structure, ownership, workflow, or child index changes. Update child docs when parent changes alter local rules. Remove stale or contradictory text immediately. Small edits that do not change behavior or contracts may leave docs unchanged, but the DOX pass still must happen.

## Hierarchy

- Root AGENTS.md is the DOX rail: project-wide instructions, global preferences, durable workflow rules, and the top-level Child DOX Index.
- Child AGENTS.md files own domain-specific instructions and their own Child DOX Index.
- Each parent explains what its direct children cover and what stays owned by the parent.
- The closer a doc is to the work, the more specific and practical it must be.

## Child Doc Shape

- Create a child AGENTS.md when a folder becomes a durable boundary with its own purpose, rules, responsibilities, workflow, materials, or quality standards.
- Work Guidance must reflect the current standards of the project or user instructions; if there are no specific standards or instructions yet, leave it empty.
- Verification must reflect an existing check; if no verification framework exists yet, leave it empty and update it when one exists.

Default section order:

- Purpose
- Ownership
- Local Contracts
- Work Guidance
- Verification
- Child DOX Index

## Style

- Keep docs concise, current, and operational.
- Document stable contracts, not diary entries.
- Put broad rules in parent docs and concrete details in child docs.
- Prefer direct bullets with explicit names.
- Do not duplicate rules across many files unless each scope needs a local version.
- Delete stale notes instead of explaining history.
- Trim obvious statements, repeated rules, misplaced detail, and warnings for risks that no longer exist.

## Closeout

1. Re-check changed paths against the DOX chain.
2. Update nearest owning docs and any affected parents or children.
3. Refresh every affected Child DOX Index.
4. Remove stale or contradictory text.
5. Run existing verification when relevant.
6. Report any docs intentionally left unchanged and why.

## Project

Speech Flow is a free, local, CPU-only dictation tool for Linux (Arch/Hyprland tested). PipeWire captures audio, Bark 3.0 runs through whisper.cpp's `parakeet-cli`, a Python daemon owns the state machine, and Wayland text insertion delivers the transcript. An optional voice assistant reuses the CPU recognizer, streams replies from an OpenAI-compatible LLM, and speaks them through a TTS endpoint.

This checkout contains the Linux port and its build/conversion scripts. The historical macOS Swift application is not present here.

## Global Contracts

- Dictation and its recognition path are CPU-only: never enable CUDA, Vulkan, HIP, SYCL, Metal, ROCm, or OpenCL backends for ASR.
- The assistant is optional and off by default. Dictation must continue to work when no LLM, TTS endpoint, key, or assistant configuration exists.
- Runtime code under `linux/ASR/` uses the Python standard library only. NumPy and constriction are allowed only for the one-time Bark conversion.
- Never write API keys into `config.json`. Use `secrets.py` and `secrets.json` with mode `0600`; never print or log key values.
- No webview or Tauri UI. Integration is Hyprland hotkeys, Waybar, and short desktop notifications.
- Keep model revisions, sizes, and hashes pinned. Do not silently replace a model, precision, or backend.
- The installed runtime is self-contained under `${XDG_DATA_HOME:-~/.local/share}/speech-flow/app`; `~/.local/bin/dictate` and the Waybar helper are symlinks into it. Never make the installed daemon depend on a checkout path.
- Preserve third-party notices and Bark attribution. No model weights are redistributed.
- Keep `README.md`, `linux/README.md`, `linux/TESTING.md`, `CHANGELOG.md`, and `linux/hyprland.conf.example` consistent with behavior when a change affects them.

## User Preferences

### Assistant UX

- One assistant hotkey: `SUPER + A` starts listening, finishes the turn, or interrupts while thinking/speaking. Do not add a separate cancel hotkey.
- The Waybar module must make it obvious when to speak: show `Speak now` with a live level bar and timer while listening, not just a microphone icon.
- Replies are spoken and also shown as short notification text; the full reply may live in history and tooltips.
- Prefer short, direct notifications over windows or overlays.

### Providers and privacy

- ASR stays on CPU. The LLM may use the GPU.
- TTS is provider-abstracted: `openai` uses `/v1/audio/speech`; `mimo` uses `/v1/chat/completions` with Base64 audio. A local TTS engine should be addable by configuration.
- The assistant sends recognized text, not raw audio, to the LLM, and reply text, not the user's voice, to TTS.

### Hyprland integration

- Hyprland keeps the first matching bind, so never define a second `SUPER + A` action elsewhere. Existing conflicts must be commented out, not shadowed.
- Generate the marked block from `cli.hyprland_block()`; keep `linux/hyprland.conf.example` and the Linux README in sync with it.
- Do not add dependencies on a display server other than Wayland/Hyprland for the supported path.

## Verification

Run from the repository root:

```sh
python3 -m py_compile linux/ASR/*.py linux/waybar/dictate-assistant-waybar
PYTHONPATH=linux python3 -m unittest discover -s linux/tests
./linux/dictate doctor
./linux/dictate assistant doctor   # when assistant, LLM, or TTS changed
```

## Child DOX Index

| Domain | Path | Scope |
|---|---|---|
| Linux port | `linux/AGENTS.md` | Packaging, install, Hyprland/Waybar/systemd integration, Linux user docs |
| Python runtime | `linux/ASR/AGENTS.md` | Daemon, CLI, ASR, insertion, config, assistant, LLM/TTS clients |
| Unit tests | `linux/tests/AGENTS.md` | Standard-library unittest suite and fakes |
| Build and conversion | `scripts/AGENTS.md` | CPU-only ASR build and Bark-to-GGML conversion |
