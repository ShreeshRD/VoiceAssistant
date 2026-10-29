"""Command-line interface for the Linux port."""

from __future__ import annotations

import argparse
import getpass
import json
import math
import os
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import (
    __version__,
    asr,
    audio,
    config as config_module,
    corrections,
    daemon as daemon_module,
    doctor,
    insertion,
    ipc,
    llm,
    models,
    paths,
    playback,
    secrets,
    tts,
)


def _parent() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--config",
        type=Path,
        default=argparse.SUPPRESS,
        help="configuration file (default: $XDG_CONFIG_HOME/dictate-unlimited/config.json)",
    )
    return parent


def build_parser() -> argparse.ArgumentParser:
    common = _parent()
    parser = argparse.ArgumentParser(
        prog="dictate",
        description="CPU-only local dictation for Linux (PipeWire + Bark 3.0 + Wayland).",
        parents=[common],
    )
    parser.add_argument("--version", action="version", version=f"dictate-unlimited {__version__}")
    sub = parser.add_subparsers(dest="command")

    daemon_parser = sub.add_parser("daemon", parents=[common], help="run the dictation daemon")
    mode = daemon_parser.add_mutually_exclusive_group()
    mode.add_argument("--detach", action="store_true", help="fork into the background")
    mode.add_argument("--foreground", action="store_true", help="stay in the foreground (default)")

    status_parser = sub.add_parser("status", parents=[common], help="show daemon state")
    status_parser.add_argument("--json", action="store_true", help="machine-readable output")
    status_parser.add_argument("--watch", action="store_true", help="refresh a live level meter")

    for name, help_text in (
        ("start", "start recording (hold-mode key press)"),
        ("stop", "finish recording and transcribe (hold-mode release)"),
        ("toggle", "start or finish dictation"),
        ("cancel", "discard the current recording or transcription"),
        ("paste-last", "insert the last completed dictation again"),
        ("reload", "reload configuration and dictionary"),
        ("quit", "stop the daemon"),
    ):
        sub.add_parser(name, parents=[common], help=help_text)

    transcribe_parser = sub.add_parser(
        "transcribe", parents=[common], help="transcribe audio files offline (CPU only)"
    )
    transcribe_parser.add_argument("files", nargs="+", type=Path)
    transcribe_parser.add_argument("--model", help="model id or .bin path")
    transcribe_parser.add_argument("--json", action="store_true")
    transcribe_parser.add_argument("--insert", action="store_true", help="deliver the result to the focused window")

    models_parser = sub.add_parser("models", parents=[common], help="manage local speech models")
    models_sub = models_parser.add_subparsers(dest="models_command")
    models_sub.add_parser("list", parents=[common], help="list catalog and installed models")
    download = models_sub.add_parser("download", parents=[common], help="download a model")
    download.add_argument("id", nargs="?")
    download.add_argument("--all", action="store_true", help="download every catalog model")
    download.add_argument("--force", action="store_true", help="replace an existing file")
    download.add_argument("--use", action="store_true", help="select the downloaded model")
    for name, help_text in (("use", "select an installed model"), ("remove", "delete a model")):
        command = models_sub.add_parser(name, parents=[common], help=help_text)
        command.add_argument("id")
    verify = models_sub.add_parser("verify", parents=[common], help="verify size and sha256")
    verify.add_argument("id", nargs="?")
    path_parser = models_sub.add_parser("path", parents=[common], help="print a model path")
    path_parser.add_argument("id", nargs="?")
    import_parser = models_sub.add_parser("import", parents=[common], help="copy a local GGML .bin model")
    import_parser.add_argument("source", type=Path)
    import_parser.add_argument("--force", action="store_true")

    mic_parser = sub.add_parser("mic", parents=[common], help="inspect and test microphones")
    mic_sub = mic_parser.add_subparsers(dest="mic_command")
    mic_sub.add_parser("list", parents=[common], help="list PipeWire sources")
    test = mic_sub.add_parser("test", parents=[common], help="record a short signal test")
    test.add_argument("--seconds", type=int, default=5)
    use_mic = mic_sub.add_parser("use", parents=[common], help="select a source name")
    use_mic.add_argument("source", nargs="?")
    use_mic.add_argument("--default", action="store_true")

    dictionary_parser = sub.add_parser("dictionary", parents=[common], help="manage local corrections")
    dictionary_sub = dictionary_parser.add_subparsers(dest="dictionary_command")
    dictionary_sub.add_parser("list", parents=[common], help="list corrections")
    add = dictionary_sub.add_parser("add", parents=[common], help="add a correction")
    add.add_argument("heard")
    add.add_argument("replacement")
    remove = dictionary_sub.add_parser("remove", parents=[common], help="remove a correction by id")
    remove.add_argument("id")
    clear = dictionary_sub.add_parser("clear", parents=[common], help="remove all corrections")
    clear.add_argument("--force", action="store_true")
    apply_parser = dictionary_sub.add_parser("apply", parents=[common], help="apply corrections to text")
    apply_parser.add_argument("text", nargs="+")

    assistant_parser = sub.add_parser(
        "assistant", parents=[common], help="voice assistant: ASR → LLM → TTS"
    )
    assistant_sub = assistant_parser.add_subparsers(dest="assistant_command")
    for name, help_text in (
        ("toggle", "start listening, or finish/interrupt the current turn"),
        ("start", "start listening"),
        ("stop", "finish recording and ask the LLM"),
        ("cancel", "discard the recording or interrupt the reply"),
        ("reset", "clear the in-memory conversation history"),
        ("warmup", "start the LLM server and check TTS/player configuration"),
    ):
        assistant_sub.add_parser(name, parents=[common], help=help_text)
    assistant_status = assistant_sub.add_parser(
        "status", parents=[common], help="show assistant state (used by Waybar)"
    )
    assistant_status.add_argument("--json", action="store_true", help="machine-readable output")
    assistant_sub.add_parser(
        "doctor", parents=[common], help="check the LLM, TTS, and playback setup"
    )

    secrets_parser = sub.add_parser(
        "secrets", parents=[common], help="store API keys privately (mode 0600)"
    )
    secrets_sub = secrets_parser.add_subparsers(dest="secrets_command")
    secrets_sub.add_parser("list", parents=[common], help="show which secrets are configured")
    secrets_set = secrets_sub.add_parser(
        "set", parents=[common], help="store a key (reads stdin, never argv)"
    )
    secrets_set.add_argument("name", choices=list(secrets.SECRET_KEYS))
    secrets_unset = secrets_sub.add_parser(
        "unset", parents=[common], help="remove a stored key"
    )
    secrets_unset.add_argument("name", choices=list(secrets.SECRET_KEYS))

    config_parser = sub.add_parser("config", parents=[common], help="inspect or edit settings")
    config_sub = config_parser.add_subparsers(dest="config_command")
    config_sub.add_parser("path", parents=[common], help="print the config file path")
    config_sub.add_parser("show", parents=[common], help="print the current config")
    get = config_sub.add_parser("get", parents=[common], help="print one setting")
    get.add_argument("key")
    set_parser = config_sub.add_parser("set", parents=[common], help="change one setting")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    config_sub.add_parser("edit", parents=[common], help="open the config in $EDITOR")

    sub.add_parser("doctor", parents=[common], help="check the Linux environment")
    setup = sub.add_parser("setup", parents=[common], help="first-run checks, model and Hyprland hints")
    setup.add_argument("--model", default=None, help="model id to download")
    setup.add_argument("--no-download", action="store_true")
    setup.add_argument("--build-asr", action="store_true", help="build the whisper.cpp CPU-only runtime")
    setup.add_argument("--hyprland", action="store_true", help="append a keybind block to Hyprland config")
    setup.add_argument("--hold", action="store_true", help="install press/release hold binds")
    setup.add_argument(
        "--assistant",
        action="store_true",
        help="also bind SUPER+A to the voice assistant (tap to talk)",
    )
    setup.add_argument("--yes", "-y", action="store_true", help="do not prompt")
    return parser


def _load_config(args: argparse.Namespace) -> config_module.Config | None:
    configured = getattr(args, "config", None)
    if configured is not None:
        os.environ["DICTATE_CONFIG"] = str(configured.expanduser())
    try:
        return config_module.ensure()
    except (config_module.ConfigError, OSError) as exc:
        return _fail(f"configuration error: {exc}")


def _fail(message: str) -> None:
    print(message, file=sys.stderr)
    return None


def _client(
    command: str,
    config: config_module.Config,
    *,
    autostart: bool | None = None,
    json_mode: bool = False,
) -> int:
    if autostart is None:
        autostart = config.auto_start_daemon
    try:
        response = ipc.request(command, autostart=autostart)
    except ipc.IPCError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if json_mode:
        print(json.dumps(response, indent=2, sort_keys=True))
    else:
        message = str(response.get("message", "")).strip()
        if message:
            print(message)
        if command == "status" and response.get("ok"):
            _print_status(response)
    return 0 if response.get("ok") else 1


def _meter(level: float, width: int = 30) -> str:
    db = 20 * math.log10(max(level, 1e-6))
    filled = int(max(0.0, min(1.0, (db + 60) / 60)) * width)
    return "[" + "#" * filled + "-" * (width - filled) + f"] {db:5.1f} dB"


def _print_status(response: dict[str, Any]) -> None:
    data = response.get("data", {})
    state = response.get("state", "?")
    print(f"state:       {state}")
    print(f"model:       {data.get('model', '?')}")
    print(f"threads:     {data.get('threads', '?')} · CPU only")
    print(f"insertion:   {data.get('insertion', '?')}")
    print(f"corrections: {data.get('corrections', 0)}")
    print(f"last:        {'available' if data.get('has_last') else 'none'} ({data.get('last_chars', 0)} chars)")
    print(f"pid:         {data.get('pid', '?')}")
    assistant = data.get("assistant")
    if isinstance(assistant, dict) and assistant.get("active"):
        print(f"assistant:   {assistant.get('state')} · {assistant.get('message', '')}")
        if assistant.get("heard"):
            print(f"heard:       {assistant['heard']}")
        if assistant.get("reply"):
            print(f"reply:       {assistant['reply']}")
    if state in ("recording", "testing", "starting", "listening"):
        live = assistant if isinstance(assistant, dict) and assistant.get("active") else data
        print(f"duration:    {live.get('seconds', 0):.1f}s")
        print(f"level:       {_meter(float(live.get('level', 0)))}")


def _status_watch(config: config_module.Config) -> int:
    try:
        while True:
            try:
                response = ipc.request("status", timeout=2, autostart=False)
            except ipc.IPCError as exc:
                print("\033[2J\033[H", end="")
                print(f"daemon not running: {exc}")
                time.sleep(0.5)
                continue
            print("\033[2J\033[H", end="")
            print(f"Dictate Unlimited · {response.get('state')}")
            print(str(response.get("message", "")))
            data = response.get("data", {})
            print(
                f"model {data.get('model')} · {data.get('seconds', 0):.1f}s · "
                f"{data.get('last_chars', 0)} last chars"
            )
            print(_meter(float(data.get("level", 0)), width=50))
            print("\nCtrl+C to stop watching.")
            time.sleep(0.15)
    except KeyboardInterrupt:
        print()
        return 0


def _cmd_daemon(args: argparse.Namespace) -> int:
    config = _load_config(args)
    if config is None:
        return 1
    detach = bool(getattr(args, "detach", False))
    return daemon_module.run(config, detach=detach, foreground=not detach)


def _cmd_transcribe(args: argparse.Namespace) -> int:
    config = _load_config(args)
    if config is None:
        return 1
    if args.model:
        config.model = args.model
    try:
        config.validate()
    except config_module.ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 1
    store = corrections.CorrectionStore(paths.corrections_path())
    if store.load_error:
        print(f"warning: corrections disabled: {store.load_error}", file=sys.stderr)

    results: list[dict[str, Any]] = []
    for raw in args.files:
        path = raw.expanduser()
        if not path.is_file():
            print(f"not found: {path}", file=sys.stderr)
            return 1
        if path.suffix.lower() == ".wav":
            try:
                duration, _, _ = audio.wav_stats(path)
                if duration > config.max_seconds + 0.05:
                    print(
                        f"{path}: {duration:.1f}s exceeds the {config.max_seconds}s limit",
                        file=sys.stderr,
                    )
                    return 1
            except audio.AudioError:
                pass
        try:
            text = asr.transcribe(path, config)
        except asr.ASRError as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            return 1
        text = store.apply(text).strip()
        results.append({"file": str(path), "text": text})
        if args.insert and text:
            delivery = insertion.deliver(text, config)
            print(delivery.message, file=sys.stderr)
            if not delivery.ok:
                return 1
        elif text:
            print(text)
        else:
            print(f"{path}: no speech detected", file=sys.stderr)
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


def _progress(done: int, total: int) -> None:
    if not sys.stderr.isatty():
        return
    fraction = min(1.0, done / max(total, 1))
    width = 32
    filled = int(fraction * width)
    sys.stderr.write(f"\r[{'#' * filled}{'-' * (width - filled)}] {fraction * 100:5.1f}%")
    sys.stderr.flush()


def _status_line(message: str) -> None:
    print(message, file=sys.stderr)


def _cmd_models(args: argparse.Namespace) -> int:
    config = _load_config(args)
    if config is None:
        return 1
    command = getattr(args, "models_command", None)
    if command in (None, "list"):
        rows = models.installed(config)
        print(f"{'':2}{'id':24} {'state':14} {'size':>8}  name")
        for info, path, installed in rows:
            selected = "*" if config.model == info.id else " "
            state = "installed" if installed else "not installed"
            size = info.display_size
            suffix = " (recommended)" if info.recommended else ""
            print(f"{selected:2}{info.id:24} {state:14} {size:>8}  {info.name}{suffix}")
        custom = list(models.custom_models(config))
        if custom:
            print("\nlocal imports:")
            for path in custom:
                selected = "*" if config.model == path.name else " "
                print(f"{selected:2}{path.name:24} {'installed':14} {path.stat().st_size / 1024**2:7.0f} MB")
        return 0
    try:
        if command == "download":
            if args.all:
                targets = models.catalog()
            elif args.id:
                targets = [models.find(args.id)]
            else:
                try:
                    targets = [models.find(config.model)]
                except models.ModelError:
                    targets = [next(info for info in models.catalog() if info.recommended)]
            for info in targets:
                destination = config.models_path() / info.file
                if destination.exists() and not args.force:
                    try:
                        models.verify(destination, info)
                        print(f"{info.id}: already installed at {destination}")
                    except models.ModelError:
                        print(f"{info.id}: existing file is invalid; downloading again")
                        destination = models.download(
                            info,
                            config.models_path(),
                            force=True,
                            progress=_progress,
                            status=_status_line,
                        )
                        print(f"\n{info.id}: {destination}")
                else:
                    print(f"{info.id}: downloading {info.display_download_size} ...", file=sys.stderr)
                    destination = models.download(
                        info,
                        config.models_path(),
                        force=args.force,
                        progress=_progress,
                        status=_status_line,
                    )
                    print(f"\n{info.id}: {destination}")
                if args.use:
                    config.model = info.id
                    config_module.save(config)
                    print(f"selected model: {info.id}")
            return 0
        if command == "use":
            info = models.find(args.id)
            destination = config.models_path() / info.file
            if not destination.is_file():
                print(f"{info.id} is not installed. Run: dictate models download {info.id}", file=sys.stderr)
                return 1
            config.model = info.id
            config_module.save(config)
            print(f"selected model: {info.id}")
            return 0
        if command == "remove":
            info = models.find(args.id)
            if models.remove(info, config.models_path()):
                print(f"removed {info.id}")
            else:
                print(f"{info.id} was not installed", file=sys.stderr)
                return 1
            if config.model == info.id:
                print("warning: the selected model was removed; choose another with `dictate models use`", file=sys.stderr)
            return 0
        if command == "verify":
            targets = models.catalog() if not args.id else [models.find(args.id)]
            failed = False
            for info in targets:
                destination = config.models_path() / info.file
                if not destination.is_file():
                    if args.id:
                        print(f"{info.id}: not installed", file=sys.stderr)
                        failed = True
                    continue
                try:
                    models.verify(destination, info)
                    models.verify_sources(info, config.models_path())
                    print(f"{info.id}: OK")
                except models.ModelError as exc:
                    print(f"{info.id}: {exc}", file=sys.stderr)
                    failed = True
            return 1 if failed else 0
        if command == "path":
            if args.id:
                info = models.find(args.id)
                print(config.models_path() / info.file)
            else:
                print(models.model_path(config))
            return 0
        if command == "import":
            source = args.source.expanduser()
            if not source.is_file() or source.suffix.lower() != ".bin":
                print("expected a .bin GGML model", file=sys.stderr)
                return 1
            if source.stat().st_size < 1024 * 1024:
                print("model file is unexpectedly small", file=sys.stderr)
                return 1
            destination = config.models_path() / source.name
            if destination.exists() and not args.force:
                print(f"{destination} already exists; use --force to replace", file=sys.stderr)
                return 1
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            destination.chmod(0o600)
            config.model = destination.name
            config_module.save(config)
            print(f"imported {destination} and selected it")
            return 0
    except (models.ModelError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("unknown models command", file=sys.stderr)
    return 1


def _cmd_mic(args: argparse.Namespace) -> int:
    config = _load_config(args)
    if config is None:
        return 1
    command = getattr(args, "mic_command", None) or "list"
    if command == "list":
        default = audio.default_source()
        sources = audio.list_sources()
        if not sources:
            print("No PipeWire sources found. Check `pactl list short sources`.", file=sys.stderr)
            return 1
        for source in sources:
            marker = "*" if source.name == default else " "
            configured = "+" if source.name == config.audio_source else " "
            print(
                f"{marker}{configured} {source.index:>3}  {source.name:40} "
                f"{source.state:12} {source.sample_spec}"
            )
        print("\n* default · + configured. Use: dictate mic use <name>")
        return 0
    if command == "use":
        if args.default:
            config.audio_source = ""
        elif args.source:
            config.audio_source = args.source
        else:
            print("provide a source name or --default", file=sys.stderr)
            return 1
        config_module.save(config)
        print(f"microphone: {config.audio_source or 'system default'}")
        return 0
    if command == "test":
        seconds = max(1, min(5, args.seconds))
        print(f"Recording {seconds}s from {config.audio_source or 'the default source'}...", file=sys.stderr)
        try:
            result = audio.mic_test(seconds=seconds, source=config.audio_source)
        except audio.AudioError as exc:
            print(f"microphone test failed: {exc}", file=sys.stderr)
            return 1
        try:
            peak_db = 20 * math.log10(max(result.peak, 1e-6))
            print(f"duration: {result.duration:.1f}s")
            print(f"rms:      {result.rms:.5f}")
            print(f"peak:     {result.peak:.5f} ({peak_db:.1f} dBFS)")
            if result.peak >= 0.001:
                print("signal detected")
                return 0
            print("no clear signal; check the selected source, mute and gain", file=sys.stderr)
            return 1
        finally:
            result.path.unlink(missing_ok=True)
    print("unknown mic command", file=sys.stderr)
    return 1


def _cmd_dictionary(args: argparse.Namespace) -> int:
    store = corrections.CorrectionStore(paths.corrections_path())
    command = getattr(args, "dictionary_command", None) or "list"
    if store.load_error and command != "clear":
        print(f"dictionary error: {store.load_error}", file=sys.stderr)
        return 1
    try:
        if command == "list":
            if not store.entries:
                print("No corrections. Add one with: dictate dictionary add \"heard\" \"replacement\"")
                return 0
            for entry in store.entries:
                print(f"{entry.id}  {entry.heard!r} -> {entry.replacement!r}")
            return 0
        if command == "add":
            entry = store.add(args.heard, args.replacement)
            print(entry.id)
            print("Run `dictate reload` if the daemon is running.", file=sys.stderr)
            return 0
        if command == "remove":
            if store.remove(args.id):
                print("removed")
                return 0
            print("no correction with that id", file=sys.stderr)
            return 1
        if command == "clear":
            store.clear(force=args.force)
            print("dictionary cleared")
            return 0
        if command == "apply":
            print(store.apply(" ".join(args.text)))
            return 0
    except corrections.CorrectionError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("unknown dictionary command", file=sys.stderr)
    return 1


def _cmd_config(args: argparse.Namespace) -> int:
    configured = getattr(args, "config", None)
    if configured is not None:
        os.environ["DICTATE_CONFIG"] = str(configured.expanduser())
    command = getattr(args, "config_command", None) or "show"
    if command == "path":
        print(paths.config_path())
        return 0
    config = _load_config(args)
    if config is None:
        return 1
    try:
        if command == "show":
            print(json.dumps(config.to_dict(), indent=2, sort_keys=True))
            return 0
        if command == "get":
            value = config_module.get_value(config, args.key)
            if isinstance(value, bool):
                print("true" if value else "false")
            else:
                print(value)
            return 0
        if command == "set":
            config = config_module.set_value(config, args.key, args.value)
            config_module.save(config)
            print(f"{args.key} = {args.value}")
            print("Run `dictate reload` if the daemon is running.", file=sys.stderr)
            return 0
        if command == "edit":
            path = paths.config_path()
            config_module.ensure(path)
            editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
            subprocess.run([*shlex.split(editor), str(path)], check=False)
            try:
                config_module.load(path)
                print(f"valid: {path}")
                return 0
            except config_module.ConfigError as exc:
                print(f"invalid configuration: {exc}", file=sys.stderr)
                return 1
    except config_module.ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("unknown config command", file=sys.stderr)
    return 1


def _print_assistant_status(response: dict[str, Any]) -> None:
    data = response.get("data", {})
    assistant = data.get("assistant", {})
    if not isinstance(assistant, dict):
        assistant = {}
    state = response.get("state") or assistant.get("state", "idle")
    print(f"assistant:   {state} · {response.get('message') or assistant.get('message', '')}")
    if assistant.get("heard"):
        print(f"heard:       {assistant['heard']}")
    if assistant.get("reply"):
        print(f"reply:       {assistant['reply']}")
    print(f"llm:         {assistant.get('llm_model', '?')} at {assistant.get('llm_base_url', '?')}")
    tts_line = assistant.get("tts_provider", "?")
    if assistant.get("tts_configured"):
        tts_line += " · configured"
    else:
        tts_line += " · not configured"
    print(f"tts:         {tts_line}")
    print(f"player:      {assistant.get('tts_player') or 'missing'}")
    print(f"history:     {assistant.get('history_turns', 0)} turn(s) in memory")


def _assistant_doctor(config: config_module.Config) -> int:
    checks: list[tuple[str, str, str]] = []

    client = llm.LLMClient(config)
    alive, detail = client.health()
    if alive:
        checks.append(("OK", "llm endpoint", f"{config.llm_base_url} ({detail})"))
    else:
        hint = (
            f"start with: {config.llm_start_command}"
            if config.llm_start_command
            else "set llm_start_command or start llama-server yourself"
        )
        checks.append(("WARN", "llm endpoint", f"{config.llm_base_url} unreachable: {detail}; {hint}"))

    tts_client = tts.TTSClient(config)
    if not tts_client.configured:
        hint = (
            "not configured; set tts_base_url and tts_model "
            "(for example mimo-v2.5-tts)"
            if config.tts_provider == "mimo"
            else "not configured; set tts_base_url, tts_model, and tts_voice "
            "(`dictate config set ...`)"
        )
        checks.append(("WARN", "tts", hint + " then store tts_api_key"))
    else:
        try:
            tts_client.check()
            source = secrets.source("tts_api_key", config.tts_api_key_env)
            checks.append(("OK", "tts", f"{tts_client.endpoint()} · key: {source}"))
        except tts.TTSUnavailable as exc:
            checks.append(("WARN", "tts", str(exc)))

    player = playback.Player(config)
    method = player.method()
    if method:
        checks.append(("OK", "audio player", method))
    else:
        checks.append(("FAIL", "audio player", "install mpv, pw-cat, or ffplay"))

    if shutil.which("notify-send"):
        checks.append(("OK", "notifications", shutil.which("notify-send") or ""))
    else:
        checks.append(("WARN", "notifications", "notify-send missing; replies stay in Waybar/logs"))

    waybar = shutil.which("dictate-assistant-waybar")
    if waybar is None:
        candidate = paths.repo_root() / "linux" / "waybar" / "dictate-assistant-waybar"
        if candidate.is_file():
            waybar = str(candidate)
    if waybar:
        checks.append(("OK", "waybar module", waybar))
    else:
        checks.append(("WARN", "waybar module", "run linux/install.sh to install the helper"))

    width = max(len(name) for _, name, _ in checks)
    for status, name, value in checks:
        print(f"[{status:4}] {name:<{width}}  {value}")
    failures = sum(1 for status, _, _ in checks if status == "FAIL")
    warnings = sum(1 for status, _, _ in checks if status == "WARN")
    print()
    print(f"{len(checks)} checks · {failures} failure(s) · {warnings} warning(s)")
    return 1 if failures else 0


def _cmd_assistant(args: argparse.Namespace) -> int:
    config = _load_config(args)
    if config is None:
        return 1
    command = getattr(args, "assistant_command", None) or "status"

    if command == "doctor":
        return _assistant_doctor(config)

    if command == "status":
        try:
            response = ipc.request("status", timeout=3, autostart=False)
        except ipc.IPCError as exc:
            if args.json:
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "running": False,
                            "state": "idle",
                            "message": str(exc),
                            "data": {"assistant": {"state": "idle", "message": str(exc)}},
                        },
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                print(str(exc), file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(response, indent=2, sort_keys=True))
        else:
            _print_assistant_status(response)
        return 0 if response.get("ok") else 1

    if command == "warmup":
        timeout = config.llm_start_timeout + 30
        try:
            response = ipc.request("assistant-warmup", timeout=timeout, autostart=True)
        except ipc.IPCError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(str(response.get("message", "")))
        return 0 if response.get("ok") else 1

    return _client(f"assistant-{command}", config, autostart=True)


def _cmd_secrets(args: argparse.Namespace) -> int:
    config = _load_config(args)
    if config is None:
        return 1
    command = getattr(args, "secrets_command", None) or "list"
    env_names = {
        "tts_api_key": config.tts_api_key_env,
        "llm_api_key": config.llm_api_key_env,
    }
    try:
        if command == "list":
            for name in secrets.SECRET_KEYS:
                print(f"{name:20} {secrets.source(name, env_names[name])}")
            print(f"\nfile: {paths.secrets_path()} (mode 0600)")
            return 0
        if command == "set":
            name = args.name
            if sys.stdin.isatty():
                value = getpass.getpass(f"{name}: ")
            else:
                value = sys.stdin.readline().strip()
            secrets.set_value(name, value)
            print(f"{name} stored in {paths.secrets_path()} (mode 0600)")
            print("Run `dictate reload` if the daemon is running.")
            return 0
        if command == "unset":
            secrets.unset(args.name)
            print(f"{args.name} removed")
            print("Run `dictate reload` if the daemon is running.")
            return 0
    except secrets.SecretsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("unknown secrets command", file=sys.stderr)
    return 1


def _hyprland_path() -> Path:
    return _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / "hypr" / "hyprland.conf"


def _xdg(name: str, fallback: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else fallback


def _dictate_command() -> str:
    found = shutil.which("dictate")
    if found:
        return found
    return str(Path.home() / ".local" / "bin" / "dictate")


def hyprland_block(hold: bool = False, assistant: bool = False) -> str:
    command = _dictate_command()
    lines = [
        "# >>> dictate-unlimited >>>",
        "# CPU-only PipeWire + Bark 3.0 dictation; optional voice assistant. Reload: hyprctl reload",
        f"exec-once = {command} daemon --detach",
    ]
    if hold:
        lines.extend(
            [
                f"bind = SUPER, D, exec, {command} start",
                f"bindr = SUPER, D, exec, {command} stop",
            ]
        )
    else:
        lines.append(f"bind = SUPER, D, exec, {command} toggle")
    lines.extend(
        [
            f"bind = SUPER SHIFT, V, exec, {command} paste-last",
            f"bind = SUPER, Escape, exec, {command} cancel",
        ]
    )
    if assistant:
        lines.extend(
            [
                "# Voice assistant: tap to talk, tap again to finish, or tap while it",
                "# is thinking/speaking to interrupt. No separate cancel bind is needed.",
                f"bind = SUPER, A, exec, {command} assistant toggle",
            ]
        )
    lines.append("# <<< dictate-unlimited <<<")
    return "\n".join(lines)


def _install_hyprland(hold: bool, yes: bool, assistant: bool = False) -> int:
    path = _hyprland_path()
    block = hyprland_block(hold, assistant)
    if not path.exists():
        print(f"Hyprland config not found: {path}", file=sys.stderr)
        return 1
    current = path.read_text(encoding="utf-8")
    start = "# >>> dictate-unlimited >>>"
    end = "# <<< dictate-unlimited <<<"
    if start in current and end in current:
        before, rest = current.split(start, 1)
        _, after = rest.split(end, 1)
        updated = before + block + after
    else:
        updated = current.rstrip() + "\n\n" + block + "\n"
    if not _confirm(f"Update {path} with the dictation keybinds?", yes):
        print(block)
        return 0
    backup = path.with_name(path.name + f".dictate-backup-{datetime.now():%Y%m%d-%H%M%S}")
    backup.write_text(current, encoding="utf-8")
    path.write_text(updated, encoding="utf-8")
    print(f"updated {path} (backup: {backup})")
    print("Run: hyprctl reload")
    return 0


def _confirm(question: str, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        return False
    answer = input(f"{question} [y/N] ").strip().lower()
    return answer in ("y", "yes")


def _cmd_setup(args: argparse.Namespace) -> int:
    config = _load_config(args)
    if config is None:
        return 1
    print(f"Dictate Unlimited {__version__} · CPU-only Linux setup\n")

    missing = [name for name in ("pw-cat",) if shutil.which(name) is None]
    if not shutil.which("wtype") and not shutil.which("wl-copy"):
        missing.append("wtype or wl-clipboard")
    if missing:
        print(f"Missing tools: {', '.join(missing)}")
        print("On Arch: sudo pacman -S pipewire-audio wtype wl-clipboard libnotify")
        return 1

    try:
        binary = asr.find_asr(config)
        print(f"parakeet-cli: {binary}")
    except asr.ASRError:
        binary = None
        print("parakeet-cli: not found")
        script = paths.repo_root() / "scripts" / "build-asr-linux.sh"
        if args.build_asr or _confirm(f"Build the CPU-only whisper.cpp runtime now ({script})?", args.yes):
            if not script.is_file():
                print(f"build script missing: {script}", file=sys.stderr)
                return 1
            completed = subprocess.run(["bash", str(script)], check=False)
            if completed.returncode != 0:
                return completed.returncode
            try:
                binary = asr.find_asr(config)
            except asr.ASRError:
                binary = None
        if binary is None:
            print(f"Build it later with: {script}")

    if not args.no_download:
        target = args.model or config.model
        try:
            info = models.find(target)
        except models.ModelError:
            info = None
        if info is not None:
            destination = config.models_path() / info.file
            if not destination.is_file():
                if _confirm(f"Download {info.name} ({info.display_download_size})?", args.yes):
                    print(f"Downloading {info.name} ...", file=sys.stderr)
                    try:
                        models.download(
                            info,
                            config.models_path(),
                            progress=_progress,
                            status=_status_line,
                        )
                        print()
                    except models.ModelError as exc:
                        print(str(exc), file=sys.stderr)
                        return 1
                    config.model = info.id
                    config_module.save(config)
            if destination.is_file():
                config.model = info.id
                config_module.save(config)

    print("\nAdd this to your Hyprland config, or run `dictate setup --hyprland`:\n")
    print(hyprland_block(args.hold, args.assistant))
    if args.hyprland:
        result = _install_hyprland(args.hold, args.yes, args.assistant)
        if result != 0:
            return result
    print("\nStart the daemon with one of:")
    print(f"  {_dictate_command()} daemon --detach")
    print("  exec-once in Hyprland (included above)")
    print("\nThen press Super+D to dictate, Super+Shift+V to paste the last result.")
    if args.assistant:
        print("Press Super+A to talk to the assistant; Super+Shift+A interrupts it.")
        print("Check the assistant with: dictate assistant doctor")
        print("Configure TTS with: dictate config set tts_base_url <url>, then")
        print("  dictate secrets set tts_api_key")
    print("Run `dictate doctor` at any time. No GPU is used for ASR; Bark 3.0 runs on CPU.")
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    if _load_config(args) is None:
        return 1
    checks = doctor.run()
    doctor.render(checks)
    return doctor.exit_code(checks)


def _dispatch(args: argparse.Namespace) -> int:
    command = args.command
    if command is None:
        build_parser().print_help()
        return 0
    if command == "daemon":
        return _cmd_daemon(args)
    if command == "status":
        config = _load_config(args)
        if config is None:
            return 1
        if args.watch:
            return _status_watch(config)
        try:
            response = ipc.request("status", timeout=3, autostart=False)
        except ipc.IPCError as exc:
            if args.json:
                print(json.dumps({"ok": False, "running": False, "message": str(exc)}))
            else:
                print(str(exc), file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(response, indent=2, sort_keys=True))
        else:
            print(str(response.get("message", "")))
            if response.get("ok"):
                _print_status(response)
        return 0 if response.get("ok") else 1
    if command == "transcribe":
        return _cmd_transcribe(args)
    if command == "models":
        return _cmd_models(args)
    if command == "mic":
        return _cmd_mic(args)
    if command == "dictionary":
        return _cmd_dictionary(args)
    if command == "assistant":
        return _cmd_assistant(args)
    if command == "secrets":
        return _cmd_secrets(args)
    if command == "config":
        return _cmd_config(args)
    if command == "doctor":
        return _cmd_doctor(args)
    if command == "setup":
        return _cmd_setup(args)
    config = _load_config(args)
    if config is None:
        return 1
    if command in ("start", "stop", "toggle", "cancel", "paste-last", "reload", "quit"):
        return _client(command, config, autostart=command != "quit")
    print(f"unknown command: {command}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return _dispatch(args)
