"""Audio playback for synthesized speech."""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import config as config_module

LOG = logging.getLogger(__name__)


class PlaybackError(RuntimeError):
    pass


def _available(method: str) -> bool:
    return shutil.which(method) is not None


class Player:
    """Play one audio file at a time, with cancellation from another thread."""

    def __init__(self, config: config_module.Config):
        self.config = config
        self._lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None

    def method(self) -> str | None:
        wanted = self.config.tts_player
        if wanted == "none":
            return None
        candidates = [wanted] if wanted != "auto" else ["mpv", "pw-cat", "ffplay"]
        for candidate in candidates:
            if _available(candidate):
                return candidate
        return None

    def available(self) -> bool:
        return self.method() is not None

    def _command(self, method: str, path: Path) -> list[str]:
        volume = max(0, min(150, round(self.config.tts_volume * 100)))
        if method == "mpv":
            return [
                "mpv",
                "--no-config",
                "--no-video",
                "--force-window=no",
                "--audio-display=no",
                "--really-quiet",
                "--no-terminal",
                f"--volume={volume}",
                str(path),
            ]
        if method == "pw-cat":
            return ["pw-cat", "--playback", str(path)]
        if method == "ffplay":
            return [
                "ffplay",
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "quiet",
                "-volume",
                str(volume),
                str(path),
            ]
        raise PlaybackError(f"unknown player: {method}")

    def play(self, path: Path, cancel_event: threading.Event | None = None) -> bool:
        method = self.method()
        if method is None:
            raise PlaybackError(
                "No audio player found. Install mpv (recommended), PipeWire's pw-cat, "
                "or ffmpeg/ffplay."
            )
        if not path.is_file():
            raise PlaybackError(f"audio file disappeared: {path}")

        try:
            process = subprocess.Popen(
                self._command(method, path),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            raise PlaybackError(f"cannot start {method}: {exc}") from exc

        with self._lock:
            self._process = process
        try:
            while process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    self._terminate(process)
                    return False
                time.sleep(0.05)
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None
        return process.returncode in (0, None)

    def stop(self) -> None:
        with self._lock:
            process = self._process
        if process is not None:
            self._terminate(process)

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=1.5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
                process.wait(timeout=1.5)
            except (OSError, subprocess.TimeoutExpired):
                pass
