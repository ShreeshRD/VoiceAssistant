#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
REV=a00964e1aa8eff99c4bce80bc9c8ff2d4dd1568d
EXPECTED=cacfce5a8cb5cdb6b4046fb2968fee8c1971824476ab9c4ce1434603632026af
DEST=.dependencies/FluidAudio
if [ -d "$DEST" ]; then
  [ "$(cat "$DEST/.pinned-revision" 2>/dev/null)" = "$REV" ] || { echo 'Existing FluidAudio source is not marked with the expected revision; inspect it before changing dependencies.' >&2; exit 1; }
  exit 0
fi
mkdir -p .dependencies
TMP=$(mktemp -d "$PWD/.dependencies/download.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
curl -fL --retry 2 --max-time 180 "https://codeload.github.com/FluidInference/FluidAudio/tar.gz/$REV" -o "$TMP/source.tar.gz"
ACTUAL=$(shasum -a 256 "$TMP/source.tar.gz" | awk '{print $1}')
[ "$ACTUAL" = "$EXPECTED" ] || { echo 'FluidAudio archive checksum mismatch.' >&2; exit 1; }
mkdir "$TMP/source"
tar -xzf "$TMP/source.tar.gz" --strip-components=1 -C "$TMP/source"
printf '%s\n' "$REV" > "$TMP/source/.pinned-revision"
mv "$TMP/source" "$DEST"
