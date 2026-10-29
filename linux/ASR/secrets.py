"""Private API-key storage for the voice assistant.

Keys are intentionally kept out of ``config.json``.  Resolution order is:

1. the environment variable named by the relevant ``*_api_key_env`` setting,
2. an entry in ``$XDG_CONFIG_HOME/speech-flow/secrets.json``.

The secrets file is written atomically with mode ``0600`` and is never printed
by the CLI.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from . import paths

SECRET_KEYS = ("tts_api_key", "llm_api_key")
ALIASES = {
    "tts_api_key": ("DICTATE_TTS_API_KEY", "MIMO_API_KEY"),
    "llm_api_key": ("DICTATE_LLM_API_KEY",),
}


class SecretsError(RuntimeError):
    pass


def load() -> dict[str, str]:
    path = paths.secrets_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SecretsError(f"cannot read {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SecretsError(f"{path} must contain a JSON object")
    return {str(key): str(value) for key, value in raw.items() if isinstance(value, str)}


def save(values: dict[str, str]) -> Path:
    path = paths.secrets_path()
    paths.ensure_private_dir(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(values, handle, indent=2, sort_keys=True)
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


def set_value(name: str, value: str) -> Path:
    if name not in SECRET_KEYS:
        raise SecretsError(f"unknown secret: {name}")
    value = value.strip()
    if not value:
        raise SecretsError("secret must not be empty")
    values = load()
    values[name] = value
    return save(values)


def unset(name: str) -> Path:
    if name not in SECRET_KEYS:
        raise SecretsError(f"unknown secret: {name}")
    values = load()
    values.pop(name, None)
    return save(values)


def resolve(name: str, env_name: str = "") -> str | None:
    """Return a secret from the environment or the private file."""
    candidates: list[str] = []
    if env_name:
        candidates.append(env_name)
    candidates.extend(ALIASES.get(name, ()))
    for candidate in candidates:
        value = os.environ.get(candidate)
        if value:
            return value.strip()
    try:
        return load().get(name) or None
    except SecretsError:
        return None


def source(name: str, env_name: str = "") -> str:
    """Describe where a secret comes from without revealing it."""
    candidates: list[str] = []
    if env_name:
        candidates.append(env_name)
    candidates.extend(ALIASES.get(name, ()))
    for candidate in candidates:
        if os.environ.get(candidate):
            return f"environment ({candidate})"
    try:
        if load().get(name):
            return f"file ({paths.secrets_path()})"
    except SecretsError:
        pass
    return "missing"
