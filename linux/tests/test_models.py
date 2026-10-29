from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from ASR import config as config_module
from ASR import models


class CatalogTests(unittest.TestCase):
    def test_catalog_is_valid(self) -> None:
        catalog = models.catalog()
        self.assertGreater(len(catalog), 0)
        ids = [info.id for info in catalog]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(any(info.recommended for info in catalog))
        for info in catalog:
            self.assertGreater(info.size, 0)
            self.assertTrue(info.url.startswith("https://"))
            self.assertTrue(info.file.endswith(".bin"))
            if info.is_build:
                self.assertTrue(info.builder.endswith(".py"))
                self.assertGreater(len(info.sources), 0)
                self.assertEqual(len(info.decoded_sha256), 64)
                for source in info.sources:
                    self.assertGreater(source.size, 0)
                    self.assertEqual(len(source.sha256), 64)
                    self.assertTrue(source.url.startswith("https://"))
            else:
                self.assertEqual(len(info.sha256), 64)

    def test_find(self) -> None:
        info = models.find("bark-3.0")
        self.assertEqual(info.id, "bark-3.0")
        self.assertTrue(info.is_build)
        self.assertFalse(info.multilingual)
        self.assertEqual(info.download_size, sum(source.size for source in info.sources))
        with self.assertRaises(models.ModelError):
            models.find("nope")

    def test_model_paths(self) -> None:
        config = config_module.Config(models_dir="/tmp/dictate-models")
        self.assertEqual(
            models.model_path(config),
            Path("/tmp/dictate-models/bark-3.0-ggml-f16.bin"),
        )
        config.model = "ggml-custom.bin"
        self.assertEqual(models.model_path(config), Path("/tmp/dictate-models/ggml-custom.bin"))
        config.model = "/absolute/model.bin"
        self.assertEqual(models.model_path(config), Path("/absolute/model.bin"))


class VerifyTests(unittest.TestCase):
    def test_verify_size_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.bin"
            path.write_bytes(b"hello bark")
            info = models.ModelInfo(
                id="test",
                name="test",
                file="model.bin",
                url="https://example.invalid/model.bin",
                size=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                multilingual=False,
                recommended=False,
                description="",
            )
            models.verify(path, info)
            info_bad = models.ModelInfo(**{**info.__dict__, "sha256": "0" * 64})
            with self.assertRaises(models.ModelError):
                models.verify(path, info_bad)

    def test_build_model_is_verified_by_size_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bark.bin"
            path.write_bytes(b"converted")
            info = models.ModelInfo(
                id="build",
                name="build",
                file="bark.bin",
                url="https://example.invalid/repo",
                size=path.stat().st_size,
                sha256="",
                multilingual=False,
                recommended=True,
                description="",
                builder="convert-bark-to-ggml.py",
                sources=(
                    models.Source(
                        path="source.bin",
                        url="https://example.invalid/source.bin",
                        size=3,
                        sha256="0" * 64,
                    ),
                ),
            )
            models.verify(path, info)
            path.write_bytes(b"too long")
            with self.assertRaises(models.ModelError):
                models.verify(path, info)

    def test_verify_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sources" / "build" / "model.bark"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"abc")
            info = models.ModelInfo(
                id="build",
                name="build",
                file="bark.bin",
                url="https://example.invalid/repo",
                size=1,
                sha256="",
                multilingual=False,
                recommended=True,
                description="",
                builder="convert-bark-to-ggml.py",
                sources=(
                    models.Source(
                        path="model.bark",
                        url="https://example.invalid/model.bark",
                        size=3,
                        sha256=hashlib.sha256(b"abc").hexdigest(),
                    ),
                ),
            )
            models.verify_sources(info, root)
            source.write_bytes(b"abd")
            with self.assertRaises(models.ModelError):
                models.verify_sources(info, root)


if __name__ == "__main__":
    unittest.main()
