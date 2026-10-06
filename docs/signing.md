# Signing and trust

## Where your key lives

Patch bundles are code. The patcher loads them into its JVM and runs them with the privileges of the process that started it. Patchy therefore splits the work:

| Job | Runs third-party patch code | Has the signing key | Token |
|---|---|---|---|
| `build` | yes | no | read-only |
| `release` | no, only Patchy, `zipalign` and `apksigner` | yes, in the signing step only | read and write |

The `build` job starts the patcher with a minimal environment (`PATH`, `HOME`, `JAVA_HOME` and a few locale and temp variables). Tokens and passwords are not inherited, and the checkout does not keep credentials. The patcher still signs its output with its own throwaway test key; that signature is replaced when the release job re-signs the file.

In the `release` job the keystore is decoded to the runner's temp directory, handed only to the signing step, passed to `apksigner` through environment references (`env:PATCHY_KS_PASSWORD`, never on the command line), and deleted when the step ends.

What this protects: your keystore, its passwords and the write token cannot be read by a compromised bundle. What it does not change: a bundle still controls what ends up inside the patched APK, and that APK is then signed with your key. Only use bundles you trust.

## How APKs are signed

For every built APK the release job:

1. makes sure the newest stable Android build-tools are installed (`sdkmanager`, then falls back to the newest already on the runner),
2. runs `zipalign -f -P 16 4` (16 KB page alignment for native libraries, which also satisfies 4 KB; older build-tools fall back to `-p`),
3. runs `apksigner sign` with your key (v1, v2 and v3 as the manifest allows; no v4 `.idsig`),
4. runs `apksigner verify --print-certs` on the result and logs the certificate SHA-256,
5. warns if the signed APKs do not all share one certificate.

An app whose signing fails is dropped from the release, and the reason appears in the notification. `patchy toolchain` prints which `apksigner` would be used.

## Original certificate pins

`pins/known.json` maps an app slug to the SHA-256 fingerprint of that app's **original** developer certificate. Before patching, the build job runs `apksigner verify --print-certs` on the downloaded APK (unwrapping `.apkm` and `.xapk` bundles to their `base.apk` first). This also checks the APK's integrity, which the previous implementation did not.

| Situation | Result |
|---|---|
| Fingerprint matches a pin | Patching continues |
| No pin for the app | Build stops; the fingerprint goes to `pins/pending.json` through the release job |
| Different fingerprint | Build stops with `SIGNATURE MISMATCH` |
| `pins/known.json` unreadable | Build stops with the file, line and column of the JSON error |

`pins/pending.json` is a review queue and is never trusted. Promote an entry with the Release workflow's `pin` input, or `patchy pin <app>` from a terminal. `SKIP_SIGNATURE_VERIFY=1` bypasses the check and is for local experiments only.

## Verifying a downloaded APK

Every APK in the Releases tab is a modified build, so its signature differs from the Play Store version. Two ways to confirm a file came from your pipeline:

**Artifact attestation (recommended).** The release job attests every signed APK with `actions/attest`. Check it with the [GitHub CLI](https://cli.github.com/):

```bash
gh attestation verify YouTube-<version>.apk --owner <your-github-username-or-org>
```

**Certificate fingerprint.** All APKs in all releases should share one SHA-256 fingerprint, the one of your keystore:

```bash
apksigner verify --print-certs YouTube-<version>.apk
```

Note it down after your first run. This is a different value from the pins in `pins/known.json`, which describe the original, pre-patch certificates.

Because the key is yours, Android will refuse to update an installed app that was signed with a different key. If you ever change keystores, users must uninstall the old APK first.
