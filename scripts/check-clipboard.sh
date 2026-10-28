#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
swiftc -swift-version 5 -parse-as-library Sources/DictateUnlimited/ClipboardLease.swift \
  Tests/ClipboardChecks/ClipboardChecks.swift -o "$TMP/ClipboardChecks"
"$TMP/ClipboardChecks"
