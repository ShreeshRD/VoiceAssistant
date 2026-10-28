# Dictate Unlimited for Linux (CPU-only)

Free, local voice dictation on Linux. PipeWire capture, Bark 3.0 recognition
through whisper.cpp's `parakeet-cli`, a small background daemon, and Wayland
text insertion. No account, subscription, cloud inference, telemetry, or
Enter-key injection. Bark 3.0 runs on the CPU with every GPU backend disabled;
the model is English-only.

Tested on Arch Linux with Hyprland 0.56.2 (Wayland), PipeWire, and Python 3.14.
Python 3.11 or newer is required.

## Install

```sh
git clone https://github.com/ShreeshRD/VoiceAssistant.git
cd VoiceAssistant

python3 -m venv .venv                 # conversion-only dependencies
source .venv/bin/activate
pip install numpy constriction

./scripts/build-asr-linux.sh          # CPU-only parakeet-cli (whisper.cpp v1.9.5)
./linux/install.sh                    # symlink ~/.local/bin/dictate
./linux/dictate models download bark-3.0 --use
deactivate
./linux/dictate doctor
```

Arch marks its Python as externally managed (PEP 668), so the conversion-only
packages must go in a virtual environment (or an existing pyenv environment).
NumPy and constriction are only used while converting the downloaded Bark
weights; the daemon and CLI use only the Python standard library at runtime.

`install.sh` also accepts `--build-asr`, `--download-model ID`, `--hyprland`,
`--hold`, `--yes`, and `--force`. It creates the default config on first run.

## Hyprland shortcuts

```sh
dictate setup --hyprland          # tap mode: SUPER + D
dictate setup --hyprland --hold   # press SUPER + D to start, release to finish
```

The command writes a marked block into `~/.config/hypr/hyprland.conf`, keeps a
timestamped backup, and asks before writing when run interactively. Then reload
Hyprland:

```sh
hyprctl reload
```

Defaults (`linux/hyprland.conf.example`):

| Action | Tap mode | Hold mode |
| --- | --- | --- |
| Start / finish | `SUPER + D` | `SUPER + D` press / release |
| Paste last result | `SUPER + SHIFT + V` | `SUPER + SHIFT + V` |
| Cancel | `SUPER + Escape` | `SUPER + Escape` |

## Commands

```sh
dictate toggle                  # start, or stop and transcribe
dictate start                   # used by hold-mode key press
dictate stop                    # used by hold-mode key release
dictate cancel                  # discard recording or in-flight transcription
dictate paste-last              # re-insert the last completed transcript
dictate status                  # state, model, CPU use, level
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

dictate models list
dictate models download bark-3.0 --use
dictate models verify
dictate models import ~/Downloads/custom-ggml.bin
dictate models remove bark-3.0

dictate dictionary list
dictate dictionary add "heard phrase" "replacement"
dictate dictionary remove <id>
```

Configuration and diagnostics:

```sh
dictate config show
dictate config set threads 6
dictate doctor                  # 21 environment checks
dictate transcribe sample.wav   # offline file transcription
```

## Model

There is one catalog entry, `bark-3.0`, from
`https://huggingface.co/ConwayResearch/Underdog-Bark-3.0` at revision
`85db2ad18ab41e534a222ee253c29191d77ed919`. It is English-only.

Bark 3.0 is published as `model.bark` plus a NumPy loader, not as GGML.
`dictate models download bark-3.0` downloads the five pinned source files
(about 167 MB total), checking each file's exact size and SHA-256, then runs
`scripts/convert-bark-to-ggml.py` locally to write a `bark-3.0-ggml-f16.bin`
(about 1.2 GB). Sources are kept under
`$XDG_DATA_HOME/dictate-unlimited/models/sources/bark-3.0/`.

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
| `silence_rms` | `0.0015` | below this RMS the result is treated as silence |
| `asr_bin` | `""` | explicit `parakeet-cli` path; empty means auto-detect |
| `models_dir` | `""` | override model directory |
| `audio_source` | `""` | PipeWire source name; empty means system default |
| `insertion` | `auto` | `auto`, `wtype`, `clipboard`, `copy`, `none` |
| `notifications` | `true` | desktop notifications |
| `auto_start_daemon` | `true` | start the daemon from a hotkey if needed |

## CPU-only guarantee

The port refuses to run a `parakeet-cli` that does not advertise `-ng`. The
build script compiles with all GPU backends disabled and checks the binary and
its linked libraries before finishing.

## Privacy and data

Recognition and correction run locally. The only network access is an explicit
`dictate models download` from Hugging Face. No audio or transcript leaves the
machine, and the conversion runs on your CPU.

Audio is written to a private temporary WAV, transcribed, and deleted unless
`keep_audio` is true. There is no transcript history.

## Development

```sh
PYTHONPATH=linux python3 -m unittest discover -s linux/tests
./linux/dictate doctor
```

See [`linux/README.md`](linux/README.md) for the full port documentation,
including insertion modes, the systemd user service, and limitations.
