"""PipeWire microphone capture, level metering and WAV helpers."""

from __future__ import annotations

import array
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from . import paths

SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
CHANNELS = 1
MAX_SECONDS = 300
CHUNK_BYTES = SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS // 10  # 100 ms


class AudioError(RuntimeError):
    pass


@dataclass
class CaptureResult:
    path: Path
    duration: float
    rms: float
    peak: float


@dataclass
class Source:
    index: str
    name: str
    driver: str
    sample_spec: str
    state: str


def have_pipewire() -> bool:
    return shutil.which("pw-cat") is not None


def list_sources() -> list[Source]:
    if shutil.which("pactl") is None:
        return []
    try:
        completed = subprocess.run(
            ["pactl", "list", "short", "sources"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    rows: list[Source] = []
    for line in completed.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) >= 5:
            rows.append(Source(fields[0], fields[1], fields[2], fields[3], fields[4]))
    return rows


def default_source() -> str | None:
    if shutil.which("pactl") is None:
        return None
    try:
        completed = subprocess.run(
            ["pactl", "get-default-source"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = completed.stdout.strip()
    return value or None


def _pcm_rms(data: bytes) -> tuple[float, float]:
    usable = len(data) - (len(data) % SAMPLE_WIDTH)
    if usable <= 0:
        return 0.0, 0.0
    samples = array.array("h")
    samples.frombytes(data[:usable])
    if sys.byteorder == "big":
        samples.byteswap()
    if not samples:
        return 0.0, 0.0
    total = 0
    peak = 0
    for sample in samples:
        value = abs(sample)
        if value > peak:
            peak = value
        total += sample * sample
    return math.sqrt(total / len(samples)) / 32768.0, peak / 32768.0


class Capture:
    """Spawns pw-cat and reads 16 kHz mono s16le PCM from stdout."""

    def __init__(self, source: str = "", max_seconds: int = MAX_SECONDS):
        self.source = source
        self.max_seconds = max(1, min(MAX_SECONDS, int(max_seconds)))
        self._process: subprocess.Popen[bytes] | None = None
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._lock = threading.Lock()
        self._pcm = bytearray()
        self._level = 0.0
        self._peak = 0.0
        self._last_data = time.monotonic()
        self._started = time.monotonic()
        self._error: str | None = None
        self._stderr: deque[str] = deque(maxlen=20)
        self._stopping = False

    def start(self) -> None:
        if not have_pipewire():
            raise AudioError("pw-cat was not found. Install PipeWire (pipewire-audio) and retry.")
        command = [
            "pw-cat",
            "--record",
            "--raw",
            "--format",
            "s16",
            "--rate",
            str(SAMPLE_RATE),
            "--channels",
            str(CHANNELS),
            "--latency",
            "20ms",
        ]
        if self.source:
            command.extend(["--target", self.source])
        command.append("-")
        try:
            self._process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                bufsize=0,
            )
        except OSError as exc:
            raise AudioError(f"cannot start PipeWire capture: {exc}") from exc

        self._started = time.monotonic()
        self._last_data = self._started
        self._reader = threading.Thread(target=self._read_stdout, name="dictate-audio", daemon=True)
        self._reader.start()
        self._stderr_reader = threading.Thread(
            target=self._read_stderr, name="dictate-audio-errors", daemon=True
        )
        self._stderr_reader.start()

        # pw-cat reports connection failures almost immediately. Give it a
        # short window so a hotkey can show an actionable error rather than
        # pretending to record.
        time.sleep(0.25)
        if self._process.poll() is not None:
            message = self._stderr_text()
            raise AudioError(message or "PipeWire capture exited immediately.")

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            while True:
                data = process.stdout.read(CHUNK_BYTES)
                if not data:
                    break
                rms, peak = _pcm_rms(data)
                with self._lock:
                    maximum = self.max_seconds * SAMPLE_RATE * SAMPLE_WIDTH
                    remaining = maximum - len(self._pcm)
                    if remaining > 0:
                        self._pcm.extend(data[:remaining])
                    self._last_data = time.monotonic()
                    self._level = 0.25 * rms + 0.75 * self._level
                    if peak > self._peak:
                        self._peak = peak
        except (OSError, ValueError) as exc:
            with self._lock:
                self._error = f"microphone read failed: {exc}"

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        try:
            for raw in iter(process.stderr.readline, b""):
                line = raw.decode("utf-8", "replace").strip()
                if line:
                    self._stderr.append(line)
        except (OSError, ValueError):
            pass

    def _stderr_text(self) -> str:
        with self._lock:
            return " | ".join(self._stderr)

    def snapshot(self) -> tuple[float, float]:
        with self._lock:
            seconds = len(self._pcm) / SAMPLE_WIDTH / SAMPLE_RATE
            return seconds, self._level

    def peak(self) -> float:
        with self._lock:
            return self._peak

    def stalled(self, timeout: float = 4.0) -> bool:
        with self._lock:
            return time.monotonic() - self._last_data >= timeout

    def process_gone(self) -> bool:
        return self._process is not None and self._process.poll() is not None and not self._stopping

    def stop(self) -> CaptureResult:
        if self._process is None:
            raise AudioError("microphone is not running")
        self._stopping = True
        process = self._process
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        if self._reader is not None:
            self._reader.join(timeout=2)
        if self._stderr_reader is not None:
            self._stderr_reader.join(timeout=1)
        with self._lock:
            pcm = bytes(self._pcm)
            error = self._error
            peak = self._peak
            self._pcm.clear()
        if error:
            raise AudioError(error)
        if not pcm:
            details = self._stderr_text()
            raise AudioError(details or "no microphone audio was received")
        rms, measured_peak = _pcm_rms(pcm)
        peak = max(peak, measured_peak)
        path = self._write_wav(pcm)
        duration = len(pcm) / SAMPLE_WIDTH / SAMPLE_RATE
        return CaptureResult(path, duration, rms, peak)

    def cancel(self) -> None:
        self._stopping = True
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        if self._reader is not None:
            self._reader.join(timeout=1)
        if self._stderr_reader is not None:
            self._stderr_reader.join(timeout=1)
        with self._lock:
            self._pcm.clear()
            self._error = None

    def _write_wav(self, pcm: bytes) -> Path:
        directory = paths.ensure_private_dir(paths.audio_temp_dir())
        fd, name = tempfile.mkstemp(prefix="dictate-", suffix=".wav", dir=directory)
        os.close(fd)
        path = Path(name)
        try:
            with wave.open(str(path), "wb") as handle:
                handle.setnchannels(CHANNELS)
                handle.setsampwidth(SAMPLE_WIDTH)
                handle.setframerate(SAMPLE_RATE)
                handle.writeframes(pcm)
            path.chmod(0o600)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return path


def wav_stats(path: Path) -> tuple[float, float, float]:
    """Return duration, RMS and peak for a 16-bit PCM WAV file."""
    try:
        with wave.open(str(path), "rb") as handle:
            if handle.getsampwidth() != SAMPLE_WIDTH:
                raise AudioError("expected 16-bit PCM audio")
            frames = handle.readframes(handle.getnframes())
            rate = handle.getframerate()
            channels = handle.getnchannels()
    except (OSError, wave.Error) as exc:
        raise AudioError(f"cannot read audio {path}: {exc}") from exc
    if channels != CHANNELS:
        raise AudioError("expected mono audio")
    if rate != SAMPLE_RATE:
        raise AudioError("expected 16 kHz audio")
    rms, peak = _pcm_rms(frames)
    duration = len(frames) / SAMPLE_WIDTH / rate
    return duration, rms, peak


def mic_test(seconds: int = 5, source: str = "") -> CaptureResult:
    capture = Capture(source=source, max_seconds=max(1, min(5, seconds)))
    capture.start()
    try:
        deadline = time.monotonic() + max(1, min(5, seconds))
        while time.monotonic() < deadline:
            time.sleep(0.1)
            if capture.process_gone():
                break
        return capture.stop()
    except BaseException:
        capture.cancel()
        raise
