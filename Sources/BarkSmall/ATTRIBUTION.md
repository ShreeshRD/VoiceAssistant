# BarkSmall runtime provenance

`Frontend.swift`, `Decoder.swift`, and the inference orchestration in `SmallBarkRecognizer.swift` adapt the algorithm in Conway Research's `coreml/ane/bark_coreml.py`, licensed CC-BY-4.0. This adaptation replaces NumPy/Core ML Python execution with Swift, Accelerate and Core ML, adds validation and cancellation, and reads only locally supplied artifacts. This is third-party-derived runtime code, separately attributed from the MIT application shell.

Source revision: ConwayResearch/Underdog-Bark-3.0-Plus `d4fab2f8b95681e5ad3cfb4e8c5f4e0c009b3deb`.

- Source: https://huggingface.co/ConwayResearch/Underdog-Bark-3.0-Plus/blob/d4fab2f8b95681e5ad3cfb4e8c5f4e0c009b3deb/coreml/ane/bark_coreml.py
- License: https://creativecommons.org/licenses/by/4.0/
- Source LICENSE: https://huggingface.co/ConwayResearch/Underdog-Bark-3.0-Plus/blob/d4fab2f8b95681e5ad3cfb4e8c5f4e0c009b3deb/coreml/LICENSE
- Source NOTICE: https://huggingface.co/ConwayResearch/Underdog-Bark-3.0-Plus/blob/d4fab2f8b95681e5ad3cfb4e8c5f4e0c009b3deb/coreml/NOTICE

The source derives from NVIDIA `nvidia/parakeet-tdt-0.6b-v3` and Moondream `moondream/parakeet-ultra`, both CC-BY-4.0; Conway Research post-trained and compressed the weights. No endorsement is implied.

`ArrayArchive.swift` is original MIT-licensed container parsing code. ZIPFoundation is a separately MIT-licensed dependency. Retain the original model LICENSE and NOTICE beside downloaded model assets and this runtime attribution in distributions.

Validation boundary: deterministic synthetic tests cover container decoding, signal processing and decoder edge paths. Whole-model recognition accuracy requires actual model/audio parity fixtures; a compiling target alone is not runtime/model validation. The native FP32 BLAS reduction order can differ from NumPy, so bit-identical intermediate values are not promised.
