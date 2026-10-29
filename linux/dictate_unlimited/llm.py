"""OpenAI-compatible chat client with token streaming.

The assistant talks to any server that implements
``POST /v1/chat/completions`` with ``stream: true`` and server-sent events.
That includes llama.cpp's ``llama-server`` (used by the local Bonsai model),
Ollama's OpenAI shim, LM Studio, and remote OpenAI-compatible providers.  Only
the Python standard library is used at runtime.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Iterable

from . import config as config_module, paths, secrets

LOG = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


class LLMCancelled(LLMError):
    pass


def _endpoint(base_url: str, suffix: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith(suffix):
        return base
    return base + suffix


def _is_local(base_url: str) -> bool:
    try:
        host = urllib.parse.urlparse(base_url).hostname or ""
    except ValueError:
        return False
    return host in ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def _tail(path: Path, limit: int = 1200) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - limit))
            return handle.read().decode("utf-8", "replace").strip()
    except OSError:
        return ""


class LLMClient:
    def __init__(self, config: config_module.Config):
        self.config = config
        self._lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None

    # -- discovery -----------------------------------------------------
    def models_url(self) -> str:
        return _endpoint(self.config.llm_base_url, "/models")

    def chat_url(self) -> str:
        return _endpoint(self.config.llm_base_url, "/chat/completions")

    def _headers(self, *, stream: bool = False) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
        }
        key = secrets.resolve("llm_api_key", self.config.llm_api_key_env)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def health(self, timeout: float = 1.5) -> tuple[bool, str]:
        request = urllib.request.Request(self.models_url(), headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return True, f"HTTP {response.status}"
        except urllib.error.HTTPError as exc:
            # Any HTTP answer means the server is reachable; 401/404 are still
            # useful diagnostics but do not block the chat endpoint.
            return True, f"HTTP {exc.code}"
        except (urllib.error.URLError, socket.timeout, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            return False, str(reason)

    # -- server lifecycle ----------------------------------------------
    def ensure_server(
        self,
        *,
        cancel_event: threading.Event | None = None,
        notify: Callable[..., None] | None = None,
    ) -> str:
        """Check the endpoint, starting a local server if configured."""
        alive, detail = self.health()
        if alive:
            return "already running"

        if not _is_local(self.config.llm_base_url):
            raise LLMError(
                f"LLM endpoint is unreachable ({detail}). Check llm_base_url: "
                f"{self.config.llm_base_url}"
            )

        command = self.config.llm_start_command.strip()
        if not command:
            raise LLMError(
                f"No LLM server at {self.config.llm_base_url} ({detail}). Start your "
                "llama.cpp server, or set llm_start_command so the assistant can start it."
            )

        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return "starting"
            if notify:
                notify("Starting the local language model…")

            paths.ensure_private_dir(paths.state_dir())
            log_path = paths.llm_log_path()
            cwd = Path(self.config.llm_start_cwd).expanduser() if self.config.llm_start_cwd else None
            if cwd is not None and not cwd.is_dir():
                raise LLMError(f"llm_start_cwd is not a directory: {cwd}")
            try:
                argv = shlex.split(command)
            except ValueError as exc:
                raise LLMError(f"invalid llm_start_command: {exc}") from exc
            if not argv:
                raise LLMError("llm_start_command is empty")
            descriptor = os.open(
                log_path,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o600,
            )
            with os.fdopen(descriptor, "ab", buffering=0) as log_handle:
                try:
                    process = subprocess.Popen(
                        argv,
                        cwd=str(cwd) if cwd else None,
                        stdin=subprocess.DEVNULL,
                        stdout=log_handle,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                        close_fds=True,
                    )
                except OSError as exc:
                    raise LLMError(f"cannot start the LLM server ({argv[0]}): {exc}") from exc
            self._process = process
            LOG.info("started LLM server pid=%s command=%s", process.pid, command)

        deadline = time.monotonic() + self.config.llm_start_timeout
        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                self.stop_server()
                raise LLMCancelled("cancelled while starting the LLM server")
            process = self._process
            if process is not None and process.poll() is not None:
                tail = _tail(paths.llm_log_path())
                raise LLMError(
                    f"The LLM server exited with status {process.returncode}."
                    + (f" Log: {tail}" if tail else f" See {paths.llm_log_path()}.")
                )
            alive, detail = self.health(timeout=1.0)
            if alive:
                LOG.info("LLM server ready at %s", self.config.llm_base_url)
                return "started"
            time.sleep(0.5)

        tail = _tail(paths.llm_log_path())
        raise LLMError(
            f"The LLM server did not become ready within {self.config.llm_start_timeout}s."
            + (f" Log: {tail}" if tail else f" See {paths.llm_log_path()}.")
        )

    def stop_server(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
                process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass

    # -- chat ----------------------------------------------------------
    def build_messages(
        self,
        history: Iterable[dict[str, str]],
        user_text: str,
        *,
        now: str | None = None,
    ) -> list[dict[str, str]]:
        system = self.config.llm_system_prompt.strip()
        stamp = now or time.strftime("%A, %d %B %Y, %H:%M")
        system = f"{system}\n\nReference line, mention it only if the user asks for the date or time: {stamp}."
        messages = [{"role": "system", "content": system}]
        for message in history:
            role = message.get("role")
            content = message.get("content")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_text})
        return messages

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        on_delta: Callable[[str], None],
        *,
        cancel_event: threading.Event | None = None,
    ) -> str:
        payload = {
            "model": self.config.llm_model,
            "messages": messages,
            "stream": True,
            "temperature": self.config.llm_temperature,
            "max_tokens": self.config.llm_max_tokens,
        }
        request = urllib.request.Request(
            self.chat_url(),
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(stream=True),
            method="POST",
        )

        chunks: list[str] = []
        try:
            response = urllib.request.urlopen(request, timeout=self.config.llm_timeout)
        except urllib.error.HTTPError as exc:
            body = exc.read(1000).decode("utf-8", "replace").strip()
            raise LLMError(f"LLM HTTP {exc.code}: {body or exc.reason}") from exc
        except (urllib.error.URLError, socket.timeout, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise LLMError(f"cannot reach the LLM at {self.config.llm_base_url}: {reason}") from exc

        try:
            content_type = response.headers.get("Content-Type", "")
            if "application/json" in content_type:
                raw = response.read()
                text = self._consume_json(raw)
                if text:
                    chunks.append(text)
                    on_delta(text)
                return "".join(chunks).strip()

            for raw_line in response:
                if cancel_event is not None and cancel_event.is_set():
                    raise LLMCancelled("cancelled during generation")
                line = raw_line.decode("utf-8", "replace").strip()
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    data = line[5:].strip()
                else:
                    data = line
                if data == "[DONE]":
                    break
                if not data:
                    continue
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                text = self._consume_event(event)
                if text:
                    chunks.append(text)
                    on_delta(text)
        except socket.timeout as exc:
            raise LLMError("the LLM stream timed out") from exc
        finally:
            try:
                response.close()
            except OSError:
                pass

        if cancel_event is not None and cancel_event.is_set():
            raise LLMCancelled("cancelled during generation")
        return "".join(chunks).strip()

    @staticmethod
    def _content(value: object) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts: list[str] = []
            for part in value:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(part["text"])
            return "".join(parts)
        return ""

    def _consume_event(self, event: dict) -> str:
        choices = event.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        choice = choices[0]
        if not isinstance(choice, dict):
            return ""
        delta = choice.get("delta")
        if isinstance(delta, dict):
            # Reasoning tokens from thinking models are deliberately ignored.
            return self._content(delta.get("content"))
        message = choice.get("message")
        if isinstance(message, dict):
            return self._content(message.get("content"))
        return ""

    def _consume_json(self, raw: bytes) -> str:
        try:
            event = json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError as exc:
            raise LLMError(f"LLM returned invalid JSON: {exc}") from exc
        return self._consume_event(event)
