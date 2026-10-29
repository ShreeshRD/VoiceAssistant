"""Environment diagnostics for the Linux port."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import (
    __version__,
    asr,
    audio,
    config as config_module,
    corrections,
    ipc,
    llm,
    models,
    paths,
    playback,
    secrets,
    tts,
)

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"


@dataclass
class Check:
    status: str
    name: str
    detail: str


def _check_python() -> Check:
    version = sys.version_info
    if version >= (3, 11):
        return Check(OK, "Python", f"{version.major}.{version.minor}.{version.micro}")
    return Check(FAIL, "Python", "Python 3.11 or newer is required")


def _check_pipewire() -> list[Check]:
    checks: list[Check] = []
    checks.append(
        Check(OK, "pw-cat", shutil.which("pw-cat") or "")
        if shutil.which("pw-cat")
        else Check(FAIL, "pw-cat", "missing; install PipeWire (pipewire-audio)")
    )
    checks.append(
        Check(OK, "pactl", shutil.which("pactl") or "")
        if shutil.which("pactl")
        else Check(WARN, "pactl", "missing; source listing is unavailable")
    )
    sources = audio.list_sources()
    if sources:
        default = audio.default_source()
        checks.append(Check(OK, "Audio sources", f"{len(sources)} found; default: {default or 'unknown'}"))
    else:
        checks.append(Check(WARN, "Audio sources", "no sources listed; check PipeWire/WirePlumber"))
    return checks


def _check_wayland(config: config_module.Config) -> list[Check]:
    display = os.environ.get("WAYLAND_DISPLAY", "")
    checks = [
        Check(OK, "Wayland display", display) if display else Check(WARN, "Wayland display", "WAYLAND_DISPLAY is not set")
    ]
    wtype = shutil.which("wtype")
    wlcopy = shutil.which("wl-copy")
    wlpaste = shutil.which("wl-paste")
    if wtype:
        checks.append(Check(OK, "wtype", wtype))
    else:
        checks.append(Check(WARN, "wtype", "missing; direct typing is unavailable"))
    if wlcopy and wlpaste:
        checks.append(Check(OK, "wl-clipboard", wlcopy))
    else:
        checks.append(Check(WARN, "wl-clipboard", "missing; clipboard fallback is unavailable"))
    if config.insertion != "none" and not wtype and not wlcopy:
        checks.append(Check(FAIL, "Text delivery", "install wtype and/or wl-clipboard"))
    if shutil.which("notify-send"):
        checks.append(Check(OK, "notifications", shutil.which("notify-send") or ""))
    else:
        checks.append(Check(WARN, "notifications", "notify-send missing; feedback goes to the log"))
    return checks


def _check_asr(config: config_module.Config) -> list[Check]:
    checks: list[Check] = []
    binary: Path | None = None
    try:
        binary = asr.find_asr(config)
        checks.append(Check(OK, "parakeet-cli", str(binary)))
    except asr.ASRError as exc:
        checks.append(Check(FAIL, "parakeet-cli", str(exc)))
        return checks
    capabilities = asr.Capabilities(binary)
    if capabilities.no_gpu:
        checks.append(Check(OK, "CPU-only flag", "-ng is available and always passed"))
    else:
        checks.append(Check(FAIL, "CPU-only flag", "parakeet-cli lacks -ng; refusing to risk GPU use"))
    try:
        linked_raw = subprocess.run(
            ["ldd", str(binary)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout
        linked = linked_raw.lower()
        gpu_libs = [
            name
            for name in ("libcuda", "libvulkan", "libhip", "librocm", "libopencl")
            if name in linked
        ]
        if gpu_libs:
            checks.append(
                Check(WARN, "GPU libraries", f"linked: {', '.join(gpu_libs)}; -ng and empty device env are still enforced")
            )
        else:
            checks.append(Check(OK, "GPU libraries", "none linked"))
        version = capabilities.version.splitlines()[0] if capabilities.version else ""
        if not version:
            match = re.search(r"libparakeet\.so\.1\s*=>\s*(\S+)", linked_raw)
            if match:
                resolved = Path(match.group(1)).resolve().name
                version_match = re.search(r"libparakeet\.so\.([0-9][0-9.]*)", resolved)
                if version_match:
                    version = f"whisper.cpp runtime {version_match.group(1)}"
        if version:
            checks.append(Check(OK, "parakeet version", version))
    except (OSError, subprocess.TimeoutExpired):
        checks.append(Check(WARN, "GPU libraries", "could not run ldd"))
    return checks


def _check_model(config: config_module.Config) -> list[Check]:
    checks: list[Check] = []
    try:
        info, path = models.require_model(config)
        checks.append(Check(OK, "model", f"{config.model} → {path}"))
        if info is not None:
            language = "English-only" if not info.multilingual else "multilingual"
            checks.append(Check(OK, "model language", language))
    except models.ModelError as exc:
        checks.append(Check(FAIL, "model", str(exc)))
    return checks


def _check_daemon() -> Check:
    try:
        response = ipc.request("status", timeout=2, autostart=False)
    except ipc.IPCError:
        return Check(WARN, "daemon", "not running; start with: dictate daemon --detach")
    data = response.get("data", {})
    if response.get("ok"):
        return Check(OK, "daemon", f"{response.get('state')} · {data.get('model')} · pid {data.get('pid')}")
    return Check(WARN, "daemon", response.get("message", "unknown response"))


def _check_assistant(config: config_module.Config) -> list[Check]:
    checks: list[Check] = []
    client = llm.LLMClient(config)
    alive, detail = client.health()
    if alive:
        checks.append(
            Check(OK, "assistant LLM", f"{config.llm_base_url} ({detail}) · {config.llm_model}")
        )
    else:
        hint = (
            f"start command configured ({config.llm_start_command})"
            if config.llm_start_command
            else "set llm_start_command or start the server yourself"
        )
        checks.append(
            Check(WARN, "assistant LLM", f"{config.llm_base_url} unreachable; {hint}")
        )

    tts_client = tts.TTSClient(config)
    if not tts_client.configured:
        hint = (
            "not configured; set tts_base_url and tts_model "
            "(for example mimo-v2.5-tts), then store tts_api_key"
            if config.tts_provider == "mimo"
            else "not configured; set tts_base_url, tts_model, tts_voice, then store tts_api_key"
        )
        checks.append(Check(WARN, "assistant TTS", hint))
    else:
        try:
            tts_client.check()
            source = secrets.source("tts_api_key", config.tts_api_key_env)
            checks.append(
                Check(OK, "assistant TTS", f"{tts_client.endpoint()} · key: {source}")
            )
        except tts.TTSUnavailable as exc:
            checks.append(Check(WARN, "assistant TTS", str(exc)))

    method = playback.Player(config).method()
    if method:
        checks.append(Check(OK, "assistant player", method))
    else:
        checks.append(
            Check(FAIL, "assistant player", "install mpv (recommended), pw-cat, or ffplay")
        )
    return checks


def _check_corrections() -> Check:
    store = corrections.CorrectionStore(paths.corrections_path())
    if store.load_error:
        return Check(FAIL, "dictionary", store.load_error)
    return Check(OK, "dictionary", f"{len(store.entries)} entries · {store.path}")


def run() -> list[Check]:
    config = config_module.ensure()
    checks: list[Check] = [
        Check(OK, "version", __version__),
        _check_python(),
        Check(OK, "config", str(config.config_file())),
        Check(OK, "corrections", str(paths.corrections_path())),
        Check(OK, "models dir", str(config.models_path())),
        Check(OK, "CPU", f"{os.cpu_count() or 1} logical CPUs; Bark threads={config_module.effective_threads(config)}"),
        _check_corrections(),
        _check_daemon(),
    ]
    checks.extend(_check_pipewire())
    checks.extend(_check_wayland(config))
    checks.extend(_check_asr(config))
    checks.extend(_check_model(config))
    checks.extend(_check_assistant(config))
    return checks


def render(checks: list[Check]) -> None:
    width = max(len(check.name) for check in checks) if checks else 10
    for check in checks:
        print(f"[{check.status:4}] {check.name:<{width}}  {check.detail}")
    failures = sum(1 for check in checks if check.status == FAIL)
    warnings = sum(1 for check in checks if check.status == WARN)
    print()
    print(f"{len(checks)} checks · {failures} failure(s) · {warnings} warning(s)")
    print("Bark 3.0 is always launched with -ng and empty CUDA/HIP/ROCR device variables.")


def exit_code(checks: list[Check]) -> int:
    return 1 if any(check.status == FAIL for check in checks) else 0
