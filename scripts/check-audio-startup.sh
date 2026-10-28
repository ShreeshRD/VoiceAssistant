#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
swift build --product CoreChecks
BIN=$(swift build --show-bin-path)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
swiftc -swift-version 5 -parse-as-library -I "$BIN/Modules" \
  Sources/DictateUnlimited/AudioCapture.swift Tests/AudioStartupChecks/main.swift \
  "$BIN"/DictateCore.build/*.swift.o -o "$TMP/AudioStartupChecks"
"$TMP/AudioStartupChecks"
