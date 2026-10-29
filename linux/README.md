# Speech Flow for Linux (CPU-only)

This directory is a native Linux port: PipeWire capture, Bark 3.0 recognition
through whisper.cpp's `parakeet-cli`, a small background daemon, and Wayland
text insertion. The repository is Linux-only; the macOS Swift GUI has been
removed.

The port has no account, cloud inference, telemetry, update service, or Enter-key
injection for dictation. Bark 3.0 runs on the CPU with every GPU backend disabled,
and the model is English-only.

An optional voice assistant lives in the same daemon. It reuses the microphone
and CPU recognizer, streams a reply from an OpenAI-compatible LLM, speaks it
through an OpenAI-compatible TTS endpoint, and reports progress through Waybar
and short notifications. Dictation behaves exactly as before when the assistant
is not used.

Tested on Arch Linux with Hyprland 0.56.2 (Wayland), PipeWire, and Python 3.14.
Python 3.11 or newer is required. Other Wayland compositors should work with the
same `wtype`/`wl-clipboard` tools, but only Hyprland keybinds are provided.

## Requirements

| Component | Package on Arch | Used for |
| --- | --- | --- |
| Python 3.11+ | `python` | daemon, CLI, configuration |
| PipeWire | `pipewire-audio` | `pw-cat` capture, `pactl` source listing |
| whisper.cpp runtime | built by `scripts/build-asr-linux.sh` | CPU `parakeet-cli` for Bark 3.0 |
| NumPy | `pip install numpy` in a venv or pyenv | one-time model conversion |
| constriction | `pip install constriction` in a venv or pyenv | one-time ANS decoding of `model.bark` |
| wtype | `wtype` | typing text into the focused window |
| wl-clipboard | `wl-clipboard` | clipboard and paste fallback |
| audio player | `mpv`, `pw-cat`, or `ffplay` | assistant speech playback |
| libnotify | `libnotify` | desktop notifications (optional) |
| Hyprland | `hyprland` | shortcuts (optional, compositor-specific) |
| Waybar | `waybar` | assistant state module (optional) |

```sh
sudo pacman -S --needed python pipewire-audio wtype wl-clipboard \
  libnotify git cmake base-devel
```

Arch marks its Python as externally managed (PEP 668), so the conversion-only
packages must go in a virtual environment (or an existing pyenv environment).
The Install steps below create one.

NumPy and constriction are only used while converting the downloaded Bark
weights. The daemon and CLI use only the Python standard library at runtime.

## Install

```sh
git clone https://github.com/ShreeshRD/VoiceAssistant.git
cd VoiceAssistant

python3 -m venv .venv                 # conversion-only dependencies
source .venv/bin/activate
pip install numpy constriction

./scripts/build-asr-linux.sh          # CPU-only parakeet-cli (whisper.cpp v1.9.5)
./linux/install.sh                    # runtime to ~/.local/share/speech-flow/app
./linux/dictate models download bark-3.0 --use
deactivate
./linux/dictate doctor
```

If you already have a pyenv or virtual environment with NumPy and constriction
(for example, `pyenv shell voice`), activate that instead of creating `.venv`.

`install.sh` copies a self-contained runtime to
`~/.local/share/speech-flow/app` and links `dictate` and the Waybar helper into
`~/.local/bin`. The installed daemon and `parakeet-cli` do not reference the
checkout, so the repository can be moved or removed after installation. Re-run
`install.sh` after updating the code or rebuilding the ASR runtime. Use
`--prefix DIR` (or `DICTATE_INSTALL_ROOT`) to choose another location.

`install.sh` also accepts `--build-asr`, `--download-model ID`, `--hyprland`,
`--hold`, `--assistant`, `--yes`, and `--force`. It creates the default config on
first run and never edits your compositor configuration unless you pass
`--hyprland`. `--assistant` only adds the `SUPER + A` bind and must be combined
with `--hyprland`. If `SUPER + A` is already used in your Hyprland config,
comment that bind out first; Hyprland keeps the first matching bind, so the
assistant would otherwise never fire.

The build script clones whisper.cpp at tag `v1.9.5`, configures CMake with
`GGML_CUDA`, `GGML_VULKAN`, `GGML_METAL`, `GGML_HIP`, and `GGML_SYCL` all off,
and refuses to finish if the resulting `parakeet-cli` lacks `-ng` or links a GPU
library. Override the tag with `ASR_TAG` (or the legacy `WHISPER_TAG`) and the
parallelism with `JOBS`.

## Hyprland shortcuts

Add the generated block automatically:

```sh
dictate setup --hyprland          # tap mode
dictate setup --hyprland --hold   # press to start, release to finish
dictate setup --hyprland --assistant  # also bind SUPER + A
```

The command writes a marked block between `# >>> speech-flow >>>` and
`# <<< speech-flow <<<`, keeps a timestamped backup, and asks before
writing when run interactively. Then reload Hyprland:

```sh
hyprctl reload
```

Defaults, also available in [`hyprland.conf.example`](hyprland.conf.example):

| Action | Tap mode | Hold mode |
| --- | --- | --- |
| Start / finish | `SUPER + D` | `SUPER + D` press / release |
| Paste last result | `SUPER + SHIFT + V` | `SUPER + SHIFT + V` |
| Cancel | `SUPER + Escape` | `SUPER + Escape` |
| Assistant tap | `SUPER + A` | `SUPER + A` |

The assistant row is only written with `--assistant`. The same key finishes a
recording and interrupts a reply, so a separate cancel bind is not needed.

The block includes `exec-once = dictate daemon --detach` so the daemon starts
once per Hyprland session. `dictate` commands auto-start the daemon when a
hotkey runs before it, so a missed `exec-once` is not fatal.

`dictate setup --hyprland` modifies your real `~/.config/hypr/hyprland.conf`.
Review the diff and the backup, and use `hyprctl reload` only when you are ready.

## Commands

```sh
dictate toggle                  # start, or stop and transcribe
dictate start                   # used by hold-mode key press
dictate stop                    # used by hold-mode key release
dictate cancel                  # discard recording or in-flight transcription
dictate paste-last              # re-insert the last completed transcript
dictate status                  # state, model, CPU use, level
dictate status --watch          # live level meter
dictate status --json           # machine-readable status
dictate daemon --detach         # background daemon
dictate daemon --foreground     # foreground daemon (systemd)
dictate reload                  # reload config and dictionary
dictate quit                    # stop the daemon
```

### Voice assistant commands

```sh
dictate assistant toggle        # idle → listen; listening → finish; busy → interrupt
dictate assistant start
dictate assistant stop
dictate assistant cancel
dictate assistant reset         # clear in-memory conversation history
dictate assistant status
dictate assistant status --json # same payload used by the Waybar helper
dictate assistant warmup        # start the LLM and check TTS/player setup
dictate assistant doctor        # endpoint, key, player, Waybar checks

dictate secrets list
dictate secrets set tts_api_key   # reads stdin/getpass, never argv
dictate secrets set llm_api_key
dictate secrets unset tts_api_key
```

`assistant toggle` is deliberately tap-oriented: from idle it starts listening,
while listening it stops and sends the turn, and while transcribing, thinking, or
speaking it cancels. `assistant status` does not start the daemon; a hotkey
command does.

Audio, models, and dictionary:

```sh
dictate mic list
dictate mic test --seconds 5
dictate mic use <source-name>
dictate mic use --default

dictate models list
dictate models download bark-3.0 --use
dictate models verify
dictate models import ~/Downloads/custom-ggml.bin
dictate models remove bark-3.0
dictate models path bark-3.0

dictate dictionary list
dictate dictionary chat
dictate dictionary add "heard phrase" "replacement"
dictate dictionary remove <id>
dictate dictionary clear
dictate dictionary apply "some text"
```

`dictate dictionary chat` is a small terminal editor: type `heard => replacement`
(or `heard -> replacement`) to add a correction, `list` to see numbers and ids,
`remove 2` or `remove <id-prefix>` to delete one, `undo` to drop the last addition
from this session, and `apply <text>` to preview the result. Each change is saved
immediately and a running daemon is reloaded automatically. The dictionary is
literal, case-insensitive, and never learns on its own; for example
`m. d. => MD` turns "open the m. d. file" into "open the MD file".

Configuration and diagnostics:

```sh
dictate config path
dictate config show
dictate config get threads
dictate config set threads 6
dictate config edit

dictate doctor                  # environment checks
dictate transcribe sample.wav   # offline file transcription
dictate transcribe sample.wav --json
dictate transcribe sample.wav --insert
```

## Voice assistant

The assistant is a separate state machine inside the dictation daemon, not a
second service. A turn looks like this:

1. Tap `SUPER + A`. PipeWire capture starts; playback and ASR are the same ones
   dictation uses. The Waybar module shows level and elapsed time.
2. Tap again. The WAV is transcribed on the CPU, then the transcript is sent to
   an OpenAI-compatible `POST /v1/chat/completions` endpoint with streaming
   enabled.
3. Reply tokens are split into sentences as they arrive. Each sentence is sent
   to `POST /v1/audio/speech` through a small worker pool and played in order, so
   speech starts before the model has finished. A few sentences are prefetched.
4. The reply also appears as a notification, and the full turn stays in memory
   for follow-up questions until `dictate assistant reset` or daemon exit.

Tap while it is thinking or speaking to interrupt. Playback and any in-flight TTS
requests are cancelled. Nothing is inserted into the focused window; the
assistant is a spoken/notification interface only.

### Setup

The LLM can be any server that speaks the OpenAI chat API. This project was
developed against a local Bonsai 1.7B `llama-server`, but the client does not
depend on llama.cpp specifically:

```sh
dictate config set llm_base_url http://127.0.0.1:8080/v1
dictate config set llm_model bonsai

# Optional: let the daemon start a local server on demand.
dictate config set llm_start_command "/path/to/Bonsai-demo/my_script.sh -m 1"
dictate config set llm_start_cwd /path/to/Bonsai-demo
```

When `llm_start_command` is set and the endpoint is local but unreachable, the
daemon runs the command with `llm_start_cwd`, logs stdout/stderr to
`$XDG_STATE_HOME/speech-flow/llm-server.log`, and waits up to `llm_start_timeout`
seconds for `/models`. A remote endpoint must already be running.

Phase 1 TTS is Xiaomi MiMo's voice service. It is an OpenAI-compatible chat
endpoint, but audio comes back as Base64 in the chat response rather than from
`/v1/audio/speech`; set `tts_provider = "mimo"` for that shape. Use the base URL
shown in your Token Plan console (for example
`https://token-plan-sgp.xiaomimimo.com/v1`):

```sh
dictate config set tts_provider mimo
dictate config set tts_base_url https://token-plan-sgp.xiaomimimo.com/v1
dictate config set tts_model mimo-v2.5-tts
dictate config set tts_voice Mia
dictate config set tts_format wav
dictate secrets set tts_api_key    # paste when prompted, then Ctrl+D
```

MiMo's built-in English voices are `Mia`, `Chloe`, `Milo`, and `Dean`; the
Chinese voices are `冰糖`, `茉莉`, `苏打`, and `白桦`; the default is
`mimo_default`. `mimo-v2.5-tts-voicedesign` takes a voice description instead
of a preset, and `mimo-v2.5-tts-voiceclone` takes a Base64 audio sample, so the
built-in `mimo-v2.5-tts` model is the right choice for this assistant.

For a provider that follows the more common OpenAI `/v1/audio/speech` shape,
leave `tts_provider = "openai"`. `tts_provider = "none"` disables synthesis;
replies are still shown as notifications. If the endpoint or key is missing, the
turn still completes and the reply is text-only, with a notification explaining
why.

Check everything without using the microphone:

```sh
dictate assistant doctor
dictate assistant warmup
```

`doctor` is read-only: it probes the LLM endpoint, validates TTS configuration
and key source, finds a player, and checks for `notify-send` and the Waybar
helper. `warmup` may start the LLM server and reports the endpoint, TTS, and
player it will use.

### Keys and privacy

API keys are never stored in `config.json`. Resolution order is the environment
variable named by `tts_api_key_env`/`llm_api_key_env`, then
`~/.config/speech-flow/secrets.json` (mode `0600`). `MIMO_API_KEY` is also
accepted as an alias for the TTS key. `dictate secrets list` reports only the
source, never the value.

The assistant sends the recognized text (not the microphone recording) to the
LLM endpoint, and reply sentences (not your voice) to the TTS endpoint. With a
local LLM and a local TTS server, the whole turn stays on the machine.

### Waybar

`install.sh` installs `dictate-assistant-waybar`. Add a custom module:

```json
"custom/dictate-assistant": {
  "exec": "dictate-assistant-waybar",
  "return-type": "json",
  "interval": 1,
  "on-click": "dictate assistant toggle",
  "on-click-right": "dictate assistant cancel",
  "on-click-middle": "dictate assistant reset"
}
```

The helper prints one JSON object per invocation with `text`, `class`, `alt`,
`tooltip`, and a `percentage` level while listening. States are `idle`,
`listening`, `transcribing`, `thinking`, `speaking`, and `error`. The
microphone stays visible so the module has a permanent spot; in the `listening`
state it changes to `󰍬 Speak now` with a level bar and timer. Highlight that
state with CSS:

```css
#custom-dictate-assistant.listening {
  background: #ffffff;
  color: #000000;
  border-radius: 8px;
  animation: dictate-pulse 1s ease-in-out infinite alternate;
}
@keyframes dictate-pulse {
  from { opacity: 1; }
  to { opacity: 0.55; }
}
```

Set `DICTATE_WAYBAR_IDLE=0` to hide the microphone when idle. The module
tolerates a stopped daemon and shows a hint instead of failing.

## Model

There is one catalog entry, `bark-3.0`, from
`https://huggingface.co/ConwayResearch/Underdog-Bark-3.0` at revision
`85db2ad18ab41e534a222ee253c29191d77ed919`. It is English-only.

Bark 3.0 is published as `model.bark` plus a NumPy loader, not as GGML.
`dictate models download bark-3.0` therefore:

1. Downloads the five pinned source files (about 167 MB total), checking each
   file's exact size and SHA-256.
2. Runs `scripts/convert-bark-to-ggml.py` locally. It verifies the decoded state
   dict and the final tensor-name set against pinned digests, then writes
   `bark-3.0-ggml-f16.bin` (1,255,897,319 bytes, about 1.2 GB).
3. Verifies the converted file's exact size and moves it into the models
   directory.

Sources are kept under `$XDG_DATA_HOME/speech-flow/models/sources/bark-3.0/`
so the model can be re-verified or re-converted. `dictate models remove bark-3.0`
deletes both the converted file and its sources.

The conversion needs `numpy` and `constriction` in the active Python; if either
is missing, the command prints an activation/install hint and stops. The
converted file is checked by size only, because libm rounding can change
individual bytes between systems. The pinned source hashes and decoded-state
digest catch any real model change.

`dictate models import FILE.bin` copies a compatible GGML Bark/parakeet model
into the models directory and selects it. Imported models are not hash-verified.

## Configuration

The config is JSON at `$XDG_CONFIG_HOME/speech-flow/config.json`
(normally `~/.config/speech-flow/config.json`). `dictate config set`
validates and writes it atomically with mode `0600`; `dictate reload` applies
changes to a running daemon.

| Key | Default | Meaning |
| --- | --- | --- |
| `model` | `bark-3.0` | catalog id or imported `.bin` file name |
| `threads` | `4` | Bark CPU threads (1–64) |
| `max_seconds` | `300` | recording limit in seconds (5–600) |
| `transcribe_timeout` | `900` | Bark timeout (30–3600 s) |
| `silence_rms` | `0.0015` | below this RMS the result is treated as silence |
| `asr_bin` | `""` | explicit `parakeet-cli` path; empty means auto-detect |
| `models_dir` | `""` | override model directory |
| `audio_source` | `""` | PipeWire source name; empty means system default |
| `insertion` | `auto` | `auto`, `wtype`, `clipboard`, `copy`, `none` |
| `restore_clipboard` | `true` | restore previous clipboard after a verified paste |
| `trailing_space` | `true` | add a space when text ends with `.`, `?`, `!`, or `…` |
| `notifications` | `true` | desktop notifications |
| `auto_start_daemon` | `true` | start the daemon from a hotkey if needed |
| `keep_audio` | `false` | keep temporary WAV files for debugging |
| `log_level` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

Assistant capture, history, and presentation:

| Key | Default | Meaning |
| --- | --- | --- |
| `assistant_max_seconds` | `120` | recording limit for one assistant turn (5–600) |
| `assistant_history_turns` | `6` | question/answer pairs kept in memory (0–50) |
| `assistant_notify_chars` | `180` | maximum characters in reply notifications (40–1000) |

LLM (OpenAI-compatible chat):

| Key | Default | Meaning |
| --- | --- | --- |
| `llm_base_url` | `http://127.0.0.1:8080/v1` | chat endpoint base URL |
| `llm_model` | `bonsai` | model name sent in requests |
| `llm_api_key_env` | `DICTATE_LLM_API_KEY` | environment variable checked first |
| `llm_system_prompt` | built-in | spoken-style prompt; keep replies short |
| `llm_temperature` | `0.5` | sampling temperature (0–2) |
| `llm_max_tokens` | `320` | reply token limit (16–4096) |
| `llm_timeout` | `120` | request timeout in seconds (5–600) |
| `llm_start_command` | `""` | optional command to start a local server |
| `llm_start_cwd` | `""` | working directory for that command |
| `llm_start_timeout` | `90` | seconds to wait for the server (5–600) |

TTS (OpenAI-compatible speech):

| Key | Default | Meaning |
| --- | --- | --- |
| `tts_provider` | `openai` | `openai` (`/v1/audio/speech`), `mimo` (`/v1/chat/completions` audio), or `none` |
| `tts_base_url` | `""` | endpoint base URL; empty disables speech |
| `tts_model` | `""` | model name; `mimo-v2.5-tts` for MiMo |
| `tts_voice` | `""` | OpenAI voice or MiMo built-in voice; MiMo defaults to `mimo_default` |
| `tts_format` | `wav` | `wav`, `mp3`, `opus`, `flac`, `pcm`, or `pcm16` (MiMo: wav/mp3/pcm) |
| `tts_speed` | `1.0` | speech rate (0.25–4.0) |
| `tts_api_key_env` | `DICTATE_TTS_API_KEY` | environment variable checked first |
| `tts_timeout` | `60` | request timeout in seconds (5–600) |
| `tts_workers` | `2` | parallel synthesis workers (1–8) |
| `tts_prefetch` | `3` | sentences synthesized ahead (1–16) |
| `tts_max_chars` | `240` | sentence-splitter soft limit (40–2000) |
| `tts_player` | `auto` | `auto`, `mpv`, `pw-cat`, `ffplay`, `none` |
| `tts_volume` | `1.0` | player volume, 0–1.5 |
| `tts_extra_body` | `{}` | extra JSON merged into the request body |

Bark 3.0 is English-only, so there is no language setting. Config files from the
Whisper-era Linux port are accepted; removed keys such as `language`,
`beam_size`, and `whisper_bin` are ignored and dropped on the next save. A
Whisper-era `model` value (for example `base` or `ggml-small.bin`) falls back to
`bark-3.0`.

### Insertion modes

- `auto` — type with `wtype`; if that fails, copy to the clipboard.
- `wtype` — type only; on failure, fall back to copying.
- `clipboard` — copy and send `Ctrl+V` through `wtype`, then restore the
  previous clipboard only if it still holds exactly the dictated text.
- `copy` — copy only and leave the text on the clipboard.
- `none` — transcribe without delivering anything. Useful headless, for
  testing, or when another tool will read the daemon status.

Line breaks are flattened before typing because `wtype` maps newlines to Return.
Nothing in this port sends Enter. When `trailing_space` is enabled (the default),
a transcript that ends with `.`, `?`, `!`, or `…` gets one trailing space, so a
following dictation starts with normal spacing instead of landing directly after
the full stop. Set `dictate config set trailing_space false` to disable it.

## CPU-only guarantees

The port refuses to run a `parakeet-cli` that does not advertise `-ng`:

1. `scripts/build-asr-linux.sh` builds with all GPU backends disabled and
   checks the binary and its linked libraries.
2. `asr.transcribe` and the daemon verify the `-ng` flag before every start.
3. Every invocation passes `-ng` plus empty `CUDA_VISIBLE_DEVICES`,
   `HIP_VISIBLE_DEVICES`, and `ROCR_VISIBLE_DEVICES`, with `GGML_CUDA=0`.
4. `dictate doctor` reports the linked GPU libraries, the runtime version, and
   the CPU-only flag.

If another process occupies the GPU, recognition neither sees nor touches it.
The optional assistant's LLM server is the exception: it is a separate process
started by `llm_start_command` and may use the GPU. That does not change ASR,
which still runs with every GPU device variable cleared.

## Privacy and data

Dictation recognition and correction run locally. The only network access for
dictation is an explicit `dictate models download` from Hugging Face. No audio or
transcript leaves the machine, and the conversion runs on your CPU.

The optional voice assistant sends the recognized text (not the microphone
recording) to the configured LLM endpoint, and each reply sentence (not your
voice) to the configured TTS endpoint. A local LLM and a local TTS server keep
the turn on-machine; the phase-1 Mimo TTS endpoint is remote. Assistant history
is kept in daemon memory only and is discarded on exit or `assistant reset`.

Audio is written to a private temporary WAV, transcribed, and deleted unless
`keep_audio` is true. The last dictation transcript stays in daemon memory for
`paste-last` and is lost when the daemon exits. There is no transcript history.

Persistent files:

| Path | Contents |
| --- | --- |
| `~/.config/speech-flow/config.json` | settings (mode 0600) |
| `~/.config/speech-flow/corrections.json` | dictionary entries |
| `~/.config/speech-flow/secrets.json` | assistant API keys (mode 0600, only if set) |
| `~/.local/share/speech-flow/models/` | converted GGML model and pinned sources |
| `~/.local/share/speech-flow/app/` | installed runtime, including `parakeet-cli` and its libraries |
| `~/.local/state/speech-flow/speech-flow.log` | rotating log |
| `~/.local/state/speech-flow/llm-server.log` | local LLM server output, if autostarted |
| `$XDG_RUNTIME_DIR/speech-flow.sock` | local control socket |
| `$XDG_RUNTIME_DIR/speech-flow.pid` | daemon PID |

Temporary TTS audio is written under the state directory with mode `0600` and
removed after playback or cancellation. Files left by a crash are swept on the
next assistant start.

## Optional systemd user service

The daemon normally starts from Hyprland's `exec-once`, but a user unit is
provided for compositor-independent startup:

```sh
mkdir -p ~/.config/systemd/user
cp ~/.local/share/speech-flow/app/linux/systemd/speech-flow.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now speech-flow.service
```

The unit binds to `graphical-session.target`, passes the Wayland environment
through, and repeats the empty GPU device variables.

## Limitations

- Wayland exposes no equivalent of the macOS Accessibility API, so this port
  cannot verify that a field accepted text or retry safely. It types or pastes
  once and reports what it attempted.
- There is no GUI. Everything is controlled by the CLI, the daemon socket, and
  compositor shortcuts.
- The assistant has no wake word and no voice-activity endpointing: you start and
  finish each turn with the hotkey. A tap also interrupts, but there is no
  barge-in while the microphone is closed.
- Assistant quality and latency depend on the LLM and TTS endpoints. The default
  pipeline speaks sentence by sentence, so the first words can arrive before the
  model has finished the reply.
- Hosted TTS introduces network latency and sends reply text to that provider;
  use a local endpoint if that matters. Assistant history is not persisted.
- Microphone selection is global rather than per-application.
- The dictionary is explicit only; there is no automatic learning.
- Hold mode depends on compositor `bindr` support. It is wired for Hyprland and
  has not been exercised with a physical key on this machine.
- Bark 3.0 is English-only. Recognition speed depends on `threads` and the
  machine; the converted model is about 1.2 GB and conversion itself takes a few
  minutes on CPU.
- Only the Hyprland integration is documented. `wtype`/`wl-clipboard` are
  generic Wayland tools, so other compositors may work with equivalent binds.
- Testing used whisper.cpp's sample audio through a PipeWire null sink. A
  physical microphone and physical hold-key path remain to be validated. See
  [`TESTING.md`](TESTING.md).

## Development

```sh
PYTHONPATH=linux python3 -m unittest discover -s linux/tests
./linux/dictate doctor
```

The package is Python standard library only at runtime; the one-time converter
also needs NumPy and constriction. Sources live in
[`ASR/`](ASR/); tests live in [`tests/`](tests/).

`./linux/dictate` runs from the checkout. `dictate` runs the installed copy in
`~/.local/share/speech-flow/app`; re-run `./linux/install.sh` after changing code
that the installed daemon should use.
See the repository [third-party notices](../THIRD_PARTY_NOTICES.md) for Bark
3.0, whisper.cpp, NumPy, and constriction licensing.
