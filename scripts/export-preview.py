"""Create a source-only preview with an explicit allowlist; never publish or use network."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
FILES = [".gitignore", ".gitattributes", "LICENSE", "THIRD_PARTY_NOTICES.md",
         "README.md", "CONTRIBUTING.md", "CHANGELOG.md", "Package.swift", "Package.resolved"]
DIRS = ["Sources", "Resources", "Tests", "scripts", "docs", ".github"]
SUFFIXES = {".swift", ".json", ".plist", ".md", ".txt", ".sh", ".py"}
IMAGES = {
    "docs/images/hero.png": b"\x89PNG\r\n\x1a\n",
    "docs/images/models.jpg": b"\xff\xd8\xff",
    "docs/images/appearance.jpg": b"\xff\xd8\xff",
}

def export(destination: Path):
    manifest_path = destination.with_name(destination.name + ".manifest.json")
    if destination.exists() or manifest_path.exists():
        raise SystemExit("Output or manifest already exists; choose a new destination")
    paths = [ROOT / name for name in FILES]
    for name in DIRS:
        for path in (ROOT / name).rglob("*"):
            if path.is_symlink():
                raise SystemExit(f"Refusing symbolic link: {path.relative_to(ROOT)}")
            if path.is_file():
                if str(path.relative_to(ROOT)) not in IMAGES and path.suffix not in SUFFIXES and path.name not in {"NOTICE", "conversion-LICENSE", "mattmireles-LICENSE"}:
                    raise SystemExit(f"Review unexpected file: {path.relative_to(ROOT)}")
                paths.append(path)
    members = {}
    for path in sorted(paths):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
            raise SystemExit(f"Refusing missing, linked or oversized source: {path}")
        data = path.read_bytes()
        name = str(path.relative_to(ROOT))
        if name in IMAGES:
            if not data.startswith(IMAGES[name]):
                raise SystemExit(f"Invalid image signature: {name}")
        else:
            data.decode("utf-8")
            if (b"/" + b"Users/") in data:
                raise SystemExit(f"Review personal absolute path: {name}")
        members[str(path.relative_to(ROOT))] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    with destination.open("xb") as output:
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            for name in sorted(members):
                path = ROOT / name
                data = path.read_bytes()
                if hashlib.sha256(data).hexdigest() != members[name]["sha256"]:
                    raise SystemExit(f"Source changed during export: {name}")
                info = tarfile.TarInfo("dictate-unlimited/" + name)
                info.size = len(data)
                info.mode = 0o755 if path.suffix == ".sh" else 0o644
                info.mtime = 0
                archive.addfile(info, io.BytesIO(data))
    record = {"artifact_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "files": members}
    with manifest_path.open("x") as output:
        json.dump(record, output, indent=2); output.write("\n")
    print(f"Exported {len(members)} source files; SHA256 {record['artifact_sha256']}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    export(parser.parse_args().output.resolve())
