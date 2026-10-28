"""CPU-only Bark 3.0 transcription through whisper.cpp's parakeet-cli."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Sequence

from . import audio, config as config_module, models, paths


class ASRError(RuntimeError):
    pass


class Cancelled(ASRError):
    pass


_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_TIMESTAMP = re.compile(r"^\[[0-9:.]+\s*-->?\s*[0-9:.]+\]\s*")
_TIMESTAMP_PREFIX = re.compile(r"^\[[0-9:.]+\]\s*")
_SPECIAL_TOKEN = re.compile(r"<\|[^|<>]*\|>")
_NON_SPEECH = re.compile(
    r"^[\[(](?:blank_audio|blank|music|applause|no speech|silence|inaudible)[^\])]*[\])]$",
    re.IGNORECASE,
)


def find_asr(config: config_module.Config) -> Path:
    if config.asr_bin:
        candidate = Path(config.asr_bin).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
        raise ASRError(f"configured asr_bin is not executable: {candidate}")
    for candidate in paths.asr_candidates():
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which("parakeet-cli")
    if found:
        return Path(found)
    raise ASRError(
        "parakeet-cli was not found. Run ./scripts/build-asr-linux.sh to build the "
        "CPU-only whisper.cpp runtime."
    )


class Capabilities:
    def __init__(self, binary: Path):
        self.binary = binary
        self.version = ""
        self.help = ""
        try:
            help_result = subprocess.run(
                [str(binary), "--help"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.help = help_result.stdout + help_result.stderr
        except (OSError, subprocess.TimeoutExpired):
            pass
        if self.has("--version"):
            try:
                version = subprocess.run(
                    [str(binary), "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                self.version = (version.stdout or version.stderr).strip()
            except (OSError, subprocess.TimeoutExpired):
                pass

    def has(self, flag: str) -> bool:
        # Help lines look like "  -ng,       --no-gpu"; match the option token
        # even when a comma is attached.
        return re.search(rf"(?<![\w-]){re.escape(flag)}(?=[\s,]|$)", self.help) is not None

    @property
    def no_gpu(self) -> bool:
        return self.has("-ng")


def _cpu_environment(binary: Path, threads: int) -> dict[str, str]:
    env = os.environ.copy()
    library_path = str(binary.parent)
    existing = env.get("LD_LIBRARY_PATH")
    env["LD_LIBRARY_PATH"] = library_path + (":" + existing if existing else "")
    # Defence in depth: -ng is always used, and these make a CUDA/HIP build
    # decline any visible device even if someone points asr_bin at it.
    env["CUDA_VISIBLE_DEVICES"] = ""
    env["HIP_VISIBLE_DEVICES"] = ""
    env["ROCR_VISIBLE_DEVICES"] = ""
    env["GGML_CUDA"] = "0"
    env["OMP_NUM_THREADS"] = str(threads)
    return env


def parse_transcript(stdout: str) -> str:
    text = _ANSI.sub("", stdout)
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("parakeet_", "whisper_", "ggml_")):
            continue
        line = _TIMESTAMP.sub("", line)
        line = _TIMESTAMP_PREFIX.sub("", line)
        line = _SPECIAL_TOKEN.sub("", line)
        line = line.strip()
        if not line:
            continue
        if _NON_SPEECH.match(line):
            continue
        lines.append(line)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def is_likely_silent(path: Path, threshold: float) -> bool:
    if path.suffix.lower() != ".wav":
        return False
    try:
        _, rms, _ = audio.wav_stats(path)
    except audio.AudioError:
        return False
    return rms < threshold


def transcribe(
    path: Path,
    config: config_module.Config,
    cancel_event: threading.Event | None = None,
    timeout: float | None = None,
) -> str:
    binary = find_asr(config).expanduser().resolve()
    _, model = models.require_model(config)
    model = model.expanduser().resolve()
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ASRError(f"audio file not found: {path}")
    if is_likely_silent(path, config.silence_rms):
        return ""

    capabilities = Capabilities(binary)
    if not capabilities.no_gpu:
        raise ASRError(
            f"{binary} does not support -ng/--no-gpu. Refusing to run because the GPU "
            "must not be used. Build whisper.cpp with scripts/build-asr-linux.sh."
        )
    threads = config_module.effective_threads(config)
    command: list[str] = [
        str(binary),
        "-m",
        str(model),
        "-f",
        str(path),
        "-t",
        str(threads),
        "-ng",
    ]

    env = _cpu_environment(binary, threads)
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            env=env,
            cwd=str(binary.parent),
        )
    except OSError as exc:
        raise ASRError(f"cannot start parakeet-cli: {exc}") from exc

    deadline = time.monotonic() + (timeout or config.transcribe_timeout)
    try:
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
                raise Cancelled("transcription cancelled")
            if time.monotonic() > deadline:
                process.kill()
                process.wait(timeout=2)
                raise ASRError("transcription timed out")
            time.sleep(0.1)
        stdout, stderr = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)

    text = parse_transcript(stdout)
    if process.returncode != 0:
        detail = (stderr or stdout).strip().splitlines()
        tail = " | ".join(detail[-4:]) if detail else f"exit status {process.returncode}"
        raise ASRError(f"parakeet-cli failed: {tail}")
    if not text and "error:" in stderr.lower():
        detail = [line for line in stderr.splitlines() if "error:" in line.lower()]
        tail = " | ".join(detail[-4:]) if detail else stderr.strip().splitlines()[-1]
        raise ASRError(f"parakeet-cli failed: {tail}")
    return text


def transcribe_files(
    files: Sequence[Path],
    config: config_module.Config,
    apply_corrections=None,
) -> list[str]:
    results: list[str] = []
    for path in files:
        text = transcribe(path, config)
        if apply_corrections is not None:
            text = apply_corrections(text)
        results.append(text)
    return results


def check_binary(binary: Path | None = None) -> tuple[bool, str]:
    try:
        binary = binary or find_asr(config_module.Config())
    except ASRError as exc:
        return False, str(exc)
    capabilities = Capabilities(binary)
    if not capabilities.help:
        return False, f"{binary} did not answer --help"
    if not capabilities.no_gpu:
        return False, f"{binary} has no -ng/--no-gpu flag; refusing to risk GPU use"
    return True, f"{binary} ({capabilities.version or 'unknown version'}, CPU-only flags present)"
