# Source preview release

V1.1 is a source-only preview. Build it locally using the README.
No signed/notarized app binary or model weights are distributed. App metadata is
0.2.0 (build 2); the source preview tag is `v0.2.0-preview.1`.

## Scope and checks

Includes three pinned Bark models plus Whisper small and Turbo, language selection,
compatible local imports, microphone readiness and selection, configurable
tap/hold shortcuts, safe text delivery, paste-last recovery, a local dictionary,
and notch/floating feedback. Local tests and physical user checks are summarized in
[TESTING.md](TESTING.md). All five catalog models passed packaged local inference checks;
Bark Download/Repair and clean dependency acquisition were tested on the existing Mac.
Whisper artifacts were acquired and hash-verified; offline inference and GUI import
were tested. The complete real Whisper Download/Repair GUI flow has not been rerun.
A fresh second Mac, broad hardware coverage, and hosted CI remain unverified.

## Source packaging

The public repository starts from an allowlisted source snapshot, not the private
working history. It excludes model weights, recordings, transcripts, user preferences,
local analysis evidence, source-app artifacts, build caches and local notes.

```sh
python3 scripts/export-preview.py /absolute/path/to/new-preview.tar.gz
```

The exporter refuses an existing output and writes an adjacent per-file SHA-256
manifest. It accepts only reviewed source types and three explicitly named images.
Images must be visually inspected for personal information before publication.
Exporting is not publishing. Preserve licences and attribution in derivative builds.

## Binary release remains separate

A downloadable app still needs stable distribution signing, notarization, and a
clean downloaded-install/permission test. See [signing preparation](SIGNING-NOTARIZATION.md).
Source release does not claim these checks passed.

## Follow-up and withdrawal

Report reproducible issues through the GitHub issue tracker using synthetic examples.
For a broken tagged preview, document the issue and publish a corrected version.
Do not silently replace a tagged source artifact. There is no automatic update service.
