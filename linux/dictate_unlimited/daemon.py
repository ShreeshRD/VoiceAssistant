"""Long-running dictation state machine and Unix-socket service."""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable

from . import (
    __version__,
    asr,
    assistant as assistant_module,
    audio,
    config as config_module,
    corrections,
    insertion,
    ipc,
    models,
    notify,
    paths,
)

LOG = logging.getLogger(__name__)


class Engine:
    """Owns the microphone, transcription and delivery state.

    External commands are serialized by a lock, but slow work (capture teardown,
    Bark, wtype) always runs outside it so status and cancel stay responsive.
    """

    def __init__(
        self,
        config: config_module.Config,
        store: corrections.CorrectionStore,
        *,
        capture_factory: Callable[..., Any] = audio.Capture,
        transcriber: Callable[..., str] = asr.transcribe,
        deliverer: Callable[..., insertion.DeliveryResult] = insertion.deliver,
        notifier: Callable[..., None] = notify.notify,
        model_resolver: Callable[..., Any] = models.require_model,
        asr_finder: Callable[..., Path] = asr.find_asr,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.config = config
        self.store = store
        self._capture_factory = capture_factory
        self._transcriber = transcriber
        self._deliverer = deliverer
        self._notifier = notifier
        self._resolve_model = model_resolver
        self._find_asr = asr_finder
        self._clock = clock
        self._lock = threading.RLock()
        self.state = "idle"
        self.message = "Ready."
        self.level = 0.0
        self.seconds = 0.0
        self.last_transcript = ""
        self.capture: Any | None = None
        self.worker: threading.Thread | None = None
        self.monitor: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.shutdown_event = threading.Event()
        self.started_at = 0.0
        self.shutdown_callback: Callable[[], None] | None = None
        self.assistant = assistant_module.Assistant(
            config,
            capture_factory=capture_factory,
            transcriber=transcriber,
            notifier=self._notify,
            clock=clock,
        )

    # -- status ---------------------------------------------------------
    def _status_data(self) -> dict[str, Any]:
        return {
            "running": True,
            "model": self.config.model,
            "insertion": self.config.insertion,
            "threads": config_module.effective_threads(self.config),
            "seconds": round(self.seconds, 2),
            "level": round(self.level, 4),
            "has_last": bool(self.last_transcript),
            "last_chars": len(self.last_transcript),
            "corrections": len(self.store.entries),
            "cpu_only": True,
            "config": str(self.config.config_file()),
            "pid": os.getpid(),
            "version": __version__,
            "mode": "assistant" if self.assistant.active else "dictation",
            "assistant": self.assistant.status(),
        }

    def _current_state(self) -> tuple[str, str]:
        if self.assistant.active:
            return self.assistant.state, self.assistant.message
        return self.state, self.message

    def _response(self, ok: bool, message: str | None = None) -> dict[str, Any]:
        with self._lock:
            state, current_message = self._current_state()
            return {
                "ok": ok,
                "state": state,
                "message": message if message is not None else current_message,
                "data": self._status_data(),
            }

    def _set(self, state: str, message: str) -> None:
        with self._lock:
            if self.state != state:
                LOG.info("state %s -> %s", self.state, state)
            self.state = state
            self.message = message

    def _notify(self, message: str, urgency: str = "normal", **kwargs: Any) -> None:
        try:
            self._notifier(self.config, message, urgency, **kwargs)
        except Exception:
            LOG.debug("notification failed", exc_info=True)

    def status(self) -> dict[str, Any]:
        return self._response(True)

    # -- lifecycle ------------------------------------------------------
    def handle(self, command: str) -> dict[str, Any]:
        handlers: dict[str, Callable[[], dict[str, Any]]] = {
            "status": self.status,
            "ping": self.status,
            "start": self.start,
            "stop": self.stop,
            "toggle": self.toggle,
            "cancel": self.cancel,
            "paste-last": self.paste_last,
            "reload": self.reload,
            "quit": self.quit,
            "assistant-start": self.assistant_start,
            "assistant-stop": self.assistant_stop,
            "assistant-toggle": self.assistant_toggle,
            "assistant-cancel": self.assistant_cancel,
            "assistant-reset": self.assistant_reset,
            "assistant-warmup": self.assistant_warmup,
        }
        handler = handlers.get(command)
        if handler is None:
            return self._response(False, f"unknown command: {command}")
        try:
            return handler()
        except Exception as exc:
            LOG.exception("command %s failed", command)
            return self._response(False, f"{type(exc).__name__}: {exc}")

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self.assistant.active:
                return self._response(False, f"The assistant is busy: {self.assistant.message}")
            if self.state != "idle":
                return self._response(False, f"Busy: {self.message}")
            self.cancel_event.clear()
            self.level = 0.0
            self.seconds = 0.0
            self.state = "starting"
            self.message = "Preparing microphone..."
        LOG.info("start requested (model=%s, source=%s)", self.config.model, self.config.audio_source or "default")
        try:
            self._resolve_model(self.config)
            binary = self._find_asr(self.config)
            capabilities = asr.Capabilities(binary)
            if not capabilities.no_gpu:
                raise asr.ASRError(
                    f"{binary} does not support -ng/--no-gpu; refusing to risk GPU use"
                )
            LOG.info("asr binary: %s", binary)
        except Exception as exc:
            self._set("idle", str(exc))
            return self._response(False)

        capture = None
        try:
            capture = self._capture_factory(
                source=self.config.audio_source,
                max_seconds=self.config.max_seconds,
            )
            capture.start()
        except Exception as exc:
            if capture is not None:
                try:
                    capture.cancel()
                except Exception:
                    pass
            self._set("idle", f"Microphone error: {exc}")
            return self._response(False)

        with self._lock:
            if self.cancel_event.is_set() or self.state != "starting":
                cancelled = True
            else:
                cancelled = False
                self.capture = capture
                self.started_at = self._clock()
                self.state = "recording"
                self.message = "Listening locally. Press the shortcut again to finish."
        if cancelled:
            try:
                capture.cancel()
            except Exception:
                pass
            self._set("idle", "Microphone preparation cancelled.")
            return self._response(False)
        self._notify("Listening…")
        self.monitor = threading.Thread(target=self._monitor_loop, args=(capture,), daemon=True)
        self.monitor.start()
        return self._response(True)

    def _monitor_loop(self, capture: Any) -> None:
        while not self.shutdown_event.is_set():
            time.sleep(0.1)
            with self._lock:
                if self.capture is not capture or self.state != "recording":
                    return
                self.seconds, self.level = capture.snapshot()
                too_long = self.seconds >= self.config.max_seconds
                stalled = capture.stalled()
                gone = capture.process_gone()
            if too_long:
                LOG.info("maximum recording length reached")
                self.stop()
                return
            if gone:
                self._interrupt("Microphone input stopped. Recording discarded; start again.")
                return
            if stalled:
                self._interrupt("Microphone input stalled. Recording discarded; check PipeWire and start again.")
                return

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if self.state == "starting":
                self.cancel_event.set()
                self._set("idle", "Microphone preparation cancelled.")
                return self._response(True)
            if self.state != "recording":
                return self._response(False, f"Not recording ({self.state}).")
            capture = self.capture
            self.capture = None
            self.level = 0.0
            self.state = "transcribing"
            self.message = "Transcribing on CPU…"
        self._notify("Transcribing on CPU…")
        self.worker = threading.Thread(target=self._finish, args=(capture,), daemon=True)
        self.worker.start()
        return self._response(True)

    def _finish(self, capture: Any) -> None:
        wav: Path | None = None
        try:
            result = capture.stop()
            wav = result.path
            if self.cancel_event.is_set():
                self._set("idle", "Cancelled. Nothing was inserted.")
                return
            if result.rms < self.config.silence_rms:
                text = ""
            else:
                text = self._transcriber(wav, self.config, self.cancel_event)
            if self.cancel_event.is_set():
                self._set("idle", "Cancelled. Nothing was inserted.")
                return
            text = self.store.apply(text).strip()
            if not text:
                self._set("idle", "No speech detected. Try again.")
                self._notify("No speech detected.")
                return
            with self._lock:
                self.last_transcript = text
                self.state = "delivering"
                self.message = "Delivering text…"
            delivery = self._deliverer(text, self.config)
            if self.cancel_event.is_set():
                self._set("idle", "Cancelled. Nothing was inserted.")
                return
            self._set("idle", delivery.message)
            self._notify(delivery.message, "normal" if delivery.ok else "critical")
        except asr.Cancelled:
            self._set("idle", "Cancelled. Nothing was inserted.")
        except Exception as exc:
            LOG.exception("transcription/delivery failed")
            self._set("idle", f"{type(exc).__name__}: {exc}")
            self._notify(f"Dictation failed: {exc}", "critical")
        finally:
            if wav is not None and not self.config.keep_audio:
                try:
                    wav.unlink(missing_ok=True)
                except OSError:
                    pass
            with self._lock:
                self.worker = None
                if self.state in ("transcribing", "delivering", "cancelling"):
                    self.state = "idle"

    def _interrupt(self, message: str) -> None:
        with self._lock:
            capture = self.capture
            self.capture = None
            self.state = "idle"
            self.message = message
            self.level = 0.0
        if capture is not None:
            try:
                capture.cancel()
            except Exception:
                pass
        self._notify(message, "critical")

    def cancel(self) -> dict[str, Any]:
        with self._lock:
            assistant_active = self.assistant.active
        if assistant_active:
            return self.assistant_cancel()
        with self._lock:
            if self.state == "delivering":
                return self._response(False, "Text delivery is already in progress.")
            if self.state in ("recording", "starting"):
                capture = self.capture
                self.capture = None
                self.cancel_event.set()
                self.state = "idle"
                self.message = "Recording discarded."
                self.level = 0.0
                self.seconds = 0.0
            elif self.state in ("transcribing", "cancelling"):
                capture = None
                self.cancel_event.set()
                self.state = "cancelling"
                self.message = "Cancelling after the current local operation stops…"
            else:
                return self._response(False, "Nothing is running.")
        if capture is not None:
            try:
                capture.cancel()
            except Exception:
                pass
            self._notify("Recording discarded.")
        else:
            self._notify("Cancelling…")
        return self._response(True)

    def toggle(self) -> dict[str, Any]:
        with self._lock:
            state = self.state
        if state == "idle":
            return self.start()
        if state in ("recording", "starting", "transcribing", "cancelling"):
            return self.stop() if state == "recording" else self.cancel()
        return self._response(False, f"Busy: {self.message}")

    # -- voice assistant ------------------------------------------------
    def _dictation_busy(self) -> dict[str, Any] | None:
        if self.state != "idle":
            return self._response(False, f"Dictation is busy: {self.message}")
        return None

    def assistant_start(self) -> dict[str, Any]:
        with self._lock:
            busy = self._dictation_busy()
        if busy is not None:
            return busy
        result = self.assistant.start()
        return self._response(bool(result.get("ok")), str(result.get("message", "")))

    def assistant_stop(self) -> dict[str, Any]:
        result = self.assistant.stop()
        return self._response(bool(result.get("ok")), str(result.get("message", "")))

    def assistant_toggle(self) -> dict[str, Any]:
        state = self.assistant.state
        if state == "idle":
            return self.assistant_start()
        if state == "listening":
            return self.assistant_stop()
        # A second tap while the model is thinking or speaking interrupts it,
        # matching the push-to-talk feel of the Jarvis prototype.
        return self.assistant_cancel()

    def assistant_cancel(self) -> dict[str, Any]:
        if not self.assistant.active:
            return self._response(False, "The assistant is not running.")
        result = self.assistant.cancel()
        return self._response(bool(result.get("ok")), str(result.get("message", "")))

    def assistant_reset(self) -> dict[str, Any]:
        result = self.assistant.reset()
        return self._response(bool(result.get("ok")), str(result.get("message", "")))

    def assistant_warmup(self) -> dict[str, Any]:
        with self._lock:
            busy = self._dictation_busy()
        if busy is not None:
            return busy
        result = self.assistant.warmup()
        return self._response(bool(result.get("ok")), str(result.get("message", "")))

    def paste_last(self) -> dict[str, Any]:
        with self._lock:
            if self.state != "idle":
                return self._response(False, f"Busy: {self.message}")
            if not self.last_transcript:
                return self._response(False, "There is no completed dictation to paste.")
            text = self.last_transcript
            self.state = "delivering"
            self.message = "Pasting the last dictation…"

        def deliver() -> None:
            try:
                result = self._deliverer(text, self.config)
                self._set("idle", result.message)
                self._notify(result.message, "normal" if result.ok else "critical")
            except Exception as exc:
                LOG.exception("paste-last failed")
                self._set("idle", f"Paste failed: {exc}")
                self._notify(f"Paste failed: {exc}", "critical")
            finally:
                with self._lock:
                    self.worker = None

        self.worker = threading.Thread(target=deliver, daemon=True)
        self.worker.start()
        return self._response(True)

    def reload(self) -> dict[str, Any]:
        with self._lock:
            if self.state != "idle" or self.assistant.active:
                return self._response(False, "Cannot reload while busy.")
        try:
            new_config = config_module.load()
            new_store = corrections.CorrectionStore(paths.corrections_path())
            if new_store.load_error:
                raise corrections.CorrectionError(new_store.load_error)
        except Exception as exc:
            return self._response(False, f"Reload failed: {exc}")
        with self._lock:
            self.config = new_config
            self.store = new_store
            self.assistant.update_config(new_config)
            self.message = "Configuration and dictionary reloaded."
        return self._response(True)

    def quit(self) -> dict[str, Any]:
        self.request_shutdown()
        return self._response(True, "Shutting down.")

    def request_shutdown(self) -> None:
        self.shutdown_event.set()
        try:
            self.assistant.shutdown()
        except Exception:
            LOG.debug("assistant shutdown failed", exc_info=True)
        with self._lock:
            capture = self.capture
            self.capture = None
            self.cancel_event.set()
        if capture is not None:
            try:
                capture.cancel()
            except Exception:
                pass
        callback = self.shutdown_callback
        if callback is not None:
            threading.Thread(target=callback, daemon=True).start()


def configure_logging(config: config_module.Config, foreground: bool) -> None:
    paths.ensure_private_dir(paths.state_dir())
    level = getattr(logging, config.log_level, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        handler = RotatingFileHandler(paths.log_path(), maxBytes=1_000_000, backupCount=2)
        handler.setFormatter(formatter)
        root.addHandler(handler)
    except OSError:
        pass
    if foreground:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        root.addHandler(stream)


def _daemonize() -> None:
    if os.fork() > 0:
        os._exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    os.chdir("/")
    devnull = os.open(os.devnull, os.O_RDWR)
    for descriptor in (0, 1, 2):
        os.dup2(devnull, descriptor)
    os.close(devnull)


def _write_pid() -> None:
    paths.ensure_private_dir(paths.runtime_dir())
    pid_path = paths.pid_path()
    pid_path.write_text(f"{os.getpid()}\n", encoding="ascii")
    pid_path.chmod(0o600)


def _remove_pid() -> None:
    try:
        paths.pid_path().unlink(missing_ok=True)
    except OSError:
        pass


def run(config: config_module.Config, *, detach: bool = False, foreground: bool = False) -> int:
    if detach:
        _daemonize()
    configure_logging(config, foreground=foreground or not detach)
    LOG.info("starting dictate-unlimited %s (cpu-only)", __version__)
    LOG.info("config: %s", config.config_file())
    try:
        store = corrections.CorrectionStore(paths.corrections_path())
        if store.load_error:
            LOG.warning("corrections file unreadable; corrections disabled: %s", store.load_error)
        engine = Engine(config, store)
        wrote_pid = False

        def on_ready() -> None:
            nonlocal wrote_pid
            _write_pid()
            wrote_pid = True
            LOG.info("listening on %s", paths.socket_path())

        def stop_server() -> None:
            # Server is created inside ipc.serve; shut down through the module.
            ipc.shutdown_server()

        engine.shutdown_callback = stop_server

        for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            try:
                signal.signal(signum, lambda *_: engine.request_shutdown())
            except (ValueError, OSError):
                pass
        try:
            ipc.serve(engine, on_ready=on_ready)
        finally:
            if wrote_pid:
                _remove_pid()
            LOG.info("stopped")
        return 0
    except Exception as exc:
        LOG.exception("daemon failed")
        print(f"dictate daemon: {exc}", file=sys.stderr)
        return 1
