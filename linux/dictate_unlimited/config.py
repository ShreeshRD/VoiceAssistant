"""Configuration stored as JSON under the XDG config directory."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from . import paths

INSERTION_MODES = ("auto", "wtype", "clipboard", "copy", "none")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

# Whisper-era catalog ids and files. The Linux port is Bark-only now, so old
# configs fall back to the default model instead of failing to start.
LEGACY_MODELS = frozenset(
    {
        "tiny",
        "tiny.en",
        "base",
        "base.en",
        "small",
        "small.en",
        "medium",
        "medium.en",
        "large-v1",
        "large-v2",
        "large-v3",
        "large-v3-turbo",
        "turbo",
    }
)


def _is_legacy_model(model: str) -> bool:
    name = Path(model).name
    if name.startswith("ggml-") and name.endswith(".bin"):
        name = name[len("ggml-") : -len(".bin")]
    return name in LEGACY_MODELS


class ConfigError(ValueError):
    pass


@dataclass
class Config:
    # Recognition
    model: str = "bark-3.0"
    threads: int = 4
    max_seconds: int = 300
    transcribe_timeout: int = 900
    silence_rms: float = 0.0015
    asr_bin: str = ""
    models_dir: str = ""

    # Audio
    audio_source: str = ""

    # Delivery
    insertion: str = "auto"
    restore_clipboard: bool = True

    # Runtime
    notifications: bool = True
    auto_start_daemon: bool = True
    keep_audio: bool = False
    log_level: str = "INFO"

    def validate(self) -> None:
        if not self.model or "/" in self.model or self.model.startswith("."):
            raise ConfigError("model must be a catalog id or a plain file name")
        if not 1 <= self.threads <= 64:
            raise ConfigError("threads must be between 1 and 64")
        if not 5 <= self.max_seconds <= 600:
            raise ConfigError("max_seconds must be between 5 and 600")
        if not 30 <= self.transcribe_timeout <= 3600:
            raise ConfigError("transcribe_timeout must be between 30 and 3600")
        if not 0 <= self.silence_rms <= 1:
            raise ConfigError("silence_rms must be between 0 and 1")
        if self.insertion not in INSERTION_MODES:
            raise ConfigError(f"insertion must be one of {', '.join(INSERTION_MODES)}")
        if self.log_level.upper() not in LOG_LEVELS:
            raise ConfigError(f"log_level must be one of {', '.join(LOG_LEVELS)}")
        self.log_level = self.log_level.upper()

    def models_path(self) -> Path:
        if self.models_dir:
            return Path(self.models_dir).expanduser()
        return paths.models_dir()

    def config_file(self) -> Path:
        return paths.config_path()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_FIELD_TYPES = {f.name: f.type for f in fields(Config)}


def load(path: Path | None = None) -> Config:
    path = path or paths.config_path()
    defaults = Config()
    if not path.exists():
        defaults.validate()
        return defaults
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a JSON object")
    values = asdict(defaults)
    for key, value in raw.items():
        if key in values:
            values[key] = value
    config = Config(**values)
    if _is_legacy_model(config.model):
        config.model = defaults.model
    config.validate()
    return config


def save(config: Config, path: Path | None = None) -> Path:
    config.validate()
    path = path or paths.config_path()
    paths.ensure_private_dir(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(config.to_dict(), handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
        path.chmod(0o600)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return path


def ensure(path: Path | None = None) -> Config:
    path = path or paths.config_path()
    config = load(path)
    if not path.exists():
        save(config, path)
    return config


def _parse_like(key: str, current: Any, raw: str) -> Any:
    if isinstance(current, bool):
        lowered = raw.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
        raise ConfigError(f"{key} expects true or false")
    if isinstance(current, int):
        try:
            return int(raw, 10)
        except ValueError as exc:
            raise ConfigError(f"{key} expects an integer") from exc
    if isinstance(current, float):
        try:
            return float(raw)
        except ValueError as exc:
            raise ConfigError(f"{key} expects a number") from exc
    return raw


def set_value(config: Config, key: str, raw: str) -> Config:
    if key not in _FIELD_TYPES:
        raise ConfigError(f"unknown setting: {key}")
    values = config.to_dict()
    values[key] = _parse_like(key, values[key], raw)
    updated = Config(**values)
    updated.validate()
    return updated


def get_value(config: Config, key: str) -> Any:
    if key not in _FIELD_TYPES:
        raise ConfigError(f"unknown setting: {key}")
    return getattr(config, key)


def effective_threads(config: Config) -> int:
    return max(1, min(64, config.threads))
