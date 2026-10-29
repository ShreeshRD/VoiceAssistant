# Third-party notices

Original Speech Flow code and the Linux port under `linux/` are MIT,
copyright 2026 DOO MADE. Third-party components and model weights retain their
own licences.

## Runtime and models

- **whisper.cpp / ggml**: MIT, copyright 2023–2026 The ggml authors. The port
  builds tag `v1.9.5` from `https://github.com/ggerganov/whisper.cpp` with all
  GPU backends disabled and uses its `parakeet-cli`. See
  `scripts/build-asr-linux.sh`.
- **Bark 3.0**: Conway Research / Underdog, derived from NVIDIA Parakeet TDT v3
  and Moondream; CC BY 4.0. The Linux catalog in `linux/models.json` pins the
  five upstream files at revision
  `85db2ad18ab41e534a222ee253c29191d77ed919` from
  `https://huggingface.co/ConwayResearch/Underdog-Bark-3.0`, including their
  sizes and SHA-256 hashes. The upstream NOTICE is downloaded alongside them.
  Weights are not included in this repository.
- **NumPy** (BSD-3-Clause and bundled licences) and **constriction**
  (MIT OR Apache-2.0 OR BSL-1.0) are used only by the one-time Bark conversion
  in `scripts/convert-bark-to-ggml.py`. They are not vendored and are not
  imported by the daemon or CLI.

No third-party Python packages, model files, or binaries are vendored. The
built whisper.cpp checkout and downloaded or converted models stay in ignored
local directories (`linux/.dependencies/`) or in the user's XDG data directory.

## External services

The optional assistant can call a user-configured OpenAI-compatible LLM service
and TTS service (for example MiMo). Those services are not bundled or
redistributed by this project, and their terms and privacy policies apply to
the text sent to them.

Model quality, speed, and output equivalence to other Bark runtimes are not
claimed. Imported third-party models remain under their own licences.
