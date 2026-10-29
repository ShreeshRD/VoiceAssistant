# Speech Flow for Linux (CPU-only)

Free, local voice dictation on Linux. PipeWire capture, Bark 3.0 recognition
through whisper.cpp's `parakeet-cli`, a small background daemon, and Wayland
text insertion. Dictation has no account, subscription, cloud inference,
telemetry, or Enter-key injection. Bark 3.0 runs on the CPU with every GPU
backend disabled; the model is English-only.

Dictation also ships with an optional hands-free voice assistant that reuses the
same microphone and CPU recognizer, then streams a reply from a local
OpenAI-compatible LLM and speaks it through an OpenAI-compatible TTS endpoint.
It is off until you configure an endpoint; dictation itself is unchanged.

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
./linux/install.sh                    # runtime to ~/.local/share/speech-flow/app
./linux/dictate models download bark-3.0 --use
deactivate
./linux/dictate doctor
```

Arch marks its Python as externally managed (PEP 668), so the conversion-only
packages must go in a virtual environment (or an existing pyenv environment).
NumPy and constriction are only used while converting the downloaded Bark
weights; the daemon and CLI use only the Python standard library at runtime.

`install.sh` copies a self-contained runtime to
`~/.local/share/speech-flow/app` and links `dictate` and the Waybar helper into
`~/.local/bin`. The installed daemon and `parakeet-cli` do not reference the
checkout, so the repository can be moved or removed after installation. Re-run
`install.sh` after updating the code or rebuilding the ASR runtime.

`install.sh` also accepts `--build-asr`, `--download-model ID`, `--prefix DIR`,
`--hyprland`, `--hold`, `--assistant`, `--yes`, and `--force`. It creates the
default config on first run and never edits your compositor configuration unless
you pass `--hyprland`.

## Hyprland shortcuts

```sh
dictate setup --hyprland                # tap mode: SUPER + D
dictate setup --hyprland --hold         # press SUPER + D to start, release to finish
dictate setup --hyprland --assistant    # dictation plus SUPER + A for the assistant
```

The command writes a marked block into `~/.config/hypr/hyprland.conf`, keeps a
timestamped backup, and asks before writing when run interactively. If
`SUPER + A` is already bound elsewhere, comment out that bind first: Hyprland
uses the first match, so the assistant bind would never fire. Then reload
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
| Assistant start / finish / interrupt | `SUPER + A` | `SUPER + A` |

The assistant row is only written when `setup` is given `--assistant`. Tapping
`SUPER + A` while the assistant is thinking or speaking interrupts it, so there
is no separate cancel shortcut.

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
dictate dictionary chat
dictate dictionary add "heard phrase" "replacement"
dictate dictionary remove <id>
```

Configuration and diagnostics:

```sh
dictate config show
dictate config set threads 6
dictate doctor                  # environment checks
dictate transcribe sample.wav   # offline file transcription
```

Voice assistant:

```sh
dictate assistant toggle        # start listening, or finish/interrupt a turn
dictate assistant status        # state, model, TTS, history depth
dictate assistant warmup        # start the LLM and check TTS/player setup
dictate assistant doctor        # endpoint, key, player, and Waybar checks
dictate assistant reset         # clear in-memory conversation history
dictate secrets set tts_api_key # reads the key from stdin, never argv
dictate secrets list            # shows where each key comes from
```

## Voice assistant (optional)

The assistant is a second mode in the same daemon. It captures through
PipeWire, transcribes with the same CPU-only Bark runtime, sends the transcript
to an OpenAI-compatible chat endpoint, splits the streamed reply into sentences,
synthesizes them with bounded parallelism, and plays the audio in order. The
reply is also shown as a short notification and in the Waybar module.

Configure it once, then check it:

```sh
dictate config set llm_base_url http://127.0.0.1:8080/v1
dictate config set llm_model bonsai
dictate config set llm_start_command "/path/to/Bonsai-demo/my_script.sh -m 1"
dictate config set llm_start_cwd /path/to/Bonsai-demo

dictate config set tts_provider mimo
dictate config set tts_base_url https://token-plan-sgp.xiaomimimo.com/v1
dictate config set tts_model mimo-v2.5-tts
dictate config set tts_voice Mia
dictate secrets set tts_api_key          # paste the key, then Ctrl+D

dictate assistant doctor
dictate assistant warmup
```

The LLM endpoint only needs to implement `POST /v1/chat/completions` with
streaming. If the endpoint is local and `llm_start_command` is set, the daemon
starts it on demand and logs it to
`$XDG_STATE_HOME/speech-flow/llm-server.log`.

TTS has two request shapes. `tts_provider = "mimo"` posts to
`POST /v1/chat/completions` and reads Base64 audio from the response, which is
how the MiMo-V2.5-TTS series works; `tts_voice` can be `mimo_default`, `Mia`,
`Chloe`, `Milo`, `Dean`, or a Chinese built-in voice such as `冰糖`.
`tts_provider = "openai"` uses the more common `POST /v1/audio/speech` shape
instead, and `none` keeps replies text-only.

API keys never go in `config.json`. The daemon checks the environment variable
named by `tts_api_key_env` (default `DICTATE_TTS_API_KEY`, with `MIMO_API_KEY`
as an alias), then `~/.config/speech-flow/secrets.json` (mode `0600`,
written by `dictate secrets set`).

With `SUPER + A`:

1. Tap once to listen. The Waybar module shows a level meter and elapsed time.
2. Tap again to stop, transcribe, and send the turn to the LLM.
3. Tap again while it is thinking or speaking to interrupt and discard the turn.

`dictate assistant reset` clears the in-memory conversation; history is never
written to disk and is trimmed to `assistant_history_turns`.

### Waybar

`install.sh` installs the module helper. Add this to your Waybar config:

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

The microphone icon stays visible in the bar. While the assistant is listening
the module switches to `󰍬 Speak now` with a live level bar and timer, so it is
clear when to talk. Style the state with Waybar CSS:

```css
#custom-dictate-assistant { padding: 0 8px; }
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

Use `interval: 1` normally; the module is cheap and updates the level meter
while listening. Set `DICTATE_WAYBAR_IDLE=0` to hide the microphone when idle.

## Model

There is one catalog entry, `bark-3.0`, from
`https://huggingface.co/ConwayResearch/Underdog-Bark-3.0` at revision
`85db2ad18ab41e534a222ee253c29191d77ed919`. It is English-only.

Bark 3.0 is published as `model.bark` plus a NumPy loader, not as GGML.
`dictate models download bark-3.0` downloads the five pinned source files
(about 167 MB total), checking each file's exact size and SHA-256, then runs
`scripts/convert-bark-to-ggml.py` locally to write a `bark-3.0-ggml-f16.bin`
(about 1.2 GB). Sources are kept under
`$XDG_DATA_HOME/speech-flow/models/sources/bark-3.0/`.

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
| `silence_rms` | `0.0015` | below this RMS the result is treated as silence |
| `asr_bin` | `""` | explicit `parakeet-cli` path; empty means auto-detect |
| `models_dir` | `""` | override model directory |
| `audio_source` | `""` | PipeWire source name; empty means system default |
| `insertion` | `auto` | `auto`, `wtype`, `clipboard`, `copy`, `none` |
| `trailing_space` | `true` | add a space when text ends with `.`, `?`, `!`, or `…` |
| `notifications` | `true` | desktop notifications |
| `auto_start_daemon` | `true` | start the daemon from a hotkey if needed |
| `assistant_max_seconds` | `120` | assistant recording limit in seconds (5–600) |
| `assistant_history_turns` | `6` | conversation turns kept in memory |
| `assistant_notify_chars` | `180` | reply characters shown in notifications |
| `llm_base_url` | `http://127.0.0.1:8080/v1` | OpenAI-compatible chat endpoint |
| `llm_model` | `bonsai` | model name sent to the chat endpoint |
| `llm_start_command` | `""` | optional command that starts a local LLM server |
| `tts_provider` | `openai` | `openai` (`/v1/audio/speech`), `mimo` (`/v1/chat/completions`), or `none` |
| `tts_base_url` | `""` | TTS endpoint; empty disables speech |
| `tts_model` | `""` | TTS model name (for MiMo, `mimo-v2.5-tts`) |
| `tts_voice` | `""` | TTS voice name (MiMo defaults to `mimo_default`) |
| `tts_player` | `auto` | `auto`, `mpv`, `pw-cat`, `ffplay`, `none` |

## CPU-only guarantee

The port refuses to run a `parakeet-cli` that does not advertise `-ng`. The
build script compiles with all GPU backends disabled and checks the binary and
its linked libraries before finishing. These guarantees cover speech
recognition: the optional assistant's LLM server may use the GPU, but it is a
separate process configured by `llm_start_command` and never changes the ASR
path.

## Privacy and data

Dictation recognition and correction run locally. The only network access for
dictation is an explicit `dictate models download` from Hugging Face. No audio or
transcript leaves the machine, and the conversion runs on your CPU.

The optional voice assistant is different: when you use it, the recognized text
(never the microphone recording) is sent to the configured LLM endpoint, and each
reply sentence is sent to the configured TTS endpoint. Point both at local
services to keep the whole turn on-machine; the phase-1 Mimo TTS endpoint is
remote. Assistant history is in memory only.

Audio is written to a private temporary WAV, transcribed, and deleted unless
`keep_audio` is true. There is no transcript history on disk. The TTS client also
writes temporary audio files and removes them after playback; a sweep at the next
assistant start cleans up files left by a crash.

## Development

```sh
PYTHONPATH=linux python3 -m unittest discover -s linux/tests
./linux/dictate doctor
```

`./linux/dictate` runs from the checkout; `dictate` runs the installed copy in
`~/.local/share/speech-flow/app`. Re-run `./linux/install.sh` after changing
code that the installed daemon should use.

See [`linux/README.md`](linux/README.md) for the full port documentation,
including insertion modes, the systemd user service, and limitations.
