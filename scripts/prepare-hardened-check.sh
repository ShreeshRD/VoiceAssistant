#!/bin/bash
# Local, ad-hoc Hardened Runtime diagnostic copy. Never submits or purchases anything.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "$#" -ne 2 ]; then echo 'Usage: prepare-hardened-check.sh INPUT.app NEW-OUTPUT.app' >&2; exit 2; fi
INPUT=$1
OUTPUT=$2
[ -d "$INPUT/Contents/MacOS" ] || { echo 'Input app bundle missing' >&2; exit 2; }
[ ! -e "$OUTPUT" ] || { echo 'Output already exists; choose a new path' >&2; exit 2; }
plutil -lint Resources/Distribution.entitlements.plist
/usr/bin/ditto "$INPUT" "$OUTPUT"
codesign --force --sign - --options runtime --timestamp=none \
  --entitlements Resources/Distribution.entitlements.plist "$OUTPUT"
codesign --verify --deep --strict "$OUTPUT"
codesign --display --verbose=4 "$OUTPUT"
echo 'Local ad-hoc diagnostic only. Not Developer ID-signed or notarized.'
