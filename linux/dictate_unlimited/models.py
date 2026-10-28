"""Local speech-model catalog, downloader and GGML converter (CPU-only)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from . import paths

CATALOG_PATH = Path(__file__).resolve().parent.parent / "models.json"
CHUNK = 1024 * 1024
USER_AGENT = "dictate-unlimited-linux/1.1 (+https://github.com/DanielJD1216/dictate-unlimited)"


class ModelError(RuntimeError):
    pass


def _format_size(size: int) -> str:
    if size >= 1024**3:
        return f"{size / 1024**3:.2f} GB"
    if size >= 1024**2:
        return f"{size / 1024**2:.0f} MB"
    if size >= 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size} B"


@dataclass(frozen=True)
class Source:
    """One pinned upstream file needed to build a model locally."""

    path: str
    url: str
    size: int
    sha256: str

    @property
    def display_size(self) -> str:
        return _format_size(self.size)


@dataclass(frozen=True)
class ModelInfo:
    id: str
    name: str
    file: str
    url: str
    size: int
    sha256: str
    multilingual: bool
    recommended: bool
    description: str
    sources: tuple[Source, ...] = ()
    builder: str = ""
    decoded_sha256: str = ""

    @property
    def is_build(self) -> bool:
        """True when the catalog entry must be assembled from pinned sources."""
        return bool(self.builder)

    @property
    def display_size(self) -> str:
        return _format_size(self.size)

    @property
    def download_size(self) -> int:
        if self.is_build:
            return sum(source.size for source in self.sources)
        return self.size

    @property
    def display_download_size(self) -> str:
        return _format_size(self.download_size)


def catalog() -> list[ModelInfo]:
    try:
        raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelError(f"cannot read model catalog {CATALOG_PATH}: {exc}") from exc
    models: list[ModelInfo] = []
    for item in raw.get("models", []):
        sources = tuple(
            Source(
                path=str(source["path"]),
                url=str(source["url"]),
                size=int(source["size"]),
                sha256=str(source["sha256"]),
            )
            for source in item.get("sources", [])
        )
        info = ModelInfo(
            id=item["id"],
            name=item["name"],
            file=item["file"],
            url=item["url"],
            size=int(item["size"]),
            sha256=str(item.get("sha256", "")),
            multilingual=bool(item.get("multilingual", False)),
            recommended=bool(item.get("recommended", False)),
            description=item.get("description", ""),
            sources=sources,
            builder=str(item.get("builder", "")),
            decoded_sha256=str(item.get("decoded_sha256", "")),
        )
        if info.is_build and not info.sources:
            raise ModelError(f"model {info.id!r} has a builder but no pinned sources")
        models.append(info)
    if not models:
        raise ModelError("model catalog is empty")
    return models


def find(model_id: str) -> ModelInfo:
    for info in catalog():
        if info.id == model_id:
            return info
    raise ModelError(f"unknown model: {model_id}")


def model_path(config, info: ModelInfo | None = None) -> Path:
    if info is not None:
        return config.models_path() / info.file
    value = config.model
    candidate = Path(value).expanduser()
    if candidate.is_absolute() or "/" in value:
        return candidate
    if candidate.suffix == ".bin":
        return config.models_path() / candidate.name
    return config.models_path() / find(value).file


def require_model(config) -> tuple[ModelInfo | None, Path]:
    path = model_path(config)
    if not path.exists():
        info = None
        try:
            info = find(config.model)
        except ModelError:
            pass
        if info is not None:
            raise ModelError(
                f"model {info.id!r} is not installed. Run: dictate models download {info.id}"
            )
        raise ModelError(f"model file not found: {path}")
    if path.stat().st_size <= 0:
        raise ModelError(f"model file is empty: {path}")
    try:
        info = find(config.model)
    except ModelError:
        info = None
    return info, path


def installed(config) -> list[tuple[ModelInfo, Path, bool]]:
    directory = config.models_path()
    rows: list[tuple[ModelInfo, Path, bool]] = []
    for info in catalog():
        path = directory / info.file
        rows.append((info, path, path.is_file()))
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(path: Path, info: ModelInfo) -> None:
    if not path.is_file():
        raise ModelError(f"missing model file: {path}")
    actual = path.stat().st_size
    if actual != info.size:
        raise ModelError(f"size mismatch for {path.name}: expected {info.size}, got {actual}")
    if info.is_build:
        # The locally converted artifact is checked by size only: libm/numpy
        # rounding can change individual bytes across systems, while the
        # converter's pinned decoded-state digest catches decoder drift.
        return
    digest = _sha256(path)
    if digest.lower() != info.sha256.lower():
        raise ModelError(f"sha256 mismatch for {path.name}")


def sources_dir(directory: Path, info: ModelInfo) -> Path:
    return directory / "sources" / info.id


def verify_sources(info: ModelInfo, directory: Path) -> None:
    if not info.is_build:
        return
    base = sources_dir(directory, info)
    for source in info.sources:
        path = base / source.path
        if not path.is_file():
            raise ModelError(f"missing source file: {path}")
        actual = path.stat().st_size
        if actual != source.size:
            raise ModelError(
                f"size mismatch for {source.path}: expected {source.size}, got {actual}"
            )
        if _sha256(path).lower() != source.sha256.lower():
            raise ModelError(f"sha256 mismatch for {source.path}")


Progress = Callable[[int, int], None]
Status = Callable[[str], None]


def _download_file(
    url: str,
    destination: Path,
    size: int,
    sha256: str,
    label: str,
    progress: Progress | None = None,
    force: bool = False,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    if force:
        destination.unlink(missing_ok=True)
        partial.unlink(missing_ok=True)
    elif destination.exists():
        if destination.stat().st_size == size and _sha256(destination).lower() == sha256.lower():
            return destination
        destination.unlink(missing_ok=True)

    offset = partial.stat().st_size if partial.exists() else 0
    if offset > size:
        partial.unlink(missing_ok=True)
        offset = 0

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if offset:
        request.add_header("Range", f"bytes={offset}-")

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status = getattr(response, "status", 200)
            if offset and status != 206:
                offset = 0
                partial.unlink(missing_ok=True)
            total_header = response.headers.get("Content-Length")
            total = offset + int(total_header) if total_header else size
            mode = "ab" if offset else "wb"
            with partial.open(mode) as handle:
                downloaded = offset
                while True:
                    block = response.read(CHUNK)
                    if not block:
                        break
                    handle.write(block)
                    downloaded += len(block)
                    if progress:
                        progress(downloaded, max(total, size))
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ModelError(f"download failed for {label}: {exc}. Partial data kept for resume.") from exc

    if partial.stat().st_size != size:
        raise ModelError(
            f"incomplete download for {label}: expected {size}, got {partial.stat().st_size}"
        )
    digest = _sha256(partial)
    if digest.lower() != sha256.lower():
        partial.unlink(missing_ok=True)
        raise ModelError(f"sha256 mismatch for {label}; the partial file was removed")
    os.replace(partial, destination)
    destination.chmod(0o600)
    return destination


def _builder_path(name: str) -> Path:
    candidate = paths.repo_root() / "scripts" / name
    if not candidate.is_file():
        raise ModelError(f"converter script missing: {candidate}")
    return candidate


def _convert(info: ModelInfo, directory: Path, destination: Path, status: Status | None) -> Path:
    base = sources_dir(directory, info)
    script = _builder_path(info.builder)
    partial = destination.with_name(destination.name + ".part")
    partial.unlink(missing_ok=True)
    if status:
        status(f"converting {info.name} to GGML f16 (this can take several minutes)")
    command = [
        sys.executable,
        str(script),
        "--sources",
        str(base),
        "--out",
        str(partial),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise ModelError(f"cannot start the converter: {exc}") from exc
    if completed.returncode != 0:
        partial.unlink(missing_ok=True)
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        tail = " | ".join(detail[-4:]) if detail else f"exit status {completed.returncode}"
        raise ModelError(f"model conversion failed: {tail}")
    try:
        verify(partial, info)
    except ModelError:
        partial.unlink(missing_ok=True)
        raise
    os.replace(partial, destination)
    destination.chmod(0o600)
    return destination


def download(
    info: ModelInfo,
    directory: Path,
    force: bool = False,
    progress: Progress | None = None,
    status: Status | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / info.file
    if destination.exists() and not force:
        try:
            verify(destination, info)
            return destination
        except ModelError:
            destination.unlink(missing_ok=True)

    if not info.is_build:
        return _download_file(
            info.url,
            destination,
            info.size,
            info.sha256,
            info.id,
            progress,
            force=force,
        )

    base = sources_dir(directory, info)
    for source in info.sources:
        if status:
            status(f"downloading {source.path} ({source.display_size})")
        _download_file(
            source.url,
            base / source.path,
            source.size,
            source.sha256,
            source.path,
            progress,
            force=force,
        )
    return _convert(info, directory, destination, status)


def remove(info: ModelInfo, directory: Path) -> bool:
    removed = False
    destination = directory / info.file
    if destination.exists():
        destination.unlink()
        removed = True
    if info.is_build:
        base = sources_dir(directory, info)
        if base.is_dir():
            shutil.rmtree(base)
            removed = True
    return removed


def custom_models(config) -> Iterable[Path]:
    directory = config.models_path()
    known = {info.file for info in catalog()}
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.glob("*.bin")
        if path.is_file() and path.name not in known and not path.name.endswith(".part")
    )
