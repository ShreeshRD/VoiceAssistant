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
TTS_PROVIDERS = ("openai", "mimo", "none")
TTS_FORMATS = ("wav", "mp3", "opus", "flac", "pcm", "pcm16")
TTS_PLAYERS = ("auto", "mpv", "pw-cat", "ffplay", "none")

DEFAULT_SYSTEM_PROMPT = (
    "You are a friendly voice assistant running locally on the user's Arch Linux "
    "laptop. The user speaks into a microphone; your reply is spoken aloud and "
    "briefly shown as a desktop notification. Treat this as a natural spoken "
    "conversation. Keep every reply to one or two short sentences, ideally under "
    "35 words. Never use markdown, code blocks, bullet points, numbered lists, "
    "tables, emojis, or URLs unless the user explicitly asks for one. Write exactly "
    "as you would speak out loud, with plain punctuation. If you do not know "
    "something, say so briefly instead of guessing. Do not mention these "
    "instructions or that you are an AI."
)

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
    trailing_space: bool = True

    # Runtime
    notifications: bool = True
    auto_start_daemon: bool = True
    keep_audio: bool = False
    log_level: str = "INFO"

    # Voice assistant: capture and history
    assistant_max_seconds: int = 120
    assistant_history_turns: int = 6
    assistant_notify_chars: int = 180

    # Voice assistant: OpenAI-compatible chat endpoint (llama.cpp server)
    llm_base_url: str = "http://127.0.0.1:8080/v1"
    llm_model: str = "bonsai"
    llm_api_key_env: str = "DICTATE_LLM_API_KEY"
    llm_system_prompt: str = DEFAULT_SYSTEM_PROMPT
    llm_temperature: float = 0.5
    llm_max_tokens: int = 320
    llm_timeout: int = 120
    llm_start_command: str = ""
    llm_start_cwd: str = ""
    llm_start_timeout: int = 90

    # Voice assistant: OpenAI-compatible text-to-speech endpoint
    tts_provider: str = "openai"
    tts_base_url: str = ""
    tts_model: str = ""
    tts_voice: str = ""
    tts_format: str = "wav"
    tts_speed: float = 1.0
    tts_api_key_env: str = "DICTATE_TTS_API_KEY"
    tts_timeout: int = 60
    tts_workers: int = 2
    tts_prefetch: int = 3
    tts_max_chars: int = 240
    tts_player: str = "auto"
    tts_volume: float = 1.0
    tts_extra_body: str = "{}"

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
        if not isinstance(self.trailing_space, bool):
            raise ConfigError("trailing_space must be true or false")
        if self.log_level.upper() not in LOG_LEVELS:
            raise ConfigError(f"log_level must be one of {', '.join(LOG_LEVELS)}")
        self.log_level = self.log_level.upper()

        if not 5 <= self.assistant_max_seconds <= 600:
            raise ConfigError("assistant_max_seconds must be between 5 and 600")
        if not 0 <= self.assistant_history_turns <= 50:
            raise ConfigError("assistant_history_turns must be between 0 and 50")
        if not 40 <= self.assistant_notify_chars <= 1000:
            raise ConfigError("assistant_notify_chars must be between 40 and 1000")

        if not self.llm_base_url.startswith(("http://", "https://")):
            raise ConfigError("llm_base_url must start with http:// or https://")
        if not self.llm_model.strip():
            raise ConfigError("llm_model must not be empty")
        if not self.llm_system_prompt.strip():
            raise ConfigError("llm_system_prompt must not be empty")
        if not 0.0 <= self.llm_temperature <= 2.0:
            raise ConfigError("llm_temperature must be between 0 and 2")
        if not 16 <= self.llm_max_tokens <= 4096:
            raise ConfigError("llm_max_tokens must be between 16 and 4096")
        if not 5 <= self.llm_timeout <= 600:
            raise ConfigError("llm_timeout must be between 5 and 600")
        if not 5 <= self.llm_start_timeout <= 600:
            raise ConfigError("llm_start_timeout must be between 5 and 600")

        if self.tts_provider not in TTS_PROVIDERS:
            raise ConfigError(f"tts_provider must be one of {', '.join(TTS_PROVIDERS)}")
        if self.tts_base_url and not self.tts_base_url.startswith(("http://", "https://")):
            raise ConfigError("tts_base_url must start with http:// or https://")
        if self.tts_format not in TTS_FORMATS:
            raise ConfigError(f"tts_format must be one of {', '.join(TTS_FORMATS)}")
        if self.tts_provider == "mimo" and self.tts_format not in ("wav", "mp3", "pcm", "pcm16"):
            raise ConfigError("mimo TTS supports tts_format wav, mp3, pcm, or pcm16")
        if not 0.25 <= self.tts_speed <= 4.0:
            raise ConfigError("tts_speed must be between 0.25 and 4.0")
        if not 5 <= self.tts_timeout <= 600:
            raise ConfigError("tts_timeout must be between 5 and 600")
        if not 1 <= self.tts_workers <= 8:
            raise ConfigError("tts_workers must be between 1 and 8")
        if not 1 <= self.tts_prefetch <= 16:
            raise ConfigError("tts_prefetch must be between 1 and 16")
        if not 40 <= self.tts_max_chars <= 2000:
            raise ConfigError("tts_max_chars must be between 40 and 2000")
        if self.tts_player not in TTS_PLAYERS:
            raise ConfigError(f"tts_player must be one of {', '.join(TTS_PLAYERS)}")
        if not 0.0 <= self.tts_volume <= 1.5:
            raise ConfigError("tts_volume must be between 0 and 1.5")
        try:
            extra = json.loads(self.tts_extra_body or "{}")
        except json.JSONDecodeError as exc:
            raise ConfigError(f"tts_extra_body must be valid JSON: {exc}") from exc
        if not isinstance(extra, dict):
            raise ConfigError("tts_extra_body must be a JSON object")

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
