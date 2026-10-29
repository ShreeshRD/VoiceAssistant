"""Unix-socket control channel for the long-running dictation daemon."""

from __future__ import annotations

import json
import logging
import os
import socket
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import paths

LOG = logging.getLogger(__name__)
MAX_LINE = 16 * 1024
AUTOSTART_COMMANDS = {
    "toggle",
    "start",
    "stop",
    "paste-last",
    "cancel",
    "assistant-toggle",
    "assistant-start",
    "assistant-stop",
    "assistant-cancel",
    "assistant-reset",
    "assistant-warmup",
}
_SERVER: "Server | None" = None


class IPCError(RuntimeError):
    pass


def _connect(path: Path, timeout: float) -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(str(path))
    except BaseException:
        sock.close()
        raise
    return sock


def request(
    command: str,
    *,
    timeout: float = 10.0,
    autostart: bool = True,
) -> dict[str, Any]:
    path = paths.socket_path()
    payload = json.dumps({"command": command}, separators=(",", ":")).encode("utf-8") + b"\n"
    attempted_start = False
    while True:
        try:
            sock = _connect(path, min(2.0, timeout))
            break
        except (FileNotFoundError, ConnectionRefusedError, socket.timeout, OSError) as exc:
            if autostart and command in AUTOSTART_COMMANDS and not attempted_start:
                attempted_start = True
                _spawn_daemon()
                if _wait_for_socket(path, 5.0):
                    continue
            raise IPCError(f"dictate daemon is not running ({exc}). Start it with: dictate daemon --detach") from exc

    try:
        with sock:
            sock.settimeout(timeout)
            sock.sendall(payload)
            sock.shutdown(socket.SHUT_WR)
            chunks: list[bytes] = []
            while True:
                block = sock.recv(65536)
                if not block:
                    break
                chunks.append(block)
                if sum(len(chunk) for chunk in chunks) > MAX_LINE:
                    raise IPCError("daemon response was too large")
    except socket.timeout as exc:
        raise IPCError("daemon did not answer in time") from exc
    except OSError as exc:
        raise IPCError(f"daemon connection failed: {exc}") from exc

    raw = b"".join(chunks).decode("utf-8", "replace").strip()
    if not raw:
        raise IPCError("daemon returned an empty response")
    try:
        response = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IPCError(f"daemon returned invalid JSON: {exc}") from exc
    if not isinstance(response, dict):
        raise IPCError("daemon returned an invalid response")
    return response


def _wait_for_socket(path: Path, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with _connect(path, 0.25):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _spawn_daemon() -> None:
    launcher = paths.source_launcher()
    if not launcher.is_file():
        found = paths.repo_root() / "linux" / "dictate"
        if found.is_file():
            launcher = found
        else:
            raise IPCError("cannot find the dictate launcher to auto-start the daemon")
    command = [sys.executable, str(launcher), "daemon", "--detach"]
    try:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except OSError as exc:
        raise IPCError(f"could not start the daemon: {exc}") from exc


class _Handler(socketserver.StreamRequestHandler):
    engine: Any

    def handle(self) -> None:
        raw = self.rfile.readline(MAX_LINE)
        if not raw:
            return
        try:
            message = json.loads(raw.decode("utf-8"))
            command = message.get("command", "")
            if not isinstance(command, str) or not command:
                raise ValueError("missing command")
            response = self.engine.handle(command)
        except Exception as exc:  # Never let a malformed request kill the server.
            LOG.exception("bad IPC request")
            response = {"ok": False, "state": "unknown", "message": str(exc)}
        try:
            self.wfile.write(json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n")
        except OSError:
            pass


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, path: Path, engine: Any):
        paths.ensure_private_dir(path.parent)
        if path.exists():
            try:
                with _connect(path, 0.25):
                    raise IPCError(f"another daemon is already listening on {path}")
            except IPCError:
                raise
            except OSError:
                path.unlink(missing_ok=True)
        handler = type("Handler", (_Handler,), {"engine": engine})
        super().__init__(str(path), handler)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        self.path = path
        self.engine = engine

    def server_close(self) -> None:
        super().server_close()
        self.path.unlink(missing_ok=True)


def serve(engine: Any, on_ready: Callable[[], None] | None = None) -> None:
    global _SERVER
    server = Server(paths.socket_path(), engine)
    _SERVER = server
    try:
        if on_ready:
            on_ready()
        server.serve_forever(poll_interval=0.2)
    finally:
        _SERVER = None
        server.server_close()


def shutdown_server() -> None:
    """Stop serve_forever from a handler/signal thread."""
    server = _SERVER
    if server is not None:
        server.shutdown()
