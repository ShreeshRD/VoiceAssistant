# Licensing and provenance

This preview has multiple licences. `LICENSE` applies to original DOO MADE code;
it does not replace third-party licences. No model weights are redistributed.

| Component | Scope / pinned source | Licence and retained notice |
| --- | --- | --- |
| Original application and tests | DictateUnlimited, DictateCore, original archive parser and project tooling | MIT, root LICENSE |
| Adapted Bark runtime | Frontend.swift, Decoder.swift and SmallBarkRecognizer.swift | CC BY 4.0; Sources/BarkSmall/ATTRIBUTION.md and Resources/Notices/Bark-CC-BY-4.0.txt |
| Optional Bark weights | Three immutable revisions in Sources/DictateCore/Resources/models.json | CC BY 4.0; packaged family notices and runtime attribution; Pro also downloads LICENSE/NOTICE |
| FluidAudio | a00964e1aa8eff99c4bce80bc9c8ff2d4dd1568d | Apache-2.0; Resources/Notices/FluidAudio-LICENSE.txt |
| FluidAudio third-party implementations | Notices from the same pinned checkout | Resources/Notices/FluidAudio-ThirdParty; includes fastcluster BSD-2-Clause and VBx Apache-2.0 |
| WhisperKit / ArgmaxCore | 1bbc57cb7fe6410248a685b1c5a3c6d56adc2ed4 | MIT and retained third-party notices, Resources/Notices/WhisperKit-* |
| Whisper models/tokenizers | Pinned Whisper catalog | MIT, OpenAI/Argmax; no weights redistributed |
| ZIPFoundation | 0.9.19, revision 02b6abe5f6eef7e3cbd5f247c5cc24e246efcfe0 | MIT; Resources/Notices/ZIPFoundation-LICENSE.txt |

Retain notices and adaptation credits in source and binary distributions. The app
build copies these notices and the BarkSmall attribution into its resources.
FluidAudio's separate LuxTTS lexicon and auxiliary data are excluded from packaging;
they are not needed for dictation and their upstream notice lists GPL/CC-BY-SA inputs.
The optional NeMo binary target is disabled by the Swift 6.2 dependency traits.
No inference models, source-app assets or source-app code are included in this preview.

This inventory was checked against locally available pinned files, not current web
pages. The existing FluidAudio licence file was already Apache-2.0; the earlier prose
calling it MIT was incorrect and has been corrected. This is a technical provenance
inventory, not legal sign-off. Review this scope again if dependencies, weights,
packaged resources or adapted code change. Do not describe the whole distribution
as exclusively MIT or imply endorsement by model/dependency authors.

Base/Plus manifests select only the encoder/runtime artifact subdirectory and do not
download separate LICENSE/NOTICE files. Their family notices and pinned source links
are retained in the app and source preview. If distributing model folders separately,
include the applicable original licence and attribution with those folders.
