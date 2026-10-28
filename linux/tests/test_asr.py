from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from dictate_unlimited import asr, config as config_module


def _fake(directory: Path, body: str) -> Path:
    path = directory / "parakeet-cli"
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


class ASRTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        (self.root / "model.bin").write_bytes(b"model")
        self.audio = self.root / "sample.raw"
        self.audio.write_bytes(b"pcm")
        self.config = config_module.Config(
            model="model.bin",
            models_dir=str(self.root),
            silence_rms=0.0,
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_transcribe_returns_stdout_text(self) -> None:
        self.config.asr_bin = str(
            _fake(
                self.root,
                'if [ "$1" = "--help" ]; then echo "  -ng, --no-gpu"; exit 0; fi\n'
                'echo "hello from bark"\n',
            )
        )
        self.assertEqual(asr.transcribe(self.audio, self.config), "hello from bark")

    def test_transcribe_reports_error_when_stdout_is_empty(self) -> None:
        self.config.asr_bin = str(
            _fake(
                self.root,
                'if [ "$1" = "--help" ]; then echo "  -ng, --no-gpu"; exit 0; fi\n'
                'echo "error: failed to load model" >&2\n',
            )
        )
        with self.assertRaises(asr.ASRError) as raised:
            asr.transcribe(self.audio, self.config)
        self.assertIn("failed to load model", str(raised.exception))

    def test_configured_binary_must_be_executable(self) -> None:
        binary = self.root / "not-executable"
        binary.write_text("#!/bin/sh\n", encoding="utf-8")
        self.config.asr_bin = str(binary)
        with self.assertRaises(asr.ASRError):
            asr.find_asr(self.config)
        self.assertFalse(os.access(binary, os.X_OK))


if __name__ == "__main__":
    unittest.main()
