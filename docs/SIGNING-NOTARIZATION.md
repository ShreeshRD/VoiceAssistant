# Signing and notarization

This source preview does not include a signed, notarized app download. The normal
build script produces an ad-hoc-signed app for local development. Rebuilding can
invalidate effective Accessibility permission even when its switch remains on.

## Future binary distribution prerequisites

A binary release needs a suitable Apple Developer team, a Developer ID Application
certificate with its matching private key, and authorized notarization credentials.
Keep secrets in a local keychain, never Git, scripts, issues, or logs. Consult the
[Apple notarization documentation](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
for the distribution workflow applicable to your toolchain and account.

`Resources/Distribution.entitlements.plist` contains only Hardened Runtime audio
input. Accessibility is separately granted by the user; insertion uses no Apple Events.

## Local hardened check

```sh
./scripts/prepare-hardened-check.sh \
  'dist/Dictate Unlimited.app' '/absolute/new/path/Dictate Hardened Check.app'
```

The helper refuses an existing output and creates a separate ad-hoc Hardened Runtime
copy. It does not contact a timestamp service, use Developer ID credentials, or
submit anything. This output is **not notarized**. A prior local hardened copy passed
signature/resource checks and offline inference for all three Bark models; that does not
prove final signed GUI behavior or Apple acceptance.

Before a binary release, verify the exact signed artifact, successful notarization,
stapled ticket, Gatekeeper assessment, and a normal clean downloaded installation.
Test microphone permission, Accessibility delivery, and model loading under that
final signature. Do not treat a valid `codesign` result as notarization success.
