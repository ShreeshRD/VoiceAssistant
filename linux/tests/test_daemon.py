from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from ASR import asr, audio, config as config_module, corrections
from ASR.daemon import Engine
from ASR.insertion import DeliveryResult


class FakeCapture:
    instances: list["FakeCapture"] = []

    def __init__(self, source: str = "", max_seconds: int = 300):
        self.source = source
        self.max_seconds = max_seconds
        self.cancelled = False
        self.stopped = False
        self.seconds = 1.0
        self.rms = 0.1
        fd, name = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        self.path = Path(name)
        FakeCapture.instances.append(self)

    def start(self) -> None:
        pass

    def snapshot(self) -> tuple[float, float]:
        return self.seconds, 0.1

    def stalled(self) -> bool:
        return False

    def process_gone(self) -> bool:
        return False

    def stop(self) -> audio.CaptureResult:
        self.stopped = True
        return audio.CaptureResult(self.path, self.seconds, self.rms, 0.2)

    def cancel(self) -> None:
        self.cancelled = True
        self.path.unlink(missing_ok=True)


class FakeParakeet:
    def __init__(self, directory: Path):
        self.path = directory / "parakeet-cli"
        self.path.write_text(
            "#!/bin/sh\n"
            'echo "usage: parakeet-cli [options] file0 file1 ..."\n'
            'echo "  -t N,   --threads N         [4      ] number of threads"\n'
            'echo "  -m,     --model FILE        [       ] model path"\n'
            'echo "  -f,     --file FILE         [       ] input audio file"\n'
            'echo "  -ng,    --no-gpu            [false  ] disable GPU"\n',
            encoding="utf-8",
        )
        self.path.chmod(0o755)


class DaemonEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        FakeCapture.instances.clear()
        self.asr = FakeParakeet(self.root)
        self.store = corrections.CorrectionStore(self.root / "corrections.json")
        self.store.add("map", "Mac")
        self.config = config_module.Config(
            model="bark-3.0",
            models_dir=str(self.root / "models"),
            notifications=False,
            keep_audio=False,
        )
        self.transcript = "hello map"
        self.deliveries: list[str] = []

        def transcriber(path, config, cancel_event=None):
            self.assertIsNotNone(path)
            return self.transcript

        def deliverer(text, config):
            self.deliveries.append(text)
            return DeliveryResult(True, "fake", "delivered")

        self.engine = Engine(
            self.config,
            self.store,
            capture_factory=FakeCapture,
            transcriber=transcriber,
            deliverer=deliverer,
            notifier=lambda *args, **kwargs: None,
            model_resolver=lambda cfg: (None, self.root / "model.bin"),
            asr_finder=lambda cfg: self.asr.path,
        )

    def tearDown(self) -> None:
        self.engine.request_shutdown()
        for capture in FakeCapture.instances:
            capture.path.unlink(missing_ok=True)
        self.directory.cleanup()

    def wait_until(self, predicate, timeout: float = 2.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("timed out waiting for daemon state")

    def test_record_transcribe_correct_and_deliver(self) -> None:
        self.assertTrue(self.engine.start()["ok"])
        self.assertEqual(self.engine.state, "recording")
        self.assertTrue(self.engine.stop()["ok"])
        self.wait_until(lambda: self.engine.state == "idle")
        self.assertEqual(self.engine.last_transcript, "hello Mac")
        self.assertEqual(self.deliveries, ["hello Mac"])
        self.assertTrue(FakeCapture.instances[-1].stopped)

    def test_cancel_recording(self) -> None:
        self.assertTrue(self.engine.start()["ok"])
        self.assertTrue(self.engine.cancel()["ok"])
        self.assertEqual(self.engine.state, "idle")
        self.assertTrue(FakeCapture.instances[-1].cancelled)
        self.assertEqual(self.engine.last_transcript, "")

    def test_empty_transcript(self) -> None:
        self.transcript = ""
        self.assertTrue(self.engine.start()["ok"])
        self.assertTrue(self.engine.stop()["ok"])
        self.wait_until(lambda: self.engine.state == "idle")
        self.assertEqual(self.engine.last_transcript, "")
        self.assertEqual(self.deliveries, [])

    def test_paste_last(self) -> None:
        self.engine.last_transcript = "last words"
        self.assertTrue(self.engine.paste_last()["ok"])
        self.wait_until(lambda: self.engine.state == "idle")
        self.assertEqual(self.deliveries, ["last words"])

    def test_toggle(self) -> None:
        self.assertTrue(self.engine.toggle()["ok"])
        self.assertEqual(self.engine.state, "recording")
        self.assertTrue(self.engine.toggle()["ok"])
        self.wait_until(lambda: self.engine.state == "idle")
        self.assertEqual(self.deliveries, ["hello Mac"])

    def test_start_without_gpu_flag_is_refused(self) -> None:
        bad = self.root / "bad-parakeet"
        bad.write_text("#!/bin/sh\necho '--help without the flag'\n", encoding="utf-8")
        bad.chmod(0o755)
        engine = Engine(
            self.config,
            self.store,
            capture_factory=FakeCapture,
            notifier=lambda *args, **kwargs: None,
            model_resolver=lambda cfg: (None, self.root / "model.bin"),
            asr_finder=lambda cfg: bad,
        )
        response = engine.start()
        self.assertFalse(response["ok"])
        self.assertIn("no-gpu", response["message"])


if __name__ == "__main__":
    unittest.main()
