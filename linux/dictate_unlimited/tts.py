"""OpenAI-compatible and MiMo text-to-speech clients.

There are two request shapes:

* ``openai`` posts ``{input, model, voice, response_format}`` to
  ``POST /v1/audio/speech`` and reads audio bytes.
* ``mimo`` posts a chat completion to ``POST /v1/chat/completions`` with the
  target speech in an ``assistant`` message and reads Base64 audio from
  ``choices[0].message.audio.data``.

Both end up as an in-memory audio blob, so the pipeline and playback code do
not care which provider produced it.  API keys are resolved from the
environment or ``secrets.json``; they are never stored in ``config.json``.
"""

from __future__ import annotations

import base64
import json
import logging
import socket
import struct
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import config as config_module, secrets

LOG = logging.getLogger(__name__)

MAX_AUDIO_BYTES = 64 * 1024 * 1024
MIMO_SAMPLE_RATE = 24_000

_EXTENSIONS = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/ogg": "ogg",
    "audio/opus": "opus",
    "audio/flac": "flac",
    "audio/x-flac": "flac",
    "audio/aac": "aac",
    "audio/mp4": "m4a",
    "audio/webm": "webm",
}


class TTSError(RuntimeError):
    pass


class TTSUnavailable(TTSError):
    pass


@dataclass
class TTSAudio:
    data: bytes
    content_type: str
    extension: str


def _endpoint(base_url: str, suffix: str = "/audio/speech") -> str:
    base = base_url.rstrip("/")
    if base.endswith(suffix):
        return base
    return base + suffix


def _chat_endpoint(base_url: str) -> str:
    return _endpoint(base_url, "/chat/completions")


def _is_local(base_url: str) -> bool:
    try:
        host = urllib.parse.urlparse(base_url).hostname or ""
    except ValueError:
        return False
    return host in ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def _extension(content_type: str, fallback: str) -> str:
    media = content_type.split(";", 1)[0].strip().lower()
    if media in _EXTENSIONS:
        return _EXTENSIONS[media]
    if media.startswith("audio/"):
        subtype = media.split("/", 1)[1]
        if subtype.isalnum():
            return subtype
    return fallback


def _wav_from_pcm(data: bytes, rate: int = MIMO_SAMPLE_RATE) -> bytes:
    """Wrap 16-bit mono little-endian PCM in a WAV container."""
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(data))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
        + b"data"
        + struct.pack("<I", len(data))
    )
    return header + data


class TTSClient:
    def __init__(self, config: config_module.Config):
        self.config = config

    @property
    def configured(self) -> bool:
        if self.config.tts_provider == "none":
            return False
        if not self.config.tts_base_url.strip():
            return False
        if self.config.tts_provider == "mimo":
            return bool(self.config.tts_model.strip())
        return True

    def endpoint(self) -> str:
        if self.config.tts_provider == "mimo":
            return _chat_endpoint(self.config.tts_base_url)
        return _endpoint(self.config.tts_base_url)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "audio/*, application/octet-stream",
        }
        key = secrets.resolve("tts_api_key", self.config.tts_api_key_env)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        elif not _is_local(self.config.tts_base_url):
            raise TTSUnavailable(
                "No TTS API key configured. Run `dictate secrets set tts_api_key` or "
                f"export {self.config.tts_api_key_env}."
            )
        return headers

    def check(self) -> None:
        """Validate configuration and credentials without making a request."""
        if not self.configured:
            if self.config.tts_provider == "mimo":
                raise TTSUnavailable(
                    "TTS is not configured. Set tts_base_url and tts_model "
                    "(for example mimo-v2.5-tts), then optionally tts_voice."
                )
            raise TTSUnavailable(
                "TTS is not configured. Set tts_base_url, tts_model, and tts_voice."
            )
        self._headers()

    def request_body(self, text: str) -> dict[str, object]:
        if self.config.tts_provider == "mimo":
            voice = self.config.tts_voice.strip() or "mimo_default"
            body: dict[str, object] = {
                "model": self.config.tts_model.strip(),
                "messages": [{"role": "assistant", "content": text}],
                "audio": {
                    "format": self.config.tts_format,
                    "voice": voice,
                },
            }
            return self._merge_extra(body)

        body = {
            "input": text,
            "response_format": self.config.tts_format,
        }
        if self.config.tts_model.strip():
            body["model"] = self.config.tts_model.strip()
        if self.config.tts_voice.strip():
            body["voice"] = self.config.tts_voice.strip()
        if self.config.tts_speed != 1.0:
            body["speed"] = self.config.tts_speed
        return self._merge_extra(body)

    def _merge_extra(self, body: dict[str, object]) -> dict[str, object]:
        try:
            extra = json.loads(self.config.tts_extra_body or "{}")
        except json.JSONDecodeError:
            extra = {}
        if isinstance(extra, dict):
            body.update(extra)
        return body

    def synthesize(self, text: str) -> TTSAudio:
        text = text.strip()
        if not text:
            raise TTSUnavailable("there is no text to synthesize")
        self.check()

        request = urllib.request.Request(
            self.endpoint(),
            data=json.dumps(self.request_body(text)).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            response = urllib.request.urlopen(request, timeout=self.config.tts_timeout)
        except urllib.error.HTTPError as exc:
            body = exc.read(1500).decode("utf-8", "replace").strip()
            raise TTSError(f"TTS HTTP {exc.code}: {body or exc.reason}") from exc
        except (urllib.error.URLError, socket.timeout, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise TTSError(f"cannot reach the TTS endpoint {self.endpoint()}: {reason}") from exc

        try:
            content_type = response.headers.get("Content-Type", "application/octet-stream")
            chunks: list[bytes] = []
            total = 0
            while True:
                block = response.read(64 * 1024)
                if not block:
                    break
                total += len(block)
                if total > MAX_AUDIO_BYTES:
                    raise TTSError("TTS response is larger than 64 MB")
                chunks.append(block)
        finally:
            try:
                response.close()
            except OSError:
                pass

        data = b"".join(chunks)
        if not data:
            raise TTSError("TTS returned an empty audio response")

        if self.config.tts_provider == "mimo":
            return self._parse_mimo(data, content_type)

        media = content_type.split(";", 1)[0].strip().lower()
        if media in ("application/json", "text/html", "text/plain"):
            detail = data[:1500].decode("utf-8", "replace").strip()
            raise TTSError(f"TTS returned {media} instead of audio: {detail}")
        return TTSAudio(
            data=data,
            content_type=content_type,
            extension=_extension(content_type, self.config.tts_format),
        )

    def _parse_mimo(self, raw: bytes, content_type: str) -> TTSAudio:
        try:
            payload = json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError as exc:
            detail = raw[:1500].decode("utf-8", "replace").strip()
            raise TTSError(f"MiMo TTS returned invalid JSON: {detail}") from exc
        if not isinstance(payload, dict):
            raise TTSError("MiMo TTS returned an unexpected JSON value")

        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code") or error
            raise TTSError(f"MiMo TTS error: {message}")

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise TTSError("MiMo TTS response did not contain choices")
        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message")
        audio = message.get("audio") if isinstance(message, dict) else None
        encoded = audio.get("data") if isinstance(audio, dict) else None
        if not isinstance(encoded, str) or not encoded:
            detail = raw[:1500].decode("utf-8", "replace").strip()
            raise TTSError(f"MiMo TTS response did not contain audio: {detail}")

        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise TTSError("MiMo TTS returned invalid Base64 audio") from exc
        if not data:
            raise TTSError("MiMo TTS returned empty audio")

        fmt = self.config.tts_format.lower()
        if fmt in ("pcm", "pcm16"):
            return TTSAudio(
                data=_wav_from_pcm(data),
                content_type="audio/wav",
                extension="wav",
            )
        if fmt == "mp3":
            return TTSAudio(data=data, content_type="audio/mpeg", extension="mp3")
        return TTSAudio(data=data, content_type="audio/wav", extension="wav")
