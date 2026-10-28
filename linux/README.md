# Dictate Unlimited for Linux (CPU-only)

This directory is a native Linux port: PipeWire capture, Bark 3.0 recognition
through whisper.cpp's `parakeet-cli`, a small background daemon, and Wayland
text insertion. The repository is Linux-only; the macOS Swift GUI has been
removed.

The port has no account, cloud inference, telemetry, update service, or Enter-key
injection. Bark 3.0 runs on the CPU with every GPU backend disabled, and the
model is English-only.

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
| libnotify | `libnotify` | desktop notifications (optional) |
| Hyprland | `hyprland` | shortcuts (optional, compositor-specific) |

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
git clone https://github.com/DanielJD1216/dictate-unlimited.git
cd dictate-unlimited

python3 -m venv .venv                 # conversion-only dependencies
source .venv/bin/activate
pip install numpy constriction

./scripts/build-asr-linux.sh          # CPU-only parakeet-cli (whisper.cpp v1.9.5)
./linux/install.sh                    # symlink ~/.local/bin/dictate
./linux/dictate models download bark-3.0 --use
deactivate
./linux/dictate doctor
```

If you already have a pyenv or virtual environment with NumPy and constriction
(for example, `pyenv shell voice`), activate that instead of creating `.venv`.

`install.sh` also accepts `--build-asr`, `--download-model ID`, `--hyprland`,
`--hold`, `--yes`, and `--force`. It creates the default config on first run and
never edits your compositor configuration unless you pass `--hyprland`.

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
```

The command writes a marked block between `# >>> dictate-unlimited >>>` and
`# <<< dictate-unlimited <<<`, keeps a timestamped backup, and asks before
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
dictate dictionary add "heard phrase" "replacement"
dictate dictionary remove <id>
dictate dictionary clear
dictate dictionary apply "some text"
```

Configuration and diagnostics:

```sh
dictate config path
dictate config show
dictate config get threads
dictate config set threads 6
dictate config edit

dictate doctor                  # 21 environment checks
dictate transcribe sample.wav   # offline file transcription
dictate transcribe sample.wav --json
dictate transcribe sample.wav --insert
```

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

Sources are kept under `$XDG_DATA_HOME/dictate-unlimited/models/sources/bark-3.0/`
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

The config is JSON at `$XDG_CONFIG_HOME/dictate-unlimited/config.json`
(normally `~/.config/dictate-unlimited/config.json`). `dictate config set`
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
| `notifications` | `true` | desktop notifications |
| `auto_start_daemon` | `true` | start the daemon from a hotkey if needed |
| `keep_audio` | `false` | keep temporary WAV files for debugging |
| `log_level` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

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
Nothing in this port sends Enter.

## CPU-only guarantees

The port refuses to run a `parakeet-cli` that does not advertise `-ng`:

1. `scripts/build-asr-linux.sh` builds with all GPU backends disabled and
   checks the binary and its linked libraries.
2. `asr.transcribe` and the daemon verify the `-ng` flag before every start.
3. Every invocation passes `-ng` plus empty `CUDA_VISIBLE_DEVICES`,
   `HIP_VISIBLE_DEVICES`, and `ROCR_VISIBLE_DEVICES`, with `GGML_CUDA=0`.
4. `dictate doctor` reports the linked GPU libraries, the runtime version, and
   the CPU-only flag.

If another process occupies the GPU, this port neither sees nor touches it.

## Privacy and data

Recognition and correction run locally. The only network access is an explicit
`dictate models download` from Hugging Face. No audio or transcript leaves the
machine, and the conversion runs on your CPU.

Audio is written to a private temporary WAV, transcribed, and deleted unless
`keep_audio` is true. The last transcript stays in daemon memory for
`paste-last` and is lost when the daemon exits. There is no transcript history.

Persistent files:

| Path | Contents |
| --- | --- |
| `~/.config/dictate-unlimited/config.json` | settings (mode 0600) |
| `~/.config/dictate-unlimited/corrections.json` | dictionary entries |
| `~/.local/share/dictate-unlimited/models/` | converted GGML model and pinned sources |
| `~/.local/state/dictate-unlimited/dictate-unlimited.log` | rotating log |
| `$XDG_RUNTIME_DIR/dictate-unlimited.sock` | local control socket |
| `$XDG_RUNTIME_DIR/dictate-unlimited.pid` | daemon PID |

## Optional systemd user service

The daemon normally starts from Hyprland's `exec-once`, but a user unit is
provided for compositor-independent startup:

```sh
mkdir -p ~/.config/systemd/user
cp linux/systemd/dictate-unlimited.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now dictate-unlimited.service
```

The unit binds to `graphical-session.target`, passes the Wayland environment
through, and repeats the empty GPU device variables.

## Limitations

- Wayland exposes no equivalent of the macOS Accessibility API, so this port
  cannot verify that a field accepted text or retry safely. It types or pastes
  once and reports what it attempted.
- There is no GUI. Everything is controlled by the CLI, the daemon socket, and
  compositor shortcuts.
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
[`dictate_unlimited/`](dictate_unlimited/); tests live in [`tests/`](tests/).
See the repository [third-party notices](../THIRD_PARTY_NOTICES.md) for Bark
3.0, whisper.cpp, NumPy, and constriction licensing.
