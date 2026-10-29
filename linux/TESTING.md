# Linux port testing

This records what was exercised for the Linux port and how to repeat it. It is
not a claim of broad hardware or application compatibility.

Last run: 2026-10-29 on Arch Linux, Hyprland 0.56.2 (Wayland), PipeWire,
Python 3.14.8 and 3.11.9 (pyenv `voice`), whisper.cpp 1.9.5 `parakeet-cli`
built CPU-only, Bark 3.0. The assistant suite uses local fake LLM/TTS servers;
a separate manual run exercised Bonsai, MiMo TTS, `mpv`, and notifications.

## Unit tests

```sh
PYTHONPATH=linux python3 -m unittest discover -s linux/tests
```

102 tests, all passing:

| File | Tests | Covers |
| --- | ---: | --- |
| `tests/test_asr.py` | 4 | configured binary, stdout transcript, stderr error path, capability probe environment |
| `tests/test_asr_parse.py` | 8 | parakeet transcript cleanup, special tokens, CPU flags |
| `tests/test_assistant.py` | 25 | sentence splitting, think-tag filtering, LLM/TTS clients, secrets, speech pipeline, full simulated turn |
| `tests/test_audio.py` | 8 | PCM statistics, WAV stats, capture lifecycle |
| `tests/test_config.py` | 7 | defaults, validation, typed `config set`, legacy-key migration |
| `tests/test_corrections.py` | 22 | ordering, matching, add/remove/clear, persistence, chat |
| `tests/test_daemon.py` | 6 | state machine, cancellation, delivery, shutdown |
| `tests/test_hyprland.py` | 5 | generated tap/hold blocks, legacy marker migration |
| `tests/test_insertion.py` | 9 | sanitization, mode fallbacks, trailing space |
| `tests/test_ipc.py` | 2 | socket request/response and error paths |
| `tests/test_models.py` | 6 | catalog rules, source verification, path resolution |

## Environment check

```sh
dictate doctor
```

The installed runtime lives in `~/.local/share/speech-flow/app`; `dictate` and
`dictate-assistant-waybar` in `~/.local/bin` are symlinks into it. `doctor`
reports the ASR binary and `-ng` capability from that copy, and dictation keeps
working after the checkout is moved.

Result: 24 checks, 0 failures, 0 warnings with the daemon running and the
optional assistant LLM/TTS endpoints configured. The check confirmed:

- Python 3.14.8, PipeWire, `pactl`, `wtype`, `wl-clipboard`, `notify-send`.
- 6 PipeWire sources with a default input.
- `parakeet-cli` linked against `libparakeet.so.1.9.5`, with `-ng` present.
- No CUDA, Vulkan, HIP, ROCm, or OpenCL libraries linked.
- `bark-3.0` installed and English-only.

## Model conversion

```sh
source .venv/bin/activate        # or: pyenv shell voice
./linux/dictate models download bark-3.0 --use
```

The five pinned source files (about 167 MB) were verified, then converted
locally to `bark-3.0-ggml-f16.bin`:

```text
size:   1,255,897,319 bytes
sha256: 357011a55f254e554b97b58f852d3de0e668fc83537a5c04d169422c4ca945e1
```

That SHA-256 is recorded as a reference for this machine, not enforced on other
systems: libm can change the Hann-window bytes slightly. The converter enforces
the pinned decoded-state digest and the 721-name tensor set, and the catalog
enforces the exact output size. `dictate models verify` also re-checks every
pinned source file.

The conversion needed NumPy and constriction in the active Python. It was run
in a temporary virtual environment and in the pyenv `voice` environment; Arch's
system Python is externally managed, so use `python3 -m venv .venv` (or an
existing pyenv/venv) and `pip install numpy constriction` there.

## Offline file transcription

```sh
./linux/dictate transcribe \
  linux/.dependencies/whisper.cpp/samples/jfk.wav
```

Output:

```text
And so, my fellow Americans, ask not what your country can do for you. Ask what you can do for your country
```

This ran with `-ng`, 4 threads, and empty GPU device variables while a separate
`llama-server` process held the GPU. No GPU memory use was observed for the
dictation process.

## PipeWire capture and daemon end-to-end

The machine's physical microphone was not used for the automated run. Instead a
temporary null sink was created and the JFK sample was looped into it, so the
full capture → WAV → CPU transcription → state transition path could be tested
without depending on room audio.

Outline of the procedure:

```sh
pactl load-module module-null-sink sink_name=dictate_test_sink
pactl set-default-source dictate_test_sink.monitor

# Play a known speech sample into dictate_test_sink with paplay in a loop.
./linux/dictate mic test --seconds 2     # reported "signal detected"

./linux/dictate daemon --detach
./linux/dictate start
sleep 3.5
./linux/dictate stop
./linux/dictate status
./linux/dictate quit

pactl unload-module module-null-sink
```

Observed:

- `mic test` detected signal from the null-sink monitor.
- Daemon accepted `start`, recorded 3.71 s, accepted `stop`, and transcribed on
  CPU with `bark-3.0`.
- The run produced a 24-character transcript and returned to `idle`.
- `quit` shut the daemon down cleanly with socket and PID cleanup.
- Temporary audio was deleted after transcription.

Note: in this environment `pw-cat --target dictate_test_sink.monitor` did not
follow the monitor name, so the test set the monitor as the default source and
left `audio_source` empty. With a normal physical microphone, selecting it with
`dictate mic use <source>` remains the intended path.

The null sink and sample loop were removed afterwards. The real default source
and configuration were restored.

## Not yet tested

- A physical microphone in a real room, including gain and mute behaviour.
- A physical hold-mode key press/release through Hyprland `bindr`.
- Insertion into a range of real applications (terminals, browsers, chat apps).
- Long recordings near the 300-second default limit.
- Non-Hyprland compositors.
- ARM or other CPU architectures.

Treat those as unverified rather than broken. `dictate doctor`, `dictate mic
test`, and `dictate status --watch` are the first checks when something does not
work.
