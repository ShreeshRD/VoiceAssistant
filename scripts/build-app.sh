#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
./scripts/prepare-dependencies.sh
swift build -c release --product DictateUnlimited
BIN="$(swift build -c release --show-bin-path)"
mkdir -p dist
STAGE=$(mktemp -d "$PWD/dist/.package.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT
APP="$STAGE/Dictate Unlimited.app"
FINAL="$PWD/dist/Dictate Unlimited.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN/DictateUnlimited" "$APP/Contents/MacOS/DictateUnlimited"
# Only the dictation catalog and ZIPFoundation privacy manifest are needed.
# FluidAudio's LuxTTS resources carry separate terms and are not used by this app.
for name in DictateUnlimited_DictateCore.bundle ZIPFoundation_ZIPFoundation.bundle; do
  [ -d "$BIN/$name" ] || { echo "Missing required resource bundle: $name" >&2; exit 1; }
  cp -R "$BIN/$name" "$APP/Contents/Resources/"
done
cp -R Resources/Notices "$APP/Contents/Resources/"
cp Sources/BarkSmall/ATTRIBUTION.md "$APP/Contents/Resources/Notices/BarkSmall-ATTRIBUTION.md"
cp LICENSE THIRD_PARTY_NOTICES.md "$APP/Contents/Resources/"
cp Resources/Info.plist "$APP/Contents/Info.plist"
codesign --force --sign - "$APP"
codesign --verify --deep --strict "$APP"
BACKUP="$STAGE/previous.app"
if [ -e "$FINAL" ]; then mv "$FINAL" "$BACKUP"; fi
if ! mv "$APP" "$FINAL"; then
  if [ -e "$BACKUP" ]; then mv "$BACKUP" "$FINAL"; fi
  exit 1
fi
printf '%s\n' "$FINAL"
