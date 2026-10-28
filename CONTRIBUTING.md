# Contributing

V1.1 development adds multilingual Whisper small/Turbo and compatible local imports
to the three pinned Bark models. Keep changes
focused on recognition, safe text insertion, model management and native feedback.
Accounts, cloud inference, analytics, meetings, voice memos and agent integrations
are outside scope.

Use Apple Silicon, macOS 15+ and a Swift 6.2 toolchain. See README.md for setup.
Run `scripts/check-local.sh`, `scripts/check-session.sh` and
`scripts/check-model-store.sh`; run `swift test` with
full Xcode. Recognition changes also need offline model/audio comparisons. Do not
replace a model, precision or backend silently. Preserve checksum validation and
all notices listed in docs/LICENSING.md.

For bug reports, include app revision, OS/toolchain, model, minimal steps and the
observed error. Use synthetic text/audio. Do not attach private recordings, full
user documents, credentials or personal logs. A changed target or an ambiguous
write must never trigger a blind insertion retry.

Use the [issue tracker](https://github.com/DanielJD1216/dictate-unlimited/issues) for
reproducible bugs and scoped feature proposals. Pull requests are welcome. Include
the checks you ran and any known limits. Also run `scripts/check-correction-store.sh`
and `scripts/check-clipboard.sh` when changing their respective paths.
