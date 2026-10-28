# Whisper and local model imports

V1.1 is available as source preview `v0.2.0-preview.1`. Build from source;
no signed/notarized app binary is included.

## Recommended models

Download **Whisper small** (about 489 MB) or **Whisper Turbo** (about 630 MB) from
Models. Turbo uses Argmax's compressed Core ML large-v3-turbo export. The displayed
sizes include locally bundled tokenizer files; runtime memory is additional.
Bark remains available for English dictation.

After loading Whisper, use **Language** in Dictation. Auto-detect allows the model
to choose a language; explicit language is useful for short utterances. Common
languages are selectable, including Korean and English; auto detection can cover
other languages supported by the model. Mixed-language accuracy is not guaranteed.
The task is always transcription, never translation.

## Import a compatible folder

Choose **Import local Whisper model…** on Models, then select a complete WhisperKit
multilingual small or large-v3-compatible Core ML export. The folder must contain:

```text
AudioEncoder.mlmodelc/
MelSpectrogram.mlmodelc/
TextDecoder.mlmodelc/
tokenizer.json
tokenizer_config.json
```

Keep the tokenizer matched to the model. Optional config, generation config,
special-token maps and licence files may accompany it. Raw PyTorch/MLX weights,
English-only Whisper exports, executable plugins and Python scripts are unsupported.

The app copies approved files into its own model storage, verifies sizes and hashes,
and loads the copied model to check compatibility before installing it. Imports are
limited to 4 GB and 2,048 files. Links and unexpected files are rejected. Cancel
leaves no partial installation; native Core ML loading may need to finish first.
Your original folder is not modified. Imported models persist across launches and
are rechecked before loading. Imported models keep their original licences.

## Offline behavior

The two catalog downloads include pinned tokenizer files. The runtime directly loads
the local tokenizer with no remote fallback. Missing, corrupt or incompatible files
produce an error instead of a network request. Models are never fetched implicitly
by recognition, and recordings/transcripts are never uploaded.

## Developer smoke test

`DICTATE_TRANSCRIPTION_LANGUAGE` controls the existing local diagnostic CLI only:

```sh
DICTATE_TRANSCRIPTION_LANGUAGE=ko 'dist/Dictate Unlimited.app/Contents/MacOS/DictateUnlimited' \
  --transcribe whisper-small /absolute/model/folder /absolute/korean.wav
```

Use `en`, `ko`, or `auto`. WAV fixtures must be mono 16 kHz floating audio, up to five
minutes. The GUI stores its own language preference. Synthetic local fixture results
are not a substitute for testing human Korean/English speech and app insertion.
