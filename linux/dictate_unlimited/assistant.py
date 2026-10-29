"""Streaming voice-assistant pipeline: ASR → LLM → parallel TTS → playback.

The responsiveness model is borrowed from the Jarvis prototype:

* the LLM response is consumed as a token stream, not as one block;
* complete sentences are handed to TTS immediately;
* a small worker pool synthesizes the next sentences while the current one is
  playing, and a separate ordered queue guarantees playback order;
* backpressure keeps only a few sentences in flight, which matters for a 4 GB
  GPU and a hosted TTS endpoint.

ASR deliberately stays on the existing CPU-only Bark path.  The LLM can use the
GPU; TTS runs remotely in phase 1 and can later be swapped for a local engine
behind :class:`dictate_unlimited.tts.TTSClient`.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import (
    asr,
    audio,
    config as config_module,
    llm,
    paths,
    playback,
    tts,
)

LOG = logging.getLogger(__name__)

TRANSCRIPT_NOTIFY_ID = 4_700_001
REPLY_NOTIFY_ID = 4_700_002

_ABBREVIATIONS = {
    "mr",
    "mrs",
    "ms",
    "dr",
    "prof",
    "sr",
    "jr",
    "st",
    "vs",
    "etc",
    "e.g",
    "i.e",
    "fig",
    "inc",
    "ltd",
    "no",
    "approx",
    "dept",
    "est",
    "al",
    "eg",
    "ie",
    "u.s",
    "u.k",
    "a.m",
    "p.m",
}

_FENCE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_LIST_PREFIX = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+", re.MULTILINE)
_EMPHASIS = re.compile(r"[*_~^#>]+")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACE = re.compile(r"\s+")


class AssistantError(RuntimeError):
    pass


class Cancelled(AssistantError):
    pass


def truncate(text: str, limit: int) -> str:
    text = _SPACE.sub(" ", text).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def clean_for_speech(text: str) -> str:
    """Turn model output into something sensible to speak and show."""
    text = _FENCE.sub(" code block ", text)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _URL.sub(" link ", text)
    text = _LIST_PREFIX.sub("", text)
    text = _EMPHASIS.sub("", text)
    text = _CONTROL.sub("", text)
    text = text.replace("&", " and ")
    return _SPACE.sub(" ", text).strip()


class ThinkFilter:
    """Strip ``<think>…</think>`` spans from a streamed reply.

    Thinking is disabled in the default Bonsai configuration, but other
    models may still emit the markers in ``content``.  The filter also handles
    tags split across chunks and holds back a possible partial tag so ordinary
    text such as ``<thing>`` is not lost.
    """

    _OPEN = "<think"
    _CLOSE = "</think"

    def __init__(self) -> None:
        self._buffer = ""
        self._inside = False

    def feed(self, text: str) -> str:
        if text:
            self._buffer += text
        return self._drain()

    def flush(self) -> str:
        text = self._drain()
        if not self._inside:
            text += self._buffer
        self._buffer = ""
        self._inside = False
        return text

    def _drain(self) -> str:
        output: list[str] = []
        while self._buffer:
            lowered = self._buffer.lower()
            if self._inside:
                index = lowered.find(self._CLOSE)
                if index < 0:
                    keep = self._suffix_prefix(lowered, self._CLOSE)
                    self._buffer = self._buffer[-keep:] if keep else ""
                    break
                end = lowered.find(">", index)
                if end < 0:
                    self._buffer = self._buffer[index:]
                    break
                self._buffer = self._buffer[end + 1 :]
                self._inside = False
                continue

            index = lowered.find(self._OPEN)
            if index < 0:
                cut = len(lowered) - self._suffix_prefix(lowered, self._OPEN)
                output.append(self._buffer[:cut])
                self._buffer = self._buffer[cut:]
                break
            if index > 0:
                output.append(self._buffer[:index])
                self._buffer = self._buffer[index:]
                continue
            end = lowered.find(">")
            if end < 0:
                break
            self._buffer = self._buffer[end + 1 :]
            self._inside = True
        return "".join(output)

    @staticmethod
    def _suffix_prefix(text: str, tag: str) -> int:
        for size in range(min(len(text), len(tag) - 1), 0, -1):
            if tag.startswith(text[-size:]):
                return size
        return 0



class SentenceSplitter:
    """Incremental sentence splitter for a token stream."""

    def __init__(self, max_chars: int = 240):
        self.max_chars = max(40, int(max_chars))
        self._buffer = ""

    def feed(self, text: str) -> list[str]:
        if not text:
            return []
        self._buffer += text
        output: list[str] = []
        while True:
            boundary = self._find_boundary(self._buffer)
            if boundary is None:
                break
            sentence = self._buffer[: boundary + 1].strip()
            self._buffer = self._buffer[boundary + 1 :].lstrip()
            if sentence:
                output.extend(self._split_long(sentence))
        while len(self._buffer) > self.max_chars:
            cut = self._buffer.rfind(" ", 0, self.max_chars)
            if cut < self.max_chars // 3:
                cut = self.max_chars
            piece = self._buffer[:cut].strip()
            self._buffer = self._buffer[cut:].lstrip()
            if piece:
                output.append(piece)
        return [piece for piece in output if piece]

    def flush(self) -> list[str]:
        remainder = self._buffer.strip()
        self._buffer = ""
        return [piece for piece in self._split_long(remainder) if piece]

    def _split_long(self, sentence: str) -> list[str]:
        sentence = sentence.strip()
        if not sentence:
            return []
        if len(sentence) <= self.max_chars:
            return [sentence]
        cut = sentence.rfind(" ", 0, self.max_chars)
        if cut < self.max_chars // 3:
            cut = self.max_chars
        head = sentence[:cut].strip()
        tail = sentence[cut:].strip()
        return [piece for piece in (head,) if piece] + self._split_long(tail)

    @staticmethod
    def _find_boundary(text: str) -> int | None:
        """Return the index of the last character of a complete sentence."""
        for index, char in enumerate(text):
            if char not in ".!?":
                continue
            end = index + 1
            while end < len(text) and text[end] in "\"'”’)]}":
                end += 1
            if end >= len(text):
                # Wait for more tokens for a period; a terminal !/? is fine.
                if char in "!?":
                    return end - 1
                continue
            if not text[end].isspace():
                continue
            if char == ".":
                if index > 0 and text[index - 1].isdigit() and text[end].isdigit():
                    continue
                word_match = re.search(r"([A-Za-z][A-Za-z.]*)$", text[:index].rstrip())
                if word_match:
                    word = word_match.group(1).lower().rstrip(".")
                    if word in _ABBREVIATIONS or len(word) == 1:
                        continue
            return end - 1
        return None


@dataclass
class _QueuedSentence:
    text: str
    future: Future[Path]


class SpeechPipeline:
    """Ordered playback with bounded, parallel synthesis."""

    def __init__(
        self,
        client: tts.TTSClient,
        player: playback.Player,
        config: config_module.Config,
        *,
        cancel_event: threading.Event,
        on_play: Callable[[], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ):
        self.client = client
        self.player = player
        self.config = config
        self.cancel_event = cancel_event
        self.on_play = on_play
        self.on_error = on_error
        self._executor = ThreadPoolExecutor(
            max_workers=config.tts_workers,
            thread_name_prefix="dictate-tts",
        )
        self._window = threading.Semaphore(config.tts_prefetch)
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._queue: deque[_QueuedSentence] = deque()
        self._done = False
        self._closed = False
        self._errors = 0
        self._temp_paths: set[Path] = set()
        self._thread = threading.Thread(
            target=self._play_loop,
            name="dictate-playback",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def feed(self, sentence: str) -> None:
        sentence = sentence.strip()
        if not sentence:
            return
        while not self._window.acquire(timeout=0.1):
            if self._cancel():
                raise Cancelled("cancelled while queueing speech")
        try:
            if self._cancel():
                raise Cancelled("cancelled while queueing speech")
            future = self._executor.submit(self._synthesize, sentence)
        except BaseException:
            self._window.release()
            raise
        with self._condition:
            self._queue.append(_QueuedSentence(sentence, future))
            self._condition.notify()

    def _synthesize(self, sentence: str) -> Path:
        if self._cancel():
            raise Cancelled("cancelled before synthesis")
        audio_data = self.client.synthesize(sentence)
        if self._cancel():
            raise Cancelled("cancelled after synthesis")
        directory = paths.ensure_private_dir(paths.audio_temp_dir())
        suffix = "." + (audio_data.extension or self.config.tts_format or "wav")
        descriptor, name = tempfile.mkstemp(prefix="tts-", suffix=suffix, dir=directory)
        path = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(audio_data.data)
            path.chmod(0o600)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        with self._lock:
            if self._closed:
                path.unlink(missing_ok=True)
                raise Cancelled("pipeline closed")
            self._temp_paths.add(path)
        return path

    def _play_loop(self) -> None:
        while True:
            if self._cancel():
                break
            with self._condition:
                while not self._queue and not self._done:
                    self._condition.wait(0.1)
                    if self._cancel():
                        break
                if not self._queue:
                    if self._done:
                        break
                    continue
                item = self._queue.popleft()
            path: Path | None = None
            try:
                path = item.future.result()
                if self._cancel():
                    break
                if self.on_play is not None:
                    self.on_play()
                self.player.play(path, self.cancel_event)
            except Cancelled:
                pass
            except BaseException as exc:  # noqa: BLE001 - report and keep playing
                self._report(exc)
            finally:
                if path is not None:
                    path.unlink(missing_ok=True)
                    with self._lock:
                        self._temp_paths.discard(path)
                self._window.release()
        self._cleanup()

    def _report(self, exc: BaseException) -> None:
        with self._lock:
            first = self._errors == 0
            self._errors += 1
        LOG.error("speech pipeline error: %s", exc)
        if first and self.on_error is not None:
            self.on_error(str(exc))

    def _cancel(self) -> bool:
        return self.cancel_event.is_set() or self._closed

    def finish(self) -> int:
        with self._condition:
            self._done = True
            self._condition.notify_all()
        self._thread.join()
        self._executor.shutdown(wait=True)
        self._cleanup()
        with self._lock:
            return self._errors

    def cancel(self) -> None:
        with self._condition:
            self._closed = True
            self._done = True
            self._condition.notify_all()
        self.player.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)
        if self._thread.is_alive():
            self._thread.join(timeout=3)
        self._cleanup()

    def _cleanup(self) -> None:
        with self._lock:
            paths_to_remove = list(self._temp_paths)
            self._temp_paths.clear()
        for path in paths_to_remove:
            path.unlink(missing_ok=True)


class Assistant:
    """Voice assistant state machine owned by the dictation daemon."""

    def __init__(
        self,
        config: config_module.Config,
        *,
        capture_factory: Callable[..., object] = audio.Capture,
        transcriber: Callable[..., str] = asr.transcribe,
        notifier: Callable[..., None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.config = config
        self._capture_factory = capture_factory
        self._transcriber = transcriber
        self._notifier = notifier
        self._clock = clock
        self._lock = threading.RLock()
        self.state = "idle"
        self.message = "Ready."
        self.level = 0.0
        self.seconds = 0.0
        self.heard = ""
        self.reply = ""
        self.error = ""
        self.history: list[dict[str, str]] = []
        self._capture: object | None = None
        self._monitor: threading.Thread | None = None
        self._worker: threading.Thread | None = None
        self._pipeline: SpeechPipeline | None = None
        self._cancel_event = threading.Event()
        self._shutdown = threading.Event()
        self._started_at = 0.0
        self._reply_parts: list[str] = []

    # -- status --------------------------------------------------------
    @property
    def active(self) -> bool:
        with self._lock:
            return self.state != "idle"

    def status(self) -> dict[str, object]:
        with self._lock:
            player = playback.Player(self.config)
            return {
                "state": self.state,
                "message": self.message,
                "level": round(self.level, 4),
                "seconds": round(self.seconds, 2),
                "heard": self.heard,
                "reply": self.reply,
                "error": self.error,
                "active": self.state != "idle",
                "history_turns": len(self.history) // 2,
                "llm_base_url": self.config.llm_base_url,
                "llm_model": self.config.llm_model,
                "tts_provider": self.config.tts_provider,
                "tts_configured": tts.TTSClient(self.config).configured,
                "tts_player": player.method(),
            }

    def _response(self, ok: bool, message: str | None = None) -> dict[str, object]:
        with self._lock:
            return {
                "ok": ok,
                "state": self.state,
                "message": message if message is not None else self.message,
                "data": self.status(),
            }

    def _set(self, state: str, message: str) -> None:
        with self._lock:
            if self.state != state:
                LOG.info("assistant %s -> %s (%s)", self.state, state, message)
            self.state = state
            self.message = message

    def _notify(self, message: str, urgency: str = "normal", **kwargs: object) -> None:
        if self._notifier is None:
            return
        try:
            self._notifier(message, urgency, **kwargs)
        except TypeError:
            try:
                self._notifier(message, urgency)
            except Exception:
                LOG.debug("notification failed", exc_info=True)
        except Exception:
            LOG.debug("notification failed", exc_info=True)

    def _show_transcript(self, text: str) -> None:
        self._notify(
            truncate(text, self.config.assistant_notify_chars),
            title="Heard",
            replace_id=TRANSCRIPT_NOTIFY_ID,
            group="dictate-assistant-transcript",
            timeout_ms=5000,
            icon="audio-input-microphone",
        )

    def _show_reply(self, text: str) -> None:
        self._notify(
            truncate(text, self.config.assistant_notify_chars),
            title="Assistant",
            replace_id=REPLY_NOTIFY_ID,
            group="dictate-assistant-reply",
            timeout_ms=7000,
            icon="audio-speakers",
        )

    # -- lifecycle -----------------------------------------------------
    def start(self) -> dict[str, object]:
        self._sweep_temp_audio()
        with self._lock:
            if self.state != "idle":
                return self._response(False, f"Assistant is busy: {self.message}")
            self._cancel_event = threading.Event()
            self.error = ""
            self.heard = ""
            self.reply = ""
            self._reply_parts = []
            self.level = 0.0
            self.seconds = 0.0
            self.state = "starting"
            self.message = "Preparing microphone…"

        capture = None
        try:
            capture = self._capture_factory(
                source=self.config.audio_source,
                max_seconds=self.config.assistant_max_seconds,
            )
            capture.start()
        except Exception as exc:
            if capture is not None:
                try:
                    capture.cancel()
                except Exception:
                    pass
            self._fail(f"Microphone error: {exc}")
            return self._response(False)

        with self._lock:
            if self._cancel_event.is_set() or self.state != "starting":
                cancelled = True
            else:
                cancelled = False
                self._capture = capture
                self._started_at = self._clock()
                self.state = "listening"
                self.message = "Listening…"
        if cancelled:
            try:
                capture.cancel()
            except Exception:
                pass
            self._set("idle", "Microphone preparation cancelled.")
            return self._response(False)

        self._monitor = threading.Thread(
            target=self._monitor_loop,
            args=(capture,),
            name="dictate-assistant-monitor",
            daemon=True,
        )
        self._monitor.start()
        return self._response(True)

    def _monitor_loop(self, capture: object) -> None:
        while not self._shutdown.is_set():
            time.sleep(0.1)
            with self._lock:
                if self._capture is not capture or self.state != "listening":
                    return
                try:
                    self.seconds, self.level = capture.snapshot()  # type: ignore[attr-defined]
                except Exception:
                    return
                too_long = self.seconds >= self.config.assistant_max_seconds
                try:
                    gone = capture.process_gone()  # type: ignore[attr-defined]
                    stalled = capture.stalled()  # type: ignore[attr-defined]
                except Exception:
                    gone = False
                    stalled = False
            if too_long:
                LOG.info("assistant maximum recording length reached")
                self.stop()
                return
            if gone:
                self._interrupt("Microphone input stopped. Recording discarded.")
                return
            if stalled:
                self._interrupt("Microphone input stalled. Check PipeWire and try again.")
                return

    def stop(self) -> dict[str, object]:
        with self._lock:
            if self.state == "starting":
                self._cancel_event.set()
                self._set("idle", "Microphone preparation cancelled.")
                return self._response(True)
            if self.state != "listening":
                return self._response(False, f"Not listening ({self.state}).")
            capture = self._capture
            self._capture = None
            self.level = 0.0
            self.state = "transcribing"
            self.message = "Transcribing on CPU…"
        self._worker = threading.Thread(
            target=self._process,
            args=(capture,),
            name="dictate-assistant-worker",
            daemon=True,
        )
        self._worker.start()
        return self._response(True)

    def _process(self, capture: object) -> None:
        wav: Path | None = None
        try:
            result = capture.stop()  # type: ignore[attr-defined]
            wav = Path(result.path)
            if self._cancel_event.is_set():
                raise Cancelled("cancelled")
            if result.rms < self.config.silence_rms:
                text = ""
            else:
                text = self._transcriber(wav, self.config, self._cancel_event)
            text = (text or "").strip()
            if self._cancel_event.is_set():
                raise Cancelled("cancelled")
            if not text:
                self._set("idle", "No speech detected.")
                self._notify("No speech detected.", "normal")
                return
            with self._lock:
                self.heard = text
            self._show_transcript(text)
            self._set("thinking", "Thinking…")
            reply = self._converse(text)
            if self._cancel_event.is_set():
                raise Cancelled("cancelled")
            if not reply:
                raise AssistantError("The language model returned an empty reply.")
            with self._lock:
                self.reply = reply
                self._remember_locked(text, reply)
                self.state = "idle"
                self.message = "Ready."
        except Cancelled:
            with self._lock:
                self.state = "idle"
                self.message = "Cancelled."
        except Exception as exc:
            LOG.exception("assistant pipeline failed")
            self._notify(f"Assistant failed: {exc}", "critical")
            self._fail(f"{type(exc).__name__}: {exc}")
        finally:
            if wav is not None and not self.config.keep_audio:
                try:
                    wav.unlink(missing_ok=True)
                except OSError:
                    pass
            with self._lock:
                self._worker = None
                self._pipeline = None
                if self.state in ("thinking", "speaking", "transcribing"):
                    self.state = "idle"

    def _converse(self, text: str) -> str:
        client = llm.LLMClient(self.config)
        try:
            client.ensure_server(cancel_event=self._cancel_event, notify=self._notify)
        except llm.LLMCancelled as exc:
            raise Cancelled(str(exc)) from exc
        except llm.LLMError as exc:
            raise AssistantError(str(exc)) from exc

        messages = client.build_messages(self._trimmed_history(), text)
        splitter = SentenceSplitter(self.config.tts_max_chars)
        think_filter = ThinkFilter()
        pipeline = self._start_speech_pipeline()

        def handle(sentence: str) -> None:
            sentence = clean_for_speech(sentence)
            if not sentence:
                return
            with self._lock:
                self._reply_parts.append(sentence)
                partial = " ".join(self._reply_parts)
            self._show_reply(partial)
            if pipeline is not None:
                pipeline.feed(sentence)

        def push(delta: str) -> None:
            for sentence in splitter.feed(think_filter.feed(delta)):
                handle(sentence)

        try:
            client.chat_stream(
                messages,
                push,
                cancel_event=self._cancel_event,
            )
            for sentence in splitter.feed(think_filter.flush()):
                handle(sentence)
            for sentence in splitter.flush():
                handle(sentence)
        finally:
            if pipeline is not None:
                if self._cancel_event.is_set():
                    pipeline.cancel()
                else:
                    errors = pipeline.finish()
                    if errors:
                        self._notify(
                            "Speech synthesis failed for part of the reply; the text is in the notification.",
                            "normal",
                        )
            with self._lock:
                self._pipeline = None
                reply = " ".join(self._reply_parts).strip()
                if not reply:
                    reply = clean_for_speech(
                        " ".join(part for part in self._reply_parts if part)
                    )
        if self._cancel_event.is_set():
            raise Cancelled("cancelled during the reply")
        return reply

    def _start_speech_pipeline(self) -> SpeechPipeline | None:
        if self.config.tts_provider == "none":
            return None
        client = tts.TTSClient(self.config)
        try:
            client.check()
        except tts.TTSUnavailable as exc:
            LOG.warning("TTS unavailable: %s", exc)
            self._notify(f"{exc} Replies will be shown as text only.", "normal")
            return None
        player = playback.Player(self.config)
        if not player.available():
            self._notify(
                "No audio player found; install mpv, pw-cat, or ffplay. Replies will be text only.",
                "critical",
            )
            return None
        pipeline = SpeechPipeline(
            client,
            player,
            self.config,
            cancel_event=self._cancel_event,
            on_play=self._on_first_audio,
            on_error=lambda message: self._notify(
                f"Speech synthesis failed: {message}", "normal"
            ),
        )
        pipeline.start()
        with self._lock:
            self._pipeline = pipeline
        return pipeline

    def _on_first_audio(self) -> None:
        with self._lock:
            if self.state == "thinking":
                self.state = "speaking"
                self.message = "Speaking…"

    def cancel(self) -> dict[str, object]:
        with self._lock:
            if self.state == "idle":
                return self._response(False, "Nothing is running.")
            self._cancel_event.set()
            capture = self._capture
            self._capture = None
            pipeline = self._pipeline
            self.state = "idle"
            self.message = "Cancelled."
            self.level = 0.0
        if capture is not None:
            try:
                capture.cancel()  # type: ignore[attr-defined]
            except Exception:
                pass
        if pipeline is not None:
            pipeline.cancel()
        self._notify("Cancelled.", "normal")
        return self._response(True)

    def reset(self) -> dict[str, object]:
        with self._lock:
            if self.state != "idle":
                return self._response(False, "Cannot reset while the assistant is busy.")
            self.history.clear()
            self.heard = ""
            self.reply = ""
            self.error = ""
            self.message = "Conversation history cleared."
        return self._response(True)

    def warmup(self) -> dict[str, object]:
        with self._lock:
            if self.state != "idle":
                return self._response(False, f"Assistant is busy: {self.message}")
            self._cancel_event = threading.Event()
        client = llm.LLMClient(self.config)
        try:
            state = client.ensure_server(cancel_event=self._cancel_event, notify=self._notify)
        except llm.LLMError as exc:
            self._fail(f"{type(exc).__name__}: {exc}")
            return self._response(False)
        notes = [f"LLM: {state} at {self.config.llm_base_url}"]
        tts_client = tts.TTSClient(self.config)
        if tts_client.configured:
            try:
                tts_client.check()
                notes.append("TTS: configured")
            except tts.TTSUnavailable as exc:
                notes.append(f"TTS: {exc}")
        else:
            notes.append("TTS: not configured")
        player = playback.Player(self.config)
        notes.append(f"Player: {player.method() or 'missing'}")
        message = " · ".join(notes)
        with self._lock:
            self.error = ""
            self.message = message
        return self._response(True, message)

    def update_config(self, config: config_module.Config) -> bool:
        with self._lock:
            if self.state != "idle":
                return False
            self.config = config
            return True

    def shutdown(self) -> None:
        self._shutdown.set()
        self.cancel()

    def _interrupt(self, message: str) -> None:
        with self._lock:
            capture = self._capture
            self._capture = None
            self.state = "idle"
            self.message = message
            self.level = 0.0
        if capture is not None:
            try:
                capture.cancel()  # type: ignore[attr-defined]
            except Exception:
                pass
        self._notify(message, "critical")

    def _fail(self, message: str) -> None:
        with self._lock:
            self.error = message
            self.state = "idle"
            self.message = message
            self.level = 0.0

    @staticmethod
    def _sweep_temp_audio(max_age: float = 3600.0) -> None:
        """Remove abandoned TTS files from a crashed session."""
        try:
            directory = paths.ensure_private_dir(paths.audio_temp_dir())
        except OSError:
            return
        now = time.time()
        for path in directory.glob("tts-*"):
            try:
                if now - path.stat().st_mtime > max_age:
                    path.unlink(missing_ok=True)
            except OSError:
                pass

    def _trimmed_history(self) -> list[dict[str, str]]:
        turns = max(0, self.config.assistant_history_turns)
        if turns == 0:
            return []
        return list(self.history[-turns * 2 :])

    def _remember_locked(self, user_text: str, reply: str) -> None:
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": reply})
        turns = max(0, self.config.assistant_history_turns)
        if turns == 0:
            self.history.clear()
        else:
            self.history = self.history[-turns * 2 :]
