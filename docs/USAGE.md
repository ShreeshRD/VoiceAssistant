# Using Dictate Unlimited

## Use

1. On first use, open Models, download a Bark model for English or Whisper small/Turbo for multilingual dictation, then Load it. Later launches automatically validate and load your last selected installed model. First load can
   take minutes while Core ML compiles. Base/Plus prepare the short encoder first and prepare the long encoder
   only when needed. Warm caches are reused; see docs/TESTING.md for coverage and the remaining first-use delay. Switching releases the previous runtime.
2. In Dictation, check **Microphone readiness**, choose System default or a specific
   input, and run the five-second microphone test. It discards audio without
   transcription. Accessibility is required for automatic insertion; readiness shows
   whether this build has access. Input selection does not change the system default.
3. Use **Control+Option+Space** by default. Shortcuts can be changed using Control or
   Option plus a key. Choose tap-to-start/finish or hold-to-talk; release finishes a
   hold session. Modifier-only/FN bindings are not supported in this preview. Settings
   reject duplicate dictation/recovery bindings and report registration failures.
4. **Control+Command+V** pastes the last completed dictation into your current field
   when you release the shortcut. It does not recognize speech again or press Enter.
   The result exists only in memory; Clear last dictation or Quit removes it. Cancelled
   attempts never become recovery results. The previous completed result may remain.
5. In **Dictionary**, add explicit “heard → replacement” corrections. They match
   whole words/phrases case-insensitively, prefer longer phrases, and never cascade
   through replacement text. Add, edit, remove and undo are local. Up to 500 entries,
   120 characters per field; no automatic learning, Contacts access or extra model.
6. If insertion cannot be verified, inspect the target before using Copy or recovery.
   The app never automatically presses Enter or retries an ambiguous insertion.

Cancel discards captured audio or suppresses a pending recognition result. An
in-flight Core ML prediction must finish before its memory can be released.
Sleep, user-session switching, or interrupted microphone input discards an active recording and suppresses pending insertion. Recording never resumes automatically.
All supported text fields use guarded clipboard paste automatically; no compatibility
switch is required. The target must still expose readable text
and selection through Accessibility. After verified delivery, the previous clipboard
is restored only if nothing else changed it. If paste cannot be verified, dictated
text remains on the clipboard so a delayed paste cannot insert your old clipboard
instead. Clipboard managers may retain that text. No Enter key is sent and no
uncertain insertion is automatically retried. Cancellation is unavailable during
the brief final delivery once a write is being dispatched.
Session text stays in memory until cleared or the app exits. The app creates no
recording/transcript history. Explicit corrections persist in Application Support/DOO MADE/
Dictate Unlimited/Corrections.json; shortcut and microphone preferences are local. Explicit Copy replaces the clipboard contents.

## Models and network boundary

`Sources/DictateCore/Resources/models.json` pins model revisions, file sizes and
large-file SHA-256 hashes. Downloads use Hugging Face HTTPS and signed CDN redirects;
no audio or transcript is part of those requests. There are no automatic updates.
Core ML executes from local files after installation. Model compilation caches live
beside the verified model artifacts in Application Support/DOO MADE/Dictate Unlimited.

The original 163/180 MB MLX and 1.25 GB BF16 artifacts are not the Core ML exports.
Actual displayed downloads are approximately 202 MB, 206 MB and 1.23 GB. Pro uses
FP16 Core ML weights. Runtime/accuracy equivalence to original benchmark paths is
not claimed. Bark models are English-only; they transcribe fillers rather than
performing cloud cleanup.


## Accessibility after a rebuild

If System Settings shows access enabled but the app says **Text insertion access: Missing**, remove the old Dictate Unlimited entry in System Settings → Privacy & Security → Accessibility, then add the exact app you are running again. Click **Refresh inputs**. Confirm **Ready** before retrying. Local ad-hoc builds can lose effective permission after rebuilding. Keep one app copy in a stable location.

Your completed text remains in the app until Clear or Quit. Once access is restored, focus your writing field and use paste-last recovery. Always inspect an uncertain delivery before retrying to avoid duplicate text.

The app lives in the menu bar. Closing Settings does not quit it. Open the app again or choose Settings from the microphone menu. The floating feedback view hides when dictation finishes.

## Languages and imported models

Load Whisper small or Turbo to enable the Language selector. Choose Auto-detect or
a listed language, including Korean and Japanese. Transcription keeps the spoken
language; translation is disabled. Mixed-language results vary, especially with small.
Use Models → Import local Whisper model for a compatible offline folder. See
[Whisper and local imports](WHISPER.md) for the exact folder requirements and limits.
