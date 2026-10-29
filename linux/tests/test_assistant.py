from __future__ import annotations

import base64
import json
import os
import stat
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from dictate_unlimited import (
    assistant as assistant_module,
    audio,
    config as config_module,
    llm,
    playback,
    secrets,
    tts,
)


class FakeHTTPServer:
    """Tiny threaded HTTP server used by the LLM/TTS tests."""

    def __init__(self, handler_class: type[BaseHTTPRequestHandler]):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "FakeHTTPServer":
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"


class LLMHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []
    sentences = ["Hello there. ", "How can I help?"]

    def log_message(self, *args: object) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        if self.path.endswith("/models"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"data":[]}')
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        LLMHandler.requests.append(body)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for sentence in LLMHandler.sentences:
            event = {"choices": [{"delta": {"content": sentence}}]}
            self.wfile.write(b"data: " + json.dumps(event).encode() + b"\n\n")
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


class TTSHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []
    payload = b"RIFF-fake-wav"

    def log_message(self, *args: object) -> None:
        pass

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        TTSHandler.requests.append(
            {"body": body, "authorization": self.headers.get("Authorization")}
        )
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(TTSHandler.payload)))
        self.end_headers()
        self.wfile.write(TTSHandler.payload)


class MiMoHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []
    audio = b"RIFF-mimo-wav"

    def log_message(self, *args: object) -> None:
        pass

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        MiMoHandler.requests.append(
            {"path": self.path, "body": body, "authorization": self.headers.get("Authorization")}
        )
        payload = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": body.get("model"),
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "audio": {
                            "id": "audio-test",
                            "data": base64.b64encode(MiMoHandler.audio).decode(),
                            "expires_at": None,
                            "transcript": None,
                        },
                    },
                }
            ],
        }
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class SplitterTests(unittest.TestCase):
    def test_incremental_sentences(self) -> None:
        splitter = assistant_module.SentenceSplitter(240)
        self.assertEqual(splitter.feed("Hello world. How are"), ["Hello world."])
        self.assertEqual(splitter.feed(" you? Fine"), ["How are you?"])
        self.assertEqual(splitter.feed("."), [])
        self.assertEqual(splitter.flush(), ["Fine."])

    def test_abbreviations_and_decimals(self) -> None:
        splitter = assistant_module.SentenceSplitter(240)
        text = "Dr. Smith arrived at 3.14 degrees. Then he left. "
        self.assertEqual(
            splitter.feed(text),
            ["Dr. Smith arrived at 3.14 degrees.", "Then he left."],
        )
        self.assertEqual(splitter.flush(), [])

    def test_long_text_is_split(self) -> None:
        splitter = assistant_module.SentenceSplitter(60)
        pieces = splitter.feed("word " * 30)
        self.assertTrue(pieces)
        self.assertTrue(all(len(piece) <= 60 for piece in pieces))
        self.assertTrue(all(piece.strip() == piece for piece in pieces))

    def test_flush_without_trailing_space(self) -> None:
        splitter = assistant_module.SentenceSplitter(240)
        self.assertEqual(splitter.feed("A complete thought."), [])
        self.assertEqual(splitter.flush(), ["A complete thought."])


class ThinkFilterTests(unittest.TestCase):
    def test_complete_block_is_removed(self) -> None:
        filter_ = assistant_module.ThinkFilter()
        self.assertEqual(filter_.feed("<think>secret</think>Hello."), "Hello.")
        self.assertEqual(filter_.flush(), "")

    def test_tag_split_across_chunks(self) -> None:
        filter_ = assistant_module.ThinkFilter()
        self.assertEqual(filter_.feed("<thi"), "")
        self.assertEqual(filter_.feed("nk>secret. </thi"), "")
        self.assertEqual(filter_.feed("nk>Hello. How"), "Hello. How")
        self.assertEqual(filter_.flush(), "")

    def test_ordinary_text_with_angle_brackets(self) -> None:
        filter_ = assistant_module.ThinkFilter()
        self.assertEqual(filter_.feed("The <thing> is here."), "The <thing> is here.")
        self.assertEqual(filter_.flush(), "")

    def test_unclosed_block_is_dropped_at_end(self) -> None:
        filter_ = assistant_module.ThinkFilter()
        self.assertEqual(filter_.feed("Hello. <think>hidden"), "Hello. ")
        self.assertEqual(filter_.flush(), "")


class TextCleanupTests(unittest.TestCase):
    def test_markdown_and_urls(self) -> None:
        text = "**Hello** [link](https://example.com) and `code` https://x.test"
        cleaned = assistant_module.clean_for_speech(text)
        self.assertIn("Hello", cleaned)
        self.assertIn("link", cleaned)
        self.assertIn("code", cleaned)
        self.assertNotIn("**", cleaned)
        self.assertNotIn("https://", cleaned)

    def test_lists_and_whitespace(self) -> None:
        cleaned = assistant_module.clean_for_speech("- one\n- two\n\n")
        self.assertEqual(cleaned, "one two")

    def test_truncate(self) -> None:
        self.assertEqual(assistant_module.truncate("short", 10), "short")
        value = assistant_module.truncate("a" * 30, 10)
        self.assertEqual(len(value), 10)
        self.assertTrue(value.endswith("…"))


class LLMClientTests(unittest.TestCase):
    def test_health_and_stream(self) -> None:
        LLMHandler.requests.clear()
        with FakeHTTPServer(LLMHandler) as server:
            config = config_module.Config(llm_base_url=f"{server.base_url}/v1")
            client = llm.LLMClient(config)
            alive, detail = client.health()
            self.assertTrue(alive, detail)

            deltas: list[str] = []
            reply = client.chat_stream(
                client.build_messages([], "hi"),
                deltas.append,
            )
        self.assertEqual(reply, "Hello there. How can I help?")
        self.assertEqual(deltas, ["Hello there. ", "How can I help?"])
        self.assertEqual(LLMHandler.requests[0]["stream"], True)
        self.assertEqual(LLMHandler.requests[0]["messages"][-1]["content"], "hi")

    def test_connection_error_is_actionable(self) -> None:
        config = config_module.Config(llm_base_url="http://127.0.0.1:1/v1")
        client = llm.LLMClient(config)
        alive, _ = client.health()
        self.assertFalse(alive)
        with self.assertRaises(llm.LLMError):
            client.chat_stream([{"role": "user", "content": "hi"}], lambda _: None)


class TTSClientTests(unittest.TestCase):
    def setUp(self) -> None:
        TTSHandler.requests.clear()

    def test_request_and_key(self) -> None:
        with FakeHTTPServer(TTSHandler) as server:
            config = config_module.Config(
                tts_base_url=f"{server.base_url}/v1",
                tts_model="mimo-tts",
                tts_voice="alloy",
            )
            with mock.patch.dict(os.environ, {"DICTATE_TTS_API_KEY": "secret-key"}):
                result = tts.TTSClient(config).synthesize("Hello.")
        self.assertEqual(result.data, TTSHandler.payload)
        self.assertEqual(result.extension, "wav")
        self.assertEqual(TTSHandler.requests[0]["authorization"], "Bearer secret-key")
        body = TTSHandler.requests[0]["body"]
        self.assertEqual(body["input"], "Hello.")
        self.assertEqual(body["model"], "mimo-tts")
        self.assertEqual(body["voice"], "alloy")
        self.assertEqual(body["response_format"], "wav")

    def test_missing_key_for_remote_endpoint(self) -> None:
        config = config_module.Config(
            tts_base_url="https://api.example.invalid/v1",
            tts_model="mimo",
        )
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(
                os.environ,
                {"XDG_CONFIG_HOME": directory, "XDG_STATE_HOME": directory},
                clear=True,
            ):
                with self.assertRaises(tts.TTSUnavailable):
                    tts.TTSClient(config).check()

    def test_local_endpoint_needs_no_key(self) -> None:
        with FakeHTTPServer(TTSHandler) as server:
            config = config_module.Config(tts_base_url=f"{server.base_url}/v1")
            with mock.patch.dict(os.environ, {}, clear=True):
                tts.TTSClient(config).check()
                tts.TTSClient(config).synthesize("Hello.")

    def test_mimo_chat_completions(self) -> None:
        MiMoHandler.requests.clear()
        with FakeHTTPServer(MiMoHandler) as server:
            config = config_module.Config(
                tts_provider="mimo",
                tts_base_url=f"{server.base_url}/v1",
                tts_model="mimo-v2.5-tts",
                tts_voice="Mia",
            )
            with mock.patch.dict(os.environ, {"DICTATE_TTS_API_KEY": "secret-key"}):
                result = tts.TTSClient(config).synthesize("Hello there.")
        self.assertEqual(result.data, MiMoHandler.audio)
        self.assertEqual(result.extension, "wav")
        request = MiMoHandler.requests[0]
        self.assertEqual(request["path"], "/v1/chat/completions")
        self.assertEqual(request["authorization"], "Bearer secret-key")
        body = request["body"]
        self.assertEqual(body["model"], "mimo-v2.5-tts")
        self.assertEqual(body["messages"][-1], {"role": "assistant", "content": "Hello there."})
        self.assertEqual(body["audio"], {"format": "wav", "voice": "Mia"})
        self.assertNotIn("input", body)

    def test_mimo_pcm16_is_wrapped_as_wav(self) -> None:
        MiMoHandler.requests.clear()
        MiMoHandler.audio = b"\x00\x01" * 10
        try:
            with FakeHTTPServer(MiMoHandler) as server:
                config = config_module.Config(
                    tts_provider="mimo",
                    tts_base_url=f"{server.base_url}/v1",
                    tts_model="mimo-v2.5-tts",
                    tts_format="pcm16",
                )
                with mock.patch.dict(os.environ, {"DICTATE_TTS_API_KEY": "secret-key"}):
                    result = tts.TTSClient(config).synthesize("Hello.")
        finally:
            MiMoHandler.audio = b"RIFF-mimo-wav"
        self.assertEqual(result.extension, "wav")
        self.assertTrue(result.data.startswith(b"RIFF"))
        self.assertIn(b"WAVEfmt ", result.data)

    def test_mimo_requires_model(self) -> None:
        config = config_module.Config(tts_provider="mimo", tts_base_url="https://example.test/v1")
        self.assertFalse(tts.TTSClient(config).configured)
        with self.assertRaises(tts.TTSUnavailable):
            tts.TTSClient(config).check()


class SecretsTests(unittest.TestCase):
    def test_set_load_unset_and_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}):
                secrets.set_value("tts_api_key", "abc123")
                path = Path(directory) / "dictate-unlimited" / "secrets.json"
                self.assertTrue(path.is_file())
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(secrets.load()["tts_api_key"], "abc123")
                secrets.unset("tts_api_key")
                self.assertNotIn("tts_api_key", secrets.load())

    def test_environment_wins(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}):
                secrets.set_value("tts_api_key", "file-key")
                with mock.patch.dict(os.environ, {"DICTATE_TTS_API_KEY": "env-key"}):
                    self.assertEqual(secrets.resolve("tts_api_key"), "env-key")


class FakeTTS:
    def __init__(self, delays: dict[str, float] | None = None):
        self.delays = delays or {}
        self.calls: list[str] = []

    def synthesize(self, text: str) -> tts.TTSAudio:
        self.calls.append(text)
        time.sleep(self.delays.get(text, 0.0))
        return tts.TTSAudio(data=text.encode(), content_type="audio/wav", extension="wav")


class FakePlayer:
    def __init__(self, config: object = None) -> None:
        self.config = config
        self.played: list[str] = []
        self.stopped = False

    def available(self) -> bool:
        return True

    def method(self) -> str:
        return "fake"

    def play(self, path: Path, cancel_event: threading.Event | None = None) -> bool:
        self.played.append(path.read_bytes().decode())
        return True

    def stop(self) -> None:
        self.stopped = True


class SpeechPipelineTests(unittest.TestCase):
    def test_parallel_synthesis_keeps_playback_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": directory}):
                client = FakeTTS({"first": 0.15, "second": 0.05, "third": 0.05})
                player = FakePlayer()
                config = config_module.Config(tts_workers=3, tts_prefetch=3)
                cancel = threading.Event()
                pipeline = assistant_module.SpeechPipeline(
                    client, player, config, cancel_event=cancel  # type: ignore[arg-type]
                )
                pipeline.start()
                for sentence in ("first", "second", "third"):
                    pipeline.feed(sentence)
                errors = pipeline.finish()
        self.assertEqual(errors, 0)
        self.assertEqual(player.played, ["first", "second", "third"])
        self.assertEqual(sorted(client.calls), ["first", "second", "third"])

    def test_cancel_stops_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": directory}):
                client = FakeTTS({"slow": 0.3})
                player = FakePlayer()
                config = config_module.Config(tts_workers=1, tts_prefetch=1)
                cancel = threading.Event()
                pipeline = assistant_module.SpeechPipeline(
                    client, player, config, cancel_event=cancel  # type: ignore[arg-type]
                )
                pipeline.start()
                pipeline.feed("slow")
                time.sleep(0.05)
                cancel.set()
                pipeline.cancel()
        self.assertTrue(player.stopped)


class FakeCapture:
    instances: list["FakeCapture"] = []

    def __init__(self, source: str = "", max_seconds: int = 120):
        self.source = source
        self.max_seconds = max_seconds
        self.cancelled = False
        fd, name = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        self.path = Path(name)
        FakeCapture.instances.append(self)

    def start(self) -> None:
        pass

    def snapshot(self) -> tuple[float, float]:
        return 0.5, 0.2

    def stalled(self) -> bool:
        return False

    def process_gone(self) -> bool:
        return False

    def stop(self) -> audio.CaptureResult:
        return audio.CaptureResult(self.path, 0.5, 0.1, 0.2)

    def cancel(self) -> None:
        self.cancelled = True
        self.path.unlink(missing_ok=True)


class AssistantTests(unittest.TestCase):
    def tearDown(self) -> None:
        for capture in FakeCapture.instances:
            capture.path.unlink(missing_ok=True)
        FakeCapture.instances.clear()

    def wait_until(self, predicate, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.02)
        self.fail("timed out waiting for the assistant")

    def test_full_turn(self) -> None:
        LLMHandler.requests.clear()
        LLMHandler.sentences = ["Hello there. ", "How can I help?"]
        TTSHandler.requests.clear()
        FakeCapture.instances.clear()
        notifications: list[tuple[str, str, dict]] = []
        played: list[str] = []

        class TestPlayer(FakePlayer):
            def play(self, path: Path, cancel_event: threading.Event | None = None) -> bool:
                played.append(path.read_bytes().decode())
                return True

        def notifier(message: str, urgency: str = "normal", **kwargs: object) -> None:
            notifications.append((message, urgency, dict(kwargs)))

        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(
                os.environ,
                {
                    "XDG_STATE_HOME": directory,
                    "XDG_CONFIG_HOME": directory,
                    "DICTATE_TTS_API_KEY": "test-key",
                },
            ):
                with FakeHTTPServer(LLMHandler) as llm_server, FakeHTTPServer(TTSHandler) as tts_server:
                    config = config_module.Config(
                        assistant_history_turns=2,
                        llm_base_url=f"{llm_server.base_url}/v1",
                        tts_base_url=f"{tts_server.base_url}/v1",
                        tts_model="mimo",
                        tts_voice="voice",
                    )
                    with mock.patch.object(playback, "Player", TestPlayer):
                        assistant = assistant_module.Assistant(
                            config,
                            capture_factory=FakeCapture,
                            transcriber=lambda path, cfg, cancel=None: "What is the time?",
                            notifier=notifier,
                        )
                        self.assertTrue(assistant.start()["ok"])
                        self.assertEqual(assistant.state, "listening")
                        self.assertTrue(assistant.stop()["ok"])
                        self.wait_until(lambda: assistant.state == "idle" and assistant.reply)
        self.assertEqual(assistant.heard, "What is the time?")
        self.assertEqual(assistant.reply, "Hello there. How can I help?")
        self.assertEqual(len(assistant.history), 2)
        self.assertEqual(len(played), 2)
        self.assertCountEqual(
            [item["body"]["input"] for item in TTSHandler.requests],
            ["Hello there.", "How can I help?"],
        )
        self.assertTrue(any(kwargs.get("title") == "Heard" for _, _, kwargs in notifications))
        self.assertTrue(any(kwargs.get("title") == "Assistant" for _, _, kwargs in notifications))
        replies = [
            message for message, _, kwargs in notifications if kwargs.get("title") == "Assistant"
        ]
        self.assertEqual(replies[-1], "Hello there. How can I help?")
        self.assertEqual(LLMHandler.requests[0]["messages"][1]["content"], "What is the time?")

    def test_no_speech(self) -> None:
        FakeCapture.instances.clear()
        notifications: list[str] = []
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": directory, "XDG_CONFIG_HOME": directory}):
                config = config_module.Config()
                assistant = assistant_module.Assistant(
                    config,
                    capture_factory=FakeCapture,
                    transcriber=lambda *args, **kwargs: "",
                    notifier=lambda message, *args, **kwargs: notifications.append(message),
                )
                assistant.start()
                assistant.stop()
                self.wait_until(lambda: assistant.state == "idle")
        self.assertEqual(assistant.message, "No speech detected.")
        self.assertIn("No speech detected.", notifications)


if __name__ == "__main__":
    unittest.main()
