#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
./scripts/prepare-dependencies.sh
swift run CoreChecks
swift run BarkSmallChecks
swift build --product DictateUnlimited
plutil -lint Resources/Info.plist
if rg -n 'Sentry|PostHog|convex\.cloud|onresonant\.com' Sources Resources; then
  echo 'Disallowed source-app telemetry/cloud reference found in product files.' >&2
  exit 1
fi
