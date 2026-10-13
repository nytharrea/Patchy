# Troubleshooting

## `uv sync --locked` fails: lockfile missing or out of date

`uv.lock` does not match `pyproject.toml`. Run **Actions → CI → Run workflow** with **refresh_lock** ticked and merge the pull request it opens.

## CI fails on `ruff format --check` or `ruff check`

Run **Actions → CI → Run workflow** with **autofix** ticked, then merge the pull request. Any rule violation that cannot be fixed automatically is still reported by `check` on that pull request.

## `No pinned signature for <app>`

Expected the first time an app is built. See [Pinning original certificates](getting-started.md#5-pinning-original-certificates).

## `SIGNATURE MISMATCH`

The APK's certificate differs from the pin. Either the app changed its signing key (check the developer's announcement, then update the pin deliberately) or the file did not come from the developer. The build stops either way, on purpose.

## `pins/known.json is not valid JSON (line N, column M)`

The file was edited by hand and is broken, usually a trailing comma or a missing quote. Fix the reported position. Nothing is treated as unpinned and nothing is overwritten while the file is broken.

## `Cloudflare challenge could not be cleared`

APKMirror kept challenging every attempt and FlareSolverr could not clear it. The message names the page and the last HTTP status, and the page is saved under the run's `diagnostics-*` artifact. Re-run the affected build later; running fewer builds at once (`builds` input) helps.

## `Applying 0 patches`

No patch in the selected bundles is compatible with the downloaded version. Pin a compatible version with `force_version` in the build, or wait for the bundle to support the new release. The `Executing command` line of the build log lists the bundle files that were passed to the patcher, and the tag of each bundle is in the plan job's log and in `bundles.json`.

## `No APKMirror release page found for version <version>`

APKMirror has no release page for that version. Patchy already tried the next versions the bundle supports (three at the most), so every one of them is missing, or the version is pinned with `force_version`. Check the app's page on APKMirror, run the build again once the upload is there, or pin another version.

## `None of the N arm64-v8a builds listed on APKMirror has a build code the patch bundle declares`

Patchy asked the patch bundle which build code it was written for and found no such build on the release page, so it fell back to the default variant, which often fails to patch. Common causes: APKMirror has not published that build yet (run the build again later), the bundle declares a build for another architecture than the app's `arch`, or the bundle and the listed release have drifted apart. The build log shows the declared codes and the variants that were considered; `force_build` can pin a different row.

## `The build pinned with force_build is not one the patch bundle declares`

The row selected by `force_build` has a build code the bundle does not declare for that version, so patching may fail. Remove the pin to let Patchy choose the declared build, or update the value. See [How the APKMirror variant is chosen](configuration.md#how-the-apkmirror-variant-is-chosen).

## `Keystore file not found at .../morphe-data/morphe.keystore`

Morphe CLI 1.18.2-dev.1 and 1.18.2-dev.2 check for the patcher's own default keystore before signing and abort when it does not exist, which is always the case on a fresh runner. Patchy starts the patcher with `--unsigned` (the release job signs with your key), so current versions never reach that check. If you still see this message, the workflow is running an older copy of Patchy.

## `No signing credentials for <app>.apk`

The release job has no usable keystore, and the patcher's output is unsigned, so nothing can be published. Set the four `KEYSTORE_*` secrets, see [Getting started](getting-started.md).

## Signing step: `apksigner sign failed`

The message ends with `apksigner`'s own output. The usual causes are a wrong `KEY_ALIAS`, a wrong `KEYSTORE_PASSWORD` or `KEY_PASSWORD`, or a `KEYSTORE_BASE64` value that is not a keystore. Affected apps are left out of the release and listed with this reason in the notification.

## `apksigner was not found`

The runner has no Android SDK build-tools. GitHub-hosted images include them; for other runners install the build-tools and set `ANDROID_HOME`, or set `APKSIGNER` to the binary.

## Release was created without MicroG or PotHelper

Companions are only uploaded when a build listed in their `for_builds` was published in the same run, and only if the companion repositories still ship an asset matching the configured `suffix`. Check `config/companions.yaml` and the `release` job log.

## Uploads fail with a 5xx or a rate-limit answer

Too many assets were being uploaded at the same time. Set `UPLOAD_CONCURRENCY` to a lower number (6 was the previous default) in the `Create release and clean up old releases` step's `env:`. A failed upload fails the run, so run the workflow again.

## Old releases were not removed

Only releases whose tag starts with `build-` are removed, and a failed deletion is logged without failing the run. Check the `release` job log for the exact API response.
