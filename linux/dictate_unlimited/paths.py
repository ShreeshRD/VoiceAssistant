"""XDG paths and tool locations for the Linux port."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "dictate-unlimited"


def _xdg(name: str, fallback: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else fallback


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / APP_NAME


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", Path.home() / ".local" / "share") / APP_NAME


def state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", Path.home() / ".local" / "state") / APP_NAME


def runtime_dir() -> Path:
    value = os.environ.get("XDG_RUNTIME_DIR")
    if value:
        return Path(value)
    return Path("/tmp") / f"{APP_NAME}-{os.getuid()}"


def config_path() -> Path:
    override = os.environ.get("DICTATE_CONFIG")
    return Path(override).expanduser() if override else config_dir() / "config.json"


def corrections_path() -> Path:
    return config_dir() / "corrections.json"


def secrets_path() -> Path:
    return config_dir() / "secrets.json"


def assistant_log_path() -> Path:
    return state_dir() / "assistant.log"


def llm_log_path() -> Path:
    return state_dir() / "llm-server.log"


def models_dir() -> Path:
    return data_dir() / "models"


def socket_path() -> Path:
    return runtime_dir() / f"{APP_NAME}.sock"


def pid_path() -> Path:
    return runtime_dir() / f"{APP_NAME}.pid"


def log_path() -> Path:
    return state_dir() / f"{APP_NAME}.log"


def audio_temp_dir() -> Path:
    return state_dir() / "audio"


def repo_root() -> Path:
    """Best-effort repository root for a source checkout."""
    return Path(__file__).resolve().parents[2]


def source_launcher() -> Path:
    return repo_root() / "linux" / "dictate"


def asr_candidates() -> list[Path]:
    return [
        repo_root() / "linux" / ".dependencies" / "whisper.cpp" / "build" / "bin" / "parakeet-cli",
        repo_root() / ".dependencies" / "whisper.cpp" / "build" / "bin" / "parakeet-cli",
        Path.home() / ".local" / "bin" / "parakeet-cli",
    ]


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path
