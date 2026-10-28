#!/usr/bin/env python3
"""Fetch pinned WhisperKit manifests and optionally download verified local QA models.

Explicit acquisition only. Uses curl's normal TLS verification. No inference, remote
code execution, or changes to the user's installed model directories.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "argmaxinc/whisperkit-coreml"
REVISION = "0f63a7800b00dd0226abd051b906c246e1907482"
VARIANTS = [
    ("whisper-small", "Whisper small", "openai_whisper-small", "Core ML FP16 multilingual", "openai/whisper-small", "973afd24965f72e36ca33b3055d56a652f456b4d"),
    ("whisper-turbo", "Whisper Turbo", "openai_whisper-large-v3-v20240930_626MB", "Core ML compressed multilingual · 626MB variant", "openai/whisper-large-v3-turbo", "41f01f3fe87f28c78e2fbf8b568835947dd65ed9"),
]
TOKENIZER_FILES = ("tokenizer.json", "tokenizer_config.json", "special_tokens_map.json")


def fetch(url, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["curl", "--fail", "--location", "--silent", "--show-error", "--retry", "2", "--max-time", "600", url, "--output", str(target)], check=True)


def get_bytes(url):
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "response"
        fetch(url, path)
        return path.read_bytes()


def source_url(repository, revision, path):
    return f"https://huggingface.co/{repository}/resolve/{revision}/{quote(path, safe='/')}"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def build_catalog():
    models = []
    for identifier, name, folder, precision, tokenizer_repo, tokenizer_rev in VARIANTS:
        tree_url = f"https://huggingface.co/api/models/{REPOSITORY}/tree/{REVISION}/{folder}?recursive=true&limit=1000"
        tree = json.loads(get_bytes(tree_url))
        if len(tree) >= 1000:
            raise ValueError("Pinned tree exceeds single-page limit; review pagination")
        files = []
        for item in tree:
            if item["type"] != "file":
                continue
            path = item["path"].removeprefix(folder + "/")
            if path == item["path"] or ".." in path.split("/"):
                raise ValueError("Unexpected manifest path")
            if not (path.startswith(("AudioEncoder.mlmodelc/", "MelSpectrogram.mlmodelc/", "TextDecoder.mlmodelc/")) or path in ("config.json", "generation_config.json")):
                raise ValueError(f"Unexpected pinned artifact: {path}")
            sha = item.get("lfs", {}).get("oid")
            if sha is None:
                data = get_bytes(source_url(REPOSITORY, REVISION, item["path"]))
                if len(data) != item["size"]:
                    raise ValueError(f"Metadata size mismatch: {path}")
                sha = hashlib.sha256(data).hexdigest()
            files.append({"path": path, "size": item["size"], "sha256": sha})
        for path in TOKENIZER_FILES:
            data = get_bytes(source_url(tokenizer_repo, tokenizer_rev, path))
            files.append({"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                          "sourceRepository": tokenizer_repo, "sourceRevision": tokenizer_rev, "sourcePath": path})
        models.append({"id": identifier, "name": name, "repository": REPOSITORY, "revision": REVISION,
                       "prefix": folder + "/", "precision": precision, "files": files})
    return models


def download(models, destination):
    def acquire(job):
        model, entry = job
        path = destination / (model["id"] + "-" + model["revision"]) / entry["path"]
        if path.exists() and path.stat().st_size == entry["size"] and digest(path) == entry["sha256"]:
            return
        url = source_url(entry.get("sourceRepository", model["repository"]), entry.get("sourceRevision", model["revision"]), entry.get("sourcePath", model["prefix"] + entry["path"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".partial")
        try:
            fetch(url, temporary)
            if temporary.stat().st_size != entry["size"] or digest(temporary) != entry["sha256"]:
                raise ValueError(f"Integrity check failed: {entry['path']}")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(acquire, [(model, entry) for model in models for entry in model["files"]]))
    for model in models:
        (destination / (model["id"] + "-" + model["revision"]) / ".complete").write_text(model["revision"])
        print(f"Verified {model['id']}: {sum(f['size'] for f in model['files'])} bytes", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-root", type=Path, help="Explicit destination for verified test model folders")
    parser.add_argument("--use-existing", action="store_true", help="Use the checked-in pinned catalog instead of regenerating it")
    args = parser.parse_args()
    catalog_path = ROOT / "Sources/DictateCore/Resources/whisper-models.json"
    models = json.loads(catalog_path.read_text()) if args.use_existing else build_catalog()
    if not args.use_existing:
        catalog_path.write_text(json.dumps(models, indent=2) + "\n")
        print(f"Wrote {len(models)} pinned Whisper entries", flush=True)
    if args.download_root:
        download(models, args.download_root.resolve())
