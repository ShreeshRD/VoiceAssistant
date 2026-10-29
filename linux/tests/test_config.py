from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ASR import config as config_module


class ConfigTests(unittest.TestCase):
    def test_defaults_validate(self) -> None:
        config = config_module.Config()
        config.validate()
        self.assertEqual(config.model, "bark-3.0")
        self.assertEqual(config.asr_bin, "")
        self.assertEqual(config_module.effective_threads(config), 4)
        self.assertTrue(config.trailing_space)

    def test_set_value_types(self) -> None:
        config = config_module.Config()
        config = config_module.set_value(config, "notifications", "false")
        self.assertFalse(config.notifications)
        config = config_module.set_value(config, "threads", "6")
        self.assertEqual(config.threads, 6)
        config = config_module.set_value(config, "silence_rms", "0.02")
        self.assertAlmostEqual(config.silence_rms, 0.02)
        config = config_module.set_value(config, "asr_bin", "/opt/parakeet-cli")
        self.assertEqual(config.asr_bin, "/opt/parakeet-cli")
        config = config_module.set_value(config, "trailing_space", "false")
        self.assertFalse(config.trailing_space)

    def test_invalid_values(self) -> None:
        config = config_module.Config()
        with self.assertRaises(config_module.ConfigError):
            config_module.set_value(config, "threads", "0")
        with self.assertRaises(config_module.ConfigError):
            config_module.set_value(config, "insertion", "magic")
        with self.assertRaises(config_module.ConfigError):
            config_module.set_value(config, "unknown", "1")
        with self.assertRaises(config_module.ConfigError):
            config_module.Config(trailing_space="yes").validate()

    def test_roundtrip_ignores_unknown_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "model": "bark-3.0",
                        "threads": 2,
                        # Removed Whisper-era keys must be ignored, not fatal.
                        "language": "ko",
                        "beam_size": 5,
                        "whisper_bin": "/usr/bin/whisper-cli",
                        "future_key": 1,
                    }
                ),
                encoding="utf-8",
            )
            config = config_module.load(path)
            self.assertEqual(config.model, "bark-3.0")
            self.assertEqual(config.threads, 2)
            config_module.save(config, path)
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("language", raw)
            self.assertNotIn("beam_size", raw)
            self.assertNotIn("whisper_bin", raw)
            self.assertNotIn("future_key", raw)

    def test_legacy_whisper_model_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            for legacy in ("base", "ggml-large-v3.bin"):
                path.write_text(json.dumps({"model": legacy}), encoding="utf-8")
                config = config_module.load(path)
                self.assertEqual(config.model, "bark-3.0")

    def test_corrupt_config_reports_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaises(config_module.ConfigError):
                config_module.load(path)

    def test_models_path_override(self) -> None:
        config = config_module.Config(models_dir="~/models")
        self.assertEqual(config.models_path(), Path("~/models").expanduser())


if __name__ == "__main__":
    unittest.main()
