# Third-party notices

Original Dictate Unlimited application code is MIT, copyright 2026 DOO MADE.
Third-party components and model weights retain their own licenses.

- Bark 3.0, Plus and Pro: Conway Research / Underdog; derived from NVIDIA
  Parakeet TDT v3 and Moondream. CC BY 4.0. See Resources/Notices/Bark-NOTICE.txt
  and Bark-CC-BY-4.0.txt. Exact model revisions/files/hashes are in
  Sources/DictateCore/Resources/models.json.
- Sources/BarkSmall adapts the published Bark NumPy/Core ML reference algorithm
  into Swift/Accelerate. It is separately attributed under CC BY 4.0; see its
  ATTRIBUTION.md. Changes: native Swift array/archive handling, FFT, LSTM/TDT,
  persistent Core ML cache and bounded local segmentation. No Resonant code used.
- FluidAudio: Apache-2.0. Pinned revision `a00964e1aa8eff99c4bce80bc9c8ff2d4dd1568d` in scripts/prepare-dependencies.sh; full notice in
  Resources/Notices/FluidAudio-LICENSE.txt. Pro adapter uses its public ASR API
  following the Conway Research reference runner.
- ZIPFoundation: MIT. Exact version 0.9.19; retain its package LICENSE when
  distributing. See Package.resolved for resolved package identity.

Model cards advertise original MLX/BF16 sizes. This app downloads separate Core ML
exports, labels the actual bytes, and does not claim BF16 inference for Pro's FP16
Core ML export. It makes no benchmark-equivalence claim.

FluidAudio includes third-party implementations. Its pinned third-party notices
are retained in Resources/Notices/FluidAudio-ThirdParty/, including fastcluster
(BSD-2-Clause), VBx (Apache-2.0), and G2P provenance. Keeping these notices does
not imply that this app exposes those features or bundles their model/data files.
NeMo text processing is disabled through `traits: []` with Swift 6.2. LuxTTS
lexicon/auxiliary data is deliberately excluded from the packaged application.
No third-party model weights are included in the source preview or app bundle.

The BarkSmall adaptation notice is also copied into the app's Notices directory.
See docs/LICENSING.md for file scope and the offline audit boundary.

## Whisper additions (V1.1 development)

- OpenAI Whisper small and large-v3-turbo weights/tokenizers: MIT. Exact upstream
  revisions and SHA-256 hashes are in Sources/DictateCore/Resources/whisper-models.json.
  Core ML exports are from Argmax's whisperkit-coreml repository, revision
  0f63a7800b00dd0226abd051b906c246e1907482. Turbo is explicitly the compressed
  626MB export; runtime equivalence to uncompressed benchmarks is not claimed.
- WhisperKit / ArgmaxCore: MIT, pinned commit
  1bbc57cb7fe6410248a685b1c5a3c6d56adc2ed4. Retain Resources/Notices/WhisperKit-LICENSE.txt
  and WhisperKit-NOTICES.txt, which includes Apache-2.0 swift-transformers-derived code.
  WhisperRecognition.swift adapts its tokenizer wrapper to remove remote fallback.
- swift-argument-parser is a resolved dependency used by upstream command-line
  targets, not linked by this app's WhisperKit library target.
- Imported models retain their own licences; the app does not relicense user imports.

## Linux port additions

The Linux port under `linux/` is original code, MIT licensed like the rest of
this repository, and uses only the Python standard library at runtime.

- whisper.cpp / ggml: MIT, copyright 2023–2026 The ggml authors. The port builds
  tag `v1.9.5` from `https://github.com/ggerganov/whisper.cpp` with all GPU
  backends disabled and uses its `parakeet-cli`. See
  `scripts/build-asr-linux.sh`.
- Bark 3.0: Conway Research / Underdog, derived from NVIDIA Parakeet TDT v3 and
  Moondream; CC BY 4.0. The Linux catalog in `linux/models.json` pins the five
  upstream files at revision `85db2ad18ab41e534a222ee253c29191d77ed919` from
  `https://huggingface.co/ConwayResearch/Underdog-Bark-3.0`, including their
  sizes and SHA-256 hashes. The upstream NOTICE is downloaded alongside them.
  Weights are not included in this repository.
- The local converter (`scripts/convert-bark-to-ggml.py`) needs NumPy
  (BSD-3-Clause and bundled licenses) and constriction
  (MIT OR Apache-2.0 OR BSL-1.0). They are used only for the one-time model
  conversion, are not vendored, and are not imported by the daemon or CLI.
- No third-party Python packages, model files, or binaries are vendored. The
  built whisper.cpp checkout and downloaded/converted models stay in ignored
  local directories (`linux/.dependencies/`) or in the user's XDG data
  directory.

Model quality, speed, and output equivalence to other Bark runtimes are not
claimed. Imported third-party models remain under their own licences.
