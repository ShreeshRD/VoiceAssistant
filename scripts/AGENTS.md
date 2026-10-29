# Build and conversion scripts

## Purpose

One-time tooling that builds the CPU-only whisper.cpp ASR runtime and converts the pinned Bark 3.0 source weights into the GGML file the daemon consumes.

## Ownership

Owns `build-asr-linux.sh` and `convert-bark-to-ggml.py`.

## Local Contracts

- `build-asr-linux.sh` clones whisper.cpp at tag `v1.9.5` by default and builds `parakeet-cli` with `GGML_CUDA`, `GGML_VULKAN`, `GGML_METAL`, `GGML_HIP`, and `GGML_SYCL` all `OFF`. Do not enable a GPU backend or remove the CPU-only checks.
- The build output stays under `linux/.dependencies/`, which is gitignored. Do not vendor the whisper.cpp checkout or its binaries.
- `convert-bark-to-ggml.py` never downloads weights. It reads the verified source directory produced by `dictate models download bark-3.0`.
- The converter pins the decoded-state SHA-256, the 721 tensor names, and the expected hyperparameters. A mismatch must abort; never loosen verification to make a conversion succeed.
- NumPy and constriction are conversion-only dependencies and must not be imported by the daemon or CLI. Document the virtual-environment requirement when changing them.
- No model weights, converted files, or third-party binaries are committed.
- Model revisions, sizes, and hashes belong in `linux/models.json`; keep the catalog, converter, and notices aligned.

## Work Guidance

- Preserve `--force` behavior in the build script and the converter's existing CLI flags unless a migration is documented.
- Keep shell scripts `set -euo pipefail` and quote paths.
- When changing a pinned revision, hash, tensor count, or expected file set, update `linux/models.json`, `linux/README.md`, `THIRD_PARTY_NOTICES.md`, and the relevant tests together.
- Prefer clear failure messages over partial output; a conversion or build must not leave a file that looks valid but is not.

## Verification

```sh
bash -n scripts/build-asr-linux.sh
python3 scripts/convert-bark-to-ggml.py --help
./scripts/build-asr-linux.sh                 # rebuilds only when missing
./linux/dictate models verify bark-3.0       # when the model is installed
```

For a rebuilt runtime, confirm `parakeet-cli` links no CUDA/Vulkan/HIP/ROCm/OpenCL libraries and still accepts `-ng`.

## Child DOX Index

None.
