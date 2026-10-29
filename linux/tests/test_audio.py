from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
import wave
from array import array
from pathlib import Path
from unittest import mock

from ASR import asr, audio
from ASR.insertion import sanitize_for_typing


def write_wav(path: Path, samples: list[int], rate: int = audio.SAMPLE_RATE) -> None:
    values = array("h", samples)
    if sys.byteorder == "big":
        values.byteswap()
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(values.tobytes())


class AudioMathTests(unittest.TestCase):
    def test_silence(self) -> None:
        rms, peak = audio._pcm_rms(b"\x00\x00" * 1600)
        self.assertEqual(rms, 0.0)
        self.assertEqual(peak, 0.0)

    def test_tone(self) -> None:
        samples = [1000, -1000] * 1600
        values = array("h", samples)
        if sys.byteorder == "big":
            values.byteswap()
        rms, peak = audio._pcm_rms(values.tobytes())
        self.assertAlmostEqual(rms, 1000 / 32768, places=5)
        self.assertAlmostEqual(peak, 1000 / 32768, places=5)

    def test_wav_stats_and_silence_detection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "silence.wav"
            write_wav(path, [0] * audio.SAMPLE_RATE)
            duration, rms, peak = audio.wav_stats(path)
            self.assertAlmostEqual(duration, 1.0, places=3)
            self.assertEqual(rms, 0.0)
            self.assertEqual(peak, 0.0)
            self.assertTrue(asr.is_likely_silent(path, 0.001))

    def test_wav_stats_rejects_wrong_rate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "48k.wav"
            write_wav(path, [0] * 4800, rate=48000)
            with self.assertRaises(audio.AudioError):
                audio.wav_stats(path)


class CaptureIntegrationTests(unittest.TestCase):
    def test_capture_with_fake_pwcat(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "pw-cat"
            fake.write_text(
                "#!/bin/sh\n"
                "head -c 32000 /dev/zero\n"
                "exec sleep 30\n",
                encoding="utf-8",
            )
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            old_path = os.environ.get("PATH", "")
            with mock.patch.dict(os.environ, {"PATH": directory + ":" + old_path}):
                capture = audio.Capture(max_seconds=5)
                capture.start()
                result = capture.stop()
                self.assertAlmostEqual(result.duration, 1.0, places=2)
                self.assertEqual(result.rms, 0.0)
                result.path.unlink(missing_ok=True)


class TypingSanitizerTests(unittest.TestCase):
    def test_newlines_become_spaces(self) -> None:
        self.assertEqual(sanitize_for_typing("hello\nworld\r\nagain"), "hello world again")

    def test_nul_removed(self) -> None:
        self.assertEqual(sanitize_for_typing("\x00hello\x00"), "hello")

    def test_no_enter_is_sent(self) -> None:
        self.assertNotIn("\n", sanitize_for_typing("one\ntwo"))


if __name__ == "__main__":
    unittest.main()
